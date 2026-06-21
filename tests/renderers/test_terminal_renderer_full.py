"""Full coverage tests for render_aggregate and render_harvest_results.

Uses the Console(file=StringIO()) pattern for plain-text assertions.
For the "green border" assertion on APPLIED panels, we use
Console(record=True) + export_text(styles=True) to capture ANSI style info.
"""
from __future__ import annotations

from io import StringIO

import pytest

from cctx.models import KIND_LABEL, FindingKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        evidence_summary="Seen in 2 sessions (~$0.15 wasted).",
    )



def _make_aggregate_report(by_kind=None, patches=None, window_days=7):
    from cctx.models import AggregateReport

    if by_kind is None:
        by_kind = {}

    return AggregateReport(
        period_label=f"last {window_days} days",
        sessions_analysed=3,
        sessions_with_findings=2,
        total_cost_usd=4.50,
        waste_cost_usd=0.75,
        by_kind=by_kind,
        patches=patches or [],
    )


def _make_apply_result(status_str: str, patch=None, message: str = "ok"):
    from pathlib import Path

    from cctx.harvest import ApplyResult, ApplyStatus

    status_map = {
        "applied": ApplyStatus.APPLIED,
        "skipped": ApplyStatus.SKIPPED,
        "error":   ApplyStatus.ERROR,
    }
    return ApplyResult(
        patch=patch or _make_patch(),
        status=status_map[status_str],
        target_path=Path("/tmp/CLAUDE.md"),
        message=message,
    )


def _render_aggregate(report):
    from rich.console import Console

    from cctx.renderers.terminal import render_aggregate

    buf = StringIO()
    console = Console(file=buf, width=120, highlight=False, markup=False)
    render_aggregate(report, console=console)
    return buf.getvalue()


def _render_harvest(results, dry_run=False):
    from rich.console import Console

    from cctx.renderers.terminal import render_harvest_results

    buf = StringIO()
    console = Console(file=buf, width=120, highlight=False, markup=False)
    render_harvest_results(results, dry_run=dry_run, console=console)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# render_aggregate — no findings
# ---------------------------------------------------------------------------


def test_aggregate_no_findings_shows_no_findings():
    report = _make_aggregate_report(by_kind={})
    output = _render_aggregate(report)
    assert "No findings" in output


def test_aggregate_no_findings_still_shows_sessions():
    report = _make_aggregate_report(by_kind={})
    output = _render_aggregate(report)
    assert "Sessions:" in output or "3" in output


def test_aggregate_no_findings_shows_cost():
    report = _make_aggregate_report(by_kind={})
    output = _render_aggregate(report)
    assert "4.50" in output or "0.75" in output


# ---------------------------------------------------------------------------
# render_aggregate — with findings
# ---------------------------------------------------------------------------


def test_aggregate_shows_window_days():
    report = _make_aggregate_report(window_days=7)
    output = _render_aggregate(report)
    assert "7" in output


def test_aggregate_shows_session_count():
    from cctx.models import FindingKind, KindEvidence

    by_kind = {
        FindingKind.RETRY_LOOP: KindEvidence(
            kind=FindingKind.RETRY_LOOP,
            session_count=3,
            total_waste_usd=0.45,
            example_summaries=[],
        )
    }
    report = _make_aggregate_report(by_kind=by_kind)
    output = _render_aggregate(report)
    assert "3" in output  # session count in table


def test_aggregate_shows_finding_kind_label():
    from cctx.models import FindingKind, KindEvidence

    by_kind = {
        FindingKind.RETRY_LOOP: KindEvidence(
            kind=FindingKind.RETRY_LOOP,
            session_count=2,
            total_waste_usd=0.20,
            example_summaries=[],
        )
    }
    report = _make_aggregate_report(by_kind=by_kind)
    output = _render_aggregate(report)
    assert "RETRY LOOP" in output or "retry" in output.lower()


def test_aggregate_shows_scope_creep_label():
    from cctx.models import FindingKind, KindEvidence

    by_kind = {
        FindingKind.SCOPE_CREEP: KindEvidence(
            kind=FindingKind.SCOPE_CREEP,
            session_count=1,
            total_waste_usd=0.10,
            example_summaries=[],
        )
    }
    report = _make_aggregate_report(by_kind=by_kind)
    output = _render_aggregate(report)
    assert "SCOPE CREEP" in output or "scope" in output.lower()


def test_aggregate_shows_waste_cost():
    from cctx.models import FindingKind, KindEvidence

    by_kind = {
        FindingKind.STALE_CONTEXT: KindEvidence(
            kind=FindingKind.STALE_CONTEXT,
            session_count=2,
            total_waste_usd=1.23,
            example_summaries=[],
        )
    }
    report = _make_aggregate_report(by_kind=by_kind, window_days=14)
    output = _render_aggregate(report)
    assert "1.23" in output


