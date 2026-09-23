"""Every recorded Claude Code fixture must export cleanly through the CLI.

The fixtures under tests/fixtures/claude_code/ are scrubbed real sessions; the
scrubber replaces every ``*_tokens`` value with ``"[SCRUBBED]"``. Nothing else
loads them through ``cctx export``, so a parser crash on that shape went unseen.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

FIXTURES = Path(__file__).parent / "fixtures" / "claude_code"
# <slug>/<slug>.jsonl — the depth excludes <slug>/<slug>/subagents/ children.
SESSION_FILES = sorted(FIXTURES.glob("*/*.jsonl"))


def test_fixture_glob_finds_the_recorded_sessions() -> None:
    assert len(SESSION_FILES) >= 5
    assert all("subagents" not in p.parts for p in SESSION_FILES)


@pytest.mark.parametrize("session", SESSION_FILES, ids=lambda p: p.stem)
def test_export_json_exits_zero_on_fixture(
    session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cctx.cli import cli

    monkeypatch.setenv("CCTX_OFFLINE", "1")
    result = CliRunner().invoke(
        cli, ["export", str(session), "--format", "json"], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    assert isinstance(json.loads(result.output), list)
