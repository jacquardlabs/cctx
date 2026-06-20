# Architecture Review — cctx — 2026-06-20

**Baseline.** No prior architecture reviews existed when this ran (the `docs/jaqal/architecture-reviews/` directory did not yet exist; the review was returned inline and persisted here afterward). This is the first one.

**Version reviewed:** v1.17.0 (the review predates the v1.18.0 cross-project-digest release by hours).

---

## Part 1 — Map What Exists

### 1. Dependency Graph

The system is a strict linear pipeline with one shared schema hub:

```
JSONL / OTLP file on disk
        |
        v
   parsers/
   ├── claude_code.py    (690 lines, Claude Code JSONL)
   └── otel.py           (347 lines, OTLP/gen_ai.* spans)
        |
        v  SessionTrace
   tokenizer.py          (78 lines)
        |
        v  SessionTrace (token counts populated)
   diagnostician/
   ├── __init__.py       (198 lines — orchestrator)
   ├── inflection.py
   ├── patterns/         (10 classifiers × ~60–120 lines each)
   └── aggregate.py      (42 lines — cross-session, imports parsers + tokenizer directly)
        |
        v  Diagnosis
   recommender/
   ├── claude_md.py      (225 lines)
   └── evidence.py       (129 lines)
        |
        v  Diagnosis (with Patches)
   renderers/
   ├── terminal.py       (536 lines)
   ├── github.py
   ├── report.py         (Jinja2 HTML)
   └── trace_tui.py      (Textual)
        |
        v
   exporters/
   ├── jsonl.py
   └── csv.py
```

Shared schema hub (imported by every other layer): `models.py` (369 lines).

Cross-cutting modules that don't fit the pipeline:
- `harvest.py` (572 lines) — append-only CLAUDE.md writer + git audit + emit/sync
- `discovery.py` (186 lines) — filesystem navigator for `~/.claude/projects/`
- `pricing.py` (18 lines) — cost lookup table
- `agents.py` (66 lines) — shells out to `claude agents --json`
- `hook_installer.py` (101 lines) — installs SessionEnd hook
- `watcher.py` (180 lines) — poll-based live session monitor
- `cli.py` (859 lines) — entry point, routes all 6 subcommands

**Clusters.** Three tight clusters:
1. Parser cluster — `parsers/claude_code.py` + `parsers/otel.py` + `models.py`
2. Diagnostician cluster — `diagnostician/__init__.py` + all 10 pattern files + `pricing.py` + `models.py`
3. Recommender cluster — `recommender/claude_md.py` + `recommender/evidence.py` + `models.py`

**Boundaries.** Renderers and exporters are genuinely isolated — swapping `terminal.py` for `report.py` does not change any number. The parser→tokenizer→diagnostician sequence is also clean at the data model boundary: each stage takes a `SessionTrace` and returns one.

### 2. Actual vs. Documented Architecture Style

Documented style (CLAUDE.md): linear layered pipeline, 5 classifiers, 5 modules in the project layout.

Actual style: linear layered pipeline with a shared schema hub — this part is accurate and clean. However:

