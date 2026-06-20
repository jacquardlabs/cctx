# Using cctx with the OpenAI Agents SDK

cctx diagnoses OpenAI Agents SDK runs the same way it diagnoses Claude Code sessions — point it at a trace file and get an autopsy.

## 1. Install dependencies

```bash
pip install cctx opentelemetry-sdk
```

## 2. Export traces to a local file

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

## 3. Run your agent

```bash
python my_agent.py
# agent_trace.jsonl is written
```

## 4. Diagnose the run

```bash
cctx autopsy agent_trace.jsonl
```

`cctx autopsy` picks up the OTLP format automatically — no flags needed.

## Notes

- If your trace file contains multiple runs, cctx diagnoses the first trace by trace ID.
- Token costs shown in the autopsy are estimates; cctx does not call the OpenAI API.
- The exact `set_trace_processors` API varies by SDK version — check the `openai-agents` changelog if the import above doesn't work.
