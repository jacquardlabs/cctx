"""Tests for cctx/agents.py."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

_SAMPLE_JSON = json.dumps([
    {
        "pid": 12345,
        "cwd": "/Users/user/Projects/myapp",
        "kind": "interactive",
        "startedAt": 1779239605842,
        "sessionId": "abc123de-0000-0000-0000-000000000000",
        "status": "busy",
    },
    {
        "pid": 12346,
        "cwd": "/Users/user/Projects/other",
        "kind": "background",
        "startedAt": 1779239605000,
        "sessionId": "def456gh-0000-0000-0000-000000000000",
        "status": "idle",
    },
])


def _mock_run(stdout: str, returncode: int = 0) -> MagicMock:
    mock = MagicMock()
    mock.stdout = stdout
    mock.returncode = returncode
    return mock


def test_live_sessions_parses_valid_json() -> None:
    from cctx.agents import live_sessions

    with patch("cctx.agents.subprocess.run", return_value=_mock_run(_SAMPLE_JSON)):
        result = live_sessions()

    assert len(result) == 2
    assert result[0].session_id == "abc123de-0000-0000-0000-000000000000"
    assert result[0].cwd == "/Users/user/Projects/myapp"
    assert result[0].status == "busy"
    assert result[0].pid == 12345
    assert result[0].kind == "interactive"
    assert result[1].status == "idle"
    assert result[1].kind == "background"


def test_live_sessions_returns_empty_when_claude_not_found() -> None:
    from cctx.agents import live_sessions

    with patch("cctx.agents.subprocess.run", side_effect=FileNotFoundError):
        result = live_sessions()

    assert result == []


def test_live_sessions_returns_empty_on_timeout() -> None:
    from cctx.agents import live_sessions

    with patch("cctx.agents.subprocess.run", side_effect=subprocess.TimeoutExpired(["claude"], 2)):
        result = live_sessions()

    assert result == []


def test_live_sessions_returns_empty_on_nonzero_exit() -> None:
    from cctx.agents import live_sessions

    with patch("cctx.agents.subprocess.run", return_value=_mock_run("", returncode=1)):
        result = live_sessions()

    assert result == []


def test_live_sessions_returns_empty_on_bad_json() -> None:
    from cctx.agents import live_sessions

    with patch("cctx.agents.subprocess.run", return_value=_mock_run("not valid json")):
        result = live_sessions()

    assert result == []


def test_live_sessions_skips_bad_records_keeps_good() -> None:
    from cctx.agents import live_sessions

    # First record missing required "sessionId"; second is valid.
    data = json.dumps([
        {"pid": 1, "cwd": "/foo", "startedAt": 1000000000000},
        {
            "pid": 99,
            "cwd": "/bar",
            "kind": "interactive",
            "startedAt": 1779239605842,
            "sessionId": "good-session-id",
            "status": "busy",
        },
    ])
    with patch("cctx.agents.subprocess.run", return_value=_mock_run(data)):
        result = live_sessions()

    assert len(result) == 1
    assert result[0].session_id == "good-session-id"


def test_live_sessions_returns_empty_on_non_list_json() -> None:
    from cctx.agents import live_sessions

    with patch("cctx.agents.subprocess.run", return_value=_mock_run("null")):
        result = live_sessions()

    assert result == []


def test_live_session_started_at_is_utc_datetime() -> None:
    from datetime import timezone

    from cctx.agents import live_sessions

    with patch("cctx.agents.subprocess.run", return_value=_mock_run(_SAMPLE_JSON)):
        result = live_sessions()

    assert result[0].started_at.tzinfo == timezone.utc
    # 1779239605842 ms → reasonable year
    assert result[0].started_at.year >= 2025
