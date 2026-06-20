"""Tests for cctx/diagnostician/patterns/unused_context.py (issue #91 — M18)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cctx.models import Attachment, SessionTrace, ToolUse, Turn

_TS = datetime(2026, 6, 20, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mcp_attachment(added_names: list[str]) -> Attachment:
    return Attachment(
        kind="mcp_servers",
        raw={"addedNames": added_names, "pendingMcpServers": [], "removedNames": []},
        content=None,
        timestamp=_TS,
        parent_uuid=None,
    )


def _tool_use(tool_name: str, n: int = 1) -> ToolUse:
    return ToolUse(
        tool_name=tool_name,
        tool_use_id=f"tu_{n}_{tool_name}",
        tool_input={},
    )


def _turn(n: int, tool_names: list[str] | None = None) -> Turn:
    uses = [_tool_use(name, n) for name in (tool_names or [])]
    return Turn(
        turn_number=n,
        uuid=f"t{n}",
        parent_uuid=None,
        role="assistant",
        text="",
        thinking="",
        tool_uses=uses,
        tool_results=[],
        usage=None,
        model=None,
        stop_reason="end_turn",
        timestamp=_TS,
        duration_ms=None,
    )


def _trace(
    attachments: list[Attachment] | None = None,
    turns: list[Turn] | None = None,
) -> SessionTrace:
    return SessionTrace(
        session_id="test-session",
        parent_session_id=None,
        project_path="/test",
        cwd="/test",
        primary_model="claude-sonnet-4-6",
        claude_code_version="1.0",
        turns=turns or [],
        subagents=[],
        attachments=attachments or [],
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


def test_unused_context_kind_exists():
    from cctx.models import FindingKind
    assert FindingKind.UNUSED_CONTEXT == "unused_context"


def test_unused_context_kind_label():
    from cctx.models import KIND_LABEL, FindingKind
    assert KIND_LABEL[FindingKind.UNUSED_CONTEXT] == "UNUSED CONTEXT"


def test_unused_context_managed_heading():
    from cctx.models import MANAGED_HEADINGS, FindingKind
    assert MANAGED_HEADINGS[FindingKind.UNUSED_CONTEXT] == "## Context overhead"


# ---------------------------------------------------------------------------
# Classifier: no findings
# ---------------------------------------------------------------------------


def test_no_mcp_attachments_no_finding():
    """Session with no mcp_servers attachments → no findings."""
    from cctx.diagnostician.patterns.unused_context import classify
    trace = _trace(attachments=[], turns=[_turn(1, ["Read", "Edit"])])
    assert classify(trace) == []


def test_mcp_tool_called_no_finding():
    """MCP tool present in attachments AND called → no finding."""
    from cctx.diagnostician.patterns.unused_context import classify
    att = _mcp_attachment(["mcp__gmail__authenticate", "mcp__gmail__complete_authentication"])
    turns = [_turn(1, ["mcp__gmail__authenticate"])]
    assert classify(_trace([att], turns)) == []


def test_partial_server_use_no_finding():
    """One of two Gmail tools called → entire server is considered used, no finding."""
    from cctx.diagnostician.patterns.unused_context import classify
    att = _mcp_attachment([
        "mcp__gmail__authenticate",
        "mcp__gmail__complete_authentication",
    ])
    turns = [_turn(1, ["mcp__gmail__authenticate"])]
    assert classify(_trace([att], turns)) == []


def test_non_mcp_deferred_tools_ignored():
    """Standard deferred tools (TaskCreate, etc.) never trigger a finding."""
    from cctx.diagnostician.patterns.unused_context import classify
    att = _mcp_attachment(["TaskCreate", "TaskUpdate", "CronCreate"])
    assert classify(_trace([att], [])) == []


def test_empty_session_no_tools_no_finding():
    from cctx.diagnostician.patterns.unused_context import classify
    assert classify(_trace()) == []


# ---------------------------------------------------------------------------
# Classifier: fires
# ---------------------------------------------------------------------------


def test_single_server_never_called_fires():
    """Gmail tools present but never called → one finding for claude_ai_Gmail."""
    from cctx.diagnostician.patterns.unused_context import classify
    from cctx.models import Confidence, FindingKind, Severity

    att = _mcp_attachment([
        "mcp__claude_ai_Gmail__authenticate",
        "mcp__claude_ai_Gmail__complete_authentication",
    ])
    turns = [_turn(1, ["Read"]), _turn(2, ["Edit"])]
    findings = classify(_trace([att], turns))

    assert len(findings) == 1
    f = findings[0]
    assert f.kind is FindingKind.UNUSED_CONTEXT
    assert f.severity is Severity.LOW
    assert f.confidence is Confidence.MEDIUM
    assert f.cost_usd is None
    assert f.evidence["mcp_server"] == "claude_ai_Gmail"
    assert f.evidence["tools_called"] == []
    assert "mcp__claude_ai_Gmail__authenticate" in f.evidence["tools_available"]
    assert "mcp__claude_ai_Gmail__complete_authentication" in f.evidence["tools_available"]


def test_two_servers_both_unused_two_findings():
    """Two MCP servers, neither called → two findings, one per server."""
    from cctx.diagnostician.patterns.unused_context import classify

    att = _mcp_attachment([
        "mcp__gmail__authenticate",
        "mcp__calendar__list_events",
    ])
    findings = classify(_trace([att], [_turn(1, ["Read"])]))
    assert len(findings) == 2
    servers = {f.evidence["mcp_server"] for f in findings}
    assert servers == {"gmail", "calendar"}


def test_two_servers_one_used_one_unused():
    """Two servers, one used and one not → only the unused server fires."""
    from cctx.diagnostician.patterns.unused_context import classify

    att = _mcp_attachment([
        "mcp__gmail__authenticate",
        "mcp__calendar__list_events",
    ])
    turns = [_turn(1, ["mcp__gmail__authenticate"])]
    findings = classify(_trace([att], turns))

    assert len(findings) == 1
    assert findings[0].evidence["mcp_server"] == "calendar"


def test_finding_spans_full_session():
    """first_turn=1, last_turn=len(turns) for whole-session waste."""
    from cctx.diagnostician.patterns.unused_context import classify

    att = _mcp_attachment(["mcp__gmail__authenticate"])
    turns = [_turn(i, ["Read"]) for i in range(1, 6)]
    findings = classify(_trace([att], turns))

    assert findings[0].first_turn == 1
    assert findings[0].last_turn == 5


def test_summary_mentions_server_name():
    from cctx.diagnostician.patterns.unused_context import classify

    att = _mcp_attachment(["mcp__gmail__authenticate"])
    findings = classify(_trace([att], [_turn(1, ["Read"])]))
    assert "gmail" in findings[0].summary


def test_summary_tool_count_singular():
    """Single tool → 'tool' (not 'tools') in summary."""
    from cctx.diagnostician.patterns.unused_context import classify

    att = _mcp_attachment(["mcp__gmail__authenticate"])
    findings = classify(_trace([att], []))
    assert "1 tool available" in findings[0].summary


def test_summary_tool_count_plural():
    """Multiple tools → 'tools' in summary."""
    from cctx.diagnostician.patterns.unused_context import classify

    att = _mcp_attachment([
        "mcp__gmail__authenticate",
        "mcp__gmail__complete_authentication",
    ])
    findings = classify(_trace([att], []))
    assert "2 tools available" in findings[0].summary


def test_multiple_attachments_union():
    """Two mcp_servers attachments (e.g. after compaction) — union of names, deduplicated."""
    from cctx.diagnostician.patterns.unused_context import classify

    att1 = _mcp_attachment(["mcp__gmail__authenticate"])
    att2 = _mcp_attachment(["mcp__gmail__authenticate", "mcp__calendar__list_events"])
    findings = classify(_trace([att1, att2], []))
    # gmail + calendar both unused → 2 findings; no duplicate gmail finding
    assert len(findings) == 2


def test_no_mcp_names_in_attachment_no_finding():
    """mcp_servers attachment with empty addedNames → no finding."""
    from cctx.diagnostician.patterns.unused_context import classify

    att = _mcp_attachment([])
    assert classify(_trace([att], [])) == []
