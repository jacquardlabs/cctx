"""Tests for cctx autopsy --all (M21: cross-project digest, issue #94)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_MCP_ATTACHMENT = {
    "type": "deferred_tools_delta",
    "addedNames": ["mcp__gmail__authenticate", "mcp__gmail__list"],
    "removedNames": [],
    "readdedNames": [],
    "pendingMcpServers": [],
}


def _write_session(
    project_dir: Path,
    session_id: str,
    *,
    with_mcp: bool = False,
) -> Path:
    """Write a minimal valid session JSONL under project_dir."""
    lines: list[dict] = []

    if with_mcp:
        lines.append({
            "type": "attachment",
            "uuid": f"{session_id}-att",
            "parentUuid": None,
            "timestamp": "2026-06-20T10:00:00.000Z",
            "sessionId": session_id,
            "attachment": _MCP_ATTACHMENT,
        })

    lines.append({
        "type": "user",
        "uuid": f"{session_id}-u1",
        "parentUuid": f"{session_id}-att" if with_mcp else None,
        "isSidechain": False,
        "timestamp": "2026-06-20T10:00:01.000Z",
        "sessionId": session_id,
        "version": "2.1.0",
        "cwd": str(project_dir),
        "gitBranch": "main",
        "userType": "external",
        "entrypoint": "cli",
        "message": {"role": "user", "content": "hello"},
    })
    lines.append({
        "type": "assistant",
        "uuid": f"{session_id}-a1",
        "parentUuid": f"{session_id}-u1",
        "isSidechain": False,
        "timestamp": "2026-06-20T10:00:02.000Z",
        "sessionId": session_id,
        "version": "2.1.0",
        "cwd": str(project_dir),
        "gitBranch": "main",
        "userType": "external",
        "entrypoint": "cli",
        "message": {
            "model": "claude-sonnet-4-6",
            "id": f"msg_{session_id}",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "hi"}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 0,
                    "ephemeral_1h_input_tokens": 0,
                },
                "service_tier": "standard",
                "iterations": [{
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": 0,
                        "ephemeral_1h_input_tokens": 0,
                    },
                    "type": "message",
                }],
            },
        },
    })

    path = project_dir / f"{session_id}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return path


def _make_projects_dir(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create two project dirs under tmp_path and return (projects_root, proj_a, proj_b)."""
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    proj_a = projects_root / "-Users-test-Projects-alpha"
    proj_b = projects_root / "-Users-test-Projects-beta"
    proj_a.mkdir()
    proj_b.mkdir()
    return projects_root, proj_a, proj_b


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_project_digest_row_model():
    from cctx.models import ProjectDigestRow
    row = ProjectDigestRow(
        display_name="~/Projects/alpha",
        sessions_analysed=3,
        sessions_with_findings=1,
        total_cost_usd=0.42,
        waste_cost_usd=0.10,
        top_pattern="UNUSED CONTEXT",
    )
    assert row.display_name == "~/Projects/alpha"
    assert row.top_pattern == "UNUSED CONTEXT"


def test_cross_project_digest_model():
    from cctx.models import CrossProjectDigest, ProjectDigestRow
    digest = CrossProjectDigest(
        period_label="last 7 days",
        projects=[
            ProjectDigestRow("~/Projects/alpha", 3, 1, 0.42, 0.10, "UNUSED CONTEXT"),
        ],
        total_cost_usd=0.42,
        total_waste_usd=0.10,
        global_patches=[],
        global_by_kind={},
        global_project_counts={},
    )
    assert digest.period_label == "last 7 days"
    assert len(digest.projects) == 1
    assert digest.global_project_counts == {}


# ---------------------------------------------------------------------------
# CLI validation tests
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    from click.testing import CliRunner
    return CliRunner()


