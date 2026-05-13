"""Claude Code JSONL session parser."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cctx.models import (
    Attachment,
    ParserError,
    ParserWarning,
    RawToolResultFile,
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


def parse_session(
    session_path: Path,
    *,
    max_subagent_depth: int = 4,
    _depth: int = 0,
    _parent_session_id: str | None = None,
) -> SessionTrace:
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

    for line_number, raw, truncated, had_encoding_error in _iter_lines(jsonl_path):
        if had_encoding_error:
            warnings.append(
                ParserWarning(
                    code="encoding_error",
                    detail=f"non-UTF-8 bytes replaced on line {line_number}",
                    line_number=line_number,
                    path=jsonl_path,
                )
            )
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

    # Validate parent_uuid references — warn on orphaned links (spec §9).
    seen_uuids = {t.uuid for t in turns if t.uuid}
    for turn in turns:
        if turn.parent_uuid is not None and turn.parent_uuid not in seen_uuids:
            warnings.append(
                ParserWarning(
                    code="orphan_parent",
                    detail=f"parent_uuid {turn.parent_uuid} not seen in this session",
                    path=jsonl_path,
                )
            )

    # Number turns 1-based and compute start/end.
    for i, turn in enumerate(turns, start=1):
        turn.turn_number = i

    start_time = turns[0].timestamp if turns else None
    end_time = turns[-1].timestamp if turns else None

    # Compute initial_context_tokens from the first assistant turn.
    initial_context_tokens = 0
    for turn in turns:
        if turn.role == "assistant" and turn.usage is not None:
            initial_context_tokens = turn.usage.cache_creation_5m + turn.usage.cache_creation_1h
            break

    # Metadata pass.
    primary_model = _most_common([t.model for t in turns if t.role == "assistant" and t.model])
    claude_code_version = _first_present_field(jsonl_path, "version", turns)
    observed_cwd = _first_present_field(jsonl_path, "cwd", turns) or project_path
    tool_names_loaded = _collect_tool_names(turns, attachments)
    raw_tool_result_files = _enumerate_raw_tool_result_files(jsonl_path)

    # Load subagent meta if this is a child session.
    subagent_meta: dict = {}
    if _depth > 0:
        meta_path = jsonl_path.with_suffix(".meta.json")
        if meta_path.exists():
            try:
                subagent_meta = json.loads(meta_path.read_text())
            except json.JSONDecodeError:
                subagent_meta = {}

    subagents, subagent_parse_errors, depth_warnings = _parse_subagents(
        jsonl_path,
        max_subagent_depth=max_subagent_depth,
        depth=_depth,
        parent_session_id=session_id,
    )
    warnings.extend(depth_warnings)

    _link_subagents(turns, subagents, warnings, jsonl_path)

    parent_session_id = _parent_session_id

    return SessionTrace(
        session_id=session_id,
        parent_session_id=parent_session_id,
        project_path=project_path,
        cwd=observed_cwd,
        primary_model=primary_model,
        claude_code_version=claude_code_version,
        turns=turns,
        subagents=subagents,
        attachments=attachments,
        raw_tool_result_files=raw_tool_result_files,
        initial_context_tokens=initial_context_tokens,
        tool_names_loaded=tool_names_loaded,
        start_time=start_time,
        end_time=end_time,
        source_path=jsonl_path,
        subagent_meta=subagent_meta,
        warnings=warnings,
        subagent_parse_errors=subagent_parse_errors,
    )


def _iter_lines(path: Path):
    """Yield (line_number, parsed_dict_or_None, is_last_line_truncated, had_encoding_error).

    For a final line that lacks a newline AND fails JSON parse, the third
    tuple element is True — the caller can drop it silently. For
    mid-file JSON failures, the third element is False — the caller
    records a malformed_json warning.

    The fourth element is True when the Unicode replacement character (U+FFFD)
    was introduced by the errors='replace' decoding, indicating non-UTF-8 bytes.
    """
    raw_bytes = path.read_bytes()
    lines = raw_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)

    for i, line in enumerate(lines):
        line_number = i + 1
        is_last = i == len(lines) - 1
        ends_with_newline = line.endswith("\n")
        had_encoding_error = "\ufffd" in line
        stripped = line.strip()
        if not stripped:
            continue
        try:
            yield line_number, json.loads(stripped), False, had_encoding_error
        except json.JSONDecodeError:
            truncated_final = is_last and not ends_with_newline
            yield line_number, None, truncated_final, had_encoding_error


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


def _most_common(values: list[str]) -> str | None:
    """Return the most frequent value, or None if the list is empty."""
    if not values:
        return None
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0]


def _first_present_field(jsonl_path: Path, field_name: str, turns: list[Turn]) -> str | None:
    """Re-scan the file to find the first non-null value of a top-level field.

    Cheap: stops at first hit. Used for fields we don't store on Turn (cwd, version).
    """
    with jsonl_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            value = obj.get(field_name)
            if value:
                return str(value)
    return None


def _collect_tool_names(turns: list[Turn], attachments: list[Attachment]) -> list[str]:
    """Union of MCP names from pendingMcpServers attachments + names observed in tool_uses."""
    names: list[str] = []
    seen: set[str] = set()
    # MCP names from attachments.
    for att in attachments:
        if att.kind != "mcp_servers":
            continue
        for n in att.raw.get("addedNames", []) or []:
            if isinstance(n, str) and n not in seen:
                seen.add(n)
                names.append(n)
    # Observed tool uses.
    for turn in turns:
        for use in turn.tool_uses:
            if use.tool_name and use.tool_name not in seen:
                seen.add(use.tool_name)
                names.append(use.tool_name)
    return names


def _parse_subagents(
    parent_jsonl: Path,
    *,
    max_subagent_depth: int,
    depth: int,
    parent_session_id: str,
) -> tuple[list[SessionTrace], list[dict], list[ParserWarning]]:
    """Discover and recursively parse subagent JSONLs.

    Returns (subagents, parse_errors, depth_warnings). Each subagent trace has
    parent_session_id set.
    """
    if depth >= max_subagent_depth:
        sub_dir = parent_jsonl.parent / parent_jsonl.stem / "subagents"
        has_children = sub_dir.is_dir() and any(sub_dir.glob("agent-*.jsonl"))
        if has_children:
            return (
                [],
                [],
                [
                    ParserWarning(
                        code="max_subagent_depth",
                        detail=(
                            f"depth {depth} reached at {sub_dir};"
                            " raise max_subagent_depth to recurse deeper"
                        ),
                        path=parent_jsonl,
                    )
                ],
            )
        return [], [], []

    sid = parent_jsonl.stem
    sub_dir = parent_jsonl.parent / sid / "subagents"
    if not sub_dir.is_dir():
        return [], [], []

    subagents: list[SessionTrace] = []
    errors: list[dict] = []
    for child_jsonl in sorted(sub_dir.glob("agent-*.jsonl")):
        try:
            child = parse_session(
                child_jsonl,
                max_subagent_depth=max_subagent_depth,
                _depth=depth + 1,
                _parent_session_id=parent_session_id,
            )
            subagents.append(child)
        except ParserError as e:
            errors.append({"path": child_jsonl, "reason": e.reason})
    return subagents, errors, []


def _link_subagents(
    turns: list[Turn],
    subagents: list[SessionTrace],
    warnings: list[ParserWarning],
    path: Path,
) -> None:
    """Stamp ToolUse.subagent_session_id and emit orphan warnings.

    Linking strategy (spec §7):
      1. Exact: child.subagent_meta["tool_use_id"] matches a parent ToolUse.tool_use_id.
      2. Fallback: not implemented in v1; orphans warn.

    Both directions of orphan are warned:
      - orphan_agent_call: parent has an Agent ToolUse with no matching child.
      - orphan_subagent_file: child exists but no parent ToolUse claimed it.
    """
    # Index parent Agent tool_uses by tool_use_id.
    agent_uses_by_id: dict[str, ToolUse] = {}
    for turn in turns:
        for use in turn.tool_uses:
            if use.tool_name == "Agent" and use.tool_use_id:
                agent_uses_by_id[use.tool_use_id] = use

    matched_use_ids: set[str] = set()
    for child in subagents:
        meta_tool_use_id = (child.subagent_meta or {}).get("tool_use_id")
        if meta_tool_use_id and meta_tool_use_id in agent_uses_by_id:
            agent_uses_by_id[meta_tool_use_id].subagent_session_id = child.session_id
            matched_use_ids.add(meta_tool_use_id)
        else:
            warnings.append(
                ParserWarning(
                    code="orphan_subagent_file",
                    detail=f"subagent {child.session_id} has no matching parent Agent tool_use",
                    path=path,
                )
            )

    # Agent tool_uses that never got linked.
    for use_id, _use in agent_uses_by_id.items():
        if use_id not in matched_use_ids:
            warnings.append(
                ParserWarning(
                    code="orphan_agent_call",
                    detail=f"Agent tool_use {use_id} has no matching subagent file",
                    path=path,
                )
            )


def _enumerate_raw_tool_result_files(jsonl_path: Path) -> list[RawToolResultFile]:
    """List <sid>/tool-results/*.txt with sizes. Does NOT read contents."""
    sid = jsonl_path.stem
    tr_dir = jsonl_path.parent / sid / "tool-results"
    if not tr_dir.is_dir():
        return []
    return [
        RawToolResultFile(path=p, size_bytes=p.stat().st_size, tool_use_id=None)
        for p in sorted(tr_dir.glob("*.txt"))
    ]


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
