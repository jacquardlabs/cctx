# README + PyPI Release Design

**Date:** 2026-05-16
**Scope:** M6 release prep — user-facing README rewrite, PyPI publish workflow, version bump, vhs demo script

---

## Goals

1. Replace the sparse 90-line README with a thorough, PyPI-ready document that serves both GitHub visitors and `pip show` readers.
2. Add a GitHub Actions workflow that publishes to PyPI on every GitHub Release (Trusted Publishing / OIDC — no stored secrets).
3. Bump the package version from `0.0.1` to `0.1.0`.
4. Commit a `demo.tape` vhs script so the terminal demo is reproducible (GIF generated separately after `brew install vhs`).

---

## README

### Audience

Both surfaces share the same file (`pyproject.toml` sets `readme = "README.md"`):
- **GitHub repo page** — developers evaluating the tool; want to see output and understand scope fast.
- **PyPI project page** — users about to `pip install`; want install instructions and a quick-start.

### Structure

```
# cctx
<one-line tagline matching pyproject.toml description>

[CI badge] [PyPI version badge] [Python 3.10+ badge] [MIT badge]

<demo.gif embed — file committed separately after vhs run>

## Install
pipx install cctx   ← recommended (isolated environment, no conflicts)
pip install cctx    ← fallback

## Quick start
Two-command path: cctx ls to find sessions, cctx autopsy to diagnose.
Brief prose (2 sentences) explaining the forensic model.

## Commands
### cctx ls              — list recent sessions across all projects
### cctx autopsy         — diagnose a session; --since N for cross-session
### cctx harvest         — propose and apply CLAUDE.md patches
### cctx export          — dump session data as JSONL or CSV
### cctx trace           — step through a session in an interactive TUI

Each command: one-line description, example invocation(s), key flags.

## What cctx detects
Pattern table (retry loop, scope creep, stale context) — current shipped classifiers only.

## Cost attribution
Honest approximation note: 85–95% of actual API billing. Explains cache read (10%)
and cache write (125%) rates. Notes that stale-context waste is attributed as
content_tokens × billed_turns_stale.

## Requirements
- Python 3.10+
- Claude Code session logs at ~/.claude/projects/
- No API key required for analysis (optional for exact token counting via CCTX_OFFLINE=0)

## Session log location
URL-encoded path explanation: /Users/you/Projects/myapp → -Users-you-Projects-myapp.
Note that cctx ls handles discovery automatically.

## License
MIT
```

### Badges

Use shields.io static badges (no external API calls for CI/PyPI version):
- CI: `https://github.com/jacquardlabs/cctx/actions/workflows/ci.yml/badge.svg`
- PyPI version: `https://img.shields.io/pypi/v/cctx`
- Python: `https://img.shields.io/pypi/pyversions/cctx`
- License: `https://img.shields.io/badge/license-MIT-blue`

### Demo GIF

- `demo.gif` embedded in README via `![demo](demo.gif)`
- Produced by running `vhs demo.tape` after `brew install vhs`
- `demo.tape` committed to repo root (see below)
- Until GIF is generated, the `![demo](demo.gif)` line is present in the README but the image will not render on GitHub/PyPI — acceptable for initial publish; GIF added in a follow-up commit

---

## demo.tape (vhs script)

Shows the two-command happy path:

```
Output demo.gif
Set FontSize 14
Set Width 120
Set Height 40
Set Theme "Catppuccin Mocha"

Type "cctx ls"
Enter
Sleep 1s

# Edit the path below to a real session file before recording
Type "cctx autopsy ~/.claude/projects/-Users-you-Projects-myapp/abc123.jsonl"
Enter
Sleep 3s
```

The tape script uses a hardcoded example path that must be edited to a real local session file before recording. The resulting GIF is committed to the repo and does not need to be regenerated on every release — only when the output format changes significantly.

---

## GitHub Actions: publish.yml

**File:** `.github/workflows/publish.yml`

**Trigger:** `release: types: [published]`

**Auth:** Trusted Publishing (OIDC via `pypa/gh-action-pypi-publish`). Requires one-time setup:
1. On PyPI: go to cctx project → Publishing → Add a pending publisher
2. Set: GitHub owner = `jacquardlabs`, repo = `cctx`, workflow = `publish.yml`, environment = `pypi`
3. No secret is stored in GitHub — the action requests a short-lived token at publish time via OIDC

**Workflow steps:**
```yaml
on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write  # required for OIDC
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install build
      - run: python -m build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

**Version source of truth:** `pyproject.toml`. No tag-extraction, no dynamic versioning. Bump the version manually before creating the GitHub Release.

**No TestPyPI step.** For v0.1.0, publish directly to PyPI. If a TestPyPI dry-run is desired later, it can be added as a separate job.

---

## Version bump

`pyproject.toml`: `version = "0.0.1"` → `version = "0.1.0"`

This is the only file that needs changing for the version bump (hatchling reads it directly; no `__version__` in source to keep in sync).

---

## Files touched

| File | Change |
|---|---|
| `README.md` | Full rewrite (~250 lines) |
| `.github/workflows/publish.yml` | New file |
| `demo.tape` | New file |
| `pyproject.toml` | Version bump only |

---

## Out of scope

- TestPyPI dry-run job
- Changelog generation or semantic release
- `cctx ls` interactive output in the demo (keep demo to the happy path: ls → autopsy)
- Any new CLI features
