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
    SubagentAttribution,
    ToolUse,
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


def _make_trace(
    session_id: str = "sess-xyz",
    turns: list[Turn] | None = None,
    subagents: list[SessionTrace] | None = None,
    parent_session_id: str | None = None,
) -> SessionTrace:
    return SessionTrace(
        session_id=session_id,
        parent_session_id=parent_session_id,
        project_path="/Users/test",
        cwd="/Users/test",
        primary_model="claude-sonnet-4-6",
        claude_code_version="2.1.138",
        turns=turns or [],
        subagents=subagents or [],
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
    subagent_costs: list[SubagentAttribution] | None = None,
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
        subagent_costs=subagent_costs or [],
    )


def _attribution(
    session_id: str,
    dispatching_tool_use_id: str | None,
    depth: int = 1,
) -> SubagentAttribution:
    return SubagentAttribution(
        session_id=session_id,
        label=session_id,
        total_cost_usd=0.0,
        depth=depth,
        model="claude-sonnet-4-6",
        dispatching_tool_use_id=dispatching_tool_use_id,
    )


def _dispatch_tool_use(tool_use_id: str, child_session_id: str) -> ToolUse:
    return ToolUse(
        tool_name="Agent",
        tool_use_id=tool_use_id,
        tool_input={"description": f"dispatch {child_session_id}"},
        subagent_session_id=child_session_id,
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


# ---------------------------------------------------------------------------
# Subagent rows + dispatch join key (#194 / #195)
# ---------------------------------------------------------------------------


def _one_child_trace(
    *,
    child_session_id: str = "child-session",
    child_turns: list[Turn] | None = None,
) -> SessionTrace:
    """Root with one dispatch turn and one direct subagent."""
    import dataclasses

    child = _make_trace(
        session_id=child_session_id,
        turns=child_turns if child_turns is not None else [_make_turn(1)],
        parent_session_id="sess-xyz",
    )
    dispatch_turn = dataclasses.replace(
        _make_turn(1),
        tool_uses=[_dispatch_tool_use("tu-dispatch", child_session_id)],
    )
    return _make_trace(turns=[dispatch_turn], subagents=[child])


def test_csv_export_has_subagent_dispatch_join_key() -> None:
    """CSV rows carry the Agent tool_use_id that dispatched the session they
    belong to — the join key jig/studious use to correlate a dispatch-time
    routing decision against its actual cost (#194, closing #193's CSV gap).
    """
    from cctx.exporters.csv import COLUMNS, write

    trace = _one_child_trace()
    diagnosis = _make_diagnosis(
        findings=[],
        subagent_costs=[_attribution("child-session", "tu-dispatch")],
    )

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    for col in ("depth", "parent_session_id", "dispatching_tool_use_id",
                "root_dispatch_tool_use_id"):
        assert col in COLUMNS

    _, rows = _read_csv(buf.getvalue())
    assert len(rows) == 2
    child_row = next(r for r in rows if r["session_id"] == "child-session")
    assert child_row["depth"] == "1"
    assert child_row["parent_session_id"] == "sess-xyz"
    assert child_row["dispatching_tool_use_id"] == "tu-dispatch"
    assert child_row["root_dispatch_tool_use_id"] == "tu-dispatch"


def test_csv_root_rows_have_empty_dispatch_columns() -> None:
    """Root turns are depth 0 with no parent and no dispatch identity."""
    from cctx.exporters.csv import write

    trace = _one_child_trace()
    diagnosis = _make_diagnosis(
        findings=[],
        subagent_costs=[_attribution("child-session", "tu-dispatch")],
    )

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    _, rows = _read_csv(buf.getvalue())
    root_row = next(r for r in rows if r["session_id"] == "sess-xyz")
    assert root_row["depth"] == "0"
    assert root_row["parent_session_id"] == ""
    assert root_row["dispatching_tool_use_id"] == ""
    assert root_row["root_dispatch_tool_use_id"] == ""


def test_csv_rows_in_dfs_order() -> None:
    """Root turns first, then each subagent's turns, each subtree contiguous —
    the same DFS order Diagnosis.subagent_costs uses."""
    import dataclasses

    from cctx.exporters.csv import write

    child_a = _make_trace("child-a", turns=[_make_turn(1)], parent_session_id="sess-xyz")
    child_b = _make_trace("child-b", turns=[_make_turn(1)], parent_session_id="sess-xyz")
    root_turn = dataclasses.replace(
        _make_turn(1),
        tool_uses=[
            _dispatch_tool_use("tu-a", "child-a"),
            _dispatch_tool_use("tu-b", "child-b"),
        ],
    )
    trace = _make_trace(turns=[root_turn, _make_turn(2)], subagents=[child_a, child_b])
    diagnosis = _make_diagnosis(
        findings=[],
        subagent_costs=[_attribution("child-a", "tu-a"), _attribution("child-b", "tu-b")],
    )

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    _, rows = _read_csv(buf.getvalue())
    assert [r["session_id"] for r in rows] == [
        "sess-xyz", "sess-xyz", "child-a", "child-b",
    ]


def test_csv_root_dispatch_rolls_up_through_grandchild() -> None:
    """A depth-2 row's dispatching_tool_use_id is its own (inner) dispatch,
    while root_dispatch_tool_use_id stays the depth-1 dispatch — so one
    GROUP BY on root_dispatch_tool_use_id gives inclusive per-dispatch cost."""
    import dataclasses

    from cctx.exporters.csv import write

    grandchild = _make_trace("grandchild", turns=[_make_turn(1)], parent_session_id="child-a")
    child_turn = dataclasses.replace(
        _make_turn(1),
        tool_uses=[_dispatch_tool_use("tu-inner", "grandchild")],
    )
    child_a = _make_trace(
        "child-a", turns=[child_turn], subagents=[grandchild], parent_session_id="sess-xyz"
    )
    root_turn = dataclasses.replace(
        _make_turn(1),
        tool_uses=[_dispatch_tool_use("tu-outer", "child-a")],
    )
    trace = _make_trace(turns=[root_turn], subagents=[child_a])
    diagnosis = _make_diagnosis(
        findings=[],
        subagent_costs=[
            _attribution("child-a", "tu-outer", depth=1),
            _attribution("grandchild", "tu-inner", depth=2),
        ],
    )

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    _, rows = _read_csv(buf.getvalue())
    by_sid = {r["session_id"]: r for r in rows}
    assert by_sid["grandchild"]["depth"] == "2"
    assert by_sid["grandchild"]["parent_session_id"] == "child-a"
    assert by_sid["grandchild"]["dispatching_tool_use_id"] == "tu-inner"
    assert by_sid["grandchild"]["root_dispatch_tool_use_id"] == "tu-outer"
    assert by_sid["child-a"]["root_dispatch_tool_use_id"] == "tu-outer"


def test_csv_depth_zero_filter_recovers_root_only_rows() -> None:
    """Filtering depth == 0 reproduces the pre-#194 root-only table exactly."""
    from cctx.exporters.csv import write

    original_columns = [
        "session_id", "turn_number", "role", "model", "input_tokens",
        "cost_usd", "tool_names", "finding_kinds", "is_inflection_turn",
    ]

    with_subagents = _one_child_trace()
    root_only = _make_trace(turns=with_subagents.turns)
    diagnosis = _make_diagnosis(
        findings=[],
        subagent_costs=[_attribution("child-session", "tu-dispatch")],
    )

    buf_a, buf_b = io.StringIO(), io.StringIO()
    write([(diagnosis, with_subagents)], buf_a)
    write([(diagnosis, root_only)], buf_b)

    _, rows_a = _read_csv(buf_a.getvalue())
    _, rows_b = _read_csv(buf_b.getvalue())
    depth_zero = [{k: r[k] for k in original_columns} for r in rows_a if r["depth"] == "0"]
    assert depth_zero == [{k: r[k] for k in original_columns} for r in rows_b]


def test_csv_root_findings_do_not_leak_onto_subagent_turns() -> None:
    """finding_kinds is scoped by session_id — turn numbers restart at 1 in
    every subagent trace, so a bare turn_number key would collide."""
    from cctx.exporters.csv import write

    trace = _one_child_trace()
    root_finding = Finding(
        kind=FindingKind.SCOPE_CREEP,
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=1,
        last_turn=1,
        evidence={},
        cost_usd=None,
        summary="Root scope creep.",
    )
    child_finding = Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=1,
        last_turn=1,
        evidence={},
        cost_usd=None,
        summary="Child retry loop.",
        session_id="child-session",
    )
    diagnosis = _make_diagnosis(
        findings=[root_finding, child_finding],
        subagent_costs=[_attribution("child-session", "tu-dispatch")],
    )

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    _, rows = _read_csv(buf.getvalue())
    by_sid = {r["session_id"]: r for r in rows}
    assert by_sid["sess-xyz"]["finding_kinds"] == "scope_creep"
    assert by_sid["child-session"]["finding_kinds"] == "retry_loop"


