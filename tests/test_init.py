"""Tests for cctx init command and hook_installer module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def settings_dir(tmp_path):
    d = tmp_path / ".claude"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# hook_installer unit tests
# ---------------------------------------------------------------------------


def test_install_creates_settings_file(tmp_path, monkeypatch):
    """install() writes .claude/settings.json with the hook entry."""
    monkeypatch.chdir(tmp_path)
    from cctx import hook_installer

    result = hook_installer.install()
    path = Path(".claude/settings.json")
    assert path.exists()
    data = json.loads(path.read_text())
    session_end = data["hooks"]["SessionEnd"]
    assert len(session_end) == 1
    inner = session_end[0]["hooks"][0]
    assert inner["type"] == "command"
    assert "cctx autopsy --latest --quiet" in inner["command"]
    assert "cctx SessionEnd" in inner["description"]
    assert result == str(path)


def test_install_idempotent(tmp_path, monkeypatch):
    """Running install() twice does not duplicate the hook."""
    monkeypatch.chdir(tmp_path)
    from cctx import hook_installer

    hook_installer.install()
    result = hook_installer.install()
    assert result == "already_installed"

    path = Path(".claude/settings.json")
    data = json.loads(path.read_text())
    assert len(data["hooks"]["SessionEnd"]) == 1


def test_install_preserves_existing_settings(tmp_path, monkeypatch):
    """install() merges into existing settings without clobbering other keys."""
    monkeypatch.chdir(tmp_path)
    from cctx import hook_installer

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    existing = {
        "permissions": {"allow": ["Bash(git*)"]},
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}]
        },
    }
    settings_path.write_text(json.dumps(existing))

    hook_installer.install()
    data = json.loads(settings_path.read_text())

    # Existing keys preserved
    assert data["permissions"]["allow"] == ["Bash(git*)"]
    assert "PreToolUse" in data["hooks"]
    # New hook added
    assert "SessionEnd" in data["hooks"]
    assert len(data["hooks"]["SessionEnd"]) == 1


def test_install_force_replaces_hook(tmp_path, monkeypatch):
    """install(force=True) replaces existing hook without duplicating."""
    monkeypatch.chdir(tmp_path)
    from cctx import hook_installer

    hook_installer.install()
    result = hook_installer.install(force=True)

    path = Path(".claude/settings.json")
    data = json.loads(path.read_text())
    assert len(data["hooks"]["SessionEnd"]) == 1
    assert result != "already_installed"


def test_remove_cleans_up(tmp_path, monkeypatch):
    """remove() deletes the hook and prunes empty keys."""
    monkeypatch.chdir(tmp_path)
    from cctx import hook_installer

    hook_installer.install()
    result = hook_installer.remove()

    path = Path(".claude/settings.json")
    assert result is not None
    data = json.loads(path.read_text())
    assert "hooks" not in data


def test_remove_preserves_other_hooks(tmp_path, monkeypatch):
    """remove() only removes the cctx hook, leaving other SessionEnd hooks."""
    monkeypatch.chdir(tmp_path)
    from cctx import hook_installer

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    other_hook = {"hooks": [{"type": "command", "command": "echo other"}]}
    settings_path.write_text(json.dumps({
        "hooks": {"SessionEnd": [other_hook]}
    }))

    hook_installer.install()
    hook_installer.remove()

    data = json.loads(settings_path.read_text())
    session_end = data["hooks"]["SessionEnd"]
    assert len(session_end) == 1
    assert session_end[0]["hooks"][0]["command"] == "echo other"


def test_remove_not_found_returns_none(tmp_path, monkeypatch):
    """remove() when hook is not installed returns None without error."""
    monkeypatch.chdir(tmp_path)
    from cctx import hook_installer

    assert hook_installer.remove() is None


def test_is_installed_false_before_install(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from cctx import hook_installer

    assert not hook_installer.is_installed()


def test_is_installed_true_after_install(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from cctx import hook_installer

    hook_installer.install()
    assert hook_installer.is_installed()


def test_invalid_json_raises(tmp_path, monkeypatch):
    """Corrupt settings.json → ValueError, not a silent overwrite."""
    monkeypatch.chdir(tmp_path)
    from cctx import hook_installer

    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir()
    path.write_text("{ not valid json }")

    with pytest.raises(ValueError, match="Invalid JSON"):
        hook_installer.install()


def test_global_scope_writes_to_home(tmp_path, monkeypatch):
    """--global writes to ~/.claude/settings.json."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    from cctx import hook_installer

    hook_installer.install(global_=True)
    path = fake_home / ".claude" / "settings.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert "SessionEnd" in data["hooks"]


