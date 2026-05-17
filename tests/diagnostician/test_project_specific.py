"""Tests for cctx/diagnostician/patterns/project_specific.py."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from tests.diagnostician.conftest import (
    make_assistant_turn,
    make_tool_result,
    make_tool_result_turn,
    make_tool_use,
    make_trace,
    make_user_turn,
)

UTC = timezone.utc


def _make_diagnosis(session_id: str):
    from cctx.models import Diagnosis
    return Diagnosis(
        session_id=session_id,
        findings=[],
        inflection_turn=None,
        patches=[],
        total_cost_usd=0.0,
        waste_cost_usd=0.0,
        analysed_at=datetime(2026, 5, 14, 10, tzinfo=UTC),
    )


def _make_pnpm_trace(session_id: str) -> object:
    """Trace: Bash('pnpm install') fails 2×, then Bash('pnpm --filter app build') succeeds."""
    turns = [make_user_turn(1)]
    for i in range(2):
        uid = f"tu-fail-{i:02d}"
        turns.append(make_assistant_turn(
            2 + i * 2,
            tool_uses=[make_tool_use(uid, "Bash", {"command": "pnpm install"})],
        ))
        turns.append(make_tool_result_turn(
            3 + i * 2,
            tool_results=[make_tool_result(uid, "Bash", "Error: workspace required", is_error=True)],
        ))
    uid_fix = "tu-fix"
    turns.append(make_assistant_turn(
        6, tool_uses=[make_tool_use(uid_fix, "Bash", {"command": "pnpm --filter app build"})],
    ))
    turns.append(make_tool_result_turn(
        7, tool_results=[make_tool_result(uid_fix, "Bash", "Done")],
    ))
    trace = make_trace(turns)
    return dataclasses.replace(trace, session_id=session_id)


def test_below_threshold_returns_no_patterns():
    """2 sessions — below default threshold of 3 — returns []."""
    from cctx.diagnostician.patterns.project_specific import detect

    pairs = [
        (_make_diagnosis(f"s{i}"), _make_pnpm_trace(f"s{i}"))
        for i in range(2)
    ]
    assert detect(pairs) == []


def test_three_sessions_returns_one_pattern():
    """3 sessions with identical failure/fix pair → one ProjectPattern."""
    from cctx.diagnostician.patterns.project_specific import detect

    pairs = [
        (_make_diagnosis(f"s{i}"), _make_pnpm_trace(f"s{i}"))
        for i in range(3)
    ]
    patterns = detect(pairs)
    assert len(patterns) == 1
    p = patterns[0]
    assert p.tool_name == "Bash"
    assert p.failure_key == "pnpm install"
    assert p.fix_key == "pnpm --filter app"
    assert p.session_count == 3
    assert p.avg_wasted_turns == 4.0   # fix_turn(6) - first_failure_turn(2)
    assert len(p.example_sessions) <= 3


def test_fix_outside_window_returns_no_pattern():
    """Fix more than 10 turns after last failure → no pattern detected."""
    from cctx.diagnostician.patterns.project_specific import detect

    def _far_fix_trace(session_id: str):
        turns = [make_user_turn(1)]
        for i in range(2):
            uid = f"tu-f{i}"
            turns.append(make_assistant_turn(
                2 + i * 2,
                tool_uses=[make_tool_use(uid, "Bash", {"command": "pnpm install"})],
            ))
            turns.append(make_tool_result_turn(
                3 + i * 2,
                tool_results=[make_tool_result(uid, "Bash", "Error: failed", is_error=True)],
            ))
        # last failure at turn 5; fill turns 6-16 so fix is at turn 17 (12 away)
        for j in range(11):
            turns.append(make_user_turn(6 + j))
        uid_fix = "tu-fix"
        turns.append(make_assistant_turn(
            17, tool_uses=[make_tool_use(uid_fix, "Bash", {"command": "pnpm --filter app build"})],
        ))
        turns.append(make_tool_result_turn(
            18, tool_results=[make_tool_result(uid_fix, "Bash", "Done")],
        ))
        trace = make_trace(turns)
        return dataclasses.replace(trace, session_id=session_id)

    pairs = [(_make_diagnosis(f"s{i}"), _far_fix_trace(f"s{i}")) for i in range(3)]
    assert detect(pairs) == []


def test_duplicate_session_id_counted_once():
    """Same session_id appearing twice in pairs counts as one session."""
    from cctx.diagnostician.patterns.project_specific import detect

    trace = _make_pnpm_trace("dup")
    diag = _make_diagnosis("dup")
    pairs = [
        (diag, trace),
        (diag, trace),  # duplicate — must not inflate session_count
        (_make_diagnosis("s1"), _make_pnpm_trace("s1")),
        (_make_diagnosis("s2"), _make_pnpm_trace("s2")),
    ]
    patterns = detect(pairs)
    assert len(patterns) == 1
    assert patterns[0].session_count == 3   # dup + s1 + s2, not 4


def test_different_tools_grouped_separately():
    """Bash and Edit failure patterns are counted as distinct patterns."""
    from cctx.diagnostician.patterns.project_specific import detect

    def _edit_trace(session_id: str):
        turns = [make_user_turn(1)]
        for i in range(2):
            uid = f"tu-e{i}"
            turns.append(make_assistant_turn(
                2 + i * 2,
                tool_uses=[make_tool_use(uid, "Edit", {"file_path": "src/foo.py"})],
            ))
            turns.append(make_tool_result_turn(
                3 + i * 2,
                tool_results=[make_tool_result(uid, "Edit", "Error: not found", is_error=True)],
            ))
        uid_fix = "tu-efix"
        turns.append(make_assistant_turn(
            6, tool_uses=[make_tool_use(uid_fix, "Edit", {"file_path": "src/bar.py"})],
        ))
        turns.append(make_tool_result_turn(
            7, tool_results=[make_tool_result(uid_fix, "Edit", "Done")],
        ))
        trace = make_trace(turns)
        return dataclasses.replace(trace, session_id=session_id)

    pairs = (
        [(_make_diagnosis(f"bash-{i}"), _make_pnpm_trace(f"bash-{i}")) for i in range(3)]
        + [(_make_diagnosis(f"edit-{i}"), _edit_trace(f"edit-{i}")) for i in range(3)]
    )
    patterns = detect(pairs)
    tool_names = {p.tool_name for p in patterns}
    assert "Bash" in tool_names
    assert "Edit" in tool_names
    assert len(patterns) == 2


def test_empty_pairs_returns_empty():
    from cctx.diagnostician.patterns.project_specific import detect
    assert detect([]) == []


def test_bash_normalization_first_three_tokens():
    """Bash key is first 3 space-separated tokens of the command."""
    from cctx.diagnostician.patterns.project_specific import _normalize_key
    assert _normalize_key("Bash", {"command": "pnpm install --legacy-peer-deps"}) == "pnpm install --legacy-peer-deps"
    assert _normalize_key("Bash", {"command": "pnpm --filter app build --verbose"}) == "pnpm --filter app"
    assert _normalize_key("Bash", {"command": "ls"}) == "ls"


def test_edit_normalization_uses_file_path():
    from cctx.diagnostician.patterns.project_specific import _normalize_key
    assert _normalize_key("Edit", {"file_path": "src/foo.py"}) == "src/foo.py"
