"""Watcher — tail an active Claude Code session and surface waste signals in real time.

Public API:
    watch(target) -> None

Layering rules (MUST respect):
- Imports parser and diagnostician only.
- Does NOT import renderers, click, rich, or anthropic.
- Uses a compact single-line formatter defined here (not imported from renderers).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from cctx import diagnostician
from cctx.models import Finding, FindingKind

_POLL_INTERVAL = 1.0    # seconds between size checks
_IDLE_TIMEOUT  = 30.0   # seconds of no file growth before declaring session ended

_KIND_LABEL: dict[FindingKind, str] = {
    FindingKind.RETRY_LOOP:    "RETRY LOOP",
    FindingKind.SCOPE_CREEP:   "SCOPE CREEP",
    FindingKind.STALE_CONTEXT: "STALE CONTEXT",
    FindingKind.TOOL_THRASH:   "TOOL THRASH",
    FindingKind.DEAD_END:      "DEAD END",
}


def _finding_key(f: Finding) -> tuple[FindingKind, int]:
    """Stable key for a finding — identifies it across re-runs."""
    return (f.kind, f.first_turn)


def _format_finding(f: Finding) -> str:
    label = _KIND_LABEL.get(f.kind, f.kind.value.upper())
    sev = f.severity.value.upper()
    return f"[{label}] {sev} — {f.summary}"


def _find_active_session(project_dir: Path) -> Path | None:
    """Return the most recently modified JSONL in project_dir, or None."""
    candidates = list(project_dir.glob("*.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _parse_trace(session_path: Path):
    """Parse a session file using the heuristic tokenizer (no API calls)."""
    from cctx.parsers.claude_code import parse_session
    from cctx.tokenizer import tokenize_session

    env_backup = os.environ.get("CCTX_OFFLINE")
    os.environ["CCTX_OFFLINE"] = "1"
    try:
        return tokenize_session(parse_session(session_path))
    finally:
        if env_backup is None:
            del os.environ["CCTX_OFFLINE"]
        else:
            os.environ["CCTX_OFFLINE"] = env_backup


def _tail(session_path: Path) -> int:
    """Tail session_path, re-running classifiers on each growth event.

    Returns the number of unique findings detected.
    """
    seen_keys: set[tuple[FindingKind, int]] = set()
    last_size = 0
    idle_since: float | None = None

    print(f"Watching {session_path.name} …  Ctrl+C to stop.", flush=True)

    while True:
        try:
            current_size = session_path.stat().st_size
        except OSError:
            time.sleep(_POLL_INTERVAL)
            continue

        if current_size > last_size:
            last_size = current_size
            idle_since = None

            try:
                trace = _parse_trace(session_path)
                diagnosis = diagnostician.run(trace)
            except Exception:
                time.sleep(_POLL_INTERVAL)
                continue

            for finding in diagnosis.findings:
                key = _finding_key(finding)
                if key not in seen_keys:
                    seen_keys.add(key)
                    print(_format_finding(finding), flush=True)
        else:
            now = time.monotonic()
            if idle_since is None:
                idle_since = now
            elif now - idle_since >= _IDLE_TIMEOUT:
                print(
                    f"\nSession idle for {_IDLE_TIMEOUT:.0f}s — analysis complete. "
                    f"Findings detected: {len(seen_keys)}",
                    flush=True,
                )
                return len(seen_keys)

        time.sleep(_POLL_INTERVAL)


def watch(target: Path | None = None) -> None:
    """Watch an active Claude Code session and print waste signals as they appear.

    target: project directory or None to use cwd.
    """
    from cctx.discovery import find_project_dir

    if target is None:
        target = Path.cwd()

    if not target.exists():
        print(f"Path does not exist: {target}", file=sys.stderr)
        sys.exit(1)

    if target.is_dir():
        # Is it already an encoded project dir with JSONL files?
        if any(target.glob("*.jsonl")):
            project_dir = target
        else:
            project_dir = find_project_dir(target)
            if project_dir is None:
                print(
                    f"No Claude Code project directory found for {target}.\n"
                    "Check that ~/.claude/projects/ contains a matching directory.",
                    file=sys.stderr,
                )
                sys.exit(1)
    else:
        project_dir = target.parent

    session_path = _find_active_session(project_dir)
    if session_path is None:
        print("No sessions found. Waiting for an active session …", flush=True)
        while session_path is None:
            time.sleep(_POLL_INTERVAL)
            session_path = _find_active_session(project_dir)

    try:
        _tail(session_path)
    except KeyboardInterrupt:
        print("\nStopped.")
