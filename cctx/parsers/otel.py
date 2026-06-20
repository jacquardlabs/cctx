"""OTLP JSONL parser for OpenAI Agents SDK traces.

Public API:
    parse_otel_file(path: Path) -> list[SessionTrace]

Reads OTLP JSON (one ResourceSpans batch per line). Maps spans to the
cctx canonical model. No imports from anthropic, click, or other cctx
modules except cctx.models.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from cctx.models import (
    ParserWarning,
    SessionTrace,
    ToolResult,
    ToolUse,
    Turn,
    Usage,
)


def parse_otel_file(path: Path) -> list[SessionTrace]:
    """Read an OTLP JSONL export; return one SessionTrace per trace_id."""
    path = Path(path)
    warnings: list[ParserWarning] = []
    spans = _load_spans(path, warnings)

    by_trace: dict[str, list[dict]] = defaultdict(list)
    for span in spans:
        trace_id = span.get("traceId", "")
        if trace_id:
            by_trace[trace_id].append(span)

    return [
        _build_session_trace(trace_id, trace_spans, path, warnings)
        for trace_id, trace_spans in by_trace.items()
    ]


def _load_spans(path: Path, warnings: list[ParserWarning]) -> list[dict]:
    """Load all spans from OTLP JSONL. One ResourceSpans JSON object per line."""
    spans: list[dict] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    warnings.append(
                        ParserWarning(
                            code="malformed_json",
                            detail=f"skipped malformed JSON on line {lineno}",
                            line_number=lineno,
                            path=path,
                        )
                    )
                    continue
                for rs in obj.get("resourceSpans", []):
                    for ss in rs.get("scopeSpans", []):
                        for span in ss.get("spans", []):
                            span["_resource"] = rs.get("resource", {})
                            spans.append(span)
    except OSError as exc:
        warnings.append(
            ParserWarning(code="read_error", detail=str(exc), path=path)
        )
    return spans


def _build_session_trace(
    trace_id: str,
    spans: list[dict],
    source_path: Path,
    warnings: list[ParserWarning],
) -> SessionTrace:
    root = _find_root_agent_span(spans, warnings)
    if root is None:
        root = {}

    turns = _build_turns(root, spans)
    subagents = _build_subagents(root, spans, source_path, warnings)
    primary_model = _primary_model(spans)
    cwd = _attr_str(root, "process.cwd") or ""

    all_start_times = [
        _nano_to_dt(s.get("startTimeUnixNano"))
        for s in spans
        if s.get("startTimeUnixNano")
    ]
    start_time = min((t for t in all_start_times if t), default=None)
    all_end_times = [
        _nano_to_dt(s.get("endTimeUnixNano"))
        for s in spans
        if s.get("endTimeUnixNano")
    ]
    end_time = max((t for t in all_end_times if t), default=None)

    tool_names: list[str] = list({
        name
        for s in spans
        if _attr_str(s, "gen_ai.operation.name") == "invoke_function"
        if (name := _attr_str(s, "gen_ai.tool.name"))
    })

    return SessionTrace(
        session_id=trace_id,
        parent_session_id=None,
        project_path="",
        cwd=cwd,
        primary_model=primary_model,
        claude_code_version=None,
        turns=turns,
        subagents=subagents,
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=tool_names,
        start_time=start_time,
        end_time=end_time,
        source_path=source_path,
        subagent_meta={},
        warnings=warnings,
        subagent_parse_errors=[],
    )


# ---------------------------------------------------------------------------
# Span tree helpers
# ---------------------------------------------------------------------------


def _find_root_agent_span(
    spans: list[dict], warnings: list[ParserWarning]
) -> dict | None:
    roots = [
        s for s in spans
        if _attr_str(s, "gen_ai.operation.name") == "run_agent"
        and not s.get("parentSpanId")
    ]
    if not roots:
        warnings.append(
            ParserWarning(code="no_root_agent_span", detail="no root AgentSpan found")
        )
        return None
    return roots[0]


def _build_turns(agent_span: dict, all_spans: list[dict]) -> list[Turn]:
    """Build assistant turns from GenerationSpans that are direct children of agent_span."""
    if not agent_span:
        return []
    agent_id = agent_span.get("spanId", "")
    gen_spans = [
        s for s in all_spans
        if s.get("parentSpanId") == agent_id
        and _attr_str(s, "gen_ai.operation.name") == "chat"
    ]
    gen_spans.sort(key=lambda s: int(s.get("startTimeUnixNano") or 0))

    turns: list[Turn] = []
    for i, gs in enumerate(gen_spans, 1):
        tool_uses, tool_results = _build_tool_uses(gs, all_spans)
        usage = Usage(
            input_tokens=_attr_int(gs, "gen_ai.usage.input_tokens") or 0,
            output_tokens=_attr_int(gs, "gen_ai.usage.output_tokens") or 0,
            cache_creation_5m=0,
            cache_creation_1h=0,
            cache_read=0,
            service_tier=None,
        )
        ts = _nano_to_dt(gs.get("startTimeUnixNano")) or datetime.now(timezone.utc)
        end_ns = gs.get("endTimeUnixNano")
        start_ns = gs.get("startTimeUnixNano")
        duration_ms: int | None = None
        if end_ns and start_ns:
            duration_ms = int((int(end_ns) - int(start_ns)) / 1_000_000)

        turns.append(
            Turn(
                turn_number=i,
                uuid=gs.get("spanId", ""),
                parent_uuid=agent_id or None,
                role="assistant",
                text=_attr_str(gs, "gen_ai.output.text") or "",
                thinking="",
                tool_uses=tool_uses,
                tool_results=tool_results,
                usage=usage,
                model=_attr_str(gs, "gen_ai.request.model"),
                stop_reason="end_turn",
                timestamp=ts,
                duration_ms=duration_ms,
            )
        )
    return turns


def _build_tool_uses(
    gen_span: dict, all_spans: list[dict]
) -> tuple[list[ToolUse], list[ToolResult]]:
    """Extract ToolUse + ToolResult from FunctionSpan children of a GenerationSpan."""
    gen_id = gen_span.get("spanId", "")
    func_spans = [
        s for s in all_spans
        if s.get("parentSpanId") == gen_id
        and _attr_str(s, "gen_ai.operation.name") == "invoke_function"
    ]
    func_spans.sort(key=lambda s: int(s.get("startTimeUnixNano") or 0))

    tool_uses: list[ToolUse] = []
    tool_results: list[ToolResult] = []
    for fs in func_spans:
        tool_name = _attr_str(fs, "gen_ai.tool.name") or "unknown"
        call_id = _attr_str(fs, "gen_ai.tool.call.id") or fs.get("spanId", "")
        result_str = _attr_str(fs, "gen_ai.tool.call.result") or ""
        is_error = fs.get("status", {}).get("code", 1) == 2  # OTEL STATUS_ERROR = 2

        tool_uses.append(ToolUse(tool_name=tool_name, tool_use_id=call_id, tool_input={}))
        tool_results.append(
            ToolResult(
                tool_name=tool_name,
                tool_use_id=call_id,
                content=result_str,
                structured=None,
                is_error=is_error,
            )
        )
    return tool_uses, tool_results


def _build_subagents(
    root_span: dict,
    all_spans: list[dict],
    source_path: Path,
    warnings: list[ParserWarning],
) -> list[SessionTrace]:
    """Build child SessionTraces from child AgentSpans (handoffs + parallel sub-agents)."""
    if not root_span:
        return []
    root_id = root_span.get("spanId", "")
    child_agent_spans = [
        s for s in all_spans
        if s.get("parentSpanId") == root_id
        and _attr_str(s, "gen_ai.operation.name") == "run_agent"
    ]
    child_agent_spans.sort(key=lambda s: int(s.get("startTimeUnixNano") or 0))

    subagents: list[SessionTrace] = []
    for child in child_agent_spans:
        child_id = child.get("spanId", "")
        child_spans = [s for s in all_spans if s.get("parentSpanId") == child_id]
        agent_name = _attr_str(child, "gen_ai.agent.name") or child_id
        child_turns = _build_turns(child, child_spans + [child])
        child_start = _nano_to_dt(child.get("startTimeUnixNano"))
        child_end = _nano_to_dt(child.get("endTimeUnixNano"))

        subagents.append(
            SessionTrace(
                session_id=child_id,
                parent_session_id=root_id or None,
                project_path="",
                cwd="",
                primary_model=_primary_model(child_spans),
                claude_code_version=None,
                turns=child_turns,
                subagents=[],
                attachments=[],
                raw_tool_result_files=[],
                initial_context_tokens=0,
                tool_names_loaded=[],
                start_time=child_start,
                end_time=child_end,
                source_path=source_path,
                subagent_meta={"agent_name": agent_name},
                warnings=[],
                subagent_parse_errors=[],
            )
        )
    return subagents


# ---------------------------------------------------------------------------
# Attribute + time helpers
# ---------------------------------------------------------------------------


def _primary_model(spans: list[dict]) -> str | None:
    models = [
        m for s in spans
        if _attr_str(s, "gen_ai.operation.name") == "chat"
        if (m := _attr_str(s, "gen_ai.request.model"))
    ]
    if not models:
        return None
    return max(set(models), key=models.count)


def _attr_str(span: dict, key: str) -> str | None:
    for attr in span.get("attributes", []):
        if attr.get("key") == key:
            return attr.get("value", {}).get("stringValue")
    return None


def _attr_int(span: dict, key: str) -> int | None:
    for attr in span.get("attributes", []):
        if attr.get("key") == key:
            val = attr.get("value", {})
            raw = val.get("intValue") or val.get("doubleValue")
            if raw is not None:
                try:
                    return int(float(raw))
                except (ValueError, TypeError):
                    return None
    return None


def _nano_to_dt(nano: str | int | None) -> datetime | None:
    if nano is None:
        return None
    try:
        ns = int(nano)
        return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None
