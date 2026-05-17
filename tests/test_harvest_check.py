"""Tests for cctx/harvest.py check_claude_md() and --check CLI flag."""
from __future__ import annotations

# ---------------------------------------------------------------------------
# check_claude_md unit tests
# ---------------------------------------------------------------------------

def test_no_claude_md_returns_empty(tmp_path):
    from cctx.harvest import check_claude_md

    assert check_claude_md(tmp_path) == []


def test_clean_file_no_findings(tmp_path):
    from cctx.harvest import check_claude_md

    (tmp_path / "CLAUDE.md").write_text(
        "# Project\n\n## Retry discipline\n\nStop after two failures.\n"
    )
    assert check_claude_md(tmp_path) == []


def test_dead_file_reference(tmp_path):
    from cctx.harvest import CheckIssue, check_claude_md

    (tmp_path / "CLAUDE.md").write_text(
        "## Style guide\n\nSee `src/styles/theme.py` for colour tokens.\n"
    )
    findings = check_claude_md(tmp_path)
    assert any(f.issue is CheckIssue.DEAD_FILE_REF for f in findings)
    assert any("theme.py" in f.detail for f in findings)


def test_existing_file_reference_no_finding(tmp_path):
    from cctx.harvest import check_claude_md

    (tmp_path / "app.py").write_text("# app")
    (tmp_path / "CLAUDE.md").write_text(
        "## Guide\n\nMain entry point is `app.py`.\n"
    )
    findings = check_claude_md(tmp_path)
    assert not any("app.py" in f.detail for f in findings)


def test_dead_skill_reference(tmp_path):
    from cctx.harvest import CheckIssue, check_claude_md

    (tmp_path / "CLAUDE.md").write_text(
        "## Skills\n\nUse `.claude/skills/nonexistent-skill.md`.\n"
    )
    findings = check_claude_md(tmp_path)
    assert any(f.issue is CheckIssue.DEAD_SKILL_REF for f in findings)


def test_empty_section_detected(tmp_path):
    from cctx.harvest import CheckIssue, check_claude_md

    (tmp_path / "CLAUDE.md").write_text(
        "## Retry discipline\n\n## Empty section\n\n## Another\n\nhas content\n"
    )
    findings = check_claude_md(tmp_path)
    issues = [f.issue for f in findings]
    assert CheckIssue.EMPTY_SECTION in issues
    headings = [f.heading for f in findings if f.issue is CheckIssue.EMPTY_SECTION]
    assert any("Empty section" in h for h in headings)


def test_preamble_not_flagged_as_empty(tmp_path):
    from cctx.harvest import CheckIssue, check_claude_md

    # File starts with preamble (no heading yet) — should not flag as empty section
    (tmp_path / "CLAUDE.md").write_text(
        "# cctx\n\nThis is the preamble.\n\n## Section\n\nHas content.\n"
    )
    findings = check_claude_md(tmp_path)
    assert not any(f.issue is CheckIssue.EMPTY_SECTION for f in findings)


def test_url_not_flagged_as_dead_file(tmp_path):
    from cctx.harvest import CheckIssue, check_claude_md

    (tmp_path / "CLAUDE.md").write_text(
        "## Docs\n\nSee `https://docs.example.com/api.json` for spec.\n"
    )
    findings = check_claude_md(tmp_path)
    assert not any(f.issue is CheckIssue.DEAD_FILE_REF for f in findings)


def test_multiple_issues(tmp_path):
    from cctx.harvest import check_claude_md

    (tmp_path / "CLAUDE.md").write_text(
        "## Dead ref\n\nSee `missing/module.py`.\n\n## Empty\n\n"
    )
    findings = check_claude_md(tmp_path)
    assert len(findings) >= 2


# ---------------------------------------------------------------------------
# CLI --check flag integration
# ---------------------------------------------------------------------------

def test_check_flag_clean_exits_zero(tmp_path):
    from click.testing import CliRunner

    from cctx.cli import cli

    (tmp_path / "CLAUDE.md").write_text("## Guide\n\nStop retrying after 2 failures.\n")
    runner = CliRunner()
    # harvest --check doesn't need a TARGET session file; we pass a dummy existing path
    result = runner.invoke(
        cli, ["harvest", str(tmp_path), "--check", "--target-dir", str(tmp_path)]
    )
    assert result.exit_code == 0


def test_check_flag_findings_exits_one(tmp_path):
    from click.testing import CliRunner

    from cctx.cli import cli

    (tmp_path / "CLAUDE.md").write_text(
        "## Dead ref\n\nSee `missing/module.py`.\n"
    )
    runner = CliRunner()
    result = runner.invoke(
        cli, ["harvest", str(tmp_path), "--check", "--target-dir", str(tmp_path)]
    )
    assert result.exit_code == 1


def test_check_flag_in_help():
    from click.testing import CliRunner

    from cctx.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["harvest", "--help"])
    assert "--check" in result.output
