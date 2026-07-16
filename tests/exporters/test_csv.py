"""Tests for cctx/exporters/csv.py."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cctx.models import (
    Confidence,
    Diagnosis,
    Finding,
    FindingKind,
    SessionTrace,
    Severity,
    Turn,
    Usage,
)

UTC = timezone.utc

_TS = datetime(2026, 5, 14, 10, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_turn(
    turn_number: int,
    role: str = "assistant",
    model: str | None = "claude-sonnet-4-6",
    input_tokens: int = 100,
    tool_names: list[str] | None = None,
) -> Turn:
    from cctx.models import ToolUse

    usage = (
        Usage(
            input_tokens=input_tokens,
            output_tokens=20,
            cache_creation_5m=0,
            cache_creation_1h=0,
            cache_read=0,
            service_tier="standard",
        )
        if role == "assistant"
        else None
    )
    tool_uses = [
        ToolUse(tool_name=name, tool_use_id=f"tu-{i}", tool_input={})
        for i, name in enumerate(tool_names or [])
    ]
    return Turn(
        turn_number=turn_number,
        uuid=f"uuid-{turn_number}",
        parent_uuid=None,
        role=role,
        text="",
        thinking="",
        tool_uses=tool_uses,
        tool_results=[],
        usage=usage,
        model=model,
        stop_reason="end_turn" if role == "assistant" else None,
        timestamp=_TS,
        duration_ms=None,
    )


def _make_trace(session_id: str = "sess-xyz", turns: list[Turn] | None = None) -> SessionTrace:
    return SessionTrace(
        session_id=session_id,
        parent_session_id=None,
        project_path="/Users/test",
        cwd="/Users/test",
        primary_model="claude-sonnet-4-6",
        claude_code_version="2.1.138",
        turns=turns or [],
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=None,
        end_time=None,
        source_path=Path("/fake/sess-xyz.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


def _make_diagnosis(
    session_id: str = "sess-xyz",
    inflection_turn: int | None = 3,
    findings: list[Finding] | None = None,
) -> Diagnosis:
    if findings is None:
        findings = [
            Finding(
                kind=FindingKind.RETRY_LOOP,
                severity=Severity.HIGH,
                confidence=Confidence.HIGH,
                first_turn=3,
                last_turn=5,
                evidence={},
                cost_usd=0.01,
                summary="Loop.",
            )
        ]
    return Diagnosis(
        session_id=session_id,
        findings=findings,
        inflection_turn=inflection_turn,
        patches=[],
        total_cost_usd=1.0,
        waste_cost_usd=0.01,
        analysed_at=_TS,
    )


def _read_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Parse CSV text into (headers, rows)."""
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    rows = list(reader)
    return list(headers), rows


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_csv_has_header_row() -> None:
    """write() emits a header row containing all COLUMNS."""
    from cctx.exporters.csv import COLUMNS, write

    turns = [_make_turn(1), _make_turn(2, role="user", model=None, input_tokens=0)]
    trace = _make_trace(turns=turns)
    diagnosis = _make_diagnosis()

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    headers, _ = _read_csv(buf.getvalue())
    for col in COLUMNS:
        assert col in headers, f"Expected column '{col}' in CSV header"


def test_csv_one_row_per_turn() -> None:
    """write() emits exactly one data row per turn."""
    from cctx.exporters.csv import write

    turns = [_make_turn(i) for i in range(1, 6)]
    trace = _make_trace(turns=turns)
    diagnosis = _make_diagnosis(findings=[])

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    _, rows = _read_csv(buf.getvalue())
    assert len(rows) == 5


def test_inflection_turn_flagged() -> None:
    """Turn matching inflection_turn has is_inflection_turn == 'true'; others 'false'."""
    from cctx.exporters.csv import write

    turns = [_make_turn(i) for i in range(1, 5)]
    trace = _make_trace(turns=turns)
    diagnosis = _make_diagnosis(inflection_turn=2, findings=[])

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    _, rows = _read_csv(buf.getvalue())
    flags = {int(r["turn_number"]): r["is_inflection_turn"] for r in rows}
    assert flags[2] == "true"
    assert flags[1] == "false"
    assert flags[3] == "false"


def test_finding_kind_on_first_turn() -> None:
    """finding_kinds cell lists finding kind(s) only on the turn where first_turn matches."""
    from cctx.exporters.csv import write

    turns = [_make_turn(i) for i in range(1, 6)]
    trace = _make_trace(turns=turns)
    finding = Finding(
        kind=FindingKind.SCOPE_CREEP,
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=3,
        last_turn=5,
        evidence={},
        cost_usd=None,
        summary="Scope expanded.",
    )
    diagnosis = _make_diagnosis(inflection_turn=None, findings=[finding])

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    _, rows = _read_csv(buf.getvalue())
    by_turn = {int(r["turn_number"]): r for r in rows}
    assert by_turn[3]["finding_kinds"] == "scope_creep"
    assert by_turn[1]["finding_kinds"] == ""
    assert by_turn[5]["finding_kinds"] == ""


def test_tool_names_joined() -> None:
    """tool_names cell is comma-joined list of tool names for a turn."""
    from cctx.exporters.csv import write

    turns = [_make_turn(1, tool_names=["Bash", "Read"])]
    trace = _make_trace(turns=turns)
    diagnosis = _make_diagnosis(inflection_turn=None, findings=[])

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    _, rows = _read_csv(buf.getvalue())
    assert rows[0]["tool_names"] == "Bash,Read"


