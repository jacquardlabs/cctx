"""Tests for cctx/cli.py — autopsy command."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def session_jsonl(tmp_path):
    """Minimal valid session JSONL."""
    session_id = "test-sess-01"
    line = {
        "type": "user",
        "uuid": f"{session_id}-u1",
        "parentUuid": None,
        "isSidechain": False,
        "timestamp": "2026-05-14T10:00:00.000Z",
        "sessionId": session_id,
        "version": "2.1.138",
        "cwd": "/Users/test/Projects/demo",
        "gitBranch": "main",
        "userType": "external",
        "entrypoint": "cli",
        "message": {"role": "user", "content": "hello"},
    }
    path = tmp_path / f"{session_id}.jsonl"
    path.write_text(json.dumps(line) + "\n")
    return path


def test_autopsy_help(runner):
    from cctx.cli import cli

    result = runner.invoke(cli, ["autopsy", "--help"])
    assert result.exit_code == 0
    assert "autopsy" in result.output.lower() or "session" in result.output.lower()


def test_autopsy_runs_on_session_file(runner, session_jsonl):
    from cctx.cli import cli

    result = runner.invoke(cli, ["autopsy", str(session_jsonl)], catch_exceptions=False)
    assert result.exit_code == 0
    # Should show session id or "No findings"
    assert "test-sess-01" in result.output or "No findings" in result.output


def test_autopsy_missing_file(runner, tmp_path):
    from cctx.cli import cli

    result = runner.invoke(cli, ["autopsy", str(tmp_path / "nonexistent.jsonl")])
    assert result.exit_code != 0


def test_cli_entrypoint_exists(runner):
    from cctx.cli import cli

    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0


def test_autopsy_since_runs_on_project_dir(runner, tmp_path):
    """Cross-session --since path: project dir with one valid JSONL → exit 0."""
    import json

    from cctx.cli import cli

    # project_dir name doesn't matter for aggregate.run; it just globs *.jsonl
    project_dir = tmp_path / "-Users-test-Projects-demo"
    project_dir.mkdir()

    session_id = "since-test-sess-01"
    line = {
        "type": "user",
        "uuid": f"{session_id}-u1",
        "parentUuid": None,
        "isSidechain": False,
        "timestamp": "2026-05-14T10:00:00.000Z",
        "sessionId": session_id,
        "version": "2.1.138",
        "cwd": "/Users/test/Projects/demo",
        "gitBranch": "main",
        "userType": "external",
        "entrypoint": "cli",
        "message": {"role": "user", "content": "hello"},
    }
    session_path = project_dir / f"{session_id}.jsonl"
    session_path.write_text(json.dumps(line) + "\n")

    result = runner.invoke(
        cli, ["autopsy", str(project_dir), "--since", "7"], catch_exceptions=False
    )
    assert result.exit_code == 0
    # The aggregate header always shows sessions analysed
    assert "Sessions:" in result.output or "day" in result.output.lower()


# ---------------------------------------------------------------------------
# parse_since tests
# ---------------------------------------------------------------------------

def test_parse_since_integer():
    from cctx.cli import parse_since
    start, end, label = parse_since("7")
    assert label == "last 7 days"
    assert (end - start).days == 7


def test_parse_since_days_suffix():
    from cctx.cli import parse_since
    start, end, label = parse_since("14d")
    assert label == "last 14 days"
    assert (end - start).days == 14


def test_parse_since_weeks_suffix():
    from cctx.cli import parse_since
    start, end, label = parse_since("2w")
    assert label == "last 14 days"
    assert (end - start).days == 14


def test_parse_since_absolute_date():
    from datetime import timezone

    from cctx.cli import parse_since
    start, end, label = parse_since("2026-05-01")
    assert start.year == 2026 and start.month == 5 and start.day == 1
    assert start.tzinfo == timezone.utc
    assert "2026-05-01" in label


def test_parse_since_date_range():

    from cctx.cli import parse_since
    start, end, label = parse_since("2026-05-01..2026-05-15")
    assert start.year == 2026 and start.month == 5 and start.day == 1
    assert end.year == 2026 and end.month == 5 and end.day == 15
    assert "2026-05-01" in label and "2026-05-15" in label


def test_parse_since_invalid():
    import click
    import pytest

    from cctx.cli import parse_since
    with pytest.raises(click.UsageError):
        parse_since("not-a-date")


# ---------------------------------------------------------------------------
# aggregate drilldown tests
# ---------------------------------------------------------------------------

def test_aggregate_drilldown_non_interactive(tmp_path, monkeypatch):
    """In non-TTY mode (piped), _aggregate_drilldown exits without prompting."""
    import sys

    from cctx.cli import _aggregate_drilldown
    from cctx.models import AggregateReport, FindingKind, KindEvidence

    by_kind = {FindingKind.RETRY_LOOP: KindEvidence(FindingKind.RETRY_LOOP, 1, 0.1, [])}
    report = AggregateReport(
        period_label="last 7 days",
        sessions_analysed=1,
        sessions_with_findings=1,
        total_cost_usd=1.0,
        waste_cost_usd=0.1,
        by_kind=by_kind,
        patches=[],
    )
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    # Should not raise or prompt; returns None
    assert _aggregate_drilldown(report, []) is None


def test_aggregate_drilldown_no_kinds_skips():
    """Empty by_kind → no prompt regardless of TTY state."""
    from cctx.cli import _aggregate_drilldown
    from cctx.models import AggregateReport

    report = AggregateReport(
        period_label="last 7 days",
        sessions_analysed=0,
        sessions_with_findings=0,
        total_cost_usd=0.0,
        waste_cost_usd=0.0,
        by_kind={},
        patches=[],
    )
    assert _aggregate_drilldown(report, []) is None


def test_render_aggregate_drilldown_output():
    """render_aggregate_drilldown shows per-session findings for the selected kind."""
    from datetime import datetime, timezone
    from io import StringIO

    from rich.console import Console

    from cctx.models import (
        Confidence,
        Diagnosis,
        Finding,
        FindingKind,
        Severity,
    )
    from cctx.renderers.terminal import render_aggregate_drilldown

    finding = Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=Severity.MEDIUM,
        confidence=Confidence.HIGH,
        first_turn=2,
        last_turn=4,
        evidence={},
        cost_usd=None,
        summary="Edit(foo.py) failed 2× between turns 2–4",
    )
    diag = Diagnosis(
        session_id="aabbccdd",
        findings=[finding],
        inflection_turn=2,
        patches=[],
        total_cost_usd=1.50,
        waste_cost_usd=0.0,
        analysed_at=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )
    buf = StringIO()
    console = Console(file=buf, width=120, highlight=False, markup=False)
    render_aggregate_drilldown([diag], FindingKind.RETRY_LOOP, console=console)
    output = buf.getvalue()
    assert "aabbccdd" in output
    assert "failed" in output.lower() or "Edit" in output


# ---------------------------------------------------------------------------
# --fail-on-findings tests
# ---------------------------------------------------------------------------

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "claude_code" / "short-clean" / "short-clean.jsonl"
)


def test_fail_on_findings_clean_session_exits_0(runner):
    """--fail-on-findings on a clean session exits 0."""
    from cctx.cli import cli

    result = runner.invoke(
        cli,
        ["autopsy", str(FIXTURE_PATH), "--fail-on-findings"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0


def test_fail_on_findings_with_findings_exits_1(runner, session_jsonl, monkeypatch):
    """--fail-on-findings exits 1 when the diagnosis has findings."""
    from datetime import datetime, timezone

    from cctx import diagnostician
    from cctx.models import Confidence, Diagnosis, Finding, FindingKind, Severity

    finding = Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=1,
        last_turn=2,
        evidence={},
        cost_usd=None,
        summary="Edit(foo.py) failed 3× between turns 1–2",
    )
    diag_with_findings = Diagnosis(
        session_id="test-sess-01",
        findings=[finding],
        inflection_turn=1,
        patches=[],
        total_cost_usd=0.0,
        waste_cost_usd=0.0,
        analysed_at=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(diagnostician, "run", lambda trace: diag_with_findings)

    from cctx.cli import cli

    result = runner.invoke(
        cli,
        ["autopsy", str(session_jsonl), "--fail-on-findings"],
    )
    assert result.exit_code == 1


def test_fail_on_findings_incompatible_with_since(runner):
    """--fail-on-findings + --since → non-zero exit (UsageError)."""
    from cctx.cli import cli

    result = runner.invoke(
        cli,
        ["autopsy", str(FIXTURE_PATH.parent), "--since", "7", "--fail-on-findings"],
    )
    assert result.exit_code != 0
