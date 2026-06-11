"""Tests for patch efficacy report (M17 #90)."""
from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from rich.console import Console as RichConsole

from cctx.models import (
    Confidence,
    Diagnosis,
    Finding,
    FindingKind,
    SessionTrace,
    Severity,
    Usage,
)

UTC = timezone.utc
_TS = datetime(2026, 5, 1, tzinfo=UTC)


def test_efficacy_row_exists():
    from cctx.models import EfficacyRow, FindingKind
    row = EfficacyRow(
        heading="## Retry discipline",
        kind=FindingKind.RETRY_LOOP,
        applied_at=_TS,
        sessions_before=5,
        sessions_after=0,
        total_before=12,
        total_after=11,
        weeks_before=3.0,
        weeks_after=3.0,
    )
    assert row.sessions_before == 5
    assert row.applied_at == _TS


def test_efficacy_report_exists():
    from cctx.models import EfficacyReport
    report = EfficacyReport(rows=[], total_sessions=0, oldest_session=None, newest_session=None)
    assert report.rows == []
    assert report.total_sessions == 0


# ---------------------------------------------------------------------------
# managed_heading_dates — Task B
# ---------------------------------------------------------------------------

def _make_git_repo_with_headings(tmp_path):
    """Create a git repo with a CLAUDE.md that has ## Retry discipline."""
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "CLAUDE.md").write_text("# Project\n\n## Retry discipline\n\nBody.\n")
    subprocess.run(["git", "add", "CLAUDE.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "add retry"], cwd=tmp_path, check=True)


def test_managed_heading_dates_returns_datetime_for_present_heading(tmp_path):
    _make_git_repo_with_headings(tmp_path)
    from cctx.harvest import managed_heading_dates
    dates = managed_heading_dates(tmp_path)
    assert "## Retry discipline" in dates
    assert dates["## Retry discipline"] is not None
    assert isinstance(dates["## Retry discipline"], datetime)


def test_managed_heading_dates_returns_none_for_absent_heading(tmp_path):
    _make_git_repo_with_headings(tmp_path)
    from cctx.harvest import managed_heading_dates
    dates = managed_heading_dates(tmp_path)
    assert dates["## Context hygiene"] is None
    assert dates["## Fan-out discipline"] is None


def test_managed_heading_dates_no_git_returns_all_none(tmp_path):
    """No git repo → all headings map to None; no exception raised."""
    (tmp_path / "CLAUDE.md").write_text("## Retry discipline\n\nBody.\n")
    from cctx.harvest import managed_heading_dates
    dates = managed_heading_dates(tmp_path)
    assert all(v is None for v in dates.values())


def test_managed_heading_dates_covers_all_managed_headings(tmp_path):
    """Return dict has a key for every heading in MANAGED_HEADINGS."""
    from cctx.harvest import managed_heading_dates
    from cctx.models import MANAGED_HEADINGS
    dates = managed_heading_dates(tmp_path)
    for heading in MANAGED_HEADINGS.values():
        assert heading in dates, f"Missing: {heading}"


# ---------------------------------------------------------------------------
# evidence.efficacy — Task C
# ---------------------------------------------------------------------------

_USAGE = Usage(100, 50, 0, 0, 0, None)

_APPLIED_AT = datetime(2026, 5, 15, tzinfo=UTC)
_BEFORE_TS  = datetime(2026, 5, 1, tzinfo=UTC)
_AFTER_TS   = datetime(2026, 5, 20, tzinfo=UTC)


def _make_trace(start_time: datetime | None) -> SessionTrace:
    return SessionTrace(
        session_id="s1",
        parent_session_id=None,
        project_path="/test",
        cwd="/test",
        primary_model="claude-sonnet-4-6",
        claude_code_version="1.0",
        turns=[],
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=start_time,
        end_time=start_time,
        source_path=Path("/test/session.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


def _make_diagnosis(kind: FindingKind | None = None) -> Diagnosis:
    from datetime import datetime as dt
    findings = []
    if kind is not None:
        findings.append(Finding(
            kind=kind,
            severity=Severity.MEDIUM,
            confidence=Confidence.MEDIUM,
            first_turn=1, last_turn=2,
            evidence={},
            cost_usd=0.01,
            summary="test",
        ))
    return Diagnosis(
        session_id="s1",
        findings=findings,
        inflection_turn=None,
        patches=[],
        total_cost_usd=0.01,
        waste_cost_usd=0.0,
        analysed_at=dt(2026, 6, 10, tzinfo=UTC),
    )


def test_efficacy_splits_before_after():
    """Sessions before applied_at go in before bucket; after go in after bucket."""
    from cctx.recommender.evidence import efficacy
    heading = "## Retry discipline"
    pairs = [
        (_make_diagnosis(FindingKind.RETRY_LOOP), _make_trace(_BEFORE_TS)),
        (_make_diagnosis(None), _make_trace(_BEFORE_TS)),
        (_make_diagnosis(FindingKind.RETRY_LOOP), _make_trace(_AFTER_TS)),
        (_make_diagnosis(None), _make_trace(_AFTER_TS)),
    ]
    report = efficacy(pairs, {heading: _APPLIED_AT})
    rows = {r.heading: r for r in report.rows}
    row = rows[heading]
    assert row.sessions_before == 1
    assert row.total_before == 2
    assert row.sessions_after == 1
    assert row.total_after == 2
    assert report.total_sessions == 4


def test_efficacy_applied_at_none_all_sessions_go_after():
    """When applied_at is None, all sessions go to 'after' bucket."""
    from cctx.recommender.evidence import efficacy
    heading = "## Retry discipline"
    pairs = [
        (_make_diagnosis(FindingKind.RETRY_LOOP), _make_trace(_BEFORE_TS)),
        (_make_diagnosis(None), _make_trace(_AFTER_TS)),
    ]
    report = efficacy(pairs, {heading: None})
    row = next(r for r in report.rows if r.heading == heading)
    assert row.sessions_before == 0
    assert row.total_before == 0
    assert row.sessions_after == 1
    assert row.total_after == 2


def test_efficacy_skips_none_start_time():
    """Sessions with start_time=None are excluded from all counts."""
    from cctx.recommender.evidence import efficacy
    heading = "## Retry discipline"
    pairs = [
        (_make_diagnosis(FindingKind.RETRY_LOOP), _make_trace(None)),
        (_make_diagnosis(FindingKind.RETRY_LOOP), _make_trace(_AFTER_TS)),
    ]
    report = efficacy(pairs, {heading: _APPLIED_AT})
    assert report.total_sessions == 1
    row = next(r for r in report.rows if r.heading == heading)
    assert row.sessions_after == 1
    assert row.total_after == 1


def test_efficacy_weeks_before_after():
    """weeks_before and weeks_after are computed from oldest/newest session start_time."""
    from cctx.recommender.evidence import efficacy
    heading = "## Retry discipline"
    oldest = datetime(2026, 5, 1, tzinfo=UTC)
    newest = datetime(2026, 5, 29, tzinfo=UTC)
    pairs = [
        (_make_diagnosis(None), _make_trace(oldest)),
        (_make_diagnosis(None), _make_trace(newest)),
    ]
    report = efficacy(pairs, {heading: _APPLIED_AT})
    row = next(r for r in report.rows if r.heading == heading)
    assert abs(row.weeks_before - 2.0) < 0.1
    assert abs(row.weeks_after - 2.0) < 0.1


def test_efficacy_all_six_headings_in_report():
    """Report contains one row per managed heading."""
    from cctx.models import MANAGED_HEADINGS
    from cctx.recommender.evidence import efficacy
    heading_dates = {h: None for h in MANAGED_HEADINGS.values()}
    report = efficacy([], heading_dates)
    assert len(report.rows) == len(MANAGED_HEADINGS)
    headings_in_report = {r.heading for r in report.rows}
    assert headings_in_report == set(MANAGED_HEADINGS.values())


# ---------------------------------------------------------------------------
# render_efficacy_report — Task D
# ---------------------------------------------------------------------------


def _make_report(rows=None, total=0, oldest=None, newest=None):
    from cctx.models import EfficacyReport
    return EfficacyReport(
        rows=rows or [],
        total_sessions=total,
        oldest_session=oldest,
        newest_session=newest,
    )


def _make_row(
    heading="## Retry discipline",
    kind=None,
    applied_at=_APPLIED_AT,
    sb=5, sa=0, tb=12, ta=11,
    wb=3.0, wa=3.0,
):
    from cctx.models import EfficacyRow, FindingKind
    return EfficacyRow(
        heading=heading,
        kind=kind or FindingKind.RETRY_LOOP,
        applied_at=applied_at,
        sessions_before=sb, sessions_after=sa,
        total_before=tb, total_after=ta,
        weeks_before=wb, weeks_after=wa,
    )


def _con() -> RichConsole:
    return RichConsole(file=StringIO(), highlight=False, markup=False)


def test_render_efficacy_no_sessions(tmp_path):
    """Empty pairs → 'No sessions found' message."""
    from cctx.renderers.terminal import render_efficacy_report
    con = _con()
    render_efficacy_report(_make_report(), tmp_path, tmp_path, console=con)
    out = con.file.getvalue()
    assert "No sessions" in out


def test_render_efficacy_not_in_git(tmp_path):
    """applied_at=None → 'not in git' in output."""
    from cctx.renderers.terminal import render_efficacy_report
    con = _con()
    row = _make_row(applied_at=None)
    report = _make_report(rows=[row], total=5)
    render_efficacy_report(report, tmp_path, tmp_path, console=con)
    out = con.file.getvalue()
    assert "not in git" in out


def test_render_efficacy_effective_signal(tmp_path):
    """rate_after == 0 with baseline → 'effective' in output."""
    from cctx.renderers.terminal import render_efficacy_report
    con = _con()
    row = _make_row(sb=5, sa=0, tb=12, ta=11, wb=3.0, wa=3.0)
    report = _make_report(rows=[row], total=23)
    render_efficacy_report(report, tmp_path, tmp_path, console=con)
    out = con.file.getvalue()
    assert "effective" in out


def test_render_efficacy_persisting_signal(tmp_path):
    """High rate_after relative to rate_before → 'persisting' in output."""
    from cctx.renderers.terminal import render_efficacy_report
    con = _con()
    row = _make_row(sb=5, sa=4, tb=8, ta=8, wb=2.0, wa=2.0)
    report = _make_report(rows=[row], total=16)
    render_efficacy_report(report, tmp_path, tmp_path, console=con)
    out = con.file.getvalue()
    assert "persisting" in out


def test_render_efficacy_no_baseline(tmp_path):
    """sessions_before == 0 with a known applied_at → 'no baseline'."""
    from cctx.renderers.terminal import render_efficacy_report
    con = _con()
    row = _make_row(sb=0, sa=3, tb=0, ta=12, wb=0.0, wa=3.0)
    report = _make_report(rows=[row], total=12)
    render_efficacy_report(report, tmp_path, tmp_path, console=con)
    out = con.file.getvalue()
    assert "no baseline" in out


def test_render_efficacy_low_sample(tmp_path):
    """total_before < 3 → 'low sample' in output."""
    from cctx.renderers.terminal import render_efficacy_report
    con = _con()
    row = _make_row(sb=1, sa=0, tb=2, ta=5, wb=1.0, wa=3.0)
    report = _make_report(rows=[row], total=7)
    render_efficacy_report(report, tmp_path, tmp_path, console=con)
    out = con.file.getvalue()
    assert "low sample" in out


# ---------------------------------------------------------------------------
# CLI integration — Task E
# ---------------------------------------------------------------------------

def test_cli_efficacy_requires_directory(tmp_path):
    """--efficacy with a .jsonl file path → usage error."""
    from click.testing import CliRunner

    from cctx.cli import cli
    session_file = tmp_path / "session.jsonl"
    session_file.write_text("{}\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["harvest", str(session_file), "--efficacy"])
    assert result.exit_code != 0


def test_cli_efficacy_empty_project(tmp_path):
    """--efficacy on a directory with no sessions → 'No sessions found'."""
    from click.testing import CliRunner

    from cctx.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, [
        "harvest", str(tmp_path), "--efficacy",
        "--target-dir", str(tmp_path),
    ])
    assert result.exit_code == 0
    assert "No sessions" in result.output
