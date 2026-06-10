# PRODUCT.md — cctx

## What is this

cctx is a local Python CLI that reads Claude Code session logs and tells you what went wrong, why it cost what it did, and what to add to your CLAUDE.md so it doesn't happen again.

It is forensic-first. You reach for it after a session — when something felt off, when the bill was higher than expected, or on a weekly review pass. `cctx watch` extends the same waste detection into a live, opt-in companion for an active session; it is a foreground command you run deliberately, not background infrastructure.

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
- Ambient monitoring (no daemons, no persistent watcher state, no alerting — `cctx watch` is a foreground command you start and stop)
- General cost dashboards (CodeBurn covers that; cctx is forensic)
- Multi-provider support (Claude Code only in v0/v1)
- Users who do not read session transcripts or maintain CLAUDE.md

## Product principles

**1. Forensic, not ambient.**
cctx is forensic-first: the core use case is "I just ran a session, something went sideways, I want to know what." Live mode (`watch`) is justified only as the same detection running earlier — it surfaces the identical findings, never becomes a daemon, and never holds state between runs.

**2. Output must be actionable.**
Every report should produce at least one thing the user can do immediately. Findings without patches are incomplete. Patches must be copy-pasteable or auto-applicable.

**3. Honest about uncertainty.**
Costs are approximated (85–95% of actual). Pattern classifiers fire only on high-confidence signals. Low-confidence signals are shown with explicit confidence labels. "System internals" token budget is never hidden or misattributed.

**4. Local and stateless.**
No network calls in the core analysis path (tokenizer may call the API for token counting; that is opt-in). Live-session detection may shell out to the local `claude` CLI and degrades gracefully without it. No persistent database. No telemetry. No account. Users own their data.

**5. Deterministic.**
Pattern classifiers are heuristics, not LLM calls. The same session file produces the same output every time. Testable on fixtures. Predictable cost to run.

**6. Small surface, deep on each command.**
Six commands (`ls`, `autopsy`, `harvest`, `watch`, `trace`, `export`). No command is shallow. Users should be able to learn the product in an afternoon and trust what it tells them.

## Feature map (v1.4.0)

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
| Verdict headline + `--top N` + `--turn N` | `autopsy` | v1.1.0 (M9) |
| `--until DATE` on cross-session mode | `autopsy --since ... --until` | v1.2.0 (M12) |
| Machine-readable diagnosis | `cctx autopsy <session> --json` | v1.2.0 (M12) |
| JSON export | `cctx export <session> --format json` | v1.2.0 (M12) |
| Project-specific pattern detection | `autopsy`/`harvest` `--since` | v1.3.0 (M14) |
| Memory-hygiene depth | `harvest --check` + `--check-severity` | v1.4.0 (M13) |
| Live session badges | `cctx ls` | unreleased |
| Live session detection, early idle exit | `cctx watch` | unreleased |
| Cross-agent emit | `cctx harvest --emit agents [--sync]` | M15; mirror CLAUDE.md sections to AGENTS.md — unreleased |

### Pattern classifiers (v1.4.0)

| Pattern | Status |
|---|---|
| Retry loop | Shipped |
| Scope creep | Shipped |
| Stale context | Shipped |
| Dead-end exploration | Shipped (v0.2.0) |
| Tool thrashing | Shipped (v0.2.0) |
| Project-specific patterns (cross-session) | Shipped (v1.3.0) |

## What we are NOT building

- A SaaS or cloud product
- An agent (cctx reads logs; it does not call the Anthropic API except optionally for token counting)
- Multi-provider support (Claude Code only in v0/v1)
- A fork-and-replay debugger
- A general eval or testing framework

## Known problems (as of 2026-06-09)

**Active gaps:**

1. **`cctx watch` polling is simple.** Early idle exit via `claude agents --json` has landed, but the watcher still polls at 1s without `fsevents`/`inotify` debouncing.

2. **Subagent traces are parsed but never diagnosed.** The parser models subagent sessions recursively and the tokenizer counts their tokens, but no classifier or cost attribution reads `trace.subagents`. Autopsy is blind to spend inside agent fan-outs. (M16)

3. **Cross-agent layer not started.** Tracked as M15 / #82 — the final step of the original growth staircase.

4. **Harvest has no feedback loop.** Nothing measures whether an applied patch reduced the recurrence of the pattern it targeted, even though patches carry fingerprints and sessions carry dates. (M17)
