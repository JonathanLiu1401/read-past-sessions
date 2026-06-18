# read-past-sessions

A [Claude Code](https://claude.com/claude-code) skill for finding and reading **past Claude Code sessions** — the conversation transcripts stored on disk — and turning one into a context briefing for the current chat.

Use it whenever you want to fork off, continue, resume, or pick up from a previous session; recall what was decided in an earlier chat; or find which old session touched a particular file, topic, or artifact.

## What's here

| File | Purpose |
|---|---|
| `SKILL.md` | The skill definition (instructions Claude Code loads). |
| `scripts/sessions.py` | The engine. Pure Python, no third-party dependencies. |

## The engine

`scripts/sessions.py` does the heavy lifting so Claude never has to read raw `.jsonl` transcripts (which are routinely tens of MB and are conversation *trees*, mixing the live thread with abandoned/rewound branches).

```
python scripts/sessions.py <command> ...
```

| Command | Purpose |
|---|---|
| `list [PROJECT] [--limit N]` | Recent sessions, newest first. `PROJECT` is an optional case-/separator-insensitive substring of the working directory. |
| `search QUERY [--project P] [--limit N]` | Find sessions by content — searches prose, tool calls (file paths, commands), and tool output. Ranked by relevance. |
| `show SESSION [--mode briefing\|full\|prompts] [--all-branches] [--include-subagents] [--max-chars N]` | Condensed transcript of one session. `SESSION` is a session id, a partial id, or a file path. |

Transcripts are read from `$CLAUDE_CONFIG_DIR/projects/` or `~/.claude/projects/`.

## Installation

Copy this directory into your Claude Code skills folder:

```
~/.claude/skills/read-past-sessions/
```

Claude Code will pick it up automatically.
