# Product Health Review — 2026-06-20

**Product:** cctx  
**Version at review:** v1.17.0  
**PRODUCT.md version stamp:** v1.4.0  
**Previous review:** None (first review)

---

## Executive Summary

PRODUCT.md is materially stale. The product is at v1.17.0; PRODUCT.md is stamped v1.4.0 — 13 releases of unrecorded drift. Three of the four "known problems" listed as open are fixed. The classifier list is missing 5 of 11 shipped classifiers. Most significantly, multi-provider support (OpenAI Agents SDK, LangGraph via OTEL) shipped in v1.11.0–v1.12.0, directly crossing two "NOT building" items without any PRODUCT.md update. These are the live disconnects that need resolution, not cosmetic copy cleanup.

---

## Part 1 — Is PRODUCT.md Still True?

### 1. Persona Check

The stated primary persona is "the regular Claude Code user" who is "comfortable with `~/.claude/projects/` on disk." That persona remains accurately served by every feature through v1.10.0.

Starting at v1.11.0 (per-subagent cost attribution) and more clearly at v1.12.0 (OpenAI Agents SDK OTEL parser) and the LangGraph quickstart docs (`98d89d9`), the product began serving a second persona: **the multi-framework agent developer** who runs OpenAI Agents SDK or LangGraph workflows and wants the same forensic diagnosis. This persona is not on `~/.claude/projects/`. They instrument with OTEL. They may not maintain a CLAUDE.md.

The CLAUDE.md "What cctx is NOT for" section still reads "Multi-provider support (Claude Code only in v0/v1)." That constraint was violated intentionally. The persona section must grow or the OTEL work must be characterized as out of scope, neither of which the current PRODUCT.md does.

**Verdict:** Primary persona is accurately described. A second persona has emerged and is unaddressed.

### 2. Principles Check

**Principle 1 — Forensic, not ambient.**

- *Honored:* `cctx watch` remains a foreground command you start deliberately; it has no persistent state.
- *Bent:* `cctx init` installs a `SessionEnd` hook that auto-runs `cctx autopsy --latest --quiet` on every normal session exit. The hook spec (`2026-06-10-init-hook-design.md`) explicitly argues this preserves forensic-first because output appears "only when findings exist" and the hook is opt-in. That argument holds: it's an opt-in installer, runs async, and the quiet flag suppresses clean-session output. The principle survives — but the principle text says "never becomes a daemon, and never holds state between runs." The hook *does not* hold state; the principle technically passes. The description in PRODUCT.md needs a sentence covering the `init` hook so the principle reads coherently for someone evaluating it against this shipped feature.

**Principle 2 — Output must be actionable.**

- *Honored:* Harvest --efficacy (v1.8.0) now closes the loop between findings and whether patches worked — the closest the product comes to measuring its own actionability.
- *Bent:* Not meaningfully bent; the principle remains strong.

**Principle 3 — Honest about uncertainty.**

- *Honored:* Cache hygiene (v1.13.0) reports KV-cache hit rate and cause, explicitly a heuristic. Compaction findings (v1.15.0) surface events rather than claiming precise cost attribution.
- *Bent:* Nothing significant found.

**Principle 4 — Local and stateless.**

- *Honored:* OTEL parser reads from disk (OTEL traces exported to file or piped in); no network dependency added.
- *Not fully addressed:* The principle text says "Live-session detection may shell out to the local `claude` CLI." `cctx init` shelling out during installation is a one-shot write; it doesn't violate statelessness.

**Principle 5 — Deterministic.**

- *Honored:* All 11 classifiers remain heuristic. No LLM calls added to the analysis path.
- *Bent:* Nothing found.

**Principle 6 — Small surface, deep on each command.**

- *Explicitly false:* The principle text states "Six commands (`ls`, `autopsy`, `harvest`, `watch`, `trace`, `export`)." A seventh command, `init`, shipped in v1.11.0. The enumeration in the principle is wrong.

**Verdict:** Principles 1–5 are essentially sound. Principle 6 needs its count updated from six to seven.

