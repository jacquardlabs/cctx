"""Tests for cctx/harvest.py — apply_patch, preview_patches, apply_patches, CLI."""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from cctx.models import FindingKind, Patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_patch(kind_str: str = "retry_loop", target_file: str = "CLAUDE.md") -> Patch:
    kind = FindingKind(kind_str)
    return Patch(
        target_file=target_file,
        description=f"Test {kind_str} patch",
        unified_diff="+## Retry discipline\n+\n+Do not retry the same failing call.",
        finding_kind=kind,
        evidence_summary=f"Test evidence for {kind_str}",
    )


def _make_patch_with_diff(diff: str, kind_str: str = "retry_loop") -> Patch:
    kind = FindingKind(kind_str)
    return Patch(
        target_file="CLAUDE.md",
        description=f"Test {kind_str} patch",
        unified_diff=diff,
        finding_kind=kind,
        evidence_summary="Test evidence",
    )


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------


def test_extract_body_strips_plus_prefix() -> None:
    from cctx.harvest import _extract_body

    diff = "+## Retry discipline\n+\n+Do not retry the same failing call."
    body = _extract_body(diff)
    assert body == "## Retry discipline\n\nDo not retry the same failing call."


def test_extract_body_lone_plus_becomes_blank_line() -> None:
    from cctx.harvest import _extract_body

    diff = "+## Heading\n+\n+Body line."
    body = _extract_body(diff)
    lines = body.splitlines()
    assert lines[0] == "## Heading"
    assert lines[1] == ""
    assert lines[2] == "Body line."


def test_fingerprint_returns_first_h2() -> None:
    from cctx.harvest import _fingerprint

    body = "## Retry discipline\n\nDo not retry the same failing call."
    assert _fingerprint(body) == "## Retry discipline"


def test_fingerprint_returns_none_when_no_h2() -> None:
    from cctx.harvest import _fingerprint

    body = "Just some text without a heading."
    assert _fingerprint(body) is None


def test_already_present_case_sensitive() -> None:
    from cctx.harvest import _already_present

    content = "## Scope discipline\n\nFinish the stated task."
    assert _already_present(content, "## Scope discipline") is True
    assert _already_present(content, "## Scope Discipline") is False


def test_already_present_line_anchored() -> None:
    from cctx.harvest import _already_present

    content = "prefix ## Scope discipline suffix\n## Scope discipline\n"
    # The first occurrence is not line-anchored (has prefix)
    # but the second line IS anchored — should still return True
    assert _already_present(content, "## Scope discipline") is True


# ---------------------------------------------------------------------------
# apply_patch unit tests
# ---------------------------------------------------------------------------


def test_apply_patch_to_empty_file(tmp_path: Path) -> None:
    from cctx.harvest import ApplyStatus, apply_patch

    patch = _make_patch()
    target_dir = tmp_path / "project"
    target_dir.mkdir()
    # Pre-create empty CLAUDE.md
    (target_dir / "CLAUDE.md").write_text("")

    result = apply_patch(patch, target_dir)

    assert result.status == ApplyStatus.APPLIED
    content = (target_dir / "CLAUDE.md").read_text()
    assert "## Retry discipline" in content
    assert "Do not retry the same failing call." in content


def test_apply_patch_to_existing_file_appends_with_separator(tmp_path: Path) -> None:
    from cctx.harvest import ApplyStatus, apply_patch

    patch = _make_patch()
    target_dir = tmp_path / "project"
    target_dir.mkdir()
    (target_dir / "CLAUDE.md").write_text("# Existing content\n")

    result = apply_patch(patch, target_dir)

    assert result.status == ApplyStatus.APPLIED
    content = (target_dir / "CLAUDE.md").read_text()
    # Should have a separator between existing content and new content
    assert "# Existing content" in content
    assert "## Retry discipline" in content
    # Separator: at least one blank line between the two sections
    idx_existing = content.index("# Existing content")
    idx_new = content.index("## Retry discipline")
    between = content[idx_existing + len("# Existing content"):idx_new]
    assert "\n" in between


def test_apply_patch_idempotent_skips_if_present(tmp_path: Path) -> None:
    from cctx.harvest import ApplyStatus, apply_patch

    patch = _make_patch()
    target_dir = tmp_path / "project"
    target_dir.mkdir()
    (target_dir / "CLAUDE.md").write_text("")

    result1 = apply_patch(patch, target_dir)
    assert result1.status == ApplyStatus.APPLIED

    result2 = apply_patch(patch, target_dir)
    assert result2.status == ApplyStatus.SKIPPED
    assert "already present" in result2.message

    # Content should appear only once
    content = (target_dir / "CLAUDE.md").read_text()
    assert content.count("## Retry discipline") == 1


def test_apply_patch_case_sensitive_fingerprint(tmp_path: Path) -> None:
    """## Scope discipline != ## Scope Discipline; patch should apply."""
    from cctx.harvest import ApplyStatus, apply_patch

    # File contains the UPPERCASE variant
    target_dir = tmp_path / "project"
    target_dir.mkdir()
    (target_dir / "CLAUDE.md").write_text("## Scope Discipline\n\nSome existing rule.\n")

    patch = _make_patch_with_diff(
        "+## Scope discipline\n+\n+Finish the stated task.",
        kind_str="scope_creep",
    )
    result = apply_patch(patch, target_dir)
    # Case mismatch → fingerprint not found → should APPLY
    assert result.status == ApplyStatus.APPLIED


