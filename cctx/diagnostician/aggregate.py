"""Cross-session aggregator.

run(project_dir, window) -> list[Diagnosis]

Discovers session JSONL files in project_dir modified within the time window,
parses each one, runs the per-session diagnostician, and returns the list of
Diagnoses. The CLI orchestrates the recommender call separately.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from cctx import diagnostician
from cctx.parsers.claude_code import parse_session

if TYPE_CHECKING:
    from cctx.models import Diagnosis

UTC = timezone.utc


def run(project_dir: Path, window: timedelta) -> list[Diagnosis]:
    cutoff = datetime.now(UTC) - window
    paths = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)

    result = []
    for path in paths:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if mtime < cutoff:
            continue
        try:
            trace = parse_session(path)
            diagnosis = diagnostician.run(trace)
            result.append(diagnosis)
        except Exception:
            continue  # skip corrupt sessions; don't fail the whole run
    return result
