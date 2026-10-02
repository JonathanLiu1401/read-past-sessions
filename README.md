# read-past-sessions

A cross-agent skill for finding and reading past session transcripts across
**Claude Code**, **Grok**, **Cursor IDE / cursor-agent CLI**, **Antigravity (agy)**,
**clx**, **clg**, **clc**, and **cld**, turning them into concise context briefings for the
current chat.

Use it when you want to fork off, continue, resume, or pick up from a previous
session; recall what was decided in an earlier chat; or find which old session
touched a particular file, topic, or artifact.

It can also search curated durable memory files and build a local
Graphify-compatible memory graph, so project knowledge can be shared between
agent sessions without rereading raw transcript JSONL files.

## Supported session stores

| Store | Flag | Location | Description |
|---|---|---|---|
| **Claude Code** | `--source claude` | `~/.claude/projects/<cwd>/*.jsonl` | Direct Claude Code sessions |
| **CLX** | `--source clx` | `~/.claude-clx/projects/<cwd>/*.jsonl` | Claude Code on Grok via CLIProxyAPI |
| **CLG** | `--source clg` | `~/.claude-clg/projects/<cwd>/*.jsonl` | Claude Code on Gemini via CLIProxyAPI |
| **CLC** | `--source clc` | `~/.claude-clc/projects/<cwd>/*.jsonl` | Claude Code on Cursor via local translator |
| **CLD** | `--source cld` | `~/.claude-cld/projects/<cwd>/*.jsonl` | Claude Code on DeepSeek |
| **Cursor** | `--source cursor` or `--source cursor-agent` | `~/.cursor/projects/<cwd>/agent-transcripts/*/*.jsonl` | Cursor IDE and cursor-agent CLI |
| **Grok Build** | `--source grok` | `~/.grok/sessions/<url-encoded-cwd>/<id>/` | Grok Build CLI / TUI |
| **Antigravity** | `--source agy` or `--source antigravity` | `~/.gemini/antigravity-cli/brain/<id>/...` | Antigravity CLI transcripts |
| **All Stores** | `--source all` | All engines above | Chronologically merged and ranked |

Default source: auto-detected from current Claude profile (`clx` / `clg` / `clc` / `cld` via `CLAUDE_CONFIG_DIR`, otherwise `claude`).

## The engine

`scripts/sessions.py` does the heavy lifting so agents never have to read raw
transcripts directly. Those files can be tens of MB and contain abandoned turns,
system prompts, and large tool outputs.

```powershell
python scripts/sessions.py [--source claude|clx|clg|clc|cld|cursor|grok|agy|all] <command> ...
```

| Command | Purpose |
|---|---|
| `list [PROJECT] [--limit N] [--source S]` | Recent sessions, newest first. `PROJECT` is an optional case- and separator-insensitive substring of the working directory. |
| `search QUERY [--project P] [--limit N] [--source S]` | Find sessions by content: prose, tool calls, file paths, commands, and tool output. |
| `show SESSION [--mode briefing\|full\|prompts] [--all-branches] [--include-subagents] [--max-chars N] [--source S]` | Condensed transcript of one session. `SESSION` is a session id, a partial id, or a file path. If not in the active source, auto-resolves across all stores. |
| `sync [--host USER@HOST] [--name N] [--as N] [--pull-only\|--push-only] [--dry-run] [--status]` | Mirror session stores to/from another machine over ssh. |
| `memory-search QUERY [--project P] [--limit N]` | Search curated durable memory files before raw transcripts. |
| `memory-corpus [PROJECT] [--out DIR] [--session-limit N] [--run-codex]` | Build a Graphify-ready corpus from durable memory summaries plus a session index. |
| `memory-codex [PROJECT] [--build-graph]` | Use Codex CLI to add a semantic digest source to the memory corpus. |
| `memory-graph [PROJECT] [--corpus-dir DIR]` | Build a deterministic Graphify-compatible `graphify-out/graph.json` without requiring an LLM API key. |
| `memory-query QUERY [--project P] [--graph-dir DIR] [--budget N] [--dfs]` | Query the memory graph with Graphify when available; otherwise fall back to text memory search. |

## Quick examples

```powershell
# List recent sessions across all stores (and synced machines)
python scripts/sessions.py --source all list Trellis --limit 10

# Search for a topic across all platforms
python scripts/sessions.py --source all search "bq76922 balancing"

# Show a specific session (auto-resolves across stores)
python scripts/sessions.py show 019fb75c

# Filter to a specific agent harness
python scripts/sessions.py --source grok list --limit 5
python scripts/sessions.py --source agy search "Antigravity"
python scripts/sessions.py --source clx list --limit 5
python scripts/sessions.py --source clg list --limit 5
python scripts/sessions.py --source cursor list --limit 5
```

## Multiple computers

Sessions from other machines are mirrored into `~/.session-mirrors/<machine>/`
and searched alongside local ones (results show `machine=<name>`; filter with
`--machine local` or `--machine <name>`).

Run `sync` on the machine that can ssh into the other (e.g. a laptop reaching a
lab server). Each run pulls the server's sessions into the laptop's mirror and
pushes the laptop's sessions into the server's mirror, sending only changed
files. The remote needs `sh`, `find` and `tar`; locally just Python and `ssh`.

```powershell
# first run on the laptop (host and names are saved to ~/.session-mirrors/config.json)
python scripts/sessions.py sync --host jliu1401@linux-lab-101.ece.uw.edu --name uw-lab --as laptop
# afterwards
python scripts/sessions.py sync
python scripts/sessions.py sync --status
```

Set up ssh key auth so `sync` runs without password prompts (Windows PowerShell):

```powershell
ssh-keygen -t ed25519
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh jliu1401@linux-lab-101.ece.uw.edu "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

Environment overrides: `SESSIONS_MIRROR_DIR` (mirror location),
`SESSIONS_MACHINE_NAME` (this machine's name), `SESSIONS_SSH` (ssh binary).

## Installation

Copy this directory into your Claude Code or Agents skills folder:

```text
~/.claude/skills/read-past-sessions/
```

or for shared cross-agent discovery:

```text
~/.agents/skills/read-past-sessions/
```
