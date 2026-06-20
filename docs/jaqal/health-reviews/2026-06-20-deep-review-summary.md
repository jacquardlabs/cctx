# Deep Review Summary — cctx — 2026-06-20

**Version reviewed:** v1.17.0 (branch `docs/readme-gaps`, HEAD 88d0d55)
**Reviews run:** Codebase health · Frontend/TUI health · Architecture · Product health
**Prior deep review:** none (first run — all metrics are baseline)

---

## Cross-Review Findings (Systemic Issues)

These findings appear in 2 or more reviews. They are structural, not isolated.

### S1 — Documentation drift: all three authoritative docs are 13+ versions stale (ALL 4 reviews)

Every review surfaced this independently. The docs that are supposed to be authoritative are describing a product that no longer exists.

| Doc | Stamped version | Current version | Gap |
|-----|----------------|-----------------|-----|
| `CLAUDE.md` project layout | v0.2.0 / M7 | v1.17.0 / M21+ | 15 minor releases |
| `PRODUCT.md` feature map | v1.4.0 | v1.17.0 | 13 minor releases |
| `DESIGN.md` | v0.2 era | v1.17.0 | 3 finding kinds documented, 11 shipped |

Concrete errors across the three docs:
- CLAUDE.md lists 5 classifiers — 12 are shipped
- CLAUDE.md project layout omits 4 load-bearing modules: `agents.py`, `pricing.py`, `hook_installer.py`, `parsers/otel.py`
- PRODUCT.md says "Claude Code only" — OTEL/OpenAI Agents SDK support shipped v1.12.0
- PRODUCT.md "Known problems" #2 and #4 are resolved; #3 is resolved — still listed as open
- PRODUCT.md classifier table shows 6 — codebase runs 11
- DESIGN.md says kind-based verdict is "future, not yet implemented" — it is live in terminal.py
- DESIGN.md kind label table shows 3 kinds — 11 shipped

**Impact:** New agents (and humans) build against a stale mental model. The architecture review flagged that a contributor following CLAUDE.md today would not understand 35% of the source tree. For a project whose product value proposition is keeping CLAUDE.md accurate, this is the most pointed irony in the codebase.

### S2 — KIND_LABEL coverage gaps cause live rendering bugs (Frontend + Codebase health)

The codebase has 11 `FindingKind` values. Three separate rendering surfaces have not kept up:

1. **HTML report** (`autopsy --html`): CSS badge rules exist only for 3 original kinds. Any session with `TOOL_THRASH`, `DEAD_END`, `FANOUT_WASTE`, `CACHE_HYGIENE`, `COMPACTION`, `EXPLORATION_THRASH`, `UNUSED_CONTEXT`, or `PROJECT_PATTERN` findings renders invisible badges — text against a matching background, no contrast.
2. **GitHub summary** (`github.py`): local `_KIND_LABEL` dict has 5 entries. 6 kinds fall through to `f.kind.value` — raw enum strings like `fanout_waste` instead of `FANOUT WASTE`.
3. **TUI FindingModal** (`trace_tui.py:115`): uses `f.kind.value` directly. Displays `retry_loop` where the rest of the product displays `RETRY LOOP`.

All three violate DESIGN.md's explicit anti-pattern: "Never use the raw enum value in user-facing output."

Root cause: `models.py` `KIND_LABEL` is the single source of truth (imported correctly by `terminal.py`), but renderers added after the original 3 kinds either defined their own local dict or used raw `.value`. No test exercises the newer kinds through the HTML renderer, which is why C1 survived.

### S3 — Rendering logic outside the renderers/ package (Architecture + Frontend)

Three rendering functions live outside `cctx/renderers/`:

- `cli.py:_render_check_findings()` (lines 150–181) — creates `rich.Console`, formats severity badges, defines local `_ISSUE_LABEL` / `_SEV_BADGE` dicts. Belongs in `terminal.py`.
- `watcher.py` — outputs via bare `print()`. No renderer is invoked.
- `renderers/terminal.py:compute_health_grade()` — computes an A–F analytical grade from diagnosis fields. Analytical logic living in a renderer; the HTML renderer cannot reuse it without importing `terminal.py`.

The `cli.py` case creates a second rendering path that `--github-summary` and `--html` cannot share.

