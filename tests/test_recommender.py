"""Tests for cctx/recommender/claude_md.py — generate_from_patterns."""
from __future__ import annotations

from datetime import datetime, timezone


def _make_finding(kind):
    from cctx.models import Confidence, Finding, Severity
    return Finding(
        kind=kind,
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=3,
        last_turn=7,
        evidence={},
        cost_usd=0.50,
        summary=f"{kind.value} occurred",
    )


def _make_diagnosis(findings):
    from cctx.models import Diagnosis
    return Diagnosis(
        session_id="s1",
        findings=findings,
        inflection_turn=None,
        patches=[],
        total_cost_usd=1.0,
        waste_cost_usd=0.5,
        analysed_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
    )


def test_generate_handles_tool_thrash_finding():
    """Regression: single-session generate() must not KeyError on TOOL_THRASH."""
    from cctx.models import FindingKind
    from cctx.recommender.claude_md import generate
    diagnosis = _make_diagnosis([_make_finding(FindingKind.TOOL_THRASH)])
    result = generate(diagnosis)
    assert len(result.patches) == 1
    assert result.patches[0].unified_diff.splitlines()[0] == "+## Tool-call discipline"


def test_generate_handles_dead_end_finding():
    """Regression: single-session generate() must not KeyError on DEAD_END."""
    from cctx.models import FindingKind
    from cctx.recommender.claude_md import generate
    diagnosis = _make_diagnosis([_make_finding(FindingKind.DEAD_END)])
    result = generate(diagnosis)
    assert len(result.patches) == 1
    assert result.patches[0].unified_diff.splitlines()[0] == "+## Exploration discipline"


def test_generate_from_evidence_emits_tool_thrash_and_dead_end():
    """Cross-session path must now emit these kinds instead of silently skipping."""
    from cctx.models import FindingKind, KindEvidence
    from cctx.recommender.claude_md import generate_from_evidence
    ev = {
        FindingKind.TOOL_THRASH: KindEvidence(
            kind=FindingKind.TOOL_THRASH, session_count=3,
            total_waste_usd=2.0, example_summaries=["thrash example"],
        ),
        FindingKind.DEAD_END: KindEvidence(
            kind=FindingKind.DEAD_END, session_count=1,
            total_waste_usd=0.5, example_summaries=["dead end example"],
        ),
    }
    patches = generate_from_evidence(ev)
    kinds = {p.finding_kind for p in patches}
    assert FindingKind.TOOL_THRASH in kinds
    assert FindingKind.DEAD_END in kinds


def _make_pattern(failure_key="pnpm install", fix_key="pnpm --filter app", session_count=7):
    from cctx.models import ProjectPattern
    return ProjectPattern(
        tool_name="Bash",
        failure_key=failure_key,
        fix_key=fix_key,
        session_count=session_count,
        avg_wasted_turns=12.0,
        total_waste_usd=4.20,
        example_sessions=["s1", "s2", "s3"],
    )


def test_generate_from_patterns_returns_one_patch_per_pattern():
    from cctx.recommender.claude_md import generate_from_patterns
    patches = generate_from_patterns([
        _make_pattern(),
        _make_pattern("npm run build", "npm run build --workspace"),
    ])
    assert len(patches) == 2


def test_patch_target_file_is_claude_md():
    from cctx.recommender.claude_md import generate_from_patterns
    patches = generate_from_patterns([_make_pattern()])
    assert patches[0].target_file == "CLAUDE.md"


def test_patch_finding_kind_is_project_pattern():
    from cctx.models import FindingKind
    from cctx.recommender.claude_md import generate_from_patterns
    patches = generate_from_patterns([_make_pattern()])
    assert patches[0].finding_kind is FindingKind.PROJECT_PATTERN


def test_patch_diff_contains_failure_and_fix_keys():
    from cctx.recommender.claude_md import generate_from_patterns
    patches = generate_from_patterns([_make_pattern()])
    diff = patches[0].unified_diff
    assert "pnpm install" in diff
    assert "pnpm --filter app" in diff


def test_patch_evidence_summary_contains_session_count():
    from cctx.recommender.claude_md import generate_from_patterns
    patches = generate_from_patterns([_make_pattern(session_count=7)])
    assert "7" in patches[0].evidence_summary


def test_generate_from_patterns_empty_returns_empty():
    from cctx.recommender.claude_md import generate_from_patterns
    assert generate_from_patterns([]) == []
