"""Tests for cctx/exporters/jsonl.py."""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pytest

from cctx.models import (
    Confidence,
    Diagnosis,
    Finding,
    FindingKind,
    Patch,  # noqa: F401 — used in _make_diagnosis default
    SessionTrace,
    Severity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc


def _make_diagnosis(
    session_id: str = "sess-abc",
    *,
    inflection_turn: int | None = 5,
    total_cost_usd: float = 2.14,
    waste_cost_usd: float = 0.50,
    findings: list[Finding] | None = None,
    patches: list[Patch] | None = None,
) -> Diagnosis:
    if findings is None:
        findings = [
            Finding(
                kind=FindingKind.RETRY_LOOP,
                severity=Severity.HIGH,
                confidence=Confidence.HIGH,
                first_turn=5,
                last_turn=9,
                evidence={"iterations": 5},
                cost_usd=0.50,
                summary="Agent looped on the same Bash command 5 times.",
            )
        ]
    if patches is None:
        patches = [
            Patch(
                target_file="CLAUDE.md",
                description="Add retry guard.",
                unified_diff="--- a/CLAUDE.md\n+++ b/CLAUDE.md\n@@ ...",
                finding_kind=FindingKind.RETRY_LOOP,
                evidence_summary="5 retry iterations detected.",
            )
        ]
    return Diagnosis(
        session_id=session_id,
        findings=findings,
        inflection_turn=inflection_turn,
        patches=patches,
        total_cost_usd=total_cost_usd,
        waste_cost_usd=waste_cost_usd,
        analysed_at=datetime(2026, 5, 14, 10, 0, 0, tzinfo=UTC),
    )


def _make_trace(session_id: str = "sess-abc", primary_model: str | None = "claude-sonnet-4-6") -> SessionTrace:
    from pathlib import Path
    return SessionTrace(
        session_id=session_id,
        parent_session_id=None,
        project_path="/Users/test/Projects/demo",
        cwd="/Users/test/Projects/demo",
        primary_model=primary_model,
        claude_code_version="2.1.138",
        turns=[],
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=None,
        end_time=None,
        source_path=Path("/fake/sess-abc.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_export_diagnosis_returns_valid_json() -> None:
    """export_diagnosis returns a parseable JSON string."""
    from cctx.exporters.jsonl import export_diagnosis

    diagnosis = _make_diagnosis()
    trace = _make_trace()
    line = export_diagnosis(diagnosis, trace)

    # Must be a string
    assert isinstance(line, str)
    # Must parse as JSON without error
    obj = json.loads(line)
    assert isinstance(obj, dict)


def test_export_diagnosis_has_required_fields() -> None:
    """session_id, findings, patches, total_cost_usd, waste_cost_usd, inflection_turn present."""
    from cctx.exporters.jsonl import export_diagnosis

    diagnosis = _make_diagnosis()
    trace = _make_trace()
    obj = json.loads(export_diagnosis(diagnosis, trace))

    assert obj["session_id"] == "sess-abc"
    assert isinstance(obj["findings"], list)
    assert isinstance(obj["patches"], list)
    assert obj["total_cost_usd"] == pytest.approx(2.14)
    assert obj["waste_cost_usd"] == pytest.approx(0.50)
    assert obj["inflection_turn"] == 5
    assert obj["finding_count"] == 1
    assert obj["turn_count"] == 0
    assert obj["model"] == "claude-sonnet-4-6"


def test_export_diagnosis_analysed_at_is_iso_string() -> None:
    """analysed_at is serialised as an ISO 8601 string, not a datetime object."""
    from cctx.exporters.jsonl import export_diagnosis

    diagnosis = _make_diagnosis()
    trace = _make_trace()
    obj = json.loads(export_diagnosis(diagnosis, trace))

    # Must be a string (not dict, not None)
    assert isinstance(obj["analysed_at"], str)
    # Must round-trip via fromisoformat
    dt = datetime.fromisoformat(obj["analysed_at"])
    assert dt.tzinfo is not None


def test_export_diagnosis_finding_has_expected_keys() -> None:
    """Each finding dict has kind, severity, confidence, first_turn, last_turn, cost_usd, summary."""
    from cctx.exporters.jsonl import export_diagnosis

    diagnosis = _make_diagnosis()
    trace = _make_trace()
    obj = json.loads(export_diagnosis(diagnosis, trace))

    finding = obj["findings"][0]
    assert finding["kind"] == "retry_loop"
    assert finding["severity"] == "high"
    assert finding["confidence"] == "high"
    assert finding["first_turn"] == 5
    assert finding["last_turn"] == 9
    assert finding["cost_usd"] == pytest.approx(0.50)
    assert "summary" in finding


def test_export_diagnosis_patch_has_expected_keys() -> None:
    """Each patch dict has target_file, finding_kind, description, evidence_summary."""
    from cctx.exporters.jsonl import export_diagnosis

    diagnosis = _make_diagnosis()
    trace = _make_trace()
    obj = json.loads(export_diagnosis(diagnosis, trace))

    patch = obj["patches"][0]
    assert patch["target_file"] == "CLAUDE.md"
    assert patch["finding_kind"] == "retry_loop"
    assert "description" in patch
    assert "evidence_summary" in patch


def test_export_diagnosis_no_content_omits_summaries() -> None:
    """include_content=False omits finding summary and patch evidence_summary keys."""
    from cctx.exporters.jsonl import export_diagnosis

    diagnosis = _make_diagnosis()
    trace = _make_trace()
    obj = json.loads(export_diagnosis(diagnosis, trace, include_content=False))

    finding = obj["findings"][0]
    assert "summary" not in finding

    patch = obj["patches"][0]
    assert "evidence_summary" not in patch


def test_export_diagnosis_no_content_keeps_other_fields() -> None:
    """include_content=False still emits all non-text fields."""
    from cctx.exporters.jsonl import export_diagnosis

    diagnosis = _make_diagnosis()
    trace = _make_trace()
    obj = json.loads(export_diagnosis(diagnosis, trace, include_content=False))

    # Session-level fields still present
    assert "session_id" in obj
    assert "total_cost_usd" in obj
    # Finding structural fields still present
    finding = obj["findings"][0]
    assert "kind" in finding
    assert "first_turn" in finding


def test_write_produces_one_line_per_session() -> None:
    """write() with 2 diagnoses produces exactly 2 non-empty lines."""
    from cctx.exporters.jsonl import write

    d1 = _make_diagnosis("sess-001")
    d2 = _make_diagnosis("sess-002")
    t1 = _make_trace("sess-001")
    t2 = _make_trace("sess-002")

    buf = io.StringIO()
    write([(d1, t1), (d2, t2)], buf)

    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 2

    ids = {json.loads(ln)["session_id"] for ln in lines}
    assert ids == {"sess-001", "sess-002"}


def test_export_diagnosis_includes_subagent_costs() -> None:
    """JSON export includes subagent_costs array with correct fields."""
    import dataclasses
    import json

    from cctx.exporters.jsonl import export_diagnosis
    from cctx.models import SubagentAttribution

    diag = _make_diagnosis()
    trace = _make_trace()
    diag = dataclasses.replace(diag, subagent_costs=[
        SubagentAttribution(
            session_id="child-1",
            label="My task",
            total_cost_usd=0.020,
            depth=1,
            model="claude-sonnet-4",
        )
    ])
    data = json.loads(export_diagnosis(diag, trace))
    assert "subagent_costs" in data
    assert len(data["subagent_costs"]) == 1
    assert data["subagent_costs"][0]["session_id"] == "child-1"
    assert data["subagent_costs"][0]["cost_usd"] == pytest.approx(0.020)
    assert data["subagent_costs"][0]["depth"] == 1


def test_export_diagnosis_subagent_costs_empty_by_default() -> None:
    """JSON export has subagent_costs: [] when no subagents."""
    from cctx.exporters.jsonl import export_diagnosis

    diag = _make_diagnosis()
    trace = _make_trace()
    data = json.loads(export_diagnosis(diag, trace))
    assert data["subagent_costs"] == []


def test_write_empty_list_produces_no_output() -> None:
    """write() with an empty list produces no output."""
    from cctx.exporters.jsonl import write

    buf = io.StringIO()
    write([], buf)
    assert buf.getvalue() == ""


def test_write_each_line_is_valid_json() -> None:
    """Every line emitted by write() parses as a JSON object."""
    from cctx.exporters.jsonl import write

    diagnoses = [(_make_diagnosis(f"sess-{i}"), _make_trace(f"sess-{i}")) for i in range(5)]
    buf = io.StringIO()
    write(diagnoses, buf)

    for line in buf.getvalue().splitlines():
        obj = json.loads(line)
        assert isinstance(obj, dict)
