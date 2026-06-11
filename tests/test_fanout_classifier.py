"""Tests for fan_out classifier (M16 #89) and related models."""
from __future__ import annotations


def test_fanout_waste_kind_exists():
    from cctx.models import FindingKind
    assert FindingKind.FANOUT_WASTE == "fanout_waste"


def test_fanout_waste_has_kind_label():
    from cctx.models import KIND_LABEL, FindingKind
    assert KIND_LABEL[FindingKind.FANOUT_WASTE] == "FANOUT WASTE"


def test_fanout_waste_has_managed_heading():
    from cctx.models import MANAGED_HEADINGS, FindingKind
    assert MANAGED_HEADINGS[FindingKind.FANOUT_WASTE] == "## Fan-out discipline"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

from datetime import datetime, timezone
from pathlib import Path

from cctx.models import (
    Attachment, RawToolResultFile, SessionTrace, ToolResult, ToolUse, Turn, Usage,
)

_TS = datetime(2026, 6, 10, tzinfo=timezone.utc)
_USAGE = Usage(100, 50, 0, 0, 0, None)


def _tu(tool_name: str, uid: str, tool_input: dict, subagent_session_id: str | None = None) -> ToolUse:
    return ToolUse(
        tool_name=tool_name,
        tool_use_id=uid,
        tool_input=tool_input,
        subagent_session_id=subagent_session_id,
    )


def _tr(tool_name: str, uid: str, content: str = "ok", is_error: bool = False) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        tool_use_id=uid,
        content=content,
        structured=None,
        is_error=is_error,
    )


def _turn(n: int, role: str, tool_uses: list | None = None, tool_results: list | None = None, text: str = "") -> Turn:
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


# These two prompts share ~85% of 3-gram content (Jaccard >> 0.65, both > 50 words).
_LONG_OVERLAP_A = (
    "Please analyze the entire authentication module in this Python codebase carefully. "
    "Look for security vulnerabilities including SQL injection XSS CSRF tokens "
    "session management password hashing and input validation. Report all findings "
    "with exact file names and line numbers. Focus on the auth directory module. "
    "Check all authentication flows and mechanisms thoroughly."
)

_LONG_OVERLAP_B = (
    "Please analyze the entire authentication module in this Python codebase carefully. "
    "Look for security vulnerabilities including SQL injection XSS CSRF tokens "
    "session management password hashing and input validation. Report all findings "
    "with exact file names and line numbers. Focus on the login forms interface. "
    "Check all authentication flows and mechanisms thoroughly."
)

# These two prompts have near-zero 3-gram overlap (Jaccard < 0.10, both > 50 words).
_LONG_DISTINCT_A = (
    "Please explore the database layer of this codebase. Examine ORM models "
    "migration files query patterns connection pooling transaction handling "
    "schema relationships indexes and any N plus 1 query problems you can find."
)

_LONG_DISTINCT_B = (
    "Please implement a new REST API endpoint for user registration. The endpoint "
    "should validate email format hash passwords using bcrypt store results in the "
    "users table send a confirmation email and return a JWT token on success."
)

# Short prompts (< 50 words) for the overlap threshold guard tests.
_SHORT_SIMILAR_A = "Analyze the authentication module for security issues."
_SHORT_SIMILAR_B = "Analyze the authentication module for security vulnerabilities."

# Retry test prompts — both ≥ 30 words, Jaccard ≥ 0.50.
_RETRY_ORIGINAL = (
    "Read the failing test file tests/test_auth.py and diagnose why exactly "
    "the test_login_redirect test is failing. Check the session management code "
    "in auth/session.py carefully and report what needs to be fixed here."
)
_RETRY_SIMILAR = (
    "Read the failing test file tests/test_auth.py and understand why exactly "
    "the test_login_redirect test is failing. Review the session management code "
    "in auth/session.py carefully and report what needs to be fixed here."
)
_RETRY_DIFFERENT = (
    "Implement the new user dashboard feature as described in the specification "
    "document. Create the frontend components backend API and database schema "
    "following the existing patterns in the entire codebase."
)


# ---------------------------------------------------------------------------
# Signal A — Overlapping prompts
# ---------------------------------------------------------------------------

def test_no_agents_no_findings():
    from cctx.diagnostician.patterns.fan_out import classify
    trace = _trace([_turn(1, "user", text="hello"), _turn(2, "assistant", text="hi")])
    assert classify(trace) == []


def test_single_agent_no_findings():
    from cctx.diagnostician.patterns.fan_out import classify
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": _LONG_OVERLAP_A}, "child-1")]),
    ])
    assert classify(trace) == []


def test_overlapping_prompts_fires():
    from cctx.diagnostician.patterns.fan_out import classify
    from cctx.models import FindingKind
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": _LONG_OVERLAP_A}, "child-1")]),
        _turn(2, "assistant", tool_uses=[_tu("Agent", "tu2", {"prompt": _LONG_OVERLAP_B}, "child-2")]),
    ])
    findings = classify(trace)
    assert len(findings) == 1
    assert findings[0].kind is FindingKind.FANOUT_WASTE
    assert findings[0].evidence["signal"] == "overlap"
    assert findings[0].evidence["jaccard"] >= 0.65
    assert "child-1" in findings[0].evidence["overlap_pair"]
    assert "child-2" in findings[0].evidence["overlap_pair"]


