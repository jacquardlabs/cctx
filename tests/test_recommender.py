"""Tests for cctx/recommender/claude_md.py — generate_from_patterns."""
from __future__ import annotations


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
