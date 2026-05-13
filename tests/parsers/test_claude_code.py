"""Unit tests for the Claude Code JSONL parser."""

from __future__ import annotations

import pytest

from cctx.models import ParserError
from cctx.parsers.claude_code import parse_session
from tests.conftest import make_user_line


def test_missing_file_raises_parser_error(tmp_path):
    with pytest.raises(ParserError) as exc:
        parse_session(tmp_path / "does-not-exist.jsonl")
    assert "does-not-exist" in exc.value.reason


def test_empty_file_returns_minimal_trace(write_jsonl):
    path = write_jsonl([])
    trace = parse_session(path)
    assert trace.turns == []
    assert trace.attachments == []
    assert trace.source_path == path
    assert trace.warnings == []
    assert trace.start_time is None
    assert trace.end_time is None
    assert trace.initial_context_tokens == 0
    assert trace.primary_model is None


def test_accepts_directory_path(tmp_path, write_jsonl):
    """parse_session accepts either the JSONL file or its sibling directory."""
    # Layout: <tmp>/abc123.jsonl with sibling <tmp>/abc123/
    jsonl = write_jsonl([], filename="abc123.jsonl")
    sibling_dir = tmp_path / "abc123"
    sibling_dir.mkdir()

    # When given the directory, parser finds the .jsonl by name.
    trace = parse_session(sibling_dir)
    assert trace.source_path == jsonl
    assert trace.session_id == "abc123"


def test_project_path_decoded_from_dirname(tmp_path):
    """Project path is decoded from the parent dir name's leading-dash convention."""
    project = tmp_path / "-Users-test-Projects-demo"
    project.mkdir()
    jsonl = project / "abc123.jsonl"
    jsonl.write_text("")

    trace = parse_session(jsonl)
    assert trace.project_path == "/Users/test/Projects/demo"
    assert trace.session_id == "abc123"


# --- Task 5: User lines with string content ---


def test_single_user_line_string_content(write_jsonl):
    path = write_jsonl([make_user_line(uuid="u1", content="hello world")])
    trace = parse_session(path)
    assert len(trace.turns) == 1
    turn = trace.turns[0]
    assert turn.turn_number == 1
    assert turn.uuid == "u1"
    assert turn.role == "user"
    assert turn.text == "hello world"
    assert turn.thinking == ""
    assert turn.tool_uses == []
    assert turn.tool_results == []
    assert turn.usage is None
    assert turn.model is None
    assert turn.parent_uuid is None


def test_user_line_timestamp_parsed_to_utc(write_jsonl):
    ts = "2026-05-13T02:00:00.123Z"
    path = write_jsonl([make_user_line(uuid="u1", content="x", timestamp=ts)])
    trace = parse_session(path)
    ts = trace.turns[0].timestamp
    assert ts.tzinfo is not None
    assert ts.isoformat().startswith("2026-05-13T02:00:00")
    assert trace.start_time == ts
    assert trace.end_time == ts


def test_multiple_user_lines_numbered_in_order(write_jsonl):
    path = write_jsonl(
        [
            make_user_line(uuid="u1", content="first", timestamp="2026-05-13T02:00:00.000Z"),
            make_user_line(
                uuid="u2", parent_uuid="u1", content="second", timestamp="2026-05-13T02:00:01.000Z"
            ),  # noqa: E501
            make_user_line(
                uuid="u3", parent_uuid="u2", content="third", timestamp="2026-05-13T02:00:02.000Z"
            ),  # noqa: E501
        ]
    )
    trace = parse_session(path)
    assert [t.turn_number for t in trace.turns] == [1, 2, 3]
    assert [t.text for t in trace.turns] == ["first", "second", "third"]
    assert trace.start_time != trace.end_time
