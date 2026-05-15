"""Tests for cctx/diagnostician/inflection.py."""
from __future__ import annotations

from datetime import timezone

UTC = timezone.utc


def _make_finding(first_turn: int):
    from cctx.models import Confidence, Finding, FindingKind, Severity

    return Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=Severity.MEDIUM,
        confidence=Confidence.HIGH,
        first_turn=first_turn,
        last_turn=None,
        evidence={},
        cost_usd=None,
        summary="test",
    )


def test_detect_no_findings_returns_none():
    from cctx.diagnostician.inflection import detect

    assert detect([]) is None


def test_detect_single_finding_returns_its_turn():
    from cctx.diagnostician.inflection import detect

    assert detect([_make_finding(7)]) == 7


def test_detect_returns_minimum_first_turn():
    from cctx.diagnostician.inflection import detect

    findings = [_make_finding(12), _make_finding(5), _make_finding(9)]
    assert detect(findings) == 5


def test_detect_all_same_first_turn():
    from cctx.diagnostician.inflection import detect

    findings = [_make_finding(3), _make_finding(3)]
    assert detect(findings) == 3
