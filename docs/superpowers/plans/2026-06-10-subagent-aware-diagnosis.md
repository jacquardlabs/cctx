# Subagent-Aware Diagnosis (M16 #88) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `cctx autopsy` show per-subagent cost attribution so the full session cost is visible, not just the parent agent's turns.

**Architecture:** Three units: (A) add `SubagentAttribution` model + `subagent_costs` field on `Diagnosis`; (B) update the diagnostician to compute inclusive cost recursively and collect per-subagent attribution; (C) update the three output surfaces (terminal, HTML, JSON) to show the new data. All synthetic fixtures — real fixtures have scrubbed token counts.

**Tech Stack:** Python 3.10+, `dataclasses`, `rich.table.Table`, Jinja2, existing `cctx.*` modules.

---

## File map

| File | Change |
|---|---|
| `cctx/models.py` | Add `SubagentAttribution` dataclass; add `subagent_costs` field to `Diagnosis` |
| `cctx/diagnostician/__init__.py` | `_compute_inclusive_cost`, `_collect_attributions`, update `run()` |
| `cctx/renderers/terminal.py` | Subagent table + amended cost line |
| `cctx/renderers/templates/autopsy.html.j2` | `<details>` block for subagent costs |
| `cctx/renderers/report.py` | Pass `subagent_costs` to template |
| `cctx/exporters/jsonl.py` | Add `subagent_costs` key to JSON output |
| `tests/test_diagnostician_subagents.py` | New file — 10 tests |

---

## Task A: `SubagentAttribution` model + `Diagnosis` field

**Files:**
- Modify: `cctx/models.py` (near `Diagnosis`, ~line 236)
- Test: `tests/test_diagnostician_subagents.py` (new)

### Context

`cctx/models.py` already has `Diagnosis` at around line 237. You are adding a new
dataclass just before it, and a new defaulted field at the end of `Diagnosis`.

Current `Diagnosis` tail (from ~line 242):
```python
    total_cost_usd:  float
    waste_cost_usd:  float
    analysed_at:     datetime
```

Current imports at the top of `models.py`:
```python
import dataclasses
from dataclasses import dataclass, field
```
(`field` is already imported — confirm before adding.)

- [ ] **Step 1: Write the failing test**

Create `tests/test_diagnostician_subagents.py`:

```python
"""Tests for per-subagent cost attribution (M16 #88)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cctx.models import SessionTrace, ToolUse, ToolResult, Turn, Usage


# ---------------------------------------------------------------------------
# Helpers — synthetic trace builders (real fixtures have scrubbed tokens)
# ---------------------------------------------------------------------------

_TS = datetime(2026, 6, 10, tzinfo=timezone.utc)


def _make_usage(input_tokens: int) -> Usage:
    return Usage(
        input_tokens=input_tokens,
        output_tokens=50,
        cache_creation_5m=0,
        cache_creation_1h=0,
        cache_read=0,
        service_tier=None,
    )


def _make_trace(
    session_id: str,
    input_tokens: int,
    *,
    subagents: list[SessionTrace] | None = None,
    model: str = "claude-sonnet-4",
    tool_uses: list[ToolUse] | None = None,
) -> SessionTrace:
    turn = Turn(
        turn_number=1,
        uuid="u1",
        parent_uuid=None,
        role="assistant",
        text="ok",
        thinking="",
        tool_uses=tool_uses or [],
        tool_results=[],
        usage=_make_usage(input_tokens),
        model=model,
        stop_reason="end_turn",
        timestamp=_TS,
        duration_ms=None,
    )
    return SessionTrace(
        session_id=session_id,
        parent_session_id=None,
        project_path="/p",
        cwd="/p",
        primary_model=model,
        claude_code_version=None,
        turns=[turn],
        subagents=subagents or [],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=_TS,
        end_time=_TS,
        source_path=Path(f"/p/{session_id}.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


def _agent_tu(
    session_id: str,
    *,
    description: str = "",
    prompt: str = "",
) -> ToolUse:
    """Construct an Agent ToolUse linked to a child session."""
    ti: dict = {"prompt": prompt}
    if description:
        ti["description"] = description
    return ToolUse(
        tool_name="Agent",
        tool_use_id=f"tu_{session_id}",
        tool_input=ti,
        subagent_session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_subagents_cost_unchanged():
    """With no subagents, total_cost_usd equals parent-only cost and subagent_costs is empty."""
    from cctx.diagnostician import run
    trace = _make_trace("parent", input_tokens=5_000)
    diag = run(trace)
    assert diag.subagent_costs == []
    # parent has 5000 input tokens at sonnet-4 price ($3/Mtok) = $0.0150
    assert abs(diag.total_cost_usd - 0.0150) < 0.001


def test_subagent_attribution_dataclass_exists():
    from cctx.models import SubagentAttribution
    a = SubagentAttribution(
        session_id="child-1",
        label="my label",
        total_cost_usd=0.05,
        depth=1,
        model="claude-sonnet-4",
    )
    assert a.session_id == "child-1"
    assert a.label == "my label"
    assert a.depth == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/bryan/Projects/cctx
uv run pytest tests/test_diagnostician_subagents.py::test_subagent_attribution_dataclass_exists -v
```