def test_all_without_since_errors(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(cli, ["autopsy", "--all"])
    assert result.exit_code != 0
    assert "--since" in result.output


def test_all_with_latest_errors(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(cli, ["autopsy", "--all", "--since", "7", "--latest"])
    assert result.exit_code != 0
    assert "--latest" in result.output


def test_all_with_html_errors(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(cli, ["autopsy", "--all", "--since", "7", "--html", "out.html"])
    assert result.exit_code != 0
    assert "--html" in result.output


def test_all_with_quiet_errors(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(cli, ["autopsy", "--all", "--since", "7", "--quiet"])
    assert result.exit_code != 0
    assert "--quiet" in result.output


def test_all_with_top_errors(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(cli, ["autopsy", "--all", "--since", "7", "--top", "3"])
    assert result.exit_code != 0
    assert "--top" in result.output


def test_all_with_health_errors(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(cli, ["autopsy", "--all", "--since", "7", "--health"])
    assert result.exit_code != 0
    assert "--health" in result.output


def test_all_with_turn_errors(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(cli, ["autopsy", "--all", "--since", "7", "--turn", "1"])
    assert result.exit_code != 0
    assert "--turn" in result.output


# ---------------------------------------------------------------------------
# CLI execution tests
# ---------------------------------------------------------------------------


def test_all_empty_window_prints_message(runner, tmp_path, monkeypatch):
    """No sessions in any project → 'No sessions found' message."""
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(cli, ["autopsy", "--all", "--since", "7"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "No sessions found" in result.output


def test_all_single_project_no_global_patterns(runner, tmp_path, monkeypatch):
    """Single project → per-project table shown, no global patterns section."""
    projects_root, proj_a, _ = _make_projects_dir(tmp_path)
    _write_session(proj_a, "sess-1")
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(cli, ["autopsy", "--all", "--since", "7"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "cross-project digest" in result.output
    assert "No cross-project patterns" in result.output


def test_all_two_clean_projects_no_global_patterns(runner, tmp_path, monkeypatch):
    """Two projects, no findings → per-project table but no global patterns."""
    projects_root, proj_a, proj_b = _make_projects_dir(tmp_path)
    _write_session(proj_a, "sess-a1")
    _write_session(proj_b, "sess-b1")
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(cli, ["autopsy", "--all", "--since", "7"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "cross-project digest" in result.output
    assert "No cross-project patterns" in result.output


def test_all_two_projects_same_kind_fires_global_pattern(runner, tmp_path, monkeypatch):
    """Two projects both with UNUSED_CONTEXT → global pattern fires."""
    projects_root, proj_a, proj_b = _make_projects_dir(tmp_path)
    _write_session(proj_a, "sess-a1", with_mcp=True)
    _write_session(proj_b, "sess-b1", with_mcp=True)
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(cli, ["autopsy", "--all", "--since", "7"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "Global patterns" in result.output
    assert "UNUSED CONTEXT" in result.output


def test_all_json_output(runner, tmp_path, monkeypatch):
    """--json flag produces a valid CrossProjectDigest JSON object."""
    projects_root, proj_a, _ = _make_projects_dir(tmp_path)
    _write_session(proj_a, "sess-a1")
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(
        cli, ["autopsy", "--all", "--since", "7", "--json"], catch_exceptions=False
    )
    assert result.exit_code == 0
    obj = json.loads(result.output)
    assert "period_label" in obj
    assert "projects" in obj
    assert "global_by_kind" in obj
    assert "global_patches" in obj
    assert "total_cost_usd" in obj
    assert "total_waste_usd" in obj


def test_all_json_project_count_in_global_kind(runner, tmp_path, monkeypatch):
    """JSON output includes project_count per global kind."""
    projects_root, proj_a, proj_b = _make_projects_dir(tmp_path)
    _write_session(proj_a, "sess-a1", with_mcp=True)
    _write_session(proj_b, "sess-b1", with_mcp=True)
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(
        cli, ["autopsy", "--all", "--since", "7", "--json"], catch_exceptions=False
    )
    assert result.exit_code == 0
    obj = json.loads(result.output)
    assert "unused_context" in obj["global_by_kind"]
    assert obj["global_by_kind"]["unused_context"]["project_count"] == 2


def test_all_global_patches_target_global_claude_md(runner, tmp_path, monkeypatch):
    """Global patches must target ~/.claude/CLAUDE.md, not a project CLAUDE.md."""
    projects_root, proj_a, proj_b = _make_projects_dir(tmp_path)
    _write_session(proj_a, "sess-a1", with_mcp=True)
    _write_session(proj_b, "sess-b1", with_mcp=True)
    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.cli import cli
    result = runner.invoke(
        cli, ["autopsy", "--all", "--since", "7", "--json"], catch_exceptions=False
    )
    assert result.exit_code == 0
    obj = json.loads(result.output)
    for patch in obj["global_patches"]:
        assert patch["target_file"] == "~/.claude/CLAUDE.md"


# ---------------------------------------------------------------------------
# Renderer unit test
# ---------------------------------------------------------------------------


def test_render_cross_project_digest_no_global_patterns():
    """Digest with no global patterns prints the expected empty message."""
    from io import StringIO

    from rich.console import Console

    from cctx.models import CrossProjectDigest, ProjectDigestRow
    from cctx.renderers.terminal import render_cross_project_digest

    buf = StringIO()
    con = Console(file=buf, no_color=True, width=120)
    digest = CrossProjectDigest(
        period_label="last 7 days",
        projects=[
            ProjectDigestRow("~/Projects/alpha", 2, 0, 0.10, 0.00, None),
        ],
        total_cost_usd=0.10,
        total_waste_usd=0.00,
        global_patches=[],
        global_by_kind={},
        global_project_counts={},
    )
    render_cross_project_digest(digest, console=con)
    out = buf.getvalue()
    assert "cross-project digest" in out
    assert "No cross-project patterns" in out


def test_render_cross_project_digest_with_global_patterns():
    """Digest with global patterns shows the global patterns table."""
    from io import StringIO

    from rich.console import Console

    from cctx.models import (
        CrossProjectDigest,
        FindingKind,
        KindEvidence,
        ProjectDigestRow,
    )
    from cctx.renderers.terminal import render_cross_project_digest

    kind = FindingKind.UNUSED_CONTEXT
    ev = KindEvidence(kind=kind, session_count=3, total_waste_usd=0.0, example_summaries=[])

    buf = StringIO()
    con = Console(file=buf, no_color=True, width=120)
    digest = CrossProjectDigest(
        period_label="last 7 days",
        projects=[
            ProjectDigestRow("~/Projects/alpha", 2, 1, 0.10, 0.00, "UNUSED CONTEXT"),
            ProjectDigestRow("~/Projects/beta", 1, 1, 0.05, 0.00, "UNUSED CONTEXT"),
        ],
        total_cost_usd=0.15,
        total_waste_usd=0.00,
        global_patches=[],
        global_by_kind={kind: ev},
        global_project_counts={kind: 2},
    )
    render_cross_project_digest(digest, console=con)
    out = buf.getvalue()
    assert "Global patterns" in out
    assert "UNUSED CONTEXT" in out


# ---------------------------------------------------------------------------
# Exporter unit test
# ---------------------------------------------------------------------------


def test_export_cross_project_digest_structure():
    from cctx.exporters.jsonl import export_cross_project_digest
    from cctx.models import (
        CrossProjectDigest,
        FindingKind,
        KindEvidence,
        Patch,
        ProjectDigestRow,
    )

    kind = FindingKind.UNUSED_CONTEXT
    ev = KindEvidence(kind=kind, session_count=2, total_waste_usd=0.0, example_summaries=["ex"])
    patch = Patch(
        target_file="~/.claude/CLAUDE.md",
        description="Add context overhead note",
        unified_diff="+## Context overhead\n+body",
        finding_kind=kind,
        evidence_summary="appeared in 2 sessions",
    )
    digest = CrossProjectDigest(
        period_label="last 7 days",
        projects=[
            ProjectDigestRow("~/Projects/alpha", 2, 1, 0.10, 0.0, "UNUSED CONTEXT"),
        ],
        total_cost_usd=0.10,
        total_waste_usd=0.0,
        global_patches=[patch],
        global_by_kind={kind: ev},
        global_project_counts={kind: 2},
    )
    raw = export_cross_project_digest(digest)
    obj = json.loads(raw)

    assert obj["period_label"] == "last 7 days"
    assert obj["total_cost_usd"] == pytest.approx(0.10)
    assert len(obj["projects"]) == 1
    assert obj["projects"][0]["display_name"] == "~/Projects/alpha"
    assert obj["projects"][0]["top_pattern"] == "UNUSED CONTEXT"

    assert "unused_context" in obj["global_by_kind"]
    gc = obj["global_by_kind"]["unused_context"]
    assert gc["project_count"] == 2
    assert gc["session_count"] == 2

    assert len(obj["global_patches"]) == 1
    assert obj["global_patches"][0]["target_file"] == "~/.claude/CLAUDE.md"
    assert obj["global_patches"][0]["finding_kind"] == "unused_context"
