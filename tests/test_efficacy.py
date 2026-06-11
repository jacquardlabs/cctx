"""Tests for patch efficacy report (M17 #90)."""
from __future__ import annotations

from datetime import datetime, timezone

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
