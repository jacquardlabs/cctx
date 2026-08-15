"""Tests for cctx/recommender/claude_md.py."""
from __future__ import annotations

from datetime import datetime, timezone

from tests.diagnostician.conftest import (
    make_retry_occurrence,
    make_scope_phrase,
    make_stale_item,
)


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

    occ = make_retry_occurrence(turn=12, key="src/foo.py", call="Edit", error="not found")
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


def test_generate_from_evidence_omits_dollar_when_no_cost_basis():
    """Kinds with no honest per-session cost basis (e.g. scope_creep) must not
    print a misleading '$0.00 wasted' — omit the dollar clause entirely."""
    from cctx.models import FindingKind, KindEvidence
    from cctx.recommender.claude_md import generate_from_evidence

    evidence = {
        FindingKind.SCOPE_CREEP: KindEvidence(
            kind=FindingKind.SCOPE_CREEP,
            session_count=5,
            total_waste_usd=0.0,
            example_summaries=["'while I'm here' at turn 4"],
        )
    }
    patches = generate_from_evidence(evidence)
    assert len(patches) == 1
    assert "wasted" not in patches[0].unified_diff
    assert "Evidence: appeared in 5 sessions." in patches[0].unified_diff


def test_generate_from_evidence_omits_dollar_when_subcent():
    """A nonzero but sub-cent total (rounds to $0.00 under :.2f) must also omit
    the dollar clause rather than print a misleading '$0.00 wasted'."""
    from cctx.models import FindingKind, KindEvidence
    from cctx.recommender.claude_md import generate_from_evidence

    evidence = {
        FindingKind.EXPLORATION_THRASH: KindEvidence(
            kind=FindingKind.EXPLORATION_THRASH,
            session_count=4,
            total_waste_usd=0.0045,
            example_summaries=["1 exploration thrash window (turns 19-35)"],
        )
    }
    patches = generate_from_evidence(evidence)
    assert len(patches) == 1
    assert "wasted" not in patches[0].unified_diff
    assert "Evidence: appeared in 4 sessions." in patches[0].unified_diff


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


# ---------------------------------------------------------------------------
# summarize() — uncovered match arms
# ---------------------------------------------------------------------------


def test_summarize_scope_creep_with_phrases():
    """SCOPE_CREEP with phrases evidence uses the phrase/turn branch."""
    from cctx.recommender.claude_md import summarize

    evidence = {
        "phrases": [
            make_scope_phrase(
                turn=4, phrase="let me also", snippet="while doing this let me also fix"
            ),
        ]
    }
    finding = _make_finding("scope_creep", evidence=evidence)
    result = summarize(finding)
    assert "let me also" in result
    assert "4" in result


def test_summarize_scope_creep_no_phrases_falls_back_to_summary():
    """SCOPE_CREEP with empty phrases falls back to finding.summary."""
    from cctx.recommender.claude_md import summarize

    finding = _make_finding("scope_creep", evidence={"phrases": []})
    result = summarize(finding)
    assert result == finding.summary


def test_summarize_stale_context_with_stale_items():
    """STALE_CONTEXT with stale_items uses the worst-item branch."""
    from cctx.recommender.claude_md import summarize

    evidence = {
        "stale_items": [
            make_stale_item(
                tool_name="Bash",
                content_tokens=5000,
                first_seen_turn=2,
                last_referenced_turn=3,
                turns_stale=8,
                token_turns=40000,
            )
        ],
        "total_token_turns": 40000,
    }
    finding = _make_finding("stale_context", evidence=evidence)
    result = summarize(finding)
    assert "Bash" in result
    assert "8" in result  # turns_stale
    assert "40,000" in result  # total_token_turns formatted


def test_summarize_stale_context_includes_cost_when_present():
    from cctx.models import Confidence, Finding, FindingKind, Severity
    from cctx.recommender.claude_md import summarize

    evidence = {
        "stale_items": [
            make_stale_item(
                tool_name="Bash",
                content_tokens=22000,
                first_seen_turn=1,
                last_referenced_turn=2,
                turns_stale=14,
                token_turns=308000,
            )
        ],
        "total_token_turns": 308000,
    }
    finding = Finding(
        kind=FindingKind.STALE_CONTEXT,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=1,
        last_turn=15,
        evidence=evidence,
        cost_usd=0.88,
        summary="stale context",
    )
    result = summarize(finding)
    assert "0.88" in result


def test_summarize_stale_context_no_items_falls_back_to_summary():
    from cctx.recommender.claude_md import summarize

    finding = _make_finding("stale_context", evidence={"stale_items": []})
    result = summarize(finding)
    assert result == finding.summary


