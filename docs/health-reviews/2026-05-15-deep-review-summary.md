# cctx Deep Review — Master Summary
**Date:** 2026-05-15
**State:** M5 complete, entering M6 (release prep / v0.1.0)
**Reviews run:** Codebase health · Frontend health · Architecture · Product health

Individual reports:
- `docs/health-reviews/2026-05-15-health-review.md`
- `docs/frontend-reviews/2026-05-15-frontend-review.md`
- `docs/architecture-reviews/2026-05-15-architecture-review.md`
- `docs/product-reviews/2026-05-15-product-review.md`

---

## Bottom line

The codebase is in genuinely good shape: 250 tests green, 81% coverage, zero layering violations, zero TODO/FIXME debt, lint clean. The product concept is coherent and persona-aligned — no scope drift. **The primary pre-release problem is that the public-facing documents (brief, pyproject.toml) do not match the shipped product.** Beyond that, two active correctness bugs are shipping to users today (wrong CSV costs, misleading TUI turn highlighting), and two design problems in the HTML renderer need fixing (dead diff CSS, red=success color inversion in terminal).

---

## Cross-review findings (systemic — appear in 2+ reviews)

These are elevated because they indicate structural patterns, not one-off mistakes.

### S1: Cost numbers are wrong in CSV export
**Codebase health + Architecture**

`_price_per_tok` is duplicated in `diagnostician/__init__.py` and `exporters/csv.py`. The diagnostician version correctly applies cache_read (×0.10) and cache_write (×1.25) multipliers. The CSV exporter does not. A user who exports to CSV and compares the `cost_usd` column against `Diagnosis.total_cost_usd` sees different numbers with no explanation — the CSV is undercounting by a significant margin (cache_read alone can be 400× larger than input_tokens in real sessions).

**Fix:** Extract a `cctx/pricing.py` module (<20 lines). Both callers import from it. Update the CSV exporter to apply the same cache multipliers, or explicitly document the column as "input tokens only, excluding cache."

### S2: Tokenizer is documented as a live pipeline stage but is never called
**Architecture + Codebase health + Product health**

`CLAUDE.md` shows `Parser → Tokenizer → Diagnostician`. The tokenizer module exists and is tested. `cli.py` never calls `tokenize_session()`. As a result, `stale_context.py` always uses `_estimate_tokens()` (word count × 1.3) because `tr.token_count` is always 0. This is undocumented and contradicts the architecture diagram.

**Decision needed:** Option A — wire in `tokenize_session()` between parse and diagnose in `cli.py`; in `CCTX_OFFLINE=1` mode the existing word-count fallback activates automatically, so behavior is unchanged for CI/offline users. Option B — remove the tokenizer from the architecture diagram, make the estimation explicit in output, archive the module. The product's cost-accuracy pitch makes Option A more defensible.

### S3: Documentation out of sync with shipped scope — release blocker
**Codebase health + Product health**

Multiple doc-vs-reality divergences, all blocking M6 PyPI publish:

| Document | Claim | Reality |
|---|---|---|
| `cctx-project-brief.md` | 5 pattern classifiers | 3 shipped |
| `cctx-project-brief.md` | `--since 7d`, `--since 2w`, `--until`, `--top N` | Integer days only |
| `cctx-project-brief.md` | `export --format html/json/csv/jsonl` | jsonl + csv only; html is `autopsy --html` |
| `cctx-project-brief.md` | Interactive aggregate with drill-down | Read-only static table |
| `cctx-project-brief.md` | `Verdict: ⚠ retry loop + scope creep` headline | Not in renderer |
| `CLAUDE.md` project layout | `exporters/html.py`, `exporters/json.py` | Files don't exist |
| `CLAUDE.md` project layout | No `harvest.py` entry | File exists, 173 lines |
| `pyproject.toml` readme | `cctx-project-brief.md` (internal design doc) | Needs user-facing `README.md` |
| `pyproject.toml` description | "Profile, debug, and optimize Claude Code and Agent SDK sessions" | No Agent SDK support; no "optimize" |
| `pyproject.toml` version | `0.0.1` | Needs bump to `0.1.0` for M6 |

### S4: Missing test coverage in high-churn renderer code
**Codebase health + Frontend health**

- `renderers/terminal.py` — 57% coverage. `render_aggregate` and `render_harvest_results` have zero tests. Both are exercisable via `Console(file=StringIO())` capture tests.
- `cli.py` — 68% coverage, 5 commits (highest churn). The entire `--since` cross-session path (lines 62–76) has never been tested. This is the highest-risk untested path: most-changed file, non-trivial branching, real user journey.
- `renderers/trace_tui.py` — 14% (Textual App body); pure helpers are 100% tested.

### S5: Repeated pipeline pattern in CLI — pre-watch-mode technical debt
**Architecture + Codebase health**

