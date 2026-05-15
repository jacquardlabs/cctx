"""cctx CLI — click + rich-click entry point.

Commands:
  cctx autopsy <session>           Single-session diagnosis
  cctx autopsy <project> --since   Cross-session aggregation
  cctx export <session>            Export session data as JSONL or CSV
  cctx trace <session>             Interactive TUI trace viewer
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import rich_click as click

from cctx import diagnostician
from cctx.diagnostician import aggregate
from cctx.models import AggregateReport
from cctx.parsers.claude_code import parse_session
from cctx.recommender import claude_md
from cctx.recommender import evidence as evidence_mod
from cctx.renderers.terminal import render_aggregate, render_diagnosis

click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True


@click.group()
def cli() -> None:
    """cctx — find out why your Claude Code session went sideways."""


@cli.command()
@click.argument("target", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--since",
    default=None,
    metavar="DAYS",
    type=int,
    help="Cross-session mode: analyse all sessions modified within the last N days.",
)
def autopsy(target: Path, since: int | None) -> None:
    """Diagnose a session or project directory.

    TARGET is a session JSONL file for single-session diagnosis,
    or a project directory for --since cross-session aggregation.
    """
    if since is not None:
        # Cross-session path
        project_dir = target if target.is_dir() else target.parent
        window = timedelta(days=since)
        diagnoses = aggregate.run(project_dir, window=window)
        ev = evidence_mod.accumulate(diagnoses)
        patches = claude_md.generate_from_evidence(ev)
        report = AggregateReport(
            window=window,
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
        trace = parse_session(target)
        diagnosis = diagnostician.run(trace)
        diagnosis = claude_md.generate(diagnosis)
        render_diagnosis(diagnosis)


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

    trace = parse_session(target)
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
@click.argument("target", type=click.Path(exists=True, path_type=Path))
def trace(target: Path) -> None:
    """Open an interactive TUI trace viewer for a session.

    TARGET is a session JSONL file.
    """
    from cctx.renderers.trace_tui import launch

    if target.is_dir():
        raise click.UsageError("TARGET must be a .jsonl session file, not a directory.")
    session = parse_session(target)
    diagnosis = diagnostician.run(session)
    diagnosis = claude_md.generate(diagnosis)
    launch(session, diagnosis)
