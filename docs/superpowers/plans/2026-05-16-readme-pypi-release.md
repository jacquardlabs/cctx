# README + PyPI Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a thorough user-facing README, a Trusted Publishing PyPI workflow, a vhs demo script, and the v0.1.0 version bump.

**Architecture:** Four independent file changes — `pyproject.toml` version bump, new `.github/workflows/publish.yml`, new `demo.tape`, and a full `README.md` rewrite. No source code changes. No tests required (no logic added).

**Tech Stack:** GitHub Actions, `pypa/gh-action-pypi-publish`, `python -m build` (hatchling backend), shields.io badges, vhs tape syntax.

---

### Task 1: Bump version to 0.1.0

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit the version field**

In `pyproject.toml`, change:
```toml
version = "0.0.1"
```
to:
```toml
version = "0.1.0"
```

No other files need updating — hatchling reads directly from `pyproject.toml`; there is no `__version__` in the source.

- [ ] **Step 2: Verify the package reports the new version**

```bash
pip install -e . -q && cctx --version
```

Expected output: `cctx, version 0.1.0`

(If `--version` isn't wired, that's fine — just verify `pyproject.toml` has `0.1.0` and move on.)

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: bump version to 0.1.0"
```

---

### Task 2: Add PyPI publish workflow (Trusted Publishing)

**Files:**
- Create: `.github/workflows/publish.yml`

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/publish.yml` with this exact content:

```yaml
name: publish

on:
  release:
    types: [published]

jobs:
  publish:
    name: Publish to PyPI
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Build
        run: |
          pip install build
          python -m build

      - name: Publish
        uses: pypa/gh-action-pypi-publish@release/v1
```

**How Trusted Publishing works:** The `environment: pypi` + `id-token: write` combination lets the action request a short-lived PyPI token via OIDC at publish time. No secret is stored anywhere. One-time setup required on PyPI before the first publish — see Task 2 Step 3.

- [ ] **Step 2: Validate the YAML**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/publish.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`

- [ ] **Step 3: Note the one-time PyPI setup (manual, not automated)**

Before the first publish, do this in the PyPI web UI:
1. Log in to pypi.org → Your projects → cctx → Publishing
2. Click "Add a new pending publisher"
3. Fill in:
   - GitHub repository owner: `jacquardlabs`
   - Repository name: `cctx`
   - Workflow filename: `publish.yml`
   - Environment name: `pypi`
4. Save — PyPI will now trust OIDC tokens from this exact workflow

This step is manual and has no automated verification. Do it before creating the v0.1.0 GitHub Release.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/publish.yml
git commit -m "ci: add PyPI publish workflow (Trusted Publishing)"
```

---

### Task 3: Add demo.tape vhs script

**Files:**
- Create: `demo.tape`

- [ ] **Step 1: Create the tape script**

Create `demo.tape` at the repo root:

```
Output demo.gif
Set FontSize 14
Set Width 120
Set Height 40
Set Theme "Catppuccin Mocha"

Type "cctx ls"
Enter
Sleep 1500ms

# Edit the path below to a real session file on your machine before recording.
# Run `cctx ls` first to find one, then copy a path from the output.
Type "cctx autopsy ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl"
Enter
Sleep 4000ms
```

- [ ] **Step 2: Note how to generate the GIF (manual step)**

When ready to record:
```bash
brew install vhs              # one-time install
# Edit demo.tape: replace the example path with a real session file path
vhs demo.tape                 # produces demo.gif in the repo root
git add demo.gif
git commit -m "docs: add terminal demo GIF"
```

The GIF is committed to the repo and referenced from README.md. It does not need to be regenerated on every release — only when the CLI output format changes significantly.

- [ ] **Step 3: Commit**

```bash
git add demo.tape
git commit -m "docs: add vhs demo tape script"
```

---

### Task 4: Rewrite README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README.md with the full content below**

Overwrite `README.md` entirely:

````markdown
# cctx

Diagnose your Claude Code sessions — find out when they went wrong, why they cost what they did, and what to add to your `CLAUDE.md` so it doesn't happen again.

[![CI](https://github.com/jacquardlabs/cctx/actions/workflows/ci.yml/badge.svg)](https://github.com/jacquardlabs/cctx/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cctx)](https://pypi.org/project/cctx/)
[![Python](https://img.shields.io/pypi/pyversions/cctx)](https://pypi.org/project/cctx/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

![demo](demo.gif)

## Install

```bash
pipx install cctx
```

Or with pip:

```bash
pip install cctx
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

Turns autopsy findings into copy-pasteable `CLAUDE.md` additions. Patches are idempotent — running harvest twice on the same session won't duplicate entries.

### `cctx export` — export session data

```bash
# CSV to file
cctx export ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl --format csv --out session.csv

# JSONL to stdout
cctx export ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl --format jsonl
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
````

- [ ] **Step 2: Verify the file looks right**

```bash
wc -l README.md
```

Expected: roughly 120–150 lines (markdown is compact). Open the file and do a quick visual check: badges present, all five commands documented, pattern table present, cost attribution section present.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for v0.1.0 — badges, all commands, cost attribution"
```

---

## Post-implementation checklist

- [ ] All four commits are on the current branch
- [ ] `pyproject.toml` shows `version = "0.1.0"`
- [ ] `.github/workflows/publish.yml` exists and passes YAML validation
- [ ] `demo.tape` exists at repo root with the placeholder path comment
- [ ] `README.md` has badges, five commands, pattern table, cost attribution, and the `demo.gif` embed
- [ ] PyPI Trusted Publishing pending publisher is configured (one-time manual step, see Task 2 Step 3)
- [ ] `demo.gif` generated and committed when ready (after `brew install vhs`)
