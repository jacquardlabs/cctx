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
