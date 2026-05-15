"""Tests for cctx/diagnostician/aggregate.py."""
from __future__ import annotations

import json
from datetime import timedelta, timezone
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


def test_run_returns_diagnoses_for_sessions_in_window(tmp_path):
    from cctx.diagnostician.aggregate import run

    _write_session(tmp_path, "session-a")
    _write_session(tmp_path, "session-b")

    diagnoses = run(tmp_path, window=timedelta(days=7))
    assert len(diagnoses) == 2
    session_ids = {d.session_id for d in diagnoses}
    assert "session-a" in session_ids
    assert "session-b" in session_ids


def test_run_excludes_old_sessions(tmp_path):
    from cctx.diagnostician.aggregate import run

    path = _write_session(tmp_path, "old-session")
    # Backdate mtime by 10 days
    import os
    import time
    old_time = time.time() - 10 * 86400
    os.utime(path, (old_time, old_time))

    _write_session(tmp_path, "new-session")

    diagnoses = run(tmp_path, window=timedelta(days=7))
    assert len(diagnoses) == 1
    assert diagnoses[0].session_id == "new-session"


def test_run_empty_dir(tmp_path):
    from cctx.diagnostician.aggregate import run

    assert run(tmp_path, window=timedelta(days=7)) == []
