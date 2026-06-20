# Diagnosing other agent frameworks with cctx

cctx diagnoses any agent framework that writes OpenTelemetry spans using `gen_ai.*` semantic conventions — the same way it diagnoses Claude Code sessions. Point it at a trace file and get an autopsy.

**Verified frameworks:** OpenAI Agents SDK, LangGraph

---

## OpenAI Agents SDK

### 1. Install dependencies

```bash
pip install cctx-cli opentelemetry-sdk
```

### 2. Export traces to a local file

Add this to your agent script before running your agent. It configures OpenTelemetry to write spans to a local JSONL file.

```python
import json
from typing import Sequence

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export import ReadableSpan


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

### 3. Run your agent

```bash
python my_agent.py
# agent_trace.jsonl is written
```

### 4. Diagnose the run

```bash
cctx autopsy agent_trace.jsonl
```

`cctx autopsy` picks up the OTLP format automatically — no flags needed.

### Notes

- If your trace file contains multiple runs, cctx diagnoses the first trace by trace ID.
- Token costs shown in the autopsy are estimates; cctx does not call the OpenAI API.
- The exact `set_trace_processors` API varies by SDK version — check the `openai-agents` changelog if the import above doesn't work.

---

## LangGraph

LangGraph emits `gen_ai.*` spans via the `opentelemetry-instrumentation-langchain` package from Traceloop. Pair it with the same `FileSpanExporter` above to write traces cctx can read.

### 1. Install dependencies

```bash
pip install cctx-cli opentelemetry-sdk opentelemetry-instrumentation-langchain
```

### 2. Export traces to a local file

Copy the `FileSpanExporter` and `_otlp_value` definitions from the OpenAI Agents SDK section above, then add the LangChain instrumentor before your graph runs:

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.langchain import LangchainInstrumentor

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(FileSpanExporter("agent_trace.jsonl")))

LangchainInstrumentor().instrument(tracer_provider=provider)
```

### 3. Run your graph

```python
from langgraph.graph import StateGraph, END
# ... build graph ...

result = graph.invoke({"messages": [HumanMessage(content="...")]})
# agent_trace.jsonl is written
```

### 4. Diagnose the run

```bash
cctx autopsy agent_trace.jsonl
```

### Notes

- `opentelemetry-instrumentation-langchain` is maintained by [Traceloop](https://github.com/traceloop/openllmetry). It emits `gen_ai.usage.input_tokens`, `gen_ai.request.model`, and other attributes cctx maps to its canonical model.
- LangGraph's `recursion_limit` (default 25) governs step count, not agent nesting depth. cctx handles arbitrary span depth.
- Token costs are estimates; cctx does not call the OpenAI or Anthropic APIs during analysis.

---

## Other frameworks

Any framework instrumented with `gen_ai.*` semantic conventions works. The minimum attributes cctx needs per span:

| Span type | Required attributes |
|---|---|
| Agent span (`run_agent`) | `gen_ai.operation.name = "run_agent"` |
| LLM call (`chat`) | `gen_ai.operation.name = "chat"`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.request.model` |
| Tool call (`invoke_function`) | `gen_ai.operation.name = "invoke_function"`, `gen_ai.tool.name` |

Spans are linked via `parentSpanId`. Use the `FileSpanExporter` above (or any OTLP JSON exporter that writes one `resourceSpans` batch per line) to produce a file cctx can read.
