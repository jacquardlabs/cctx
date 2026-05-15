# PRODUCT.md — cctx

## What is this

cctx is a local Python CLI that reads Claude Code session logs and tells you what went wrong, why it cost what it did, and what to add to your CLAUDE.md so it doesn't happen again.

It is a forensic tool, not a monitoring tool. You reach for it after a session — when something felt off, when the bill was higher than expected, or on a weekly review pass.

## Primary persona

**The regular Claude Code user** who:
- Runs multiple Claude Code sessions per day across one or more projects
- Maintains a CLAUDE.md and wants it to get smarter over time
- Is willing to read a terminal report and act on its suggestions
- Cares about cost and session quality but does not need a dashboard
- Is comfortable with the command line and with `~/.claude/projects/` on disk

This persona is already the target; everything shipped to date serves them directly.

## What cctx is NOT for

- Teams or organizations (no shared reports, no access control, no multi-user state)
- Real-time monitoring (completed sessions only in v0 and v1)
- General cost dashboards (CodeBurn covers that; cctx is forensic)
- Multi-provider support (Claude Code only in v0/v1)
- Users who do not read session transcripts or maintain CLAUDE.md

## Product principles

**1. Forensic, not ambient.**
cctx is used after something goes wrong, not as background infrastructure. Every feature should be justified by this use case: "I just ran a session, something went sideways, I want to know what."

**2. Output must be actionable.**
Every report should produce at least one thing the user can do immediately. Findings without patches are incomplete. Patches must be copy-pasteable or auto-applicable.

**3. Honest about uncertainty.**
Costs are approximated (85–95% of actual). Pattern classifiers fire only on high-confidence signals. Low-confidence signals are shown with explicit confidence labels. "System internals" token budget is never hidden or misattributed.

**4. Local and stateless.**
No network calls in the core analysis path (tokenizer may call the API for token counting; that is opt-in). No persistent database. No telemetry. No account. Users own their data.

**5. Deterministic.**
Pattern classifiers are heuristics, not LLM calls. The same session file produces the same output every time. Testable on fixtures. Predictable cost to run.

**6. Small surface, deep on each command.**
Four commands. No command is shallow. Users should be able to learn the product in an afternoon and trust what it tells them.

## Feature map (v0.1.0)

### Shipped

| Feature | Command | Status |
|---|---|---|
| Single-session diagnosis | `cctx autopsy <session>` | Shipped (M2) |
| Cross-session pattern detection | `cctx autopsy <project> --since N` | Shipped (M2) |
| HTML report | `cctx autopsy <session> --html FILE` | Shipped (M2/PR#59) |
| Session trace TUI | `cctx trace <session>` | Shipped (M3) |
| JSONL export | `cctx export <session> --format jsonl` | Shipped (M4) |
| CSV export | `cctx export <session> --format csv` | Shipped (M4) |
| Harvest (CLAUDE.md patcher) | `cctx harvest <session>` | Shipped (M5) |
| Cross-session harvest | `cctx harvest <project> --since N` | Shipped (M5) |

### Pattern classifiers (v0.1.0)

| Pattern | Status |
|---|---|
| Retry loop | Shipped |
| Scope creep | Shipped |
| Stale context | Shipped |
| Dead-end exploration | Not shipped in v0 |
| Tool thrashing | Not shipped in v0 |

### NOT in v0.1.0

- `--format json` and `--format html` on `export` (html moved to `autopsy --html`; json not scheduled)
- `--since` string formats (`7d`, `2w`, date ranges, `--until`, `--top N`) — accepts integer days only
- Patch targets other than `CLAUDE.md` (rules, skills, ADR — v1+)
- Interactive aggregate drill-down ("press N to inspect pattern") — read-only in v0
- `cctx ls` / session discovery helper
- Dead-end and tool-thrash classifiers

## What we are NOT building

- A SaaS or cloud product
- An agent (cctx reads logs; it does not call the Anthropic API except optionally for token counting)
- A real-time watcher (v2+ roadmap item)
- Multi-provider support (v3+ roadmap item)
- A fork-and-replay debugger
- A general eval or testing framework

## Known problems (as of 2026-05-15)

**Release blockers for v0.1.0 (M6):**

1. **No README.md.** `pyproject.toml` uses `cctx-project-brief.md` as the readme. The brief contains architecture diagrams and an internal "First session prompt" that should not be on PyPI. A user-facing README.md is required before publish.

2. **`pyproject.toml` description is inaccurate.** Current: "Profile, debug, and optimize Claude Code and Agent SDK sessions." Accurate: "Diagnose Claude Code sessions — find what went wrong, what it cost, and what to add to CLAUDE.md."

3. **Version is `0.0.1`.** M6 requires bumping to `0.1.0`.

4. **Brief example outputs show unshipped features.** The `cctx-project-brief.md` (which currently IS the readme) shows 5 pattern classifiers, 4 export formats, string `--since` arguments, a `Verdict` headline, and interactive aggregate output. None of these are accurate for the shipped CLI. Before PyPI publish, either ship them or update the brief.

**Active gaps (non-blocking for v0.1.0 but worth tracking):**

5. **Cost approximation honesty not surfaced in output.** The terminal renderer shows `$X.XX` total cost with no confidence annotation. The brief says "The system internals slice is honest; don't pretend to be exact" — this is a principle not yet expressed to users in output.

6. **No session discovery helper.** Users must manually navigate URL-encoded project directories in `~/.claude/projects/` to find session files. First-run friction.

7. **Aggregate output is read-only.** The brief's example shows an interactive aggregate view. Shipped aggregate is a static table. The interactive drill-down is a meaningful UX gap that the brief implicitly promises.
