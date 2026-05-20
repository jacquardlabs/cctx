"""Live Claude Code agent query via `claude agents --json`.

Public API:
    live_sessions() -> list[LiveSession]
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class LiveSession:
    session_id: str    # matches JSONL filename stem in ~/.claude/projects/
    cwd: str
    status: str        # "busy" | "idle"
    pid: int
    kind: str          # "interactive" | "background"
    started_at: datetime


def live_sessions() -> list[LiveSession]:
    """Query `claude agents --json`. Returns [] on any failure."""
    try:
        result = subprocess.run(
            ["claude", "agents", "--json"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except FileNotFoundError:
        return []
    except subprocess.TimeoutExpired:
        return []

    if result.returncode != 0:
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    sessions: list[LiveSession] = []
    for item in data:
        try:
            sessions.append(
                LiveSession(
                    session_id=item["sessionId"],
                    cwd=item["cwd"],
                    status=item.get("status", "unknown"),
                    pid=int(item["pid"]),
                    kind=item.get("kind", "interactive"),
                    started_at=datetime.fromtimestamp(
                        item["startedAt"] / 1000, tz=timezone.utc
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return sessions
