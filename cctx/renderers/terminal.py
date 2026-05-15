"""Terminal renderer for autopsy Diagnosis output.

render_diagnosis(diagnosis, console=None) -> None
render_aggregate(report, console=None) -> None
render_harvest_results(results, dry_run=False, console=None) -> None

Uses rich for formatting. Accepts an optional Console for testing.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from cctx.models import FindingKind, Severity

if TYPE_CHECKING:
    from cctx.models import AggregateReport, Diagnosis

_SEVERITY_STYLE = {
    Severity.HIGH:   "bold red",
    Severity.MEDIUM: "bold yellow",
    Severity.LOW:    "bold green",
}

_KIND_LABEL = {
    FindingKind.RETRY_LOOP:    "RETRY LOOP",
    FindingKind.SCOPE_CREEP:   "SCOPE CREEP",
    FindingKind.STALE_CONTEXT: "STALE CONTEXT",
}


def _default_console() -> Console:
    return Console()


def render_diagnosis(diagnosis: Diagnosis, *, console: Console | None = None) -> None:
    con = console or _default_console()

    # Header
    con.print(Rule(f"cctx autopsy — session {diagnosis.session_id}"))
    cost_line = f"Session cost: ${diagnosis.total_cost_usd:.2f}"
    if diagnosis.waste_cost_usd > 0:
        pct = (
            diagnosis.waste_cost_usd / diagnosis.total_cost_usd * 100
            if diagnosis.total_cost_usd
            else 0
        )
        cost_line += f" | Attributed waste: ${diagnosis.waste_cost_usd:.2f} ({pct:.0f}%)"
    con.print(cost_line)

    if not diagnosis.findings:
        con.print("\nNo findings — session looks clean.")
        return

    con.print(f"Inflection turn: {diagnosis.inflection_turn}")
    con.print()

    # Findings
    for finding in diagnosis.findings:
        style = _SEVERITY_STYLE.get(finding.severity, "")
        label = _KIND_LABEL.get(finding.kind, finding.kind.value.upper())
        badge = Text(f" {label} ", style=style)
        conf_note = f"({finding.confidence.value} confidence)"
        con.print(badge, conf_note, "—", finding.summary)

    # Patches
    if diagnosis.patches:
        con.print()
        con.print(Rule("CLAUDE.md patches"))
        for patch in diagnosis.patches:
            con.print(f"\n{patch.description}  [{patch.target_file}]")
            con.print(f"Evidence: {patch.evidence_summary}")
            syntax = Syntax(patch.unified_diff, "diff", theme="monokai", word_wrap=True)
            con.print(syntax)


def render_aggregate(report: AggregateReport, *, console: Console | None = None) -> None:
    con = console or _default_console()

    days = int(report.window.total_seconds() / 86400)
    con.print(Rule(f"cctx autopsy — last {days} days"))
    con.print(
        f"Sessions: {report.sessions_analysed} analysed, "
        f"{report.sessions_with_findings} with findings"
    )
    con.print(
        f"Total cost: ${report.total_cost_usd:.2f} | "
        f"Waste: ${report.waste_cost_usd:.2f}"
    )

    if not report.by_kind:
        con.print("\nNo findings across sessions.")
        return

    # Summary table
    table = Table(title="Finding frequency")
    table.add_column("Pattern")
    table.add_column("Sessions", justify="right")
    table.add_column("Waste ($)", justify="right")
    for kind, ev in report.by_kind.items():
        table.add_row(
            _KIND_LABEL.get(kind, kind.value),
            str(ev.session_count),
            f"${ev.total_waste_usd:.2f}",
        )
    con.print(table)

    # Patches
    if report.patches:
        con.print(Rule("Recommended CLAUDE.md patches"))
        for patch in report.patches:
            con.print(f"\n{patch.description}")
            syntax = Syntax(patch.unified_diff, "diff", theme="monokai", word_wrap=True)
            con.print(syntax)


def render_harvest_results(
    results: list,  # list[ApplyResult] — avoid circular import
    *,
    dry_run: bool = False,
    console: Console | None = None,
) -> None:
    """Render harvest ApplyResult list to terminal."""
    from cctx.harvest import ApplyStatus

    con = console or _default_console()

    if not results:
        con.print("No patches to apply. Session looks clean.")
        return

    total = len(results)
    for i, result in enumerate(results, start=1):
        if result.status == ApplyStatus.SKIPPED:
            con.print(
                Text(
                    f"already present ({result.message.removeprefix('already present: ')}) "
                    f"— skipping",
                    style="dim",
                )
            )
            continue

        title_style = "red" if result.status == ApplyStatus.APPLIED else "dim"
        title = f"Patch {i} of {total} — {result.patch.finding_kind.value}"
        syntax = Syntax(result.patch.unified_diff, "diff", theme="monokai", word_wrap=True)
        panel = Panel(
            syntax,
            title=title,
            title_align="left",
            border_style=title_style,
            subtitle=Text(result.patch.evidence_summary, style="dim"),
            subtitle_align="left",
        )
        con.print(panel)

    applied_count = sum(1 for r in results if r.status == ApplyStatus.APPLIED)
    if dry_run:
        con.print("Dry run complete. No changes made.")
    else:
        con.print(f"Applied {applied_count} patch(es).")
