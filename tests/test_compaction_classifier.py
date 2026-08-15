"""Tests for compaction classifier (#93) and related models."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cctx.models import SessionTrace, ToolResult, ToolUse, Turn, Usage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = datetime(2026, 6, 10, tzinfo=timezone.utc)
_USAGE = Usage(100, 50, 0, 0, 0, None)


def _tu(tool_name: str, uid: str, tool_input: dict) -> ToolUse:
    return ToolUse(
        tool_name=tool_name,
        tool_use_id=uid,
        tool_input=tool_input,
    )


def _tr(
    tool_name: str,
    uid: str,
    content: str = "file content here",
    is_error: bool = False,
    token_count: int = 0,
) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        tool_use_id=uid,
        content=content,
        structured=None,
        is_error=is_error,
        token_count=token_count,
    )


def _turn(
    n: int,
    role: str,
    tool_uses: list | None = None,
    tool_results: list | None = None,
    text: str = "",
) -> Turn:
    return Turn(
        turn_number=n,
        uuid=f"uuid-{n}",
        parent_uuid=None,
        role=role,
        text=text,
        thinking="",
        tool_uses=tool_uses or [],
        tool_results=tool_results or [],
        usage=_USAGE if role == "assistant" else None,
        model="claude-sonnet-4-6",
        stop_reason="tool_use" if tool_uses else "end_turn",
        timestamp=_TS,
        duration_ms=100,
    )


def _compaction_turn(n: int) -> Turn:
    """Build a context-window compaction turn."""
    return Turn(
        turn_number=n,
        uuid=f"comp-{n}",
        parent_uuid=None,
        role="system",
        text="<context_window_compaction>...</context_window_compaction>",
        thinking="",
        tool_uses=[],
        tool_results=[],
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=_TS,
        duration_ms=None,
    )


def _trace(turns: list) -> SessionTrace:
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
# Smoke tests — models
# ---------------------------------------------------------------------------


def test_compaction_kind_exists():
    from cctx.models import FindingKind
    assert FindingKind.COMPACTION == "compaction"


def test_compaction_has_kind_label():
    from cctx.models import KIND_LABEL, FindingKind
    assert KIND_LABEL[FindingKind.COMPACTION] == "COMPACTION"


def test_compaction_has_managed_heading():
    from cctx.models import MANAGED_HEADINGS, FindingKind
    assert MANAGED_HEADINGS[FindingKind.COMPACTION] == "## Compaction hygiene"


# ---------------------------------------------------------------------------
# is_compaction_turn helper
# ---------------------------------------------------------------------------


def test_is_compaction_turn_system_compact():
    from cctx.diagnostician.patterns.compaction import is_compaction_turn
    t = _turn(1, "system", text="<context_window_compaction>...</context_window_compaction>")
    assert is_compaction_turn(t) is True


def test_is_compaction_turn_system_compact_case_insensitive():
    from cctx.diagnostician.patterns.compaction import is_compaction_turn
    t = _turn(1, "system", text="Context COMPACT summary follows")
    assert is_compaction_turn(t) is True


def test_is_compaction_turn_context_window_prefix():
    from cctx.diagnostician.patterns.compaction import is_compaction_turn
    # Non-system role but text starts with <context_window
    t = _turn(1, "user", text="<context_window>some content</context_window>")
    assert is_compaction_turn(t) is True


def test_is_compaction_turn_normal_assistant():
    from cctx.diagnostician.patterns.compaction import is_compaction_turn
    t = _turn(1, "assistant", text="Here is what I found in the codebase.")
    assert is_compaction_turn(t) is False


def test_is_compaction_turn_normal_system():
    from cctx.diagnostician.patterns.compaction import is_compaction_turn
    t = _turn(1, "system", text="You are a helpful assistant.")
    assert is_compaction_turn(t) is False



# ---------------------------------------------------------------------------
# Classifier: no compactions → no findings
# ---------------------------------------------------------------------------


def test_no_compactions_no_findings():
    from cctx.diagnostician.patterns.compaction import classify
    turns = [
        _turn(1, "user", text="Do something"),
        _turn(2, "assistant", text="Working on it"),
    ]
    findings = classify(_trace(turns))
    assert findings == []


# ---------------------------------------------------------------------------
# Classifier: 1 compaction, no re-fetches → LOW severity
# ---------------------------------------------------------------------------


def test_one_compaction_no_refetch_low_severity():
    from cctx.diagnostician.patterns.compaction import classify
    from cctx.models import FindingKind, Severity

    turns = [
        _turn(1, "user", text="Start task"),
        _turn(2, "assistant", text="Doing work"),
        _compaction_turn(3),
        _turn(4, "assistant", text="Continuing after compaction"),
    ]
    findings = classify(_trace(turns))
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == FindingKind.COMPACTION
    assert f.severity == Severity.LOW
    assert f.evidence["n_compactions"] == 1
    assert f.evidence["compaction_turns"] == [3]
    assert f.evidence["re_fetches"] == []
    assert f.evidence["total_refetch_tokens"] == 0


# ---------------------------------------------------------------------------
# Classifier: 1 compaction + 1 re-fetch → HIGH severity
# ---------------------------------------------------------------------------


def test_one_compaction_with_refetch_high_severity():
    from cctx.diagnostician.patterns.compaction import classify
    from cctx.models import FindingKind, Severity

    # Turn 2: assistant reads /foo/bar.py before compaction
    tu_read = _tu("Read", "uid-read-1", {"file_path": "/foo/bar.py"})
    tr_read = _tr("Read", "uid-read-1", content="def main(): pass", token_count=50)

    # Turn 6: assistant re-reads /foo/bar.py after compaction
    tu_reread = _tu("Read", "uid-read-2", {"file_path": "/foo/bar.py"})
    tr_reread = _tr("Read", "uid-read-2", content="def main(): pass", token_count=50)

    turns = [
        _turn(1, "user", text="Start"),
        _turn(2, "assistant", tool_uses=[tu_read], tool_results=[tr_read]),
        _compaction_turn(3),
        _turn(4, "user", text="Continue"),
        _turn(5, "assistant", text="Back at it"),
        _turn(6, "assistant", tool_uses=[tu_reread], tool_results=[tr_reread]),
    ]
    findings = classify(_trace(turns))
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == FindingKind.COMPACTION
    assert f.severity == Severity.HIGH
    assert f.evidence["n_compactions"] == 1
    assert len(f.evidence["re_fetches"]) == 1
    refetch = f.evidence["re_fetches"][0]
    assert refetch["path"] == "/foo/bar.py"
    assert refetch["turn"] == 6
    assert refetch["tokens"] == 50
    assert f.evidence["total_refetch_tokens"] == 50


# ---------------------------------------------------------------------------
# Classifier: multiple compactions
# ---------------------------------------------------------------------------


def test_multiple_compactions_tracked():
    from cctx.diagnostician.patterns.compaction import classify
    from cctx.models import FindingKind

    turns = [
        _turn(1, "user", text="Start"),
        _compaction_turn(2),
        _turn(3, "assistant", text="After first compaction"),
        _compaction_turn(5),
        _turn(6, "assistant", text="After second compaction"),
    ]
    findings = classify(_trace(turns))
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == FindingKind.COMPACTION
    assert f.evidence["n_compactions"] == 2
    assert f.evidence["compaction_turns"] == [2, 5]
    assert f.first_turn == 2
    assert f.last_turn == 5


# ---------------------------------------------------------------------------
# Classifier: only first re-fetch per file counted
# ---------------------------------------------------------------------------


def test_only_first_refetch_per_file_counted():
    from cctx.diagnostician.patterns.compaction import classify

    tu_read = _tu("Read", "uid-r1", {"file_path": "/a.py"})
    tr_read = _tr("Read", "uid-r1", content="content", token_count=100)

    tu_reread1 = _tu("Read", "uid-r2", {"file_path": "/a.py"})
    tr_reread1 = _tr("Read", "uid-r2", content="content", token_count=100)

    tu_reread2 = _tu("Read", "uid-r3", {"file_path": "/a.py"})
    tr_reread2 = _tr("Read", "uid-r3", content="content", token_count=100)

    turns = [
        _turn(1, "assistant", tool_uses=[tu_read], tool_results=[tr_read]),
        _compaction_turn(2),
        _turn(3, "assistant", tool_uses=[tu_reread1], tool_results=[tr_reread1]),
        _turn(4, "assistant", tool_uses=[tu_reread2], tool_results=[tr_reread2]),
    ]
    findings = classify(_trace(turns))
    assert len(findings) == 1
    # Only 1 re-fetch, not 2 — second repetition isn't flagged again
    assert len(findings[0].evidence["re_fetches"]) == 1
    assert findings[0].evidence["total_refetch_tokens"] == 100


# ---------------------------------------------------------------------------
# Classifier: token_count heuristic when token_count == 0
# ---------------------------------------------------------------------------


def test_refetch_token_heuristic_when_zero():
    from cctx.diagnostician.patterns.compaction import classify

    # 12 words → 12 * 4 // 3 = 16 tokens via heuristic
    content = "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10 word11 word12"
    tu_read = _tu("Read", "uid-h1", {"file_path": "/heuristic.py"})
    tr_read = _tr("Read", "uid-h1", content=content, token_count=0)

    tu_reread = _tu("Read", "uid-h2", {"file_path": "/heuristic.py"})
    tr_reread = _tr("Read", "uid-h2", content=content, token_count=0)

    turns = [
        _turn(1, "assistant", tool_uses=[tu_read], tool_results=[tr_read]),
        _compaction_turn(2),
        _turn(3, "assistant", tool_uses=[tu_reread], tool_results=[tr_reread]),
    ]
    findings = classify(_trace(turns))
    assert len(findings) == 1
    # Heuristic: 12 words * 4 // 3 = 16
    expected_tokens = len(content.split()) * 4 // 3
    assert findings[0].evidence["total_refetch_tokens"] == expected_tokens


# ---------------------------------------------------------------------------
# dead_end compaction detection still works after refactor
# ---------------------------------------------------------------------------


def test_dead_end_compaction_resets_error_run():
    from cctx.diagnostician.patterns.dead_end import classify

    # Build a session where errors happen, then compaction resets, then success
    # Without compaction reset, this would register a dead-end.
    # With compaction reset, the error count is cleared.
    tu_err1 = _tu("Bash", "e1", {"command": "failing-cmd"})
    tr_err1 = _tr("Bash", "e1", content="Error: command not found", is_error=True)

    tu_err2 = _tu("Bash", "e2", {"command": "failing-cmd"})
    tr_err2 = _tr("Bash", "e2", content="Error: command not found", is_error=True)

    tu_ok = _tu("Bash", "ok1", {"command": "ls"})
    tr_ok = _tr("Bash", "ok1", content="file1.py\nfile2.py", is_error=False)

    turns = [
        _turn(1, "assistant", tool_uses=[tu_err1], tool_results=[tr_err1]),
        _turn(2, "assistant", tool_uses=[tu_err2], tool_results=[tr_err2]),
        _compaction_turn(3),  # resets error count
        _turn(4, "assistant", tool_uses=[tu_ok], tool_results=[tr_ok]),
    ]
    findings = classify(_trace(turns))
    # After compaction reset, the pivot at turn 4 is not counted as dead-end
    assert findings == []