Expected: `ImportError: cannot import name 'SubagentAttribution' from 'cctx.models'`

- [ ] **Step 3: Add `SubagentAttribution` to `models.py` and `subagent_costs` to `Diagnosis`**

In `cctx/models.py`, insert this block **before** the `Diagnosis` dataclass:

```python
@dataclass
class SubagentAttribution:
    """Cost attribution for a single subagent session."""

    session_id:    str
    label:         str        # from Agent tool_input['description'], else prompt[:80]
    total_cost_usd: float     # inclusive: this subagent + its own children
    depth:         int        # 1 = direct child, 2 = grandchild, …
    model:         str | None
```

Then add this line at the **end** of `Diagnosis` (after `analysed_at`):

```python
    subagent_costs: list["SubagentAttribution"] = field(default_factory=list)
```

Verify `field` is already imported from `dataclasses`. Check the top of `models.py` —
it should read `from dataclasses import dataclass, field`. If `field` is missing, add it.

Also add `SubagentAttribution` to the `TYPE_CHECKING` section or the direct imports in
`diagnostician/__init__.py` — we'll do that in Task B.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_diagnostician_subagents.py -v
```

Expected: both tests pass. Also run the full suite to catch any regressions:

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git checkout -b feat/subagent-cost-attribution
git add cctx/models.py tests/test_diagnostician_subagents.py
git commit -m "feat: SubagentAttribution model + Diagnosis.subagent_costs field (#88)"
```

---

## Task B: Diagnostician — inclusive cost + attribution collection

**Files:**
- Modify: `cctx/diagnostician/__init__.py`
- Test: `tests/test_diagnostician_subagents.py` (extend)

### Context

`cctx/diagnostician/__init__.py` currently has:

```python
def _compute_total_cost(trace: SessionTrace, model: str | None) -> float:
    """Approximate total session cost..."""
    price = _price_per_tok(model)
    total = 0.0
    for turn in trace.turns:
        if turn.usage is not None:
            total += turn.usage.input_tokens * price
            total += turn.usage.cache_read * price * 0.1
            cache_writes = turn.usage.cache_creation_5m + turn.usage.cache_creation_1h
            total += cache_writes * price * 1.25
    return round(total, 4)
```

And `run()` calls `_compute_total_cost(trace, trace.primary_model)`.