def test_aggregate_with_patches_shows_diff():
    from cctx.models import FindingKind, KindEvidence

    patch = _make_patch("retry_loop")
    by_kind = {
        FindingKind.RETRY_LOOP: KindEvidence(
            kind=FindingKind.RETRY_LOOP,
            session_count=2,
            total_waste_usd=0.30,
            example_summaries=[],
        )
    }
    report = _make_aggregate_report(by_kind=by_kind, patches=[patch])
    output = _render_aggregate(report)
    assert "Retry discipline" in output


def test_aggregate_with_patches_shows_description():
    from cctx.models import FindingKind, KindEvidence

    patch = _make_patch("retry_loop")
    by_kind = {
        FindingKind.RETRY_LOOP: KindEvidence(
            kind=FindingKind.RETRY_LOOP,
            session_count=2,
            total_waste_usd=0.30,
            example_summaries=[],
        )
    }
    report = _make_aggregate_report(by_kind=by_kind, patches=[patch])
    output = _render_aggregate(report)
    assert "Add retry discipline rule" in output


# ---------------------------------------------------------------------------
# render_harvest_results — empty
# ---------------------------------------------------------------------------


def test_harvest_empty_shows_no_patches():
    output = _render_harvest([])
    assert "No patches" in output or "clean" in output.lower()


# ---------------------------------------------------------------------------
# render_harvest_results — SKIPPED
# ---------------------------------------------------------------------------


def test_harvest_skipped_shows_already_present():
    result = _make_apply_result("skipped", message="already present: ## Retry discipline")
    output = _render_harvest([result])
    assert "already present" in output or "skipping" in output


def test_harvest_skipped_does_not_show_dry_run():
    result = _make_apply_result("skipped", message="already present: ## Retry discipline")
    output = _render_harvest([result])
    assert "Dry run" not in output


# ---------------------------------------------------------------------------
# render_harvest_results — APPLIED
# ---------------------------------------------------------------------------


def test_harvest_applied_shows_patch_diff():
    result = _make_apply_result("applied", message="appended: ## Retry discipline")
    output = _render_harvest([result])
    assert "Retry discipline" in output


def test_harvest_applied_not_dry_run_shows_applied_count():
    result = _make_apply_result("applied")
    output = _render_harvest([result], dry_run=False)
    assert "Applied" in output or "1" in output


def test_harvest_applied_panel_uses_green_border():
    """APPLIED results use border_style='green'. Capture with record=True to see styles."""
    from rich.console import Console

    from cctx.renderers.terminal import render_harvest_results

    result = _make_apply_result("applied")
    con = Console(record=True, width=120, color_system="truecolor")
    render_harvest_results([result], console=con)
    styled = con.export_text(styles=True)
    # Rich renders green borders with ANSI green codes; the word "green" may also
    # appear in the export. Either form is acceptable.
    assert "green" in styled or "\x1b[32m" in styled or "\x1b[92m" in styled


# ---------------------------------------------------------------------------
# render_harvest_results — dry_run=True
# ---------------------------------------------------------------------------


def test_harvest_dry_run_shows_dry_run_complete():
    result = _make_apply_result("applied")
    output = _render_harvest([result], dry_run=True)
    assert "Dry run" in output


def test_harvest_dry_run_does_not_show_applied_count():
    result = _make_apply_result("applied")
    output = _render_harvest([result], dry_run=True)
    assert "Applied" not in output


# ---------------------------------------------------------------------------
# render_harvest_results — ERROR status
# ---------------------------------------------------------------------------


def test_harvest_error_still_renders():
    """ERROR results should not raise; they render with a panel."""
    result = _make_apply_result("error", message="permission denied")
    output = _render_harvest([result])
    # Should render some output without raising
    assert len(output) > 0


# ---------------------------------------------------------------------------
# render_diagnosis — verdict + kind_summary + finding-kind labels
# ---------------------------------------------------------------------------


def _make_finding(kind, *, summary="circling without progress"):
    from cctx.models import Confidence, Finding, Severity

    return Finding(
        kind=kind,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=3,
        last_turn=7,
        evidence={},
        cost_usd=0.12,
        summary=summary,
    )


def _make_diagnosis(findings, *, waste_cost_usd=0.0, patches=None):
    from datetime import datetime, timezone

    from cctx.models import Diagnosis

    return Diagnosis(
        session_id="sess-01",
        findings=findings,
        inflection_turn=3 if findings else None,
        patches=patches or [],
        total_cost_usd=1.00,
        waste_cost_usd=waste_cost_usd,
        analysed_at=datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc),
    )


