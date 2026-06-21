"""Tests for cctx/renderers/report.py — render_html(diag, trace) -> str."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from cctx.models import KIND_LABEL, FindingKind
from tests.diagnostician.conftest import (
    make_assistant_turn,
    make_trace,
    make_user_turn,
)


def _make_finding(kind_str: str = "retry_loop", cost: float | None = 0.05):
    from cctx.models import Confidence, Finding, FindingKind, Severity

    kind_map = {
        "retry_loop":    FindingKind.RETRY_LOOP,
        "scope_creep":   FindingKind.SCOPE_CREEP,
        "stale_context": FindingKind.STALE_CONTEXT,
    }
    return Finding(
        kind=kind_map[kind_str],
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=3,
        last_turn=5,
        evidence={"tool": "Edit", "retries": 2},
        cost_usd=cost,
        summary=f"test {kind_str} finding",
    )


def _make_patch(kind_str: str = "retry_loop"):
    from cctx.models import FindingKind, Patch

    kind_map = {
        "retry_loop":    FindingKind.RETRY_LOOP,
        "scope_creep":   FindingKind.SCOPE_CREEP,
        "stale_context": FindingKind.STALE_CONTEXT,
    }
    return Patch(
        target_file="CLAUDE.md",
        description="Add retry discipline rule",
        unified_diff="+## Retry discipline\n+Stop after two failures.",
        finding_kind=kind_map[kind_str],
        evidence_summary="Seen in 1 session ($0.05 waste)",
    )


def _make_diagnosis(findings=None, patches=None):
    from cctx.models import Diagnosis

    return Diagnosis(
        session_id="test-session-abc",
        findings=findings or [],
        inflection_turn=3 if findings else None,
        patches=patches or [],
        total_cost_usd=1.23,
        waste_cost_usd=sum(f.cost_usd or 0 for f in (findings or [])),
        analysed_at=datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc),
    )


def _simple_trace():
    return make_trace([make_user_turn(1), make_assistant_turn(2, text="ok")])


def _render(diag, trace=None):
    from cctx.renderers.report import render_html
    return render_html(diag, trace or _simple_trace())


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_returns_string():
    assert isinstance(_render(_make_diagnosis()), str)


def test_starts_with_doctype():
    html = _render(_make_diagnosis())
    assert html.strip().startswith("<!DOCTYPE html>")


def test_has_html_skeleton():
    html = _render(_make_diagnosis())
    assert "<html" in html
    assert "</html>" in html
    assert "<head>" in html
    assert "<body>" in html


def test_no_external_script_or_style_src():
    """All CSS must be inline; no external resources loaded."""
    html = _render(_make_diagnosis())
    assert not re.search(r'src=["\']https?://', html)
    assert not re.search(r'<link[^>]+href=["\']https?://', html)


# ---------------------------------------------------------------------------
# Content — clean session
# ---------------------------------------------------------------------------


def test_session_id_present():
    html = _render(_make_diagnosis())
    assert "test-session-abc" in html


def test_clean_session_verdict():
    html = _render(_make_diagnosis())
    assert "Clean session" in html


def test_total_cost_present():
    html = _render(_make_diagnosis())
    assert "1.23" in html


def test_analysed_at_present():
    html = _render(_make_diagnosis())
    assert "2026-05-14" in html


# ---------------------------------------------------------------------------
# Content — findings
# ---------------------------------------------------------------------------


def test_finding_kind_badge_shown():
    diag = _make_diagnosis([_make_finding("retry_loop")])
    html = _render(diag)
    assert "RETRY LOOP" in html


def _finding_of_kind(kind):
    from cctx.models import Confidence, Finding, Severity

    return Finding(
        kind=kind,
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=1,
        last_turn=2,
        evidence={},
        cost_usd=0.01,
        summary=f"{kind.value} finding",
    )


@pytest.mark.parametrize("kind", list(FindingKind))
def test_every_finding_kind_has_styled_badge(kind):
    """Every FindingKind must render its badge AND have a CSS rule to style it (#128).

    Without the CSS rule the badge renders as invisible text on the dark report
    background — the bug that shipped for 8 of 11 kinds.
    """
    html = _render(_make_diagnosis([_finding_of_kind(kind)]))
    assert f"badge kind-{kind.value}" in html  # element rendered
    assert f".badge.kind-{kind.value}" in html  # CSS rule present


@pytest.mark.parametrize("kind", list(FindingKind))
def test_every_finding_kind_renders_canonical_label(kind):
    """Badge text is the canonical KIND_LABEL for every kind (#128)."""
    html = _render(_make_diagnosis([_finding_of_kind(kind)]))
    assert KIND_LABEL[kind] in html


def test_verdict_is_count_based():
    diag = _make_diagnosis([_make_finding("retry_loop")])
    html = _render(diag)
    assert "1 finding · $0.05 waste" in html


def test_finding_summary_shown():
    diag = _make_diagnosis([_make_finding("retry_loop")])
    html = _render(diag)
    assert "test retry_loop finding" in html


def test_finding_cost_shown():
    diag = _make_diagnosis([_make_finding("retry_loop", cost=0.05)])
    html = _render(diag)
    assert "0.0500" in html


def test_inflection_turn_shown():
    diag = _make_diagnosis([_make_finding()])
    html = _render(diag)
    assert "3" in html  # inflection_turn == first_turn == 3


def test_evidence_json_shown():
    diag = _make_diagnosis([_make_finding()])
    html = _render(diag)
    assert "retries" in html


def test_multiple_findings_all_shown():
    diag = _make_diagnosis([_make_finding("retry_loop"), _make_finding("scope_creep")])
    html = _render(diag)
    assert "RETRY LOOP" in html
    assert "SCOPE CREEP" in html


# ---------------------------------------------------------------------------
# Content — patches
# ---------------------------------------------------------------------------


def test_patch_description_shown():
    diag = _make_diagnosis(patches=[_make_patch()])
    html = _render(diag)
    assert "Add retry discipline rule" in html


def test_patch_diff_shown():
    diag = _make_diagnosis(patches=[_make_patch()])
    html = _render(diag)
    assert "Retry discipline" in html


def test_patch_target_file_shown():
    diag = _make_diagnosis(patches=[_make_patch()])
    html = _render(diag)
    assert "CLAUDE.md" in html


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def test_timeline_turn_numbers_present():
    trace = make_trace([make_user_turn(1), make_assistant_turn(2)])
    html = _render(_make_diagnosis(), trace)
    assert "Turn timeline" in html
    # Both turn numbers appear somewhere
    assert ">1<" in html or "turn_number" in html or "turn-bar" in html


def test_flagged_turns_marked():
    """A finding spanning turns 1-2 causes those turn-bars to have 'flagged' class."""
    from cctx.models import Confidence, Finding, FindingKind, Severity

    trace = make_trace([make_user_turn(1), make_assistant_turn(2)])
    finding = Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=1,
        last_turn=2,
        evidence={},
        cost_usd=None,
        summary="flagged",
    )
    diag = _make_diagnosis([finding])
    html = _render(diag, trace)
    assert "flagged" in html


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_autopsy_html_flag_writes_file(tmp_path):
    """cctx autopsy <session> --html <file> writes an HTML file."""
    import json

    from click.testing import CliRunner

    from cctx.cli import cli

    session_id = "html-test-sess"
    line = {
        "type": "user",
        "uuid": f"{session_id}-u1",
        "parentUuid": None,
        "isSidechain": False,
        "timestamp": "2026-05-14T10:00:00.000Z",
        "sessionId": session_id,
        "version": "2.1.138",
        "cwd": "/Users/test",
        "gitBranch": "main",
        "userType": "external",
        "entrypoint": "cli",
        "message": {"role": "user", "content": "hello"},
    }
    session_path = tmp_path / f"{session_id}.jsonl"
    session_path.write_text(json.dumps(line) + "\n")
    out_path = tmp_path / "report.html"

    runner = CliRunner()
    result = runner.invoke(
        cli, ["autopsy", str(session_path), "--html", str(out_path)], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert out_path.exists()
    content = out_path.read_text()
    assert "<!DOCTYPE html>" in content
    assert session_id in content


def test_html_includes_subagent_costs():
    """HTML output contains subagent label and cost when subagent_costs present."""
    import dataclasses

    from cctx.models import SubagentAttribution
    from cctx.renderers.report import render_html

    diag = _make_diagnosis()
    trace = _simple_trace()
    diag = dataclasses.replace(diag, subagent_costs=[
        SubagentAttribution(
            session_id="child-1",
            label="Analyze the database schema",
            total_cost_usd=0.025,
            depth=1,
            model="claude-sonnet-4",
        )
    ])
    html = render_html(diag, trace)
    assert "Analyze the database schema" in html
    assert "0.025" in html


def test_autopsy_html_with_since_errors(tmp_path):
    """--html and --since together should error, not silently ignore --html."""

    from click.testing import CliRunner

    from cctx.cli import cli

    project_dir = tmp_path / "-Users-test-proj"
    project_dir.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        cli, ["autopsy", str(project_dir), "--since", "7", "--html", "out.html"]
    )
    assert result.exit_code != 0
    assert "--html" in result.output or "not supported" in result.output


def test_html_tags_subagent_finding():
    import dataclasses

    from cctx.models import SubagentAttribution

    diag = _make_diagnosis([_make_finding("retry_loop")])
    f = dataclasses.replace(diag.findings[0], session_id="sub-1")
    diag = dataclasses.replace(diag, findings=[f], subagent_costs=[
        SubagentAttribution(session_id="sub-1", label="Resolver",
                            total_cost_usd=0.2, depth=1, model="gpt-4o"),
    ])
    html = _render(diag)
    # the finding itself carries a sub-label badge (not just the subagent cost table)
    assert 'class="badge sub-label">Resolver' in html
