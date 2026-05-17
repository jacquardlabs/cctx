"""Tests for cctx/diagnostician/patterns/tool_thrash.py."""
from __future__ import annotations

from tests.diagnostician.conftest import (
    make_assistant_turn,
    make_tool_use,
    make_trace,
    make_user_turn,
)


def _trace_with_repeated_reads(n: int, file_path: str = "src/app.py"):
    """Trace where Read(file_path) is called n times identically."""
    turns = [make_user_turn(1, "check the file")]
    for i in range(n):
        uid = f"toolu_read_{i:02d}"
        turns.append(make_assistant_turn(
            2 + i,
            tool_uses=[make_tool_use(uid, "Read", {"file_path": file_path})],
        ))
    return make_trace(turns)


def test_no_thrash_below_threshold():
    from cctx.diagnostician.patterns.tool_thrash import classify

    # 2 identical calls — below MIN_REPEATS=3
    trace = _trace_with_repeated_reads(2)
    assert classify(trace) == []


def test_detects_thrash_at_threshold():
    from cctx.diagnostician.patterns.tool_thrash import classify
    from cctx.models import Confidence, FindingKind, Severity

    trace = _trace_with_repeated_reads(3)
    findings = classify(trace)
    assert len(findings) == 1
    f = findings[0]
    assert f.kind is FindingKind.TOOL_THRASH
    assert f.confidence is Confidence.HIGH
    assert f.severity is Severity.MEDIUM
    assert f.evidence["total_calls"] == 3


def test_severity_high_at_six_calls():
    from cctx.diagnostician.patterns.tool_thrash import classify
    from cctx.models import Severity

    trace = _trace_with_repeated_reads(6)
    findings = classify(trace)
    assert findings[0].severity is Severity.HIGH


def test_different_inputs_no_thrash():
    from cctx.diagnostician.patterns.tool_thrash import classify

    # Same tool (Read), different paths — not a thrash
    turns = [make_user_turn(1)]
    for i in range(5):
        uid = f"toolu_{i:02d}"
        turns.append(make_assistant_turn(
            2 + i,
            tool_uses=[make_tool_use(uid, "Read", {"file_path": f"src/file_{i}.py"})],
        ))
    trace = make_trace(turns)
    assert classify(trace) == []


def test_different_tools_same_input_no_thrash():
    from cctx.diagnostician.patterns.tool_thrash import classify

    # Different tools with similar patterns — no thrash per tool
    turns = [make_user_turn(1)]
    for tool in ["Read", "Bash", "Glob"]:
        uid = f"toolu_{tool}"
        turns.append(make_assistant_turn(
            2,
            tool_uses=[make_tool_use(uid, tool, {"file_path": "src/app.py"})],
        ))
    trace = make_trace(turns)
    assert classify(trace) == []


def test_clean_trace_no_tools():
    from cctx.diagnostician.patterns.tool_thrash import classify

    trace = make_trace([make_user_turn(1), make_user_turn(2)])
    assert classify(trace) == []


def test_window_constraint_outside_window():
    from cctx.diagnostician.patterns.tool_thrash import WINDOW, classify

    # Calls spread more than WINDOW turns apart — no thrash burst
    turns = [make_user_turn(1)]
    for i in range(3):
        turn_num = 2 + i * (WINDOW + 5)
        uid = f"toolu_{i:02d}"
        turns.append(make_assistant_turn(
            turn_num,
            tool_uses=[make_tool_use(uid, "Read", {"file_path": "src/app.py"})],
        ))
    trace = make_trace(turns)
    assert classify(trace) == []


def test_summary_mentions_tool_and_count():
    from cctx.diagnostician.patterns.tool_thrash import classify

    trace = _trace_with_repeated_reads(4)
    findings = classify(trace)
    assert "Read" in findings[0].summary
    assert "4" in findings[0].summary
