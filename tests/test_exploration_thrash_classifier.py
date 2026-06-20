"""Tests for exploration_thrash classifier (issue #99)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cctx.models import SessionTrace, ToolResult, ToolUse, Turn, Usage

_TS = datetime(2026, 6, 10, tzinfo=timezone.utc)
_USAGE = Usage(500, 100, 0, 0, 0, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_turn(n: int, path: str = "/foo.py") -> Turn:
    tu = ToolUse(
        tool_name="Read",
        tool_use_id=f"r{n}",
        tool_input={"file_path": path},
    )
    tr = ToolResult(
        tool_name="Read",
        tool_use_id=f"r{n}",
        content="content",
        structured=None,
        is_error=False,
    )
    return Turn(
        turn_number=n,
        uuid=f"t{n}",
        parent_uuid=None,
        role="assistant",
        text="",
        thinking="",
        tool_uses=[tu],
        tool_results=[tr],
        usage=_USAGE,
        model=None,
        stop_reason="tool_use",
        timestamp=_TS,
        duration_ms=None,
    )


def _write_turn(n: int, path: str = "/foo.py") -> Turn:
    tu = ToolUse(
        tool_name="Edit",
        tool_use_id=f"w{n}",
        tool_input={"file_path": path},
    )
    tr = ToolResult(
        tool_name="Edit",
        tool_use_id=f"w{n}",
        content="ok",
        structured=None,
        is_error=False,
    )
    return Turn(
        turn_number=n,
        uuid=f"t{n}",
        parent_uuid=None,
        role="assistant",
        text="",
        thinking="",
        tool_uses=[tu],
        tool_results=[tr],
        usage=_USAGE,
        model=None,
        stop_reason="tool_use",
        timestamp=_TS,
        duration_ms=None,
    )


def _grep_turn(n: int, pattern: str = "def foo") -> Turn:
    tu = ToolUse(
        tool_name="Grep",
        tool_use_id=f"g{n}",
        tool_input={"pattern": pattern},
    )
    tr = ToolResult(
        tool_name="Grep",
        tool_use_id=f"g{n}",
        content="match",
        structured=None,
        is_error=False,
    )
    return Turn(
        turn_number=n,
        uuid=f"t{n}",
        parent_uuid=None,
        role="assistant",
        text="",
        thinking="",
        tool_uses=[tu],
        tool_results=[tr],
        usage=_USAGE,
        model=None,
        stop_reason="tool_use",
        timestamp=_TS,
        duration_ms=None,
    )


def _trace(turns: list[Turn]) -> SessionTrace:
    return SessionTrace(
        session_id="test-session",
        parent_session_id=None,
        project_path="/test",
        cwd="/test",
        primary_model="claude-sonnet-4-6",
        claude_code_version="1.0",
        turns=turns,
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=_TS,
        end_time=_TS,
        source_path=Path("/test/session.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


# ---------------------------------------------------------------------------
# Model smoke tests
# ---------------------------------------------------------------------------


def test_exploration_thrash_kind_exists():
    from cctx.models import FindingKind
    assert FindingKind.EXPLORATION_THRASH == "exploration_thrash"


def test_exploration_thrash_kind_label():
    from cctx.models import KIND_LABEL, FindingKind
    assert KIND_LABEL[FindingKind.EXPLORATION_THRASH] == "EXPLORATION THRASH"


def test_exploration_thrash_managed_heading():
    from cctx.models import MANAGED_HEADINGS, FindingKind
    assert MANAGED_HEADINGS[FindingKind.EXPLORATION_THRASH] == "## Exploration thrash"


# ---------------------------------------------------------------------------
# Classifier tests
# ---------------------------------------------------------------------------


def test_too_few_active_turns_no_window_finding():
    """Fewer than WINDOW_SIZE (6) active tool turns with no repeated calls → no finding."""
    from cctx.diagnostician.patterns.exploration_thrash import classify

    # 5 turns each reading a distinct file — not enough for a window, no repeats
    turns = [_read_turn(i, path=f"/file{i}.py") for i in range(1, 6)]
    assert classify(_trace(turns)) == []


def test_all_write_turns_no_finding():
    """6 consecutive Edit turns → no finding (no read-only ratio exceeded)."""
    from cctx.diagnostician.patterns.exploration_thrash import classify

    turns = [_write_turn(i) for i in range(1, 7)]
    assert classify(_trace(turns)) == []


def test_six_read_turns_fires_high_severity():
    """6 consecutive Read turns (100% read-only, no writes) → HIGH severity finding."""
    from cctx.diagnostician.patterns.exploration_thrash import classify
    from cctx.models import FindingKind, Severity

    turns = [_read_turn(i, path=f"/file{i}.py") for i in range(1, 7)]
    findings = classify(_trace(turns))

    assert len(findings) == 1
    f = findings[0]
    assert f.kind is FindingKind.EXPLORATION_THRASH
    assert f.severity is Severity.HIGH
    assert len(f.evidence["thrash_windows"]) == 1
    assert f.evidence["thrash_windows"][0]["read_ratio"] == 1.0


def test_three_reads_three_writes_no_finding():
    """3 read turns then 3 write turns — no window is all-read."""
    from cctx.diagnostician.patterns.exploration_thrash import classify

    turns = [_read_turn(i, path=f"/file{i}.py") for i in range(1, 4)]
    turns += [_write_turn(i) for i in range(4, 7)]
    assert classify(_trace(turns)) == []


def test_repeated_identical_grep_fires_medium():
    """Same Grep pattern called 3× → MEDIUM severity (repeated_reads signal only)."""
    from cctx.diagnostician.patterns.exploration_thrash import classify
    from cctx.models import FindingKind, Severity

    # Only 3 active turns → below WINDOW_SIZE=6, so no thrash window
    # but the repeat threshold should still trigger
    turns = [_grep_turn(i, pattern="def authenticate") for i in range(1, 4)]
    findings = classify(_trace(turns))

    assert len(findings) == 1
    f = findings[0]
    assert f.kind is FindingKind.EXPLORATION_THRASH
    assert f.severity is Severity.MEDIUM
    assert f.evidence["thrash_windows"] == []
    assert len(f.evidence["repeated_reads"]) == 1
    assert f.evidence["repeated_reads"][0]["count"] == 3
    assert f.evidence["repeated_reads"][0]["tool_name"] == "Grep"


def test_window_with_one_write_among_reads_no_finding():
    """6 turns where 1 is a write (17% write) — below 80% read threshold → no window finding."""
    from cctx.diagnostician.patterns.exploration_thrash import classify

    # 5 reads + 1 write = 83% read, but has_write is True → should NOT fire
    turns = [_read_turn(i, path=f"/f{i}.py") for i in range(1, 6)]
    turns.append(_write_turn(6))
    assert classify(_trace(turns)) == []


def test_summary_contains_ratio():
    """Finding summary includes the read-only percentage."""
    from cctx.diagnostician.patterns.exploration_thrash import classify

    turns = [_read_turn(i, path=f"/file{i}.py") for i in range(1, 7)]
    findings = classify(_trace(turns))

    assert len(findings) == 1
    assert "100%" in findings[0].summary


def test_first_last_turn_span():
    """first_turn and last_turn correctly span the thrash window."""
    from cctx.diagnostician.patterns.exploration_thrash import classify

    turns = [_read_turn(i, path=f"/file{i}.py") for i in range(1, 7)]
    findings = classify(_trace(turns))

    assert findings[0].first_turn == 1
    assert findings[0].last_turn == 6


def test_no_tool_calls_no_finding():
    """Turns with no tool_uses are ignored; session with only text turns → no finding."""
    from cctx.diagnostician.patterns.exploration_thrash import classify

    def _text_turn(n: int) -> Turn:
        return Turn(
            turn_number=n,
            uuid=f"t{n}",
            parent_uuid=None,
            role="assistant",
            text="thinking...",
            thinking="",
            tool_uses=[],
            tool_results=[],
            usage=_USAGE,
            model=None,
            stop_reason="end_turn",
            timestamp=_TS,
            duration_ms=None,
        )

    turns = [_text_turn(i) for i in range(1, 10)]
    assert classify(_trace(turns)) == []
