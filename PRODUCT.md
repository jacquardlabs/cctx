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

## Feature map (v0.2.0)

### Shipped

| Feature | Command | Notes |
|---|---|---|
| Single-session diagnosis | `cctx autopsy <session>` | M2 |
| Cross-session pattern detection | `cctx autopsy <project> --since N` | M2 |
| `--since` string formats | `--since 7d`, `2w`, `2026-05-01`, date ranges | M6+ |
| Interactive aggregate drill-down | select pattern → per-session detail | M6+ |
| HTML report | `cctx autopsy <session> --html FILE` | M2 |
| GitHub Actions job summary | `cctx autopsy --github-summary` | M6+ |
| CI fail gate | `cctx autopsy --fail-on-findings` | M6+ |
| GitHub Action (composite) | `jacquardlabs/cctx@v1` in workflow | M6+ |
| Session trace TUI | `cctx trace <session>` | M3 |
| JSONL export | `cctx export <session> --format jsonl` | M4 |
| CSV export | `cctx export <session> --format csv` | M4 |
| Harvest (CLAUDE.md patcher) | `cctx harvest <session>` | M5 |
| Harvest v2 (multi-target) | patches to `.claude/rules/`, `.claude/skills/` | M6+ |
| Harvest --check | `cctx harvest <dir> --check` — audit for dead refs | M6+ |
| Cross-session harvest | `cctx harvest <project> --since N` | M5 |
| Session discovery | `cctx ls` / `cctx autopsy --latest` | M6+ |
| Live waste signals | `cctx watch <project>` | M6+ |

### Pattern classifiers (v0.2.0)

| Pattern | Status |
|---|---|
| Retry loop | Shipped |
| Scope creep | Shipped |
| Stale context | Shipped |
| Dead-end exploration | Shipped (v0.2.0) |
| Tool thrashing | Shipped (v0.2.0) |

## What we are NOT building

- A SaaS or cloud product
- An agent (cctx reads logs; it does not call the Anthropic API except optionally for token counting)
- Multi-provider support (Claude Code only in v0/v1)
- A fork-and-replay debugger
- A general eval or testing framework

## Known problems (as of 2026-05-16)

**Active gaps (non-blocking for v0.2.0 but worth tracking):**

1. **`cctx watch` polling is simple.** Polls every 1s and re-runs classifiers on any file growth. Does not debounce or use `fsevents`/`inotify`. Fine for v0 but will chatter on active sessions.

2. **`--format json` on `export` not shipped.** `--html` moved to `autopsy --html`; `json` format on the `export` subcommand is still deferred.

3. **Cross-agent layer not started.** Emitting findings as `.cursorrules`, `AGENTS.md`, `.windsurfrules`, or GitHub Copilot instructions is a roadmap item with no milestone yet.
