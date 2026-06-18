---
name: read-past-sessions
description: >-
  Find and read PAST Claude Code sessions (the conversation transcripts stored
  on disk) and turn one into a context briefing for the current chat. Use this
  WHENEVER the user wants to fork off, continue, resume, or pick up from a
  previous Claude Code session or chat; remember/recall what was done in an
  earlier session; "read through the X chat", "what did we decide in that other
  session", "go look at my previous conversation about Y", "continue where the
  last session left off", or find which old session touched a particular file,
  topic, or artifact. Also use proactively when you need context that clearly
  lives in an earlier session rather than the current one. Do NOT use it to
  read normal project source files — only Claude Code's own session history.
---

# Reading Past Claude Code Sessions

## What this is for

Claude Code records every session as a JSONL transcript on disk. When the user
wants to start a new chat that **forks off** an earlier one — "read through the
bms-driver-schematic chat and continue from it" — you need to locate the right
transcript, understand what happened, and brief the current chat so it can pick
up the work. This skill does that without you reinventing the wheel (globbing,
grepping, and writing throwaway digest scripts) every time.

The work is done by a bundled engine, `scripts/sessions.py`. Always use it
rather than reading raw `.jsonl` files: transcripts are routinely tens of MB
and will blow your context, and they are conversation **trees** — a single file
mixes the live conversation with abandoned/rewound branches, which the engine
untangles for you.

## The engine

Run with the Python on the machine (`python` or `python3`; no third-party deps):

```
python <skill_dir>/scripts/sessions.py <command> ...
```

Three commands:

| Command | Purpose |
|---|---|
| `list [PROJECT] [--limit N]` | Recent sessions, newest first. `PROJECT` is an optional case-/separator-insensitive substring of the working directory (e.g. `Trellis`, `EE331`). |
| `search QUERY [--project P] [--limit N]` | Find sessions by content. Searches prose **and tool calls** (file paths, commands) **and tool output** — so an artifact named only inside an `Edit`/`Bash`/`Glob` call is still found. Token- and separator-normalized, ranked by relevance. |
| `show SESSION [--mode briefing\|full\|prompts] [--all-branches] [--include-subagents] [--max-chars N]` | Condensed transcript of one session. `SESSION` is a session id, a partial id, or a file path. |

## Workflow

Create a todo per step if the task is non-trivial.

**1 — Identify the session.** Pick the path of least resistance:
- The user gave a session id or file path → go straight to `show`.
- The user named a project / it's "the recent one" → `list <project>` and read the titles.
- The user described a topic, file, or artifact (the common case, since many
  sessions are auto-titled poorly or not at all) → `search "<their words>" --project <project>`.
  Lead with the distinctive noun (a filename, a part number, a feature name);
  the engine handles hyphens/underscores/case for you.

If several candidates look plausible, show the user the top few from `list`/
`search` (title, id, last-active, project) and confirm which one — don't guess
silently when it's ambiguous. A session that is `(untitled)` or whose title is
just a path is normal; rank by the search score and recency, not the title.

**2 — Read it.** `python sessions.py show <id>`. The default `briefing` mode
reconstructs the **live branch** (the conversation that actually led to where
the session ended), renders it chronologically as YOU / CLAUDE turns with a
one-line action per tool call, and ends with an ACTION SUMMARY of files
edited and commands run. The header tells you how many messages were on
abandoned/rewound branches (hidden by default) and whether subagents ran.
- If the live branch looks suspiciously short versus the total (e.g. the
  session was compacted or heavily rewound), rerun with `--all-branches` to see
  everything in file order.
- For a huge session, raise `--max-chars` or first `search` within it to find
  the relevant span, then read around it.

**3 — Brief the current chat.** Synthesize what you read into a tight briefing
for the user, covering: what that session was trying to do, the key decisions
and their rationale, the concrete artifacts/files it produced or changed, and
**where it left off / what the obvious next step is**. This is the "fork point"
— after this, the current chat is primed to continue the work.

**4 — Offer to persist (only if useful).** Don't auto-save. If the briefing is
something the user will want again, offer to write it to a file in the current
project (e.g. `SESSION-BRIEFING.md`) or to save a durable note in memory. Wait
for them to ask.

## Examples

**Fork off a named-by-topic session (titles unreliable):**
```
search "bms-driver-schematic1" --project Trellis     # find candidates
show 2eb4d213                                         # read the winner
```
then brief the user and continue from where it left off.

**"Continue my most recent EE331 session":**
```
list EE331 --limit 5      # newest first; pick the top one
show <id>
```

**"Which session was it where I set up the GitHub Actions deploy?":**
```
search "github actions deploy"   # no --project: searches every project
```

## Notes on the data model (why the engine works the way it does)

- **Location:** `$CLAUDE_CONFIG_DIR/projects/` or `~/.claude/projects/`, one
  subfolder per working directory (path-encoded), one `.jsonl` per session.
- **Live branch:** the engine walks `parentUuid` back from the latest
  `last-prompt` leaf to get the real conversation; rewound/edited turns stay in
  the file but are excluded from the briefing (and counted in the header).
- **Search recall:** indexing tool-call inputs/outputs is deliberate — artifact
  names (filenames, part numbers) usually appear in tool calls, not prose, and
  many sessions have no useful title. That's why content search beats title
  matching for finding the right past session.
- **Titles:** resolved as user-set custom title → latest AI title → first real
  prompt. Treat them as hints, not identity.