def test_fingerprint_collision_prevention(tmp_path: Path) -> None:
    """File has '## Scope' but not '## Scope discipline' → not skipped."""
    from cctx.harvest import ApplyStatus, apply_patch

    target_dir = tmp_path / "project"
    target_dir.mkdir()
    (target_dir / "CLAUDE.md").write_text("## Scope\n\nSome other scope rule.\n")

    patch = _make_patch_with_diff(
        "+## Scope discipline\n+\n+Finish the stated task.",
        kind_str="scope_creep",
    )
    result = apply_patch(patch, target_dir)
    assert result.status == ApplyStatus.APPLIED
    content = (target_dir / "CLAUDE.md").read_text()
    assert "## Scope discipline" in content


def test_apply_patch_creates_file_if_missing(tmp_path: Path) -> None:
    from cctx.harvest import ApplyStatus, apply_patch

    patch = _make_patch()
    target_dir = tmp_path / "project"
    target_dir.mkdir()
    # CLAUDE.md does NOT exist yet

    result = apply_patch(patch, target_dir)

    assert result.status == ApplyStatus.APPLIED
    assert (target_dir / "CLAUDE.md").exists()
    content = (target_dir / "CLAUDE.md").read_text()
    assert "## Retry discipline" in content


def test_non_md_target_returns_skipped(tmp_path: Path) -> None:
    from cctx.harvest import ApplyStatus, apply_patch

    patch = _make_patch(target_file=".claude/config.json")
    target_dir = tmp_path / "project"
    target_dir.mkdir()

    result = apply_patch(patch, target_dir)

    assert result.status == ApplyStatus.SKIPPED
    assert "not supported" in result.message


def test_rules_target_creates_dir_and_file(tmp_path: Path) -> None:
    from cctx.harvest import ApplyStatus, apply_patch

    patch = _make_patch(target_file=".claude/rules/retry-discipline.md")
    target_dir = tmp_path / "project"
    target_dir.mkdir()

    result = apply_patch(patch, target_dir)

    assert result.status == ApplyStatus.APPLIED
    rules_file = target_dir / ".claude" / "rules" / "retry-discipline.md"
    assert rules_file.exists()
    assert "Retry discipline" in rules_file.read_text()


def test_skills_target_creates_stub(tmp_path: Path) -> None:
    from cctx.harvest import ApplyStatus, apply_patch

    patch = _make_patch(target_file=".claude/skills/retry-guide.md")
    target_dir = tmp_path / "project"
    target_dir.mkdir()

    result = apply_patch(patch, target_dir)

    assert result.status == ApplyStatus.APPLIED
    skill_file = target_dir / ".claude" / "skills" / "retry-guide.md"
    assert skill_file.exists()


def test_new_target_idempotent(tmp_path: Path) -> None:
    from cctx.harvest import ApplyStatus, apply_patch

    patch = _make_patch(target_file=".claude/rules/discipline.md")
    target_dir = tmp_path / "project"
    target_dir.mkdir()

    r1 = apply_patch(patch, target_dir)
    r2 = apply_patch(patch, target_dir)

    assert r1.status == ApplyStatus.APPLIED
    assert r2.status == ApplyStatus.SKIPPED


def test_preview_patches_does_not_write(tmp_path: Path) -> None:
    from cctx.harvest import ApplyStatus, preview_patches

    patch = _make_patch()
    target_dir = tmp_path / "project"
    target_dir.mkdir()
    # CLAUDE.md does NOT exist

    results = preview_patches([patch], target_dir)

    assert len(results) == 1
    assert results[0].status == ApplyStatus.APPLIED
    # File must NOT have been created
    assert not (target_dir / "CLAUDE.md").exists()


def test_apply_patches_multi_patch(tmp_path: Path) -> None:
    """Two patches: one already present → one APPLIED, one SKIPPED."""
    from cctx.harvest import ApplyStatus, apply_patches

    target_dir = tmp_path / "project"
    target_dir.mkdir()
    # Pre-populate the scope_creep heading
    (target_dir / "CLAUDE.md").write_text("## Scope discipline\n\nFinish the stated task.\n")

    patch_retry = _make_patch("retry_loop")
    patch_scope = _make_patch_with_diff(
        "+## Scope discipline\n+\n+Finish the stated task.",
        kind_str="scope_creep",
    )

    results = apply_patches([patch_retry, patch_scope], target_dir)

    assert len(results) == 2
    statuses = {r.patch.finding_kind.value: r.status for r in results}
    assert statuses["retry_loop"] == ApplyStatus.APPLIED
    assert statuses["scope_creep"] == ApplyStatus.SKIPPED


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "claude_code" / "short-clean" / "short-clean.jsonl"
)


def test_harvest_cli_smoke() -> None:
    """Clean session → zero findings → 'No patches' message, exit 0."""
    from cctx.cli import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["harvest", str(FIXTURE_PATH), "--dry-run"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "No patches" in result.output


def test_harvest_cli_dry_run(tmp_path: Path) -> None:
    """--dry-run flag: exits 0, no file created."""
    from cctx.cli import cli

    runner = CliRunner()
    target_dir = tmp_path / "project"
    target_dir.mkdir()

    result = runner.invoke(
        cli,
        [
            "harvest",
            str(FIXTURE_PATH),
            "--dry-run",
            "--target-dir",
            str(target_dir),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    # CLAUDE.md should NOT be written during dry-run
    assert not (target_dir / "CLAUDE.md").exists()


def test_harvest_cli_apply_dry_run_error() -> None:
    """--apply and --dry-run together → non-zero exit (UsageError)."""
    from cctx.cli import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["harvest", str(FIXTURE_PATH), "--apply", "--dry-run"],
    )
    assert result.exit_code != 0
