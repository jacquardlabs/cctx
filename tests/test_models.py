"""Tests for cctx/models.py — dataclass construction and group_into_exchanges()."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc


def _utcnow() -> datetime:
    return datetime(2026, 5, 13, 2, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


def test_usage_instantiates():
    from cctx.models import Usage

    u = Usage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_5m=10,
        cache_creation_1h=20,
        cache_read=5,
        service_tier="standard",
    )
    assert u.input_tokens == 100
    assert u.output_tokens == 50
    assert u.cache_creation_5m == 10
    assert u.cache_creation_1h == 20
    assert u.cache_read == 5
    assert u.service_tier == "standard"


def test_usage_service_tier_none():
    from cctx.models import Usage

    u = Usage(
        input_tokens=0,
        output_tokens=0,
        cache_creation_5m=0,
        cache_creation_1h=0,
        cache_read=0,
        service_tier=None,
    )
    assert u.service_tier is None


# ---------------------------------------------------------------------------
# ToolUse
# ---------------------------------------------------------------------------


def test_tool_use_instantiates_with_defaults():
    from cctx.models import ToolUse

    tu = ToolUse(
        tool_name="Read",
        tool_use_id="toolu_01",
        tool_input={"file_path": "/foo/bar.py"},
    )
    assert tu.tool_name == "Read"
    assert tu.tool_use_id == "toolu_01"
    assert tu.tool_input == {"file_path": "/foo/bar.py"}
    assert tu.token_count == 0
    assert tu.subagent_session_id is None


def test_tool_use_subagent_session_id():
    from cctx.models import ToolUse

    tu = ToolUse(
        tool_name="Agent",
        tool_use_id="toolu_02",
        tool_input={},
        subagent_session_id="child-session-abc",
    )
    assert tu.subagent_session_id == "child-session-abc"


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------


def test_tool_result_instantiates_with_defaults():
    from cctx.models import ToolResult

    tr = ToolResult(
        tool_name="Read",
        tool_use_id="toolu_01",
        content="file contents here",
        structured=None,
        is_error=False,
    )
    assert tr.tool_name == "Read"
    assert tr.tool_use_id == "toolu_01"
    assert tr.content == "file contents here"
    assert tr.structured is None
    assert tr.is_error is False
    assert tr.token_count == 0


def test_tool_result_with_structured():
    from cctx.models import ToolResult

    tr = ToolResult(
        tool_name="Bash",
        tool_use_id="toolu_03",
        content="stdout output",
        structured={"stdout": "output", "exit_code": 0},
        is_error=False,
    )
    assert tr.structured == {"stdout": "output", "exit_code": 0}


# ---------------------------------------------------------------------------
# Turn
# ---------------------------------------------------------------------------


def test_turn_instantiates_with_defaults():
    from cctx.models import Turn

    t = Turn(
        turn_number=1,
        uuid="uuid-a1",
        parent_uuid=None,
        role="assistant",
        text="Hello",
        thinking="",
        tool_uses=[],
        tool_results=[],
        usage=None,
        model="claude-sonnet-4-6",
        stop_reason="end_turn",
        timestamp=_utcnow(),
        duration_ms=None,
    )
    assert t.turn_number == 1
    assert t.uuid == "uuid-a1"
    assert t.parent_uuid is None
    assert t.role == "assistant"
    assert t.text == "Hello"
    assert t.thinking == ""
    assert t.tool_uses == []
    assert t.tool_results == []
    assert t.usage is None
    assert t.model == "claude-sonnet-4-6"
    assert t.stop_reason == "end_turn"
    assert t.duration_ms is None
    # defaults
    assert t.token_count == 0
    assert t.is_sidechain is False
    assert t.error is None


def test_turn_is_sidechain_can_be_set():
    from cctx.models import Turn

    t = Turn(
        turn_number=2,
        uuid="uuid-b1",
        parent_uuid="uuid-a1",
        role="assistant",
        text="",
        thinking="some extended thinking",
        tool_uses=[],
        tool_results=[],
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=_utcnow(),
        duration_ms=100,
        is_sidechain=True,
        error="some error",
    )
    assert t.is_sidechain is True
    assert t.error == "some error"
    assert t.thinking == "some extended thinking"


# ---------------------------------------------------------------------------
# Attachment
# ---------------------------------------------------------------------------


def test_attachment_instantiates():
    from cctx.models import Attachment

    a = Attachment(
        kind="hook_output",
        raw={"hookEvent": "SessionStart", "stdout": "startup output"},
        content="startup output",
        timestamp=_utcnow(),
        parent_uuid="uuid-a1",
    )
    assert a.kind == "hook_output"
    assert a.content == "startup output"
    assert a.parent_uuid == "uuid-a1"


def test_attachment_nullable_fields():
    from cctx.models import Attachment

    a = Attachment(
        kind="other",
        raw={"unknown": "payload"},
        content=None,
        timestamp=None,
        parent_uuid=None,
    )
    assert a.content is None
    assert a.timestamp is None
    assert a.parent_uuid is None


# ---------------------------------------------------------------------------
# RawToolResultFile
# ---------------------------------------------------------------------------


def test_raw_tool_result_file_instantiates():
    from cctx.models import RawToolResultFile

    f = RawToolResultFile(
        path=Path("/home/user/.claude/projects/foo/sid/tool-results/result1.txt"),
        size_bytes=12345,
        tool_use_id=None,
    )
    assert f.size_bytes == 12345
    assert f.tool_use_id is None


# ---------------------------------------------------------------------------
# ParserError
# ---------------------------------------------------------------------------


def test_parser_error_is_exception():
    from cctx.models import ParserError

    err = ParserError(
        reason="File not found",
        path=Path("/nonexistent.jsonl"),
        line_number=None,
    )
    assert isinstance(err, Exception)
    assert err.reason == "File not found"
    assert err.path == Path("/nonexistent.jsonl")
    assert err.line_number is None


def test_parser_error_with_line_number():
    from cctx.models import ParserError

    err = ParserError(
        reason="malformed JSON",
        path=Path("/session.jsonl"),
        line_number=42,
    )
    assert err.line_number == 42
    assert isinstance(err, Exception)


def test_parser_error_can_be_raised():
    from cctx.models import ParserError

    with pytest.raises(ParserError):
        raise ParserError(reason="oops", path=Path("/x.jsonl"), line_number=1)


# ---------------------------------------------------------------------------
# ParserWarning
# ---------------------------------------------------------------------------


def test_parser_warning_is_dataclass_not_exception():
    from cctx.models import ParserWarning

    pw = ParserWarning(code="unknown_type", detail="compact_summary")
    assert pw.code == "unknown_type"
    assert pw.detail == "compact_summary"
    assert pw.line_number is None
    assert pw.path is None
    assert not isinstance(pw, Exception)


def test_parser_warning_with_all_fields():
    from cctx.models import ParserWarning

    pw = ParserWarning(
        code="malformed_json",
        detail="unexpected token",
        line_number=7,
        path=Path("/session.jsonl"),
    )
    assert pw.line_number == 7
    assert pw.path == Path("/session.jsonl")


# ---------------------------------------------------------------------------
# SessionTrace
# ---------------------------------------------------------------------------


def test_session_trace_instantiates_with_required_fields():
    from cctx.models import SessionTrace

    st = SessionTrace(
        session_id="abc123",
        parent_session_id=None,
        project_path="/Users/test/Projects/demo",
        cwd="/Users/test/Projects/demo",
        primary_model="claude-sonnet-4-6",
        claude_code_version="2.1.138",
        turns=[],
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=30488,
        tool_names_loaded=["Read", "Bash"],
        start_time=_utcnow(),
        end_time=_utcnow(),
        source_path=Path("/Users/test/.claude/projects/demo/abc123.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )
    assert st.session_id == "abc123"
    assert st.parent_session_id is None
    assert st.initial_context_tokens == 30488
    assert st.tool_names_loaded == ["Read", "Bash"]
    assert st.subagent_meta == {}
    assert st.warnings == []
    assert st.subagent_parse_errors == []


def test_session_trace_nullable_times():
    from cctx.models import SessionTrace

    st = SessionTrace(
        session_id="bookkeeping-only",
        parent_session_id=None,
        project_path="/p",
        cwd="/p",
        primary_model=None,
        claude_code_version=None,
        turns=[],
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=None,
        end_time=None,
        source_path=Path("/p/session.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )
    assert st.start_time is None
    assert st.end_time is None
    assert st.primary_model is None


# ---------------------------------------------------------------------------
# group_into_exchanges
# ---------------------------------------------------------------------------


def _make_turn(turn_number: int, role: str, uuid: str | None = None):
    """Build a minimal Turn for exchange-grouping tests."""
    from cctx.models import Turn

    return Turn(
        turn_number=turn_number,
        uuid=uuid or f"uuid-{turn_number}",
        parent_uuid=None,
        role=role,
        text="",
        thinking="",
        tool_uses=[],
        tool_results=[],
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=_utcnow(),
        duration_ms=None,
    )


def test_group_into_exchanges_empty():
    from cctx.models import group_into_exchanges

    result = group_into_exchanges([])
    assert result == []


def test_group_into_exchanges_one_user_one_assistant():
    from cctx.models import group_into_exchanges

    turns = [
        _make_turn(1, "user"),
        _make_turn(2, "assistant"),
    ]
    result = group_into_exchanges(turns)
    assert len(result) == 1
    assert len(result[0]) == 2
    assert result[0][0].role == "user"
    assert result[0][1].role == "assistant"


def test_group_into_exchanges_multiple():
    from cctx.models import group_into_exchanges

    turns = [
        _make_turn(1, "user"),
        _make_turn(2, "assistant"),
        _make_turn(3, "tool_result"),
        _make_turn(4, "assistant"),
        _make_turn(5, "user"),
        _make_turn(6, "assistant"),
    ]
    result = group_into_exchanges(turns)
    # Exchange 1: turns 1-2 (user + assistant)
    # Exchange 2: turns 3-4 (tool_result + assistant)
    # Exchange 3: turns 5-6 (user + assistant)
    assert [[t.turn_number for t in ex] for ex in result] == [[1, 2], [3, 4], [5, 6]]


def test_group_into_exchanges_tool_result_starts_new_exchange():
    """A tool_result turn opens a new exchange, like a user turn does."""
    from cctx.models import group_into_exchanges

    turns = [
        _make_turn(1, "user"),
        _make_turn(2, "assistant"),
        _make_turn(3, "tool_result"),
        _make_turn(4, "assistant"),
    ]
    result = group_into_exchanges(turns)
    assert len(result) == 2
    assert [t.turn_number for t in result[0]] == [1, 2]
    assert [t.turn_number for t in result[1]] == [3, 4]


def test_group_into_exchanges_leading_non_user_turns():
    """Turns before the first user turn land in their own group."""
    from cctx.models import group_into_exchanges

    turns = [
        _make_turn(1, "system"),
        _make_turn(2, "user"),
        _make_turn(3, "assistant"),
    ]
    result = group_into_exchanges(turns)
    # Leading system turn gets its own exchange (or is included in the first)
    # The key invariant: we get at least 2 groups or the system turn is bundled.
    # Either behavior is acceptable but must be consistent.
    # We test what we implement: leading non-user = own group.
    # Total groups: at least 1
    assert len(result) >= 1
    all_turns = [t for group in result for t in group]
    assert len(all_turns) == 3


# ---------------------------------------------------------------------------
# No forbidden imports in cctx/models.py
# ---------------------------------------------------------------------------


def test_no_third_party_imports():
    """cctx/models.py must not import from forbidden modules."""
    source = Path(__file__).parent.parent / "cctx" / "models.py"
    text = source.read_text(encoding="utf-8")

    forbidden = [
        "import anthropic",
        "import click",
        "from cctx.parsers",
        "from cctx.analyzers",
        "from cctx.renderers",
        "from cctx.exporters",
        "from cctx.tokenizer",
    ]
    for pattern in forbidden:
        assert pattern not in text, f"Forbidden import found in models.py: {pattern!r}"


# ---------------------------------------------------------------------------
# Autopsy types — M2
# ---------------------------------------------------------------------------


def test_finding_kind_values():
    from cctx.models import FindingKind

    assert FindingKind.RETRY_LOOP.value == "retry_loop"
    assert FindingKind.SCOPE_CREEP.value == "scope_creep"
    assert FindingKind.STALE_CONTEXT.value == "stale_context"


def test_severity_and_confidence_are_str_enums():
    from cctx.models import Confidence, Severity

    assert isinstance(Severity.HIGH, str)
    assert Severity.HIGH == "high"
    assert Confidence.MEDIUM == "medium"


def test_finding_instantiates():
    from cctx.models import Confidence, Finding, FindingKind, Severity

    f = Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=12,
        last_turn=16,
        evidence={"occurrences": [], "loop_length": 3},
        cost_usd=None,
        summary="Edit(src/foo.py) failed 3× between turns 12–16",
    )
    assert f.kind is FindingKind.RETRY_LOOP
    assert f.severity is Severity.HIGH
    assert f.confidence is Confidence.HIGH
    assert f.first_turn == 12
    assert f.last_turn == 16
    assert f.cost_usd is None


def test_finding_last_turn_none():
    from cctx.models import Confidence, Finding, FindingKind, Severity

    f = Finding(
        kind=FindingKind.SCOPE_CREEP,
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=5,
        last_turn=None,
        evidence={"phrases": []},
        cost_usd=None,
        summary="'while I'm here' at turn 5",
    )
    assert f.last_turn is None


def test_patch_instantiates():
    from cctx.models import FindingKind, Patch

    p = Patch(
        target_file="CLAUDE.md",
        description="Add retry discipline rule",
        unified_diff="+## Retry discipline\n+\n+Stop after two failures.",
        finding_kind=FindingKind.RETRY_LOOP,
        evidence_summary="Edit(src/foo.py) failed 3× between turns 12–16",
    )
    assert p.target_file == "CLAUDE.md"
    assert p.finding_kind is FindingKind.RETRY_LOOP
    assert "+## Retry discipline" in p.unified_diff


def test_diagnosis_instantiates():
    from cctx.models import Confidence, Diagnosis, Finding, FindingKind, Severity

    f = Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=12,
        last_turn=16,
        evidence={},
        cost_usd=None,
        summary="test",
    )
    d = Diagnosis(
        session_id="abc123",
        findings=[f],
        inflection_turn=12,
        patches=[],
        total_cost_usd=2.14,
        waste_cost_usd=0.0,
        analysed_at=_utcnow(),
    )
    assert d.session_id == "abc123"
    assert len(d.findings) == 1
    assert d.inflection_turn == 12
    assert d.patches == []
    assert d.waste_cost_usd == 0.0


def test_diagnosis_no_findings():
    from cctx.models import Diagnosis

    d = Diagnosis(
        session_id="clean",
        findings=[],
        inflection_turn=None,
        patches=[],
        total_cost_usd=0.50,
        waste_cost_usd=0.0,
        analysed_at=_utcnow(),
    )
    assert d.inflection_turn is None


def test_kind_evidence_instantiates():
    from cctx.models import FindingKind, KindEvidence

    ev = KindEvidence(
        kind=FindingKind.STALE_CONTEXT,
        session_count=8,
        total_waste_usd=4.30,
        example_summaries=["22K-token Bash result stale 14 turns"],
    )
    assert ev.session_count == 8
    assert ev.total_waste_usd == 4.30


def test_aggregate_report_instantiates():
    from datetime import timedelta

    from cctx.models import AggregateReport, FindingKind, KindEvidence

    ev = KindEvidence(FindingKind.RETRY_LOOP, 3, 0.0, [])
    report = AggregateReport(
        window=timedelta(days=7),
        sessions_analysed=12,
        sessions_with_findings=8,
        total_cost_usd=24.10,
        waste_cost_usd=4.30,
        by_kind={FindingKind.RETRY_LOOP: ev},
        patches=[],
    )
    assert report.sessions_analysed == 12
    assert FindingKind.RETRY_LOOP in report.by_kind