### 3. Feature Map Accuracy

The feature map is stamped v1.4.0. Current version is v1.17.0. The following shipped features are absent from or misrepresented in the map:

**Missing from the shipped table:**
- `cctx init` (SessionEnd hook installer + `--quiet` mode) — v1.11.0
- Per-subagent cost attribution in autopsy — v1.7.0 (listed as a known problem fix, never added to map)
- `harvest --efficacy` (patch efficacy report) — v1.8.0
- `harvest --emit` (cross-agent layer, emit to AGENTS.md) — listed as "unreleased" but shipped v1.5.1/#82
- KV-cache hygiene diagnosis (`--health` flag for grade, per-finding savings) — v1.13.0–v1.14.0
- Compaction findings — v1.15.0
- `--health` flag (health grade + savings framing) — v1.14.0
- OTEL parser (OpenAI Agents SDK, LangGraph) — v1.12.0
- `autopsy --quiet` — v1.11.0

**Classifier table (lists 6, codebase has 11):**

The classifier table in PRODUCT.md lists: Retry loop, Scope creep, Stale context, Dead-end exploration, Tool thrashing, Project-specific patterns. Missing:
- Fan-out waste (v1.7.0, M16)
- Cache hygiene (v1.13.0)
- Compaction (v1.15.0)
- Exploration thrash (v1.16.0)
- Unused context / MCP servers loaded but never called (v1.17.0)