def test_no_usage_turn_has_zero_tokens_and_cost() -> None:
    """User/tool_result turns with no usage get input_tokens=0 and cost_usd=0.0."""
    from cctx.exporters.csv import write

    turns = [_make_turn(1, role="user", model=None, input_tokens=0)]
    trace = _make_trace(turns=turns)
    diagnosis = _make_diagnosis(inflection_turn=None, findings=[])

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    _, rows = _read_csv(buf.getvalue())
    assert rows[0]["input_tokens"] == "0"
    assert float(rows[0]["cost_usd"]) == pytest.approx(0.0)


def test_session_id_in_every_row() -> None:
    """Every row carries the session_id from the trace."""
    from cctx.exporters.csv import write

    turns = [_make_turn(i) for i in range(1, 4)]
    trace = _make_trace(session_id="my-session", turns=turns)
    diagnosis = _make_diagnosis(session_id="my-session", findings=[])

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    _, rows = _read_csv(buf.getvalue())
    for row in rows:
        assert row["session_id"] == "my-session"


def test_multiple_sessions_all_rows_present() -> None:
    """write() with 2 sessions emits rows for all turns from both."""
    from cctx.exporters.csv import write

    turns_a = [_make_turn(i) for i in range(1, 4)]  # 3 turns
    turns_b = [_make_turn(i) for i in range(1, 3)]  # 2 turns
    trace_a = _make_trace(session_id="sess-A", turns=turns_a)
    trace_b = _make_trace(session_id="sess-B", turns=turns_b)
    diag_a = _make_diagnosis(session_id="sess-A", findings=[])
    diag_b = _make_diagnosis(session_id="sess-B", findings=[])

    buf = io.StringIO()
    write([(diag_a, trace_a), (diag_b, trace_b)], buf)

    _, rows = _read_csv(buf.getvalue())
    assert len(rows) == 5
    session_ids = {r["session_id"] for r in rows}
    assert session_ids == {"sess-A", "sess-B"}


def test_export_turn_rows_returns_correct_count() -> None:
    """export_turn_rows returns one dict per turn."""
    from cctx.exporters.csv import export_turn_rows

    turns = [_make_turn(i) for i in range(1, 4)]
    trace = _make_trace(turns=turns)
    diagnosis = _make_diagnosis(findings=[])

    rows = export_turn_rows(diagnosis, trace)
    assert len(rows) == 3


def test_csv_cost_includes_cache_read() -> None:
    """Per-turn cost_usd must include cache_read at 10% of input rate."""
    import dataclasses
    from datetime import datetime, timezone

    from cctx.exporters.csv import export_turn_rows
    from cctx.models import Diagnosis, Usage
    from tests.diagnostician.conftest import make_assistant_turn, make_trace, make_user_turn

    # Sonnet rate = $3/MTok = 3e-6 per token
    # 1000 input × 1.00 + 10000 cache_read × 0.10 = 2000 effective tokens × 3e-6 = $0.006
    t = make_assistant_turn(2, text="ok")
    t = dataclasses.replace(
        t,
        usage=Usage(
            input_tokens=1_000,
            output_tokens=20,
            cache_creation_5m=0,
            cache_creation_1h=0,
            cache_read=10_000,
            service_tier=None,
        ),
        model="claude-sonnet-4-6",
    )
    trace = make_trace([make_user_turn(1), t], model="claude-sonnet-4-6")
    diag = Diagnosis(
        session_id="test",
        findings=[],
        inflection_turn=None,
        patches=[],
        total_cost_usd=0.0,
        waste_cost_usd=0.0,
        analysed_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
    )
    rows = export_turn_rows(diag, trace)
    assistant_row = next(r for r in rows if r["role"] == "assistant")
    cost = float(assistant_row["cost_usd"])
    # 1000 × 3e-6 + 10000 × 3e-6 × 0.10 = 3e-3 + 3e-3 = 6e-3 = 0.006
    assert abs(cost - 0.006) < 1e-6, f"Expected ~0.006 but got {cost}"


def test_csv_export_has_no_subagent_dispatch_join_key() -> None:
    """Characterizes #193's finding: CSV rows carry no field linking a parent
    turn's Task/Agent tool_use_id to the subagent session it dispatched, and
    subagent turns are never exported as rows at all — export_turn_rows only
    iterates trace.turns (the root session), never trace.subagents.
    """
    import dataclasses

    from cctx.exporters.csv import COLUMNS, write
    from cctx.models import ToolUse

    child_turn = _make_turn(1)
    child_trace = _make_trace(session_id="child-session", turns=[child_turn])

    dispatch_tool_use = ToolUse(
        tool_name="Task",
        tool_use_id="tu-dispatch",
        tool_input={"description": "child task"},
        subagent_session_id="child-session",
    )
    dispatch_turn = dataclasses.replace(
        _make_turn(1, tool_names=[]),
        tool_uses=[dispatch_tool_use],
    )
    trace = dataclasses.replace(
        _make_trace(turns=[dispatch_turn]),
        subagents=[child_trace],
    )
    diagnosis = _make_diagnosis(findings=[])

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    # No column exposes the dispatch join key.
    assert "tool_use_id" not in COLUMNS
    assert "subagent_session_id" not in COLUMNS

    # The child session's own turn never appears as a row — only the
    # parent's dispatch_turn does.
    _, rows = _read_csv(buf.getvalue())
    assert len(rows) == 1
    assert rows[0]["session_id"] == "sess-xyz"
