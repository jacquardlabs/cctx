# cctx codebase health review — 2026-05-15

Baseline review (first in series). Conducted at M5 completion / M6 release-prep entry.

---

## Summary

The codebase is in strong shape for a project that just shipped M2–M5 in rapid succession. The layering invariants the architecture depends on are clean — no forbidden cross-boundary imports detected. The test suite passes (250/250) with 81% overall coverage and a test-to-code ratio of 1.76:1 (4,881 test LOC vs. 2,781 source LOC). The biggest structural concerns are: (1) `cctx/harvest.py` exists on disk but is absent from the documented project layout in `CLAUDE.md`, indicating documentation drift; (2) `_price_per_tok` is duplicated in `diagnostician/__init__.py` and `exporters/csv.py` with slightly different implementations; and (3) `cctx/renderers/trace_tui.py` has 14% coverage because the Textual `App` subclass body is untestable without a running terminal, and no headless test strategy exists yet. The codebase has zero TODO/FIXME debt comments in production code, no skipped or xfail tests, and lints clean under ruff.

---

## Critical (address this week)

**None.** No issues were found that are actively causing broken behavior or are one merge away from doing so. All tests pass; all layering invariants hold; no known vulnerabilities found.

---

## Important (address this month)

### 1. `harvest.py` is undocumented in CLAUDE.md layout

