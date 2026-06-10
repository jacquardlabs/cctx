"""cctx CLI — click + rich-click entry point.

Commands:
  cctx ls [project]                List projects or sessions
  cctx autopsy <session>           Single-session diagnosis
  cctx autopsy <project> --since   Cross-session aggregation
  cctx export <session>            Export session data as JSONL or CSV
  cctx trace <session>             Interactive TUI trace viewer
  cctx harvest <session>           Apply autopsy patches to CLAUDE.md
  cctx harvest <project> --since   Cross-session harvest
  cctx watch [project]             Live waste signals during an active session
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO

import rich_click as click

from cctx import diagnostician
from cctx.agents import live_sessions as _live_sessions
from cctx.diagnostician import aggregate
from cctx.diagnostician.patterns import project_specific
from cctx.discovery import complete_project as _complete_project
from cctx.harvest import EMIT_TARGETS
from cctx.models import KIND_LABEL, AggregateReport
from cctx.parsers.claude_code import parse_session
from cctx.recommender import claude_md
from cctx.recommender import evidence as evidence_mod
from cctx.renderers.terminal import (
    render_aggregate,
    render_aggregate_drilldown,
    render_diagnosis,
    render_harvest_results,
    render_projects,
    render_sessions,
    render_turn,
)
from cctx.tokenizer import tokenize_session

UTC = timezone.utc


def parse_since(value: str) -> tuple[datetime, datetime, str]:
    """Parse --since value into (start, end, label) UTC datetimes.

    Formats accepted:
      "7"               → last 7 days
      "7d"              → last 7 days
      "2w"              → last 14 days
      "2026-05-01"      → since that date (UTC midnight) until now
      "2026-05-01..2026-05-15"  → explicit range (end is inclusive, midnight)
    """
    now = datetime.now(UTC)
    stripped = value.strip()

    # Date range: "YYYY-MM-DD..YYYY-MM-DD"
    if ".." in stripped:
        parts = stripped.split("..", 1)
        if len(parts) != 2:
            raise click.UsageError(
                f"Invalid --since range '{value}'. Expected YYYY-MM-DD..YYYY-MM-DD"
            )
        try:
            start = datetime.fromisoformat(parts[0].strip()).replace(tzinfo=UTC)
            end = datetime.fromisoformat(parts[1].strip()).replace(tzinfo=UTC)
            end = end.replace(hour=23, minute=59, second=59)
        except ValueError:
            raise click.UsageError(
                f"Invalid date in --since '{value}'. Expected YYYY-MM-DD..YYYY-MM-DD"
            ) from None
        return start, end, f"{parts[0].strip()}..{parts[1].strip()}"

    # Absolute date: "YYYY-MM-DD"
    if len(stripped) == 10 and stripped[4] == "-" and stripped[7] == "-":
        try:
            start = datetime.fromisoformat(stripped).replace(tzinfo=UTC)
        except ValueError:
            raise click.UsageError(
                f"Invalid date '{value}'. Expected YYYY-MM-DD"
            ) from None
        return start, now, f"since {stripped}"

    # Relative: "7", "7d", "2w"
    stripped_lower = stripped.lower()
    if stripped_lower.endswith("w"):
        try:
            weeks = int(stripped_lower[:-1])
        except ValueError:
            raise click.UsageError(
                f"Invalid --since value '{value}'. Expected integer weeks, e.g. 2w"
            ) from None
        delta = timedelta(weeks=weeks)
        label = f"last {weeks * 7} days"
    elif stripped_lower.endswith("d"):
        try:
            days = int(stripped_lower[:-1])
        except ValueError:
            raise click.UsageError(
                f"Invalid --since value '{value}'. Expected integer days, e.g. 7d"
            ) from None
        delta = timedelta(days=days)
        label = f"last {days} days"
    else:
        try:
            days = int(stripped)
        except ValueError:
            raise click.UsageError(
                f"Invalid --since value '{value}'. "
                "Use an integer (7), a shorthand (7d, 2w), or a date (2026-05-01) "
                "or range (2026-05-01..2026-05-15)."
            ) from None
        delta = timedelta(days=days)
        label = f"last {days} days"

    return now - delta, now, label

click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True


def _aggregate_drilldown(report: AggregateReport, diagnoses: list) -> None:
    """Prompt user to drill into a pattern from an aggregate report (TTY only)."""
    import sys
    if not report.by_kind or not sys.stdout.isatty():
        return
    kinds = list(report.by_kind.keys())
    click.echo()
    for i, kind in enumerate(kinds, 1):
        label = KIND_LABEL.get(kind, kind.value)
        click.echo(f"  {i}. {label}")
    val = click.prompt(
        "\nInspect pattern (1–N) or Enter to exit",
        default="",
        show_default=False,
    )
    val = val.strip()
    if not val:
        return
    if val.isdigit() and 0 <= (idx := int(val) - 1) < len(kinds):
        render_aggregate_drilldown(diagnoses, kinds[idx])
    else:
        click.echo(f"Invalid selection: {val!r}")


def _render_check_findings(findings: list, target_dir: Path) -> None:
    """Print harvest --check results to stdout using rich."""
    from rich.console import Console
    from rich.rule import Rule

    from cctx.harvest import CheckIssue, CheckSeverity

    con = Console()
    claude_md_path = target_dir / "CLAUDE.md"
    con.print(Rule(f"cctx harvest --check — {claude_md_path}"))
    if not findings:
        con.print("✓ CLAUDE.md looks clean — no issues found.")
        return
    con.print(f"{len(findings)} issue(s) found:\n")
    _ISSUE_LABEL = {
        CheckIssue.DEAD_FILE_REF:    "dead file reference",
        CheckIssue.DEAD_SKILL_REF:   "dead skill reference",
        CheckIssue.EMPTY_SECTION:    "empty section",
        CheckIssue.CONTRADICTION:    "contradiction",
        CheckIssue.REDUNDANCY:       "redundancy",
        CheckIssue.STALE_IDENTIFIER: "stale identifier",
    }
    _SEV_BADGE = {
        CheckSeverity.HIGH:   "[HIGH]",
        CheckSeverity.MEDIUM: "[MED]",
        CheckSeverity.LOW:    "[LOW]",
    }
    for f in findings:
        badge = _SEV_BADGE.get(f.severity, "      ")
        label = _ISSUE_LABEL.get(f.issue, f.issue.value)
        con.print(f"  {badge:<6}  {f.heading}  {label}: {f.detail}")


@click.group()
def cli() -> None:
    """cctx — find out why your Claude Code session went sideways."""


@cli.command("ls")
@click.argument(
    "project",
    required=False,
    type=click.Path(exists=True, path_type=Path),
    shell_complete=lambda c, p, i: _complete_project(c, p, i),
)
def ls(project: Path | None) -> None:
    """List Claude Code projects and sessions.

    With no arguments, lists all projects in ~/.claude/projects/.

    With PROJECT (a local project directory), lists sessions for that project.
    """
    from cctx.discovery import ProjectInfo, find_project_dir, list_projects, list_sessions

    live_statuses = {s.session_id: s.status for s in _live_sessions()}

    if project is None:
        projects = list_projects()
        render_projects(projects, live_statuses=live_statuses)
    else:
        cwd = project if project.is_dir() else project.parent
        project_dir = find_project_dir(cwd)
        if project_dir is None:
            raise click.UsageError(
                f"No Claude Code sessions found for {cwd}.\n"
                "Check that ~/.claude/projects/ contains a matching directory."
            )
        sessions = list_sessions(project_dir)
        info = ProjectInfo(
            project_dir=project_dir,
            display_name=str(cwd).replace(str(Path.home()), "~"),
            sessions=sessions,
        )
        render_sessions(info, live_statuses=live_statuses)


@cli.command()
@click.argument(
    "target",
    required=False,
    type=click.Path(path_type=Path),
    shell_complete=lambda c, p, i: _complete_project(c, p, i),
)
@click.option(
    "--since",
    default=None,
    metavar="PERIOD",
    type=str,
    help="Cross-session mode: 7, 7d, 2w, 2026-05-01, or 2026-05-01..2026-05-15.",
)
@click.option(
    "--until",
    "until_date",
    default=None,
    metavar="DATE",
    type=str,
    help="End date for --since window (YYYY-MM-DD). Requires --since.",
)
@click.option(
    "--latest",
    is_flag=True,
    default=False,
    help="Diagnose the most recent session in TARGET project (default: cwd).",
)
@click.option(
    "--html",
    "html_out",
    default=None,
    metavar="FILE",
    type=click.Path(path_type=Path),
    help="Write a self-contained HTML report to FILE (single-session only).",
)
@click.option(
    "--github-summary",
    "github_summary",
    is_flag=True,
    default=False,
    help="Append findings as markdown to $GITHUB_STEP_SUMMARY (single-session only).",
)
@click.option(
    "--fail-on-findings",
    "fail_on_findings",
    is_flag=True,
    default=False,
    help="Exit 1 if any findings are detected (single-session only).",
)
@click.option(
    "--top",
    "top_n",
    default=None,
    metavar="N",
    type=click.IntRange(min=1),
    help="Show only the top N patterns by session count (--since mode only).",
)
@click.option(
    "--turn",
    "turn_num",
    default=None,
    metavar="N",
    type=click.IntRange(min=1),
    help="Show details for turn N (single-session only).",
)
@click.option(
    "--json",
    "json_out",
    is_flag=True,
    default=False,
    help="Output diagnosis as JSON to stdout (single-session only).",
)
def autopsy(
    target: Path | None,
    since: str | None,
    until_date: str | None,
    latest: bool,
    html_out: Path | None,
    github_summary: bool,
    fail_on_findings: bool,
    top_n: int | None,
    turn_num: int | None,
    json_out: bool,
) -> None:
    """Diagnose a session or project directory.

    TARGET is a session JSONL file for single-session diagnosis,
    or a project directory for --since cross-session aggregation.

    Use --latest to automatically pick the most recent session in a project.
    """
    from cctx.discovery import find_project_dir
    from cctx.discovery import latest_session as _latest_session

    if latest and since is not None:
        raise click.UsageError("--latest and --since are mutually exclusive.")
    if fail_on_findings and since is not None:
        raise click.UsageError("--fail-on-findings is not supported with --since.")
    if top_n is not None and since is None:
        raise click.UsageError("--top requires --since.")
    if turn_num is not None and since is not None:
        raise click.UsageError("--turn is not supported with --since.")
    if until_date is not None and since is None:
        raise click.UsageError("--until requires --since.")
    if json_out and since is not None:
        raise click.UsageError("--json is not supported with --since.")

    if target is None:
        if not latest:
            raise click.UsageError(
                "TARGET is required. Pass a session .jsonl file, a project directory, "
                "or use --latest to pick the most recent session."
            )
        target = Path.cwd()

    if not target.exists():
        raise click.UsageError(f"Path does not exist: {target}")

    # Resolve a directory to its latest session (explicit --latest or implicit when
    # a directory is passed without --since).
    if target.is_dir() and since is None:
        # Accept both local project dirs (~/Projects/foo) and encoded claude dirs
        session = _latest_session(target)  # works if target IS the .claude/projects dir
        if session is None:
            project_dir = find_project_dir(target)
            if project_dir is not None:
                session = _latest_session(project_dir)
        if session is None:
            raise click.UsageError(
                f"No Claude Code sessions found for {target}.\n"
                "Check that ~/.claude/projects/ contains a matching directory."
            )
        target = session

    if since is not None:
        if html_out is not None:
            raise click.UsageError("--html is not supported with --since.")
        if github_summary:
            raise click.UsageError("--github-summary is not supported with --since.")
        # Cross-session path
        project_dir = target if target.is_dir() else target.parent
        start, end, label = parse_since(since)
        if until_date is not None:
            try:
                end = datetime.fromisoformat(until_date.strip()).replace(
                    tzinfo=UTC, hour=23, minute=59, second=59
                )
            except ValueError:
                raise click.UsageError(
                    f"Invalid --until date '{until_date}'. Expected YYYY-MM-DD."
                ) from None
            label = f"{label} until {until_date.strip()}"
        pairs = aggregate.run(project_dir, start, end)
        diagnoses = [d for d, _ in pairs]
        ev = evidence_mod.accumulate(diagnoses)
        if top_n is not None:
            ev = dict(sorted(ev.items(), key=lambda x: x[1].session_count, reverse=True)[:top_n])
        patterns = project_specific.detect(pairs)
        pattern_patches = claude_md.generate_from_patterns(patterns)
        patches = claude_md.generate_from_evidence(ev) + pattern_patches
        report = AggregateReport(
            period_label=label,
            sessions_analysed=len(diagnoses),
            sessions_with_findings=sum(1 for d in diagnoses if d.findings),
            total_cost_usd=sum(d.total_cost_usd for d in diagnoses),
            waste_cost_usd=sum(d.waste_cost_usd for d in diagnoses),
            by_kind=ev,
            patches=patches,
            project_patterns=patterns,
        )
        render_aggregate(report)
        _aggregate_drilldown(report, diagnoses)
    else:
        # Single-session path
        if target.is_dir():
            raise click.UsageError(
                "TARGET is a directory. Use --since N for cross-session mode, "
                "or pass a .jsonl file directly."
            )
        trace = tokenize_session(parse_session(target))
        diagnosis = diagnostician.run(trace)
        diagnosis = claude_md.generate(diagnosis)
        if json_out:
            import json as _json

            from cctx.exporters.jsonl import export_diagnosis as _export_diag
            click.echo(_json.dumps(_json.loads(_export_diag(diagnosis, trace)), indent=2))
        elif turn_num is not None:
            render_turn(trace, diagnosis, turn_num)
        elif html_out is not None:
            from cctx.renderers.report import render_html
            html_out.write_text(render_html(diagnosis, trace), encoding="utf-8")
            click.echo(f"HTML report written to {html_out}")
        elif github_summary:
            from cctx.renderers.github import write_github_summary
            write_github_summary(diagnosis)
        else:
            render_diagnosis(diagnosis, session_path=target)
        if fail_on_findings and diagnosis.findings:
            raise SystemExit(1)


@cli.command()
@click.argument("target", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["jsonl", "csv", "json"]),
    default="jsonl",
    show_default=True,
    help="Output format: jsonl (one object per session), csv (one row per turn), or json (array).",
)
@click.option(
    "--out",
    type=click.Path(path_type=Path),
    default=None,
    help="Write output to FILE instead of stdout.",
)
@click.option(
    "--no-content",
    is_flag=True,
    default=False,
    help="Omit text content (finding summaries, patch diffs).",
)
def export(target: Path, fmt: str, out: Path | None, no_content: bool) -> None:
    """Export session data in machine-readable format.

    TARGET is a session JSONL file.
    """
    import sys

    from cctx.exporters import csv as csv_mod
    from cctx.exporters import json as json_mod
    from cctx.exporters import jsonl as jsonl_mod

    trace = tokenize_session(parse_session(target))
    diagnosis = diagnostician.run(trace)
    diagnosis = claude_md.generate(diagnosis)
    pairs = [(diagnosis, trace)]

    def _write(fh: IO[str]) -> None:
        if fmt == "jsonl":
            jsonl_mod.write(pairs, fh, include_content=not no_content)
        elif fmt == "json":
            json_mod.write(pairs, fh, include_content=not no_content)
        else:
            csv_mod.write(pairs, fh)

    if out is not None:
        with open(out, "w", encoding="utf-8") as fh:
            _write(fh)
    else:
        _write(sys.stdout)


@cli.command()
@click.argument(
    "target",
    required=False,
    type=click.Path(path_type=Path),
)
@click.option(
    "--latest",
    is_flag=True,
    default=False,
    help="Open the most recent session in TARGET project (default: cwd).",
)
def trace(target: Path | None, latest: bool) -> None:
    """Open an interactive TUI trace viewer for a session.

    TARGET is a session JSONL file or project directory.
    Use --latest to automatically pick the most recent session.
    """
    from cctx.discovery import find_project_dir
    from cctx.discovery import latest_session as _latest_session
    from cctx.renderers.trace_tui import launch

    if target is None:
        if not latest:
            raise click.UsageError(
                "TARGET is required. Pass a session .jsonl file, a project directory, "
                "or use --latest to pick the most recent session."
            )
        target = Path.cwd()

    if not target.exists():
        raise click.UsageError(f"Path does not exist: {target}")

    if target.is_dir():
        session_path = _latest_session(target)
        if session_path is None:
            project_dir = find_project_dir(target)
            if project_dir is not None:
                session_path = _latest_session(project_dir)
        if session_path is None:
            raise click.UsageError(
                f"No Claude Code sessions found for {target}.\n"
                "Check that ~/.claude/projects/ contains a matching directory."
            )
        target = session_path

    session = tokenize_session(parse_session(target))
    diagnosis = diagnostician.run(session)
    diagnosis = claude_md.generate(diagnosis)
    launch(session, diagnosis)


@cli.command()
@click.argument("target", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--since",
    default=None,
    metavar="PERIOD",
    type=str,
    help="Cross-session mode: 7, 7d, 2w, 2026-05-01, or 2026-05-01..2026-05-15.",
)
@click.option(
    "--apply",
    "apply_mode",
    is_flag=True,
    default=False,
    help="Apply patches without interactive confirmation.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would change and exit 0; do not write.",
)
@click.option(
    "--target-dir",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory containing CLAUDE.md (default: cwd).",
)
@click.option(
    "--check",
    "check_mode",
    is_flag=True,
    default=False,
    help="Audit existing CLAUDE.md for dead references and empty sections. Exit 1 if findings.",
)
@click.option(
    "--check-severity",
    "check_severity",
    default="MEDIUM",
    type=click.Choice(["LOW", "MEDIUM", "HIGH"], case_sensitive=False),
    show_default=True,
    help="Minimum severity that causes --check to exit 1.",
)
@click.option(
    "--emit",
    "emit_targets",
    multiple=True,
    type=click.Choice(list(EMIT_TARGETS)),
    help="Also write applicable patches to another agent's instruction file "
         "(e.g. AGENTS.md). Repeatable.",
)
@click.option(
    "--sync",
    "sync_mode",
    is_flag=True,
    default=False,
    help="With --emit: also mirror already-harvested cctx-managed sections "
         "from CLAUDE.md into the emit target.",
)
def harvest(
    target: Path,
    since: str | None,
    apply_mode: bool,
    dry_run: bool,
    target_dir: Path | None,
    check_mode: bool,
    check_severity: str,
    emit_targets: tuple[str, ...],
    sync_mode: bool,
) -> None:
    """Apply autopsy patches to CLAUDE.md."""
    from cctx.harvest import (
        apply_patches,
        check_claude_md,
        preview_patches,
        retarget_patches,
        sync_managed_sections,
    )

    if sync_mode and not emit_targets:
        raise click.UsageError("--sync requires --emit.")

    if check_mode:
        from cctx.harvest import CheckSeverity
        resolved_dir = target_dir or Path.cwd()
        findings = check_claude_md(resolved_dir)
        _render_check_findings(findings, resolved_dir)
        _SEVERITY_ORDER = {
            CheckSeverity.LOW: 0,
            CheckSeverity.MEDIUM: 1,
            CheckSeverity.HIGH: 2,
        }
        threshold = CheckSeverity(check_severity.lower())
        triggering = [
            f for f in findings
            if _SEVERITY_ORDER[f.severity] >= _SEVERITY_ORDER[threshold]
        ]
        raise SystemExit(1 if triggering else 0)

    if apply_mode and dry_run:
        raise click.UsageError("--apply and --dry-run are mutually exclusive.")

    resolved_dir = target_dir or Path.cwd()
    claude_md_path = resolved_dir / "CLAUDE.md"
    click.echo(f"Target: {claude_md_path}")

    if since is not None:
        project_dir = target if target.is_dir() else target.parent
        start, end, _label = parse_since(since)
        pairs = aggregate.run(project_dir, start, end)
        diagnoses = [d for d, _ in pairs]
        ev = evidence_mod.accumulate(diagnoses)
        # project_specific.detect() intentionally omitted: pattern patches need human review
        # (autopsy shows them; harvest doesn't auto-apply).
        patches = claude_md.generate_from_evidence(ev)
    else:
        if target.is_dir():
            raise click.UsageError(
                "TARGET is a directory. Use --since N for cross-session mode, "
                "or pass a .jsonl file directly."
            )
        trace = tokenize_session(parse_session(target))
        diagnosis = diagnostician.run(trace)
        diagnosis = claude_md.generate(diagnosis)
        patches = diagnosis.patches

    base = patches
    for t in emit_targets:
        emitted = retarget_patches(base, t)
        if sync_mode:
            emitted = emitted + sync_managed_sections(resolved_dir, t)
        patches = patches + emitted

    if not patches:
        render_harvest_results([], dry_run=dry_run)
        return

    if dry_run:
        results = preview_patches(patches, resolved_dir)
        render_harvest_results(results, dry_run=True)
        return

    if apply_mode:
        results = apply_patches(patches, resolved_dir)
        render_harvest_results(results)
        return

    preview = preview_patches(patches, resolved_dir)
    render_harvest_results(preview, dry_run=True)
    applicable = sum(1 for r in preview if r.status.value == "applied")
    if applicable == 0:
        return
    if click.confirm(f"Apply {applicable} patch(es)?"):
        results = apply_patches(patches, resolved_dir)
        render_harvest_results(results)


@cli.command()
@click.argument(
    "target",
    required=False,
    type=click.Path(path_type=Path),
    shell_complete=lambda c, p, i: _complete_project(c, p, i),
)
def watch(target: Path | None) -> None:
    """Watch an active Claude Code session for waste signals in real time.

    TARGET is a project directory (defaults to cwd). New findings are printed
    as they are detected. Exits after 30s of session inactivity or Ctrl+C.
    """
    from cctx.watcher import watch as _watch
    _watch(target)
