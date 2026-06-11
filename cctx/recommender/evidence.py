"""Cross-session evidence accumulation.

accumulate(diagnoses) -> dict[FindingKind, KindEvidence]

Counts how many sessions triggered each finding kind and sums waste cost.
Per the spec, session_count increments once per session per kind, regardless
of how many findings of that kind appear in one session.
Stores up to 3 example_summaries for the renderer.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from cctx.models import (
    MANAGED_HEADINGS,  # noqa: E402 — after stdlib, isort groups together
    Diagnosis,
    EfficacyReport,
    EfficacyRow,
    FindingKind,
    KindEvidence,
    SessionTrace,
)
from cctx.recommender.claude_md import summarize

if TYPE_CHECKING:
    from cctx.models import Finding


_HEADING_TO_KIND: dict[str, FindingKind] = {v: k for k, v in MANAGED_HEADINGS.items()}


def _summarize_finding(finding: Finding) -> str:
    return summarize(finding)


def accumulate(diagnoses: list[Diagnosis]) -> dict[FindingKind, KindEvidence]:
    result: dict[FindingKind, KindEvidence] = {}
    for diagnosis in diagnoses:
        # Track which kinds we've already counted for this session to ensure
        # session_count increments once per session per kind, not per finding.
        seen_kinds: set[FindingKind] = set()
        for finding in diagnosis.findings:
            if finding.kind not in result:
                result[finding.kind] = KindEvidence(
                    kind=finding.kind,
                    session_count=0,
                    total_waste_usd=0.0,
                    example_summaries=[],
                )
            ev = result[finding.kind]
            if finding.kind not in seen_kinds:
                ev.session_count += 1
                seen_kinds.add(finding.kind)
            ev.total_waste_usd += finding.cost_usd or 0.0
            if len(ev.example_summaries) < 3:
                ev.example_summaries.append(_summarize_finding(finding))
    return result


def _session_matches(diag: Diagnosis, kind: FindingKind | None) -> bool:
    if kind is None:
        return False
    return any(f.kind is kind for f in diag.findings)


def efficacy(
    pairs: list[tuple[Diagnosis, SessionTrace]],
    heading_dates: dict[str, datetime | None],
) -> EfficacyReport:
    """Compute before/after session counts for each managed CLAUDE.md heading.

    For each heading in heading_dates:
      - Sessions with start_time < applied_at → "before" bucket.
      - Sessions with start_time >= applied_at → "after" bucket.
      - Sessions with start_time=None are skipped entirely.
      - If applied_at is None: all sessions go into "after" (no baseline).
    """
    valid_pairs = [(d, t) for d, t in pairs if t.start_time is not None]

    oldest = min((t.start_time for _, t in valid_pairs), default=None)
    newest = max((t.start_time for _, t in valid_pairs), default=None)

    rows: list[EfficacyRow] = []

    for heading, applied_at in heading_dates.items():
        kind = _HEADING_TO_KIND.get(heading)

        before_pairs = []
        after_pairs = []
        for diag, trace in valid_pairs:
            if applied_at is None or trace.start_time >= applied_at:
                after_pairs.append((diag, trace))
            else:
                before_pairs.append((diag, trace))

        sessions_before = sum(1 for d, _ in before_pairs if _session_matches(d, kind))
        sessions_after  = sum(1 for d, _ in after_pairs  if _session_matches(d, kind))

        if applied_at is not None and oldest is not None:
            weeks_before = max((applied_at - oldest).days, 0) / 7
        else:
            weeks_before = 0.0

        if applied_at is not None and newest is not None:
            weeks_after = max((newest - applied_at).days, 0) / 7
        elif newest is not None and oldest is not None:
            weeks_after = max((newest - oldest).days, 0) / 7
        else:
            weeks_after = 0.0

        rows.append(EfficacyRow(
            heading=heading,
            kind=kind,
            applied_at=applied_at,
            sessions_before=sessions_before,
            sessions_after=sessions_after,
            total_before=len(before_pairs),
            total_after=len(after_pairs),
            weeks_before=weeks_before,
            weeks_after=weeks_after,
        ))

    return EfficacyReport(
        rows=rows,
        total_sessions=len(valid_pairs),
        oldest_session=oldest,
        newest_session=newest,
    )