- **10 pattern classifiers** are shipping. CLAUDE.md lists 5 (`retry_loop`, `scope_creep`, `stale_context`, `tool_thrash`, `dead_end`). Missing: `fan_out`, `cache_hygiene`, `compaction`, `exploration_thrash`, `unused_context`, `project_specific`.
- **CLAUDE.md project layout section omits 6 modules** that are now load-bearing: `agents.py`, `pricing.py`, `hook_installer.py`, `parsers/otel.py`, `exporters/json.py` (if it exists), and arguably `watcher.py` (listed but described differently).
- **Multi-provider scope.** CLAUDE.md and PRODUCT.md say "Claude Code only." But `parsers/otel.py` (347 lines), `cli._detect_source()`, and a committed `docs/quickstart-otel.md` covering OpenAI Agents SDK and LangGraph confirm multi-provider support is shipped and intentional. This is doc-lag, not an accident.
- **PRODUCT.md "Known problems" are stale.** It lists "subagent traces parsed but never diagnosed (M16)" — `SubagentAttribution` and fan-out cost attribution now exist in `diagnostician/__init__.py`. It lists "harvest has no feedback loop (M17)" — `evidence.efficacy()` + `EfficacyReport` + `harvest --efficacy` are shipped. The code is ahead of its own product document.
- **Aggregate orchestration.** `diagnostician/aggregate.py` is documented as an analyzer, but it directly imports and calls `parse_session` and `tokenize_session`. It is an orchestrator, not an analyzer, and it lives in the wrong package. (The same orchestration logic is partially duplicated in `cli.py`'s `autopsy --since` path.)

### 3. Load-Bearing Modules (by distinct importing files)

| Rank | Module | Import count |
|------|--------|-------------|
| 1 | `cctx.models` | 47 |
| 2 | `cctx.discovery` | 9 |
| 3 | `cctx.harvest` | 6 |
| 4 | `cctx` (package `__init__`) | 4 |
| 5 | `cctx.parsers.claude_code` | 3 |
| 6 | `cctx.tokenizer` | 3 |
| 7 | `cctx.exporters.jsonl` | 3 |
| 8 | `cctx.pricing` | 3 |
| 9 | `cctx.agents` | 2 |
| 10 | `cctx.diagnostician` | 2 |

`cctx.models` at 47 imports is in a tier of its own. A breaking change to any dataclass cascades to every layer. `cctx.discovery` at 9 is the second-highest — it's imported by `cli.py`, `watcher.py`, `aggregate.py`, `agents.py`, and renderers. `cctx.harvest` at 6 is imported across cli, renderers, and tests.

### 4. Core Journey Data Flows

**Journey 1: `cctx autopsy <session.jsonl>`**

```
cli.py:autopsy_cmd
  → _detect_source(path) → "claude_code" or "otel"
  → parse_session(path) / parse_otel_file(path) → SessionTrace
  → tokenize_session(trace) → SessionTrace (tokens filled)
  → diagnostician.run(trace) → Diagnosis (raw, no patches)
  → recommender.generate(diagnosis) → Diagnosis (with Patches)
  → terminal.render_diagnosis(diagnosis) or report.render_html(...)
```

Path is clean. The only wrinkle is that `_detect_source` lives in `cli.py` rather than the parsers package — a caller-side sniffing decision that makes sense but means any future parser (e.g., LangSmith) requires touching `cli.py`.

**Journey 2: `cctx autopsy <project> --since 7d`**

```
cli.py:autopsy_cmd (--since branch)
  → discovery.list_sessions(project_dir) → list of session paths
  → for each: parse_session → tokenize_session → diagnostician.run → recommender.generate
  [OR via aggregate.run(project_dir, start, end) which duplicates the above]
  → evidence.accumulate(diagnoses) → dict[FindingKind, KindEvidence]
  → recommender.generate_from_evidence(evidence) → list[Patch]
  → terminal.render_aggregate(report)
```

There is a structural seam issue here: the per-session pipeline is expressed twice — once directly in `cli.py`'s `--since` branch and once inside `diagnostician/aggregate.py`. The `aggregate.py` path is the cleaner one but the CLI sometimes bypasses it.

**Journey 3: `cctx harvest --apply`**

```
cli.py:harvest_cmd
  → [optional: autopsy pipeline to get patches if not --apply-all]
  → harvest.preview_patches(patches) → list of (patch, applicable bool)
  → harvest.apply_patches(patches, target_dir) → list of HarvestResult
  → terminal.render_harvest_results(results)
```

Path is clean. `harvest.py`'s fingerprint-based idempotency handles re-runs correctly.

**Journey 4: `cctx watch`**

```
cli.py:watch_cmd
  → discovery.latest_session(project_dir) → path
  → watcher.watch(path, callback) [poll loop at 1s]
      → parse_session(path) on each tick
      → diagnostician.run(trace) → Diagnosis
      → callback renders findings via watcher.py's own print() calls
```

Path is functional but not architecturally clean: `watcher.py` outputs directly via `print()` rather than using `renderers/terminal.py`. This is documented as intentional in the module's docstring but creates a secondary rendering path.

---

## Part 2 — Evaluate

### Boundaries

**Aligned with product concepts or technical layers?**

The primary axis is correct: the package names (`parsers`, `diagnostician`, `recommender`, `renderers`, `exporters`) map directly to pipeline stages, not to generic technical categories like "controllers" or "services." This is a genuine strength — a developer asked "where does token counting happen?" or "where do patches get generated?" has a clear answer.

**Cross-cutting concerns.**

Two concerns are re-implemented rather than centralized:

1. **Error absorption.** Every pattern classifier wraps its body in `try/except Exception: return []`. This is the right behavior but expressed 10 times. If the policy ever changes (e.g., log the error, attach a warning to the Diagnosis), all 10 files need touching. The `diagnostician.__init__.run()` orchestrator is the right place for this wrapper.

2. **Rendering.** `cli.py`'s `_render_check_findings()` (lines 150–181) uses `rich.Console` and `rich.Rule` directly. It belongs in `terminal.py`. Meanwhile `watcher.py` uses bare `print()`. Two rendering paths exist outside the `renderers/` package.

**Could you delete one feature module without breaking unrelated features?**

Yes, mostly. Removing any single pattern classifier from `diagnostician/patterns/` only requires removing its import from `diagnostician/__init__.py`. Removing a renderer requires removing its CLI invocation. The coupling is contained.

The exception is `harvest.py` — it imports from `models.py` (for MANAGED_HEADINGS), calls `discovery.py`, shells out to git, and is called from `cli.py`, `renderers/terminal.py` (for efficacy), and tests. It's the module most entangled with everything else.

### Complexity Distribution

**Where is complexity concentrated?**

Appropriately: the diagnostician is the most complex layer (10 classifiers, inflection detection, cost attribution, fan-out deduplication) and that complexity is justified — it's the core business logic.

Inappropriately:

- **`cli.py` at 859 lines.** It contains: argument parsing, orchestration of the full per-session pipeline, orchestration of the `--since` aggregate pipeline, interactive aggregate drilldown, source-format detection, `parse_since()` (a 70-line date parser), and `_render_check_findings()` (rendering logic). This is approaching god-object territory for a routing module.

- **`harvest.py` at 572 lines.** It handles: fingerprint-based patch application, CLAUDE.md auditing (`check_claude_md`), managed section heading discovery via git pickaxe (`managed_heading_dates`), patch retargeting (`retarget_patches`), emit to `AGENTS.md` (`sync_managed_sections`), and deduplication. That is 5–6 distinct responsibilities in one file.

- **`models.py` carries MANAGED_HEADINGS and `group_into_exchanges()`.** The constants are a reasonable home (models.py is the single source of truth for cross-layer shared data). The helper function is a minor exception to "pure data containers" but is low-risk.

**Unnecessary abstraction layers?**

No. The pipeline stages map 1-to-1 with product concepts. There are no intermediate facades or unnecessary wrappers.

**God objects?**

`cli.py` is the closest. It routes 6 subcommands but also orchestrates 2–3 pipelines directly. `harvest.py` is the second — its breadth of responsibility is wide for a single module.

### Evolution Readiness

**What will change most in the next 3–6 months** (per PRODUCT.md and open specs):

1. **Cross-agent emit (M15)** — emit patches to `AGENTS.md`, `.cursorrules`, `.windsurfrules`, GitHub Copilot instructions. The seam exists: `EMIT_TARGETS = {"agents": "AGENTS.md"}` in `harvest.py` and `retarget_patches()`. The architecture can accommodate additional targets without structural change, but `harvest.py`'s mixed responsibilities will make the sync logic harder to extend cleanly.

2. **Subagent-aware diagnosis (M16)** — per PRODUCT.md, the known problem is "subagent traces parsed but never diagnosed." This is now partially incorrect: `fan_out.py` exists and `SubagentAttribution` flows through `Diagnosis`. What's still missing is a full classifier that walks `trace.subagents` recursively and emits findings for child session patterns. The seam (subagents field on `SessionTrace`) is there. One new classifier in `diagnostician/patterns/` is the only required change.

3. **Patch efficacy (M17 area)** — `evidence.efficacy()` and `EfficacyReport` are shipped but the feedback loop PRODUCT.md describes (cctx learns that a past patch reduced a finding) is incomplete. The architecture is structured for this: efficacy runs through the recommender. No structural changes needed.

4. **New model pricing** — `pricing.py` uses a hardcoded dict of 3 model families. Every new model family (e.g., Claude Sonnet 5, Haiku 5) requires a code change. The prefix-matching approach is correct but the data source is fragile.

**Are high-change areas structured to accommodate change?**

Pattern classifiers: yes. Adding a new classifier is a 3-step operation: write the file, add it to `diagnostician/__init__.py`'s call list, add a template to `recommender/claude_md.py`. The pattern is repetitive by design — that's a feature.

Emit targets: partially. `harvest.py`'s `sync_managed_sections` and `EMIT_TARGETS` handle a fixed list. Adding a new target format (e.g., `.windsurfrules` with a different section syntax) would require extending a few branches in `harvest.py`, not a new file. This is acceptable but watch the complexity ceiling.

Parser addition: the `_detect_source` pattern in `cli.py` requires a new branch per parser. If a third format (LangSmith, Weights & Biases) is added, the detection logic should move from `cli.py` into a parser registry in `parsers/__init__.py`.

### Data Layer

cctx has no database. The "data layer" is: parsers read JSONL from disk, `harvest.py` appends to CLAUDE.md on disk, `discovery.py` navigates `~/.claude/projects/`. Mapping the standard data-layer rubric:

**Schema normalization.** `Finding.evidence: dict[str, Any]` carries a different implicit schema per `FindingKind`. The stale-context classifier puts `{"stale_items": [...], "total_token_turns": N}` in this dict. The retry-loop classifier puts `{"occurrences": [...], "loop_length": N}`. There is no runtime type enforcement. `recommender/claude_md.py:summarize()` accesses `ev.get("occurrences", [])` and silently falls back to `finding.summary` on a miss. This is the closest structural smell to a denormalized blob — it's trading type safety for flexibility. The tradeoff is acceptable in v0 but will accumulate drift as evidence shapes evolve per classifier.

**Queries that bypass the data access layer.** `diagnostician/aggregate.py` calls `parse_session` and `tokenize_session` directly. This isn't a bypass (there's no ORM to bypass) but it is the one place in the codebase where the pipeline is re-orchestrated outside `cli.py`, creating the dual-path issue described in the Journey 2 trace.