def test_non_overlapping_prompts_clean():
    from cctx.diagnostician.patterns.fan_out import classify
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": _LONG_DISTINCT_A}, "child-1")]),
        _turn(2, "assistant", tool_uses=[_tu("Agent", "tu2", {"prompt": _LONG_DISTINCT_B}, "child-2")]),
    ])
    assert classify(trace) == []


def test_short_prompts_below_overlap_threshold_clean():
    """Prompts under 50 words must not be compared even if textually similar."""
    from cctx.diagnostician.patterns.fan_out import classify
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": _SHORT_SIMILAR_A}, "child-1")]),
        _turn(2, "assistant", tool_uses=[_tu("Agent", "tu2", {"prompt": _SHORT_SIMILAR_B}, "child-2")]),
    ])
    assert classify(trace) == []


# ---------------------------------------------------------------------------
# Signal B — Failed-retry
# ---------------------------------------------------------------------------

def test_failed_retry_fires():
    from cctx.diagnostician.patterns.fan_out import classify
    from cctx.models import FindingKind
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": _RETRY_ORIGINAL}, "child-1")]),
        _turn(2, "user", tool_results=[_tr("Agent", "tu1", "Error: timeout", is_error=True)]),
        _turn(3, "assistant", tool_uses=[_tu("Agent", "tu2", {"prompt": _RETRY_SIMILAR}, "child-2")]),
    ])
    findings = classify(trace)
    assert len(findings) == 1
    assert findings[0].kind is FindingKind.FANOUT_WASTE
    assert findings[0].evidence["signal"] == "retry"
    assert findings[0].evidence["jaccard"] >= 0.50
    assert findings[0].evidence.get("failed_session_id") == "child-1"


def test_failed_no_retry_clean():
    """is_error=True followed by a DIFFERENT Agent prompt: no finding."""
    from cctx.diagnostician.patterns.fan_out import classify
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": _RETRY_ORIGINAL}, "child-1")]),
        _turn(2, "user", tool_results=[_tr("Agent", "tu1", "Error", is_error=True)]),
        _turn(3, "assistant", tool_uses=[_tu("Agent", "tu2", {"prompt": _RETRY_DIFFERENT}, "child-2")]),
    ])
    assert classify(trace) == []


def test_failed_retry_short_prompts_clean():
    """Retry prompts under 30 words must not trigger even if similar."""
    from cctx.diagnostician.patterns.fan_out import classify
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": "Fix the bug."}, "child-1")]),
        _turn(2, "user", tool_results=[_tr("Agent", "tu1", "Error", is_error=True)]),
        _turn(3, "assistant", tool_uses=[_tu("Agent", "tu2", {"prompt": "Fix the bug please."}, "child-2")]),
    ])
    assert classify(trace) == []


# ---------------------------------------------------------------------------
# _patch_fanout_costs — unit tests
# ---------------------------------------------------------------------------

def test_patch_fanout_costs_overlap_picks_cheaper():
    """overlap finding: cost_usd = cheaper subagent's cost; subagent_session_ids updated."""
    import dataclasses
    from cctx.diagnostician import _patch_fanout_costs
    from cctx.models import (
        Confidence, Finding, FindingKind, Severity, SubagentAttribution,
    )
    finding = Finding(
        kind=FindingKind.FANOUT_WASTE,
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=1, last_turn=2,
        evidence={
            "signal": "overlap",
            "overlap_pair": ["child-1", "child-2"],
            "jaccard": 0.72,
            "prompt_a": "x", "prompt_b": "y",
            "subagent_session_ids": [],
        },
        cost_usd=None,
        summary="test",
    )
    attrs = [
        SubagentAttribution("child-1", "label1", 0.05, 1, "claude-sonnet-4-6"),
        SubagentAttribution("child-2", "label2", 0.02, 1, "claude-sonnet-4-6"),
    ]
    patched = _patch_fanout_costs([finding], attrs)
    assert len(patched) == 1
    assert patched[0].cost_usd == 0.02           # cheaper one
    assert patched[0].evidence["subagent_session_ids"] == ["child-2"]


def test_patch_fanout_costs_retry_sets_failed_cost():
    """retry finding: cost_usd = the failed subagent's cost."""
    from cctx.diagnostician import _patch_fanout_costs
    from cctx.models import (
        Confidence, Finding, FindingKind, Severity, SubagentAttribution,
    )
    finding = Finding(
        kind=FindingKind.FANOUT_WASTE,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=1, last_turn=3,
        evidence={
            "signal": "retry",
            "failed_session_id": "child-1",
            "jaccard": 0.55,
            "failed_prompt": "x", "retry_prompt": "y",
            "subagent_session_ids": [],
        },
        cost_usd=None,
        summary="test",
    )
    attrs = [
        SubagentAttribution("child-1", "label1", 0.08, 1, "claude-sonnet-4-6"),
    ]
    patched = _patch_fanout_costs([finding], attrs)
    assert patched[0].cost_usd == 0.08
    assert patched[0].evidence["subagent_session_ids"] == ["child-1"]
