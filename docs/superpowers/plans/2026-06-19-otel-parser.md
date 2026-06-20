# OTEL Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `parsers/otel.py` that reads OTLP JSONL exports from the OpenAI Agents SDK, maps spans to `SessionTrace`, and wires auto-detection into `cctx autopsy` so users never need a `--source` flag.

**Architecture:** A new `parsers/otel.py` loads spans from OTLP JSONL, groups them by `trace_id`, reconstructs the parent/child tree, and maps span types to cctx's canonical model (`GenerationSpan` → `Turn`, `FunctionSpan` → `ToolUse`/`ToolResult`, child `AgentSpan` → `SessionTrace.subagents`). A `_detect_source()` helper in `cli.py` sniffs the first line of the file to route `autopsy` to the right parser without requiring a `--source` flag.

**Tech Stack:** Python 3.10+ stdlib only in the parser (`json`, `pathlib`, `datetime`, `collections`). `click` only in `cli.py` (already imported). No new dependencies.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `tests/fixtures/otel_handoff.jsonl` | Create | Two-agent handoff trace (OTLP JSONL) |
| `tests/fixtures/otel_fanout.jsonl` | Create | Orchestrator + 2 parallel sub-agents (OTLP JSONL) |
| `cctx/parsers/otel.py` | Create | `parse_otel_file(path) -> list[SessionTrace]` |
| `tests/test_otel_parser.py` | Create | All parser + auto-detection tests |
| `cctx/cli.py` | Modify | `_detect_source()` helper; route `autopsy` through it |
| `docs/quickstart-openai-agents.md` | Create | One-page setup guide |

---

## Task 1: Create OTLP JSONL fixture files

**Files:**
- Create: `tests/fixtures/otel_handoff.jsonl`
- Create: `tests/fixtures/otel_fanout.jsonl`

These fixtures simulate what a `BatchSpanProcessor` + file exporter writes: one JSON object per line where each object is an OTLP `ResourceSpans` batch. Each fixture is one line (one batch containing all spans for the trace).

- [ ] **Step 1: Create the handoff fixture**

`tests/fixtures/otel_handoff.jsonl` — one line, copy verbatim:

```json
{"resourceSpans":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"my-agent-app"}}]},"scopeSpans":[{"scope":{"name":"openai.agents","version":"0.0.1"},"spans":[{"traceId":"aabbccddeeff00112233445566778899","spanId":"aa00000000000001","name":"agent","kind":3,"startTimeUnixNano":"1718800000000000000","endTimeUnixNano":"1718800010000000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"run_agent"}},{"key":"gen_ai.agent.name","value":{"stringValue":"TriageAgent"}},{"key":"gen_ai.system","value":{"stringValue":"openai"}}],"status":{"code":1}},{"traceId":"aabbccddeeff00112233445566778899","spanId":"aa00000000000002","parentSpanId":"aa00000000000001","name":"chat","kind":3,"startTimeUnixNano":"1718800001000000000","endTimeUnixNano":"1718800003000000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"chat"}},{"key":"gen_ai.request.model","value":{"stringValue":"gpt-4o"}},{"key":"gen_ai.system","value":{"stringValue":"openai"}},{"key":"gen_ai.usage.input_tokens","value":{"intValue":"1200"}},{"key":"gen_ai.usage.output_tokens","value":{"intValue":"350"}}],"status":{"code":1}},{"traceId":"aabbccddeeff00112233445566778899","spanId":"aa00000000000003","parentSpanId":"aa00000000000002","name":"function","kind":3,"startTimeUnixNano":"1718800002000000000","endTimeUnixNano":"1718800002500000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"invoke_function"}},{"key":"gen_ai.tool.name","value":{"stringValue":"check_priority"}},{"key":"gen_ai.tool.call.id","value":{"stringValue":"call_abc123"}},{"key":"gen_ai.tool.call.result","value":{"stringValue":"high"}}],"status":{"code":1}},{"traceId":"aabbccddeeff00112233445566778899","spanId":"aa00000000000004","parentSpanId":"aa00000000000001","name":"handoff","kind":3,"startTimeUnixNano":"1718800003000000000","endTimeUnixNano":"1718800003100000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"handoff"}},{"key":"openai.handoff.from_agent","value":{"stringValue":"TriageAgent"}},{"key":"openai.handoff.to_agent","value":{"stringValue":"ResolutionAgent"}}],"status":{"code":1}},{"traceId":"aabbccddeeff00112233445566778899","spanId":"aa00000000000005","parentSpanId":"aa00000000000001","name":"agent","kind":3,"startTimeUnixNano":"1718800003100000000","endTimeUnixNano":"1718800010000000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"run_agent"}},{"key":"gen_ai.agent.name","value":{"stringValue":"ResolutionAgent"}},{"key":"gen_ai.system","value":{"stringValue":"openai"}}],"status":{"code":1}},{"traceId":"aabbccddeeff00112233445566778899","spanId":"aa00000000000006","parentSpanId":"aa00000000000005","name":"chat","kind":3,"startTimeUnixNano":"1718800004000000000","endTimeUnixNano":"1718800008000000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"chat"}},{"key":"gen_ai.request.model","value":{"stringValue":"gpt-4o"}},{"key":"gen_ai.system","value":{"stringValue":"openai"}},{"key":"gen_ai.usage.input_tokens","value":{"intValue":"2000"}},{"key":"gen_ai.usage.output_tokens","value":{"intValue":"500"}}],"status":{"code":1}}]}]}]}
```