All four single-session command handlers contain:
```python
trace = parse_session(target)
diagnosis = diagnostician.run(trace)
diagnosis = claude_md.generate(diagnosis)
```
Adding the tokenizer (S2 fix) requires patching four places. Adding `cctx watch` would need a fifth. Extract `run_single_session(path) -> tuple[Diagnosis, SessionTrace]` in `cctx/pipeline.py` before that milestone.

---

## Prioritized action plan

### Critical (this week — correctness bugs and release blockers)

**C1. Fix CSV cost column (S1)** — Ships wrong numbers to users today.
Extract `cctx/pricing.py`. Update `exporters/csv.py` to apply cache multipliers. ~20 lines total.

**C2. Fix `render_harvest_results` color inversion (frontend)**
`ApplyStatus.APPLIED` renders in red; `ApplyStatus.ERROR` and `ApplyStatus.SKIPPED` both render dim — errors are visually indistinguishable from benign skips. Fix: green for APPLIED, red for ERROR, dim for SKIPPED. In `cctx/renderers/terminal.py` line ~150.

**C3. Fix dead CSS in HTML diff blocks (frontend)**
`autopsy.html.j2` defines `.add` and `.del` CSS classes for diff line coloring but the template renders `p.unified_diff` as raw text with no `<span>` wrapping. Add a Jinja2 filter in `report.py` that wraps `+`-prefixed lines in `<span class="add">` and `-`-prefixed lines in `<span class="del">`. Zero external dependencies needed.

**C4. Start M6 release prep — address S3 doc blockers**
Write user-facing `README.md`. Update `pyproject.toml` description and readme field. Version bump to `0.1.0`. These must land before PyPI publish.

### Important (this month / before v0.1.0 ships)

**I1. Decide and implement tokenizer strategy (S2)**
Pick Option A (wire it in) or Option B (remove from architecture). Document the decision. If Option A: `cli.py` adds one line per command handler, or extract pipeline helper first (S5).

**I2. Update CLAUDE.md layout to match disk (S3)**
Add `harvest.py` entry. Remove phantom `exporters/html.py` and `exporters/json.py` entries. Update build order to mark M5 as shipped.

**I3. Update brief to match shipped scope (S3)**
Narrow classifier count to 3. Fix `--since` examples to integer-only. Update export format list. Remove or demote unshipped verdict headline and interactive aggregate mock. This is also fixing the PyPI readme.

**I4. Fix `affected_turns` TUI bug (frontend + architecture)**
`trace_tui.py:affected_turns()` uses `frozenset(range(first_turn, last + 1))` for all finding kinds. Per the trace-tui spec §2.3, correct behavior is:
- `retry_loop` → `{occ["turn"] for occ in evidence["occurrences"]}`
- `scope_creep` → `{ph["turn"] for ph in evidence["phrases"]}`
- `stale_context` → `range(item["last_referenced_turn"] + 1, last_turn + 1)` per stale item

Currently the TUI flags every turn between first and last as problematic, including turns the classifier never touched. Misleads users.

**I5. Add missing renderer and CLI integration tests (S4)**
- `tests/renderers/test_terminal.py` — `render_aggregate` and `render_harvest_results` via `Console(file=StringIO())`
- `tests/test_cli.py` — `--since` cross-session path (needs a temp project dir with 1+ session files)

**I6. Fix `recommender/claude_md.py` coverage gaps (codebase health)**
Lines 67, 72–75, 81–82 (`summarize()` match arms) and line 113 (`kind not in _TEMPLATES` guard) are the primary user-facing output path and have no tests. Add fixture-based tests in `tests/recommender/`.

### Track (next review cycle)

| Item | Review(s) | Check at |
|---|---|---|
| Extract `pipeline.py` helper (S5) | Architecture, Codebase | Before `cctx watch` (M7) |
| Relocate `aggregate.py` cross-boundary orchestrator | Architecture | When `pipeline.py` created |
| `Finding.evidence: dict[str, Any]` → typed per-kind dataclasses | Architecture | Before new classifiers in harvest v1 |
| Cost precision consistency: `.2f` terminal vs `.4f` HTML | Frontend | Next renderer touch |
| Verdict format standardization across surfaces (3 different formats) | Frontend | Before v0.2 |
| HTML evidence rendered as raw JSON dumps — needs per-kind structured templates | Frontend | Before v0.2 |
| TUI Textual App coverage via `App.run_test()` pilot | Codebase | M3 follow-up |
| `aggregate.py` cross-session path integration test | Codebase | S4 work |
| `rich_click` deprecation warning (`use_rich_markup=` → `text_markup=`) | Codebase | When upstream ships fix |
| Terminal renderer comment fix: "avoid circular import" → accurate explanation | Architecture | Next terminal.py touch |
| TUI spec gap: ~60% of spec'd keybindings/widgets not shipped (severity coloring, `t`, `c`, `r`, `g`, filter dialog, inflection gutter indicator) | Frontend | M3 completion sprint |

