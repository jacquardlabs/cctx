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
