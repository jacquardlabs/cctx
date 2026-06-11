"""Tests for per-subagent cost attribution (M16 #88)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cctx.models import SessionTrace, ToolUse, Turn, Usage

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