### S4 — `cli.py` and `harvest.py` are accumulating responsibility (Architecture + Codebase health)

`cli.py` (859 lines, highest churn) currently contains: argument parsing, per-session pipeline orchestration, `--since` aggregate pipeline orchestration, interactive drilldown, source-format detection, date parsing (`parse_since`, 70 lines), and rendering (`_render_check_findings`). This is approaching god-object territory for a routing module.

`harvest.py` (572 lines) handles: fingerprint-based patch application, CLAUDE.md auditing, git pickaxe heading timestamps, patch retargeting, and emit/sync to external agent files — 5–6 distinct responsibilities. Before M15 cross-agent emit adds `.cursorrules`, `.windsurfrules`, and GitHub Copilot targets, this file needs to be split.

---

## Prioritized Action Plan

### Critical (this week)

**C1 — Update CLAUDE.md project layout and build order** *(Systemic S1)*
Add all 12 classifiers, all 4 missing modules, update build order through M21, add multi-provider note for OTEL. A contributor following today's CLAUDE.md would not know `pricing.py`, `agents.py`, `hook_installer.py`, or `parsers/otel.py` exist.

**C2 — Fix HTML badge CSS for 8 of 11 finding kinds** *(Systemic S2, Frontend C1)*
File: `cctx/renderers/templates/autopsy.html.j2`. Add CSS rules for `tool_thrash`, `dead_end`, `fanout_waste`, `cache_hygiene`, `compaction`, `exploration_thrash`, `unused_context`, `project_pattern`. Simplest fix: neutral fallback rule `.badge[class*="kind-"] { background: #2d333b; color: #e6edf3; }` plus per-kind colors where semantics exist.

**C3 — Fix github.py KIND_LABEL for 6 of 11 finding kinds** *(Systemic S2, Frontend C2)*
File: `cctx/renderers/github.py`. Replace local 5-entry string-keyed dict with `from cctx.models import KIND_LABEL`. Key by `FindingKind` enum member, not `.value` string.

### Important (this month)

**I1 — Update PRODUCT.md** *(Systemic S1, Product health)*
Update version stamp to v1.17.0. Add 7 classifiers to the classifier table (total: 11). Add `cctx init` as the 7th command. Mark known problems #2, #3, #4 as resolved. Add OTEL/multi-provider section. Remove "Claude Code only" from positioning (or add "also ships" carve-out).

**I2 — Update DESIGN.md** *(Systemic S1, Frontend I6)*
- Add all 11 `FindingKind` members to the kind label table
- Correct verdict format section: kind-based format is live in `terminal.py`; count-based is used by TUI and HTML — declare which is canonical
- Add `.3f` subagent cost format to the cost formatting table
- Remove all "v0.2 TODO" annotations from evidence rendering table
- Add anti-pattern: "Never define `_KIND_LABEL` locally inside a renderer; import from `cctx.models.KIND_LABEL`"

**I3 — Move `compute_health_grade()` out of terminal.py** *(Architecture F2)*
File: `cctx/renderers/terminal.py:48`. Move to `cctx/models.py` as a method on `Diagnosis` or to `cctx/diagnostician/__init__.py`. It's analytical logic (produces a grade from cost ratios), not presentation.

**I4 — Move click import out of discovery.py** *(Architecture F3, layering rule violation)*
File: `cctx/discovery.py:170`. Move `complete_project()` to `cli.py` as a private shell-complete callback. `discovery.py` exposes `list_projects() -> list[ProjectInfo]`; the CLI wraps results in `CompletionItem`.

**I5 — Move `_render_check_findings()` to terminal.py** *(Systemic S3, Architecture F4, Frontend I5)*
File: `cctx/cli.py:150–181`. Extract to `terminal.py` as `render_check_results(findings, target_dir, console=None)`. Enables `--github-summary` and HTML paths to share the output.

**I6 — Fix TUI FindingModal and harvest patch panel title** *(Systemic S2, Frontend I1/I2)*
- `cctx/renderers/trace_tui.py:115` — replace `f.kind.value` with `KIND_LABEL[f.kind]`
- `cctx/renderers/terminal.py:341` — replace `finding_kind.value` with `KIND_LABEL[result.patch.finding_kind]`