- [ ] **Step 2: Create the fan-out fixture**

`tests/fixtures/otel_fanout.jsonl` — one line, copy verbatim:

```json
{"resourceSpans":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"my-agent-app"}}]},"scopeSpans":[{"scope":{"name":"openai.agents","version":"0.0.1"},"spans":[{"traceId":"bbccddee00112233bbccddee00112233","spanId":"bb00000000000001","name":"agent","kind":3,"startTimeUnixNano":"1718800000000000000","endTimeUnixNano":"1718800015000000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"run_agent"}},{"key":"gen_ai.agent.name","value":{"stringValue":"OrchestratorAgent"}},{"key":"gen_ai.system","value":{"stringValue":"openai"}}],"status":{"code":1}},{"traceId":"bbccddee00112233bbccddee00112233","spanId":"bb00000000000002","parentSpanId":"bb00000000000001","name":"chat","kind":3,"startTimeUnixNano":"1718800001000000000","endTimeUnixNano":"1718800002000000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"chat"}},{"key":"gen_ai.request.model","value":{"stringValue":"gpt-4o"}},{"key":"gen_ai.usage.input_tokens","value":{"intValue":"800"}},{"key":"gen_ai.usage.output_tokens","value":{"intValue":"200"}}],"status":{"code":1}},{"traceId":"bbccddee00112233bbccddee00112233","spanId":"bb00000000000003","parentSpanId":"bb00000000000002","name":"function","kind":3,"startTimeUnixNano":"1718800002000000000","endTimeUnixNano":"1718800012000000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"invoke_function"}},{"key":"gen_ai.tool.name","value":{"stringValue":"run_subagent"}},{"key":"gen_ai.tool.call.id","value":{"stringValue":"call_sub1"}}],"status":{"code":1}},{"traceId":"bbccddee00112233bbccddee00112233","spanId":"bb00000000000004","parentSpanId":"bb00000000000002","name":"function","kind":3,"startTimeUnixNano":"1718800002000000000","endTimeUnixNano":"1718800012000000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"invoke_function"}},{"key":"gen_ai.tool.name","value":{"stringValue":"run_subagent"}},{"key":"gen_ai.tool.call.id","value":{"stringValue":"call_sub2"}}],"status":{"code":1}},{"traceId":"bbccddee00112233bbccddee00112233","spanId":"bb00000000000005","parentSpanId":"bb00000000000001","name":"agent","kind":3,"startTimeUnixNano":"1718800002000000000","endTimeUnixNano":"1718800012000000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"run_agent"}},{"key":"gen_ai.agent.name","value":{"stringValue":"SubAgent1"}}],"status":{"code":1}},{"traceId":"bbccddee00112233bbccddee00112233","spanId":"bb00000000000006","parentSpanId":"bb00000000000005","name":"chat","kind":3,"startTimeUnixNano":"1718800003000000000","endTimeUnixNano":"1718800010000000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"chat"}},{"key":"gen_ai.request.model","value":{"stringValue":"gpt-4o"}},{"key":"gen_ai.usage.input_tokens","value":{"intValue":"1500"}},{"key":"gen_ai.usage.output_tokens","value":{"intValue":"400"}}],"status":{"code":1}},{"traceId":"bbccddee00112233bbccddee00112233","spanId":"bb00000000000007","parentSpanId":"bb00000000000001","name":"agent","kind":3,"startTimeUnixNano":"1718800002000000000","endTimeUnixNano":"1718800012000000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"run_agent"}},{"key":"gen_ai.agent.name","value":{"stringValue":"SubAgent2"}}],"status":{"code":1}},{"traceId":"bbccddee00112233bbccddee00112233","spanId":"bb00000000000008","parentSpanId":"bb00000000000007","name":"chat","kind":3,"startTimeUnixNano":"1718800003000000000","endTimeUnixNano":"1718800011000000000","attributes":[{"key":"gen_ai.operation.name","value":{"stringValue":"chat"}},{"key":"gen_ai.request.model","value":{"stringValue":"gpt-4o"}},{"key":"gen_ai.usage.input_tokens","value":{"intValue":"1800"}},{"key":"gen_ai.usage.output_tokens","value":{"intValue":"450"}}],"status":{"code":1}}]}]}]}
```

