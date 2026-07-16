"""Tests for per-subagent cost attribution (M16 #88)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cctx.models import Diagnosis, SessionTrace, ToolUse, Turn, Usage

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


def test_one_subagent_cost_inclusive():
    """total_cost_usd includes direct child's cost."""
    from cctx.diagnostician import run
    child = _make_trace("child-1", input_tokens=10_000)
    parent = _make_trace("parent", input_tokens=5_000, subagents=[child])
    diag = run(parent)
    # sonnet $3 in / $15 out, 50 output tok/turn. input: 15000*3/1e6 = 0.045;
    # output: 2 turns * 50 * 15/1e6 = 0.0015; total = 0.0465
    assert abs(diag.total_cost_usd - 0.0465) < 0.001
    assert len(diag.subagent_costs) == 1
    assert diag.subagent_costs[0].session_id == "child-1"


def test_nested_subagents_cost_inclusive():
    """total_cost_usd sums all levels (parent + child + grandchild)."""
    from cctx.diagnostician import run
    grandchild = _make_trace("grand", input_tokens=5_000)
    child = _make_trace("child", input_tokens=10_000, subagents=[grandchild])
    parent = _make_trace("parent", input_tokens=5_000, subagents=[child])
    diag = run(parent)
    # input: 20000 * 3/1e6 = 0.060; output: 3 turns * 50 * 15/1e6 = 0.00225; total = 0.06225
    assert abs(diag.total_cost_usd - 0.06225) < 0.001
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
    # input: 35000 * 3/1e6 = 0.105; output: 3 turns * 50 * 15/1e6 = 0.00225
    expected = (5_000 + 10_000 + 20_000) * 3 / 1_000_000 + 3 * 50 * 15 / 1_000_000
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


# ---------------------------------------------------------------------------
# Renderer tests
# ---------------------------------------------------------------------------

def _make_diagnosis_with_subagents(n: int = 2) -> Diagnosis:
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


# ---------------------------------------------------------------------------
# Full-accounting interior waste + fan-out ancestry dedup (#156, Task 3)
# ---------------------------------------------------------------------------


def test_interior_finding_in_unflagged_subagent_raises_waste():
    """A subagent NOT fan-out-flagged but with an interior finding adds to waste.

    Asserts the _interior_waste accounting helper directly (run() integration is
    covered end-to-end in the final task)."""
    from cctx.diagnostician import _interior_waste
    from cctx.models import Confidence, Finding, FindingKind, Severity

    sub_finding = Finding(
        kind=FindingKind.STALE_CONTEXT, severity=Severity.MEDIUM, confidence=Confidence.MEDIUM,
        first_turn=1, last_turn=2, evidence={}, cost_usd=0.05, summary="stale", session_id="sub-1",
    )
    parent_map = {"sub-1": "root"}
    wasted_sids: set[str] = set()  # sub-1 NOT flagged
    assert _interior_waste([sub_finding], parent_map, wasted_sids) == 0.05


def test_interior_finding_in_flagged_subagent_is_not_double_counted():
    """If the subagent is fan-out-flagged, its interior finding cost is NOT re-charged."""
    from cctx.diagnostician import _interior_waste
    from cctx.models import Confidence, Finding, FindingKind, Severity

    sub_finding = Finding(
        kind=FindingKind.RETRY_LOOP, severity=Severity.HIGH, confidence=Confidence.HIGH,
        first_turn=1, last_turn=2, evidence={}, cost_usd=0.05, summary="retry", session_id="sub-1",
    )
    parent_map = {"sub-1": "root"}
    wasted_sids = {"sub-1"}  # flagged -> whole cost already in fanout_waste
    assert _interior_waste([sub_finding], parent_map, wasted_sids) == 0.0


def test_interior_finding_in_flagged_ancestor_is_not_double_counted():
    """A grandchild finding is excluded when its parent subagent is flagged."""
    from cctx.diagnostician import _interior_waste
    from cctx.models import Confidence, Finding, FindingKind, Severity

    grand_finding = Finding(
        kind=FindingKind.RETRY_LOOP, severity=Severity.HIGH, confidence=Confidence.HIGH,
        first_turn=1, last_turn=2, evidence={}, cost_usd=0.05, summary="retry",
        session_id="grand-1",
    )
    parent_map = {"grand-1": "sub-1", "sub-1": "root"}
    wasted_sids = {"sub-1"}  # parent flagged -> grandchild already counted inclusively
    assert _interior_waste([grand_finding], parent_map, wasted_sids) == 0.0


def test_end_to_end_subagent_retry_loop_surfaces_and_is_attributed():
    """A subagent with a retry-loop pattern surfaces tagged; waste stays bounded."""
    import dataclasses

    from cctx.diagnostician import run
    from cctx.models import FindingKind
    from tests.diagnostician.conftest import (
        make_assistant_turn,
        make_tool_result,
        make_tool_result_turn,
        make_tool_use,
        make_trace,
        make_user_turn,
    )

    err = "Error: file not found"
    fp = "src/foo.py"
    retry_turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use("t1", "Edit", {"file_path": fp})]),
        make_tool_result_turn(3, tool_results=[make_tool_result("t1", "Edit", err, is_error=True)]),
        make_assistant_turn(4, tool_uses=[make_tool_use("t2", "Edit", {"file_path": fp})]),
        make_tool_result_turn(5, tool_results=[make_tool_result("t2", "Edit", err, is_error=True)]),
    ]
    sub = dataclasses.replace(make_trace(retry_turns), session_id="sub-1", parent_session_id="root")
    parent = dataclasses.replace(
        make_trace([make_user_turn(1), make_assistant_turn(2, text="ok")]),
        session_id="root", subagents=[sub],
    )
    diag = run(parent)
    tagged = [f for f in diag.findings if f.session_id == "sub-1"]
    assert any(f.kind is FindingKind.RETRY_LOOP for f in tagged)
    assert diag.waste_cost_usd <= diag.total_cost_usd


def test_attribution_records_dispatching_tool_use_id():
    """SubagentAttribution.dispatching_tool_use_id is the parent's Agent/Task
    tool_use_id that dispatched this subagent — the join key jig/studious use
    to correlate a dispatch-time routing decision with its actual cost (#193
    follow-up)."""
    from cctx.diagnostician import run
    child = _make_trace("child-1", input_tokens=1_000)
    tu = _agent_tu("child-1", description="Explore the codebase")
    parent = _make_trace("parent", input_tokens=1_000, subagents=[child], tool_uses=[tu])
    diag = run(parent)
    assert diag.subagent_costs[0].dispatching_tool_use_id == "tu_child-1"


def test_attribution_dispatching_tool_use_id_none_when_orphaned():
    """Unlinked subagent (no matching ToolUse) gets dispatching_tool_use_id=None."""
    from cctx.diagnostician import run
    child = _make_trace("child-unlinked-session", input_tokens=1_000)
    parent = _make_trace("parent", input_tokens=1_000, subagents=[child])
    diag = run(parent)
    assert diag.subagent_costs[0].dispatching_tool_use_id is None