**I7 — Centralize per-classifier try/except** *(Architecture F6)*
All 10 pattern classifiers have identical `try/except Exception: return []` wrappers. Move policy to `diagnostician/__init__.py` as `_safe_classify(fn, trace)`. Remove individual wrappers. When the error policy changes, change one place.

**I8 — Fix Diagnosis.verdict capitalization** *(Frontend I4)*
File: `cctx/models.py:276`. Change `"clean session"` to `"Clean session"`. Terminal inherits lowercase; all other surfaces hard-code the capitalized form.

**I9 — Resolve verdict format inconsistency across surfaces** *(Frontend I3)*
Terminal renders kind-based (`"RETRY LOOP + SCOPE CREEP"`) from `Diagnosis.verdict`. TUI and HTML render count-based (`"N findings · $X.XX waste"`). Declare one canonical format in DESIGN.md, update the other two surfaces to match.

### Track (next review cycle)

**T1 — Split harvest.py before M15 cross-agent emit** *(Architecture F8)*
At 572 lines with 5–6 responsibilities, adding 3 new emit targets will push `harvest.py` past manageable complexity. Proposed split: `harvest.py` (patch application, fingerprinting, preview) + `emit.py` (sync_managed_sections, retarget_patches, EMIT_TARGETS, git pickaxe functions).

**T2 — Restructure aggregate.py as an orchestrator** *(Architecture F5)*
`diagnostician/aggregate.py` imports `parse_session` and `tokenize_session` and re-orchestrates the per-session pipeline — the same logic duplicated in `cli.py`'s `--since` branch. Move to `cctx/aggregate.py` and route `cli.py --since` exclusively through it. Do before M16 subagent diagnosis adds per-subagent pipeline calls.

**T3 — Update anthropic SDK** *(Codebase health T8)*
Installed `0.102.0`, current `0.111.0`. 9 minor versions is the largest runtime dep drift. Update to pick up security patches.

**T4 — Fix rich-click deprecation warnings** *(Codebase health T9)*
82 test warnings fire `PendingDeprecationWarning: use_rich_markup= will be deprecated... use text_markup= instead`. Switch to `text_markup=`.

**T5 — trace_tui.py test coverage** *(Codebase health T6, Frontend T1)*
`TraceTUI` Textual app class (220 lines, 4 nested classes in `launch()`) is at 21% coverage. Intentional — Textual Pilot async tests are deferred. Monitor as Textual's async Pilot API matures; the nested-class structure makes unit testing harder regardless.

**T6 — Add renderer test cases for newer finding kinds** *(Frontend T7)*
`test_terminal_renderer.py` and `test_report.py` fixture factories cover only 3 original kinds. Adding `TOOL_THRASH` and `FANOUT_WASTE` through the HTML renderer would have caught C2 before it shipped.

**T7 — Document Finding.evidence schema** *(Architecture F7)*
`Finding.evidence: dict[str, Any]` carries a different implicit schema per `FindingKind`. Currently accessed with `.get()` fallbacks in `recommender/claude_md.py`. Acceptable for now; add a docstring per kind documenting the expected keys. Revisit if a third consumer beyond the recommender appears.

**T8 — Document pricing.py update requirement** *(Architecture F9)*
3-entry hardcoded model table with prefix matching; correct tradeoff for a 3-row table. Add a comment noting this file requires updates when new model families ship. Add a test asserting the default fallback is within a reasonable range.

**T9 — `_wide_console()` dead code in terminal.py** *(Frontend T2)*
Defined at `terminal.py:43`, never called. Delete or promote to use in the efficacy table render path.

**T10 — `group_into_exchanges()` unused by renderers** *(Frontend T3)*
Defined in `models.py:342`, has tests, but no renderer imports it. Either promote to use or move to a utility module to clarify intent.

---

## Proposed Context Doc Updates

These are presented for review — not applied. Three docs need updates; changes are ordered by severity.

### CLAUDE.md

**Project layout section** — add 4 missing modules:
```
├── agents.py           # claude agents --json live-session query; consumed by ls and watcher
├── hook_installer.py   # cctx init SessionEnd hook install/remove
├── pricing.py          # per-token price table; single source of truth for cost computation
├── parsers/
│   ├── claude_code.py  # SHIPPED.
│   └── otel.py         # SHIPPED. OTLP/OpenAI Agents SDK parser (v1.12.0).
```

