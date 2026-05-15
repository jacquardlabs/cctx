"""Cross-session evidence accumulation.

accumulate(diagnoses) -> dict[FindingKind, KindEvidence]

Counts how many sessions triggered each finding kind and sums waste cost.
Per the spec, session_count increments once per session per kind, regardless
of how many findings of that kind appear in one session.
Stores up to 3 example_summaries for the renderer.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from cctx.models import Diagnosis, FindingKind, KindEvidence
from cctx.recommender.claude_md import summarize

if TYPE_CHECKING:
    from cctx.models import Finding


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
