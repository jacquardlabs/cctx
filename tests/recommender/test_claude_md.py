"""Tests for cctx/recommender/claude_md.py."""
from __future__ import annotations

from datetime import datetime, timezone


def _make_finding(kind_str: str, first_turn: int = 5, evidence: dict | None = None):
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
        first_turn=first_turn,
        last_turn=None,
        evidence=evidence or {},
        cost_usd=0.50 if kind_str == "stale_context" else None,
        summary=f"test {kind_str}",
    )


def _make_diagnosis(findings):
    from cctx.models import Diagnosis

    return Diagnosis(
        session_id="test-session",
        findings=findings,
        inflection_turn=findings[0].first_turn if findings else None,
        patches=[],
        total_cost_usd=2.14,
        waste_cost_usd=sum(f.cost_usd or 0 for f in findings),
        analysed_at=datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc),
    )


def test_generate_returns_new_diagnosis():
    from cctx.recommender.claude_md import generate

    diagnosis = _make_diagnosis([_make_finding("retry_loop")])
    result = generate(diagnosis)
    assert result is not diagnosis  # new object
    assert result.session_id == diagnosis.session_id


def test_generate_produces_one_patch_per_finding():
    from cctx.recommender.claude_md import generate

    findings = [_make_finding("retry_loop"), _make_finding("scope_creep")]
    result = generate(_make_diagnosis(findings))
    assert len(result.patches) == 2


def test_retry_loop_patch_targets_claude_md():
    from cctx.models import FindingKind
    from cctx.recommender.claude_md import generate

    result = generate(_make_diagnosis([_make_finding("retry_loop")]))
    patch = result.patches[0]
    assert patch.target_file == "CLAUDE.md"
    assert patch.finding_kind is FindingKind.RETRY_LOOP
    assert "+## Retry discipline" in patch.unified_diff


def test_scope_creep_patch_has_discipline_content():
    from cctx.recommender.claude_md import generate

    result = generate(_make_diagnosis([_make_finding("scope_creep")]))
    patch = result.patches[0]
    assert "Scope discipline" in patch.unified_diff


def test_stale_context_patch_has_hygiene_content():
    from cctx.recommender.claude_md import generate

    result = generate(_make_diagnosis([_make_finding("stale_context")]))
    patch = result.patches[0]
    assert "Context hygiene" in patch.unified_diff


def test_evidence_summary_populated():
    from cctx.recommender.claude_md import generate

    occ = {"turn": 12, "key": "src/foo.py", "call": "Edit", "error": "not found"}
    evidence = {"occurrences": [occ], "loop_length": 2}
    result = generate(_make_diagnosis([_make_finding("retry_loop", evidence=evidence)]))
    assert result.patches[0].evidence_summary != ""


def test_original_diagnosis_not_mutated():
    from cctx.recommender.claude_md import generate

    diagnosis = _make_diagnosis([_make_finding("retry_loop")])
    generate(diagnosis)
    assert diagnosis.patches == []  # original unchanged


def test_generate_from_evidence_single_session():
    """With session_count=1, no evidence line appended."""
    from cctx.models import FindingKind, KindEvidence
    from cctx.recommender.claude_md import generate_from_evidence

    evidence = {
        FindingKind.RETRY_LOOP: KindEvidence(
            kind=FindingKind.RETRY_LOOP,
            session_count=1,
            total_waste_usd=0.0,
            example_summaries=["Edit(foo.py) failed 2× between turns 5–8"],
        )
    }
    patches = generate_from_evidence(evidence)
    assert len(patches) == 1
    assert "Evidence:" not in patches[0].unified_diff


def test_generate_from_evidence_cross_session_appends_evidence_line():
    """With session_count>=2, evidence line is appended."""
    from cctx.models import FindingKind, KindEvidence
    from cctx.recommender.claude_md import generate_from_evidence

    evidence = {
        FindingKind.STALE_CONTEXT: KindEvidence(
            kind=FindingKind.STALE_CONTEXT,
            session_count=8,
            total_waste_usd=4.30,
            example_summaries=["22K-token Bash result stale 14 turns"],
        )
    }
    patches = generate_from_evidence(evidence)
    assert len(patches) == 1
    assert "\n+Evidence:" in patches[0].unified_diff
    assert "8" in patches[0].unified_diff
    assert "4.30" in patches[0].unified_diff
