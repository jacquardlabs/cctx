"""Integration tests for the Claude Code JSONL parser against synthetic adversarial fixtures."""

from __future__ import annotations

from pathlib import Path

from cctx.parsers.claude_code import parse_session

SYNTHETIC_DIR = Path(__file__).parent.parent / "fixtures" / "synthetic"


def test_synthetic_malformed_middle_warns_continues_parses_both_sides():
    trace = parse_session(SYNTHETIC_DIR / "malformed_middle.jsonl")
    assert [t.text for t in trace.turns] == ["before", "after"]
    assert any(w.code == "malformed_json" for w in trace.warnings)


def test_synthetic_truncated_final_line_silently_dropped():
    trace = parse_session(SYNTHETIC_DIR / "truncated_final_line.jsonl")
    assert len(trace.turns) == 1
    # No malformed_json warning for the truncated last line.
    assert not any(w.code == "malformed_json" for w in trace.warnings)


def test_synthetic_unknown_type_warns():
    trace = parse_session(SYNTHETIC_DIR / "unknown_type.jsonl")
    assert any(
        w.code == "unknown_type" and w.detail == "tool_search_result" for w in trace.warnings
    )


def test_synthetic_bookkeeping_only_no_warnings():
    trace = parse_session(SYNTHETIC_DIR / "bookkeeping_only.jsonl")
    assert trace.turns == []
    assert trace.warnings == []
    assert trace.start_time is None
    assert trace.end_time is None


def test_synthetic_unknown_attachment_shape_no_warning():
    trace = parse_session(SYNTHETIC_DIR / "unknown_attachment_shape.jsonl")
    assert len(trace.attachments) == 1
    assert trace.attachments[0].kind == "other"
    assert trace.warnings == []
