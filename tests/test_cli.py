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


# ---------------------------------------------------------------------------
# --top N tests (#75)
# ---------------------------------------------------------------------------


def test_top_requires_since(runner, session_jsonl):
    """--top without --since → non-zero exit (UsageError)."""
    from cctx.cli import cli

    result = runner.invoke(cli, ["autopsy", str(session_jsonl), "--top", "3"])
    assert result.exit_code != 0
    assert "since" in result.output.lower() or "Error" in result.output


def test_top_with_since_accepted(runner, tmp_path):
    """--top N with --since → exit 0."""
    from cctx.cli import cli

    project_dir = tmp_path / "-Users-test-Projects-demo"
    project_dir.mkdir()
    session_id = "top-test-sess"
    line = {
        "type": "user", "uuid": f"{session_id}-u1", "parentUuid": None,
        "isSidechain": False, "timestamp": "2026-05-14T10:00:00.000Z",
        "sessionId": session_id, "version": "2.1.138",
        "cwd": "/Users/test/Projects/demo", "gitBranch": "main",
        "userType": "external", "entrypoint": "cli",
        "message": {"role": "user", "content": "hello"},
    }
    (project_dir / f"{session_id}.jsonl").write_text(json.dumps(line) + "\n")

    result = runner.invoke(
        cli, ["autopsy", str(project_dir), "--since", "7", "--top", "2"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# --turn N tests (#76)
# ---------------------------------------------------------------------------


def test_turn_incompatible_with_since(runner, tmp_path):
    """--turn N + --since → non-zero exit (UsageError)."""
    from cctx.cli import cli

    project_dir = tmp_path / "-Users-test-Projects-demo"
    project_dir.mkdir()
    result = runner.invoke(
        cli, ["autopsy", str(project_dir), "--since", "7", "--turn", "3"],
    )
    assert result.exit_code != 0
    assert "since" in result.output.lower() or "Error" in result.output


def test_turn_shows_turn_details(runner, session_jsonl):
    """--turn 1 on a session with one turn prints turn details."""
    from cctx.cli import cli

    result = runner.invoke(
        cli, ["autopsy", str(session_jsonl), "--turn", "1"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Turn 1" in result.output


def test_turn_out_of_range_shows_not_found(runner, session_jsonl):
    """--turn 999 on a one-turn session shows 'not found' message."""
    from cctx.cli import cli

    result = runner.invoke(
        cli, ["autopsy", str(session_jsonl), "--turn", "999"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "not found" in result.output.lower() or "999" in result.output


# ---------------------------------------------------------------------------
# --until DATE tests (#77)
# ---------------------------------------------------------------------------


def test_until_requires_since(runner, session_jsonl):
    """--until without --since → non-zero exit (UsageError)."""
    from cctx.cli import cli

    result = runner.invoke(cli, ["autopsy", str(session_jsonl), "--until", "2026-05-15"])
    assert result.exit_code != 0
    assert "since" in result.output.lower() or "Error" in result.output


def test_until_with_since_accepted(runner, tmp_path):
    """--until DATE + --since → exit 0."""
    from cctx.cli import cli

    project_dir = tmp_path / "-Users-test-Projects-demo"
    project_dir.mkdir()
    session_id = "until-test-sess"
    line = {
        "type": "user", "uuid": f"{session_id}-u1", "parentUuid": None,
        "isSidechain": False, "timestamp": "2026-05-14T10:00:00.000Z",
        "sessionId": session_id, "version": "2.1.138",
        "cwd": "/Users/test/Projects/demo", "gitBranch": "main",
        "userType": "external", "entrypoint": "cli",
        "message": {"role": "user", "content": "hello"},
    }
    (project_dir / f"{session_id}.jsonl").write_text(json.dumps(line) + "\n")

    result = runner.invoke(
        cli,
        ["autopsy", str(project_dir), "--since", "7", "--until", "2026-05-15"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0


def test_until_invalid_date(runner, tmp_path):
    """--until with a non-date string → non-zero exit."""
    from cctx.cli import cli

    project_dir = tmp_path / "-Users-test-Projects-demo"
    project_dir.mkdir()

    result = runner.invoke(
        cli, ["autopsy", str(project_dir), "--since", "7", "--until", "not-a-date"],
    )
    assert result.exit_code != 0


def test_until_label_includes_date(runner, tmp_path):
    """--until DATE appears in the period label in aggregate output."""
    from cctx.cli import cli

    project_dir = tmp_path / "-Users-test-Projects-demo"
    project_dir.mkdir()
    session_id = "until-label-sess"
    line = {
        "type": "user", "uuid": f"{session_id}-u1", "parentUuid": None,
        "isSidechain": False, "timestamp": "2026-05-10T10:00:00.000Z",
        "sessionId": session_id, "version": "2.1.138",
        "cwd": "/Users/test/Projects/demo", "gitBranch": "main",
        "userType": "external", "entrypoint": "cli",
        "message": {"role": "user", "content": "hello"},
    }
    (project_dir / f"{session_id}.jsonl").write_text(json.dumps(line) + "\n")

    result = runner.invoke(
        cli,
        ["autopsy", str(project_dir), "--since", "30", "--until", "2026-05-15"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "2026-05-15" in result.output


# ---------------------------------------------------------------------------
# autopsy --json tests (#78)
# ---------------------------------------------------------------------------


def test_autopsy_json_outputs_valid_json(runner, session_jsonl):
    """--json flag produces valid JSON on stdout."""
    from cctx.cli import cli

    result = runner.invoke(
        cli, ["autopsy", str(session_jsonl), "--json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "session_id" in data
    assert "findings" in data


def test_autopsy_json_aggregate_outputs_valid_json(runner, tmp_path):
    """--json + --since → valid aggregate JSON with expected top-level keys."""
    from cctx.cli import cli

    project_dir = tmp_path / "-Users-test-Projects-demo"
    project_dir.mkdir()

    session_id = "json-agg-test-01"
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
    (project_dir / f"{session_id}.jsonl").write_text(json.dumps(line) + "\n")

    result = runner.invoke(
        cli, ["autopsy", str(project_dir), "--since", "7", "--json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "sessions_analysed" in data
    assert "total_cost_usd" in data
    assert "waste_cost_usd" in data
    assert "by_kind" in data
    assert "patches" in data
    assert "project_patterns" in data


def test_autopsy_json_contains_cost(runner, session_jsonl):
    """--json output includes cost fields."""
    from cctx.cli import cli

    result = runner.invoke(
        cli, ["autopsy", str(session_jsonl), "--json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "total_cost_usd" in data
    assert "waste_cost_usd" in data


# ---------------------------------------------------------------------------
# export --format json tests (#79)
# ---------------------------------------------------------------------------


def test_export_json_produces_valid_json(runner, session_jsonl):
    """export --format json produces a valid JSON array."""
    from cctx.cli import cli

    result = runner.invoke(
        cli, ["export", str(session_jsonl), "--format", "json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 1
    assert "session_id" in data[0]


def test_export_json_to_file(runner, session_jsonl, tmp_path):
    """export --format json --out FILE writes a valid JSON file."""
    from cctx.cli import cli

    out_path = tmp_path / "out.json"
    result = runner.invoke(
        cli, ["export", str(session_jsonl), "--format", "json", "--out", str(out_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    data = json.loads(out_path.read_text())
    assert isinstance(data, list)
    assert data[0]["session_id"] == "test-sess-01"


# ---------------------------------------------------------------------------
# project-specific patterns in --since output (#81)
# ---------------------------------------------------------------------------


def _write_pnpm_session(project_dir: Path, session_id: str) -> None:
    """Write a session JSONL with the pnpm install → pnpm --filter failure/fix pattern."""
    import json as _json
    lines = [
        {
            "type": "user", "uuid": f"{session_id}-u1", "parentUuid": None,
            "isSidechain": False, "timestamp": "2026-05-14T10:00:00.000Z",
            "sessionId": session_id, "version": "2.1.138",
            "cwd": "/Users/test/Projects/demo", "gitBranch": "main",
            "userType": "external", "entrypoint": "cli",
            "message": {"role": "user", "content": "build the project"},
        },
        {
            "type": "assistant", "uuid": f"{session_id}-a1",
            "parentUuid": f"{session_id}-u1", "isSidechain": False,
            "timestamp": "2026-05-14T10:00:01.000Z",
            "sessionId": session_id,
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": f"{session_id}-tu1",
                              "name": "Bash", "input": {"command": "pnpm install"}}],
                "model": "claude-sonnet-4-6", "stop_reason": "tool_use",
                "usage": {"input_tokens": 100, "output_tokens": 5,
                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            },
        },
        {
            "type": "user", "uuid": f"{session_id}-r1",
            "parentUuid": f"{session_id}-a1", "isSidechain": False,
            "timestamp": "2026-05-14T10:00:02.000Z",
            "sessionId": session_id,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"{session_id}-tu1",
                 "content": "Error: workspace required", "is_error": True}
            ]},
        },
        {
            "type": "assistant", "uuid": f"{session_id}-a2",
            "parentUuid": f"{session_id}-r1", "isSidechain": False,
            "timestamp": "2026-05-14T10:00:03.000Z",
            "sessionId": session_id,
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": f"{session_id}-tu2",
                              "name": "Bash", "input": {"command": "pnpm install"}}],
                "model": "claude-sonnet-4-6", "stop_reason": "tool_use",
                "usage": {"input_tokens": 120, "output_tokens": 5,
                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            },
        },
        {
            "type": "user", "uuid": f"{session_id}-r2",
            "parentUuid": f"{session_id}-a2", "isSidechain": False,
            "timestamp": "2026-05-14T10:00:04.000Z",
            "sessionId": session_id,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"{session_id}-tu2",
                 "content": "Error: workspace required", "is_error": True}
            ]},
        },
        {
            "type": "assistant", "uuid": f"{session_id}-a3",
            "parentUuid": f"{session_id}-r2", "isSidechain": False,
            "timestamp": "2026-05-14T10:00:05.000Z",
            "sessionId": session_id,
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": f"{session_id}-tu3",
                              "name": "Bash", "input": {"command": "pnpm --filter app build"}}],
                "model": "claude-sonnet-4-6", "stop_reason": "tool_use",
                "usage": {"input_tokens": 130, "output_tokens": 5,
                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            },
        },
        {
            "type": "user", "uuid": f"{session_id}-r3",
            "parentUuid": f"{session_id}-a3", "isSidechain": False,
            "timestamp": "2026-05-14T10:00:06.000Z",
            "sessionId": session_id,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"{session_id}-tu3",
                 "content": "Done", "is_error": False}
            ]},
        },
    ]
    path = project_dir / f"{session_id}.jsonl"
    path.write_text("\n".join(_json.dumps(ln) for ln in lines) + "\n")


def test_autopsy_since_shows_project_patterns(runner, tmp_path):
    """--since with 3 sessions containing pnpm pattern → project patterns in output."""
    from cctx.cli import cli

    project_dir = tmp_path / "-Users-test-Projects-demo"
    project_dir.mkdir()
    for i in range(3):
        _write_pnpm_session(project_dir, f"pnpm-sess-{i:02d}")

    result = runner.invoke(
        cli, ["autopsy", str(project_dir), "--since", "7"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Sessions:" in result.output
    assert "Project-specific patterns" in result.output


def test_autopsy_since_two_sessions_no_project_pattern(runner, tmp_path):
    """--since with only 2 matching sessions → no project patterns table."""
    from cctx.cli import cli

    project_dir = tmp_path / "-Users-test-Projects-demo"
    project_dir.mkdir()
    for i in range(2):
        _write_pnpm_session(project_dir, f"pnpm-sess-{i:02d}")

    result = runner.invoke(
        cli, ["autopsy", str(project_dir), "--since", "7"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Project-specific patterns" not in result.output


# ---------------------------------------------------------------------------
# _complete_project — shell completion moved from discovery.py to cli.py (#134)
# ---------------------------------------------------------------------------


def test_complete_project_filters_by_incomplete(monkeypatch):
    from pathlib import Path

    from cctx import discovery
    from cctx.cli import _complete_project
    from cctx.discovery import ProjectInfo

    projects = [
        ProjectInfo(project_dir=Path("/x/-a-cctx"), display_name="~/Projects/cctx", sessions=[]),
        ProjectInfo(project_dir=Path("/x/-a-other"), display_name="~/Projects/other", sessions=[]),
    ]
    monkeypatch.setattr(discovery, "list_projects", lambda: projects)

    values = [item.value for item in _complete_project(None, None, "cctx")]
    assert any("cctx" in v for v in values)
    assert all("other" not in v for v in values)


def test_complete_project_returns_empty_on_error(monkeypatch):
    from cctx import discovery
    from cctx.cli import _complete_project

    def boom():
        raise RuntimeError("no projects dir")

    monkeypatch.setattr(discovery, "list_projects", boom)
    assert _complete_project(None, None, "x") == []