**Diagnostician patterns** — add 7 classifiers to the layout:
```
│   ├── fan_out.py
│   ├── cache_hygiene.py
│   ├── compaction.py
│   ├── exploration_thrash.py
│   ├── unused_context.py
│   ├── project_specific.py
```

**Build order** — add M8 through M21 block (or link to CHANGELOG for the full history).

**Tech stack / Architecture sections** — add sentence: "Multi-provider: `parsers/otel.py` enables diagnosis of OpenAI Agents SDK and LangGraph traces exported via OTLP. Same `SessionTrace` output as the Claude Code parser."

**Layering rules** — add: "When adding a parser, add a branch to `cli._detect_source()`. When adding an emit target, extend `EMIT_TARGETS` in `harvest.py` / `emit.py`."

### PRODUCT.md

**Version stamp** — update to v1.17.0.

**Classifier table** — add all 11 classifiers currently in `diagnostician/patterns/`. Remove "unreleased" tags from cross-agent emit, live session badges, live idle exit.

**"Six commands" principle** — update to "Seven commands" (add `init`).

**"What cctx is NOT for" / "What we are NOT building"** — remove or qualify "Multi-provider support (Claude Code only in v0/v1)." Suggested replacement: "General observability dashboards — cctx diagnoses specific sessions, not aggregate cost tracking across all sessions."

**Known problems** — mark #2 (subagent diagnosis), #3 (cross-agent emit), #4 (harvest feedback loop) as resolved. Keep #1 (watch polling at 1s, no debouncing) as open.

**Persona section** — add secondary persona: "Multi-framework agent developer using OpenAI Agents SDK or LangGraph who exports OTLP traces and wants the same forensic loop without the `~/.claude/projects/` path."

### DESIGN.md

**Finding kind labels table** — expand from 3 to all 11 current `FindingKind` members. Point to `models.py KIND_LABEL` as the canonical source.

**Verdict string section** — declare one canonical format; correct the "future, not yet implemented" claim about kind-based verdicts.

**Cost formatting table** — add `.3f` row for subagent individual cost line items.

**Evidence rendering table** — remove all "v0.2 TODO" annotations. Describe current state.

**Anti-patterns section** — add: "Never define `_KIND_LABEL` locally inside a renderer; import from `cctx.models.KIND_LABEL` and key by `FindingKind` enum member, not `.value` string."

---

## Metrics Dashboard

| Metric | Value | Trend vs last review |
|--------|-------|---------------------|
| Lines of code (src + tests) | 18,687 | Baseline |
| Source lines (`cctx/` only) | 7,293 | Baseline |
| Test lines (`tests/` only) | 7,807 | Baseline |
| Test coverage (overall) | 88% | Baseline |
| Source files | 40 | Baseline |
| Test files | 52 | Baseline |
| Passing tests | 640 | Baseline |
| Skipped / xfail tests | 0 | Baseline |
| TODO/FIXME (real) | 0 | Baseline |
| Outdated runtime deps | 4 | Baseline |
| Known vulnerabilities | 1 (pip only, not runtime) | Baseline |
| Largest source file | `cli.py` — 859 lines | Baseline |
| Classifiers shipped | 12 | Baseline |
| CLAUDE.md documented through | M7 / v0.2.0 | Baseline |
| Current version | v1.17.0 | Baseline |
| Design system deviations | 6 | Baseline |
| KIND_LABEL implementations | 3 (models.py canonical, github.py local, HTML inline) | Baseline |
| HTML badge CSS gaps | 8 of 11 finding kinds unstyled | Baseline |
| Renderer test gaps (newer kinds) | 8 of 11 kinds untested in terminal/HTML | Baseline |

*All trends marked "Baseline" — no prior deep review exists for comparison.*

---

## Source Reports

- Codebase health: `docs/jaqal/health-reviews/2026-06-20-health-review.md`
- Product health: `docs/jaqal/product-reviews/2026-06-20-product-review.md`
- Architecture review: returned inline (directory `docs/jaqal/architecture-reviews/` did not exist)
- Frontend/TUI health: returned inline (directory `docs/jaqal/frontend-reviews/` did not exist)
