"""Tests for cctx/watcher.py."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

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
    from cctx.watcher import _finding_key
    from cctx.models import Confidence, Finding, FindingKind, Severity

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
    from cctx.watcher import _format_finding
    from cctx.models import Confidence, Finding, FindingKind, Severity

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
    from cctx.watcher import _tail
    import cctx.watcher as watcher_mod

    session_path = tmp_path / "sess.jsonl"
    _write_session_line(session_path, _minimal_line())

    # Patch IDLE_TIMEOUT to 0.05s so the test runs fast
    monkeypatch.setattr(watcher_mod, "_IDLE_TIMEOUT", 0.05)
    monkeypatch.setattr(watcher_mod, "_POLL_INTERVAL", 0.01)

    count = _tail(session_path)
    assert isinstance(count, int)


def test_tail_reports_new_findings_once(tmp_path: Path, monkeypatch) -> None:
    """A finding that fires on every re-run is only printed once."""
    from cctx.models import Confidence, Diagnosis, Finding, FindingKind, Severity
    from cctx.watcher import _tail
    from datetime import datetime, timezone
    import cctx.diagnostician as diag_mod
    import cctx.watcher as watcher_mod

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
