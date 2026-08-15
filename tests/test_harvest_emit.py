"""Tests for cctx/harvest.py cross-agent emit (M15) and the managed-heading registry."""
from __future__ import annotations


def test_managed_headings_cover_the_diagnostic_kinds():
    from cctx.models import MANAGED_HEADINGS, FindingKind
    assert MANAGED_HEADINGS == {
        FindingKind.RETRY_LOOP:         "## Retry discipline",
        FindingKind.SCOPE_CREEP:        "## Scope discipline",
        FindingKind.STALE_CONTEXT:      "## Context hygiene",
        FindingKind.TOOL_THRASH:        "## Tool-call discipline",
        FindingKind.DEAD_END:           "## Exploration discipline",
        FindingKind.FANOUT_WASTE:       "## Fan-out discipline",
        FindingKind.CACHE_HYGIENE:      "## Cache hygiene",
        FindingKind.COMPACTION:         "## Compaction hygiene",
        FindingKind.EXPLORATION_THRASH: "## Exploration thrash",
        FindingKind.UNUSED_CONTEXT:     "## Context overhead",
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
    from cctx.emit import retarget_patches
    out = retarget_patches([_patch()], "agents")
    assert len(out) == 1
    assert out[0].target_file == "AGENTS.md"
    assert out[0].unified_diff == _patch().unified_diff


def test_retarget_excludes_non_claude_md_patches():
    from cctx.emit import retarget_patches
    rules_patch = _patch(target_file=".claude/rules/foo.md")
    out = retarget_patches([_patch(), rules_patch], "agents")
    assert len(out) == 1
    assert out[0].target_file == "AGENTS.md"


def test_emit_targets_has_agents():
    from cctx.emit import EMIT_TARGETS
    assert EMIT_TARGETS["agents"] == "AGENTS.md"


def test_sync_returns_managed_sections_only(tmp_path):
    from cctx.emit import sync_managed_sections
    (tmp_path / "CLAUDE.md").write_text(
        "# Project\n\n"
        "## Retry discipline\n\nRetry rule body.\n\n"
        "## My hand-written section\n\nNot managed by cctx.\n\n"
        "## Project-specific: Bash(pnpm install)\n\nUse pnpm --filter.\n",
        encoding="utf-8",
    )
    patches = sync_managed_sections(tmp_path, "agents")
    headings = {p.unified_diff.splitlines()[0] for p in patches}
    assert "+## Retry discipline" in headings
    assert "+## Project-specific: Bash(pnpm install)" in headings
    assert "+## My hand-written section" not in headings
    assert all(p.target_file == "AGENTS.md" for p in patches)


def test_sync_finding_kind_reverse_lookup(tmp_path):
    from cctx.emit import sync_managed_sections
    from cctx.models import FindingKind
    (tmp_path / "CLAUDE.md").write_text(
        "## Context hygiene\n\nbody\n\n"
        "## Project-specific: Bash(x)\n\nbody\n",
        encoding="utf-8",
    )
    patches = sync_managed_sections(tmp_path, "agents")
    by_heading = {p.unified_diff.splitlines()[0]: p.finding_kind for p in patches}
    assert by_heading["+## Context hygiene"] is FindingKind.STALE_CONTEXT
    assert by_heading["+## Project-specific: Bash(x)"] is FindingKind.PROJECT_PATTERN


def test_sync_no_claude_md_returns_empty(tmp_path):
    from cctx.emit import sync_managed_sections
    assert sync_managed_sections(tmp_path, "agents") == []


def test_emit_apply_then_reapply_is_idempotent(tmp_path):
    from cctx.emit import retarget_patches
    from cctx.harvest import ApplyStatus, apply_patches
    patches = retarget_patches([_patch()], "agents")
    first = apply_patches(patches, tmp_path)
    assert [r.status for r in first] == [ApplyStatus.APPLIED]
    second = apply_patches(patches, tmp_path)
    assert [r.status for r in second] == [ApplyStatus.SKIPPED]
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert text.count("## Retry discipline") == 1


def test_sync_apply_then_reapply_is_idempotent(tmp_path):
    from cctx.emit import sync_managed_sections
    from cctx.harvest import ApplyStatus, apply_patches
    (tmp_path / "CLAUDE.md").write_text(
        "## Retry discipline\n\nRetry rule body.\n", encoding="utf-8"
    )
    patches = sync_managed_sections(tmp_path, "agents")
    apply_patches(patches, tmp_path)
    second = apply_patches(patches, tmp_path)
    assert all(r.status is ApplyStatus.SKIPPED for r in second)
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert text.count("## Retry discipline") == 1


def test_preview_same_heading_different_targets_both_applied(tmp_path):
    """Two patches with the same heading but different target files must both
    preview as APPLIED — dedup is per-(file, heading), not heading-only."""
    from cctx.harvest import ApplyStatus, preview_patches
    from cctx.models import FindingKind, Patch
    diff = "+## Retry discipline\n+\n+body"
    patches = [
        Patch("CLAUDE.md", "d", diff, FindingKind.RETRY_LOOP, "e"),
        Patch("AGENTS.md", "d", diff, FindingKind.RETRY_LOOP, "e"),
    ]
    statuses = [r.status for r in preview_patches(patches, tmp_path)]
    assert statuses == [ApplyStatus.APPLIED, ApplyStatus.APPLIED]


def test_preview_same_heading_same_target_dedups(tmp_path):
    """Two patches with the same heading AND same target: second is SKIPPED."""
    from cctx.harvest import ApplyStatus, preview_patches
    from cctx.models import FindingKind, Patch
    diff = "+## Retry discipline\n+\n+body"
    patches = [
        Patch("AGENTS.md", "d", diff, FindingKind.RETRY_LOOP, "e"),
        Patch("AGENTS.md", "d", diff, FindingKind.RETRY_LOOP, "e"),
    ]
    statuses = [r.status for r in preview_patches(patches, tmp_path)]
    assert statuses == [ApplyStatus.APPLIED, ApplyStatus.SKIPPED]


def test_sync_without_emit_errors(tmp_path):
    from click.testing import CliRunner  # noqa: I001
    from cctx.cli import cli
    (tmp_path / "CLAUDE.md").write_text("## Retry discipline\n\nbody\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "harvest", str(tmp_path), "--since", "7",
        "--sync", "--target-dir", str(tmp_path),
    ])
    assert result.exit_code != 0
    assert "--sync" in result.output and "--emit" in result.output


