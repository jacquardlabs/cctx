"""Tests for cctx/cli.py — autopsy command."""
from __future__ import annotations

import json

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
