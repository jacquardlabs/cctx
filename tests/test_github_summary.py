"""Tests for cctx/renderers/github.py and --github-summary CLI flag."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from io import StringIO


def _make_finding(kind_str: str = "retry_loop", cost: float | None = None):
    from cctx.models import Confidence, Finding, FindingKind, Severity

    kind_map = {
        "retry_loop":    FindingKind.RETRY_LOOP,
        "stale_context": FindingKind.STALE_CONTEXT,
        "tool_thrash":   FindingKind.TOOL_THRASH,
        "dead_end":      FindingKind.DEAD_END,
    }
    return Finding(
        kind=kind_map[kind_str],
        severity=Severity.MEDIUM,
        confidence=Confidence.HIGH,
        first_turn=3,
        last_turn=7,
        evidence={},
        cost_usd=cost,
        summary=f"test {kind_str} summary",
    )


def _make_diagnosis(findings=None, patches=None):
    from cctx.models import Diagnosis

    return Diagnosis(
        session_id="deadbeef1234",
        findings=findings or [],
        inflection_turn=3 if findings else None,
        patches=patches or [],
        total_cost_usd=3.50,
        waste_cost_usd=sum(f.cost_usd or 0 for f in (findings or [])),
        analysed_at=datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# render_github_summary unit tests
# ---------------------------------------------------------------------------

def test_clean_session_no_table():
    from cctx.renderers.github import render_github_summary

    md = render_github_summary(_make_diagnosis())
    assert "Clean session" in md
    assert "deadbeef1234" in md
    assert "|" not in md  # no findings table


def test_session_id_in_output():
    from cctx.renderers.github import render_github_summary

    md = render_github_summary(_make_diagnosis([_make_finding()]))
    assert "deadbeef1234" in md


def test_findings_table_present():
    from cctx.renderers.github import render_github_summary

    md = render_github_summary(_make_diagnosis([_make_finding("retry_loop")]))
    assert "| Severity |" in md
    assert "Retry Loop" in md


def test_finding_severity_emoji():
    from cctx.renderers.github import render_github_summary
    from cctx.models import Confidence, Finding, FindingKind, Severity

    f = Finding(
        kind=FindingKind.TOOL_THRASH,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=1,
        last_turn=5,
        evidence={},
        cost_usd=None,
        summary="lots of reads",
    )
    md = render_github_summary(_make_diagnosis([f]))
    assert "🔴" in md


def test_cost_shown_with_tilde():
    from cctx.renderers.github import render_github_summary

    md = render_github_summary(_make_diagnosis())
    assert "~$3.50" in md


def test_patch_diff_shown():
    from cctx.models import FindingKind, Patch

    patch = Patch(
        target_file="CLAUDE.md",
        description="Add rule",
        unified_diff="+## Retry discipline\n+Stop after two failures.",
        finding_kind=FindingKind.RETRY_LOOP,
        evidence_summary="2 sessions",
    )
    from cctx.renderers.github import render_github_summary

    md = render_github_summary(_make_diagnosis([_make_finding()], patches=[patch]))
    assert "Retry discipline" in md
    assert "```diff" in md


# ---------------------------------------------------------------------------
# write_github_summary integration
# ---------------------------------------------------------------------------

def test_write_writes_to_step_summary(tmp_path):
    from cctx.renderers.github import write_github_summary

    summary_file = tmp_path / "step_summary.md"
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary_file)}

    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-c",
         "import os; os.environ['GITHUB_STEP_SUMMARY'] = '" + str(summary_file) + "';"
         "from cctx.renderers.github import write_github_summary;"
         "from tests.test_github_summary import _make_diagnosis;"
         "write_github_summary(_make_diagnosis())"],
        capture_output=True, text=True,
        env={**os.environ, "GITHUB_STEP_SUMMARY": str(summary_file), "CCTX_OFFLINE": "1"},
    )
    assert result.returncode == 0
    assert summary_file.exists()
    content = summary_file.read_text()
    assert "deadbeef1234" in content or "Clean session" in content


def test_write_warns_when_env_not_set(capsys):
    from cctx.renderers.github import write_github_summary

    env_backup = os.environ.pop("GITHUB_STEP_SUMMARY", None)
    try:
        write_github_summary(_make_diagnosis())
        captured = capsys.readouterr()
        assert "GITHUB_STEP_SUMMARY" in captured.err
    finally:
        if env_backup is not None:
            os.environ["GITHUB_STEP_SUMMARY"] = env_backup


# ---------------------------------------------------------------------------
# CLI --github-summary flag
# ---------------------------------------------------------------------------

def test_autopsy_github_summary_flag_exists():
    from click.testing import CliRunner
    from cctx.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["autopsy", "--help"])
    assert "--github-summary" in result.output


def test_autopsy_github_summary_since_incompatible(tmp_path):
    from click.testing import CliRunner
    from cctx.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["autopsy", str(tmp_path), "--since", "7d", "--github-summary"])
    assert result.exit_code != 0
    assert "not supported" in result.output.lower() or "mutually exclusive" in result.output.lower() or "not supported" in (result.exception or "")