def _render_diagnosis(diagnosis):
    from rich.console import Console

    from cctx.renderers.terminal import render_diagnosis

    buf = StringIO()
    console = Console(file=buf, width=120, highlight=False, markup=False)
    render_diagnosis(diagnosis, console=console)
    return buf.getvalue()


def test_render_diagnosis_clean_session_verdict():
    output = _render_diagnosis(_make_diagnosis([]))
    assert "Clean session" in output


def test_render_diagnosis_disclaimer_shows_prices_as_of():
    """The cost disclaimer surfaces the pricing freshness date (#120)."""
    from cctx.pricing import PRICING_LAST_VERIFIED

    output = _render_diagnosis(_make_diagnosis([]))
    assert "prices as of" in output
    assert str(PRICING_LAST_VERIFIED) in output


def test_render_diagnosis_warns_on_unknown_model():
    """An unrecognized model priced at default is flagged in output (#120)."""
    import dataclasses

    diag = dataclasses.replace(_make_diagnosis([]), unknown_models=["gpt-6-preview"])
    output = _render_diagnosis(diag)
    assert "gpt-6-preview" in output
    assert "default" in output.lower()


def test_render_diagnosis_verdict_is_count_based():
    from cctx.models import FindingKind

    diag = _make_diagnosis([_make_finding(FindingKind.RETRY_LOOP)], waste_cost_usd=0.42)
    output = _render_diagnosis(diag)
    assert "1 finding · $0.42 waste" in output


def test_render_diagnosis_shows_kind_summary_secondary_line():
    from cctx.models import FindingKind

    diag = _make_diagnosis(
        [_make_finding(FindingKind.RETRY_LOOP), _make_finding(FindingKind.SCOPE_CREEP)],
        waste_cost_usd=0.50,
    )
    output = _render_diagnosis(diag)
    assert "RETRY LOOP + SCOPE CREEP" in output


@pytest.mark.parametrize("kind", list(FindingKind))
def test_render_diagnosis_every_kind_uses_kind_label(kind):
    """Every FindingKind must render its KIND_LABEL through render_diagnosis (#143)."""
    diag = _make_diagnosis([_make_finding(kind)], waste_cost_usd=0.10)
    output = _render_diagnosis(diag)
    assert KIND_LABEL[kind] in output


def test_harvest_panel_title_uses_kind_label():
    """Patch panel title must use KIND_LABEL, not the raw finding_kind.value (#136)."""
    result = _make_apply_result("applied", patch=_make_patch("retry_loop"))
    output = _render_harvest([result])
    assert "RETRY LOOP" in output
    assert "retry_loop" not in output


# ---------------------------------------------------------------------------
# render_check_results — harvest --check output (#135, moved from cli.py)
# ---------------------------------------------------------------------------


def _make_check_finding(issue_str="dead_file_ref", sev_str="high", heading="## Setup"):
    from cctx.harvest import CheckFinding, CheckIssue, CheckSeverity

    issue_map = {
        "dead_file_ref":  CheckIssue.DEAD_FILE_REF,
        "empty_section":  CheckIssue.EMPTY_SECTION,
        "contradiction":  CheckIssue.CONTRADICTION,
    }
    sev_map = {"high": CheckSeverity.HIGH, "medium": CheckSeverity.MEDIUM, "low": CheckSeverity.LOW}
    return CheckFinding(
        heading=heading,
        issue=issue_map[issue_str],
        severity=sev_map[sev_str],
        detail="references missing.py",
    )


def _render_check(findings):
    from pathlib import Path

    from rich.console import Console

    from cctx.renderers.terminal import render_check_results

    buf = StringIO()
    console = Console(file=buf, width=120, highlight=False, markup=False)
    render_check_results(findings, Path("/tmp/proj"), console=console)
    return buf.getvalue()


def test_render_check_results_clean_when_no_findings():
    output = _render_check([])
    assert "clean" in output.lower()


def test_render_check_results_shows_finding_details():
    output = _render_check([_make_check_finding("dead_file_ref", "high")])
    assert "## Setup" in output
    assert "dead file reference" in output
    assert "references missing.py" in output
    assert "HIGH" in output


def test_render_diagnosis_tags_subagent_finding_with_label():
    import dataclasses

    from cctx.models import FindingKind, SubagentAttribution

    f = dataclasses.replace(_make_finding(FindingKind.RETRY_LOOP), session_id="sub-1")
    diag = _make_diagnosis([f], waste_cost_usd=0.10)
    diag = dataclasses.replace(diag, subagent_costs=[
        SubagentAttribution(session_id="sub-1", label="Resolver",
                            total_cost_usd=0.2, depth=1, model="gpt-4o"),
    ])
    output = _render_diagnosis(diag)
    assert "[Resolver]" in output
    assert "RETRY LOOP" in output
