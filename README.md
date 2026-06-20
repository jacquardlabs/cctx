# cctx

Diagnose your Claude Code sessions and OpenTelemetry agent traces — find out when they went wrong, why they cost what they did, and what to add to your `CLAUDE.md` so it doesn't happen again.

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
cctx ls                          # find your sessions
cctx autopsy --latest            # diagnose the most recent one
cctx autopsy --all --since 7d    # weekly digest across all projects
cctx watch                       # live signals during an active session
```

cctx is primarily a forensic tool. You reach for it after a session — when something felt off, when the cost was higher than expected, or on a weekly review pass. `cctx watch` runs during a session and surfaces patterns as they happen. It reads the JSONL logs Claude Code writes to `~/.claude/projects/` and produces findings with attributed cost and copy-pasteable `CLAUDE.md` patches.

cctx also diagnoses OTEL traces from the OpenAI Agents SDK, LangGraph, and any framework that emits `gen_ai.*` semantic convention spans — auto-detected, no flags needed. See [Diagnosing other agent frameworks](docs/quickstart-otel.md).

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

# All sessions from the last 7 days in one project
cctx autopsy ~/Projects/myapp --since 7

# Weekly digest across all projects (cross-project mode)
cctx autopsy --all --since 7d

# Health grade (A–F) with per-finding savings estimate
cctx autopsy --latest --health

# Turn-level detail for a specific turn
cctx autopsy --latest --turn 12

# Write a self-contained HTML report
cctx autopsy ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl --html report.html

# OTEL trace from OpenAI Agents SDK, LangGraph, or any gen_ai.*-instrumented framework
cctx autopsy agent_trace.jsonl
```

Runs 10 pattern classifiers and prints findings with attributed cost. `--since N` aggregates patterns across sessions in a single project. `--all --since N` iterates every project under `~/.claude/projects/` and surfaces `FindingKind`s that recur in 2+ projects, with patches targeting `~/.claude/CLAUDE.md`.

OTEL traces are auto-detected — cctx sniffs the file format and routes to the right parser. See [docs/quickstart-otel.md](docs/quickstart-otel.md) for how to wire the OTEL exporter in each framework.

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

# Also write patches to AGENTS.md (Codex / OpenAI Agents)
cctx harvest --since 7 ~/Projects/myapp --emit agents

# Mirror already-harvested cctx sections from CLAUDE.md into AGENTS.md
cctx harvest --since 7 ~/Projects/myapp --emit agents --sync

# Measure whether applied patches reduced their target patterns
cctx harvest ~/Projects/myapp --efficacy
```

Turns autopsy findings into copy-pasteable `CLAUDE.md` additions. Patches are idempotent — running harvest twice on the same session won't duplicate entries. Use `--target-dir DIR` to specify which directory's `CLAUDE.md` to patch (default: current working directory).

`--emit agents` clones applicable `CLAUDE.md` patches to `AGENTS.md` in the same directory. `--sync` also mirrors any cctx-managed sections that were previously harvested but aren't in the current session's findings. `--efficacy` compares finding rates before and after each managed heading was applied — useful for measuring whether a patch actually changed behavior.

```bash
# Audit existing CLAUDE.md for dead file references and empty sections
cctx harvest . --check

# Only fail on HIGH-severity issues
cctx harvest . --check --check-severity high
```

`--check` reads the target `CLAUDE.md` without writing anything. Exits 1 if issues meet or exceed the severity threshold (default: `medium`). Useful as a CI step when `CLAUDE.md` is committed to the repo.

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

### `cctx watch` — live waste signals

```bash
cctx watch                    # watch the active session in cwd's project
cctx watch ~/Projects/myapp   # watch a specific project
```

Tails the active session as it progresses and prints a single-line alert each time a new waste pattern is detected. Exits after 30s of session inactivity or Ctrl+C.

### `cctx init` — automatic post-session diagnostics

```bash
# Install hook for the current project (.claude/settings.json)
cctx init

# Install hook globally (~/.claude/settings.json — all projects)
cctx init --global

# Remove the hook
cctx init --remove
```

Installs a `SessionEnd` hook that runs `cctx autopsy --latest --quiet` automatically when a Claude Code session ends. Output appears only when findings exist — silent when the session is clean. Running `cctx init` twice does not duplicate the hook.

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
| **Stale context** | Large tool results sitting in context long after their last reference | `content_tokens × turns_stale` — a 22K grep result present 14 turns after last use costs ~308K token-turns |
| **Tool thrash** | High tool-call volume with low forward progress | Exploratory calls that don't change the next step burn input tokens and turns |
| **Dead end** | Approach abandoned after significant sunk effort | Turns spent on a failing path before backtracking |
| **Fan-out waste** | Subagent spawned but result never consumed, or identical retry spawns | Full subagent cost with no new information |
| **Cache hygiene** | Frequent prompt-prefix changes that defeat KV-cache reuse | Cold input reads cost 10× a warm cache hit |
| **Compaction** | Context-window compaction mid-session | Compaction re-reads context from scratch; reduces effective context window |
| **Exploration thrash** | High read/search volume with no writes — circling without progress | Token cost of reads that don't advance the task |
| **Unused context** | MCP server loaded at session start but never called | Token overhead on every API request for tools that go unused |

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

## Using cctx in CI

cctx is primarily a local forensic tool — it reads session logs from `~/.claude/projects/` on your machine. Those logs are personal conversation history and should not be committed to git or uploaded as build artifacts.

**The one case where cctx belongs in CI:** when Claude Code itself runs inside a GitHub Actions job (agentic PR workflows, automated coding steps). In that case the JSONL logs are written on the runner during the job and cctx can analyse them as a post-step.

### GitHub Action (recommended)

```yaml
- uses: anthropics/claude-code-action@v1
  with:
    # ... your agentic workflow config

- uses: jacquardlabs/cctx@v0
  with:
    fail_on_findings: false   # set true to gate the job on waste findings
    github_summary: true      # write findings to the job summary UI
```

The action auto-discovers the most recent Claude Code session written on the runner. It does not accept arbitrary file paths — that pattern would require committing session logs to the repo, which you should not do.

### Manual step

```yaml
- uses: anthropics/claude-code-action@v1
  with:
    # ... your agentic workflow config

- name: Analyse session
  run: pipx run cctx-cli autopsy --latest . --github-summary
```

`--github-summary` appends a markdown findings report to the GitHub Actions job summary UI. Add `--fail-on-findings` to exit 1 when waste patterns are detected.

Commands that make sense as CI steps:
- `cctx autopsy` — diagnose the session that just ran
- `cctx export` — archive structured findings as a build artifact

`cctx harvest` requires session logs AND writes to `CLAUDE.md` — neither step maps cleanly to CI. Run it locally after a session.

## License

MIT
