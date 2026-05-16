"""cctx CLI — click + rich-click entry point.

Commands:
  cctx ls [project]                List projects or sessions
  cctx autopsy <session>           Single-session diagnosis
  cctx autopsy <project> --since   Cross-session aggregation
  cctx export <session>            Export session data as JSONL or CSV
  cctx trace <session>             Interactive TUI trace viewer
  cctx harvest <session>           Apply autopsy patches to CLAUDE.md
  cctx harvest <project> --since   Cross-session harvest
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import rich_click as click

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
            raise click.UsageError(f"Invalid --since range '{value}'. Expected YYYY-MM-DD..YYYY-MM-DD")
        try:
            start = datetime.fromisoformat(parts[0].strip()).replace(tzinfo=UTC)
            end = datetime.fromisoformat(parts[1].strip()).replace(tzinfo=UTC)
            end = end.replace(hour=23, minute=59, second=59)
        except ValueError:
            raise click.UsageError(f"Invalid date in --since '{value}'. Expected YYYY-MM-DD..YYYY-MM-DD")
        return start, end, f"{parts[0].strip()}..{parts[1].strip()}"

    # Absolute date: "YYYY-MM-DD"
    if len(stripped) == 10 and stripped[4] == "-" and stripped[7] == "-":
        try:
            start = datetime.fromisoformat(stripped).replace(tzinfo=UTC)
        except ValueError:
            raise click.UsageError(f"Invalid date '{value}'. Expected YYYY-MM-DD")
        return start, now, f"since {stripped}"

    # Relative: "7", "7d", "2w"
    stripped_lower = stripped.lower()
    if stripped_lower.endswith("w"):
        try:
            weeks = int(stripped_lower[:-1])
        except ValueError:
            raise click.UsageError(f"Invalid --since value '{value}'. Expected integer weeks, e.g. 2w")
        delta = timedelta(weeks=weeks)
        label = f"last {weeks * 7} days"
    elif stripped_lower.endswith("d"):
        try:
            days = int(stripped_lower[:-1])
        except ValueError:
            raise click.UsageError(f"Invalid --since value '{value}'. Expected integer days, e.g. 7d")
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
            )
        delta = timedelta(days=days)
        label = f"last {days} days"

    return now - delta, now, label

from cctx import diagnostician
from cctx.diagnostician import aggregate
from cctx.discovery import complete_project as _complete_project
from cctx.models import AggregateReport
from cctx.parsers.claude_code import parse_session
from cctx.recommender import claude_md
from cctx.recommender import evidence as evidence_mod
from cctx.renderers.terminal import (
    render_aggregate,
    render_diagnosis,
    render_harvest_results,
    render_projects,
    render_sessions,
)
from cctx.tokenizer import tokenize_session

click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True


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

    if project is None:
        projects = list_projects()
        render_projects(projects)
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
        render_sessions(info)


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
def autopsy(
    target: Path | None,
    since: str | None,
    latest: bool,
    html_out: Path | None,
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
        # Cross-session path
        project_dir = target if target.is_dir() else target.parent
        start, end, label = parse_since(since)
        diagnoses = aggregate.run(project_dir, start, end)
        ev = evidence_mod.accumulate(diagnoses)
        patches = claude_md.generate_from_evidence(ev)
        report = AggregateReport(
            period_label=label,
            sessions_analysed=len(diagnoses),
            sessions_with_findings=sum(1 for d in diagnoses if d.findings),
            total_cost_usd=sum(d.total_cost_usd for d in diagnoses),
            waste_cost_usd=sum(d.waste_cost_usd for d in diagnoses),
            by_kind=ev,
            patches=patches,
        )
        render_aggregate(report)
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
        if html_out is not None:
            from cctx.renderers.report import render_html
            html_out.write_text(render_html(diagnosis, trace), encoding="utf-8")
            click.echo(f"HTML report written to {html_out}")
        else:
            render_diagnosis(diagnosis, session_path=target)


@cli.command()
@click.argument("target", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["jsonl", "csv"]),
    default="jsonl",
    show_default=True,
    help="Output format: jsonl (one object per session) or csv (one row per turn).",
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
    from cctx.exporters import jsonl as jsonl_mod

    trace = tokenize_session(parse_session(target))
    diagnosis = diagnostician.run(trace)
    diagnosis = claude_md.generate(diagnosis)
    pairs = [(diagnosis, trace)]

    if out is not None:
        with open(out, "w", encoding="utf-8") as fh:
            if fmt == "jsonl":
                jsonl_mod.write(pairs, fh, include_content=not no_content)
            else:
                csv_mod.write(pairs, fh)
    elif fmt == "jsonl":
        jsonl_mod.write(pairs, sys.stdout, include_content=not no_content)
    else:
        csv_mod.write(pairs, sys.stdout)


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
def harvest(
    target: Path,
    since: str | None,
    apply_mode: bool,
    dry_run: bool,
    target_dir: Path | None,
) -> None:
    """Apply autopsy patches to CLAUDE.md."""
    from cctx.harvest import apply_patches, preview_patches

    if apply_mode and dry_run:
        raise click.UsageError("--apply and --dry-run are mutually exclusive.")

    resolved_dir = target_dir or Path.cwd()
    claude_md_path = resolved_dir / "CLAUDE.md"
    click.echo(f"Target: {claude_md_path}")

    if since is not None:
        project_dir = target if target.is_dir() else target.parent
        start, end, _label = parse_since(since)
        diagnoses = aggregate.run(project_dir, start, end)
        ev = evidence_mod.accumulate(diagnoses)
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
