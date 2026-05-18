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


def test_check_severity_enum_exists():
    from cctx.harvest import CheckSeverity
    assert CheckSeverity.LOW.value == "low"
    assert CheckSeverity.MEDIUM.value == "medium"
    assert CheckSeverity.HIGH.value == "high"


def test_check_issue_has_new_values():
    from cctx.harvest import CheckIssue
    assert CheckIssue.CONTRADICTION.value == "contradiction"
    assert CheckIssue.REDUNDANCY.value == "redundancy"
    assert CheckIssue.STALE_IDENTIFIER.value == "stale_identifier"


def test_check_finding_has_severity():
    from cctx.harvest import CheckFinding, CheckIssue, CheckSeverity
    f = CheckFinding(
        heading="## Test",
        issue=CheckIssue.EMPTY_SECTION,
        severity=CheckSeverity.MEDIUM,
        detail="no content",
    )
    assert f.severity is CheckSeverity.MEDIUM


def test_existing_checks_have_medium_severity(tmp_path):
    from cctx.harvest import CheckSeverity, check_claude_md
    (tmp_path / "CLAUDE.md").write_text(
        "## Dead ref\n\nSee `missing/module.py`.\n"
    )
    findings = check_claude_md(tmp_path)
    assert findings
    assert all(f.severity is CheckSeverity.MEDIUM for f in findings)


# ---------------------------------------------------------------------------
# check_contradictions unit tests
# ---------------------------------------------------------------------------

def test_contradiction_detected_across_sections():
    from cctx.harvest import CheckIssue, check_contradictions
    sections = [
        ("## Formatting", "Always use tabs for indentation."),
        ("## Style", "Never use tabs, use spaces instead."),
    ]
    findings = check_contradictions(sections)
    assert len(findings) == 1
    assert findings[0].issue is CheckIssue.CONTRADICTION


def test_no_contradiction_same_polarity():
    from cctx.harvest import check_contradictions
    sections = [
        ("## A", "Always use tabs."),
        ("## B", "Always use spaces."),
    ]
    assert check_contradictions(sections) == []


def test_no_contradiction_different_subjects():
    from cctx.harvest import check_contradictions
    sections = [
        ("## A", "Always use tabs."),
        ("## B", "Never import numpy."),
    ]
    assert check_contradictions(sections) == []


def test_contradiction_severity_is_high():
    from cctx.harvest import CheckSeverity, check_contradictions
    sections = [
        ("## A", "Always use tabs."),
        ("## B", "Never use tabs."),
    ]
    findings = check_contradictions(sections)
    assert findings[0].severity is CheckSeverity.HIGH


# ---------------------------------------------------------------------------
# check_redundancy unit tests
# ---------------------------------------------------------------------------

def test_redundancy_detected_similar_sections():
    from cctx.harvest import CheckIssue, check_redundancy
    body = "stop retrying after two failures diagnose before retrying"
    sections = [
        ("## Retry discipline", body),
        ("## Failure handling", body),
    ]
    findings = check_redundancy(sections)
    assert len(findings) == 1
    assert findings[0].issue is CheckIssue.REDUNDANCY


def test_no_redundancy_different_sections():
    from cctx.harvest import check_redundancy
    sections = [
        ("## Retry discipline", "stop retrying after two failures diagnose before"),
        ("## Scope creep", "finish stated task before picking up anything else"),
    ]
    assert check_redundancy(sections) == []


def test_short_section_not_eligible():
    from cctx.harvest import check_redundancy
    sections = [
        ("## A", "stop retry"),           # 2 words after stopword removal — not eligible
        ("## B", "stop retry"),
    ]
    assert check_redundancy(sections) == []


def test_redundancy_severity_is_medium():
    from cctx.harvest import CheckSeverity, check_redundancy
    body = "stop retrying after two failures diagnose before retrying"
    sections = [
        ("## A", body),
        ("## B", body),
    ]
    findings = check_redundancy(sections)
    assert findings[0].severity is CheckSeverity.MEDIUM
