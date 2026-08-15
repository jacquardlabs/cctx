# Spec: CSV subagent rows + dispatch join key

**Date:** 2026-08-15
**Issue:** #194 (M4 — Export), #195
**Status:** Ready for implementation

---

## 1. Goal

`cctx export --format csv` currently emits one row per turn of the **root session only**. Subagent turns never appear, and no column identifies which `Agent` dispatch produced a given row. External dispatch-time telemetry (jig's per-build-task executor, studious's 6 parallel `/gate-audit` auditors) therefore cannot join a routing decision — skill, role, model, routing_reason — against its actual cost through the CSV surface.

Spike #193 confirmed the gap across all three formats. #196 closed the JSON/JSONL half by adding `SubagentAttribution.dispatching_tool_use_id`, emitted as `subagent_costs[].dispatching_tool_use_id`. This spec closes the CSV half, completing #194.

After this change, one `GROUP BY` answers "what did dispatch `tu_abc` cost":

```sql
SELECT root_dispatch_tool_use_id, SUM(cost_usd)
FROM session_export
WHERE depth > 0
GROUP BY 1;
```

---

## 2. Design

### 2.1 Row set

`export_turn_rows` recurses into `trace.subagents` depth-first, emitting one row per turn at every depth. Row order: the root's turns, then each subagent's turns in `trace.subagents` order, each subagent's own children immediately after it — the same DFS order `_collect_attributions` uses, so CSV row order and `subagent_costs` order agree.

**Row identity is `(session_id, turn_number)`.** `turn_number` restarts at 1 in every subagent trace, so it is not unique on its own.

### 2.2 Columns

Four columns appended to `COLUMNS`, after the existing nine. Position matters: appending keeps positional-index consumers of the first nine working.

| Column | Type | Root row | Subagent row |
|---|---|---|---|
| `depth` | int | `0` | `1` = direct child, `2` = grandchild, … |
| `parent_session_id` | str | `""` | dispatching session's `session_id` |
| `dispatching_tool_use_id` | str | `""` | the `Agent` `tool_use_id` in the **immediate parent** that dispatched this session; `""` when orphaned |
| `root_dispatch_tool_use_id` | str | `""` | the **depth-1 ancestor's** `dispatching_tool_use_id`, carried down to every descendant |

`depth` agrees with `SubagentAttribution.depth` (1 = direct child) and extends it with a root level of `0`, which has no attribution entry.

For a depth-1 row, `dispatching_tool_use_id == root_dispatch_tool_use_id`. They diverge from depth 2 down: `dispatching_tool_use_id` is the local dispatch, `root_dispatch_tool_use_id` is the top-level dispatch the whole subtree rolls up to. Without the second column, inclusive per-dispatch cost requires reconstructing the session tree — a regression in purpose for a flat format.

### 2.3 Contract change

`sum(cost_usd)` over all rows moves from root-only to inclusive-of-subagents. Filtering `depth == 0` recovers today's exact output, byte for byte. This is documented in the README export section.

### 2.4 Finding scoping

`Finding.session_id` is `None` for root findings and the subagent's `session_id` for subagent findings. The `finding_at` index keys on `(session_id, first_turn)` rather than bare `first_turn`, resolving `None` to the root trace's `session_id`:

```python
finding_at: dict[tuple[str, int], list[str]] = {}
for f in diagnosis.findings:
    finding_at.setdefault((f.session_id or trace.session_id, f.first_turn), []).append(f.kind.value)
```

Without this, a subagent's turn 3 would inherit the root's turn-3 finding kinds.

### 2.5 `is_inflection_turn`

`inflection.detect` runs on root findings only, so `diagnosis.inflection_turn` is a root turn number. Subagent rows are always `"false"`, guarded on `depth == 0` — otherwise every subagent turn sharing that number is falsely flagged.

### 2.6 Where dispatch identity comes from

From `diagnosis.subagent_costs` — already public on the `Diagnosis`, already at exactly this granularity, already carrying `dispatching_tool_use_id`. Not recomputed from the trace, and not imported from the diagnostician's private `_build_dispatch_map`: sourcing both formats from the same field is what keeps CSV's join key from drifting away from JSON's.

`depth` and `parent_session_id` come from the recursion and `SessionTrace.parent_session_id` respectively, so they are correct even when `subagent_costs` is empty (a hand-built `Diagnosis`); `dispatching_tool_use_id` and `root_dispatch_tool_use_id` are `""` in that case.

### 2.7 Cost

Unchanged. The existing per-turn formula already prices on `turn.model`, so subagent turns are priced at the subagent's own model with no new code. Issue #178 (the exporter recomputing cost via `price_per_tok` with hardcoded cache multipliers instead of `get_pricing`) is M23 scope and deliberately untouched here.

---

## 3. Layering

`cctx/exporters/csv.py` gains no imports. It reads `Diagnosis` and `SessionTrace` fields and writes rows — no analysis, no `click`, no `anthropic`.

---

## 4. Tests

`tests/exporters/test_csv.py`:

- `test_csv_export_has_subagent_dispatch_join_key` — replaces the `has_no_` characterization test from #193; asserts the four columns exist and the child's turn appears as a row keyed to `tu-dispatch`.
- Subagent turns emitted as rows, in DFS order, with `depth`/`parent_session_id` set.
- `root_dispatch_tool_use_id` on a depth-2 grandchild equals the depth-1 dispatch, while its `dispatching_tool_use_id` is the inner one.
- `depth == 0` filter reproduces the pre-change row set.
- Root finding kinds do not leak onto a subagent turn with the same `turn_number`.
- `is_inflection_turn` is `"false"` on a subagent turn whose number equals `diagnosis.inflection_turn`.
- Orphaned subagent (no matching `SubagentAttribution`) emits rows with empty dispatch columns.
- Subagent turns priced at the subagent's own model, not the root's.

---

## 5. Out of scope

- `--include-subagents` flag or a separate CSV mode. Rejected: CSV exists to be flat, and `depth == 0` already recovers the old output.
- CSV columns for `label` / `model` of the dispatch. `subagent_costs` in JSON carries those; the join key is what CSV was missing.
- #178's cost-computation refactor.
