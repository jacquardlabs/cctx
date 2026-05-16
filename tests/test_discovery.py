"""Tests for cctx.discovery — session and project discovery."""
from __future__ import annotations

import json
from pathlib import Path


def _write_jsonl(path: Path, *rows: dict) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _session_line(
    session_id: str = "abc123",
    cwd: str = "/Users/test/Projects/myapp",
    branch: str = "main",
    ts: str = "2026-05-14T10:00:00.000Z",
) -> dict:
    return {
        "type": "user",
        "uuid": f"{session_id}-u1",
        "parentUuid": None,
        "sessionId": session_id,
        "timestamp": ts,
        "cwd": cwd,
        "gitBranch": branch,
        "message": {"role": "user", "content": "hello"},
    }


# ---------------------------------------------------------------------------
# find_project_dir
# ---------------------------------------------------------------------------


def test_find_project_dir_returns_matching_encoded_dir(tmp_path):
    from cctx.discovery import find_project_dir

    cwd = Path("/Users/test/Projects/myapp")
    encoded = "Users-test-Projects-myapp"
    project_dir = tmp_path / f"-{encoded}"
    project_dir.mkdir()

    result = find_project_dir(cwd, base=tmp_path)
    assert result == project_dir


def test_find_project_dir_returns_none_when_absent(tmp_path):
    from cctx.discovery import find_project_dir

    result = find_project_dir(Path("/Users/test/Projects/missing"), base=tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


def test_list_sessions_empty_dir(tmp_path):
    from cctx.discovery import list_sessions

    assert list_sessions(tmp_path) == []


def test_list_sessions_returns_metadata(tmp_path):
    from cctx.discovery import list_sessions

    path = tmp_path / "abc123.jsonl"
    _write_jsonl(path, _session_line("abc123", ts="2026-05-14T10:00:00.000Z"))

    sessions = list_sessions(tmp_path)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.session_id == "abc123"
    assert s.cwd == "/Users/test/Projects/myapp"
    assert s.git_branch == "main"
    assert s.start_time is not None
    assert s.start_time.year == 2026


def test_list_sessions_sorted_newest_first(tmp_path):
    from cctx.discovery import list_sessions

    for sid, ts in [
        ("older", "2026-05-01T10:00:00.000Z"),
        ("newer", "2026-05-14T10:00:00.000Z"),
    ]:
        _write_jsonl(tmp_path / f"{sid}.jsonl", _session_line(sid, ts=ts))

    sessions = list_sessions(tmp_path)
    assert sessions[0].session_id == "newer"
    assert sessions[1].session_id == "older"


def test_list_sessions_tolerates_malformed_lines(tmp_path):
    from cctx.discovery import list_sessions

    path = tmp_path / "bad.jsonl"
    path.write_text("not json\n" + json.dumps(_session_line("ok")) + "\n")

    sessions = list_sessions(tmp_path)
    assert len(sessions) == 1
    assert sessions[0].session_id == "ok"


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------


def test_list_projects_empty_base(tmp_path):
    from cctx.discovery import list_projects

    assert list_projects(base=tmp_path) == []


def test_list_projects_skips_dirs_without_jsonl(tmp_path):
    from cctx.discovery import list_projects

    (tmp_path / "empty-dir").mkdir()
    assert list_projects(base=tmp_path) == []


def test_list_projects_returns_project_info(tmp_path):
    from cctx.discovery import list_projects

    proj_dir = tmp_path / "-Users-test-Projects-myapp"
    proj_dir.mkdir()
    _write_jsonl(
        proj_dir / "abc.jsonl",
        _session_line("abc", cwd="/Users/test/Projects/myapp"),
    )

    projects = list_projects(base=tmp_path)
    assert len(projects) == 1
    p = projects[0]
    assert p.session_count == 1
    assert "myapp" in p.display_name


def test_list_projects_sorted_newest_first(tmp_path):
    from cctx.discovery import list_projects

    for name, ts, cwd in [
        ("-Users-test-Projects-old", "2026-05-01T10:00:00.000Z", "/Users/test/Projects/old"),
        ("-Users-test-Projects-new", "2026-05-14T10:00:00.000Z", "/Users/test/Projects/new"),
    ]:
        d = tmp_path / name
        d.mkdir()
        _write_jsonl(d / "s.jsonl", _session_line(ts=ts, cwd=cwd))

    projects = list_projects(base=tmp_path)
    assert "new" in projects[0].display_name
    assert "old" in projects[1].display_name


# ---------------------------------------------------------------------------
# latest_session
# ---------------------------------------------------------------------------


def test_latest_session_returns_most_recent(tmp_path):
    from cctx.discovery import latest_session

    for sid, ts in [
        ("older", "2026-05-01T10:00:00.000Z"),
        ("newer", "2026-05-14T10:00:00.000Z"),
    ]:
        _write_jsonl(tmp_path / f"{sid}.jsonl", _session_line(sid, ts=ts))

    result = latest_session(tmp_path)
    assert result is not None
    assert result.stem == "newer"


def test_latest_session_returns_none_when_empty(tmp_path):
    from cctx.discovery import latest_session

    assert latest_session(tmp_path) is None


# ---------------------------------------------------------------------------
# CLI integration — ls command
# ---------------------------------------------------------------------------


def test_cli_ls_no_args(tmp_path):
    """cctx ls with no args lists projects."""
    from click.testing import CliRunner

    from cctx.cli import cli

    proj = tmp_path / "-Users-test-Projects-myapp"
    proj.mkdir()
    _write_jsonl(proj / "s.jsonl", _session_line(cwd="/Users/test/Projects/myapp"))

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["ls"],
        catch_exceptions=False,
        env={"CCTX_OFFLINE": "1", "CCTX_PROJECTS_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0
    assert "myapp" in result.output or "Projects" in result.output


def test_cli_ls_with_project(tmp_path):
    """cctx ls <project-path> lists sessions."""
    from click.testing import CliRunner

    from cctx.cli import cli

    cwd_path = tmp_path / "myapp"
    cwd_path.mkdir()
    # Encode the actual path so find_project_dir can locate it
    encoded = cwd_path.resolve().as_posix().replace("/", "-")
    projects_base = tmp_path / "projects"
    proj = projects_base / encoded
    proj.mkdir(parents=True)
    _write_jsonl(
        proj / "abc123.jsonl",
        _session_line("abc123", cwd=str(cwd_path)),
    )

    import cctx.discovery as disc
    orig = disc.claude_projects_dir
    disc.claude_projects_dir = lambda: projects_base
    try:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["ls", str(cwd_path)], catch_exceptions=False, env={"CCTX_OFFLINE": "1"}
        )
    finally:
        disc.claude_projects_dir = orig

    assert result.exit_code == 0
    assert "abc123" in result.output


def test_cli_autopsy_latest(tmp_path):
    """cctx autopsy --latest finds the most recent session."""
    import json as _json

    from click.testing import CliRunner

    from cctx.cli import cli

    cwd_path = tmp_path / "myproject"
    cwd_path.mkdir()
    proj = tmp_path / "projects" / (
        str(cwd_path.resolve()).replace("/", "-")
    )
    proj.mkdir(parents=True)

    session_id = "latest-sess-01"
    line = {
        "type": "user",
        "uuid": f"{session_id}-u1",
        "parentUuid": None,
        "isSidechain": False,
        "timestamp": "2026-05-14T10:00:00.000Z",
        "sessionId": session_id,
        "version": "2.1.138",
        "cwd": str(cwd_path),
        "gitBranch": "main",
        "userType": "external",
        "entrypoint": "cli",
        "message": {"role": "user", "content": "hello"},
    }
    (proj / f"{session_id}.jsonl").write_text(_json.dumps(line) + "\n")

    import cctx.discovery as disc
    orig = disc.claude_projects_dir
    disc.claude_projects_dir = lambda: tmp_path / "projects"
    try:
        result = runner = CliRunner()
        result = runner.invoke(
            cli,
            ["autopsy", "--latest", str(cwd_path)],
            catch_exceptions=False,
            env={"CCTX_OFFLINE": "1"},
        )
    finally:
        disc.claude_projects_dir = orig

    assert result.exit_code == 0
    assert session_id in result.output or "session" in result.output.lower()
