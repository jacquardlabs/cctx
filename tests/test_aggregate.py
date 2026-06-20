"""Tests for cctx/aggregate.py."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc


def _write_session(tmp_path: Path, session_id: str, model: str = "claude-sonnet-4-6") -> Path:
    """Write a minimal valid session JSONL to tmp_path."""
    lines = [
        {
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
            "message": {"role": "user", "content": "do the thing"},
        }
    ]
    path = tmp_path / f"{session_id}.jsonl"
    with path.open("w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return path


def _now_and_window(days: int) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    return now - timedelta(days=days), now


def test_run_returns_diagnoses_for_sessions_in_window(tmp_path):
    from cctx.aggregate import run

    _write_session(tmp_path, "session-a")
    _write_session(tmp_path, "session-b")

    start, end = _now_and_window(7)
    pairs = run(tmp_path, start, end)
    assert len(pairs) == 2
    diagnoses = [d for d, _ in pairs]
    session_ids = {d.session_id for d in diagnoses}
    assert "session-a" in session_ids
    assert "session-b" in session_ids


def test_run_excludes_old_sessions(tmp_path):
    from cctx.aggregate import run

    path = _write_session(tmp_path, "old-session")
    old_time = time.time() - 10 * 86400
    os.utime(path, (old_time, old_time))

    _write_session(tmp_path, "new-session")

    start, end = _now_and_window(7)
    pairs = run(tmp_path, start, end)
    assert len(pairs) == 1
    assert pairs[0][0].session_id == "new-session"


def test_run_empty_dir(tmp_path):
    from cctx.aggregate import run

    start, end = _now_and_window(7)
    assert run(tmp_path, start, end) == []
