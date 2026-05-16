# cctx

Diagnose your Claude Code sessions — find out when they went wrong, why they cost what they did, and what to add to your `CLAUDE.md` so it doesn't happen again.

[![CI](https://github.com/jacquardlabs/cctx/actions/workflows/ci.yml/badge.svg)](https://github.com/jacquardlabs/cctx/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cctx-cli)](https://pypi.org/project/cctx-cli/)
[![Python](https://img.shields.io/badge/python-3.10_%7C_3.11_%7C_3.12_%7C_3.13-blue)](https://pypi.org/project/cctx-cli/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

![demo](demo.gif)

## Install

```bash
pipx install cctx-cli
```

Or with pip:

```bash
pip install cctx-cli
```

`pipx` is recommended — it installs cctx in an isolated environment so its dependencies don't conflict with your projects.

## Quick start

```bash
cctx ls                   # find your sessions
cctx autopsy --latest     # diagnose the most recent one
```

cctx is a forensic tool. You reach for it after a session — when something felt off, when the cost was higher than expected, or on a weekly review pass. It reads the JSONL logs Claude Code writes to `~/.claude/projects/` and produces findings with attributed cost and copy-pasteable `CLAUDE.md` patches.

## Commands

### `cctx ls` — list projects and sessions

```bash
cctx ls                    # list all Claude Code projects
cctx ls ~/Projects/myapp   # list sessions for a specific project
```

### `cctx autopsy` — diagnose a session

```bash
# Most recent session in the current directory
cctx autopsy --latest

# Specific session file
cctx autopsy ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl

# All sessions from the last 7 days
cctx autopsy ~/Projects/myapp --since 7

# Write a self-contained HTML report
cctx autopsy ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl --html report.html
```

Runs three pattern classifiers (retry loop, scope creep, stale context) and prints findings with attributed cost. Use `--since N` to aggregate patterns across multiple sessions in a project.

### `cctx harvest` — apply patches to CLAUDE.md

```bash
# Interactive: preview then confirm
cctx harvest ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl

# Preview only — don't write anything
cctx harvest ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl --dry-run

# Apply without confirmation
cctx harvest ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl --apply

# Cross-session: patches from the last 7 days of sessions
cctx harvest ~/Projects/myapp --since 7
```

Turns autopsy findings into copy-pasteable `CLAUDE.md` additions. Patches are idempotent — running harvest twice on the same session won't duplicate entries. Use `--target-dir DIR` to specify which directory's `CLAUDE.md` to patch (default: current working directory).

### `cctx export` — export session data

```bash
# CSV to file
cctx export ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl --format csv --out session.csv

# JSONL to stdout
cctx export ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl --format jsonl

# Omit patch text and finding summaries (smaller output for scripted use)
cctx export ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl --format jsonl --no-content
```

Dumps session analysis as JSONL (one object per session) or CSV (one row per turn) for use in external tools.

### `cctx trace` — interactive TUI

```bash
cctx trace ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl
```

Steps through a session turn by turn in a terminal UI with autopsy findings overlaid. Press `q` to quit.

## What cctx detects

| Pattern | What it means | How it wastes money |
|---|---|---|
| **Retry loop** | The same tool call failing 2+ times with no successful fix | Repeated identical API calls burn input tokens |
| **Scope creep** | Assistant expanding scope mid-task without being asked | Unnecessary extra turns and tool calls |
| **Stale context** | Large tool results sitting in context long after their last reference | `content_tokens × billed_turns_stale` — a 22K grep result still present 14 turns later costs ~308K token-turns |

## Cost attribution

cctx estimates session cost using Anthropic's published billing rates:

- Input tokens: standard rate
- Cache reads: 10% of the input rate
- Cache writes: 125% of the input rate

Stale-context waste is attributed turn by turn: every turn a large result stays in context after its last reference counts against waste.

These are **approximations** (~85–95% of actual API billing). The gap is internal prompt framing that isn't observable in the JSONL logs. cctx shows estimated costs, not billing-exact figures.

## Requirements

- Python 3.10+
- Claude Code session logs at `~/.claude/projects/` (written automatically by Claude Code)
- No API key required for analysis

An `ANTHROPIC_API_KEY` is optional. When set, cctx can call the Anthropic API for exact token counts. Without it, cctx uses the token counts already recorded in the JSONL logs (the default and recommended mode for most users).

## Session log location

Claude Code writes logs to `~/.claude/projects/<encoded-path>/<session-id>.jsonl`. The project path is URL-encoded with `-` replacing `/`, so `/Users/you/Projects/myapp` becomes `-Users-you-Projects-myapp`.

`cctx ls` handles discovery automatically — you don't need to navigate the encoded directory structure by hand.

## License

MIT
