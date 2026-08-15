"""Tests for cctx/aggregate.py's report builders.

These exercise the cross-session rollup directly — no CliRunner, no click.
Before #173 this logic lived inside click command bodies and could only be
reached through the CLI.
"""
from __future__ import annotations

import dataclasses
import subprocess
import sys
from datetime import datetime, timezone

from cctx.models import (
    Confidence,
    Diagnosis,
    Finding,
    FindingKind,
    Severity,
)
from tests.diagnostician.conftest import make_trace, make_user_turn
from tests.diagnostician.test_project_specific import _make_pnpm_trace

UTC = timezone.utc
_TS = datetime(2026, 5, 14, 10, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finding(kind: FindingKind, cost: float = 0.01, summary: str = "s") -> Finding:
    return Finding(
        kind=kind,
        severity=Severity.MEDIUM,
        confidence=Confidence.HIGH,
        first_turn=1,
        last_turn=2,
        evidence={},
        cost_usd=cost,
        summary=summary,
    )


def _diagnosis(
    session_id: str,
    kinds: list[FindingKind] | None = None,
    total: float = 1.0,
    waste: float = 0.1,
) -> Diagnosis:
    return Diagnosis(
        session_id=session_id,
        findings=[_finding(k, summary=f"{k.value} in {session_id}") for k in (kinds or [])],
        inflection_turn=None,
        patches=[],
        total_cost_usd=total,
        waste_cost_usd=waste,
        analysed_at=_TS,
    )


def _pair(session_id: str, kinds: list[FindingKind] | None = None, **kw):
    trace = dataclasses.replace(make_trace([make_user_turn(1)]), session_id=session_id)
    return (_diagnosis(session_id, kinds, **kw), trace)


# ---------------------------------------------------------------------------
# build_aggregate_report
# ---------------------------------------------------------------------------


def test_build_aggregate_report_rolls_up_costs_and_counts() -> None:
    from cctx.aggregate import build_aggregate_report

    pairs = [
        _pair("s1", [FindingKind.RETRY_LOOP], total=1.0, waste=0.10),
        _pair("s2", [], total=2.0, waste=0.00),
        _pair("s3", [FindingKind.RETRY_LOOP], total=3.0, waste=0.25),
    ]
    r = build_aggregate_report(pairs, period_label="last 7 days")

    assert r.period_label == "last 7 days"
    assert r.sessions_analysed == 3
    assert r.sessions_with_findings == 2
    assert r.total_cost_usd == 6.0
    assert r.waste_cost_usd == 0.35
    assert list(r.by_kind) == [FindingKind.RETRY_LOOP]
    assert r.by_kind[FindingKind.RETRY_LOOP].session_count == 2


def test_build_aggregate_report_empty_pairs_is_all_zeros() -> None:
    from cctx.aggregate import build_aggregate_report

    r = build_aggregate_report([], period_label="x")
    assert r.sessions_analysed == 0
    assert r.sessions_with_findings == 0
    assert r.total_cost_usd == 0.0
    assert r.waste_cost_usd == 0.0
    assert r.by_kind == {}
    assert r.patches == []
    assert r.project_patterns == []


def test_build_aggregate_report_top_n_trims_by_kind_and_patches() -> None:
    """top_n keeps the n most-recurring kinds, and patches follow by_kind."""
    from cctx.aggregate import build_aggregate_report

    pairs = [
        _pair("s1", [FindingKind.RETRY_LOOP, FindingKind.SCOPE_CREEP]),
        _pair("s2", [FindingKind.RETRY_LOOP]),
        _pair("s3", [FindingKind.RETRY_LOOP]),
    ]
    full = build_aggregate_report(pairs, period_label="x")
    trimmed = build_aggregate_report(pairs, period_label="x", top_n=1)

    assert len(full.by_kind) == 2
    assert list(trimmed.by_kind) == [FindingKind.RETRY_LOOP]
    assert len(trimmed.patches) <= len(full.patches)
    assert all(p.finding_kind is FindingKind.RETRY_LOOP for p in trimmed.patches)


def test_build_aggregate_report_evidence_patches_precede_pattern_patches() -> None:
    """Ordering is load-bearing: evidence patches first, then pattern patches."""
    from cctx.aggregate import build_aggregate_report

    pairs = [
        (_diagnosis(f"s{i}", [FindingKind.RETRY_LOOP]), _make_pnpm_trace(f"s{i}"))
        for i in range(1, 4)
    ]
    r = build_aggregate_report(pairs, period_label="x")

    kinds = [p.finding_kind for p in r.patches]
    assert FindingKind.PROJECT_PATTERN in kinds, "fixture should trip project_specific.detect"
    first_pattern = kinds.index(FindingKind.PROJECT_PATTERN)
    assert all(k is not FindingKind.PROJECT_PATTERN for k in kinds[:first_pattern])


def test_build_aggregate_report_detects_project_patterns_by_default() -> None:
    from cctx.aggregate import build_aggregate_report

    pairs = [(_diagnosis(f"s{i}"), _make_pnpm_trace(f"s{i}")) for i in range(1, 4)]
    r = build_aggregate_report(pairs, period_label="x")
    assert r.project_patterns, "3 sessions with a recurring failure should yield a pattern"


def test_build_aggregate_report_detect_false_skips_detection() -> None:
    """The digest and harvest --since both pass False, for different reasons."""
    from cctx.aggregate import build_aggregate_report

    pairs = [(_diagnosis(f"s{i}"), _make_pnpm_trace(f"s{i}")) for i in range(1, 4)]
    r = build_aggregate_report(pairs, period_label="x", detect_project_patterns=False)

    assert r.project_patterns == []
    assert all(p.finding_kind is not FindingKind.PROJECT_PATTERN for p in r.patches)


# ---------------------------------------------------------------------------
# build_cross_project_digest
# ---------------------------------------------------------------------------


def test_build_cross_project_digest_rows_mirror_per_project_rollup() -> None:
    from cctx.aggregate import build_cross_project_digest

    digest = build_cross_project_digest(
        [
            ("~/Projects/a", [_pair("a1", [FindingKind.RETRY_LOOP], total=1.0, waste=0.1)]),
            ("~/Projects/b", [_pair("b1", [], total=2.0, waste=0.0)]),
        ],
        period_label="last 7 days",
    )

    assert [r.display_name for r in digest.projects] == ["~/Projects/a", "~/Projects/b"]
    assert digest.projects[0].sessions_analysed == 1
    assert digest.projects[0].sessions_with_findings == 1
    assert digest.projects[1].sessions_with_findings == 0
    assert digest.total_cost_usd == 3.0
    assert digest.total_waste_usd == 0.1


def test_build_cross_project_digest_skips_projects_with_no_sessions() -> None:
    from cctx.aggregate import build_cross_project_digest

    digest = build_cross_project_digest(
        [("~/Projects/empty", []), ("~/Projects/a", [_pair("a1")])],
        period_label="x",
    )
    assert [r.display_name for r in digest.projects] == ["~/Projects/a"]


def test_build_cross_project_digest_empty_is_all_zeros() -> None:
    from cctx.aggregate import build_cross_project_digest

    digest = build_cross_project_digest([], period_label="x")
    assert digest.projects == []
    assert digest.global_by_kind == {}
    assert digest.global_patches == []
    assert digest.total_cost_usd == 0.0
    assert digest.total_waste_usd == 0.0


def test_build_cross_project_digest_global_kind_requires_two_projects() -> None:
    """A kind seen in one project is counted but not promoted to a global pattern."""
    from cctx.aggregate import build_cross_project_digest

    digest = build_cross_project_digest(
        [
            ("a", [_pair("a1", [FindingKind.RETRY_LOOP, FindingKind.SCOPE_CREEP])]),
            ("b", [_pair("b1", [FindingKind.RETRY_LOOP])]),
        ],
        period_label="x",
    )

    assert FindingKind.RETRY_LOOP in digest.global_by_kind
    assert FindingKind.SCOPE_CREEP not in digest.global_by_kind
    # global_project_counts keeps every kind, including the single-project one.
    assert digest.global_project_counts[FindingKind.SCOPE_CREEP] == 1
    assert digest.global_project_counts[FindingKind.RETRY_LOOP] == 2


def test_build_cross_project_digest_global_patches_target_user_claude_md() -> None:
    from cctx.aggregate import GLOBAL_CLAUDE_MD, build_cross_project_digest

    digest = build_cross_project_digest(
        [
            ("a", [_pair("a1", [FindingKind.RETRY_LOOP])]),
            ("b", [_pair("b1", [FindingKind.RETRY_LOOP])]),
        ],
        period_label="x",
    )
    assert digest.global_patches
    assert all(p.target_file == GLOBAL_CLAUDE_MD for p in digest.global_patches)


def test_build_cross_project_digest_global_order_follows_first_seen() -> None:
    """Regression for a PYTHONHASHSEED-dependent set iteration.

    Asserts the CONCRETE expected order, not equality between two in-process
    calls — hash() is stable within a process, so a two-call comparison passes
    on the old set-based code and can never fail.
    """
    from cctx.aggregate import build_cross_project_digest

    digest = build_cross_project_digest(
        [
            ("a", [_pair("a1", [FindingKind.RETRY_LOOP, FindingKind.STALE_CONTEXT])]),
            ("b", [_pair("b1", [FindingKind.STALE_CONTEXT, FindingKind.RETRY_LOOP])]),
        ],
        period_label="x",
    )

    assert list(digest.global_by_kind) == [FindingKind.RETRY_LOOP, FindingKind.STALE_CONTEXT]
    assert [p.finding_kind for p in digest.global_patches] == [
        FindingKind.RETRY_LOOP,
        FindingKind.STALE_CONTEXT,
    ]


def test_build_cross_project_digest_never_runs_project_specific_detect(monkeypatch) -> None:
    """ProjectDigestRow has no ProjectPattern slot, so detection must not run."""
    import cctx.aggregate as agg

    def _boom(pairs):
        raise AssertionError("project_specific.detect must not run for the digest")

    monkeypatch.setattr(agg.project_specific, "detect", _boom)
    digest = agg.build_cross_project_digest(
        [("a", [_pair("a1", [FindingKind.RETRY_LOOP])])], period_label="x"
    )
    assert digest.projects


def test_top_pattern_tiebreak() -> None:
    """Equal session_count breaks on waste, then on kind name."""
    from cctx.aggregate import _top_pattern
    from cctx.models import KIND_LABEL, KindEvidence

    by_kind = {
        FindingKind.RETRY_LOOP: KindEvidence(
            kind=FindingKind.RETRY_LOOP, session_count=2,
            total_waste_usd=0.50, example_summaries=[],
        ),
        FindingKind.SCOPE_CREEP: KindEvidence(
            kind=FindingKind.SCOPE_CREEP, session_count=2,
            total_waste_usd=0.10, example_summaries=[],
        ),
    }
    assert _top_pattern(by_kind) == KIND_LABEL[FindingKind.RETRY_LOOP]
    assert _top_pattern({}) is None


# ---------------------------------------------------------------------------
# run_all_projects + layering
# ---------------------------------------------------------------------------


def test_run_all_projects_returns_empty_for_missing_base(tmp_path, monkeypatch) -> None:
    from cctx.aggregate import run_all_projects

    monkeypatch.setenv("CCTX_PROJECTS_DIR", str(tmp_path / "does-not-exist"))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2027, 1, 1, tzinfo=UTC)
    assert run_all_projects(start, end) == []


def test_aggregate_module_does_not_import_click() -> None:
    """Layering invariant: aggregate.py sits above the analyzers, below the CLI.

    A real import check, not a source grep — a grep false-positives on the word
    "click" in a comment and false-negatives on an indirect import. Since #173
    this also transitively guards discovery, recommender, and
    diagnostician.patterns.project_specific.
    """
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import cctx.aggregate, sys; "
            "assert 'click' not in sys.modules, 'click leaked into aggregate.py'; "
            "assert 'rich_click' not in sys.modules, 'rich_click leaked into aggregate.py'",
        ],
        check=True,
    )
