# Design: OTEL parser — OpenAI Agents SDK support via `parsers/otel.py`

**Date:** 2026-06-19
**Status:** Draft

## Overview

Add support for diagnosing OpenAI Agents SDK runs in cctx by parsing OpenTelemetry (OTEL) span exports. Rather than owning a proprietary trace format, cctx reads the OTLP JSON that the OpenAI Agents SDK emits natively — so the same parser works for any framework that emits `gen_ai.*` semantic convention spans (LangChain, LlamaIndex, CrewAI, etc.).

The mapped output is a canonical `SessionTrace`, so all existing diagnostics, renderers, exporters, and harvest commands run unchanged.

## User setup

Users configure the OpenAI Agents SDK to export spans to a local OTLP JSON file. The exact wiring depends on the SDK version and which OTEL exporter packages are installed — `docs/quickstart-openai-agents.md` covers the verified setup. The sketch:

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
# exporter writes OTLP JSON lines to a local file
from <otel_file_exporter> import FileSpanExporter

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(FileSpanExporter("agent_trace.jsonl")))
```

No cctx-owned processor. No proprietary format. The quickstart doc pins exact package versions and verifies the OTEL output shape.

## Auto-detection in `cli.py`

`cctx autopsy <path>` gains a `_detect_source(path: Path) -> Literal["claude_code", "otel"]` helper that sniffs the file before routing to the correct parser:

1. Read the first line; parse as JSON
2. If the object contains `resourceSpans`, `traceId`, or `spanId` at the top level → `"otel"`
3. If `obj.get("type")` is a known Claude Code type (`"user"`, `"assistant"`, `"attachment"`, …) → `"claude_code"`
4. Fall back: attempt to parse the whole file as a single OTLP JSON object → `"otel"`
5. Raise a clear `UsageError` if neither matches

No `--source` flag is required. An explicit `--source {claude_code,otel}` override is available for edge cases.

## New module: `cctx/parsers/otel.py`

### Public API

```python
def parse_otel_file(path: Path) -> list[SessionTrace]:
    """Read an OTLP JSONL export and return one SessionTrace per trace_id."""
```

Returns a list because a single file may contain multiple traces (e.g. a test run that executed several agent runs).

### Span-to-model mapping

The parser groups spans by `trace_id`, reconstructs the parent/child tree via `parentSpanId`, then maps:

| OTEL span (`gen_ai.operation.name`) | cctx model |
|---|---|
| Root `AgentSpan` (`run_agent`, no `parentSpanId`) | `SessionTrace` — `session_id = trace_id`, `cwd` from resource attributes |
| `GenerationSpan` (`chat`) | `Turn(role="assistant")` — `Usage` from `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens`; `model` from `gen_ai.request.model` |
| `FunctionSpan` child of `GenerationSpan` | `ToolUse` + `ToolResult` on the parent turn |
| `HandoffSpan` / child `AgentSpan` | child `SessionTrace` in `subagents` |
| Parallel child `AgentSpan`s | multiple `subagents` — same structure as Claude Code fan-out |
| Grandchild `AgentSpan`s (depth > 1) | recursively built `subagents` on the child — see below |
| Unknown span type | `ParserWarning` emitted; parse continues |

Turn ordering within a `SessionTrace` follows `startTimeUnixNano`. Parallel sub-agents are ordered by start time and each becomes an independent `SessionTrace` in `subagents`.

`_build_subagents` recurses to **arbitrary depth** (#118): each child `AgentSpan`'s own child `AgentSpan`s become its `subagents`, so handoff chains and multi-level orchestrators (OpenAI Agents SDK, LangGraph) are fully represented. A `_visited` span-id set guards against cyclic parent links in malformed traces.

### Layering

`parsers/otel.py` imports only stdlib (`json`, `pathlib`, `datetime`, `collections`) and `cctx.models`. No imports from `anthropic`, `click`, the tokenizer, diagnostician, or any other cctx module.

### Error handling

- Truncated file (crash mid-run): parse all complete span lines; return a partial `SessionTrace` with `ParserWarning(code="truncated_otel_file")`
- Malformed JSON line: emit `ParserWarning(code="malformed_json", line_number=N)`; skip line
- Missing required span attribute: emit `ParserWarning(code="missing_attribute")`; populate field as `None` or empty string

## Testing

### Fixtures

- `tests/fixtures/otel_handoff.jsonl` — two-agent handoff run (sequential): root agent → `HandoffSpan` → child agent
- `tests/fixtures/otel_fanout.jsonl` — orchestrator with two parallel sub-agents

### Test cases (`tests/test_otel_parser.py`)

**Parser:**
- Handoff fixture → root `SessionTrace` + one child in `subagents`; `ToolUse`/`ToolResult` populated; `Usage` correct
- Fan-out fixture → root `SessionTrace` + two children in `subagents`; `SubagentAttribution` cost rollup correct
- Unknown span type → `ParserWarning` emitted; rest of trace parses correctly
- Truncated file → partial `SessionTrace` returned with `ParserWarning`; no exception raised

**Auto-detection (`cli.py`):**
- Claude Code JSONL → routes to `claude_code` parser
- OTEL JSONL → routes to `otel` parser
- Single-object OTLP JSON → routes to `otel` parser
- Unrecognised format → `UsageError` with clear message

## Files touched

| File | Change |
|---|---|
| `cctx/parsers/otel.py` | New — OTEL parser |
| `cctx/cli.py` | Add `_detect_source()`; route `autopsy` through it |
| `tests/fixtures/otel_handoff.jsonl` | New fixture |
| `tests/fixtures/otel_fanout.jsonl` | New fixture |
| `tests/test_otel_parser.py` | New test file |
| `docs/quickstart-openai-agents.md` | New — one-page OTEL setup guide |

No changes to `models.py`, the diagnostician, recommender, renderers, or exporters.

## Out of scope

- Fetching traces from the OpenAI platform Traces API (tracked in #114)
- Generic OTEL collector integration (tracked in #115)
- Adapting `harvest` patches for OpenAI Agents SDK (`AGENTS.md` vs `CLAUDE.md`) — separate design
- `cctx watch` live-tailing OTEL files — future work, depends on this landing first
