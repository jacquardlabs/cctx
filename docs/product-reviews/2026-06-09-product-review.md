# cctx Product Health Review — 2026-06-09

Second review. Prior review: `2026-05-15-product-review.md`. Source of product truth: `PRODUCT.md` (created from the prior review's draft), with `cctx-project-brief.md` as the original pitch and growth staircase.

**Headline: the growth staircase is one step from complete.** Every milestone from the original brief — autopsy, cross-session, harvest, memory hygiene, live mode — has shipped. The issue board holds three open issues, one of which (#80) actually shipped in v1.4.0. The only substantive roadmap item left is the cross-agent layer (#82, M15). The product needs two things now: PRODUCT.md brought up to date (it describes v0.2.0; reality is v1.4.0+), and a deliberate decision about what comes after the staircase.

---

## Part 1 — Is PRODUCT.md still true?

### 1. Persona check

Everything shipped since the last review — M9 polish (verdict headline, `--top`, `--turn`), M11 GitHub Action, M12 output completeness (`--until`, `autopsy --json`, `export --format json`), M13 harvest `--check` depth, M14 project-specific patterns, and the unreleased live-session integration — serves the same single developer reviewing their own sessions. No team features, no dashboards, no hypothetical users.

**Verdict: no persona drift.** The discipline noted in the prior review has held through eight releases.

### 2. Principles check

**P1 — Forensic, not ambient.** *Bent, deliberately.* `cctx watch` (M10) and the in-flight `claude agents --json` live integration (live badges in `cctx ls`, early idle exit in the watcher) are real-time features. The staircase sanctioned this as v2 ("Live mode — optional"), so it is roadmap-aligned, not drift — but PRODUCT.md's principle text and its "NOT for: real-time monitoring" line now contradict the shipped product. The doc must evolve: forensic-first, with live mode as an explicitly opt-in companion.

**P2 — Output must be actionable.** Honored. M14 project-specific patterns emit CLAUDE.md patches via `generate_from_patterns()`; harvest `--check` depth findings carry severity and location.

**P3 — Honest about uncertainty.** Honored. The prior review's gap (cost confidence not surfaced) was fixed in #69 — terminal and HTML output annotate costs as ~85–95% estimates.

**P4 — Local and stateless.** Honored, with one footnote: the live path now shells out to the `claude` CLI (`claude agents --json`). Still local, no network, gracefully degrades when the binary is absent — but it is the first external-binary dependency in any code path and should be named in the principle.

**P5 — Deterministic.** Fully honored. All four new analysis surfaces since the last review (tool-thrash, dead-end, project-specific patterns, check-depth detectors) are heuristic — Jaccard similarity, keyword matching, n-gram overlap. No LLM calls anywhere outside the opt-in tokenizer.

**P6 — Small surface, deep on each command.** The text says "Four commands." There are six: `ls`, `autopsy`, `export`, `trace`, `harvest`, `watch`. The spirit holds — each verb is deep and the surface is learnable in an afternoon — but the letter is false.

### 3. Feature map accuracy

PRODUCT.md is headed "Feature map (v0.2.0)". The released version is **v1.4.0** (2026-05-20), with live-session integration unreleased on main. Missing from the map:

| Shipped feature | Where | Version |
|---|---|---|
| Verdict headline | `autopsy` terminal output | v1.1.0 (M9) |
| `--top N` on cross-session autopsy | `autopsy --since` | v1.1.0 (M9) |
| `--turn N` drill-down | `autopsy` | v1.1.0 (M9) |
| `--until DATE` | `autopsy --since` | v1.2.0 (M12) |
| Machine-readable diagnosis | `autopsy --json` | v1.2.0 (M12) |
| JSON export | `export --format json` | v1.2.0 (M12) |
| Project-specific pattern detection | `autopsy --since` / `harvest --since` | v1.3.0 (M14) |
| Contradiction / redundancy / staleness detectors | `harvest --check`, `--check-severity` | v1.4.0 (M13) |
| Live session badges | `cctx ls` | unreleased |
| Live session detection + early idle exit | `cctx watch` | unreleased |

The classifier table is also incomplete: project-specific patterns (M14) is a sixth detection surface alongside the five listed.

### 4. "Not building" check

- "Real-time monitoring (completed sessions only in v0 and v1)" — **crossed**, per the staircase's own v2 plan. Remove from the NOT-for list; replace with what genuinely stays out (background daemons, persistent monitoring state, alerting).
- No SaaS, no agent behavior, no multi-provider, no fork-and-replay, no eval framework — all still clean. `claude agents --json` is reading local state from a local binary, not provider expansion.

### 5. Known problems freshness

1. **"watch polling is simple"** — partially fixed. Early idle exit via `claude agents --json` landed (unreleased); 1s polling without fsevents/inotify remains. Update, don't remove.
2. **"`--format json` on export not shipped"** — **fixed in v1.2.0**. Remove.
3. **"Cross-agent layer not started… no milestone yet"** — stale. It now has milestone M15 and issue #82. Update.

**New problems to add:**
4. **Subagent traces are parsed but never diagnosed.** The parser recursively parses subagent sessions (`models.py:151`, `parsers/claude_code.py:165`), the tokenizer counts their tokens, but no classifier or cost attribution ever reads `trace.subagents`. As agent fan-out becomes the dominant Claude Code workflow, autopsy is blind to where an increasing share of the spend goes.
5. **Issue board hygiene.** #80 shipped in v1.4.0 (PR #87) but is still open. #85 has no milestone.
6. **Roadmap exhaustion.** After M15 there is no defined direction. Not a bug — but the next planning conversation is overdue.

---

## Part 2 — Product coherence

### One product?

Yes — more so than at the last review. The loop now has a clean narrative arc that matches a real day: `cctx ls` (what sessions exist, which are live) → `cctx watch` (catch waste during) → `cctx autopsy` (diagnose after) → `cctx harvest` (persist the lesson) → `harvest --check` (keep the memory honest). `trace` and `export` are the inspection/escape hatches. Every command operates on the same `SessionTrace → Diagnosis → Patch` chain.

### Feature interaction

- `ls` ↔ `watch` via live badges: good new connection (unreleased).
- `autopsy → harvest`: still the spine, now strengthened by M14 (cross-session patterns produce evidence-backed patches).
- **Gap: `watch` findings are ephemeral.** A waste signal surfaced live evaporates when the session ends; the user must re-run autopsy to act on it. A natural connection — watch ending with "run `cctx autopsy --latest` to harvest these findings" or writing a findings stub — is unbuilt.
- **Gap: harvest never learns whether its patches worked.** Patches carry fingerprints and sessions carry dates; nothing compares pattern recurrence before/after a patch was applied. This is the strongest unbuilt connection in the product (see proposals).

### Complexity audit

Nothing is deadweight. `trace` (Textual TUI) remains the highest-maintenance surface relative to use; acceptable while it stays stable. The two JSON outputs (`autopsy --json` vs `export --format json`) are different shapes for different purposes (diagnosis vs raw turns) — fine, but the README should say which to use when.

### Onboarding

Dramatically improved since the last review: `pip install cctx` → `cctx ls` → `cctx autopsy --latest` is a genuine under-60-second path, and the README exists. Remaining friction: a clean session yields "no findings," which still reads anticlimactic on a first run — consider always showing the cost/token decomposition so a clean session still demonstrates value.

---

## Part 3 — Proposed PRODUCT.md updates

Presented as a diff; not applied.

```diff
--- PRODUCT.md
+++ PRODUCT.md
@@ -5,7 +5,8 @@
 cctx is a local Python CLI that reads Claude Code session logs and tells you what went wrong, why it cost what it did, and what to add to your CLAUDE.md so it doesn't happen again.

-It is a forensic tool, not a monitoring tool. You reach for it after a session — when something felt off, when the bill was higher than expected, or on a weekly review pass.
+It is forensic-first. You reach for it after a session — when something felt off, when the bill was higher than expected, or on a weekly review pass. `cctx watch` extends the same waste detection into a live, opt-in companion for an active session; it is a foreground command you run deliberately, not background infrastructure.

@@ -20,9 +21,9 @@
 ## What cctx is NOT for

 - Teams or organizations (no shared reports, no access control, no multi-user state)
-- Real-time monitoring (completed sessions only in v0 and v1)
+- Ambient monitoring (no daemons, no persistent watcher state, no alerting — `cctx watch` is a foreground command you start and stop)
 - General cost dashboards (CodeBurn covers that; cctx is forensic)
 - Multi-provider support (Claude Code only in v0/v1)
 - Users who do not read session transcripts or maintain CLAUDE.md

@@ -30,8 +31,8 @@
 **1. Forensic, not ambient.**
-cctx is used after something goes wrong, not as background infrastructure. Every feature should be justified by this use case: "I just ran a session, something went sideways, I want to know what."
+cctx is forensic-first: the core use case is "I just ran a session, something went sideways, I want to know what." Live mode (`watch`) is justified only as the same detection running earlier — it surfaces the identical findings, never becomes a daemon, and never holds state between runs.

@@ -39,7 +40,7 @@
 **4. Local and stateless.**
-No network calls in the core analysis path (tokenizer may call the API for token counting; that is opt-in). No persistent database. No telemetry. No account. Users own their data.
+No network calls in the core analysis path (tokenizer may call the API for token counting; that is opt-in). Live-session detection may shell out to the local `claude` CLI and degrades gracefully without it. No persistent database. No telemetry. No account. Users own their data.

@@ -45,7 +46,7 @@
 **6. Small surface, deep on each command.**
-Four commands. No command is shallow. Users should be able to learn the product in an afternoon and trust what it tells them.
+Six commands (`ls`, `autopsy`, `harvest`, `watch`, `trace`, `export`). No command is shallow. Users should be able to learn the product in an afternoon and trust what it tells them.

@@ -48,2 +49,2 @@
-## Feature map (v0.2.0)
+## Feature map (v1.4.0)

@@ (append to Shipped table)
+| Verdict headline + `--top N` + `--turn N` | `autopsy` | v1.1.0 (M9) |
+| `--until DATE` on cross-session mode | `autopsy --since ... --until` | v1.2.0 (M12) |
+| Machine-readable diagnosis | `cctx autopsy <session> --json` | v1.2.0 (M12) |
+| JSON export | `cctx export <session> --format json` | v1.2.0 (M12) |
+| Project-specific pattern detection | `autopsy`/`harvest` `--since` | v1.3.0 (M14) |
+| Memory-hygiene depth | `harvest --check` + `--check-severity` | v1.4.0 (M13) |
+| Live session badges | `cctx ls` | unreleased |
+| Live session detection, early idle exit | `cctx watch` | unreleased |

@@ (classifier table)
+| Project-specific patterns (cross-session) | Shipped (v1.3.0) |

@@ -90,12 +99,14 @@
-## Known problems (as of 2026-05-16)
+## Known problems (as of 2026-06-09)

-1. **`cctx watch` polling is simple.** Polls every 1s and re-runs classifiers on any file growth. Does not debounce or use `fsevents`/`inotify`. Fine for v0 but will chatter on active sessions.
+1. **`cctx watch` polling is simple.** Early idle exit via `claude agents --json` has landed, but the watcher still polls at 1s without `fsevents`/`inotify` debouncing.

-2. **`--format json` on `export` not shipped.** `--html` moved to `autopsy --html`; `json` format on the `export` subcommand is still deferred.
+2. **Subagent traces are parsed but never diagnosed.** The parser models subagent sessions recursively and the tokenizer counts their tokens, but no classifier or cost attribution reads `trace.subagents`. Autopsy is blind to spend inside agent fan-outs.

-3. **Cross-agent layer not started.** Emitting findings as `.cursorrules`, `AGENTS.md`, `.windsurfrules`, or GitHub Copilot instructions is a roadmap item with no milestone yet.
+3. **Cross-agent layer not started.** Tracked as M15 / #82 — the final step of the original growth staircase.
+
+4. **Harvest has no feedback loop.** Nothing measures whether an applied patch reduced the recurrence of the pattern it targeted, even though patches carry fingerprints and sessions carry dates.
```

---

## Issue board actions

1. **Close #80** — shipped in v1.4.0 via PR #87 (`check_contradictions`/`check_redundancy`/`check_staleness` + `--check-severity` are on main). Close with a comment linking the PR.
2. **#85 (fuzzy/semantic normalization, M14 Option B)** — assign a milestone or label it explicitly as icebox. As written it risks drifting toward embedding/LLM territory; if pursued, constrain to deterministic techniques (stemming, edit distance) per P5.
3. **#82 (M15 cross-agent layer)** — the committed next milestone. Note: emitting `AGENTS.md`/`.cursorrules` partially relaxes "multi-provider support" in the NOT-for list; the distinction worth preserving is *we write other agents' config formats; we do not parse other agents' logs*.

## Post-staircase feature proposals

Ranked by leverage. All are deterministic, local, and persona-aligned.

**1. Subagent-aware diagnosis (highest leverage).** The data model is already built — parser recurses into subagent sessions, tokenizer counts them — only the analysis is missing. Ship: (a) per-subagent cost attribution in the autopsy decomposition ("$1.84 of $3.10 went to 7 subagents"), (b) a fan-out waste classifier (overlapping subagent work, failed-and-retried agents, subagent results never referenced by the parent). Claude Code's evolution (Task tool, workflows, parallel agents) makes this the fastest-growing blind spot in the product.

**2. Patch efficacy tracking.** `harvest` patches carry fingerprints; sessions carry dates. Compare pattern recurrence before/after a patch's application date: "retry-loop fired in 5 sessions the week before the 2026-05-20 patch; 0 since." This converts cctx from *suggesting* improvements to *proving* them — no other tool in the space closes this loop, and it requires no new data collection.

**3. Loaded-but-never-used context waste (MCP servers / skills).** Extend the brief's binary waste decision to context overhead: MCP tool definitions and skills that are loaded into every request but never invoked across N sessions. Finding: "MCP server X adds ~8K tokens/request and was never called in 30 sessions — disable it for this project." Binary signal, high confidence, directly actionable patch (settings change).

**4. `cctx init` — SessionEnd hook installer.** The biggest adoption friction is remembering to run cctx. A command that installs an opt-in Claude Code SessionEnd/Stop hook running `cctx autopsy --latest --quiet` and printing a one-line verdict *only when findings exist*. Preserves forensic-first (output appears only when something went sideways) while removing the memory burden.

**5. Compaction findings.** Compaction events are already detected (classifiers reset on them) but never reported. Promote to a finding: compaction count, content re-fetched after compaction (re-reading a file that was compacted away is concrete, attributable waste), and a "compact earlier" recommendation when stale context preceded a forced compaction.

**6. Cross-project digest.** `cctx autopsy --all --since 7d` — the persona's stated "weekly review pass" currently requires running per-project. Aggregate the aggregates; lowest effort of the six.

Suggested sequencing: board hygiene now → M15 (#82) finishes the staircase → M16 subagent-aware diagnosis → M17 patch efficacy. Items 3–6 slot in as polish-scale milestones between or after.