- [ ] **Step 3: Verify fixtures are valid JSON**

```bash
python3 -c "
import json, pathlib
for name in ['otel_handoff.jsonl', 'otel_fanout.jsonl']:
    p = pathlib.Path('tests/fixtures') / name
    lines = [l.strip() for l in p.read_text().splitlines() if l.strip()]
    for i, line in enumerate(lines):
        obj = json.loads(line)
        spans = [s for rs in obj['resourceSpans'] for ss in rs['scopeSpans'] for s in ss['spans']]
        print(f'{name} line {i+1}: {len(spans)} spans OK')
"
```

Expected output:
```
otel_handoff.jsonl line 1: 6 spans OK
otel_fanout.jsonl line 1: 8 spans OK
```

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/otel_handoff.jsonl tests/fixtures/otel_fanout.jsonl
git commit -m "test: add OTLP JSONL fixtures for otel parser (handoff + fanout)"
```

---

## Task 2: OTEL parser skeleton and span loading

**Files:**
- Create: `cctx/parsers/otel.py`
- Create: `tests/test_otel_parser.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_otel_parser.py`:

```python
"""Tests for cctx/parsers/otel.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_otel_file_returns_list(tmp_path: Path) -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert isinstance(result, list)
    assert len(result) == 1


def test_parse_otel_file_session_id_is_trace_id(tmp_path: Path) -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert result[0].session_id == "aabbccddeeff00112233445566778899"


def test_parse_otel_file_source_path_set(tmp_path: Path) -> None:
    from cctx.parsers.otel import parse_otel_file

    path = FIXTURES / "otel_handoff.jsonl"
    result = parse_otel_file(path)
    assert result[0].source_path == path


def test_parse_otel_file_fanout_returns_one_trace() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_fanout.jsonl")
    assert len(result) == 1
    assert result[0].session_id == "bbccddee00112233bbccddee00112233"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_otel_parser.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError` or `ImportError` — `cctx.parsers.otel` does not exist yet.

- [ ] **Step 3: Implement the parser skeleton**

Create `cctx/parsers/otel.py`:

```python
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

    all_timestamps = [
        _nano_to_dt(s.get("startTimeUnixNano"))
        for s in spans
        if s.get("startTimeUnixNano")
    ]
    start_time = min(all_timestamps) if all_timestamps else None
    end_time_candidates = [
        _nano_to_dt(s.get("endTimeUnixNano"))
        for s in spans
        if s.get("endTimeUnixNano")
    ]
    end_time = max(end_time_candidates) if end_time_candidates else None

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
        tool_names_loaded=list({
            _attr_str(s, "gen_ai.tool.name")
            for s in spans
            if _attr_str(s, "gen_ai.operation.name") == "invoke_function"
            and _attr_str(s, "gen_ai.tool.name")
        }),
        start_time=start_time,
        end_time=end_time,
        source_path=source_path,
        subagent_meta={},
        warnings=warnings,
        subagent_parse_errors=[],
    )


# ---------------------------------------------------------------------------
# Helpers
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

        tool_uses.append(
            ToolUse(
                tool_name=tool_name,
                tool_use_id=call_id,
                tool_input={},
            )
        )
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
        child_spans = _subtree(child_id, all_spans)
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


def _subtree(span_id: str, all_spans: list[dict]) -> list[dict]:
    """Return all spans whose parentSpanId is span_id (one level deep)."""
    return [s for s in all_spans if s.get("parentSpanId") == span_id]


def _primary_model(spans: list[dict]) -> str | None:
    models = [
        _attr_str(s, "gen_ai.request.model")
        for s in spans
        if _attr_str(s, "gen_ai.operation.name") == "chat"
        and _attr_str(s, "gen_ai.request.model")
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
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_otel_parser.py::test_parse_otel_file_returns_list tests/test_otel_parser.py::test_parse_otel_file_session_id_is_trace_id tests/test_otel_parser.py::test_parse_otel_file_source_path_set tests/test_otel_parser.py::test_parse_otel_file_fanout_returns_one_trace -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add cctx/parsers/otel.py tests/test_otel_parser.py
git commit -m "feat: OTEL parser skeleton — span loading and session trace construction"
```

---

## Task 3: GenerationSpan → Turn mapping

**Files:**
- Modify: `tests/test_otel_parser.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_otel_parser.py`:

```python
def test_handoff_root_has_one_turn() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    root = result[0]
    assert len(root.turns) == 1


def test_handoff_turn_role_is_assistant() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    turn = result[0].turns[0]
    assert turn.role == "assistant"


def test_handoff_turn_usage_populated() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    usage = result[0].turns[0].usage
    assert usage is not None
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 350


def test_handoff_turn_model() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert result[0].turns[0].model == "gpt-4o"


def test_handoff_turn_number_is_one_based() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert result[0].turns[0].turn_number == 1


def test_handoff_primary_model() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert result[0].primary_model == "gpt-4o"


def test_handoff_start_end_times_set() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    trace = result[0]
    assert trace.start_time is not None
    assert trace.end_time is not None
    assert trace.end_time > trace.start_time
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_otel_parser.py -v 2>&1 | tail -20
```

Expected: all tests PASS (the skeleton already implements turn mapping — these tests verify the implementation is correct).

- [ ] **Step 3: Commit**

```bash
git add tests/test_otel_parser.py
git commit -m "test: verify GenerationSpan → Turn mapping for OTEL parser"
```

---

## Task 4: FunctionSpan → ToolUse + ToolResult

**Files:**
- Modify: `tests/test_otel_parser.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_otel_parser.py`:

```python
def test_handoff_turn_has_one_tool_use() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    turn = result[0].turns[0]
    assert len(turn.tool_uses) == 1
    assert turn.tool_uses[0].tool_name == "check_priority"
    assert turn.tool_uses[0].tool_use_id == "call_abc123"


def test_handoff_turn_has_one_tool_result() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    turn = result[0].turns[0]
    assert len(turn.tool_results) == 1
    result_obj = turn.tool_results[0]
    assert result_obj.tool_name == "check_priority"
    assert result_obj.tool_use_id == "call_abc123"
    assert result_obj.content == "high"
    assert result_obj.is_error is False


def test_tool_names_loaded_contains_tool() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert "check_priority" in result[0].tool_names_loaded


def test_fanout_orchestrator_has_two_tool_uses() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_fanout.jsonl")
    turn = result[0].turns[0]
    assert len(turn.tool_uses) == 2
    tool_names = {tu.tool_name for tu in turn.tool_uses}
    assert tool_names == {"run_subagent"}
    call_ids = {tu.tool_use_id for tu in turn.tool_uses}
    assert call_ids == {"call_sub1", "call_sub2"}
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_otel_parser.py -v 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_otel_parser.py
git commit -m "test: verify FunctionSpan → ToolUse + ToolResult mapping"
```

---

## Task 5: Child AgentSpan → subagents

**Files:**
- Modify: `tests/test_otel_parser.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_otel_parser.py`:

```python
def test_handoff_produces_one_subagent() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    root = result[0]
    assert len(root.subagents) == 1


def test_handoff_subagent_agent_name_in_meta() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    child = result[0].subagents[0]
    assert child.subagent_meta.get("agent_name") == "ResolutionAgent"


def test_handoff_subagent_has_one_turn() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    child = result[0].subagents[0]
    assert len(child.turns) == 1
    assert child.turns[0].usage is not None
    assert child.turns[0].usage.input_tokens == 2000
    assert child.turns[0].usage.output_tokens == 500


def test_handoff_subagent_parent_session_id_set() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    child = result[0].subagents[0]
    assert child.parent_session_id == result[0].turns[0].parent_uuid


def test_fanout_produces_two_subagents() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_fanout.jsonl")
    root = result[0]
    assert len(root.subagents) == 2


def test_fanout_subagent_names() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_fanout.jsonl")
    names = {s.subagent_meta.get("agent_name") for s in result[0].subagents}
    assert names == {"SubAgent1", "SubAgent2"}


def test_fanout_subagents_each_have_one_turn() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_fanout.jsonl")
    for sub in result[0].subagents:
        assert len(sub.turns) == 1
        assert sub.turns[0].role == "assistant"
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_otel_parser.py -v 2>&1 | tail -25
```

Expected: all tests PASS. If `test_handoff_subagent_parent_session_id_set` fails, investigate: the `parent_session_id` on the child should match the root's `spanId`. Update the assertion to `child.parent_session_id == "aa00000000000001"` (the root span ID from the fixture) if the turn's `parent_uuid` field differs.

- [ ] **Step 3: Commit**

```bash
git add tests/test_otel_parser.py
git commit -m "test: verify child AgentSpan → subagents mapping (handoff + fan-out)"
```

---

## Task 6: Error handling

**Files:**
- Modify: `tests/test_otel_parser.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_otel_parser.py`:

```python
def test_malformed_json_line_emits_warning(tmp_path: Path) -> None:
    from cctx.parsers.otel import parse_otel_file

    bad = tmp_path / "bad.jsonl"
    bad.write_text('not valid json\n')
    result = parse_otel_file(bad)
    # no crash; returns empty list (no valid spans)
    assert isinstance(result, list)


def test_malformed_json_line_records_warning(tmp_path: Path) -> None:
    import json as _json
    from cctx.parsers.otel import parse_otel_file

    good_line = _json.dumps({"resourceSpans": [{"resource": {"attributes": []}, "scopeSpans": [{"scope": {}, "spans": [{"traceId": "cc00000000000000cc00000000000000", "spanId": "cc00000000000001", "name": "agent", "kind": 3, "startTimeUnixNano": "1718800000000000000", "endTimeUnixNano": "1718800010000000000", "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "run_agent"}}], "status": {"code": 1}}]}]}]})
    f = tmp_path / "mixed.jsonl"
    f.write_text("not valid json\n" + good_line + "\n")
    result = parse_otel_file(f)
    # Still parses the valid line
    assert len(result) == 1
    # And recorded a warning
    assert any(w.code == "malformed_json" for w in result[0].warnings)


def test_unknown_span_type_does_not_crash(tmp_path: Path) -> None:
    import json as _json
    from cctx.parsers.otel import parse_otel_file

    # A span with an unrecognised gen_ai.operation.name
    span = {
        "traceId": "dd00000000000000dd00000000000000",
        "spanId": "dd00000000000001",
        "name": "agent",
        "kind": 3,
        "startTimeUnixNano": "1718800000000000000",
        "endTimeUnixNano": "1718800010000000000",
        "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "run_agent"}}
        ],
        "status": {"code": 1},
    }
    unknown = {
        "traceId": "dd00000000000000dd00000000000000",
        "spanId": "dd00000000000002",
        "parentSpanId": "dd00000000000001",
        "name": "future_span_type",
        "kind": 3,
        "startTimeUnixNano": "1718800001000000000",
        "endTimeUnixNano": "1718800002000000000",
        "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "future_op"}}
        ],
        "status": {"code": 1},
    }
    batch = {"resourceSpans": [{"resource": {"attributes": []}, "scopeSpans": [{"scope": {}, "spans": [span, unknown]}]}]}
    p = tmp_path / "unknown.jsonl"
    p.write_text(_json.dumps(batch) + "\n")
    result = parse_otel_file(p)
    # Parses successfully; unknown span silently ignored (no crash, no warning required)
    assert len(result) == 1
    assert result[0].session_id == "dd00000000000000dd00000000000000"


def test_empty_file_returns_empty_list(tmp_path: Path) -> None:
    from cctx.parsers.otel import parse_otel_file

    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    result = parse_otel_file(empty)
    assert result == []
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_otel_parser.py -v 2>&1 | tail -30
```

Expected: all tests PASS. Unknown span types are already silently ignored by the current implementation (they don't match `invoke_function`, `chat`, or `run_agent` so they're skipped in each `_build_*` function).

- [ ] **Step 3: Commit**

```bash
git add tests/test_otel_parser.py
git commit -m "test: OTEL parser error handling — malformed JSON, unknown spans, empty file"
```

---

## Task 7: Auto-detection helper `_detect_source`

**Files:**
- Modify: `cctx/cli.py`
- Modify: `tests/test_otel_parser.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_otel_parser.py`:

```python
def test_detect_source_identifies_otel(tmp_path: Path) -> None:
    import json as _json
    from cctx.cli import _detect_source

    otel_line = _json.dumps({"resourceSpans": [{"resource": {"attributes": []}, "scopeSpans": []}]})
    p = tmp_path / "trace.jsonl"
    p.write_text(otel_line + "\n")
    assert _detect_source(p) == "otel"


def test_detect_source_identifies_claude_code(tmp_path: Path) -> None:
    import json as _json
    from cctx.cli import _detect_source

    cc_line = _json.dumps({"type": "assistant", "uuid": "abc", "timestamp": "2026-01-01T00:00:00Z"})
    p = tmp_path / "session.jsonl"
    p.write_text(cc_line + "\n")
    assert _detect_source(p) == "claude_code"


def test_detect_source_uses_fixture_otel(tmp_path: Path) -> None:
    from cctx.cli import _detect_source

    assert _detect_source(FIXTURES / "otel_handoff.jsonl") == "otel"


def test_detect_source_unknown_raises_usage_error(tmp_path: Path) -> None:
    import click
    from cctx.cli import _detect_source

    p = tmp_path / "unknown.jsonl"
    p.write_text('{"foo": "bar"}\n')
    with pytest.raises(click.UsageError):
        _detect_source(p)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_otel_parser.py::test_detect_source_identifies_otel tests/test_otel_parser.py::test_detect_source_identifies_claude_code tests/test_otel_parser.py::test_detect_source_uses_fixture_otel tests/test_otel_parser.py::test_detect_source_unknown_raises_usage_error -v
```

Expected: `ImportError` — `_detect_source` not in `cli.py` yet.

- [ ] **Step 3: Implement `_detect_source` in `cli.py`**

Add these lines near the top of `cli.py`, after the existing imports:

```python
import json as _json
```

Then add this function directly before the `@click.group()` decorator (before line `@cli.command("ls")`):

```python
_CLAUDE_CODE_LINE_TYPES = frozenset({
    "user", "assistant", "system", "attachment",
    "last-prompt", "permission-mode", "ai-title", "custom-title",
    "queue-operation", "file-history-snapshot", "pr-link",
})


def _detect_source(path: Path) -> str:
    """Sniff first non-empty lines to detect trace format.

    Returns "claude_code" or "otel".
    Raises click.UsageError if the format cannot be determined.
    """
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for _ in range(5):
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if "resourceSpans" in obj:
                    return "otel"
                if "traceId" in obj and "spanId" in obj:
                    return "otel"
                line_type = obj.get("type")
                if isinstance(line_type, str) and line_type in _CLAUDE_CODE_LINE_TYPES:
                    return "claude_code"
    except OSError as exc:
        raise click.UsageError(f"Cannot read file: {path}: {exc}") from exc

    raise click.UsageError(
        f"Cannot determine trace format for {path}.\n"
        "Expected a Claude Code JSONL session file or an OTLP JSON trace export."
    )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_otel_parser.py::test_detect_source_identifies_otel tests/test_otel_parser.py::test_detect_source_identifies_claude_code tests/test_otel_parser.py::test_detect_source_uses_fixture_otel tests/test_otel_parser.py::test_detect_source_unknown_raises_usage_error -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
uv run pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add cctx/cli.py tests/test_otel_parser.py
git commit -m "feat: _detect_source() — auto-detect Claude Code vs OTEL trace format"
```

---

## Task 8: Wire detection into `autopsy` command

**Files:**
- Modify: `cctx/cli.py`
- Modify: `tests/test_otel_parser.py`

The current single-session path in `autopsy` (around line 418) reads:

```python
trace = tokenize_session(parse_session(target))
```

This hardcodes the Claude Code parser. Replace it with format detection and routing.

- [ ] **Step 1: Add integration test**

Append to `tests/test_otel_parser.py`:

```python
def test_autopsy_command_accepts_otel_file(tmp_path: Path) -> None:
    from click.testing import CliRunner
    from cctx.cli import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["autopsy", str(FIXTURES / "otel_handoff.jsonl")],
        env={"CCTX_OFFLINE": "1"},
        catch_exceptions=False,
    )
    assert result.exit_code in (0, 1)  # 0 = clean, 1 = findings; both are success
    assert "Traceback" not in (result.output or "")
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_otel_parser.py::test_autopsy_command_accepts_otel_file -v
```

Expected: FAIL — the `autopsy` command passes the OTEL file to `parse_session` (Claude Code parser), which raises a `ParserError` or produces wrong output.

- [ ] **Step 3: Add the OTEL import to `cli.py`**

At the top of `cli.py`, alongside the existing `parse_session` import, add:

```python
from cctx.parsers.otel import parse_otel_file as _parse_otel_file
```

- [ ] **Step 4: Replace the hardcoded parser call in `autopsy`**

Find this block in the `autopsy` function (around line 418):

```python
        trace = tokenize_session(parse_session(target))
```

Replace it with:

```python
        source = _detect_source(target)
        if source == "otel":
            otel_traces = _parse_otel_file(target)
            if not otel_traces:
                raise click.UsageError(f"No traces found in {target}")
            trace = tokenize_session(otel_traces[0])
        else:
            trace = tokenize_session(parse_session(target))
```

- [ ] **Step 5: Run the integration test**

```bash
uv run pytest tests/test_otel_parser.py::test_autopsy_command_accepts_otel_file -v
```

Expected: PASS.

- [ ] **Step 6: Run the full test suite**

```bash
uv run pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 7: Smoke test with the real CLI**

```bash
uv run cctx autopsy tests/fixtures/otel_handoff.jsonl
```

Expected: autopsy output with session info (model `gpt-4o`, 1 turn, etc.). No crash.

- [ ] **Step 8: Commit**

```bash
git add cctx/cli.py tests/test_otel_parser.py
git commit -m "feat: wire OTEL auto-detection into autopsy — cctx autopsy <otel.jsonl> just works"
```

---

## Task 9: Quickstart doc

**Files:**
- Create: `docs/quickstart-openai-agents.md`

- [ ] **Step 1: Write the quickstart**

Create `docs/quickstart-openai-agents.md`:

```markdown
# Using cctx with the OpenAI Agents SDK

cctx diagnoses OpenAI Agents SDK runs the same way it diagnoses Claude Code sessions — point it at a trace file and get an autopsy.

## 1. Install dependencies

pip install cctx opentelemetry-sdk

## 2. Export traces to a local file

Add this to your agent script before running your agent. It configures OpenTelemetry to write spans to a local JSONL file.

```python
import json
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export import ReadableSpan
from typing import Sequence


class FileSpanExporter(SpanExporter):
    """Writes OTLP-style JSON batches to a local file, one line per flush."""

    def __init__(self, path: str) -> None:
        self._path = path

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        batch = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "scope": {"name": "openai.agents"},
                    "spans": [self._span_to_dict(s) for s in spans],
                }],
            }]
        }
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(batch) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    @staticmethod
    def _span_to_dict(span: ReadableSpan) -> dict:
        ctx = span.context
        attrs = [
            {"key": k, "value": _otlp_value(v)}
            for k, v in (span.attributes or {}).items()
        ]
        d: dict = {
            "traceId": format(ctx.trace_id, "032x"),
            "spanId": format(ctx.span_id, "016x"),
            "name": span.name,
            "kind": int(span.kind),
            "startTimeUnixNano": str(span.start_time),
            "endTimeUnixNano": str(span.end_time),
            "attributes": attrs,
            "status": {"code": span.status.status_code.value},
        }
        if span.parent is not None:
            d["parentSpanId"] = format(span.parent.span_id, "016x")
        return d


def _otlp_value(v: object) -> dict:
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(FileSpanExporter("agent_trace.jsonl")))

# Wire into the OpenAI Agents SDK — exact API depends on your SDK version:
# from agents import set_trace_processors
# set_trace_processors([...])
```

## 3. Run your agent

python my_agent.py
# agent_trace.jsonl is written

## 4. Diagnose the run

cctx autopsy agent_trace.jsonl

cctx autopsy picks up the OTLP format automatically — no flags needed.

## Notes

- If your trace file contains multiple runs, cctx diagnoses the first trace by trace ID. Use `cctx export agent_trace.jsonl` to inspect all traces.
- Token costs shown in the autopsy are estimates based on OpenAI pricing; cctx does not call the OpenAI API.
- The exact `set_trace_processors` API varies by SDK version. Check the `openai-agents` changelog if the import above doesn't work.
```

- [ ] **Step 2: Commit**

```bash
git add docs/quickstart-openai-agents.md
git commit -m "docs: quickstart guide for OpenAI Agents SDK + cctx OTEL integration"
```

---

## Done

Run the full suite one final time:

```bash
uv run pytest --tb=short -q
```

Then smoke-test both parsers:

```bash
# OTEL
uv run cctx autopsy tests/fixtures/otel_handoff.jsonl

# Claude Code (regression check — pick any real session)
uv run cctx autopsy --latest
```
