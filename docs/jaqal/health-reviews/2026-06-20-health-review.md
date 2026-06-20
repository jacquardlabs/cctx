# cctx Codebase Health Review — 2026-06-20

**Reviewed branch:** `docs/readme-gaps` (HEAD: 88d0d55, latest main commit: 21f3374)
**Shipped version:** v1.17.0
**Reviewed by:** automated health audit
**Previous review:** none (first review)

---

## Summary

The codebase is structurally sound and in active development. 640 tests pass, overall coverage is 88%, layering invariants are clean in every module except one deliberate coupling (the aggregator), and the classifier pattern is consistent across all 12 pattern modules. The biggest concern is documentation drift: CLAUDE.md documents v0.2.0 (M7) and 5 classifiers, but the codebase has shipped to v1.17.0 with 12 classifiers and 4 undocumented top-level modules. For a project whose product value proposition is CLAUDE.md hygiene, this is the most pointed irony in the codebase. The biggest strength is the test suite — 52 test files covering 40 source files, near-zero real TODO debt, and no flaky or skipped tests.

---

## Critical (address this week)

### 1. CLAUDE.md documents the wrong codebase

CLAUDE.md's project layout and build order were last updated for v0.2.0 (M7). The actual codebase is v1.17.0. The gap is wide:

**Undocumented top-level modules (4):**
- `cctx/agents.py` — `claude agents --json` live-session query; consumed by `ls` and `watcher`
- `cctx/hook_installer.py` — `cctx init` SessionEnd hook install/remove; drives an entire CLI command
- `cctx/pricing.py` — per-token price table; imported by 4 modules as the single source of truth
- `cctx/parsers/otel.py` — OTEL/OpenAI Agents SDK parser (shipped v1.12.0, PR #116)

**Undocumented pattern classifiers (7 of 12 total):**
`cache_hygiene`, `exploration_thrash`, `fan_out`, `project_specific`, `unused_context`, `compaction` — all shipped, none in the architecture diagram.

**Stale build order:** CLAUDE.md stops at M7. The repo has shipped M8 through M21+ (v1.5.0–v1.17.0 per CHANGELOG).

This matters because CLAUDE.md is the authoritative spec for contributors. A contributor following it today would not understand 35% of the codebase.

---

## Important (address this month)

### 2. PRODUCT.md feature map is 13 minor versions stale

PRODUCT.md shows "Feature map (v1.4.0)." The repo is at v1.17.0. Features shipped since v1.4.0 that are missing from PRODUCT.md:
- `cctx init` / SessionEnd hook installer (v1.11.0)
- OTEL / OpenAI Agents SDK parser (v1.12.0)
- Subagent-aware diagnosis via `--json` aggregate output (v1.10.0)
- KV-cache hygiene classifier (v1.13.0)
- Savings framing + health grade (`--health` flag, v1.14.0)
- Compaction classifier (v1.15.0)
- Exploration thrash classifier (v1.16.0)
- Unused-context classifier / MCP never-called (v1.17.0)

Additionally, PRODUCT.md's "Known problems as of 2026-06-09" lists problem #2 as "Subagent traces are parsed but never diagnosed." This is no longer accurate. `fan_out.py` classifies subagent overlap/retry waste, and `diagnostician/__init__.py` populates `SubagentAttribution` and `subagent_costs` on every `Diagnosis`. The subagent diagnosis gap is substantially addressed (though per-subagent recursive classification is still open, see #3 below).

`init` is also a 7th CLI command not reflected in PRODUCT.md's "Six commands" principle statement.

### 3. `cctx/diagnostician/aggregate.py` absorbs parser + tokenizer orchestration

`aggregate.py` imports `parse_session` from `cctx.parsers.claude_code` and `tokenize_session` from `cctx.tokenizer`. CLAUDE.md's layering rules do not explicitly prohibit this (the "analyzers never import each other across boundary lines" rule is about cross-analyzer imports, and aggregate imports downward). However, `cli.py` duplicates the same parse → tokenize → diagnose pattern directly (lines 475–478, 537–538, 603–604, 754–755) for single-session flows. The result is two orchestration paths: `cli.py` manages single-session orchestration directly, `aggregate.py` manages batch orchestration internally.

This is workable but creates a maintenance surface: if the parse or tokenize pipeline changes, both `cli.py` and `aggregate.py` must be updated. Extracting a shared `pipeline.run_session(path)` helper would consolidate the four single-session call sites and `aggregate.py` into one place.

### 4. `cli.py` at 859 lines with 83% coverage

`cli.py` is the largest file in the codebase (859 lines, the threshold is 200) and the most-changed source file (11 changes in the last 50 commits). At 83% coverage, uncovered branches include multi-flag validation, `--json` aggregate, quiet mode, `--health` flag, the `watch` command body, and the `init` command body. Given its churn rate and central role, this is a compound risk.

The file has grown organically. Candidate extractions include: the `parse_since` utility (already a standalone function at line 48), the `_aggregate_drilldown` helper (line 126), and the `_render_check_findings` helper (line 150). The `harvest`, `watch`, and `init` command functions could each live in thin command modules imported by `cli.py`.

### 5. Duplicate helper functions across pattern classifiers

Three classifiers implement nearly identical private helpers:
- `_is_error(result: ToolResult) -> bool` — identical in `retry_loop.py` (line 31) and `dead_end.py` (line 44)
- `_canon_key(tool_name, tool_input) -> str` — nearly identical in `tool_thrash.py` (line 32) and `dead_end.py` (line 32)
- `_similarity_key` in `retry_loop.py` and `_canon_key` in `tool_thrash.py` serve the same purpose (deduplication key for tool call fingerprinting)

Extraction to `cctx/diagnostician/patterns/_helpers.py` or `cctx/diagnostician/_util.py` would be a clean refactor with high unit-test payback.

---

## Track (revisit next review)

### 6. `trace_tui.py` at 21% test coverage

`trace_tui.py` (296 lines) is the least-covered module in the codebase. The test file explicitly acknowledges this: "Textual Pilot (async UI) tests are omitted — the pure functions cover correctness of the logic; the TUI is exercised manually." The 3 pure helper functions (`affected_turns`, `verdict`, `_build_flagged_index`) are tested; the `TraceTUI` Textual app class (lines 46–296) is not. This is intentional and defensible for a TUI, but track it as Textual's async Pilot API matures.

### 7. `discovery.py` (77%) and `watcher.py` (76%) coverage gaps

`discovery.py` uncovered branches are all `~/.claude` filesystem edge cases (missing directories, encoded-path mismatches). `watcher.py` uncovered lines are the idle-timeout and session-ended exit paths in `_tail()` — both require real time-based behavior to test. These are reasonable gaps; the watcher has 12 tests covering the core detection logic. Monitor if either file's complexity grows.

### 8. `anthropic` SDK is 9 minor versions behind

The installed `anthropic` package is `0.102.0`; current is `0.111.0`. The project pins `>=0.25`, so the constraint is loose and the update would be non-breaking. The tokenizer's `count_tokens` API is unlikely to have changed, but 9 minor versions is a larger drift than the other runtime deps. Worth updating to pick up any security patches in the SDK.

### 9. rich-click `use_rich_markup` deprecation warning

82 test warnings fire `PendingDeprecationWarning: use_rich_markup= will be deprecated... use text_markup= instead`. This traces to rich-click's internal API. The project is on `1.9.7`; the `1.9.8` release may address it. This is cosmetic but makes test output noisy.

### 10. `tokenizer.py` live-path coverage (74%)

Lines 42–58 (the live `anthropic.messages.count_tokens` call path) are uncovered because tests run with `CCTX_OFFLINE=1`. This is by design and acceptable. Track it so a future contributor doesn't feel compelled to add a live-API test in CI.

---

## Metrics Snapshot

| Metric | Value |
|--------|-------|
| Total lines of code (src + tests) | 18,687 |
| Source lines (cctx/ only) | 7,293 |
| Test lines (tests/ only) | 7,807 |
| Test coverage (overall) | 88% |
| Source files | 40 |
| Test files | 52 |
| Test-to-source file ratio | 1.3:1 |
| Passing tests | 640 |
| Skipped / xfail tests | 0 |
| Real TODO/FIXME comments | 0 (all grep hits are test fixture strings or patch templates) |
| Outdated runtime dependencies | 4 (anthropic, click, rich-click, textual — all minor/patch) |
| Known vulnerabilities | 1: `pip 26.1.1` (PYSEC-2026-196, fix: upgrade to 26.1.2; not a runtime dep) |
| Largest source file | `cli.py` — 859 lines |
| Largest test file | `tests/parsers/test_claude_code.py` — 879 lines |
| Deepest dependency chain | 4 layers: `cli.py` → `aggregate.py` → `tokenizer.py` → `anthropic` (offline: stdlib) |
| CLAUDE.md last milestone documented | M7 / v0.2.0 |
| Shipped version | v1.17.0 |
| Version gap | 15 minor releases undocumented in CLAUDE.md |
| Modules in code not in CLAUDE.md | 4 top-level + 7 pattern classifiers |

**Previous review comparison:** First review; no prior baseline.

---

## Audit Detail: Layering Invariant Verification

All 5 layering rules from CLAUDE.md were checked:

| Rule | Status |
|------|--------|
| Parsers never import tokenizer, anthropic, or analyzers | PASS — `claude_code.py` and `otel.py` import only stdlib and `cctx.models` |
| Tokenizer is the only `anthropic` importer | PASS — `grep -rn "import anthropic"` finds only `cctx/tokenizer.py` |
| Analyzers never import each other across boundaries | PASS — `recommender/` does not import from `diagnostician/` internals; `aggregate.py` imports downward (parser + tokenizer), which is allowed by the rule's wording |
| Renderers never compute analysis | PASS — all renderers accept pre-computed output; no Finding generation in renderers |
| Only `cli.py` imports `click` / `rich_click` | PASS — confirmed; `harvest.py` docstring mentions this as a negative constraint and honors it |

---

## Audit Detail: API / Interface Consistency

- **CLI error handling:** Uniform — all validation uses `raise click.UsageError(...)`. No `sys.exit()` calls outside of `--fail-on-findings` logic. Consistent.
- **Classifier interface:** All 12 classifiers export `classify(trace: SessionTrace) -> list[Finding]`. 9 of 12 also have a private `_classify_impl` guard (scope_creep inverts the order but implements both). The `project_specific` module differs intentionally — it takes `list[tuple[Diagnosis, SessionTrace]]` because it operates across sessions.
- **Output format:** Terminal, GitHub summary, HTML, JSONL, CSV, and JSON exporters all receive a `Diagnosis` or `AggregateReport` — no exporter calls into analysis code. Consistent.
- **Patch targets:** `harvest.py` routes to `.md` files (CLAUDE.md, rules/, skills/) through a unified `apply_patch()` API. Multi-target routing introduced in v2 is handled with a single dispatch path. Consistent.
