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

## Secondary persona

**The multi-framework agent developer** who builds on the OpenAI Agents SDK or LangGraph and exports OTEL traces. Since v1.12.0, `cctx autopsy <trace>` parses OTLP `gen_ai.*` spans and runs the same forensic loop — they get the same findings, costs, and patches without a `~/.claude/projects/` path. This persona arrived with the OTEL parser; the core product surface is still Claude Code.

## What cctx is NOT for

- Teams or organizations (no shared reports, no access control, no multi-user state)
- Ambient monitoring (no daemons, no persistent watcher state, no alerting — `cctx watch` is a foreground command you start and stop)
- General cost dashboards (CodeBurn covers that; cctx is forensic)
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
Seven commands (`ls`, `autopsy`, `harvest`, `watch`, `trace`, `export`, `init`). No command is shallow. `init` is a one-shot installer for the opt-in SessionEnd hook — it does not make cctx ambient (the hook is async, opt-in, and silent on clean sessions). Users should be able to learn the product in an afternoon and trust what it tells them.

## Feature map (v1.18.0)

### Shipped

| Feature | Command | Notes |
|---|---|---|
| Single-session diagnosis | `cctx autopsy <session>` | M2 |
| Cross-session pattern detection | `cctx autopsy <project> --since N` | M2 |
| Cross-project digest | `cctx autopsy --all --since N` | v1.18.0 |
| `--since` string formats | `--since 7d`, `2w`, `2026-05-01`, date ranges | M6+ |
| `--until DATE` on cross-session mode | `autopsy --since ... --until` | v1.2.0 (M12) |
| Interactive aggregate drill-down | select pattern → per-session detail | M6+ |
| HTML report | `cctx autopsy <session> --html FILE` | M2 |
| GitHub Actions job summary | `cctx autopsy --github-summary` | M6+ |
| CI fail gate | `cctx autopsy --fail-on-findings` | M6+ |
| GitHub Action (composite) | `jacquardlabs/cctx@v1` in workflow | M6+ |
| Session trace TUI | `cctx trace <session>` | M3 |
| JSONL / CSV / JSON export | `cctx export <session> --format jsonl\|csv\|json` | M4, JSON v1.2.0 |
| Machine-readable diagnosis | `cctx autopsy <session> --json` (single + `--since` aggregate) | v1.2.0 / v1.10.0 |
| Harvest (CLAUDE.md patcher) | `cctx harvest <session>` | M5 |
| Harvest v2 (multi-target) | patches to `.claude/rules/`, `.claude/skills/` | M6+ |
| Harvest --check depth | `cctx harvest <dir> --check` + `--check-severity` — dead refs, contradiction, redundancy, staleness | v1.4.0 (M13) |
| Cross-session harvest | `cctx harvest <project> --since N` | M5 |
| Cross-agent emit | `cctx harvest --emit agents [--sync]` — mirror CLAUDE.md sections to AGENTS.md | v1.6.0 (M15) |
| Patch efficacy | `cctx harvest --efficacy` — before/after recurrence measurement | v1.9.0 (M17) |
| Session discovery | `cctx ls` / `cctx autopsy --latest` | M6+ |
| Live session badges | `cctx ls` | v1.5.0 |
| Live waste signals + early idle exit | `cctx watch <project>` | M6+, idle exit v1.5.0 |
| Verdict headline + `--top N` + `--turn N` | `autopsy` | v1.1.0 (M9) |
| Project-specific pattern detection | `autopsy`/`harvest` `--since` | v1.3.0 (M14) |
| Per-subagent cost attribution | `cctx autopsy <session>` (subagent cost table) | v1.7.0 (M16) |
| Recursive subagent diagnosis | per-turn classifiers run inside each subagent; findings tagged + attributed | M29 (#156) |
| Health grade + savings framing | `cctx autopsy --health` | v1.14.0 |
| SessionEnd hook installer + quiet mode | `cctx init` / `cctx autopsy --quiet` | v1.11.0 |
| OTEL / multi-framework parsing | `cctx autopsy <otel.jsonl>` — OpenAI Agents SDK, LangGraph | v1.12.0 |

### Pattern classifiers (v1.18.0)

| Pattern | Status |
|---|---|
| Retry loop | Shipped |
| Scope creep | Shipped |
| Stale context | Shipped |
| Dead-end exploration | Shipped (v0.2.0) |
| Tool thrashing | Shipped (v0.2.0) |
| Project-specific patterns (cross-session) | Shipped (v1.3.0) |
| Fan-out waste (subagent overlap + retry) | Shipped (v1.8.0) |
| KV-cache hygiene (hit rate + cause) | Shipped (v1.13.0) |
| Compaction (events + re-fetch waste) | Shipped (v1.15.0) |
| Exploration thrash (read-heavy circling) | Shipped (v1.16.0) |
| Unused context (MCP loaded but never called) | Shipped (v1.17.0) |

## What we are NOT building

- A SaaS or cloud product
- An agent (cctx reads logs; it does not call the Anthropic API except optionally for token counting)
- Provider-specific integrations beyond trace parsing — cctx reads OTEL traces from any framework that exports them (OpenAI Agents SDK, LangGraph), but it does not hook into vendor APIs or dashboards
- A fork-and-replay debugger
- A general eval or testing framework

## Known problems (as of 2026-06-21)

**Active gaps:**

1. **`cctx watch` polling is simple.** Early idle exit via `claude agents --json` has landed, but the watcher still polls at 1s without `fsevents`/`inotify` debouncing.

**Resolved since the prior review:**

- **Subagent diagnosis depth** — the 9 per-turn classifiers now run recursively inside every subagent (grandchildren included), priced at each subagent's own model, with full-accounting waste that dedups against fan-out cost. A retry loop or stale-context buildup *within* a child session is now surfaced and attributed (M29 / #156). Per-subagent cost attribution (v1.7.0, #88) and the fan-out waste classifier (v1.8.0, #89) preceded it.
- **Cross-agent layer** — `harvest --emit agents [--sync]` to AGENTS.md shipped v1.6.0 (M15 / #82). Breadth (`.cursorrules`, `.windsurfrules`, Copilot) remains future work.
- **Harvest feedback loop** — `harvest --efficacy` before/after recurrence measurement shipped v1.9.0 (M17 / #90).
