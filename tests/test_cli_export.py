"""CLI integration tests for the cctx export subcommand."""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def session_jsonl(tmp_path):
    """Minimal valid single-turn session JSONL."""
    session_id = "test-export-sess-01"
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


def test_export_help(runner: CliRunner) -> None:
    """cctx export --help exits 0 and mentions format."""
    from cctx.cli import cli

    result = runner.invoke(cli, ["export", "--help"])
    assert result.exit_code == 0
    assert "format" in result.output.lower() or "jsonl" in result.output.lower()


def test_export_jsonl_runs(runner: CliRunner, session_jsonl) -> None:
    """cctx export <file> --format jsonl exits 0."""
    from cctx.cli import cli

    result = runner.invoke(
        cli, ["export", str(session_jsonl), "--format", "jsonl"], catch_exceptions=False
    )
    assert result.exit_code == 0


def test_export_jsonl_output_is_valid_json(runner: CliRunner, session_jsonl) -> None:
    """cctx export <file> --format jsonl emits at least one valid JSON line."""
    from cctx.cli import cli

    result = runner.invoke(
        cli, ["export", str(session_jsonl), "--format", "jsonl"], catch_exceptions=False
    )
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert len(lines) >= 1
    obj = json.loads(lines[0])
    assert "session_id" in obj


def test_export_csv_runs(runner: CliRunner, session_jsonl) -> None:
    """cctx export <file> --format csv exits 0."""
    from cctx.cli import cli

    result = runner.invoke(
        cli, ["export", str(session_jsonl), "--format", "csv"], catch_exceptions=False
    )
    assert result.exit_code == 0


def test_export_csv_output_has_header(runner: CliRunner, session_jsonl) -> None:
    """cctx export <file> --format csv emits a CSV header."""
    from cctx.cli import cli

    result = runner.invoke(
        cli, ["export", str(session_jsonl), "--format", "csv"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert "session_id" in result.output


def test_export_out_file_jsonl(runner: CliRunner, session_jsonl, tmp_path) -> None:
    """--out writes JSONL to a file instead of stdout."""
    from cctx.cli import cli

    out_file = tmp_path / "output.jsonl"
    result = runner.invoke(
        cli,
        ["export", str(session_jsonl), "--format", "jsonl", "--out", str(out_file)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    # stdout should be empty (or minimal)
    assert "session_id" not in result.output
    # file should contain the data
    content = out_file.read_text()
    lines = [ln for ln in content.splitlines() if ln.strip()]
    assert len(lines) >= 1
    obj = json.loads(lines[0])
    assert "session_id" in obj


def test_export_out_file_csv(runner: CliRunner, session_jsonl, tmp_path) -> None:
    """--out writes CSV to a file instead of stdout."""
    from cctx.cli import cli

    out_file = tmp_path / "output.csv"
    result = runner.invoke(
        cli,
        ["export", str(session_jsonl), "--format", "csv", "--out", str(out_file)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    content = out_file.read_text()
    assert "session_id" in content


def test_export_no_content_flag(runner: CliRunner, session_jsonl) -> None:
    """--no-content flag is accepted and exits 0."""
    from cctx.cli import cli

    result = runner.invoke(
        cli,
        ["export", str(session_jsonl), "--format", "jsonl", "--no-content"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0


def test_export_missing_file(runner: CliRunner, tmp_path) -> None:
    """export with nonexistent file exits non-zero."""
    from cctx.cli import cli

    result = runner.invoke(cli, ["export", str(tmp_path / "no-such.jsonl")])
    assert result.exit_code != 0


def test_export_default_format_is_jsonl(runner: CliRunner, session_jsonl) -> None:
    """When --format is omitted, default is jsonl (output contains JSON)."""
    from cctx.cli import cli

    result = runner.invoke(cli, ["export", str(session_jsonl)], catch_exceptions=False)
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert len(lines) >= 1
    # Should parse as JSON
    json.loads(lines[0])