def test_summarize_retry_loop_with_occurrences():
    """RETRY_LOOP with occurrences uses the call/key/turn branch."""
    from cctx.recommender.claude_md import summarize

    evidence = {
        "occurrences": [
            make_retry_occurrence(turn=3, key="src/foo.py", error="Error: not found"),
            make_retry_occurrence(turn=5, key="src/foo.py", error="Error: not found"),
        ],
        "loop_length": 2,
    }
    finding = _make_finding("retry_loop", evidence=evidence)
    result = summarize(finding)
    assert "Edit" in result
    assert "src/foo.py" in result
    assert "2" in result  # loop_length


# ---------------------------------------------------------------------------
# generate_from_evidence — kind not in _TEMPLATES guard
# ---------------------------------------------------------------------------


def test_generate_from_evidence_skips_unknown_kind(monkeypatch):
    """generate_from_evidence silently skips kinds absent from _TEMPLATES."""
    import cctx.recommender.claude_md as _mod
    from cctx.models import FindingKind, KindEvidence

    # Remove RETRY_LOOP from the template dict for this test only
    original = dict(_mod._TEMPLATES)
    monkeypatch.setitem(_mod._TEMPLATES, FindingKind.RETRY_LOOP, original[FindingKind.RETRY_LOOP])
    patched = {k: v for k, v in original.items() if k != FindingKind.RETRY_LOOP}
    monkeypatch.setattr(_mod, "_TEMPLATES", patched)

    evidence = {
        FindingKind.RETRY_LOOP: KindEvidence(
            kind=FindingKind.RETRY_LOOP,
            session_count=3,
            total_waste_usd=1.00,
            example_summaries=["example"],
        ),
        FindingKind.SCOPE_CREEP: KindEvidence(
            kind=FindingKind.SCOPE_CREEP,
            session_count=1,
            total_waste_usd=0.05,
            example_summaries=[],
        ),
    }
    patches = _mod.generate_from_evidence(evidence)
    # Only SCOPE_CREEP has a template; RETRY_LOOP is skipped
    assert len(patches) == 1
    assert patches[0].finding_kind is FindingKind.SCOPE_CREEP


# ---------------------------------------------------------------------------
# generate() — single-session with actual evidence-populated findings
# ---------------------------------------------------------------------------


def test_generate_retry_loop_evidence_summary_contains_call_and_key():
    """generate() uses summarize() for evidence_summary; verify end-to-end."""
    from cctx.recommender.claude_md import generate

    evidence = {
        "occurrences": [
            make_retry_occurrence(turn=3, key="file.py", error="Error: not found"),
        ],
        "loop_length": 1,
    }
    finding = _make_finding("retry_loop", evidence=evidence)
    result = generate(_make_diagnosis([finding]))
    assert "Edit" in result.patches[0].evidence_summary
    assert "file.py" in result.patches[0].evidence_summary


def test_generate_scope_creep_evidence_summary_contains_phrase():
    from cctx.recommender.claude_md import generate

    evidence = {
        "phrases": [
            make_scope_phrase(turn=4, phrase="let me also", snippet="let me also fix X")
        ]
    }
    finding = _make_finding("scope_creep", evidence=evidence)
    result = generate(_make_diagnosis([finding]))
    assert "let me also" in result.patches[0].evidence_summary


def test_generate_stale_context_evidence_summary_contains_tool_name():
    from cctx.recommender.claude_md import generate

    evidence = {
        "stale_items": [
            make_stale_item(
                tool_name="Bash",
                content_tokens=5000,
                first_seen_turn=2,
                last_referenced_turn=3,
                turns_stale=8,
                token_turns=40000,
            )
        ],
        "total_token_turns": 40000,
    }
    finding = _make_finding("stale_context", evidence=evidence)
    result = generate(_make_diagnosis([finding]))
    assert "Bash" in result.patches[0].evidence_summary


def test_generate_from_evidence_empty_example_summaries():
    """evidence_summary is empty string when no example_summaries present."""
    from cctx.models import FindingKind, KindEvidence
    from cctx.recommender.claude_md import generate_from_evidence

    evidence = {
        FindingKind.SCOPE_CREEP: KindEvidence(
            kind=FindingKind.SCOPE_CREEP,
            session_count=2,
            total_waste_usd=0.30,
            example_summaries=[],
        )
    }
    patches = generate_from_evidence(evidence)
    assert patches[0].evidence_summary == ""
