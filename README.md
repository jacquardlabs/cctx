# cctx

Diagnose your Claude Code sessions and OpenTelemetry agent traces — find out when they went wrong, why they cost what they did, and what to add to your `CLAUDE.md` so it doesn't happen again.

[![CI](https://github.com/jacquardlabs/cctx/actions/workflows/ci.yml/badge.svg)](https://github.com/jacquardlabs/cctx/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cctx-cli)](https://pypi.org/project/cctx-cli/)
[![Python](https://img.shields.io/badge/python-3.10_%7C_3.11_%7C_3.12_%7C_3.13-blue)](https://pypi.org/project/cctx-cli/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

![cctx ls and cctx autopsy --latest running in a terminal](demo.gif)

## Install

```bash
pipx install cctx-cli
```

Or with pip: `pip install cctx-cli`. `pipx` is recommended: it isolates cctx's dependencies from your projects.

No API key required. cctx reads the JSONL logs Claude Code already writes to `~/.claude/projects/` and uses the token counts recorded there.

## See it

Point cctx at your most recent session:

```console
$ cctx autopsy --latest

Verdict: 3 findings · $0.98 waste
RETRY LOOP + SCOPE CREEP + STALE CONTEXT
Session cost: ~$1.42   (~85–95% of actual billing)
Inflection turn: 14

 RETRY LOOP  (high confidence) — Edit→Bash(npm test) repeated across turns
 14–22 with no intervening Read; the same test failed identically each time.

 SCOPE CREEP  (medium confidence) — the prompt was "fix auth bug"; refactoring
 of the user model began at turn 25 with no request observed.

 STALE CONTEXT  (medium confidence) — a 4.8K-token directory listing from
 turn 9 stayed in context 14 turns after its last reference.

──────────────────────────────── CLAUDE.md patches ────────────────────────────

When tests fail  [CLAUDE.md]
+ ## When tests fail
+ If a test fails twice with the same error, stop and re-read the source
+ file before attempting another fix.

Scope  [CLAUDE.md]
+ ## Scope
+ Stick to the task in the prompt. If you spot adjacent issues, name them
+ and ask before fixing.

cctx trace --latest   to step through this session interactively
```

Every finding ties to specific turns; every patch is a copy-pasteable `CLAUDE.md` diff. Add `--health` for an A–F grade plus per-finding savings.

## The loop

cctx is forensic: you reach for it *after* a session that felt off, cost more than expected, or on a weekly review. The payoff comes from running the loop, not a single command:

**1. Diagnose** — autopsy the session you just finished.

```bash
cctx autopsy --latest        # the most recent session in this project
cctx init                    # or: run it automatically at every session end
```

**2. Fix** — turn the findings into durable `CLAUDE.md` rules. Harvest previews the diffs, then applies on confirm. It's idempotent: running it twice never duplicates an entry.

```bash
cctx harvest . --since 7d    # patches from the last week of sessions
```

**3. Verify** — after the rules have had time to bite, check whether they actually changed behavior.

```bash
cctx harvest . --efficacy    # finding rates before vs. after each patch
```

Two more entry points around the loop:

```bash
cctx autopsy --all --since 7d   # weekly digest across every project
cctx watch                      # live waste signals during an active session
```

cctx also diagnoses OTEL traces from the OpenAI Agents SDK, LangGraph, and any `gen_ai.*`-instrumented framework (auto-detected, no flags). See [Other agent frameworks](#other-agent-frameworks).

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

Every per-turn pattern above is also detected **inside subagents** — a retry loop or stale-context buildup within a child session (at any nesting depth) is surfaced, tagged with that subagent, and priced at the subagent's own model.

## Commands

Common invocations below. Run `cctx <command> --help` for the full flag set.

### `cctx ls` — find your sessions

```bash
cctx ls                      # all Claude Code projects
cctx ls ~/Projects/myapp     # sessions in one project
```

Handles the encoded `~/.claude/projects/` layout for you: no need to navigate it by hand.

### `cctx autopsy` — diagnose a session

```bash
cctx autopsy --latest                # most recent session in this project
cctx autopsy session.jsonl           # a specific session file
cctx autopsy ~/Projects/myapp --since 7d   # aggregate one project's recent sessions
cctx autopsy --all --since 7d        # cross-project weekly digest
```

Runs 10 pattern classifiers and prints findings with attributed cost. Notable flags: `--health` (A–F grade + savings), `--turn N` (turn-level detail), `--html report.html` (self-contained report), `--json` (machine-readable). `--since` accepts `7`, `7d`, `2w`, `2026-05-01`, or `2026-05-01..2026-05-15`.

### `cctx harvest` — write fixes into CLAUDE.md

```bash
cctx harvest session.jsonl           # preview, then confirm
cctx harvest . --since 7d            # patches from the last week
cctx harvest . --since 7d --apply    # apply without prompting
cctx harvest . --check               # audit CLAUDE.md for dead refs / empty sections
```

Turns autopsy findings into copy-pasteable `CLAUDE.md` additions, deduplicated by fingerprint. `--target-dir DIR` picks which directory's `CLAUDE.md` to patch. `--emit agents` also writes applicable patches to `AGENTS.md` (add `--sync` to mirror existing cctx-managed sections). `--efficacy` measures whether applied patches reduced their target patterns. `--check` exits 1 when issues meet the severity threshold (useful as a CI gate on a committed `CLAUDE.md`).

### `cctx watch` — live waste signals

```bash
cctx watch                   # the active session in this project
cctx watch ~/Projects/myapp  # a specific project
```

Tails the active session and prints a one-line alert each time a new waste pattern appears. Exits after 30s of inactivity or Ctrl+C.

### `cctx init` — automatic post-session diagnostics

```bash
cctx init            # install the hook for this project
cctx init --global   # install for all projects (~/.claude/settings.json)
cctx init --remove   # uninstall
```

Installs a `SessionEnd` hook that runs `cctx autopsy --latest --quiet` when a session ends. Output appears only when findings exist; idempotent.

### `cctx trace` — interactive TUI

```bash
cctx trace --latest          # step through the most recent session
cctx trace session.jsonl     # a specific session
```

Walks a session turn by turn with autopsy findings overlaid. Press `q` to quit.

### `cctx export` — machine-readable data

```bash
cctx export session.jsonl --format csv --out session.csv   # one row per turn
cctx export session.jsonl --format jsonl                   # one object per session, to stdout
```

Dumps session analysis as `jsonl`/`csv`/`json` for external tools. Add `--no-content` to omit patch text and finding summaries.

## Going further

### Other agent frameworks

cctx diagnoses OTEL traces from the OpenAI Agents SDK, LangGraph, and any framework that emits `gen_ai.*` semantic-convention spans. It sniffs the file format and routes to the right parser: `cctx autopsy agent_trace.jsonl` works with no flags. See [docs/quickstart-otel.md](docs/quickstart-otel.md) for wiring the exporter in each framework.

### Cost attribution

cctx prices both input and output tokens from a built-in table covering Anthropic (Claude) and OpenAI models, so OTEL traces are costed at the right provider's rates — not just Claude sessions. Prompt-cache reads bill at 10% of input, 5-minute cache writes at 125%, 1-hour writes at 200%. Stale-context waste is attributed turn by turn: every turn a large result lingers after its last reference counts against waste.

The price table is stamped with a verification date (shown as "prices as of …" in output) and a CI tripwire flags it when stale; an unrecognized model family is flagged and priced at a default rate rather than silently mis-costed.

These are **approximations** (~85–95% of actual API billing). The gap is internal prompt framing that isn't observable in the logs. cctx shows estimated costs, not billing-exact figures.

### In CI

cctx is a local forensic tool: session logs are personal history and shouldn't be committed to git. The one exception: **when Claude Code runs inside a GitHub Actions job** (agentic PR workflows), the logs are written on the runner and cctx can analyze them as a post-step.

```yaml
- uses: anthropics/claude-code-action@v1
  with:
    # ... your agentic workflow config

- uses: jacquardlabs/cctx@v1.20.0
  with:
    fail_on_findings: false   # set true to gate the job on waste findings
    github_summary: true      # write findings to the job summary UI
```

The action auto-discovers the most recent session on the runner. For a manual step, `pipx run cctx-cli autopsy --latest . --github-summary` appends findings to the job summary; add `--fail-on-findings` to exit 1 on detection.

### Requirements

- Python 3.10+
- Claude Code session logs at `~/.claude/projects/` (written automatically)
- No API key for analysis. An optional `ANTHROPIC_API_KEY` enables exact token counts via the Anthropic API; without it, cctx uses the counts already in the logs (the default and recommended mode).

## Contributing

Issues and PRs welcome.

```bash
pip install -e ".[dev]"
ruff check cctx tests
CCTX_OFFLINE=1 pytest -v
```

## License

MIT

> TODO: no `LICENSE` file exists at the repo root, though `pyproject.toml` declares `license = "MIT"` and GitHub's API reports no detected license for this repo. The License badge at the top of this page also links to `LICENSE`, which doesn't exist yet. Add a `LICENSE` file so both are accurate.