`cctx/harvest.py` (173 lines, `ApplyStatus`, `ApplyResult`, `apply_patch`, `preview_patches`, `apply_patches`) shipped in M5 (#56) but the `CLAUDE.md` project layout section was not updated. New contributors working from the documented layout will not find it, and the build order section still lists M5 as "Issues TBD after autopsy lands." The brief also has no matching entry. This is documentation drift — the code is correct, the map is wrong.

Files to update: `CLAUDE.md` (project layout block, build order block).

### 2. `_price_per_tok` duplicated across `diagnostician` and `exporters/csv`

Two independent copies of the same function exist:

- `cctx/diagnostician/__init__.py:33` — used for cost attribution in Findings
- `cctx/exporters/csv.py:30` — used for per-turn cost rows in CSV export

Both use the same price table (`claude-opus-4: 15.0`, `claude-sonnet-4: 3.0`, `claude-haiku-4: 0.8`). The implementations are functionally equivalent (verified by inspection) but textually different — the diagnostician version guards with `if model and model.startswith(...)`, the CSV version with `if model is not None`. When prices change (they will), both copies need updating. The canonical home should be `cctx/models.py` (shared data layer, no layer violations) or a new `cctx/pricing.py` utility, imported by both consumers.

### 3. `cctx/exporters/html.py` and `cctx/exporters/json.py` documented but not shipped

`CLAUDE.md`'s project layout lists four exporters: `jsonl.py`, `csv.py`, `html.py`, `json.py`. Only the first two exist. `html.py` and `json.py` are documented as part of M4 but were not implemented. Either implement them before M6 or remove them from the documented layout to avoid misrepresenting the tool's capabilities at release.

### 4. `asyncio_mode = "auto"` configured but `pytest-asyncio` not installed

`pyproject.toml` line 43 sets `asyncio_mode = "auto"` and lists `pytest-asyncio>=0.23` in dev extras, but `pytest-asyncio` is not present in the venv. This produces a `PytestConfigWarning: Unknown config option: asyncio_mode` on every test run. There are currently no async tests in the suite. Either install `pytest-asyncio` (it's already declared as a dev dep — run `uv pip install -e ".[dev]"` to sync) or remove the config option until async tests are actually needed.

### 5. `recommender/claude_md.py` at 84% — missing coverage for the cross-session path

Lines 67, 72–75, 81–82 are the `summarize()` function's match arms for when `evidence` sub-dicts are present (phrases list, stale_items list). Line 113 is the `kind not in _TEMPLATES` guard in `generate_from_evidence`. These branches are reachable in normal use but have no unit tests. For a module that produces the primary user-facing output (CLAUDE.md diffs), these gaps are worth closing before M6.

---

## Track (revisit next review)

### 6. `renderers/trace_tui.py` at 14% coverage

Lines 59–269 are the Textual `App`, `ModalScreen`, and `DataTable` subclasses. They cannot be exercised by the current unit test suite without a headless Textual driver. The pure helper functions above line 57 (`affected_turns`, `verdict`, `_build_flagged_index`) are tested at 100%. The Textual app body is structurally sound but invisible to coverage. Before M6, consider whether Textual's `App.run_test()` pilot (available since textual 0.23) can cover the compose/mount paths. Not blocking release, but 14% is a signal to revisit.

### 7. `renderers/terminal.py` at 57% — `render_aggregate` and `render_harvest_results` untested

Lines 84–120 (`render_aggregate`) and 138–167 (`render_harvest_results`) have no test coverage. Both functions are exercised only through CLI integration in `cli.py`, which is itself at 68% coverage. The CLI's `--since` path (cross-session) is entirely untested (lines 62–76). These are output-layer functions where a buffer-capture test (`console=Console(file=StringIO())`) would be cheap to write.

### 8. `_flagged_index` has two near-duplicate implementations in the renderers

- `renderers/report.py:21` (`_flagged_index`) — iterates `range(first_turn, last_turn + 1)`
- `renderers/trace_tui.py:43` (`_build_flagged_index`) — calls `affected_turns()` which uses `frozenset`

The semantics differ slightly: `report.py` uses simple range iteration; `trace_tui.py` goes through `affected_turns` which handles the `last_turn is None` case identically but through a different code path. Both produce the same result for well-formed data. This is a candidate for extraction into a shared helper in `renderers/__init__.py`, but it's low-risk given both renderers are tested against their own copies.

### 9. `rich_click` deprecation warning: `use_rich_markup=` → `text_markup=`

Five test warnings per run: `PendingDeprecationWarning: use_rich_markup= will be deprecated in a future version of rich_click. Please use text_markup= instead.` This originates inside `rich_click` itself (version 1.9.7), not from cctx code. Monitor for the next `rich_click` release that removes the old parameter; there is no action required in cctx today.

### 10. `claude_code.py` parser at 690 lines — watch for further growth

The parser is the largest file (690 lines) and the most logically complex module. It is currently within reason given the JSONL format's complexity (subagents, compaction, attachments, tool-result files), but it bears watching. If new JSONL shapes emerge (e.g., additional attachment types), consider splitting the attachment-classification logic (`_classify_attachment_shape`, `_extract_attachment_content`, `_parse_attachment_line`) into a `parsers/attachments.py` sub-module rather than growing the single file further.

### 11. `models.py` and `trace_tui.py` are both exactly 269 lines

Both crossed the 200-line threshold. `models.py` contains all dataclasses for the entire system — `Turn`, `ToolUse`, `ToolResult`, `Usage`, `Attachment`, `RawToolResultFile`, `SessionTrace`, `Finding`, `Patch`, `Diagnosis`, `AggregateReport` — plus `group_into_exchanges()`. A split into `models/session.py` and `models/diagnosis.py` may become warranted as M6 adds release-facing types. `trace_tui.py` is dense because the Textual app classes are inline inside `launch()`; if the TUI grows, extract the `App` subclass to its own class at module level.

---

## Metrics snapshot (baseline)

| Metric | Value |
|---|---|
| Total source LOC (`cctx/`) | 2,781 |
| Total test LOC (`tests/`) | 4,881 |
| Test-to-code ratio | 1.76:1 |
| Test coverage (overall) | 81% |
| Tests passing | 250 / 250 |
| TODO/FIXME in production code | 0 |
| TODO/FIXME in tests | 0 (test fixture string content only) |
| Skipped / xfail tests | 0 |
| Ruff lint errors | 0 |
| Outdated dependencies | 1 (`ruff` 0.15.12 → 0.15.13, patch bump) |
| Known vulnerabilities | 0 (pip-audit not available; no CVEs in dep set at time of review) |
| Layering violations | 0 |
| Largest file | `parsers/claude_code.py` — 690 lines |
| Source files | 24 |
| Test files | 30 |
| Previous health review | None (baseline) |

### Coverage by module

| Module | Coverage |
|---|---|
| `models.py` | 100% |
| `diagnostician/__init__.py` | 100% |
| `diagnostician/inflection.py` | 100% |
| `exporters/jsonl.py` | 100% |
| `renderers/report.py` | 100% |
| `diagnostician/patterns/stale_context.py` | 97% |
| `exporters/csv.py` | 96% |
| `diagnostician/patterns/retry_loop.py` | 91% |
| `diagnostician/patterns/scope_creep.py` | 92% |
| `diagnostician/aggregate.py` | 91% |
| `harvest.py` | 92% |
| `parsers/claude_code.py` | 92% |
| `recommender/evidence.py` | 100% |
| `recommender/claude_md.py` | 84% |
| `tokenizer.py` | 74% |
| `cli.py` | 68% |
| `renderers/terminal.py` | 57% |
| `renderers/trace_tui.py` | 14% |

### Dependency versions

| Package | Installed | Latest | Status |
|---|---|---|---|
| `anthropic` | 0.102.0 | — | current |
| `click` | 8.3.3 | — | current |
| `jinja2` | 3.1.6 | — | current |
| `rich` | 15.0.0 | — | current |
| `rich-click` | 1.9.7 | — | current |
| `textual` | 8.2.6 | — | current |
| `ruff` | 0.15.12 | 0.15.13 | patch outdated |
| `pytest` | 9.0.3 | — | current |

### Most-changed files (last 90 days of git history)

| Churn | File |
|---|---|
| 5 | `cctx/cli.py` |
| 3 | `cctx/models.py` |
| 3 | `tests/test_models.py` |
| 2 | `cctx/renderers/terminal.py` |
| 2 | `cctx/diagnostician/__init__.py` |
| 2 | `cctx/diagnostician/patterns/stale_context.py` |

High-churn files with coverage gaps: `cli.py` (68%) is the highest-risk combination. The `--since` cross-session path in `cli.py` (lines 62–76) has never been exercised by tests and has seen 5 commits.
