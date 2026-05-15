"""Tests for cctx/diagnostician/patterns/retry_loop.py."""
from __future__ import annotations

from tests.diagnostician.conftest import (
    make_assistant_turn,
    make_tool_result,
    make_tool_result_turn,
    make_tool_use,
    make_trace,
    make_user_turn,
)


def _edit_trace_with_retry(n_fails: int = 2):
    """Trace where Edit(src/foo.py) fails n_fails times, no fix between."""
    turns = [make_user_turn(1, "fix src/foo.py")]
    for i in range(n_fails):
        turn_num_a = 2 + i * 2
        turn_num_r = 3 + i * 2
        uid = f"toolu_{i:02d}"
        turns.append(make_assistant_turn(
            turn_num_a,
            tool_uses=[make_tool_use(uid, "Edit", {"file_path": "src/foo.py"})],
        ))
        turns.append(make_tool_result_turn(
            turn_num_r,
            tool_results=[make_tool_result(uid, "Edit", "Error: file not found", is_error=True)],
        ))
    return make_trace(turns)


def test_no_retry_on_single_call():
    from cctx.diagnostician.patterns.retry_loop import classify

    turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use("tu01", "Edit", {"file_path": "a.py"})]),
        make_tool_result_turn(3, tool_results=[make_tool_result("tu01", "Edit", "Error: oops", is_error=True)]),
    ]
    assert classify(make_trace(turns)) == []


def test_detects_retry_loop_two_failures():
    from cctx.diagnostician.patterns.retry_loop import classify
    from cctx.models import Confidence, FindingKind, Severity

    findings = classify(_edit_trace_with_retry(2))
    assert len(findings) == 1
    f = findings[0]
    assert f.kind is FindingKind.RETRY_LOOP
    assert f.confidence is Confidence.HIGH
    assert f.severity is Severity.MEDIUM
    assert f.first_turn == 4  # second failing call is turn 4
    assert f.evidence["loop_length"] == 2


def test_severity_high_at_four_failures():
    from cctx.diagnostician.patterns.retry_loop import classify
    from cctx.models import Severity

    findings = classify(_edit_trace_with_retry(4))
    assert findings[0].severity is Severity.HIGH


def test_no_retry_when_success_intervenes():
    from cctx.diagnostician.patterns.retry_loop import classify

    turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use("tu01", "Edit", {"file_path": "a.py"})]),
        make_tool_result_turn(3, tool_results=[make_tool_result("tu01", "Edit", "Error: oops", is_error=True)]),
        make_assistant_turn(4, tool_uses=[make_tool_use("tu02", "Edit", {"file_path": "a.py"})]),
        make_tool_result_turn(5, tool_results=[make_tool_result("tu02", "Edit", "ok", is_error=False)]),
        make_assistant_turn(6, tool_uses=[make_tool_use("tu03", "Edit", {"file_path": "a.py"})]),
        make_tool_result_turn(7, tool_results=[make_tool_result("tu03", "Edit", "Error: oops", is_error=True)]),
    ]
    assert classify(make_trace(turns)) == []


def test_bash_key_uses_command():
    from cctx.diagnostician.patterns.retry_loop import classify
    from cctx.models import FindingKind

    turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use("tu01", "Bash", {"command": "ls -la"})]),
        make_tool_result_turn(3, tool_results=[make_tool_result("tu01", "Bash", "Error: permission denied", is_error=True)]),
        make_assistant_turn(4, tool_uses=[make_tool_use("tu02", "Bash", {"command": "ls -la"})]),
        make_tool_result_turn(5, tool_results=[make_tool_result("tu02", "Bash", "Error: permission denied", is_error=True)]),
    ]
    findings = classify(make_trace(turns))
    assert len(findings) == 1
    assert findings[0].kind is FindingKind.RETRY_LOOP


def test_different_keys_not_a_loop():
    from cctx.diagnostician.patterns.retry_loop import classify

    turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use("tu01", "Edit", {"file_path": "a.py"})]),
        make_tool_result_turn(3, tool_results=[make_tool_result("tu01", "Edit", "Error: oops", is_error=True)]),
        make_assistant_turn(4, tool_uses=[make_tool_use("tu02", "Edit", {"file_path": "b.py"})]),
        make_tool_result_turn(5, tool_results=[make_tool_result("tu02", "Edit", "Error: oops", is_error=True)]),
    ]
    assert classify(make_trace(turns)) == []


def test_empty_trace_returns_empty():
    from cctx.diagnostician.patterns.retry_loop import classify

    assert classify(make_trace([])) == []


def test_cost_usd_is_none():
    from cctx.diagnostician.patterns.retry_loop import classify

    findings = classify(_edit_trace_with_retry(2))
    assert findings[0].cost_usd is None


def test_summary_mentions_tool_and_turns():
    from cctx.diagnostician.patterns.retry_loop import classify

    findings = classify(_edit_trace_with_retry(2))
    assert "Edit" in findings[0].summary
    assert "fail" in findings[0].summary.lower() or "×" in findings[0].summary


def test_error_detected_by_error_prefix():
    """is_error=False but content starts with 'Error:' — should detect loop."""
    from cctx.diagnostician.patterns.retry_loop import classify
    from cctx.models import FindingKind

    turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use("tu01", "Bash", {"command": "ls"})]),
        make_tool_result_turn(3, tool_results=[make_tool_result("tu01", "Bash", "Error: permission denied", is_error=False)]),
        make_assistant_turn(4, tool_uses=[make_tool_use("tu02", "Bash", {"command": "ls"})]),
        make_tool_result_turn(5, tool_results=[make_tool_result("tu02", "Bash", "Error: permission denied", is_error=False)]),
    ]
    findings = classify(make_trace(turns))
    assert len(findings) == 1
    assert findings[0].kind is FindingKind.RETRY_LOOP


def test_substring_error_not_detected_without_flag():
    """Content containing 'error:' but not starting with it — NOT an error."""
    from cctx.diagnostician.patterns.retry_loop import classify

    turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use("tu01", "Bash", {"command": "ls"})]),
        make_tool_result_turn(3, tool_results=[make_tool_result("tu01", "Bash", "Warning: encountered error: 42", is_error=False)]),
        make_assistant_turn(4, tool_uses=[make_tool_use("tu02", "Bash", {"command": "ls"})]),
        make_tool_result_turn(5, tool_results=[make_tool_result("tu02", "Bash", "Warning: encountered error: 42", is_error=False)]),
    ]
    # Content doesn't start with "Error:" / "error:" / "FAILED" and is_error=False
    assert classify(make_trace(turns)) == []
