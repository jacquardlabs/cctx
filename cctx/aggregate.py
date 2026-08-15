"""Cross-session pipeline orchestrator and report assembly.

run(project_dir, start, end)      -> list[SessionPair]
run_all_projects(start, end)      -> list[ProjectPairs]
build_aggregate_report(pairs, …)  -> AggregateReport
build_cross_project_digest(…)     -> CrossProjectDigest

`run` discovers session JSONL files in project_dir modified within [start, end],
parses each one, runs the per-session diagnostician, and returns
(Diagnosis, SessionTrace) pairs. `run_all_projects` does the same across every
project under ~/.claude/projects/.

The two `build_*` functions own cross-session report assembly. They are pure
over already-diagnosed pairs — no I/O, no click — so every CLI path computes
its rollup from one formula instead of re-implementing it in a command body.
"""
from __future__ import annotations

import dataclasses
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from cctx import diagnostician
from cctx.diagnostician.patterns import project_specific
from cctx.discovery import list_projects
from cctx.models import (
    KIND_LABEL,
    AggregateReport,
    CrossProjectDigest,
    Diagnosis,
    FindingKind,
    KindEvidence,
    ProjectDigestRow,
    SessionTrace,
)
from cctx.parsers.claude_code import parse_session
from cctx.recommender import claude_md
from cctx.recommender import evidence as evidence_mod
from cctx.tokenizer import tokenize_session

UTC = timezone.utc

SessionPair = tuple[Diagnosis, SessionTrace]
ProjectPairs = tuple[str, list[SessionPair]]

# Patches rolled up across projects target the user-level config, not any one repo.
GLOBAL_CLAUDE_MD = "~/.claude/CLAUDE.md"

# A kind has to recur in at least this many distinct projects to count as global.
MIN_PROJECTS_FOR_GLOBAL_PATTERN = 2


def run(project_dir: Path, start: datetime, end: datetime) -> list[SessionPair]:
    paths = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)

    result = []
    for path in paths:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if not (start <= mtime <= end):
            continue
        try:
            trace = tokenize_session(parse_session(path))
            diagnosis = diagnostician.run(trace)
            result.append((diagnosis, trace))
        except Exception:
            continue  # skip corrupt sessions; don't fail the whole run
    return result


def run_all_projects(
    start: datetime, end: datetime, *, base: Path | None = None
) -> list[ProjectPairs]:
    """Run the per-session pipeline across every project under ~/.claude/projects/."""
    return [(p.display_name, run(p.project_dir, start, end)) for p in list_projects(base)]


def build_aggregate_report(
    pairs: list[SessionPair],
    *,
    period_label: str,
    top_n: int | None = None,
    detect_project_patterns: bool = True,
) -> AggregateReport:
    """Roll a window's diagnosed sessions up into one AggregateReport.

    `pairs` is a list, not an Iterable, on purpose: the body walks it twice —
    once for the diagnoses and once inside project_specific.detect — so a
    generator would silently yield zero patterns on the second pass.

    `detect_project_patterns=False` has two distinct callers, both deliberate:
      - the cross-project digest, whose ProjectDigestRow carries no
        ProjectPattern slot, so detection output would be discarded;
      - harvest --since, because pattern patches need human review. autopsy
        displays them; harvest can auto-apply, so it must not generate them.
    """
    diagnoses = [d for d, _ in pairs]
    ev = evidence_mod.accumulate(diagnoses)
    if top_n is not None:
        ev = dict(sorted(ev.items(), key=lambda x: x[1].session_count, reverse=True)[:top_n])
    patterns = project_specific.detect(pairs) if detect_project_patterns else []
    patches = claude_md.generate_from_evidence(ev) + claude_md.generate_from_patterns(patterns)
    return AggregateReport(
        period_label=period_label,
        sessions_analysed=len(diagnoses),
        sessions_with_findings=sum(1 for d in diagnoses if d.findings),
        total_cost_usd=sum(d.total_cost_usd for d in diagnoses),
        waste_cost_usd=sum(d.waste_cost_usd for d in diagnoses),
        by_kind=ev,
        patches=patches,
        project_patterns=patterns,
    )


def _top_pattern(by_kind: dict[FindingKind, KindEvidence]) -> str | None:
    """Label of the most-frequent kind; ties broken by waste, then kind name."""
    if not by_kind:
        return None
    kind = max(
        by_kind.items(),
        key=lambda x: (x[1].session_count, x[1].total_waste_usd, x[0].value),
    )[0]
    return KIND_LABEL.get(kind)


def build_cross_project_digest(
    project_pairs: list[ProjectPairs], *, period_label: str
) -> CrossProjectDigest:
    """Roll per-project reports up into one cross-project digest.

    Each project's report is built with detect_project_patterns=False; the
    per-project `.patches` are computed and discarded, which is cheap
    (generate_from_evidence is pure string templating, no I/O) and keeps this
    on the same builder rather than adding a second flag.
    """
    reports = [
        (name, build_aggregate_report(
            pairs, period_label=period_label, detect_project_patterns=False
        ))
        for name, pairs in project_pairs
        if pairs
    ]

    rows = [
        ProjectDigestRow(
            display_name=name,
            sessions_analysed=r.sessions_analysed,
            sessions_with_findings=r.sessions_with_findings,
            total_cost_usd=r.total_cost_usd,
            waste_cost_usd=r.waste_cost_usd,
            top_pattern=_top_pattern(r.by_kind),
        )
        for name, r in reports
    ]

    # Counter, not a set: FindingKind is a str Enum, and a set of them iterates in
    # PYTHONHASHSEED-dependent order — which leaked into both the --json key order
    # and the terminal table. Counter is a dict subclass and keeps first-seen order.
    project_kind_counts: Counter[FindingKind] = Counter(
        kind for _, r in reports for kind in r.by_kind
    )

    global_ev: dict[FindingKind, KindEvidence] = {}
    for kind, n in project_kind_counts.items():
        if n < MIN_PROJECTS_FOR_GLOBAL_PATTERN:
            continue
        all_ev = [r.by_kind[kind] for _, r in reports if kind in r.by_kind]
        global_ev[kind] = KindEvidence(
            kind=kind,
            session_count=sum(e.session_count for e in all_ev),
            total_waste_usd=sum(e.total_waste_usd for e in all_ev),
            example_summaries=[s for e in all_ev for s in e.example_summaries][:3],
        )

    global_patches = [
        dataclasses.replace(p, target_file=GLOBAL_CLAUDE_MD)
        for p in claude_md.generate_from_evidence(global_ev)
    ]

    return CrossProjectDigest(
        period_label=period_label,
        projects=rows,
        total_cost_usd=sum(r.total_cost_usd for _, r in reports),
        total_waste_usd=sum(r.waste_cost_usd for _, r in reports),
        global_patches=global_patches,
        global_by_kind=global_ev,
        # All kinds, including n == 1 — the renderer shows project counts per kind.
        global_project_counts=dict(project_kind_counts),
    )