def test_csv_inflection_turn_not_flagged_on_subagent_rows() -> None:
    """inflection_turn is detected on root findings only — a subagent turn
    sharing that number must not be flagged."""
    from cctx.exporters.csv import write

    trace = _one_child_trace(child_turns=[_make_turn(1), _make_turn(2)])
    diagnosis = _make_diagnosis(
        inflection_turn=1,
        findings=[],
        subagent_costs=[_attribution("child-session", "tu-dispatch")],
    )

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    _, rows = _read_csv(buf.getvalue())
    root_row = next(r for r in rows if r["session_id"] == "sess-xyz")
    child_turn_1 = next(
        r for r in rows if r["session_id"] == "child-session" and r["turn_number"] == "1"
    )
    assert root_row["is_inflection_turn"] == "true"
    assert child_turn_1["is_inflection_turn"] == "false"


def test_csv_orphaned_subagent_has_empty_dispatch_columns() -> None:
    """A subagent with no matching SubagentAttribution still gets rows —
    structural columns (depth, parent_session_id) are correct, dispatch
    identity is empty rather than missing."""
    from cctx.exporters.csv import write

    grandchild = _make_trace("under-orphan", turns=[_make_turn(1)], parent_session_id="orphan")
    child = _make_trace(
        "orphan", turns=[_make_turn(1)], subagents=[grandchild], parent_session_id="sess-xyz"
    )
    trace = _make_trace(turns=[_make_turn(1)], subagents=[child])
    diagnosis = _make_diagnosis(findings=[])  # no subagent_costs

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    _, rows = _read_csv(buf.getvalue())
    by_sid = {r["session_id"]: r for r in rows}
    assert by_sid["orphan"]["depth"] == "1"
    assert by_sid["orphan"]["parent_session_id"] == "sess-xyz"
    assert by_sid["orphan"]["dispatching_tool_use_id"] == ""
    assert by_sid["orphan"]["root_dispatch_tool_use_id"] == ""
    # A descendant of an unlinked dispatch has no top-level dispatch to roll up
    # to — it stays blank rather than inheriting a wrong key.
    assert by_sid["under-orphan"]["depth"] == "2"
    assert by_sid["under-orphan"]["parent_session_id"] == "orphan"
    assert by_sid["under-orphan"]["root_dispatch_tool_use_id"] == ""


def test_csv_subagent_turn_priced_at_own_model() -> None:
    """Subagent rows are priced at the subagent's model, not the root's."""
    from cctx.exporters.csv import write

    # Sonnet-4 family = $3/MTok input; Opus 5 = $5/MTok.
    child_turn = _make_turn(1, model="claude-opus-5", input_tokens=1_000)
    # The root's dispatch turn keeps _make_turn's default 100 input tokens.
    trace = _one_child_trace(child_turns=[child_turn])
    diagnosis = _make_diagnosis(
        findings=[],
        subagent_costs=[_attribution("child-session", "tu-dispatch")],
    )

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    _, rows = _read_csv(buf.getvalue())
    root_row = next(r for r in rows if r["session_id"] == "sess-xyz")
    child_row = next(r for r in rows if r["session_id"] == "child-session")
    assert float(root_row["cost_usd"]) == pytest.approx(100 * 3e-6)
    assert float(child_row["cost_usd"]) == pytest.approx(1_000 * 5e-6)