**Listed as "unreleased" but actually shipped:**
- `cross-agent emit` (`cctx harvest --emit agents [--sync]`) — shipped v1.5.1 (PR #108)
- `Live session badges` in `cctx ls` — shipped alongside v1.5.0 live-session detection
- `Live session detection, early idle exit` in `cctx watch` — shipped v1.5.0

**Verdict:** Feature map is significantly incomplete. Approximately half of shipped features post-v1.4.0 are unrecorded.

### 4. "Not Building" Check

Two items in "What we are NOT building" have been crossed:

1. **"Multi-provider support (Claude Code only in v0/v1)"** — OpenAI Agents SDK support shipped in v1.12.0 via an OTEL parser (`cctx/parsers/otel.py`). LangGraph was added as a supported framework in docs (`98d89d9`). This is a deliberate strategic expansion, not accidental scope creep. The "NOT building" item is now false.

2. **"What cctx is NOT for: Multi-provider support"** — Same expansion, same verdict.

The other items remain accurate:
- No SaaS or cloud product: still true.
- "An agent": still true; OTEL parser reads exported traces, doesn't call APIs.
- Fork-and-replay debugger: still true.
- General eval or testing framework: still true.

The `--health` flag (health grade A–F based on waste fraction + finding severity) is session-scoped and opt-in. It is not a general cost dashboard. The "cctx is NOT for: General cost dashboards" item is intact.

**Verdict:** Two "not building" items are now false. Both trace to the same strategic call: multi-provider support via OTEL.

### 5. Known Problems Freshness

PRODUCT.md lists four known problems dated 2026-06-09. Three are fixed:

| Problem as listed | Status | Fix |
|---|---|---|
| `cctx watch` polling simple, 1s without debouncing | **Still open** | `watcher.py` confirms `_POLL_INTERVAL = 1.0` with no fsevents/inotify |
| Subagent traces parsed but never diagnosed (M16) | **Fixed** | Per-subagent cost attribution shipped v1.7.0 (#88, #109); fan-out waste classifier shipped v1.7.0 (#89, #110) |
| Cross-agent layer not started (M15/#82) | **Fixed** | `harvest --emit` shipped v1.5.1 (PR #108) |
| Harvest has no feedback loop (M17) | **Fixed** | `harvest --efficacy` shipped v1.8.0 (PR #111) |

Three of the four "known problems" were fixed in the releases that followed the PRODUCT.md update — the document was not kept current after v1.5.1.

**Verdict:** Remove problems 2–4. Retain problem 1 (watch polling). Consider adding new problems — see Part 3.

---

## Part 2 — Product Coherence

### 1. Does This Feel Like One Product?

The core loop (autopsy → harvest → CLAUDE.md → next session is better) is coherent. A new user can walk `ls → autopsy → harvest` in sequence and the hand-offs are clean.

The OTEL path (`cctx autopsy --otel-file ...` or similar) is a seam. It uses the same autopsy command but reads a fundamentally different log format from a different ecosystem. Whether this feels coherent or jarring depends on whether the OTEL persona is included or excluded from the primary persona definition. Right now the mismatch is invisible: PRODUCT.md names a Claude Code persona but the product now serves an OTEL persona too, and nothing in the help text or feature map explains the connection.

The `init` command stands somewhat apart from the forensic flow because it is setup-time, not run-time. That said, it is narrow and its help text is clear. No coherence concern.

### 2. Feature Interaction

Recent additions interact well:

- `cache_hygiene` classifier → `--health` flag → savings framing: these compose naturally across the single-session diagnosis flow.
- `fan_out` classifier → subagent cost attribution → `harvest --emit` (emit to AGENTS.md): a genuine end-to-end chain for agent users.
- `harvest --efficacy` reads patch fingerprints and session dates: the connection between diagnosis and measurement is complete, not bolted on.
- `exploration_thrash` + `unused_context` are the newest classifiers; both produce findings that flow normally to harvest patches.

**Natural connection not yet built:** The `cctx init` hook auto-runs `autopsy --quiet` on session end, but the one-line verdict does not suggest running harvest. A user who sees "2 findings: stale_context, retry_loop" has no in-product prompt to run `cctx harvest`. The `init`→`autopsy`→`harvest` chain has a gap at the last step in quiet mode.

### 3. Complexity Audit

| Feature | If removed, would users notice? | Worth keeping? |
|---|---|---|
| `cctx trace` (TUI) | Yes — visual turn-by-turn replay is differentiated | Yes |
| HTML report (`--html`) | Probably few users use this; no usage data | Questionable |
| JSON export | Useful for CI scripting; pairs with `--github-summary` | Yes |
| `--health` flag | Optional annotation; adds no complexity to the base flow | Yes, low cost |
| `cctx init` | Small setup command; reduces adoption friction meaningfully | Yes |
| OTEL parser | Serves a different user class entirely | Depends on strategy |

No feature warrants removal. The HTML report is the weakest case but low maintenance burden.

### 4. Onboarding Path

**For the Claude Code user (stated persona):**
1. `pip install cctx` — clear.
2. `cctx ls` — shows projects. Works immediately with no config.
3. `cctx autopsy --latest` — runs on most recent session. This is the core value.
4. `cctx harvest --latest` — applies patches to CLAUDE.md.

Time to core value: under 60 seconds if the user has any Claude Code sessions on disk. The path is clean.

**Friction points:**
- `cctx init` is not in the onboarding path but it arguably should be: installing the `SessionEnd` hook on first use means autopsy runs automatically going forward. There's no first-run prompt or suggestion to run `cctx init`.
- The OTEL path has no obvious discovery. An OpenAI Agents SDK user who stumbles on cctx from PyPI has no natural path to finding the OTEL subcommand.

**For the OTEL/multi-framework user (new de facto persona):**
No clear onboarding path exists in the CLI itself. The LangGraph quickstart doc (`docs/`) helps but only if you find it. This is an area to address as the OTEL work matures.

---

## Part 3 — Proposed PRODUCT.md Updates

The following changes are proposed. Not applied — presented for review.

```diff
--- a/PRODUCT.md
+++ b/PRODUCT.md
@@ -10,7 +10,7 @@
 ## Primary persona
 
-**The regular Claude Code user** who:
+**Primary: The regular Claude Code user** who:
 - Runs multiple Claude Code sessions per day across one or more projects
 - Maintains a CLAUDE.md and wants it to get smarter over time
 - Is willing to read a terminal report and act on its suggestions
 - Cares about cost and session quality but does not need a dashboard
 - Is comfortable with the command line and with `~/.claude/projects/` on disk
 
 This persona is already the target; everything shipped to date serves them directly.
 
+**Secondary: The multi-framework agent developer** who:
+- Runs agents built on OpenAI Agents SDK, LangGraph, or other OTEL-instrumented frameworks
+- Wants the same forensic diagnosis on their agent sessions that Claude Code users get
+- Exports OTEL traces and passes them to `cctx autopsy --otel-file`
+- May not use Claude Code or maintain a CLAUDE.md
+
+This persona is served by the OTEL parser (v1.12.0+). The core forensic loop (classify → attribute cost → recommend) is identical; only the log format changes.
+
 ## What cctx is NOT for
 
 - Teams or organizations (no shared reports, no access control, no multi-user state)
 - Ambient monitoring (no daemons, no persistent watcher state, no alerting — `cctx watch` is a foreground command you start and stop)
 - General cost dashboards (CodeBurn covers that; cctx is forensic)
-- Multi-provider support (Claude Code only in v0/v1)
+- Real-time agent telemetry or tracing infrastructure (cctx reads completed logs; it does not instrument running agents)
 - Users who do not read session transcripts or maintain CLAUDE.md
 
 ## Product principles
 
 **1. Forensic, not ambient.**
-cctx is forensic-first: the core use case is "I just ran a session, something went sideways, I want to know what." Live mode (`watch`) is justified only as the same detection running earlier — it surfaces the identical findings, never becomes a daemon, and never holds state between runs.
+cctx is forensic-first: the core use case is "I just ran a session, something went sideways, I want to know what." Live mode (`watch`) is justified only as the same detection running earlier — it surfaces the identical findings, never becomes a daemon, and never holds state between runs. The `cctx init` SessionEnd hook runs `autopsy --quiet` automatically at session end — it is opt-in, async, and outputs nothing on clean sessions, preserving forensic-first by surfacing findings only when they exist.
 
 ...
 
 **6. Small surface, deep on each command.**
-Six commands (`ls`, `autopsy`, `harvest`, `watch`, `trace`, `export`). No command is shallow. Users should be able to learn the product in an afternoon and trust what it tells them.
+Seven commands (`ls`, `autopsy`, `harvest`, `watch`, `trace`, `export`, `init`). No command is shallow. Users should be able to learn the product in an afternoon and trust what it tells them.
 
-## Feature map (v1.4.0)
+## Feature map (v1.17.0)
 
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
 | JSON export | `cctx export <session> --format json` | v1.2.0 (M12) |
 | Harvest (CLAUDE.md patcher) | `cctx harvest <session>` | M5 |
 | Harvest v2 (multi-target) | patches to `.claude/rules/`, `.claude/skills/` | M6+ |
 | Harvest --check | `cctx harvest <dir> --check` — audit for dead refs | M6+ |
 | Cross-session harvest | `cctx harvest <project> --since N` | M5 |
 | Session discovery | `cctx ls` / `cctx autopsy --latest` | M6+ |
 | Live session badges | `cctx ls` | v1.5.0 |
 | Live session detection, early idle exit | `cctx watch` | v1.5.0 |
 | Live waste signals | `cctx watch <project>` | M6+ |
 | Verdict headline + `--top N` + `--turn N` | `autopsy` | v1.1.0 (M9) |
 | `--until DATE` on cross-session mode | `autopsy --since ... --until` | v1.2.0 (M12) |
 | Machine-readable diagnosis | `cctx autopsy <session> --json` | v1.2.0 (M12) |
 | Project-specific pattern detection | `autopsy`/`harvest` `--since` | v1.3.0 (M14) |
 | Memory-hygiene depth | `harvest --check` + `--check-severity` | v1.4.0 (M13) |
+| Per-subagent cost attribution | `cctx autopsy` | v1.7.0 (M16) |
+| Cross-agent emit | `cctx harvest --emit agents [--sync]` | v1.5.1 (M15/#82) |
+| Fan-out waste classifier | `autopsy` | v1.7.0 (M16) |
+| Patch efficacy report | `cctx harvest --efficacy` | v1.8.0 (M17) |
+| SessionEnd hook installer | `cctx init` | v1.11.0 (M19) |
+| Autopsy quiet mode | `cctx autopsy --quiet` | v1.11.0 (M19) |
+| KV-cache hygiene diagnosis | `autopsy` | v1.13.0 |
+| Health grade + savings framing | `cctx autopsy --health` | v1.14.0 |
+| Compaction findings | `autopsy` | v1.15.0 |
+| OTEL parser (OpenAI Agents SDK, LangGraph) | `cctx autopsy` (auto-detected) | v1.12.0 |
 
-### Pattern classifiers (v1.4.0)
+### Pattern classifiers (v1.17.0)
 
 | Pattern | Status |
 |---|---|
 | Retry loop | Shipped |
 | Scope creep | Shipped |
 | Stale context | Shipped |
 | Dead-end exploration | Shipped (v0.2.0) |
 | Tool thrashing | Shipped (v0.2.0) |
 | Project-specific patterns (cross-session) | Shipped (v1.3.0) |
+| Fan-out waste | Shipped (v1.7.0) |
+| Cache hygiene | Shipped (v1.13.0) |
+| Compaction | Shipped (v1.15.0) |
+| Exploration thrash | Shipped (v1.16.0) |
+| Unused context (MCP servers) | Shipped (v1.17.0) |
 
 ## What we are NOT building
 
 - A SaaS or cloud product
 - An agent (cctx reads logs; it does not call the Anthropic API except optionally for token counting)
-- Multi-provider support (Claude Code only in v0/v1)
+- Real-time agent telemetry or tracing infrastructure
 - A fork-and-replay debugger
 - A general eval or testing framework
 
-## Known problems (as of 2026-06-09)
+## Known problems (as of 2026-06-20)
 
 **Active gaps:**
 
 1. **`cctx watch` polling is simple.** Early idle exit via `claude agents --json` has landed, but the watcher still polls at 1s without `fsevents`/`inotify` debouncing.
 
-2. **Subagent traces are parsed but never diagnosed.** The parser models subagent sessions recursively and the tokenizer counts their tokens, but no classifier or cost attribution reads `trace.subagents`. Autopsy is blind to spend inside agent fan-outs. (M16)
-
-3. **Cross-agent layer not started.** Tracked as M15 / #82 — the final step of the original growth staircase.
-
-4. **Harvest has no feedback loop.** Nothing measures whether an applied patch reduced the recurrence of the pattern it targeted, even though patches carry fingerprints and sessions carry dates. (M17)
+2. **OTEL persona has no onboarding path in the CLI.** An OpenAI Agents SDK or LangGraph user who installs cctx from PyPI cannot discover the OTEL parser or its invocation from `cctx --help` alone. Needs a `cctx docs` pointer or a README quickstart surface in the help text.
+
+3. **`cctx init` → harvest chain is incomplete in quiet mode.** When the SessionEnd hook fires and prints a one-line verdict, there is no in-product prompt to run `cctx harvest`. The full `init → autopsy → harvest` automation loop requires a follow-on step: either emit the harvest command in the quiet verdict, or add a `cctx init --auto-harvest` option.
```

---

## Summary of Findings

| Area | Finding | Severity |
|---|---|---|
| Feature map version stamp | PRODUCT.md says v1.4.0; product is at v1.17.0 | High |
| "Not building" list | "Multi-provider support (Claude Code only)" is false — OTEL/OpenAI shipped v1.12.0 | High |
| Known problems | 3 of 4 listed problems are fixed; list is stale | High |
| Classifier table | Lists 6 classifiers; codebase has 11 | High |
| Principle 6 | Says "Six commands" — there are now 7 | Medium |
| Feature map completeness | ~10 shipped features missing from the map | Medium |
| Persona | Secondary OTEL persona is unacknowledged | Medium |
| Principle 1 | `cctx init` hook not addressed; principle text technically holds but reads inconsistently | Low |
| New problem: OTEL onboarding gap | No CLI discovery path for OTEL persona | Medium |
| New problem: init → harvest gap | Quiet verdict doesn't close the harvest loop | Low |
