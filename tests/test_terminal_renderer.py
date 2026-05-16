"""Tests for cctx/renderers/terminal.py.

Tests capture Console output as text; they don't check for exact ANSI codes,
only that key information is present in the output.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO


def _make_finding(kind_str: str, cost: float | None = None):
    from cctx.models import Confidence, Finding, FindingKind, Severity

    kind_map = {
        "retry_loop": FindingKind.RETRY_LOOP,
        "scope_creep": FindingKind.SCOPE_CREEP,
        "stale_context": FindingKind.STALE_CONTEXT,
    }
    return Finding(
        kind=kind_map[kind_str],
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=5,
        last_turn=10,
        evidence={},
        cost_usd=cost,
        summary=f"test {kind_str} finding",
    )


def _make_patch(kind_str: str):
    from cctx.models import FindingKind, Patch

    kind_map = {
        "retry_loop": FindingKind.RETRY_LOOP,
        "scope_creep": FindingKind.SCOPE_CREEP,
        "stale_context": FindingKind.STALE_CONTEXT,
    }
    return Patch(
        target_file="CLAUDE.md",
        description="Add discipline rule",
        unified_diff="+## Retry discipline\n+Stop after two failures.",
        finding_kind=kind_map[kind_str],
        evidence_summary="test evidence",
    )


def _make_diagnosis(findings=None, patches=None):
    from cctx.models import Diagnosis

    return Diagnosis(
        session_id="abc123",
        findings=findings or [],
        inflection_turn=5 if findings else None,
        patches=patches or [],
        total_cost_usd=2.14,
        waste_cost_usd=sum(f.cost_usd or 0 for f in (findings or [])),
        analysed_at=datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc),
    )


def _render_to_string(diagnosis):
    from rich.console import Console

    from cctx.renderers.terminal import render_diagnosis

    buf = StringIO()
    console = Console(file=buf, width=120, highlight=False, markup=False)
    render_diagnosis(diagnosis, console=console)
    return buf.getvalue()


def test_clean_session_shows_no_findings():
    output = _render_to_string(_make_diagnosis())
    assert "No findings" in output or "clean" in output.lower()


def test_session_id_shown():
    output = _render_to_string(_make_diagnosis([_make_finding("retry_loop")]))
    assert "abc123" in output


def test_retry_loop_finding_shown():
    output = _render_to_string(_make_diagnosis([_make_finding("retry_loop")]))
    assert "retry" in output.lower() or "loop" in output.lower()


def test_inflection_turn_shown():
    output = _render_to_string(_make_diagnosis([_make_finding("retry_loop")]))
    assert "5" in output  # inflection_turn=5


def test_cost_shown():
    diag = _make_diagnosis([_make_finding("stale_context", cost=0.88)])
    output = _render_to_string(diag)
    assert "~$2.14" in output or "2.14" in output


def test_cost_approximation_note_shown():
    output = _render_to_string(_make_diagnosis())
    assert "85" in output or "95" in output or "~" in output


def test_patch_diff_shown():
    diag = _make_diagnosis(
        findings=[_make_finding("retry_loop")],
        patches=[_make_patch("retry_loop")],
    )
    output = _render_to_string(diag)
    assert "Retry discipline" in output or "CLAUDE.md" in output
