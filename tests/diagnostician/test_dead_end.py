"""Tests for cctx/diagnostician/patterns/dead_end.py."""
from __future__ import annotations

from tests.diagnostician.conftest import (
    make_assistant_turn,
    make_tool_result,
    make_tool_result_turn,
    make_tool_use,
    make_trace,
    make_user_turn,
)


def _dead_end_trace(fail_count: int = 2, pivot_tool: str = "Bash"):
    """
    Trace: user asks, assistant fails on Edit(src/foo.py) `fail_count` times,
    then pivots to a different tool (pivot_tool).
    """
    turns = [make_user_turn(1, "fix it")]
    turn = 2
    for i in range(fail_count):
        uid = f"toolu_fail_{i:02d}"
        turns.append(make_assistant_turn(
            turn, tool_uses=[make_tool_use(uid, "Edit", {"file_path": "src/foo.py"})]
        ))
        turns.append(make_tool_result_turn(
            turn + 1,
            tool_results=[make_tool_result(uid, "Edit", "Error: file locked", is_error=True)],
        ))
        turn += 2

    # Pivot: successful call with a different tool
    uid_pivot = "toolu_pivot"
    turns.append(make_assistant_turn(
        turn, tool_uses=[make_tool_use(uid_pivot, pivot_tool, {"command": "ls src/"})]
    ))
    turns.append(make_tool_result_turn(
        turn + 1,
        tool_results=[make_tool_result(uid_pivot, pivot_tool, "src/foo.py", is_error=False)],
    ))
    return make_trace(turns)


def test_no_dead_end_single_failure():
    from cctx.diagnostician.patterns.dead_end import classify

    # Only 1 failure before pivot — below N_FAIL_MIN=2
    turns = [make_user_turn(1)]
    turns.append(make_assistant_turn(2, tool_uses=[make_tool_use("u01", "Edit", {"file_path": "a.py"})]))
    turns.append(make_tool_result_turn(3, tool_results=[make_tool_result("u01", "Edit", "Error: x", is_error=True)]))
    turns.append(make_assistant_turn(4, tool_uses=[make_tool_use("u02", "Bash", {"command": "ls"})]))
    turns.append(make_tool_result_turn(5, tool_results=[make_tool_result("u02", "Bash", "ok", is_error=False)]))
    assert classify(make_trace(turns)) == []


def test_detects_dead_end_two_failures():
    from cctx.diagnostician.patterns.dead_end import classify
    from cctx.models import Confidence, FindingKind, Severity

    findings = classify(_dead_end_trace(fail_count=2))
    assert len(findings) == 1
    f = findings[0]
    assert f.kind is FindingKind.DEAD_END
    assert f.confidence is Confidence.HIGH
    assert f.severity is Severity.MEDIUM
    assert f.evidence["total_fails"] == 2


def test_severity_high_at_five_failures():
    from cctx.diagnostician.patterns.dead_end import classify
    from cctx.models import Severity

    findings = classify(_dead_end_trace(fail_count=5))
    assert findings[0].severity is Severity.HIGH


def test_no_dead_end_when_same_tool_succeeds():
    from cctx.diagnostician.patterns.dead_end import classify

    # Failures then success WITH THE SAME tool/key — not a pivot, so no dead-end
    turns = [make_user_turn(1)]
    for i in range(3):
        uid = f"toolu_{i:02d}"
        turns.append(make_assistant_turn(
            2 + i * 2, tool_uses=[make_tool_use(uid, "Edit", {"file_path": "src/foo.py"})]
        ))
        is_err = i < 2
        turns.append(make_tool_result_turn(
            3 + i * 2,
            tool_results=[make_tool_result(uid, "Edit", "Error: x" if is_err else "ok", is_error=is_err)],
        ))
    assert classify(make_trace(turns)) == []


def test_clean_trace_no_findings():
    from cctx.diagnostician.patterns.dead_end import classify

    turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use("u01", "Bash", {"command": "ls"})]),
        make_tool_result_turn(3, tool_results=[make_tool_result("u01", "Bash", "ok", is_error=False)]),
    ]
    assert classify(make_trace(turns)) == []


def test_compaction_resets_error_run():
    from cctx.diagnostician.patterns.dead_end import classify

    # 2 failures, then a compaction event, then a pivot — the run was reset by
    # compaction so no dead-end should fire
    turns = [make_user_turn(1)]
    for i in range(2):
        uid = f"toolu_fail_{i}"
        turns.append(make_assistant_turn(
            2 + i * 2, tool_uses=[make_tool_use(uid, "Edit", {"file_path": "src/foo.py"})]
        ))
        turns.append(make_tool_result_turn(
            3 + i * 2,
            tool_results=[make_tool_result(uid, "Edit", "Error: x", is_error=True)],
        ))
    # Compaction turn
    from cctx.models import Turn
    from tests.diagnostician.conftest import _dt
    turns.append(Turn(
        turn_number=7,
        uuid="uuid-compact",
        parent_uuid=None,
        role="user",
        text="<context_window_compacted/>",
        thinking="",
        tool_uses=[],
        tool_results=[],
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=_dt(70),
        duration_ms=None,
    ))
    # Pivot after compaction
    uid_pivot = "toolu_pivot"
    turns.append(make_assistant_turn(
        8, tool_uses=[make_tool_use(uid_pivot, "Bash", {"command": "ls"})]
    ))
    turns.append(make_tool_result_turn(
        9, tool_results=[make_tool_result(uid_pivot, "Bash", "ok", is_error=False)]
    ))
    assert classify(make_trace(turns)) == []


def test_summary_mentions_failed_tool():
    from cctx.diagnostician.patterns.dead_end import classify

    findings = classify(_dead_end_trace(fail_count=3))
    assert "Edit" in findings[0].summary
    assert "3" in findings[0].summary