def test_sync_dry_run_writes_nothing(tmp_path):
    from click.testing import CliRunner  # noqa: I001
    from cctx.cli import cli
    (tmp_path / "CLAUDE.md").write_text("## Retry discipline\n\nbody\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "harvest", str(tmp_path), "--since", "7",
        "--emit", "agents", "--sync", "--dry-run",
        "--target-dir", str(tmp_path),
    ])
    assert result.exit_code == 0
    assert not (tmp_path / "AGENTS.md").exists()


def test_sync_apply_creates_agents_md(tmp_path):
    from click.testing import CliRunner  # noqa: I001
    from cctx.cli import cli
    (tmp_path / "CLAUDE.md").write_text("## Retry discipline\n\nbody\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "harvest", str(tmp_path), "--since", "7",
        "--emit", "agents", "--sync", "--apply",
        "--target-dir", str(tmp_path),
    ])
    assert result.exit_code == 0
    assert (tmp_path / "AGENTS.md").exists()
    assert "## Retry discipline" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")


def test_emit_applies_both_targets(tmp_path):
    """End-to-end fan-out: a CLAUDE.md patch and its retargeted clone both land,
    one in CLAUDE.md and one in AGENTS.md (mirrors the CLI's base+retarget flow)."""
    from cctx.emit import retarget_patches
    from cctx.harvest import ApplyStatus, apply_patches
    base = [_patch()]  # one CLAUDE.md patch
    combined = base + retarget_patches(base, "agents")
    results = apply_patches(combined, tmp_path)
    assert all(r.status is ApplyStatus.APPLIED for r in results)
    assert "## Retry discipline" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## Retry discipline" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")


def test_emit_imports_only_public_harvest_api():
    """#177 Track-1: emit.py consumes harvest's public surface, not its privates.

    Scoped to emit.py deliberately — repo-wide this would also fail on
    cctx/watcher.py's `from cctx.discovery import _encode_path`, which #177
    does not cover and #203 tracks.
    """
    import ast
    from pathlib import Path

    import cctx
    import cctx.harvest

    src = Path(cctx.__file__).parent / "emit.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    private = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("cctx")
        for alias in node.names
        if alias.name.startswith("_")
    ]
    assert private == [], f"emit.py reaches into private cctx names: {private}"
    assert callable(cctx.harvest.parse_sections)
