"""Tests for cache_hygiene classifier (issue #96)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cctx.models import SessionTrace, Turn, Usage

# ---------------------------------------------------------------------------
# Models smoke tests
# ---------------------------------------------------------------------------


def test_cache_hygiene_kind_exists():
    from cctx.models import FindingKind

    assert FindingKind.CACHE_HYGIENE == "cache_hygiene"


def test_cache_hygiene_has_kind_label():
    from cctx.models import KIND_LABEL, FindingKind

    assert KIND_LABEL[FindingKind.CACHE_HYGIENE] == "CACHE HYGIENE"


def test_cache_hygiene_has_managed_heading():
    from cctx.models import MANAGED_HEADINGS, FindingKind

    assert MANAGED_HEADINGS[FindingKind.CACHE_HYGIENE] == "## Cache hygiene"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_TS = datetime(2026, 6, 20, tzinfo=timezone.utc)


def _usage(input_tokens: int, cache_read: int) -> Usage:
    return Usage(
        input_tokens=input_tokens,
        output_tokens=100,
        cache_creation_5m=0,
        cache_creation_1h=0,
        cache_read=cache_read,
        service_tier=None,
    )


def _turn(
    n: int,
    role: str,
    usage: Usage | None = None,
    text: str = "",
) -> Turn:
    return Turn(
        turn_number=n,
        uuid=f"uuid-{n}",
        parent_uuid=None,
        role=role,
        text=text,
        thinking="",
        tool_uses=[],
        tool_results=[],
        usage=usage,
        model="claude-sonnet-4-6" if role == "assistant" else None,
        stop_reason="end_turn",
        timestamp=_TS,
        duration_ms=100,
    )


def _trace(
    turns: list[Turn],
    tool_names_loaded: list[str] | None = None,
) -> SessionTrace:
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
        tool_names_loaded=tool_names_loaded or [],
        start_time=_TS,
        end_time=_TS,
        source_path=Path("/test/session.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


# ---------------------------------------------------------------------------
# No-finding cases
# ---------------------------------------------------------------------------


def test_high_hit_rate_no_finding():
    """Session with >= 50% cache hit rate must not fire."""
    from cctx.diagnostician.patterns.cache_hygiene import classify

    # hit rate = 6000 / (3000 + 6000) = 66.7%
    turns = [
        _turn(1, "assistant", _usage(input_tokens=3000, cache_read=6000)),
    ]
    assert classify(_trace(turns)) == []


def test_tiny_session_no_finding():
    """Session with < MIN_TOTAL_TOKENS must be skipped."""
    from cctx.diagnostician.patterns.cache_hygiene import classify

    # total = 200 + 100 = 300, well below 5_000
    turns = [
        _turn(1, "assistant", _usage(input_tokens=200, cache_read=100)),
    ]
    assert classify(_trace(turns)) == []


def test_no_assistant_turns_no_finding():
    """Session with no assistant turns must not fire."""
    from cctx.diagnostician.patterns.cache_hygiene import classify

    turns = [
        _turn(1, "user", usage=None, text="hello"),
    ]
    assert classify(_trace(turns)) == []


# ---------------------------------------------------------------------------
# Firing cases — severity
# ---------------------------------------------------------------------------


def test_overall_rate_20_pct_fires_high():
    """Overall hit rate 20% → severity HIGH (below 25%)."""
    from cctx.diagnostician.patterns.cache_hygiene import classify
    from cctx.models import FindingKind, Severity

    # input=8000, cache_read=2000 → hit_rate = 2000/10000 = 20%
    turns = [
        _turn(1, "assistant", _usage(input_tokens=8000, cache_read=2000)),
    ]
    findings = classify(_trace(turns))
    assert len(findings) == 1
    f = findings[0]
    assert f.kind is FindingKind.CACHE_HYGIENE
    assert f.severity is Severity.HIGH
    assert f.evidence["overall_hit_rate"] == 0.2


def test_overall_rate_40_pct_fires_medium():
    """Overall hit rate 40% → severity MEDIUM (>= 25%, < 50%)."""
    from cctx.diagnostician.patterns.cache_hygiene import classify
    from cctx.models import FindingKind, Severity

    # input=6000, cache_read=4000 → hit_rate = 4000/10000 = 40%
    turns = [
        _turn(1, "assistant", _usage(input_tokens=6000, cache_read=4000)),
    ]
    findings = classify(_trace(turns))
    assert len(findings) == 1
    f = findings[0]
    assert f.kind is FindingKind.CACHE_HYGIENE
    assert f.severity is Severity.MEDIUM
    assert f.evidence["overall_hit_rate"] == 0.4


# ---------------------------------------------------------------------------
# Degradation detection
# ---------------------------------------------------------------------------


def test_degrading_hit_rate_reported_in_evidence():
    """Session with high early rate and low late rate must report degradation."""
    from cctx.diagnostician.patterns.cache_hygiene import classify

    # Turn 1 (early half): input=1000, cache_read=8000 → 88.9%
    # Turn 2 (late half):  input=9000, cache_read=1000 → 10%
    # overall = 9000 / (10000 + 9000) → ~47.4% → fires; early - late > 0.20
    turns = [
        _turn(1, "assistant", _usage(input_tokens=1000, cache_read=8000)),
        _turn(2, "assistant", _usage(input_tokens=9000, cache_read=1000)),
    ]
    findings = classify(_trace(turns))
    assert len(findings) == 1
    ev = findings[0].evidence
    assert ev["early_hit_rate"] > 0.5
    assert ev["late_hit_rate"] < 0.3
    # Summary must mention degradation
    assert "degraded" in findings[0].summary


# ---------------------------------------------------------------------------
# Cause attribution
# ---------------------------------------------------------------------------


def test_compaction_cause_attributed():
    """Session with a compaction system turn must blame compaction."""
    from cctx.diagnostician.patterns.cache_hygiene import classify

    # Low hit rate overall so finding fires, compaction turn present
    assistant = _turn(1, "assistant", _usage(input_tokens=9000, cache_read=1000))
    system_compact = _turn(2, "system", text="Context was compacted at this point.")
    turns = [assistant, system_compact]
    findings = classify(_trace(turns))
    assert len(findings) == 1
    cause = findings[0].evidence["cause"]
    assert cause is not None
    assert "compact" in cause.lower()


def test_large_tool_surface_cause_attributed():
    """>20 tools loaded must be attributed as the cause."""
    from cctx.diagnostician.patterns.cache_hygiene import classify

    # Low hit rate + many tools loaded
    turns = [
        _turn(1, "assistant", _usage(input_tokens=9000, cache_read=1000)),
    ]
    tool_names = [f"tool_{i}" for i in range(25)]
    findings = classify(_trace(turns, tool_names_loaded=tool_names))
    assert len(findings) == 1
    cause = findings[0].evidence["cause"]
    assert cause is not None
    assert "tool" in cause.lower()


def test_no_first_turn_cache_cause():
    """Turn 1 with zero cache_read and > 1000 input tokens → prompt prefix cause."""
    from cctx.diagnostician.patterns.cache_hygiene import classify

    # turn 1: cache_read=0, input=5000 → no warm prefix
    # Turn 2: cache_read=1000, input=4000 → adds some cache, but overall still low
    turns = [
        _turn(1, "assistant", _usage(input_tokens=5000, cache_read=0)),
        _turn(2, "assistant", _usage(input_tokens=4000, cache_read=1000)),
    ]
    findings = classify(_trace(turns))
    assert len(findings) == 1
    cause = findings[0].evidence["cause"]
    assert cause is not None
    assert "turn 1" in cause or "prefix" in cause


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_exactly_at_threshold_no_finding():
    """Exactly 50% hit rate must NOT fire (boundary: >= threshold → skip)."""
    from cctx.diagnostician.patterns.cache_hygiene import classify

    # input=5000, cache_read=5000 → 5000/10000 = 50%
    turns = [
        _turn(1, "assistant", _usage(input_tokens=5000, cache_read=5000)),
    ]
    assert classify(_trace(turns)) == []


def test_evidence_fields_present():
    """Finding evidence must contain all required keys."""
    from cctx.diagnostician.patterns.cache_hygiene import classify

    turns = [
        _turn(1, "assistant", _usage(input_tokens=9000, cache_read=1000)),
    ]
    findings = classify(_trace(turns))
    assert len(findings) == 1
    ev = findings[0].evidence
    for key in ("overall_hit_rate", "early_hit_rate", "late_hit_rate", "total_tokens", "cause"):
        assert key in ev, f"Missing evidence key: {key}"
