"""Tests for cctx/recommender/evidence.py."""
from __future__ import annotations

from datetime import datetime, timezone


def _make_diagnosis(finding_kinds: list[str], waste: float = 0.0):
    from cctx.models import (
        Confidence,
        Diagnosis,
        Finding,
        FindingKind,
        Severity,
    )

    kind_map = {
        "retry_loop": FindingKind.RETRY_LOOP,
        "scope_creep": FindingKind.SCOPE_CREEP,
        "stale_context": FindingKind.STALE_CONTEXT,
    }
    findings = [
        Finding(
            kind=kind_map[k],
            severity=Severity.MEDIUM,
            confidence=Confidence.MEDIUM,
            first_turn=1,
            last_turn=None,
            evidence={},
            cost_usd=waste if k == "stale_context" else None,
            summary=f"test {k}",
        )
        for k in finding_kinds
    ]
    return Diagnosis(
        session_id=f"session-{id(findings)}",
        findings=findings,
        inflection_turn=1 if findings else None,
        patches=[],
        total_cost_usd=2.0,
        waste_cost_usd=waste,
        analysed_at=datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc),
    )


def test_accumulate_empty():
    from cctx.recommender.evidence import accumulate

    assert accumulate([]) == {}


def test_accumulate_single_session_retry_loop():
    from cctx.models import FindingKind
    from cctx.recommender.evidence import accumulate

    result = accumulate([_make_diagnosis(["retry_loop"])])
    assert FindingKind.RETRY_LOOP in result
    assert result[FindingKind.RETRY_LOOP].session_count == 1


def test_accumulate_counts_sessions_not_findings():
    """Two diagnoses each with retry_loop → session_count=2 (once per session, not per finding)."""
    from cctx.models import FindingKind
    from cctx.recommender.evidence import accumulate

    diagnoses = [
        _make_diagnosis(["retry_loop"]),
        _make_diagnosis(["retry_loop"]),
    ]
    result = accumulate(diagnoses)
    assert result[FindingKind.RETRY_LOOP].session_count == 2


def test_accumulate_sums_waste_usd():
    from cctx.models import FindingKind
    from cctx.recommender.evidence import accumulate

    diagnoses = [
        _make_diagnosis(["stale_context"], waste=1.50),
        _make_diagnosis(["stale_context"], waste=2.80),
    ]
    result = accumulate(diagnoses)
    assert abs(result[FindingKind.STALE_CONTEXT].total_waste_usd - 4.30) < 0.01


def test_accumulate_stores_up_to_3_summaries():
    from cctx.models import FindingKind
    from cctx.recommender.evidence import accumulate

    diagnoses = [_make_diagnosis(["retry_loop"]) for _ in range(10)]
    result = accumulate(diagnoses)
    assert len(result[FindingKind.RETRY_LOOP].example_summaries) <= 3


def test_accumulate_handles_no_findings_in_diagnosis():
    from cctx.recommender.evidence import accumulate

    diagnoses = [_make_diagnosis([])]
    result = accumulate(diagnoses)
    assert result == {}


def test_accumulate_deduplicates_same_kind_in_one_session():
    """One session with two retry_loop findings → session_count=1, not 2."""
    from cctx.models import Confidence, Diagnosis, Finding, FindingKind, Severity
    from cctx.recommender.evidence import accumulate

    findings = [
        Finding(
            kind=FindingKind.RETRY_LOOP,
            severity=Severity.HIGH,
            confidence=Confidence.HIGH,
            first_turn=2,
            last_turn=5,
            evidence={},
            cost_usd=None,
            summary="first retry",
        ),
        Finding(
            kind=FindingKind.RETRY_LOOP,
            severity=Severity.HIGH,
            confidence=Confidence.HIGH,
            first_turn=8,
            last_turn=11,
            evidence={},
            cost_usd=None,
            summary="second retry in same session",
        ),
    ]
    diagnosis = Diagnosis(
        session_id="multi-finding",
        findings=findings,
        inflection_turn=2,
        patches=[],
        total_cost_usd=1.0,
        waste_cost_usd=0.0,
        analysed_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    result = accumulate([diagnosis])
    assert result[FindingKind.RETRY_LOOP].session_count == 1