# ---------------------------------------------------------------------------
# CLI integration tests (cctx init)
# ---------------------------------------------------------------------------


def test_init_installs_hook(runner, tmp_path):
    """cctx init writes the hook and prints confirmation."""
    from cctx.cli import cli

    result = runner.invoke(cli, ["init"], catch_exceptions=False, env={"PWD": str(tmp_path)})
    # Note: monkeypatching cwd is simpler in unit tests; CLI uses Path(".claude/...")
    # relative to cwd — just check exit code and output shape
    assert result.exit_code == 0
    assert "✓" in result.output or "already" in result.output.lower() or "installed" in result.output.lower()


def test_init_idempotent_cli(runner, tmp_path, monkeypatch):
    """cctx init twice → second run reports already installed."""
    monkeypatch.chdir(tmp_path)
    from cctx.cli import cli

    runner.invoke(cli, ["init"], catch_exceptions=False)
    result = runner.invoke(cli, ["init"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "already" in result.output.lower()


def test_init_remove_cli(runner, tmp_path, monkeypatch):
    """cctx init --remove cleans up the hook."""
    monkeypatch.chdir(tmp_path)
    from cctx.cli import cli

    runner.invoke(cli, ["init"], catch_exceptions=False)
    result = runner.invoke(cli, ["init", "--remove"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "removed" in result.output.lower()


def test_init_remove_not_installed_cli(runner, tmp_path, monkeypatch):
    """cctx init --remove when not installed exits 0 with a friendly message."""
    monkeypatch.chdir(tmp_path)
    from cctx.cli import cli

    result = runner.invoke(cli, ["init", "--remove"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "nothing" in result.output.lower() or "not found" in result.output.lower()


def test_init_force_and_remove_errors(runner, tmp_path, monkeypatch):
    """--force --remove together → UsageError."""
    monkeypatch.chdir(tmp_path)
    from cctx.cli import cli

    result = runner.invoke(cli, ["init", "--force", "--remove"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# autopsy --quiet tests
# ---------------------------------------------------------------------------


def _make_session_file(tmp_path: Path, session_id: str) -> Path:
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


def test_autopsy_quiet_clean_no_output(runner, tmp_path):
    """--quiet on a clean session emits nothing and exits 0."""
    from cctx.cli import cli

    session = _make_session_file(tmp_path, "quiet-clean-01")
    result = runner.invoke(cli, ["autopsy", str(session), "--quiet"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_autopsy_quiet_with_findings_emits_verdict(runner, tmp_path, monkeypatch):
    """--quiet on a session with findings emits one verdict line."""
    from cctx.cli import cli
    from cctx.models import Confidence, Finding, FindingKind, Severity

    session = _make_session_file(tmp_path, "quiet-dirty-01")

    # Inject a finding via monkeypatch so we don't need a real problematic session
    from cctx import diagnostician
    from cctx.models import Diagnosis
    from datetime import datetime, timezone

    def fake_run(trace):
        return Diagnosis(
            session_id=trace.session_id,
            findings=[
                Finding(
                    kind=FindingKind.RETRY_LOOP,
                    severity=Severity.HIGH,
                    confidence=Confidence.HIGH,
                    first_turn=1,
                    last_turn=2,
                    evidence={},
                    cost_usd=0.01,
                    summary="test finding",
                )
            ],
            inflection_turn=1,
            patches=[],
            total_cost_usd=0.10,
            waste_cost_usd=0.01,
            analysed_at=datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(diagnostician, "run", fake_run)

    result = runner.invoke(cli, ["autopsy", str(session), "--quiet"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "finding" in result.output.lower()
    assert "retry_loop" in result.output.lower()
