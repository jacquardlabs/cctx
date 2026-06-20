# Subagent-aware diagnosis (M16)

**Issues:** #88 (per-subagent cost attribution), #89 (fan-out waste classifier)
**Date:** 2026-06-10
**Status:** Ready for implementation

---

## Goal

The parser recursively parses child sessions into `SessionTrace.subagents`, and the
tokenizer counts their tokens, but `diagnostician.run()` never reads them — the cost
decomposition shown by `cctx autopsy` is blind to spend inside agent fan-outs.

M16 fixes that in two stages:
- **#88 (this PR):** Attribute cost to subagents. Surface "$1.84 of $3.10 across 7
  subagents" in terminal, HTML report, and `--json` output.
- **#89 (next PR):** Classify *wasteful* fan-outs — overlapping work, failed retries,
  unused results.

---

## Empirical baseline

Two facts verified empirically before this spec was written:

1. **Subagent spend is additive.** `_compute_total_cost` reads only `trace.turns`.
   Subagent API calls are billed separately and are entirely invisible to the current
   diagnostician. Making `total_cost_usd` inclusive (parent turns + all recursive
   subagent costs) is the correct fix.

2. **Existing fixtures use scrubbed token counts.** `with-subagents.jsonl` and
   `with-compaction.jsonl` have `input_tokens: "[SCRUBBED]"` throughout.
   Tests for M16 must use synthetic fixtures (inline subagent traces built in the test
   module), exactly as `test_subagent_files_discovered_and_parsed` in
   `tests/parsers/test_claude_code.py` already does.

---

## #88 — Per-subagent cost attribution

### New dataclass: `SubagentAttribution`

Add to `cctx/models.py`, near `Diagnosis`:

```python
@dataclass
class SubagentAttribution:
    session_id: str
    label:       str        # from Agent tool_input['description'], else prompt[:80]
    total_cost_usd: float   # inclusive: this subagent + its own children
    depth:       int        # 1 = direct child, 2 = grandchild, …
    model:       str | None
```

### `Diagnosis` field addition

Add at the end of `Diagnosis` (defaulted so no existing callsites break):

```python
subagent_costs: list[SubagentAttribution] = field(default_factory=list)
```

### Label derivation

When a `ToolUse` with `tool_name == "Agent"` has a `subagent_session_id` set
(linked by the parser), read the label from `tool_input`:

```
label = tool_input.get("description") or tool_input.get("prompt", "")[:80] or session_id[:12]
```

`description` is the concise phrase ("Explore how courses, users…" — confirmed in
the real fixture). `prompt[:80]` is the fallback when no `description` field exists.
`session_id[:12]` is the last resort for orphan subagents.

### Changes to `cctx/diagnostician/__init__.py`

#### `_compute_total_cost` → recursive

Rename the existing private function to `_compute_own_cost` and add a new wrapper:

```python
def _compute_own_cost(trace: SessionTrace, model: str | None) -> float:
    """Parent-turns-only cost (unchanged logic)."""
    price = _price_per_tok(model)
    total = 0.0
    for turn in trace.turns:
        if turn.usage is not None:
            total += turn.usage.input_tokens * price
            total += turn.usage.cache_read * price * 0.1
            cache_writes = turn.usage.cache_creation_5m + turn.usage.cache_creation_1h
            total += cache_writes * price * 1.25
    return round(total, 4)


def _compute_inclusive_cost(trace: SessionTrace) -> float:
    """Recursive cost: own turns + all subagent turns."""
    own = _compute_own_cost(trace, trace.primary_model)
    return own + sum(_compute_inclusive_cost(sa) for sa in trace.subagents)
```

#### `_collect_attributions`

```python
def _collect_attributions(
    trace: SessionTrace,
    depth: int = 1,
    label_map: dict[str, str] | None = None,
) -> list[SubagentAttribution]:
    """Build flat list of SubagentAttribution, one per subagent, DFS order."""
    from cctx.models import SubagentAttribution  # avoid circular at module level
    if label_map is None:
        # Build label_map from parent's linked Agent tool uses
        label_map = {}
        for turn in trace.turns:
            for tu in turn.tool_uses:
                if tu.subagent_session_id:
                    ti = tu.tool_input
                    label_map[tu.subagent_session_id] = (
                        ti.get("description")
                        or (ti.get("prompt") or "")[:80]
                        or tu.subagent_session_id[:12]
                    )
    result: list[SubagentAttribution] = []
    for child in trace.subagents:
        label = label_map.get(child.session_id, child.session_id[:12])
        cost = _compute_inclusive_cost(child)
        result.append(SubagentAttribution(
            session_id=child.session_id,
            label=label,
            total_cost_usd=round(cost, 4),
            depth=depth,
            model=child.primary_model,
        ))
        # Recurse into grandchildren (no label_map for grandchildren — orphan fallback)
        result.extend(_collect_attributions(child, depth + 1, None))
    return result
```

#### `run()` update

