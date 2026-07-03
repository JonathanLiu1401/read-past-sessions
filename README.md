# read-past-sessions

A Claude Code skill for finding and reading past Claude Code session transcripts
and turning them into concise context briefings for the current chat.

Use it when you want to fork off, continue, resume, or pick up from a previous
session; recall what was decided in an earlier chat; or find which old session
touched a particular file, topic, or artifact.

It can also search curated durable memory files and build a local
Graphify-compatible memory graph, so project knowledge can be shared between
agent sessions without rereading raw transcript JSONL files.

## What's here

| File | Purpose |
|---|---|
| `SKILL.md` | The skill definition loaded by Claude Code. |
| `scripts/sessions.py` | The engine. Pure Python, no third-party dependencies for transcript and deterministic memory-graph operations. |

## The engine

`scripts/sessions.py` does the heavy lifting so Claude never has to read raw
`.jsonl` transcripts directly. Those files can be tens of MB and are conversation
trees, mixing the live thread with abandoned or rewound branches.

```powershell
python scripts/sessions.py <command> ...
```

| Command | Purpose |
|---|---|
| `list [PROJECT] [--limit N]` | Recent sessions, newest first. `PROJECT` is an optional case- and separator-insensitive substring of the working directory. |
| `search QUERY [--project P] [--limit N]` | Find sessions by content: prose, tool calls, file paths, commands, and tool output. |
| `show SESSION [--mode briefing\|full\|prompts] [--all-branches] [--include-subagents] [--max-chars N]` | Condensed transcript of one session. `SESSION` is a session id, a partial id, or a file path. |
| `memory-search QUERY [--project P] [--limit N]` | Search curated durable memory files before raw transcripts. |
| `memory-corpus [PROJECT] [--out DIR] [--session-limit N]` | Build a Graphify-ready corpus from durable memory summaries plus a session index. |
| `memory-graph [PROJECT] [--corpus-dir DIR]` | Build a deterministic Graphify-compatible `graphify-out/graph.json` without requiring an LLM API key. |
| `memory-query QUERY [--project P] [--graph-dir DIR] [--budget N] [--dfs]` | Query the memory graph with Graphify when available; otherwise fall back to text memory search. |

Transcripts are read from `$CLAUDE_CONFIG_DIR/projects/` or `~/.claude/projects/`.

Durable memory is read from the local Codex/Claude memory locations and selected
project briefing files. `memory-corpus` and `memory-graph` deliberately exclude
raw transcript `.jsonl` files.

## Installation

Copy this directory into your Claude Code skills folder:

```text
~/.claude/skills/read-past-sessions/
```

Claude Code will pick it up automatically.
