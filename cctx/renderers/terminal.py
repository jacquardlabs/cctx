"""Terminal renderer for autopsy Diagnosis output.

render_diagnosis(diagnosis, console=None) -> None
render_aggregate(report, console=None) -> None
render_harvest_results(results, dry_run=False, console=None) -> None
render_projects(projects, console=None) -> None
render_sessions(project, console=None) -> None

Uses rich for formatting. Accepts an optional Console for testing.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from cctx.models import KIND_LABEL, FindingKind, Severity

if TYPE_CHECKING:
    from cctx.discovery import ProjectInfo
    from cctx.models import AggregateReport, Diagnosis

_SEVERITY_STYLE = {
    Severity.HIGH:   "bold red",
    Severity.MEDIUM: "bold yellow",
    Severity.LOW:    "bold green",
}

_KIND_LABEL = KIND_LABEL


def _default_console() -> Console:
    return Console()


def render_diagnosis(
    diagnosis: Diagnosis,
    *,
    session_path: Path | None = None,
    console: Console | None = None,
) -> None:
    con = console or _default_console()

    # Header
    con.print(Rule(f"cctx autopsy — session {diagnosis.session_id}"))
    cost_line = f"Session cost: ~${diagnosis.total_cost_usd:.2f}"
    if diagnosis.waste_cost_usd > 0:
        pct = (
            diagnosis.waste_cost_usd / diagnosis.total_cost_usd * 100
            if diagnosis.total_cost_usd
            else 0
        )
        cost_line += f" | Attributed waste: ~${diagnosis.waste_cost_usd:.2f} ({pct:.0f}%)"
    con.print(cost_line)
    con.print(Text("~85–95% of actual billing; system framing not observable in JSONL", style="dim"))

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

    if session_path is not None:
        con.print()
        con.print(
            Text("cctx trace ", style="bold")
            + Text(str(session_path), style="dim")
            + Text("  to step through this session interactively", style="dim")
        )


def render_aggregate(report: AggregateReport, *, console: Console | None = None) -> None:
    con = console or _default_console()

    con.print(Rule(f"cctx autopsy — {report.period_label}"))
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


def render_aggregate_drilldown(
    diagnoses: list,
    kind: FindingKind,
    *,
    console: Console | None = None,
) -> None:
    """Print per-session findings for a specific FindingKind."""
    from cctx.models import Diagnosis  # local import — avoids circular at module level

    con = console or _default_console()
    label = _KIND_LABEL.get(kind, kind.value)
    con.print(Rule(f"{label} — per-session detail"))

    table = Table(show_header=True, box=None, pad_edge=False, show_edge=False)
    table.add_column("Session", style="bold")
    table.add_column("Cost", justify="right", style="dim")
    table.add_column("Summary")

    found = False
    for d in diagnoses:
        for f in d.findings:
            if f.kind is kind:
                table.add_row(
                    d.session_id[:12],
                    f"~${d.total_cost_usd:.2f}",
                    f.summary,
                )
                found = True

    if found:
        con.print(table)
    else:
        con.print("No matching findings.")


def render_harvest_results(
    results: list,  # list[ApplyResult] — ApplyStatus is harvest-internal; imported lazily
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

        if result.status == ApplyStatus.APPLIED:
            title_style = "green"
        elif result.status == ApplyStatus.ERROR:
            title_style = "red"
        else:
            title_style = "dim"
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


def render_projects(projects: list[ProjectInfo], *, console: Console | None = None) -> None:
    con = console or _default_console()

    if not projects:
        con.print("No projects found in ~/.claude/projects/.")
        return

    con.print(Rule("cctx — projects"))
    table = Table(show_header=True, box=None, pad_edge=False, show_edge=False)
    table.add_column("Project", style="bold")
    table.add_column("Sessions", justify="right", style="dim")
    table.add_column("Last session", style="dim")

    for proj in projects:
        last = proj.latest_time.strftime("%Y-%m-%d") if proj.latest_time else "—"
        table.add_row(
            proj.display_name,
            str(proj.session_count),
            last,
        )
    con.print(table)
    con.print()
    con.print(
        Text("cctx ls <project-path>", style="bold") +
        Text("  to list sessions in a project", style="dim")
    )
    con.print(
        Text("cctx autopsy --latest <project-path>", style="bold") +
        Text("  to diagnose the most recent session", style="dim")
    )


def render_sessions(project: ProjectInfo, *, console: Console | None = None) -> None:
    con = console or _default_console()

    con.print(Rule(f"cctx — {project.display_name}"))
    if not project.sessions:
        con.print("No sessions found.")
        return

    table = Table(show_header=True, box=None, pad_edge=False, show_edge=False)
    table.add_column("Session", style="bold")
    table.add_column("Date", style="dim")
    table.add_column("Branch", style="dim")
    table.add_column("Path", style="dim")

    for s in project.sessions:
        date_str = s.start_time.strftime("%Y-%m-%d %H:%M") if s.start_time else "—"
        table.add_row(
            s.session_id[:8],
            date_str,
            s.git_branch or "—",
            str(s.path),
        )
    con.print(table)
    con.print()
    con.print(
        Text("cctx autopsy <path>", style="bold") +
        Text("  to diagnose a session", style="dim")
    )
