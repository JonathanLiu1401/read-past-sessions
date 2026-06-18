#!/usr/bin/env python3
"""
read-past-sessions engine
==========================
Find and read past Claude Code session transcripts so a new chat can be
"forked" off a previous one.

Claude Code stores every session as a JSONL file at:
    <config>/projects/<path-encoded-cwd>/<session-uuid>.jsonl
where <config> is $CLAUDE_CONFIG_DIR or ~/.claude. Each line is one JSON
object with a "type" (user / assistant / system / ai-title / last-prompt / ...).

Why this script exists instead of just reading the files:
  * Files get huge (tens of MB) -- reading them raw blows the context window.
  * Sessions are TREES, not lists. When you rewind/edit a prompt, the old
    branch stays in the file. The live conversation is the chain you get by
    walking parentUuid back from the latest "last-prompt" leaf. Naive
    file-order reading mixes in hundreds of abandoned, dead turns.
  * What you want (file paths, commands, decisions) lives in tool calls, not
    just prose -- so search has to index tool_use inputs and outputs too.

Subcommands:
    list    [PROJECT] [--limit N]            recent sessions, newest first
    search  QUERY [--project P] [--limit N]  find sessions by content/title
    show    SESSION [--mode MODE] [...]       condensed transcript of one session

Run with no args for help.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

# Transcripts contain arbitrary Unicode (paths, prose, symbols). On Windows the
# console defaults to cp1252 and would crash on the first non-Latin char, so
# force UTF-8 output and never let an unencodable character abort a briefing.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# --------------------------------------------------------------------------
# Locating session files
# --------------------------------------------------------------------------
def base_dir():
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    root = Path(cfg) if cfg else (Path.home() / ".claude")
    return root / "projects"


def session_files():
    """All top-level *.jsonl session files. project.glob('*.jsonl') matches
    only direct children, so subfolders like memory/ are skipped."""
    base = base_dir()
    out = []
    if not base.exists():
        return out
    for proj in base.iterdir():
        if proj.is_dir():
            out.extend(proj.glob("*.jsonl"))
    return out


def mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


# --------------------------------------------------------------------------
# Text normalization for fuzzy matching
# --------------------------------------------------------------------------
_SEP = re.compile(r"[-_/\\.\s]+")


def norm(s):
    """Lowercase and collapse separators (-, _, /, \\, ., whitespace) to single
    spaces, so 'bms-driver-schematic1' matches 'bms_driver schematic1' and
    'BMS/Driver/Schematic1' alike."""
    return _SEP.sub(" ", str(s).lower()).strip()


# --------------------------------------------------------------------------
# Streaming JSONL reader
# --------------------------------------------------------------------------
def iter_lines(path):
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


# --------------------------------------------------------------------------
# Content extraction
# --------------------------------------------------------------------------
def format_tool(block):
    """Turn a tool_use block into a one-line action like 'Edit foo.py' or
    'Bash: npm test'. Artifact names (file paths) live here."""
    name = block.get("name", "tool")
    inp = block.get("input") or {}

    def g(*keys):
        for k in keys:
            v = inp.get(k)
            if v:
                return str(v)
        return ""

    if name in ("Edit", "Write", "Read", "NotebookEdit", "MultiEdit"):
        arg = g("file_path", "notebook_path", "path")
    elif name == "Bash":
        arg = g("command")
    elif name in ("Grep", "Glob"):
        arg = g("pattern")
        loc = g("path", "glob")
        if loc:
            arg += " in " + loc
    elif name in ("Task", "Agent"):
        arg = g("description", "prompt")
    elif name == "Skill":
        arg = g("skill", "command")
    elif name in ("WebFetch", "WebSearch"):
        arg = g("url", "query")
    elif name == "TodoWrite":
        arg = "(todo update)"
    else:
        arg = ""
        for k, v in inp.items():
            if isinstance(v, str) and v:
                arg = f"{k}={v}"
                break
    arg = " ".join(arg.split())  # collapse newlines/space
    if len(arg) > 160:
        arg = arg[:157] + "..."
    return f"{name}: {arg}" if arg else name


def extract(content):
    """Return (visible_text, actions) for rendering a turn.
    visible_text = user prose / assistant prose. actions = tool_use one-liners.
    thinking blocks and tool_result blobs are dropped from the briefing."""
    if content is None:
        return "", []
    if isinstance(content, str):
        return content, []
    texts, actions = [], []
    for b in content:
        if not isinstance(b, dict):
            texts.append(str(b))
            continue
        t = b.get("type")
        if t == "text":
            texts.append(b.get("text", ""))
        elif t == "tool_use":
            actions.append(format_tool(b))
        # thinking / tool_result / image -> skipped for the briefing
    return "\n".join(x for x in texts if x).strip(), actions


def searchable(o):
    """Comprehensive, readable text for one message used by `search`. Includes
    prose, thinking, tool_use inputs (file paths!), and tool_result output, so
    an artifact named only inside a tool call is still findable."""
    m = o.get("message")
    if not isinstance(m, dict):
        return ""
    c = m.get("content")
    if isinstance(c, str):
        return c
    if not isinstance(c, list):
        return ""
    parts = []
    for b in c:
        if not isinstance(b, dict):
            parts.append(str(b))
            continue
        t = b.get("type")
        if t == "text":
            parts.append(b.get("text", ""))
        elif t == "thinking":
            parts.append(b.get("thinking", ""))
        elif t == "tool_use":
            parts.append(b.get("name", ""))
            inp = b.get("input")
            if isinstance(inp, dict):
                for v in inp.values():
                    if isinstance(v, str):
                        parts.append(v)
                    else:
                        parts.append(json.dumps(v))
        elif t == "tool_result":
            rc = b.get("content")
            if isinstance(rc, str):
                parts.append(rc[:3000])
            elif isinstance(rc, list):
                for rb in rc:
                    if isinstance(rb, dict) and rb.get("type") == "text":
                        parts.append(rb.get("text", "")[:3000])
    return "\n".join(p for p in parts if p)


SYSTEM_PREFIXES = ("<system-reminder", "<command-", "Caveat:", "[Request interrupted")


def is_real_prompt(text):
    """True if a user string looks like something the human actually typed
    (not a tool_result echo, system reminder, or command wrapper)."""
    t = text.strip()
    if not t:
        return False
    return not t.startswith(SYSTEM_PREFIXES)


# --------------------------------------------------------------------------
# Session scan
# --------------------------------------------------------------------------
def scan(path, full=False):
    """One pass over a session file.
    Always collects metadata + parent/type maps (cheap, for live-branch size).
    With full=True also keeps the entries themselves (for rendering)."""
    parent = {}        # uuid -> parentUuid
    kind = {}          # uuid -> 'user'/'assistant'/...
    ts_map = {}        # uuid -> timestamp (user/assistant only)
    entries = {} if full else None
    leaf = None
    ai_titles = []
    custom_title = None
    cwd = git = version = None
    ts_first = ts_last = None
    nuser = nasst = nside = 0
    first_prompt = None

    for o in iter_lines(path):
        t = o.get("type")
        if t == "last-prompt":
            leaf = o.get("leafUuid") or leaf
            continue
        if t == "ai-title":
            at = o.get("aiTitle") or o.get("title")
            if at:
                ai_titles.append(at)
            continue
        if t == "custom-title":
            custom_title = (o.get("customTitle") or o.get("title")
                            or o.get("content") or custom_title)
            continue
        u = o.get("uuid")
        if u:
            parent[u] = o.get("parentUuid")
            kind[u] = t
            if full:
                entries[u] = o
        if t in ("user", "assistant"):
            ts = o.get("timestamp")
            if ts:
                ts_first = ts_first or ts
                ts_last = ts
                if u:
                    ts_map[u] = ts
            cwd = cwd or o.get("cwd")
            git = git or o.get("gitBranch")
            version = version or o.get("version")
            if t == "user":
                nuser += 1
                if first_prompt is None:
                    msg = o.get("message")
                    txt, _ = extract(msg.get("content") if isinstance(msg, dict) else None)
                    if is_real_prompt(txt):
                        first_prompt = txt.strip()
            else:
                nasst += 1
            if o.get("isSidechain"):
                nside += 1

    return dict(
        path=str(path), parent=parent, kind=kind, ts_map=ts_map,
        entries=entries, leaf=leaf,
        ai_titles=ai_titles, custom_title=custom_title, cwd=cwd, git=git,
        version=version, ts_first=ts_first, ts_last=ts_last,
        nuser=nuser, nasst=nasst, nside=nside, first_prompt=first_prompt,
        session_id=Path(path).stem, mtime=mtime(path),
    )


def live_branch(meta):
    """UUIDs of the live conversation, chronological order, by walking
    parentUuid back from the leaf and reversing."""
    parent, leaf = meta["parent"], meta["leaf"]
    seq, cur, seen = [], leaf, set()
    while cur and cur in parent and cur not in seen:
        seen.add(cur)
        seq.append(cur)
        cur = parent[cur]
    seq.reverse()
    return seq


def branch_counts(meta):
    """(live_user, live_asst) reachable from leaf."""
    lu = la = 0
    for u in live_branch(meta):
        k = meta["kind"].get(u)
        if k == "user":
            lu += 1
        elif k == "assistant":
            la += 1
    return lu, la


def branch_span(meta):
    """(first_ts, last_ts) of the LIVE branch's real turns. Using the live
    branch -- not global file order -- avoids reporting a misleading end time:
    session-rename reminders and rewound turns sit off-branch with later
    timestamps and would otherwise overstate when the conversation ended.
    Falls back to the global span if the branch carries no timestamps."""
    tss = [meta["ts_map"][u] for u in live_branch(meta) if u in meta["ts_map"]]
    if not tss:
        return meta["ts_first"], meta["ts_last"]
    return tss[0], tss[-1]


def title_of(meta):
    if meta["custom_title"]:
        return str(meta["custom_title"]).strip()
    if meta["ai_titles"]:
        return str(meta["ai_titles"][-1]).strip()  # last = most current
    if meta["first_prompt"]:
        return "(untitled) " + meta["first_prompt"][:60].replace("\n", " ")
    return "(untitled, no prompt)"


def project_label(meta, path):
    """Prefer the real cwd recorded inside the session; fall back to the
    path-encoded folder name."""
    return meta.get("cwd") or Path(path).parent.name


# --------------------------------------------------------------------------
# Project filtering
# --------------------------------------------------------------------------
def match_project(path, query):
    """True if query (separator-insensitive) is a substring of either the
    encoded folder name or the decoded-ish form."""
    if not query:
        return True
    qn = norm(query)
    folder = path.parent.name
    return qn in norm(folder)


def filter_files(files, project):
    return [f for f in files if match_project(f, project)]


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def _fmt_time(ts):
    if not ts:
        return "?"
    return str(ts).replace("T", " ")[:16]


def cmd_list(args):
    files = filter_files(session_files(), args.project)
    files.sort(key=mtime, reverse=True)
    shown = files[: max(1, args.limit)]
    if not shown:
        where = f" matching project '{args.project}'" if args.project else ""
        print(f"No sessions found{where}.")
        if args.project:
            print("Tip: run `list` with no project to see everything, then copy the project label.")
        return
    print(f"{len(shown)} most-recent session(s)"
          + (f" in projects matching '{args.project}'" if args.project else "")
          + f" (of {len(files)} matched):\n")
    for f in shown:
        m = scan(f)
        lu, la = branch_counts(m)
        total = m["nuser"] + m["nasst"]
        live = lu + la
        flag = ""
        if total and live < total * 0.6:
            flag = f"  [!{total - live} off-branch msgs]"
        side = f"  [{m['nside']} subagent]" if m["nside"] else ""
        last_ts = branch_span(m)[1]
        print(f"* {title_of(m)}")
        print(f"    id={m['session_id']}  last={_fmt_time(last_ts)}"
              f"  msgs={total} (live {live}){flag}{side}")
        print(f"    project: {project_label(m, f)}")
        print()


def _snippet(text, query, tokens, width=200):
    low = text.lower()
    idx = low.find(query.lower())
    if idx < 0:
        for tok in tokens:
            idx = low.find(tok)
            if idx >= 0:
                break
    if idx < 0:
        idx = 0
    start = max(0, idx - width // 3)
    seg = text[start:start + width]
    seg = " ".join(seg.split())
    return ("..." if start else "") + seg + "..."


def cmd_search(args):
    files = filter_files(session_files(), args.project)
    files.sort(key=mtime, reverse=True)
    qn = norm(args.query)
    tokens = [t for t in qn.split() if t]
    if not tokens:
        print("Empty query.")
        return

    results = []
    for f in files:
        phrase_hits = 0          # messages containing the whole query
        all_token_hits = 0       # messages containing every token
        covered = set()          # tokens seen anywhere in the session
        best_text = None
        m = None
        for o in iter_lines(f):
            if o.get("type") not in ("user", "assistant"):
                continue
            raw = searchable(o)
            if not raw:
                continue
            tn = norm(raw)
            if qn and qn in tn:
                phrase_hits += 1
                if best_text is None:
                    best_text = raw
            present = [t for t in tokens if t in tn]
            if present:
                covered.update(present)
                if len(present) == len(tokens):
                    all_token_hits += 1
                    if best_text is None:
                        best_text = raw
        if not covered:
            continue
        score = (phrase_hits * 1000
                 + all_token_hits * 100
                 + len(covered) * 10
                 + (50 if len(covered) == len(tokens) else 0))
        m = scan(f)
        results.append((score, phrase_hits, all_token_hits, len(covered),
                        f, m, best_text))

    if not results:
        where = f" in projects matching '{args.project}'" if args.project else ""
        print(f"No sessions matched '{args.query}'{where}.")
        print("Try fewer/different keywords, or drop --project to widen the search.")
        return

    results.sort(key=lambda r: (r[0], mtime(r[4])), reverse=True)
    limit = max(1, args.limit)
    shown_n = min(limit, len(results))
    print(f"Search '{args.query}' -> {len(results)} session(s) matched, showing {shown_n}:\n")
    for rank, (score, ph, at, cov, f, m, best) in enumerate(results[:limit], 1):
        why = []
        if ph:
            why.append(f"{ph} exact-phrase hit(s)")
        if at and not ph:
            why.append(f"{at} all-token hit(s)")
        why.append(f"{cov}/{len(tokens)} keyword(s)")
        print(f"{rank}. {title_of(m)}")
        print(f"    id={m['session_id']}  last={_fmt_time(branch_span(m)[1])}"
              f"  score={score}  ({', '.join(why)})")
        print(f"    project: {project_label(m, f)}")
        if best:
            print(f"    > {_snippet(best, args.query, tokens)}")
        print()
    print("Read one with:  python sessions.py show <id>")


def _resolve(session):
    """Return the list of files matching a session id / partial id / path.
    A full path resolves uniquely; an id may legitimately match more than one
    file (the same uuid can exist in two projects, and partial ids collide), so
    the caller decides what to do with multiple matches rather than us silently
    guessing."""
    p = Path(session)
    if p.exists() and p.is_file():
        return [p]
    cands = [f for f in session_files() if f.stem == session]
    if not cands:
        cands = [f for f in session_files() if session.lower() in f.stem.lower()]
    cands.sort(key=mtime, reverse=True)
    return cands


def _trunc(text, n):
    text = text.rstrip()
    if len(text) <= n:
        return text
    return text[:n].rstrip() + f" ...[+{len(text) - n} chars]"


def _fit(blocks, budget):
    """Fit rendered turn-blocks into budget. If they don't fit, keep the HEAD
    (the original goal) and the TAIL (where the session left off -- the part a
    fork needs most) and elide the middle, with a visible notice. Returns
    (text, truncated_bool). Rendering from the start and silently cutting the
    tail would drop exactly the most recent state, so we never do that."""
    total = sum(len(b) for b in blocks)
    if total <= budget:
        return "".join(blocks), False
    head_budget = int(budget * 0.35)
    head, hlen, hi = [], 0, 0
    for i, b in enumerate(blocks):
        if head and hlen + len(b) > head_budget:
            hi = i
            break
        head.append(b)
        hlen += len(b)
        hi = i + 1
    tail_budget = budget - hlen
    tail, tlen, ti = [], 0, len(blocks)
    for j in range(len(blocks) - 1, hi - 1, -1):
        b = blocks[j]
        if tail and tlen + len(b) > tail_budget:
            ti = j + 1
            break
        tail.insert(0, b)
        tlen += len(b)
        ti = j
    omitted = ti - hi
    parts = list(head)
    if omitted > 0:
        parts.append(f"\n... [omitted {omitted} middle turn(s) to fit] ...\n\n")
    parts.extend(tail)
    # Only report truncation when a turn was actually elided. head+tail can
    # absorb every block (head and tail each always keep at least their first
    # block), in which case nothing was cut and the notice would be a lie.
    return "".join(parts), omitted > 0


def cmd_show(args):
    cands = _resolve(args.session)
    if not cands:
        print(f"No session matching '{args.session}'. Use `list` or `search` to find an id.")
        return
    if len(cands) > 1:
        print(f"'{args.session}' matches {len(cands)} sessions. Re-run `show` with the "
              f"full file path (or a longer/exact id) to pick one:")
        for c in cands[:20]:
            print(f"  {c}")
        if len(cands) > 20:
            print(f"  ...(+{len(cands) - 20} more)")
        return
    f = cands[0]
    m = scan(f, full=True)
    lu, la = branch_counts(m)
    total = m["nuser"] + m["nasst"]
    live = lu + la

    if args.all_branches:
        seq = [u for u in m["kind"] if m["kind"][u] in ("user", "assistant")]
        # file order is preserved by dict insertion
    else:
        seq = live_branch(m)
        if not seq:  # no leaf / broken chain -> fall back so we show *something*
            seq = [u for u in m["kind"] if m["kind"][u] in ("user", "assistant")]

    # Header
    print("=" * 70)
    print(f"SESSION: {title_of(m)}")
    print(f"  id        : {m['session_id']}")
    print(f"  project   : {project_label(m, f)}")
    if m["git"]:
        print(f"  git branch: {m['git']}")
    span_first, span_last = branch_span(m)
    print(f"  activity  : {_fmt_time(span_first)}  ->  {_fmt_time(span_last)}")
    if args.all_branches:
        print(f"  messages  : {total} total -- showing ALL branches in file order "
              f"(live branch is {live})")
    else:
        print(f"  messages  : {total} total | {live} on live branch", end="")
        if total and live < total:
            print(f" | {total - live} off the live branch (rewound, pre-compaction, or "
                  f"subagent; hidden -- --all-branches to see)")
        else:
            print()
    if m["nside"]:
        print(f"  subagents : {m['nside']} sidechain msgs "
              + ("(shown)" if args.include_subagents else "(hidden; --include-subagents)"))
    print("=" * 70)
    print()

    mode = args.mode
    # (user_text_cap, assistant_text_cap) per mode. 'full' is effectively
    # untruncated; 'prompts' drops assistant turns entirely.
    caps = {"briefing": (2000, 1200), "full": (10**8, 10**8), "prompts": (2000, 0)}
    user_cap, asst_cap = caps.get(mode, caps["briefing"])
    budget = max(args.max_chars, 10**8) if mode == "full" else args.max_chars

    files_touched = []
    commands = []
    blocks = []

    for u in seq:
        o = m["entries"].get(u)
        if not o:
            continue
        if o.get("isSidechain") and not args.include_subagents:
            continue
        role = o.get("type")
        msg = o.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        text, actions = extract(content)

        # collect a high-level action summary regardless of what text is rendered
        for a in actions:
            if a.startswith(("Edit:", "Write:", "MultiEdit:", "NotebookEdit:")):
                files_touched.append(a.split(":", 1)[1].strip())
            elif a.startswith("Bash:"):
                commands.append(a.split(":", 1)[1].strip())

        if role == "user":
            if o.get("isCompactSummary"):
                blocks.append("### [COMPACTION SUMMARY]\n" + _trunc(text, 4000) + "\n\n")
            elif is_real_prompt(text):  # skip tool_result echoes / system reminders
                blocks.append("### YOU\n" + _trunc(text, user_cap) + "\n\n")
        elif role == "assistant":
            if mode == "prompts":
                continue
            parts = []
            if text:
                parts.append("### CLAUDE\n" + _trunc(text, asst_cap) + "\n")
            if actions:
                parts.append("    - " + "\n    - ".join(actions[:40]) + "\n")
                if len(actions) > 40:
                    parts.append(f"    - ...(+{len(actions) - 40} more actions)\n")
            if parts:
                blocks.append("".join(parts) + "\n")

    if not blocks:
        print("(No renderable turns on this branch -- try --all-branches.)")
    else:
        body, truncated = _fit(blocks, budget)
        sys.stdout.write(body)
        if truncated:
            sys.stdout.write(
                f"\n[Briefing exceeded --max-chars {budget}: kept the start and the most "
                f"recent turns, elided the middle. Raise --max-chars or use `search` to "
                f"read the elided span.]\n")

    # Action summary footer -- file/command coverage across the WHOLE branch,
    # unaffected by any text elision above (this is what a fork most needs).
    if mode != "prompts" and (files_touched or commands):
        print("\n" + "-" * 70)
        print("ACTION SUMMARY")
        if files_touched:
            uniq = list(dict.fromkeys(files_touched))
            print(f"  files written/edited ({len(uniq)}):")
            for x in uniq[:40]:
                print(f"    - {x}")
            if len(uniq) > 40:
                print(f"    ...(+{len(uniq) - 40} more)")
        if commands:
            print(f"  shell commands run: {len(commands)}")


# --------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="sessions.py",
        description="Find and read past Claude Code session transcripts.")
    sub = p.add_subparsers(dest="cmd")

    pl = sub.add_parser("list", help="recent sessions, newest first")
    pl.add_argument("project", nargs="?", default=None,
                    help="optional project filter (substring of cwd/folder)")
    pl.add_argument("--limit", type=int, default=15)
    pl.set_defaults(func=cmd_list)

    ps = sub.add_parser("search", help="find sessions by content/title")
    ps.add_argument("query")
    ps.add_argument("--project", default=None)
    ps.add_argument("--limit", type=int, default=10)
    ps.set_defaults(func=cmd_search)

    ph = sub.add_parser("show", help="condensed transcript of one session")
    ph.add_argument("session", help="session id, partial id, or file path")
    ph.add_argument("--mode", choices=["briefing", "full", "prompts"],
                    default="briefing")
    ph.add_argument("--all-branches", action="store_true",
                    help="include abandoned/rewound turns (file order)")
    ph.add_argument("--include-subagents", action="store_true")
    ph.add_argument("--max-chars", type=int, default=60000)
    ph.set_defaults(func=cmd_show)
    return p


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
