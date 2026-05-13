"""Claude Code JSONL session parser."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cctx.models import (
    ParserError,
    SessionTrace,
    Turn,
    Usage,
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
        elif line_type == "assistant":
            turn = _parse_assistant_line(raw)
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


def _parse_assistant_line(raw: dict) -> Turn | None:
    """Build a Turn from a `type: "assistant"` JSONL line."""
    message = raw.get("message") or {}
    content_blocks = message.get("content") or []

    text_parts: list[str] = []
    thinking_parts: list[str] = []

    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "thinking":
            thinking_parts.append(block.get("thinking", ""))
        # tool_use and server_tool_use handled in later tasks.

    return Turn(
        turn_number=0,
        uuid=raw.get("uuid", ""),
        parent_uuid=raw.get("parentUuid"),
        role="assistant",
        text="\n".join(text_parts),
        thinking="\n".join(thinking_parts),
        tool_uses=[],
        tool_results=[],
        usage=_parse_usage(message.get("usage")),
        model=message.get("model"),
        stop_reason=message.get("stop_reason"),
        timestamp=_parse_timestamp(raw.get("timestamp")),
        duration_ms=None,
        is_sidechain=bool(raw.get("isSidechain", False)),
        error=("api_error" if raw.get("isApiErrorMessage") else None),
    )


def _parse_usage(raw: dict | None) -> Usage | None:
    """Build a Usage from the message.usage dict.

    Defensive sum of iterations[] if present and divergent — spec §5.2.
    """
    if not isinstance(raw, dict):
        return None

    iterations = raw.get("iterations")
    if isinstance(iterations, list) and iterations:
        # Sum across iterations defensively.
        input_t = sum(it.get("input_tokens", 0) for it in iterations)
        output_t = sum(it.get("output_tokens", 0) for it in iterations)
        cache_read = sum(it.get("cache_read_input_tokens", 0) for it in iterations)
        cache_5m = sum(
            (it.get("cache_creation") or {}).get("ephemeral_5m_input_tokens", 0)
            for it in iterations
        )
        cache_1h = sum(
            (it.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0)
            for it in iterations
        )
    else:
        input_t = raw.get("input_tokens", 0)
        output_t = raw.get("output_tokens", 0)
        cache_read = raw.get("cache_read_input_tokens", 0)
        cache_obj = raw.get("cache_creation") or {}
        cache_5m = cache_obj.get("ephemeral_5m_input_tokens", 0)
        cache_1h = cache_obj.get("ephemeral_1h_input_tokens", 0)

    return Usage(
        input_tokens=input_t,
        output_tokens=output_t,
        cache_creation_5m=cache_5m,
        cache_creation_1h=cache_1h,
        cache_read=cache_read,
        service_tier=raw.get("service_tier"),
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