```python
def run(trace: SessionTrace) -> Diagnosis:
    ...
    total_cost = _compute_inclusive_cost(trace)  # now inclusive
    waste_cost = ...
    subagent_costs = _collect_attributions(trace)

    return Diagnosis(
        ...
        total_cost_usd=total_cost,
        waste_cost_usd=round(waste_cost, 4),
        subagent_costs=subagent_costs,
    )
```

**Note on `total_cost_usd` change:** No existing tests assert `total_cost_usd` on a
subagent-bearing trace produced by `diagnostician.run()`. All existing tests construct
`Diagnosis` objects directly with fixed values. The change is safe.

---

### Terminal rendering (`cctx/renderers/terminal.py`)

After the existing cost line, add a subagent section when `diagnosis.subagent_costs`
is non-empty:

```
Session cost: ~$3.10 (includes 2 subagents: ~$1.84)  ← amended cost line
~85–95% of actual billing; system framing not observable in JSONL

  Subagent costs:
  ┌─────────────────────────────────────────┬───────┬────────┐
  │ Label                                   │ Depth │   Cost │
  ├─────────────────────────────────────────┼───────┼────────┤
  │ Explore how courses, users, and enroll… │     1 │ $0.021 │
  │ Explore the StudyEngine codebase at /U… │     1 │ $0.018 │
  └─────────────────────────────────────────┴───────┴────────┘
```

Amended cost line format (only when `subagent_costs` non-empty):

```
Session cost: ~${total:.2f} (includes {n} subagent{"s" if n!=1 else ""}: ~${subagent_sum:.2f})
```

where `subagent_sum = sum(a.total_cost_usd for a in diagnosis.subagent_costs if a.depth == 1)`.

The table uses `rich.table.Table` (consistent with existing renderers) with columns:
- Label (max 45 chars, truncated with `…`)
- Depth (right-align, int)
- Cost (right-align, `$N.NNN`)

Only show depth column if any depth > 1 (nested fan-outs). When all are depth == 1,
omit the depth column for cleanliness.

No output change when `subagent_costs` is empty.

---

### HTML report (`cctx/renderers/report.py`)

The Jinja2 template receives a new `subagent_costs` variable. When non-empty, render
a collapsed `<details>` block after the cost line:

```html
<details>
  <summary>Subagents: {{ n }} — ${{ subagent_sum:.3f }}</summary>
  <table>
    <tr><th>Label</th><th>Depth</th><th>Cost</th></tr>
    {% for a in subagent_costs %}
    <tr>
      <td>{{ a.label | truncate(80) }}</td>
      <td>{{ a.depth }}</td>
      <td>${{ "%.3f" % a.total_cost_usd }}</td>
    </tr>
    {% endfor %}
  </table>
</details>
```

Pass `subagent_costs=diagnosis.subagent_costs` to the template context.

---

### JSON output (`cctx/exporters/jsonl.py`)

`export_diagnosis` adds a `subagent_costs` key to the output object:

```python
obj["subagent_costs"] = [
    {
        "session_id": a.session_id,
        "label":      a.label,
        "cost_usd":   a.total_cost_usd,
        "depth":      a.depth,
        "model":      a.model,
    }
    for a in diagnosis.subagent_costs
]
```

Always present (empty list `[]` when no subagents).

---

### Tests (#88)

All in `tests/test_diagnostician_subagents.py` (new file).

| Test | Asserts |
|---|---|
| `test_no_subagents_cost_unchanged` | `run()` on trace with `subagents=[]` yields `total_cost_usd` == parent-only cost; `subagent_costs == []` |
| `test_one_subagent_cost_inclusive` | `total_cost_usd` == parent + child cost; `len(subagent_costs) == 1` |
| `test_nested_subagents_cost_inclusive` | parent + child + grandchild all summed |
| `test_attribution_depth_1` | direct child has `depth == 1` |
| `test_attribution_depth_2` | grandchild has `depth == 2` |
| `test_attribution_label_from_description` | linked Agent with `description` field → label |
| `test_attribution_label_from_prompt_fallback` | linked Agent without `description`, has `prompt` → label == `prompt[:80]` |
| `test_attribution_label_orphan_fallback` | unlinked subagent → `session_id[:12]` |
| `test_subagent_cost_does_not_double_count` | two subagents: each appears once, costs sum correctly |
| `test_total_cost_never_less_than_subagent_sum` | structural invariant: `total_cost_usd >= sum(a.total_cost_usd for a in subagent_costs if a.depth==1)` |

Build synthetic traces inline (same approach as `test_tokenize_recurses_into_subagents`):
use the `_make_minimal_trace` / `_make_turn` helpers from `tests/test_tokenizer.py` as
a model, or write equivalents in the new test file.

---

## #89 — Fan-out waste classifier (design only; implementation is a separate PR)

Requires #88 merged first (needs `SubagentAttribution` and the attribution plumbing).

### New `FindingKind` values