The plan:
1. Rename `_compute_total_cost` → `_compute_own_cost` (same logic, just the parent's turns).
2. Add `_compute_inclusive_cost(trace)` that recurses into `trace.subagents`.
3. Add `_collect_attributions(trace)` that builds `list[SubagentAttribution]`.
4. Update `run()` to use inclusive cost and collect attributions.

- [ ] **Step 1: Write the failing tests** (extend `tests/test_diagnostician_subagents.py`)

Append these tests:

```python
def test_one_subagent_cost_inclusive():
    """total_cost_usd includes direct child's cost."""
    from cctx.diagnostician import run
    child = _make_trace("child-1", input_tokens=10_000)
    parent = _make_trace("parent", input_tokens=5_000, subagents=[child])
    diag = run(parent)
    # parent: 5000 * 3/1e6 = 0.015; child: 10000 * 3/1e6 = 0.030; total = 0.045
    assert abs(diag.total_cost_usd - 0.045) < 0.001
    assert len(diag.subagent_costs) == 1
    assert diag.subagent_costs[0].session_id == "child-1"


def test_nested_subagents_cost_inclusive():
    """total_cost_usd sums all levels (parent + child + grandchild)."""
    from cctx.diagnostician import run
    grandchild = _make_trace("grand", input_tokens=5_000)
    child = _make_trace("child", input_tokens=10_000, subagents=[grandchild])
    parent = _make_trace("parent", input_tokens=5_000, subagents=[child])
    diag = run(parent)
    # 5000 + 10000 + 5000 = 20000 tokens * 3/1e6 = 0.060
    assert abs(diag.total_cost_usd - 0.060) < 0.001
    # flat attribution list: child at depth 1, grandchild at depth 2
    assert len(diag.subagent_costs) == 2


def test_attribution_depth_1():
    """Direct child has depth == 1."""
    from cctx.diagnostician import run
    child = _make_trace("child-1", input_tokens=1_000)
    parent = _make_trace("parent", input_tokens=1_000, subagents=[child])
    diag = run(parent)
    assert diag.subagent_costs[0].depth == 1


def test_attribution_depth_2():
    """Grandchild has depth == 2."""
    from cctx.diagnostician import run
    grandchild = _make_trace("grand", input_tokens=1_000)
    child = _make_trace("child", input_tokens=1_000, subagents=[grandchild])
    parent = _make_trace("parent", input_tokens=1_000, subagents=[child])
    diag = run(parent)
    depths = {a.session_id: a.depth for a in diag.subagent_costs}
    assert depths["child"] == 1
    assert depths["grand"] == 2


def test_attribution_label_from_description():
    """Label comes from Agent tool_input['description'] when present."""
    from cctx.diagnostician import run
    child = _make_trace("child-1", input_tokens=1_000)
    tu = _agent_tu("child-1", description="Explore the codebase", prompt="Do something long")
    parent = _make_trace("parent", input_tokens=1_000, subagents=[child], tool_uses=[tu])
    diag = run(parent)
    assert diag.subagent_costs[0].label == "Explore the codebase"


def test_attribution_label_from_prompt_fallback():
    """When no 'description', label is prompt[:80]."""
    from cctx.diagnostician import run
    child = _make_trace("child-1", input_tokens=1_000)
    long_prompt = "A" * 200
    tu = _agent_tu("child-1", prompt=long_prompt)
    parent = _make_trace("parent", input_tokens=1_000, subagents=[child], tool_uses=[tu])
    diag = run(parent)
    assert diag.subagent_costs[0].label == long_prompt[:80]


def test_attribution_label_orphan_fallback():
    """Unlinked subagent (no matching ToolUse) gets session_id[:12] as label."""
    from cctx.diagnostician import run
    child = _make_trace("child-unlinked-session", input_tokens=1_000)
    # Parent has no Agent ToolUse linking to this child
    parent = _make_trace("parent", input_tokens=1_000, subagents=[child])
    diag = run(parent)
    assert diag.subagent_costs[0].label == "child-unlink"  # first 12 chars


def test_subagent_cost_no_double_count():
    """Two direct subagents: total equals parent + child1 + child2."""
    from cctx.diagnostician import run
    child1 = _make_trace("c1", input_tokens=10_000)
    child2 = _make_trace("c2", input_tokens=20_000)
    parent = _make_trace("parent", input_tokens=5_000, subagents=[child1, child2])
    diag = run(parent)
    expected = (5_000 + 10_000 + 20_000) * 3 / 1_000_000
    assert abs(diag.total_cost_usd - expected) < 0.001
    assert len(diag.subagent_costs) == 2


def test_total_cost_not_less_than_depth1_sum():
    """Invariant: total_cost >= sum of direct-child costs."""
    from cctx.diagnostician import run
    child1 = _make_trace("c1", input_tokens=10_000)
    child2 = _make_trace("c2", input_tokens=20_000)
    parent = _make_trace("parent", input_tokens=5_000, subagents=[child1, child2])
    diag = run(parent)
    depth1_sum = sum(a.total_cost_usd for a in diag.subagent_costs if a.depth == 1)
    assert diag.total_cost_usd >= depth1_sum
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_diagnostician_subagents.py -v
```

Expected: `test_no_subagents_cost_unchanged` and `test_subagent_attribution_dataclass_exists` still pass; the new tests fail with assertion errors (cost too low, subagent_costs empty).

- [ ] **Step 3: Implement inclusive cost and attribution in `cctx/diagnostician/__init__.py`**

Replace the existing `_compute_total_cost` function and update `run()`:

```python
"""Autopsy diagnostician — public entry point.

run(trace) -> Diagnosis
  Runs all pattern classifiers, detects inflection turn,
  patches stale_context cost attribution, and returns
  a Diagnosis with patches=[] and subagent_costs populated.

The Recommender (cctx.recommender.claude_md) populates patches.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from cctx.diagnostician import inflection
from cctx.diagnostician.patterns import (
    dead_end,
    retry_loop,
    scope_creep,
    stale_context,
    tool_thrash,
)
from cctx.models import Diagnosis, Finding, FindingKind, SubagentAttribution
from cctx.pricing import price_per_tok as _price_per_tok

if TYPE_CHECKING:
    from cctx.models import SessionTrace

UTC = timezone.utc


def _patch_costs(findings: list[Finding], model: str | None) -> list[Finding]:
    price = _price_per_tok(model)
    result = []
    for f in findings:
        if f.kind is FindingKind.STALE_CONTEXT:
            tt = f.evidence.get("total_token_turns", 0)
            f = dataclasses.replace(f, cost_usd=round(tt * price, 4))
        result.append(f)
    return result


def _compute_own_cost(trace: SessionTrace, model: str | None) -> float:
    """Parent-turns-only cost — does not recurse into subagents."""
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
    """Recursive cost: own turns + all subagent turns at every depth."""
    own = _compute_own_cost(trace, trace.primary_model)
    return own + sum(_compute_inclusive_cost(sa) for sa in trace.subagents)


def _build_label_map(trace: SessionTrace) -> dict[str, str]:
    """Map child session_id → display label from the parent's Agent ToolUse inputs."""
    label_map: dict[str, str] = {}
    for turn in trace.turns:
        for tu in turn.tool_uses:
            if tu.subagent_session_id:
                ti = tu.tool_input
                label_map[tu.subagent_session_id] = (
                    ti.get("description")
                    or (ti.get("prompt") or "")[:80]
                    or tu.subagent_session_id[:12]
                )
    return label_map


def _collect_attributions(
    trace: SessionTrace,
    depth: int = 1,
    label_map: dict[str, str] | None = None,
) -> list[SubagentAttribution]:
    """Flat DFS list of SubagentAttribution, one per subagent at every depth."""
    if label_map is None:
        label_map = _build_label_map(trace)
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
        result.extend(_collect_attributions(child, depth + 1, None))
    return result


def run(trace: SessionTrace) -> Diagnosis:
    """Diagnose a single SessionTrace. Returns Diagnosis with patches=[]."""
    findings: list[Finding] = [
        *retry_loop.classify(trace),
        *scope_creep.classify(trace),
        *stale_context.classify(trace),
        *tool_thrash.classify(trace),
        *dead_end.classify(trace),
    ]
    findings.sort(key=lambda f: f.first_turn)

    inflection_turn = inflection.detect(findings)
    findings = _patch_costs(findings, trace.primary_model)

    total_cost = round(_compute_inclusive_cost(trace), 4)
    waste_cost = sum(f.cost_usd for f in findings if f.cost_usd is not None)
    waste_cost = min(waste_cost, total_cost)

    subagent_costs = _collect_attributions(trace)

    return Diagnosis(
        session_id=trace.session_id,
        findings=findings,
        inflection_turn=inflection_turn,
        patches=[],
        total_cost_usd=total_cost,
        waste_cost_usd=round(waste_cost, 4),
        analysed_at=datetime.now(UTC),
        subagent_costs=subagent_costs,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_diagnostician_subagents.py -v
```

Expected: all 11 tests pass.

Full suite:

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass. (Existing tests construct `Diagnosis` directly with positional
args — the new `subagent_costs` field has a default, so they are unaffected.)

- [ ] **Step 5: Commit**

```bash
git add cctx/diagnostician/__init__.py tests/test_diagnostician_subagents.py
git commit -m "feat: diagnostician — inclusive cost + per-subagent attribution (#88)"
```

---

## Task C: Terminal renderer — subagent cost table

**Files:**
- Modify: `cctx/renderers/terminal.py`
- Test: `tests/test_terminal_renderer.py` (extend — or new file `tests/test_subagent_renderer.py`)

### Context

`render_diagnosis` in `cctx/renderers/terminal.py` currently renders the cost line at
~line 55:

```python
cost_line = f"Session cost: ~${diagnosis.total_cost_usd:.2f}"
if diagnosis.waste_cost_usd > 0:
    pct = (
        diagnosis.waste_cost_usd / diagnosis.total_cost_usd * 100
        if diagnosis.total_cost_usd
        else 0
    )
    cost_line += f" | Attributed waste: ~${diagnosis.waste_cost_usd:.2f} ({pct:.0f}%)"
con.print(cost_line)
```

The `rich.table.Table` import is already in the file. The `Diagnosis` type annotation
is in `TYPE_CHECKING`.

- [ ] **Step 1: Write the failing tests** (add to `tests/test_diagnostician_subagents.py`)

```python
# ---------------------------------------------------------------------------
# Renderer tests
# ---------------------------------------------------------------------------

def _make_diagnosis_with_subagents(n: int = 2) -> "Diagnosis":
    from cctx.models import Diagnosis, SubagentAttribution
    attributions = [
        SubagentAttribution(
            session_id=f"child-{i}",
            label=f"Task {i}: do something useful",
            total_cost_usd=round(0.010 * (i + 1), 4),
            depth=1,
            model="claude-sonnet-4",
        )
        for i in range(n)
    ]
    return Diagnosis(
        session_id="parent-session",
        findings=[],
        inflection_turn=None,
        patches=[],
        total_cost_usd=round(0.030 + sum(a.total_cost_usd for a in attributions), 4),
        waste_cost_usd=0.0,
        analysed_at=_TS,
        subagent_costs=attributions,
    )


def test_render_diagnosis_shows_subagent_summary():
    """Cost line mentions subagent count and sum when subagents present."""
    from io import StringIO
    from rich.console import Console
    from cctx.renderers.terminal import render_diagnosis
    buf = StringIO()
    con = Console(file=buf, no_color=True, width=120)
    diag = _make_diagnosis_with_subagents(2)
    render_diagnosis(diag, console=con)
    out = buf.getvalue()
    assert "2 subagent" in out
    assert "$0.03" in out  # subagent sum = 0.010 + 0.020 = 0.030


def test_render_diagnosis_shows_subagent_table():
    """Subagent table lists each agent's label and cost."""
    from io import StringIO
    from rich.console import Console
    from cctx.renderers.terminal import render_diagnosis
    buf = StringIO()
    con = Console(file=buf, no_color=True, width=120)
    diag = _make_diagnosis_with_subagents(2)
    render_diagnosis(diag, console=con)
    out = buf.getvalue()
    assert "Task 0: do something useful" in out
    assert "Task 1: do something useful" in out


def test_render_diagnosis_no_subagents_no_table():
    """When subagent_costs is empty, no subagent table is shown."""
    from io import StringIO
    from rich.console import Console
    from cctx.models import Diagnosis
    from cctx.renderers.terminal import render_diagnosis
    buf = StringIO()
    con = Console(file=buf, no_color=True, width=120)
    diag = Diagnosis(
        session_id="s1",
        findings=[],
        inflection_turn=None,
        patches=[],
        total_cost_usd=0.05,
        waste_cost_usd=0.0,
        analysed_at=_TS,
    )
    render_diagnosis(diag, console=con)
    out = buf.getvalue()
    assert "subagent" not in out.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_diagnostician_subagents.py::test_render_diagnosis_shows_subagent_summary -v
```

Expected: FAIL — the current renderer never mentions "subagent".

- [ ] **Step 3: Update `render_diagnosis` in `cctx/renderers/terminal.py`**

Replace the cost-line block (lines 55–63) with:

```python
    subagent_sum = sum(a.total_cost_usd for a in diagnosis.subagent_costs if a.depth == 1)
    n_sub = len([a for a in diagnosis.subagent_costs if a.depth == 1])
    cost_line = f"Session cost: ~${diagnosis.total_cost_usd:.2f}"
    if n_sub:
        cost_line += (
            f" (includes {n_sub} subagent{'s' if n_sub != 1 else ''}: ~${subagent_sum:.2f})"
        )
    if diagnosis.waste_cost_usd > 0:
        pct = (
            diagnosis.waste_cost_usd / diagnosis.total_cost_usd * 100
            if diagnosis.total_cost_usd
            else 0
        )
        cost_line += f" | Attributed waste: ~${diagnosis.waste_cost_usd:.2f} ({pct:.0f}%)"
    con.print(cost_line)
    con.print(Text(
        "~85–95% of actual billing; system framing not observable in JSONL", style="dim"
    ))

    if diagnosis.subagent_costs:
        show_depth = any(a.depth > 1 for a in diagnosis.subagent_costs)
        tbl = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        tbl.add_column("Subagent", no_wrap=False, max_width=48)
        if show_depth:
            tbl.add_column("Depth", justify="right", width=6)
        tbl.add_column("Cost", justify="right", width=8)
        for a in diagnosis.subagent_costs:
            label = a.label if len(a.label) <= 45 else a.label[:44] + "…"
            cost_cell = f"${a.total_cost_usd:.3f}"
            if show_depth:
                tbl.add_row(label, str(a.depth), cost_cell)
            else:
                tbl.add_row(label, cost_cell)
        con.print(tbl)
```

Remove the now-redundant standalone `con.print(Text(..., style="dim"))` line that
was originally after the `cost_line` print (the updated block now includes it inline).

**Important:** The original code had:
```python
con.print(cost_line)
con.print(Text(
    "~85–95% of actual billing; system framing not observable in JSONL", style="dim"
))
```
The new code folds the dim line into the cost block. Ensure you replace **both** of
these original lines, not just the first.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_diagnostician_subagents.py -v
```

Expected: all tests pass including the three new renderer tests.

Full suite:

```bash
uv run pytest tests/ -x -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add cctx/renderers/terminal.py tests/test_diagnostician_subagents.py
git commit -m "feat: terminal renderer — subagent cost table in autopsy output (#88)"
```

---

## Task D: HTML report + JSON exporter

**Files:**
- Modify: `cctx/renderers/templates/autopsy.html.j2`
- Modify: `cctx/renderers/report.py`
- Modify: `cctx/exporters/jsonl.py`
- Test: `tests/renderers/test_report.py` (extend) and `tests/exporters/test_jsonl.py` (extend)

### Context

`render_html` in `cctx/renderers/report.py` calls `tmpl.render(diag=diag, trace=trace, flagged=...)`.
The template has access to `diag.subagent_costs` already through the `diag` variable —
no change to `report.py` is strictly needed unless the template requires explicit passing.
Verify by checking: does `diag.subagent_costs` render in a Jinja2 template via `diag`?
Yes — `diag` is the `Diagnosis` object, so `diag.subagent_costs` is accessible directly.

`export_diagnosis` in `cctx/exporters/jsonl.py` builds a dict manually. Add the key there.

The test helpers in `tests/renderers/test_report.py` and `tests/exporters/test_jsonl.py`
build `Diagnosis` objects directly. Check those files before adding tests.

- [ ] **Step 1: Write the failing tests**

Check existing test helpers:

```bash
grep -n "def _make_diag\|def make_diag\|Diagnosis(" tests/renderers/test_report.py | head -10
grep -n "def _make_diag\|def make_diag\|Diagnosis(" tests/exporters/test_jsonl.py | head -10
```

In `tests/renderers/test_report.py`, add:

```python
def test_html_includes_subagent_costs():
    """HTML output contains subagent count and label when subagent_costs present."""
    from cctx.models import SubagentAttribution
    from cctx.renderers.report import render_html
    from datetime import datetime, timezone
    ts = datetime(2026, 6, 10, tzinfo=timezone.utc)
    # Build a minimal Diagnosis with one subagent attribution
    # Reuse existing _make_diag() helper from the file, then override
    diag = _make_diag()  # adapt to whatever helper exists in this file
    import dataclasses
    diag = dataclasses.replace(diag, subagent_costs=[
        SubagentAttribution(
            session_id="child-1",
            label="Analyze the database schema",
            total_cost_usd=0.025,
            depth=1,
            model="claude-sonnet-4",
        )
    ])
    trace = _make_trace()  # adapt to whatever helper exists in this file
    html = render_html(diag, trace)
    assert "Analyze the database schema" in html
    assert "0.025" in html
```

In `tests/exporters/test_jsonl.py`, add:

```python
def test_export_diagnosis_includes_subagent_costs():
    """JSON export includes subagent_costs array."""
    import json
    from cctx.models import SubagentAttribution
    from cctx.exporters.jsonl import export_diagnosis
    from datetime import datetime, timezone
    import dataclasses
    ts = datetime(2026, 6, 10, tzinfo=timezone.utc)
    # Use existing helpers in this file to build diag + trace
    diag = _make_diag()  # adapt
    trace = _make_trace()  # adapt
    diag = dataclasses.replace(diag, subagent_costs=[
        SubagentAttribution(
            session_id="child-1",
            label="My task",
            total_cost_usd=0.020,
            depth=1,
            model="claude-sonnet-4",
        )
    ])
    data = json.loads(export_diagnosis(diag, trace))
    assert "subagent_costs" in data
    assert len(data["subagent_costs"]) == 1
    assert data["subagent_costs"][0]["session_id"] == "child-1"
    assert data["subagent_costs"][0]["cost_usd"] == 0.020
    assert data["subagent_costs"][0]["depth"] == 1


def test_export_diagnosis_subagent_costs_empty_by_default():
    """JSON export has subagent_costs: [] when no subagents."""
    import json
    from cctx.exporters.jsonl import export_diagnosis
    diag = _make_diag()   # adapt
    trace = _make_trace()  # adapt
    data = json.loads(export_diagnosis(diag, trace))
    assert data["subagent_costs"] == []
```

**Note:** Before running, read `tests/renderers/test_report.py` and
`tests/exporters/test_jsonl.py` to find the actual names of their `_make_diag` /
`_make_trace` helpers. Adapt the test code above to use those actual names.

- [ ] **Step 2: Run failing tests**

```bash
uv run pytest tests/renderers/test_report.py::test_html_includes_subagent_costs -v
uv run pytest tests/exporters/test_jsonl.py::test_export_diagnosis_includes_subagent_costs -v
```

Expected: both fail — `subagent_costs` not in HTML / JSON yet.

- [ ] **Step 3: Update the HTML template**

In `cctx/renderers/templates/autopsy.html.j2`, after the closing `</dl>` in the
costs section (~line 178), insert:

```html
    {% if diag.subagent_costs %}
    <details class="subagent-costs">
      <summary>Subagents: {{ diag.subagent_costs | selectattr("depth", "eq", 1) | list | length }} — ${{ "%.3f" % (diag.subagent_costs | selectattr("depth", "eq", 1) | map(attribute="total_cost_usd") | sum) }}</summary>
      <table>
        <tr><th>Label</th><th>Depth</th><th>Cost</th></tr>
        {% for a in diag.subagent_costs %}
        <tr>
          <td>{{ a.label | truncate(80) }}</td>
          <td>{{ a.depth }}</td>
          <td>${{ "%.3f" % a.total_cost_usd }}</td>
        </tr>
        {% endfor %}
      </table>
    </details>
    {% endif %}
```

No changes to `cctx/renderers/report.py` — `diag.subagent_costs` is already accessible
via the `diag` variable passed to the template.

- [ ] **Step 4: Update `cctx/exporters/jsonl.py`**

In `export_diagnosis`, after the `"patches": patches` line in `obj`, add:

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

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/renderers/test_report.py tests/exporters/test_jsonl.py -v
```

Expected: all pass.

Full suite:

```bash
uv run pytest tests/ -x -q
```

Expected: all pass. Run lint:

```bash
uv run ruff check cctx tests
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add cctx/renderers/templates/autopsy.html.j2 cctx/exporters/jsonl.py \
        tests/renderers/test_report.py tests/exporters/test_jsonl.py
git commit -m "feat: HTML report + JSON exporter — subagent_costs output (#88)"
```

---

## Task E: Final check + PR

- [ ] **Step 1: Run the full test suite and lint**

```bash
uv run pytest tests/ -q
uv run ruff check cctx tests
```

Expected: all tests pass, no lint errors.

- [ ] **Step 2: Verify `git log` contains only the right commits**

```bash
git log --oneline origin/main..HEAD
```

Expected: four commits from this feature only — no unrelated commits from main.

- [ ] **Step 3: Create the PR**

```bash
gh pr create \
  --title "feat: per-subagent cost attribution in autopsy (#88)" \
  --body "$(cat <<'EOF'
## Summary
- Adds `SubagentAttribution` dataclass and `Diagnosis.subagent_costs` field
- Makes `total_cost_usd` inclusive (parent turns + all recursive subagent turns)
- Terminal renderer shows amended cost line + subagent table when subagents present
- HTML report adds collapsed `<details>` block for subagent breakdown
- JSON exporter adds `subagent_costs` array to output
- 10 new tests in `tests/test_diagnostician_subagents.py`; extended renderer + exporter tests

## Test plan
- [ ] `uv run pytest tests/ -q` — all pass
- [ ] `uv run ruff check cctx tests` — clean
- [ ] `cctx autopsy` on a session with no subagents — cost line unchanged, no table
- [ ] `cctx autopsy` on a session with subagents — amended cost line + table appear
EOF
)"
```

---

## Self-review against spec

| Spec requirement | Task |
|---|---|
| `SubagentAttribution` dataclass | Task A |
| `subagent_costs: list[SubagentAttribution]` on `Diagnosis` | Task A |
| Label from `description`, fallback to `prompt[:80]`, fallback to `session_id[:12]` | Task B |
| `total_cost_usd` inclusive (recursive) | Task B |
| `_collect_attributions` DFS order, correct depths | Task B |
| `run()` uses inclusive cost + populates `subagent_costs` | Task B |
| Terminal: amended cost line with subagent count + sum | Task C |
| Terminal: subagent table with label / depth / cost | Task C |
| Terminal: no change when `subagent_costs` is empty | Task C |
| HTML: `<details>` block for subagent breakdown | Task D |
| JSON: `subagent_costs` array always present | Task D |
| Tests use synthetic fixtures (real fixtures have scrubbed tokens) | Tasks A–D |
| Layering: no `anthropic` outside tokenizer; renderers compute no analysis | All tasks |
