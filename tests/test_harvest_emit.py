"""Tests for cctx/harvest.py cross-agent emit (M15) and the managed-heading registry."""
from __future__ import annotations


def test_managed_headings_cover_the_five_diagnostic_kinds():
    from cctx.models import MANAGED_HEADINGS, FindingKind
    assert MANAGED_HEADINGS == {
        FindingKind.RETRY_LOOP:    "## Retry discipline",
        FindingKind.SCOPE_CREEP:   "## Scope discipline",
        FindingKind.STALE_CONTEXT: "## Context hygiene",
        FindingKind.TOOL_THRASH:   "## Tool-call discipline",
        FindingKind.DEAD_END:      "## Exploration discipline",
    }


def test_managed_heading_prefix_is_project_specific():
    from cctx.models import MANAGED_HEADING_PREFIX
    assert MANAGED_HEADING_PREFIX == "## Project-specific: "


def test_registry_matches_templates():
    """Each MANAGED_HEADINGS value equals the first '+##' line of its template diff."""
    from cctx.models import MANAGED_HEADINGS
    from cctx.recommender.claude_md import _TEMPLATES
    for kind, heading in MANAGED_HEADINGS.items():
        assert kind in _TEMPLATES, f"{kind} missing from _TEMPLATES"
        _desc, diff_body, _target = _TEMPLATES[kind]
        first_line = diff_body.splitlines()[0]
        assert first_line == f"+{heading}", (
            f"{kind}: template heading {first_line!r} != registry {('+' + heading)!r}"
        )


def _patch(target_file="CLAUDE.md", heading="## Retry discipline"):
    from cctx.models import FindingKind, Patch
    return Patch(
        target_file=target_file,
        description="desc",
        unified_diff=f"+{heading}\n+\n+body line",
        finding_kind=FindingKind.RETRY_LOOP,
        evidence_summary="ev",
    )


def test_retarget_clones_claude_md_patches_to_agents():
    from cctx.harvest import retarget_patches
    out = retarget_patches([_patch()], "agents")
    assert len(out) == 1
    assert out[0].target_file == "AGENTS.md"
    assert out[0].unified_diff == _patch().unified_diff


def test_retarget_excludes_non_claude_md_patches():
    from cctx.harvest import retarget_patches
    rules_patch = _patch(target_file=".claude/rules/foo.md")
    out = retarget_patches([_patch(), rules_patch], "agents")
    assert len(out) == 1
    assert out[0].target_file == "AGENTS.md"


def test_emit_targets_has_agents():
    from cctx.harvest import EMIT_TARGETS
    assert EMIT_TARGETS["agents"] == "AGENTS.md"
