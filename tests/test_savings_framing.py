"""Tests for health grade and savings framing (issue #101).

Tests cover:
- compute_health_grade() grade logic for all A–F outcomes
- render_diagnosis() with show_health=True smoke test
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest

from cctx.models import Confidence, Diagnosis, Finding, FindingKind, Severity
from cctx.renderers.terminal import compute_health_grade, render_diagnosis

_TS = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _diagnosis(
    findings: list[Finding],
    total_cost: float = 1.0,
    waste_cost: float = 0.0,
) -> Diagnosis:
    return Diagnosis(
        session_id="test-session",
        findings=findings,
        inflection_turn=None,
        patches=[],
        total_cost_usd=total_cost,
        waste_cost_usd=waste_cost,
        analysed_at=_TS,
        subagent_costs=[],
    )


def _finding(severity: Severity = Severity.MEDIUM, cost: float | None = None) -> Finding:
    return Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=severity,
        confidence=Confidence.HIGH,
        first_turn=1,
        last_turn=5,
        evidence={},
        cost_usd=cost,
        summary="test finding",
    )


# ---------------------------------------------------------------------------
# Grade logic
# ---------------------------------------------------------------------------


def test_grade_no_findings_is_a():
    diag = _diagnosis(findings=[], total_cost=1.0, waste_cost=0.0)
    assert compute_health_grade(diag) == "A"


def test_grade_findings_low_waste_is_b():
    """Findings present, waste < 10% → B."""
    diag = _diagnosis(
        findings=[_finding()],
        total_cost=1.0,
        waste_cost=0.05,  # 5%
    )
    assert compute_health_grade(diag) == "B"


def test_grade_findings_moderate_waste_is_c():
    """Findings present, waste 15% (>10%, ≤25%) → C."""
    diag = _diagnosis(
        findings=[_finding()],
        total_cost=1.0,
        waste_cost=0.15,  # 15%
    )
    assert compute_health_grade(diag) == "C"


def test_grade_findings_high_waste_is_d():
    """Findings present, waste 30% (>25%) → D."""
    diag = _diagnosis(
        findings=[_finding()],
        total_cost=1.0,
        waste_cost=0.30,  # 30%
    )
    assert compute_health_grade(diag) == "D"


def test_grade_high_severity_low_waste_is_d():
    """HIGH severity finding with waste < 25% → D (severity alone triggers D)."""
    diag = _diagnosis(
        findings=[_finding(severity=Severity.HIGH)],
        total_cost=1.0,
        waste_cost=0.10,  # 10% — not above 25%, but HIGH severity still triggers D
    )
    assert compute_health_grade(diag) == "D"


def test_grade_high_severity_high_waste_is_f():
    """HIGH severity finding + waste > 50% → F."""
    diag = _diagnosis(
        findings=[_finding(severity=Severity.HIGH)],
        total_cost=1.0,
        waste_cost=0.60,  # 60%
    )
    assert compute_health_grade(diag) == "F"


def test_grade_zero_cost_session_with_findings_is_b():
    """Zero-cost session (total=0, waste=0) with findings → waste_frac=0 → B."""
    diag = _diagnosis(
        findings=[_finding()],
        total_cost=0.0,
        waste_cost=0.0,
    )
    assert compute_health_grade(diag) == "B"


# ---------------------------------------------------------------------------
# render_diagnosis smoke test with show_health=True
# ---------------------------------------------------------------------------


@pytest.fixture
def make_diagnosis():
    """Factory fixture: returns a callable that produces a Diagnosis."""
    def _make(
        findings: list[Finding] | None = None,
        total_cost: float = 1.0,
        waste_cost: float = 0.20,
    ) -> Diagnosis:
        if findings is None:
            findings = [_finding(severity=Severity.MEDIUM, cost=0.20)]
        return _diagnosis(findings, total_cost=total_cost, waste_cost=waste_cost)
    return _make


def test_render_diagnosis_with_health_does_not_raise(make_diagnosis):
    from rich.console import Console

    buf = io.StringIO()
    con = Console(file=buf, width=120, highlight=False, markup=False)
    render_diagnosis(make_diagnosis(), show_health=True, console=con)
    output = buf.getvalue()
    assert "Health grade:" in output


def test_render_diagnosis_health_grade_visible(make_diagnosis):
    from rich.console import Console

    buf = io.StringIO()
    con = Console(file=buf, width=120, highlight=False, markup=False)
    # waste_cost=0.20 on total_cost=1.0 → 20% waste → grade C
    render_diagnosis(make_diagnosis(waste_cost=0.20), show_health=True, console=con)
    output = buf.getvalue()
    assert "Health grade: C" in output


def test_render_diagnosis_savings_line_shown(make_diagnosis):
    """When show_health=True and finding has cost_usd, savings line appears."""
    from rich.console import Console

    buf = io.StringIO()
    con = Console(file=buf, width=120, highlight=False, markup=False)
    findings = [_finding(cost=0.42)]
    render_diagnosis(
        _diagnosis(findings, total_cost=1.0, waste_cost=0.42),
        show_health=True,
        console=con,
    )
    output = buf.getvalue()
    assert "savings if fixed" in output
    assert "0.42" in output


def test_render_diagnosis_no_savings_when_cost_is_none(make_diagnosis):
    """When finding.cost_usd is None, no savings line appears."""
    from rich.console import Console

    buf = io.StringIO()
    con = Console(file=buf, width=120, highlight=False, markup=False)
    findings = [_finding(cost=None)]
    render_diagnosis(
        _diagnosis(findings, total_cost=1.0, waste_cost=0.0),
        show_health=True,
        console=con,
    )
    output = buf.getvalue()
    assert "savings if fixed" not in output


def test_render_diagnosis_health_hidden_by_default(make_diagnosis):
    """Without show_health=True, no health grade or savings appear."""
    from rich.console import Console

    buf = io.StringIO()
    con = Console(file=buf, width=120, highlight=False, markup=False)
    render_diagnosis(make_diagnosis(), show_health=False, console=con)
    output = buf.getvalue()
    assert "Health grade:" not in output
    assert "savings if fixed" not in output