**Reversibility.** `harvest.py`'s `apply_patches` is append-only and idempotent (fingerprint-based deduplication prevents double-application). There is no `un-harvest` operation. A patch applied cannot be reverted programmatically — only manually. This is a documented design constraint (append-only), not an accident. The managed-section sync (`sync_managed_sections`) can overwrite, but not roll back.

**Data that has outgrown its storage.** `managed_heading_dates` in `harvest.py` reconstructs the git commit timestamp for each managed heading by running a `git log -S` pickaxe search at runtime. This couples efficacy computation to git history and is slow on large repos. If the project moves to multi-target emit (several output files), git pickaxe per heading per file per run will become a performance problem.

---

## Part 3 — Recommendations

### Finding 1 — `CLAUDE.md` and `PRODUCT.md` are significantly out of date

**Classification: REFACTOR NOW** — *(resolved by PR #147, 2026-06-20)*

Both documents are authoritative per CLAUDE.md's own rules. They were not. CLAUDE.md's project layout section listed 5 classifiers (10 shipped), omitted 6 modules, and described the scope as Claude Code only when multi-provider support is shipped with a committed quickstart. PRODUCT.md listed 2 known problems that are at least partially solved.

**Action:** Update CLAUDE.md's project layout to reflect all classifiers and missing modules; add multi-provider parsing; update PRODUCT.md status. *(Done in PR #147.)*

### Finding 2 — `compute_health_grade()` violates the "renderers never compute analysis" rule

**Classification: REFACTOR NOW** — *(tracked: #133)*

`compute_health_grade()` lives in `renderers/terminal.py` and computes an A–F grade from `diagnosis.waste_cost_usd`, `diagnosis.total_cost_usd`, and finding severity. This is analytical logic. The HTML renderer would need its own copy or would have to import `terminal.py` to reuse it.

**Action:** Move `compute_health_grade(diagnosis) -> str` to `models.py` as a method on `Diagnosis` (or a standalone diagnostician function).

### Finding 3 — `discovery.py` imports `click`

**Classification: REFACTOR NOW** — *(tracked: #134)*

`discovery.py:complete_project()` does `from click.shell_completion import CompletionItem`. CLAUDE.md rule: "Only `cli.py` imports `click`."

**Action:** Move `complete_project()` into `cli.py`; `discovery.py` exposes `list_projects()` and the CLI wraps results in `CompletionItem`.

### Finding 4 — `_render_check_findings()` rendering logic lives in `cli.py`

**Classification: REFACTOR NOW** — *(tracked: #135)*

`cli.py:_render_check_findings()` creates a `rich.Console`, formats severity badges, and renders issue labels. It belongs in `terminal.py`.

**Action:** Move to `terminal.py` as `render_check_results(findings, target_dir, console=None) -> None`.

### Finding 5 — `diagnostician/aggregate.py` is an orchestrator masquerading as an analyzer

**Classification: REFACTOR BEFORE cross-agent emit (M15) and subagent diagnosis (M16)** — *(tracked: #141)*

`aggregate.run()` imports `parse_session`, `tokenize_session`, and runs the full per-session pipeline. The `--since` aggregate pipeline is expressed twice.

**Action:** Move `aggregate.py` to `cctx/aggregate.py` (or `cctx/orchestration.py`). Make `cli.py`'s `--since` path go exclusively through it.

### Finding 6 — Per-classifier `try/except` blocks should be centralized

**Classification: REFACTOR BEFORE adding more classifiers** — *(tracked: #137)*

All 10 classifiers wrap their body in `try/except Exception: return []`.

**Action:** Add a single `_safe_classify(fn, trace)` wrapper in `diagnostician/__init__.py`.

### Finding 7 — `Finding.evidence: dict[str, Any]` is a schema-less blob

**Classification: DESIGN DECISION NEEDED** — *(tracked: #145)*

Every `Finding` carries an `evidence` dict whose shape varies by `FindingKind`. No type enforcement.

- **Option A:** Document the expected evidence shape per `FindingKind`. Low-cost now, accumulates drift.
- **Option B:** Per-kind Evidence dataclasses. Higher initial cost, type-safe.

Recommendation: Option A with good docstrings if classifiers stay at 10–12. Option B if a third consumer of evidence appears.

### Finding 8 — `harvest.py` has too many responsibilities

**Classification: REFACTOR BEFORE cross-agent emit (M15)** — *(tracked: #140)*

`harvest.py` (572 lines) handles patch application, CLAUDE.md auditing, git pickaxe, retargeting, and emit/sync.

**Action:** Split into `harvest.py` (apply/idempotency/preview) and `emit.py` (`sync_managed_sections`, `retarget_patches`, `EMIT_TARGETS`, `managed_heading_dates`).

### Finding 9 — `pricing.py` hardcodes a 3-entry model table

**Classification: DOCUMENT AND ACCEPT (for now)** — *(tracked: #145)*

Each new model family requires a code change. For a 3-row table, that's the correct tradeoff. Add a comment and a default-fallback sanity test.

### Finding 10 — Source-format detection lives in `cli.py`

**Classification: DOCUMENT AND ACCEPT** — *(documented in CLAUDE.md by PR #147)*

`cli._detect_source()` reads the first lines of a trace file. Adding a parser requires touching `cli.py`. Accept; document the convention.

---

## Priority Order

1. **Finding 1 (documentation).** *(Done — PR #147.)*
2. **Finding 2 (`compute_health_grade`).** #133
3. **Finding 3 (`click` import in discovery.py).** #134
4. **Finding 4 (`_render_check_findings`).** #135
5. **Finding 6 (centralize classifier error handling).** #137
6. **Finding 5 (aggregate.py orchestrator).** #141 — before M15/M16
7. **Finding 8 (harvest.py split).** #140 — prep for M15
8. **Finding 7 (evidence dict schema).** #145 — defer/monitor
9. **Finding 9 (pricing hardcoding).** #145 — document and accept
10. **Finding 10 (source detection in cli.py).** Documented.