---

## Context doc updates proposed

These are proposals only — do not apply without review.

### CLAUDE.md proposed changes

**Add `harvest.py` to project layout:**
```diff
 ├── recommender/
 │   ├── claude_md.py    # Finding -> Patch (CLAUDE.md diff proposals)
 │   └── evidence.py     # session-count + dollar evidence accumulation
+├── harvest.py          # SHIPPED. apply_patch, preview_patches, apply_patches
+│                       # Append-only, idempotent CLAUDE.md patching with
+│                       # fingerprint-based dedup (first ## heading).
```

**Remove phantom exporters from layout:**
```diff
 └── exporters/
     ├── jsonl.py
     ├── csv.py
-    ├── html.py
-    └── json.py
```

**Update build order:**
```diff
-3. **M2 — Autopsy v0.** Single-session diagnosis + cross-session pattern detection. The wedge product. (#9, #10, #40–#49)
-4. **M3 — Trace TUI** with autopsy overlay. (#20, #21)
-5. **M4 — Export.** jsonl + csv + html + json. (#24, #27)
-6. **M5 — Harvest v1.** Promote autopsy findings to durable CLAUDE.md / rules / skill / ADR diffs. (Issues TBD after autopsy lands.)
+3. **M2 — Autopsy v0.** SHIPPED. Single-session + cross-session diagnosis, terminal renderer, HTML report. (#9, #10, #40–#49, #58, #59)
+4. **M3 — Trace TUI.** SHIPPED. Textual TUI with autopsy finding overlay. (#20, #21, #57)
+5. **M4 — Export.** SHIPPED. jsonl + csv exporters. (html moved to autopsy --html; json deferred) (#24, #27, #54)
+6. **M5 — Harvest v0.** SHIPPED. Apply autopsy patches to CLAUDE.md (CLAUDE.md target only in v0). (#56)
```

**Update architecture diagram (tokenizer decision pending):**
If Option A (wire it in):
```diff
 Parser           ← dependency-free; takes a path, returns SessionTrace
   ↓
-Tokenizer        ← only place that imports anthropic; offline-mode safe for CI
+Tokenizer        ← only place that imports anthropic; populates Turn.token_count.
+                   CCTX_OFFLINE=1 uses word-count heuristic (same as before).
   ↓
 Diagnostician
```

If Option B (remove):
```diff
 Parser           ← dependency-free; takes a path, returns SessionTrace
   ↓
-Tokenizer        ← only place that imports anthropic; offline-mode safe for CI
-  ↓
 Diagnostician    ← stale-context token costs use word-count heuristic (×1.3).
```

### PRODUCT.md — create new file
The product review proposes a full `PRODUCT.md` draft in `docs/product-reviews/2026-05-15-product-review.md` (Part 3). Key sections: persona, principles (6), feature map v0.1.0, NOT building list, known problems. Recommend creating `PRODUCT.md` at repo root from that draft before M6 ships.

### DESIGN.md — create new file
The frontend review proposes a `DESIGN.md` (or `docs/design-system.md`) to codify decisions already made implicitly across surfaces. Key entries: severity color palette, cost formatting standard (`.2f` user-facing), kind label canonical form, verdict format, evidence rendering per surface, anti-patterns (no red for success, no raw JSON evidence dumps). Recommend creating before adding a 4th renderer.

---

## Metrics dashboard

| Metric | Value | Trend vs last review |
|---|---|---|
| Source LOC (`cctx/`) | 2,781 | Baseline |
| Test LOC (`tests/`) | 4,881 | Baseline |
| Test-to-code ratio | 1.76:1 | Baseline |
| Test coverage (overall) | 81% | Baseline |
| Tests passing | 250 / 250 | Baseline |
| Skipped / xfail tests | 0 | Baseline |
| TODO/FIXME (production) | 0 | Baseline |
| Ruff lint errors | 0 | Baseline |
| Outdated dependencies | 1 (ruff patch) | Baseline |
| Known vulnerabilities | 0 | Baseline |
| Layering violations | 0 | Baseline |
| Source files | 24 | Baseline |
| Test files | 30 | Baseline |
| Renderer files | 4 | Baseline |
| Dead CSS rules | 2 (`.add`, `.del` in HTML template) | Baseline |
| Pricing duplication sites | 2 | Baseline |
| CLI commands | 4 | Baseline |
| Active correctness bugs | 2 (CSV costs, TUI affected_turns) | Baseline |
| Component count | N/A (no web frontend) | — |
| Bundle size | N/A (local CLI) | — |
| Design system deviations | 3 (cost precision, verdict format, color inversion) | Baseline |
