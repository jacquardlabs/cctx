"""Tests for cctx/renderers/terminal.py.

Tests capture Console output as text; they don't check for exact ANSI codes,
only that key information is present in the output.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO


def _make_finding(kind_str: str, cost: float | None = None):
    from cctx.models import Confidence, Finding, FindingKind, Severity

    kind_map = {
        "retry_loop": FindingKind.RETRY_LOOP,
        "scope_creep": FindingKind.SCOPE_CREEP,
        "stale_context": FindingKind.STALE_CONTEXT,
    }
    return Finding(
        kind=kind_map[kind_str],
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=5,
        last_turn=10,
        evidence={},
        cost_usd=cost,
        summary=f"test {kind_str} finding",
    )


def _make_patch(kind_str: str):
    from cctx.models import FindingKind, Patch

    kind_map = {
        "retry_loop": FindingKind.RETRY_LOOP,
        "scope_creep": FindingKind.SCOPE_CREEP,
        "stale_context": FindingKind.STALE_CONTEXT,
    }
    return Patch(
        target_file="CLAUDE.md",
        description="Add discipline rule",
        unified_diff="+## Retry discipline\n+Stop after two failures.",
        finding_kind=kind_map[kind_str],
        evidence_summary="test evidence",
    )


def _make_diagnosis(findings=None, patches=None):
    from cctx.models import Diagnosis

    return Diagnosis(
        session_id="abc123",
        findings=findings or [],
        inflection_turn=5 if findings else None,
        patches=patches or [],
        total_cost_usd=2.14,
        waste_cost_usd=sum(f.cost_usd or 0 for f in (findings or [])),
        analysed_at=datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc),
    )


def _render_to_string(diagnosis):
    from rich.console import Console

    from cctx.renderers.terminal import render_diagnosis

    buf = StringIO()
    console = Console(file=buf, width=120, highlight=False, markup=False)
    render_diagnosis(diagnosis, console=console)
    return buf.getvalue()


def test_clean_session_shows_no_findings():
    output = _render_to_string(_make_diagnosis())
    assert "No findings" in output or "clean" in output.lower()


def test_session_id_shown():
    output = _render_to_string(_make_diagnosis([_make_finding("retry_loop")]))
    assert "abc123" in output


def test_retry_loop_finding_shown():
    output = _render_to_string(_make_diagnosis([_make_finding("retry_loop")]))
    assert "retry" in output.lower() or "loop" in output.lower()


def test_inflection_turn_shown():
    output = _render_to_string(_make_diagnosis([_make_finding("retry_loop")]))
    assert "5" in output  # inflection_turn=5


def test_cost_shown():
    diag = _make_diagnosis([_make_finding("stale_context", cost=0.88)])
    output = _render_to_string(diag)
    assert "~$2.14" in output or "2.14" in output


def test_cost_approximation_note_shown():
    output = _render_to_string(_make_diagnosis())
    assert "85" in output or "95" in output or "~" in output


def test_patch_diff_shown():
    diag = _make_diagnosis(
        findings=[_make_finding("retry_loop")],
        patches=[_make_patch("retry_loop")],
    )
    output = _render_to_string(diag)
    assert "Retry discipline" in output or "CLAUDE.md" in output


def test_verdict_shown_in_output():
    diag = _make_diagnosis([_make_finding("retry_loop")])
    output = _render_to_string(diag)
    assert "Verdict" in output


def test_verdict_clean_shown():
    output = _render_to_string(_make_diagnosis())
    assert "clean" in output.lower()


# ---------------------------------------------------------------------------
# render_turn (#76)
# ---------------------------------------------------------------------------


def _make_trace_with_turn(turn_number=3, role="assistant", text="some content"):
    from datetime import datetime, timezone

    from cctx.models import SessionTrace, Turn

    t = Turn(
        turn_number=turn_number,
        uuid=f"uuid-{turn_number}",
        parent_uuid=None,
        role=role,
        text=text,
        thinking="",
        tool_uses=[],
        tool_results=[],
        usage=None,
        model="claude-sonnet-4-6",
        stop_reason="end_turn",
        timestamp=datetime(2026, 5, 14, 10, 30, 0, tzinfo=timezone.utc),
        duration_ms=None,
    )
    from pathlib import Path
    return SessionTrace(
        session_id="trace-test",
        parent_session_id=None,
        project_path="/p",
        cwd="/p",
        primary_model="claude-sonnet-4-6",
        claude_code_version=None,
        turns=[t],
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=t.timestamp,
        end_time=t.timestamp,
        source_path=Path("/p/trace-test.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


def _render_turn_to_string(trace, diagnosis, turn_num):
    from rich.console import Console

    from cctx.renderers.terminal import render_turn

    buf = StringIO()
    console = Console(file=buf, width=120, highlight=False, markup=False)
    render_turn(trace, diagnosis, turn_num, console=console)
    return buf.getvalue()


def test_render_turn_shows_role_and_number():
    trace = _make_trace_with_turn(turn_number=3, role="assistant", text="hello world")
    diag = _make_diagnosis()
    output = _render_turn_to_string(trace, diag, 3)
    assert "Turn 3" in output
    assert "assistant" in output


def test_render_turn_shows_text():
    trace = _make_trace_with_turn(text="important content here")
    diag = _make_diagnosis()
    output = _render_turn_to_string(trace, diag, 3)
    assert "important content here" in output


def test_render_turn_not_found():
    trace = _make_trace_with_turn(turn_number=3)
    diag = _make_diagnosis()
    output = _render_turn_to_string(trace, diag, 99)
    assert "not found" in output.lower() or "99" in output


def test_render_turn_shows_active_finding():
    trace = _make_trace_with_turn(turn_number=5)
    finding = _make_finding("retry_loop")  # first_turn=5, last_turn=10
    diag = _make_diagnosis([finding])
    output = _render_turn_to_string(trace, diag, 5)
    assert "retry" in output.lower() or "RETRY" in output


# ---------------------------------------------------------------------------
# render_aggregate project patterns (#81)
# ---------------------------------------------------------------------------


def _make_aggregate_report_with_pattern():
    from cctx.models import AggregateReport, ProjectPattern

    pp = ProjectPattern(
        tool_name="Bash",
        failure_key="pnpm install",
        fix_key="pnpm --filter app",
        session_count=7,
        avg_wasted_turns=12.3,
        total_waste_usd=4.20,
        example_sessions=["s1", "s2", "s3"],
    )
    return AggregateReport(
        period_label="last 30 days",
        sessions_analysed=41,
        sessions_with_findings=7,
        total_cost_usd=22.0,
        waste_cost_usd=4.20,
        by_kind={},
        patches=[],
        project_patterns=[pp],
    )


def _render_aggregate_to_string(report):
    from io import StringIO
    from rich.console import Console
    from cctx.renderers.terminal import render_aggregate
    buf = StringIO()
    console = Console(file=buf, width=120, highlight=False, markup=False)
    render_aggregate(report, console=console)
    return buf.getvalue()


def test_render_aggregate_shows_project_patterns_table():
    output = _render_aggregate_to_string(_make_aggregate_report_with_pattern())
    assert "pnpm install" in output
    assert "pnpm --filter app" in output


def test_render_aggregate_project_pattern_shows_session_count():
    output = _render_aggregate_to_string(_make_aggregate_report_with_pattern())
    assert "7" in output


def test_render_aggregate_no_patterns_no_extra_table():
    from cctx.models import AggregateReport
    report = AggregateReport(
        period_label="last 7 days",
        sessions_analysed=2,
        sessions_with_findings=0,
        total_cost_usd=1.0,
        waste_cost_usd=0.0,
        by_kind={},
        patches=[],
    )
    output = _render_aggregate_to_string(report)
    assert "Project-specific" not in output


def test_render_aggregate_patterns_visible_even_when_by_kind_empty():
    """Project patterns table renders even when there are no per-session findings."""
    output = _render_aggregate_to_string(_make_aggregate_report_with_pattern())
    # by_kind is empty but pattern table should still appear
    assert "pnpm install" in output