```python
FANOUT_OVERLAP = "fanout_overlap"   # overlapping agent prompts
FANOUT_RETRY   = "fanout_retry"     # failed subagent → re-spawned for same task
FANOUT_UNUSED  = "fanout_unused"    # subagent result never referenced by parent
```

Add `KIND_LABEL` entries and `MANAGED_HEADINGS` entry (single heading for the family):
`"## Fan-out discipline"`.

### New classifier: `cctx/diagnostician/patterns/fan_out.py`

```
classify(trace: SessionTrace) -> list[Finding]
```

#### Signal A — Overlapping subagents (`FANOUT_OVERLAP`)

1. Collect all Agent `ToolUse` from parent turns that have a `subagent_session_id`.
2. For each pair (i, j), compute Jaccard similarity on word 3-grams of their `prompt`
   fields (fall back to `description` if no `prompt`).
3. **Threshold:** Jaccard ≥ 0.65 AND both prompts ≥ 50 words.
4. Each overlapping pair fires one Finding.

#### Signal B — Failed-retry fan-out (`FANOUT_RETRY`)

1. For each Agent `ToolResult` where `is_error == True`, find the next Agent `ToolUse`
   in the same session (by turn order).
2. Compute Jaccard 3-gram similarity between the failed Agent's prompt and the
   retry Agent's prompt.
3. **Threshold:** Jaccard ≥ 0.50 AND both prompts ≥ 30 words.
4. Fires one Finding per failed-retry pair.

#### Signal C — Unused result (`FANOUT_UNUSED`)

1. For each Agent ToolResult with `len(content) ≥ 2000 chars`, extract word 6-grams.
2. Scan all subsequent parent assistant turns' `.text` for any matching 6-gram.
3. **Binary:** if zero matches → `FANOUT_UNUSED` Finding.
4. `cost_usd` = subagent's `total_cost_usd` from `SubagentAttribution`.

#### Thresholds rationale

All thresholds are deterministic and documented here — no tuning at runtime.
Jaccard on word 3-grams is O(n+m) via set intersection. No LLM calls.
The "binary, high-confidence" v1 principle applies: only fire on strong signals.

### Recommender patch (`cctx/recommender/claude_md.py`)

One template for all three kinds, targeting heading `"## Fan-out discipline"`:

```diff
+## Fan-out discipline
+
+Before spawning multiple subagents in parallel, state what each one will return
+and verify the tasks don't overlap. After each subagent completes, confirm its
+result is actually consumed by the parent before spawning retries. Retry only
+after changing something meaningful about the task — identical re-spawns waste
+the full subagent cost with no new information.
```

### Tests (#89)

File: `tests/test_fanout_classifier.py`. Key cases:

| Test | Signal |
|---|---|
| `test_overlapping_prompts_fires` | A: Jaccard ≥ 0.65 on two Agent calls |
| `test_non_overlapping_prompts_clean` | A: Jaccard < 0.65 → no finding |
| `test_short_prompts_not_compared` | A: prompts < 50 words → no finding |
| `test_failed_retry_fires` | B: `is_error=True` Agent + similar next Agent |
| `test_failed_no_retry_clean` | B: `is_error=True` but no similar follow-up |
| `test_unused_result_fires` | C: long result, zero 6-gram matches in parent turns |
| `test_used_result_clean` | C: parent turn quotes part of result → no finding |
| `test_clean_fanout_no_findings` | Multiple diverse successful subagents → no findings |

---

## Layering

No layering rules are broken:

- `cctx/models.py` adds `SubagentAttribution` dataclass (no new imports).
- `cctx/diagnostician/__init__.py` reads `trace.subagents` (already in scope).
- Renderers receive `diagnosis.subagent_costs` — they never compute analysis.
- `cctx/exporters/jsonl.py` serializes the new field — no analysis.
- No `anthropic` import outside `tokenizer.py`.

---

## Files touched (per PR)

### PR #88

| File | Change |
|---|---|
| `cctx/models.py` | Add `SubagentAttribution`; add `subagent_costs` to `Diagnosis` |
| `cctx/diagnostician/__init__.py` | `_compute_inclusive_cost`, `_collect_attributions`, update `run()` |
| `cctx/renderers/terminal.py` | Subagent cost table + amended cost line |
| `cctx/renderers/report.py` | `subagent_costs` in Jinja2 template context |
| `cctx/exporters/jsonl.py` | `subagent_costs` key in JSON output |
| `tests/test_diagnostician_subagents.py` | New test file (10 tests) |

### PR #89 (separate, blocked by #88)

| File | Change |
|---|---|
| `cctx/models.py` | `FANOUT_OVERLAP`, `FANOUT_RETRY`, `FANOUT_UNUSED` + KIND_LABEL + MANAGED_HEADINGS |
| `cctx/diagnostician/patterns/fan_out.py` | New classifier |
| `cctx/diagnostician/__init__.py` | Import + call `fan_out.classify()` |
| `cctx/recommender/claude_md.py` | Fan-out discipline template |
| `tests/test_fanout_classifier.py` | New test file |
