"""Claude Code JSONL session parser."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cctx.models import (
    ParserError,
    SessionTrace,
    Turn,
)


def parse_session(session_path: Path, *, max_subagent_depth: int = 4) -> SessionTrace:
    session_path = Path(session_path)
    jsonl_path = _resolve_jsonl_path(session_path)

    if not jsonl_path.exists():
        raise ParserError(
            path=jsonl_path,
            line_number=None,
            reason=f"file not found: {jsonl_path}",
        )

    session_id = jsonl_path.stem
    project_dir = jsonl_path.parent
    project_path = _decode_project_path(project_dir.name)

    turns: list[Turn] = []

    for _line_number, raw in _iter_lines(jsonl_path):
        if raw is None:
            continue
        line_type = raw.get("type")
        if line_type == "user":
            turn = _parse_user_line(raw)
            if turn is not None:
                turns.append(turn)

    # Number turns 1-based and compute start/end.
    for i, turn in enumerate(turns, start=1):
        turn.turn_number = i

    start_time = turns[0].timestamp if turns else None
    end_time = turns[-1].timestamp if turns else None

    return SessionTrace(
        session_id=session_id,
        parent_session_id=None,
        project_path=project_path,
        cwd=project_path,
        primary_model=None,
        claude_code_version=None,
        turns=turns,
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=start_time,
        end_time=end_time,
        source_path=jsonl_path,
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


def _iter_lines(path: Path):
    """Yield (line_number, parsed_dict) for each line in the file.

    Yields (line_number, None) for lines that cannot be parsed; the caller
    decides how to record those.
    """
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_number, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield line_number, json.loads(stripped)
            except json.JSONDecodeError:
                yield line_number, None


def _parse_user_line(raw: dict) -> Turn | None:
    """Build a Turn from a `type: "user"` JSONL line."""
    message = raw.get("message") or {}
    content = message.get("content")

    text = content if isinstance(content, str) else ""

    return Turn(
        turn_number=0,  # set by caller after collection
        uuid=raw.get("uuid", ""),
        parent_uuid=raw.get("parentUuid"),
        role="user",
        text=text,
        thinking="",
        tool_uses=[],
        tool_results=[],
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=_parse_timestamp(raw.get("timestamp")),
        duration_ms=None,
        is_sidechain=bool(raw.get("isSidechain", False)),
    )


def _parse_timestamp(value: str | None) -> datetime:
    """Parse an ISO 8601 timestamp. Accepts both 'Z' suffix and '+00:00'."""
    if not value:
        # Fallback for synthetic edge cases; should never be reached with real data.
        return datetime.fromtimestamp(0, tz=__import__("datetime").timezone.utc)
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _resolve_jsonl_path(path: Path) -> Path:
    if path.is_dir():
        return path.parent / f"{path.name}.jsonl"
    return path


def _decode_project_path(dir_name: str) -> str:
    if not dir_name.startswith("-"):
        return dir_name
    return dir_name.replace("-", "/")
