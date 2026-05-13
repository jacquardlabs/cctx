"""Claude Code JSONL session parser."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cctx.models import (
    Attachment,
    ParserError,
    ParserWarning,
    SessionTrace,
    ToolResult,
    ToolUse,
    Turn,
    Usage,
)

_BOOKKEEPING_TYPES = frozenset(
    {
        "last-prompt",
        "permission-mode",
        "ai-title",
        "custom-title",
        "queue-operation",
        "file-history-snapshot",
        "pr-link",
    }
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
    attachments: list[Attachment] = []
    warnings: list[ParserWarning] = []

    for line_number, raw, truncated in _iter_lines(jsonl_path):
        if raw is None:
            if not truncated:
                warnings.append(
                    ParserWarning(
                        code="malformed_json",
                        detail="failed to parse JSON",
                        line_number=line_number,
                        path=jsonl_path,
                    )
                )
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
        elif line_type == "system":
            turn = _parse_system_line(raw)
            if turn is not None:
                turns.append(turn)
        elif line_type == "attachment":
            att = _parse_attachment_line(raw)
            if att is not None:
                attachments.append(att)
        elif line_type in _BOOKKEEPING_TYPES:
            # Known bookkeeping — drop silently.
            continue
        else:
            warnings.append(
                ParserWarning(
                    code="unknown_type",
                    detail=str(line_type) if line_type else "<missing>",
                    line_number=line_number,
                    path=jsonl_path,
                )
            )

    _pair_tool_results(turns)

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
        attachments=attachments,
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=start_time,
        end_time=end_time,
        source_path=jsonl_path,
        subagent_meta={},
        warnings=warnings,
        subagent_parse_errors=[],
    )


def _iter_lines(path: Path):
    """Yield (line_number, parsed_dict_or_None, is_last_line_truncated).

    For a final line that lacks a newline AND fails JSON parse, the third
    tuple element is True — the caller can drop it silently. For
    mid-file JSON failures, the third element is False — the caller
    records a malformed_json warning.
    """
    raw_bytes = path.read_bytes()
    lines = raw_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)

    for i, line in enumerate(lines):
        line_number = i + 1
        is_last = i == len(lines) - 1
        ends_with_newline = line.endswith("\n")
        stripped = line.strip()
        if not stripped:
            continue
        try:
            yield line_number, json.loads(stripped), False
        except json.JSONDecodeError:
            truncated_final = is_last and not ends_with_newline
            yield line_number, None, truncated_final


def _parse_user_line(raw: dict) -> Turn | None:
    """Build a Turn from a `type: "user"` JSONL line.

    Pattern-matches on the set of content block types so heterogeneous arrays
    don't fall through to the unknown-type path. tool_name on each ToolResult
    is set to "" here; the pairing pass fills it from prior ToolUses.
    """
    message = raw.get("message") or {}
    content = message.get("content")

    if isinstance(content, str):
        text = content
        tool_results: list[ToolResult] = []
        role = "user"
    elif isinstance(content, list):
        block_types = {b.get("type") for b in content if isinstance(b, dict)}
        if "tool_result" in block_types:
            role = "tool_result"
            text = ""  # tool_result lines have no narrative text
            tool_results = _extract_tool_results(content, structured=raw.get("toolUseResult"))
        else:
            role = "user"
            text = _flatten_user_blocks(content)
            tool_results = []
    else:
        # Defensive: unexpected content shape — keep as empty user turn with a marker.
        role = "user"
        text = ""
        tool_results = []

    return Turn(
        turn_number=0,
        uuid=raw.get("uuid", ""),
        parent_uuid=raw.get("parentUuid"),
        role=role,
        text=text,
        thinking="",
        tool_uses=[],
        tool_results=tool_results,
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=_parse_timestamp(raw.get("timestamp")),
        duration_ms=None,
        is_sidechain=bool(raw.get("isSidechain", False)),
    )


def _extract_tool_results(content: list, *, structured: dict | None) -> list[ToolResult]:
    """Extract ToolResult objects from a list of content blocks.

    `structured` is the parallel toolUseResult field; it's attached to every
    ToolResult in this turn because a JSONL line carries one toolUseResult
    even when there are multiple tool_result blocks. The decomposer can
    inspect it; the parser doesn't try to split.
    """
    results: list[ToolResult] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_result":
            continue
        raw_content = block.get("content")
        if isinstance(raw_content, str):
            content_str = raw_content
        elif isinstance(raw_content, list):
            content_str = "\n".join(
                b.get("text", "")
                for b in raw_content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            content_str = ""
        results.append(
            ToolResult(
                tool_name="",  # filled by pairing pass
                tool_use_id=block.get("tool_use_id", ""),
                content=content_str,
                structured=structured,
                is_error=bool(block.get("is_error", False)),
            )
        )
    return results


def _flatten_user_blocks(content: list) -> str:
    """Join text blocks and inline image placeholders for a user-role list-content message."""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "image":
            source = block.get("source") or {}
            media_type = source.get("media_type", "?")
            data = source.get("data", "")
            size = len(data) if isinstance(data, str) else 0
            parts.append(f"<image:{media_type},{size}B>")
    return "\n".join(parts)


def _pair_tool_results(turns: list[Turn]) -> None:
    """Populate ToolResult.tool_name by matching tool_use_id against earlier ToolUses."""
    by_id: dict[str, str] = {}
    for turn in turns:
        for use in turn.tool_uses:
            if use.tool_use_id:
                by_id[use.tool_use_id] = use.tool_name
        for result in turn.tool_results:
            if result.tool_use_id and not result.tool_name:
                result.tool_name = by_id.get(result.tool_use_id, "")


def _parse_system_line(raw: dict) -> Turn | None:
    """Build a Turn from a `type: "system"` line (compaction notices, model swaps)."""
    text = raw.get("content") or raw.get("message", {}).get("content") or ""
    if isinstance(text, list):
        text = _flatten_user_blocks(text)
    return Turn(
        turn_number=0,
        uuid=raw.get("uuid", ""),
        parent_uuid=raw.get("parentUuid"),
        role="system",
        text=str(text),
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


def _parse_attachment_line(raw: dict) -> Attachment | None:
    """Build an Attachment from a `type: "attachment"` line.

    Classification is by payload-key shape, not by hookEvent (which is only
    present on hook-output attachments). Unknown shapes are preserved with
    kind="other" — no warning, attachments are inherently polymorphic.
    """
    payload = raw.get("attachment")
    if not isinstance(payload, dict):
        return None

    kind = _classify_attachment_shape(payload)
    content = _extract_attachment_content(kind, payload)
    timestamp = raw.get("timestamp")

    return Attachment(
        kind=kind,
        raw=payload,
        content=content,
        timestamp=_parse_timestamp(timestamp) if timestamp else None,
        parent_uuid=raw.get("parentUuid"),
    )


def _classify_attachment_shape(payload: dict) -> str:
    if "hookEvent" in payload:
        return "hook_output"
    if "pendingMcpServers" in payload:
        return "mcp_servers"
    if "skillCount" in payload:
        return "skills"
    if "allowedTools" in payload:
        return "allowed_tools"
    if "itemCount" in payload:
        return "items"
    return "other"


def _extract_attachment_content(kind: str, payload: dict) -> str | None:
    """Best-effort extraction of human-readable content from an attachment.

    Returns None when nothing useful is present.
    """
    if kind == "hook_output":
        stdout = payload.get("stdout") or ""
        try:
            parsed = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            return stdout or None
        hook_specific = parsed.get("hookSpecificOutput") or {}
        return hook_specific.get("additionalContext") or stdout or None

    if kind in ("skills", "items"):
        c = payload.get("content")
        return c if isinstance(c, str) and c else None

    return None


def _parse_assistant_line(raw: dict) -> Turn | None:
    """Build a Turn from a `type: "assistant"` JSONL line."""
    message = raw.get("message") or {}
    content_blocks = message.get("content") or []

    tool_uses: list[ToolUse] = []
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
        elif block_type == "tool_use":
            tool_uses.append(
                ToolUse(
                    tool_name=block.get("name", ""),
                    tool_use_id=block.get("id", ""),
                    tool_input=block.get("input") if isinstance(block.get("input"), dict) else {},
                )
            )
        elif block_type in ("server_tool_use", "advisor_tool_result"):
            # Inline a marker so the text remains useful; structured handling deferred.
            text_parts.append(f"<{block_type}:{block.get('id', '')}>")

    return Turn(
        turn_number=0,
        uuid=raw.get("uuid", ""),
        parent_uuid=raw.get("parentUuid"),
        role="assistant",
        text="\n".join(text_parts),
        thinking="\n".join(thinking_parts),
        tool_uses=tool_uses,
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
