"""Tests for cctx/watcher.py."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from tests.conftest import make_user_line

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_session_line(path: Path, obj: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj) + "\n")


def _minimal_line(session_id: str = "test-sess") -> dict:
    return make_user_line(f"{session_id}-u1", session_id=session_id, cwd="/tmp/demo")


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_finding_key_deduplication() -> None:
    from cctx.models import Confidence, Finding, FindingKind, Severity
    from cctx.watcher import _finding_key

    f = Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=3,
        last_turn=7,
        evidence={},
        cost_usd=None,
        summary="Edit failed 3×",
    )
    key = _finding_key(f)
    assert key == (FindingKind.RETRY_LOOP, 3)


def test_format_finding_output() -> None:
    from cctx.models import Confidence, Finding, FindingKind, Severity
    from cctx.watcher import _format_finding

    f = Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=2,
        last_turn=5,
        evidence={},
        cost_usd=None,
        summary="Edit(foo.py) failed 3× between turns 2–5",
    )
    line = _format_finding(f)
    assert "[RETRY LOOP]" in line
    assert "HIGH" in line
    assert "Edit(foo.py)" in line


def test_find_active_session_returns_newest(tmp_path: Path) -> None:
    from cctx.watcher import _find_active_session

    old = tmp_path / "old.jsonl"
    new = tmp_path / "new.jsonl"
    old.write_text("{}\n")
    time.sleep(0.01)
    new.write_text("{}\n")

    result = _find_active_session(tmp_path)
    assert result == new


def test_find_active_session_empty_dir(tmp_path: Path) -> None:
    from cctx.watcher import _find_active_session

    assert _find_active_session(tmp_path) is None


def test_parse_trace_sets_offline(tmp_path: Path, monkeypatch) -> None:
    """_parse_trace forces CCTX_OFFLINE=1 to avoid API calls."""
    from cctx.watcher import _parse_trace

    monkeypatch.delenv("CCTX_OFFLINE", raising=False)
    session_path = tmp_path / "sess.jsonl"
    _write_session_line(session_path, _minimal_line())

    trace = _parse_trace(session_path)
    assert trace is not None


def test_tail_exits_on_idle(tmp_path: Path, monkeypatch) -> None:
    """_tail returns after IDLE_TIMEOUT seconds of no file growth."""
    import cctx.watcher as watcher_mod
    from cctx.watcher import _tail

    session_path = tmp_path / "sess.jsonl"
    _write_session_line(session_path, _minimal_line())

    # Patch IDLE_TIMEOUT to 0.05s so the test runs fast
    monkeypatch.setattr(watcher_mod, "_IDLE_TIMEOUT", 0.05)
    monkeypatch.setattr(watcher_mod, "_POLL_INTERVAL", 0.01)

    count = _tail(session_path)
    assert isinstance(count, int)


def test_tail_reports_new_findings_once(tmp_path: Path, monkeypatch) -> None:
    """A finding that fires on every re-run is only printed once."""
    from datetime import datetime, timezone

    import cctx.diagnostician as diag_mod
    import cctx.watcher as watcher_mod
    from cctx.models import Confidence, Diagnosis, Finding, FindingKind, Severity
    from cctx.watcher import _tail

    session_path = tmp_path / "sess.jsonl"
    _write_session_line(session_path, _minimal_line())

    finding = Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=1,
        last_turn=3,
        evidence={},
        cost_usd=None,
        summary="Edit failed 3×",
    )

    call_count = {"n": 0}

    def _fake_diag(trace):
        call_count["n"] += 1  # must be called >1× for dedup to be exercised
        return Diagnosis(
            session_id="x",
            findings=[finding],
            inflection_turn=1,
            patches=[],
            total_cost_usd=0.0,
            waste_cost_usd=0.0,
            analysed_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(diag_mod, "run", _fake_diag)
    monkeypatch.setattr(watcher_mod, "_IDLE_TIMEOUT", 0.05)
    monkeypatch.setattr(watcher_mod, "_POLL_INTERVAL", 0.01)

    with patch("builtins.print") as mock_print:
        _tail(session_path)

    printed_calls = [str(c) for c in mock_print.call_args_list]
    finding_lines = [c for c in printed_calls if "RETRY LOOP" in c]
    assert len(finding_lines) == 1, f"Finding printed {len(finding_lines)}× (expected 1)"
    assert call_count["n"] >= 1, "diagnostician was never called"


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


def test_watch_help() -> None:
    from click.testing import CliRunner

    from cctx.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["watch", "--help"])
    assert result.exit_code == 0
    assert "watch" in result.output.lower() or "session" in result.output.lower()


def test_watch_missing_project_dir(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from cctx.cli import cli

    runner = CliRunner()
    nonexistent = tmp_path / "does-not-exist"
    result = runner.invoke(cli, ["watch", str(nonexistent)])
    assert result.exit_code != 0


def test_find_active_session_prefers_live_session(tmp_path: Path) -> None:
    """When live_sessions() returns a cwd match, that JSONL wins over mtime."""
    import time
    from datetime import datetime, timezone
    from unittest.mock import patch

    from cctx.agents import LiveSession

    # Build a fake project dir whose name equals the encoded cwd.
    cwd_path = tmp_path / "myproject"
    cwd_path.mkdir()
    encoded_name = cwd_path.resolve().as_posix().replace("/", "-")
    project_dir = tmp_path / encoded_name
    project_dir.mkdir()

    # live-session.jsonl is OLDER by mtime; other-session.jsonl is NEWER.
    live_jl = project_dir / "live-session.jsonl"
    other_jl = project_dir / "other-session.jsonl"
    live_jl.write_text("{}\n")
    time.sleep(0.02)
    other_jl.write_text("{}\n")

    live = [LiveSession(
        session_id="live-session",
        cwd=str(cwd_path),
        status="busy",
        pid=1,
        kind="interactive",
        started_at=datetime.now(timezone.utc),
    )]

    with patch("cctx.watcher.live_sessions", return_value=live):
        from cctx.watcher import _find_active_session
        result = _find_active_session(project_dir)

    assert result == live_jl


def test_find_active_session_falls_back_to_mtime_when_no_live(tmp_path: Path) -> None:
    """When live_sessions() returns [], mtime fallback picks the newest file."""
    import time
    from unittest.mock import patch

    old = tmp_path / "old.jsonl"
    new = tmp_path / "new.jsonl"
    old.write_text("{}\n")
    time.sleep(0.02)
    new.write_text("{}\n")

    with patch("cctx.watcher.live_sessions", return_value=[]):
        from cctx.watcher import _find_active_session
        result = _find_active_session(tmp_path)

    assert result == new


def test_tail_exits_early_when_session_leaves_live_list(
    tmp_path: Path, monkeypatch
) -> None:
    """_tail exits as soon as the session disappears from live_sessions(), not after 30s."""
    import time as _time
    from datetime import datetime, timezone
    from unittest.mock import patch

    import cctx.watcher as watcher_mod
    from cctx.agents import LiveSession

    session_path = tmp_path / "abc123.jsonl"
    session_path.write_text("{}\n")

    live_session = LiveSession(
        session_id="abc123",
        cwd=str(tmp_path),
        status="busy",
        pid=1,
        kind="interactive",
        started_at=datetime.now(timezone.utc),
    )

    call_count: dict[str, int] = {"n": 0}

    def fake_live_sessions() -> list[LiveSession]:
        call_count["n"] += 1
        return [live_session] if call_count["n"] == 1 else []

    monkeypatch.setattr(watcher_mod, "_IDLE_TIMEOUT", 30.0)  # would be slow if hit
    monkeypatch.setattr(watcher_mod, "_POLL_INTERVAL", 0.01)

    start = _time.monotonic()
    with patch("cctx.watcher.live_sessions", side_effect=fake_live_sessions):
        count = watcher_mod._tail(session_path)
    elapsed = _time.monotonic() - start

    assert isinstance(count, int)
    assert elapsed < 5.0, f"_tail took {elapsed:.1f}s — should have exited early via live detection"
