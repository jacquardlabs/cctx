"""Terminal renderer for autopsy Diagnosis output.

render_diagnosis(diagnosis, console=None) -> None
render_aggregate(report, console=None) -> None
render_harvest_results(results, dry_run=False, console=None) -> None
render_projects(projects, live_statuses=None, console=None) -> None
render_sessions(project, live_statuses=None, console=None) -> None
render_efficacy_report(report, target_dir, project_dir, console=None) -> None

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
    from cctx.models import (
        AggregateReport,
        CrossProjectDigest,
        Diagnosis,
        EfficacyReport,
        EfficacyRow,
        SessionTrace,
    )

_SEVERITY_STYLE = {
    Severity.HIGH:   "bold red",
    Severity.MEDIUM: "bold yellow",
    Severity.LOW:    "bold green",
}

_KIND_LABEL = KIND_LABEL


def _default_console() -> Console:
    return Console()


def _wide_console() -> Console:
    """Console with fixed wide width to prevent table cell wrapping."""
    return Console(width=200)


def compute_health_grade(diagnosis: Diagnosis) -> str:
    """A–F grade based on waste fraction and finding severity."""
    if not diagnosis.findings:
        return "A"

    has_high = any(f.severity == Severity.HIGH for f in diagnosis.findings)
    waste_frac = (
        diagnosis.waste_cost_usd / diagnosis.total_cost_usd
        if diagnosis.total_cost_usd > 0
        else 0.0
    )

    if has_high and waste_frac > 0.50:
        return "F"
    if has_high or waste_frac > 0.25:
        return "D"
    if waste_frac > 0.10:
        return "C"
    if diagnosis.findings:
        return "B"
    return "A"


def render_diagnosis(
    diagnosis: Diagnosis,
    *,
    session_path: Path | None = None,
    console: Console | None = None,
    show_health: bool = False,
) -> None:
    con = console or _default_console()

    # Header
    con.print(Rule(f"cctx autopsy — session {diagnosis.session_id}"))
    verdict = diagnosis.verdict
    verdict_style = "bold green" if not diagnosis.findings else "bold red"
    con.print(Text(f"Verdict: {verdict}", style=verdict_style))
    if diagnosis.findings:
        con.print(Text(diagnosis.kind_summary, style="dim"))
    subagent_sum = sum(a.total_cost_usd for a in diagnosis.subagent_costs if a.depth == 1)
    n_sub = len([a for a in diagnosis.subagent_costs if a.depth == 1])
    cost_line = f"Session cost: ~${diagnosis.total_cost_usd:.2f}"
    if n_sub:
        cost_line += (
            f" (includes {n_sub} subagent{'s' if n_sub != 1 else ''}: ~${subagent_sum:.2f})"
        )
    if diagnosis.waste_cost_usd > 0:
        pct = (
            diagnosis.waste_cost_usd / diagnosis.total_cost_usd * 100
            if diagnosis.total_cost_usd
            else 0
        )
        cost_line += f" | Attributed waste: ~${diagnosis.waste_cost_usd:.2f} ({pct:.0f}%)"
    con.print(cost_line)
    con.print(Text(
        "~85–95% of actual billing; system framing not observable in JSONL", style="dim"
    ))

    if show_health:
        grade = compute_health_grade(diagnosis)
        waste_frac = (
            diagnosis.waste_cost_usd / diagnosis.total_cost_usd * 100
            if diagnosis.total_cost_usd > 0
            else 0.0
        )
        con.print(f"Health grade: {grade}  (waste {waste_frac:.0f}% of session cost)")

    if diagnosis.subagent_costs:
        show_depth = any(a.depth > 1 for a in diagnosis.subagent_costs)
        tbl = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        tbl.add_column("Subagent", no_wrap=False, max_width=48)
        if show_depth:
            tbl.add_column("Depth", justify="right", width=6)
        tbl.add_column("Cost", justify="right", width=8)
        for a in diagnosis.subagent_costs:
            label = a.label if len(a.label) <= 45 else a.label[:44] + "…"
            cost_cell = f"${a.total_cost_usd:.3f}"
            if show_depth:
                tbl.add_row(label, str(a.depth), cost_cell)
            else:
                tbl.add_row(label, cost_cell)
        con.print(tbl)

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
        if show_health and finding.cost_usd is not None:
            con.print(f"  → savings if fixed: ~${finding.cost_usd:.2f}")

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

    if not report.by_kind and not report.project_patterns:
        con.print("\nNo findings across sessions.")
        return

    # Summary table
    if report.by_kind:
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

    # Project-specific patterns
    if report.project_patterns:
        con.print()
        pp_table = Table(title="Project-specific patterns")
        pp_table.add_column("Failure", style="bold")
        pp_table.add_column("Fix")
        pp_table.add_column("Sessions", justify="right", style="dim")
        pp_table.add_column("Avg turns", justify="right", style="dim")
        pp_table.add_column("Waste", justify="right")
        for pp in report.project_patterns:
            pp_table.add_row(
                pp.failure_key,
                pp.fix_key,
                str(pp.session_count),
                f"{pp.avg_wasted_turns:.1f}",
                f"~${pp.total_waste_usd:.2f}",
            )
        con.print(pp_table)


def render_aggregate_drilldown(
    diagnoses: list,
    kind: FindingKind,
    *,
    console: Console | None = None,
) -> None:
    """Print per-session findings for a specific FindingKind."""

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


def render_turn(
    trace: SessionTrace,
    diagnosis: Diagnosis,
    turn_num: int,
    *,
    console: Console | None = None,
) -> None:
    """Render details for a single turn N from a session."""
    con = console or _default_console()

    turn = next((t for t in trace.turns if t.turn_number == turn_num), None)
    if turn is None:
        con.print(Text(
            f"Turn {turn_num} not found (session has {len(trace.turns)} turns).",
            style="red",
        ))
        return

    con.print(Rule(f"Turn {turn_num} — {turn.role} — {turn.timestamp.strftime('%H:%M:%S')}"))

    text = turn.text
    if text:
        preview = text[:500]
        if len(text) > 500:
            preview += f"\n… [{len(text) - 500} more chars]"
        con.print(preview)

    for tu in turn.tool_uses:
        con.print(Text(f"  tool_use: {tu.tool_name}", style="cyan"))

    for tr in turn.tool_results:
        style = "red" if tr.is_error else "dim"
        content = tr.content
        preview = content[:200] + ("…" if len(content) > 200 else "")
        con.print(Text(f"  tool_result ({tr.tool_name}): {preview}", style=style))

    # Findings that span this turn
    touching = [
        f for f in diagnosis.findings
        if f.first_turn <= turn_num <= (f.last_turn or f.first_turn)
    ]
    if touching:
        con.print()
        con.print(Text("Findings active at this turn:", style="bold"))
        for finding in touching:
            style = _SEVERITY_STYLE.get(finding.severity, "")
            label = _KIND_LABEL.get(finding.kind, finding.kind.value.upper())
            con.print(Text(f"  [{label}]", style=style), finding.summary)


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
        kind_label = _KIND_LABEL.get(
            result.patch.finding_kind, result.patch.finding_kind.value.upper()
        )
        title = f"Patch {i} of {total} — {kind_label}"
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


def render_projects(
    projects: list[ProjectInfo],
    *,
    live_statuses: dict[str, str] | None = None,
    console: Console | None = None,
) -> None:
    con = console or _default_console()

    if not projects:
        con.print("No projects found in ~/.claude/projects/.")
        return

    _live = live_statuses or {}
    live_project_ids: set[str] = {
        proj.project_dir.name
        for proj in projects
        for s in proj.sessions
        if s.session_id in _live
    }

    con.print(Rule("cctx — projects"))
    table = Table(show_header=True, box=None, pad_edge=False, show_edge=False)
    table.add_column("Project", style="bold")
    table.add_column("Sessions", justify="right", style="dim")
    table.add_column("Last session", style="dim")
    table.add_column("Status")

    for proj in projects:
        last = proj.latest_time.strftime("%Y-%m-%d") if proj.latest_time else "—"
        if proj.project_dir.name in live_project_ids:
            status_cell = Text("● live", style="green bold")
        else:
            status_cell = Text("")
        table.add_row(
            proj.display_name,
            str(proj.session_count),
            last,
            status_cell,
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


def render_sessions(
    project: ProjectInfo,
    *,
    live_statuses: dict[str, str] | None = None,
    console: Console | None = None,
) -> None:
    con = console or _default_console()
    _live = live_statuses or {}

    con.print(Rule(f"cctx — {project.display_name}"))
    if not project.sessions:
        con.print("No sessions found.")
        return

    table = Table(show_header=True, box=None, pad_edge=False, show_edge=False)
    table.add_column("Session", style="bold")
    table.add_column("Date", style="dim")
    table.add_column("Branch", style="dim")
    table.add_column("Path", style="dim")
    table.add_column("Status")

    for s in project.sessions:
        date_str = s.start_time.strftime("%Y-%m-%d %H:%M") if s.start_time else "—"
        if s.session_id in _live:
            status_cell = Text(f"● {_live[s.session_id]}", style="green bold")
        else:
            status_cell = Text("")
        table.add_row(
            s.session_id[:8],
            date_str,
            s.git_branch or "—",
            str(s.path),
            status_cell,
        )
    con.print(table)
    con.print()
    con.print(
        Text("cctx autopsy <path>", style="bold") +
        Text("  to diagnose a session", style="dim")
    )


def _efficacy_signal(row: EfficacyRow) -> str:
    """Classify efficacy: ✓ effective | ↓ reduced | ✗ persisting | ? no baseline | ? not in git."""
    if row.applied_at is None:
        return "? not in git"
    if row.sessions_before == 0:
        return "? no baseline"
    if row.total_after == 0:
        return "? no post-patch data"
    rate_before = row.sessions_before / max(row.weeks_before, 0.5)
    rate_after  = row.sessions_after  / max(row.weeks_after,  0.5)
    low = " (low sample)" if row.total_before < 3 or row.total_after < 3 else ""
    if rate_after == 0 or rate_after < rate_before * 0.25:
        return f"✓ effective{low}"
    if rate_after < rate_before * 0.75:
        return f"↓ reduced{low}"
    return f"✗ persisting{low}"


def render_cross_project_digest(
    digest: CrossProjectDigest,
    *,
    console: Console | None = None,
) -> None:
    """Render a cross-project digest (cctx autopsy --all --since) to terminal."""
    con = console or _default_console()

    con.print(Rule(f"cctx autopsy — cross-project digest  ({digest.period_label})"))
    con.print(
        f"Projects: {len(digest.projects)} analysed  |  "
        f"Total: ${digest.total_cost_usd:.2f}  |  "
        f"Waste: ${digest.total_waste_usd:.2f}"
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Project")
    table.add_column("Sessions", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Waste", justify="right")
    table.add_column("Top pattern")
    for row in digest.projects:
        table.add_row(
            row.display_name,
            str(row.sessions_analysed),
            f"${row.total_cost_usd:.2f}",
            f"${row.waste_cost_usd:.2f}",
            row.top_pattern or "—",
        )
    con.print(table)

    if not digest.global_by_kind:
        con.print("\nNo cross-project patterns in this window.")
        return

    con.print(Rule("Global patterns (2+ projects)"))
    gt = Table(show_header=True, header_style="bold")
    gt.add_column("Pattern")
    gt.add_column("Projects", justify="right")
    gt.add_column("Sessions", justify="right")
    gt.add_column("Waste", justify="right")
    for kind, ev in digest.global_by_kind.items():
        gt.add_row(
            _KIND_LABEL.get(kind, kind.value),
            str(digest.global_project_counts.get(kind, 0)),
            str(ev.session_count),
            f"${ev.total_waste_usd:.2f}",
        )
    con.print(gt)

    if digest.global_patches:
        con.print(Rule("Recommended ~/.claude/CLAUDE.md patches"))
        for patch in digest.global_patches:
            con.print(f"\n{patch.description}  [{patch.target_file}]")
            syntax = Syntax(patch.unified_diff, "diff", theme="monokai", word_wrap=True)
            con.print(syntax)


def render_efficacy_report(
    report: EfficacyReport,
    target_dir: Path,
    project_dir: Path,
    *,
    console: Console | None = None,
) -> None:
    """Render patch efficacy table to terminal."""
    con = console or _default_console()

    if report.total_sessions == 0:
        con.print(f"No sessions found in {project_dir}.")
        return

    if not report.rows:
        con.print(f"No managed headings found in CLAUDE.md at {target_dir / 'CLAUDE.md'}.")
        return

    range_str = ""
    if report.oldest_session and report.newest_session:
        oldest = report.oldest_session.strftime("%Y-%m-%d")
        newest = report.newest_session.strftime("%Y-%m-%d")
        range_str = f"   Range: {oldest} — {newest}"
    con.print(Rule("cctx harvest --efficacy"))
    con.print(f"Sessions: {report.total_sessions}{range_str}")
    con.print(f"CLAUDE.md: {target_dir / 'CLAUDE.md'}")
    con.print()

    _SIGNAL_STYLE = {
        "✓": "bold green",
        "↓": "bold yellow",
        "✗": "bold red",
        "?": "dim",
    }

    # Build table for heading + applied + before/after counts.
    # Signal is printed as a separate styled line per row so it is never
    # truncated or wrapped regardless of terminal width.
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
    table.add_column("Heading", style="bold", no_wrap=True)
    table.add_column("Applied", no_wrap=True)
    table.add_column("Before", no_wrap=True)
    table.add_column("After", no_wrap=True)

    row_signals: list[tuple[str, str]] = []  # (signal_text, style)

    for row in report.rows:
        if row.applied_at is None:
            applied_str = "(not in git)"
            before_str = "—"
        else:
            applied_str = row.applied_at.strftime("%Y-%m-%d")
            before_str = f"{row.sessions_before}/{row.total_before} sessions"
        after_str = f"{row.sessions_after}/{row.total_after} sessions"
        signal = _efficacy_signal(row)
        first_char = signal[0] if signal else "?"
        signal_style = _SIGNAL_STYLE.get(first_char, "")
        table.add_row(row.heading, applied_str, before_str, after_str)
        row_signals.append((signal, signal_style))

    con.print(table)
    con.print()
    for (signal, style), row in zip(row_signals, report.rows, strict=True):
        prefix = Text(f"  {row.heading}: ", style="dim")
        signal_text = Text(signal, style=style)
        con.print(prefix + signal_text, soft_wrap=True)
