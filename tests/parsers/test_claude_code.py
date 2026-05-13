"""Unit tests for the Claude Code JSONL parser."""

from __future__ import annotations

import pytest

from cctx.models import ParserError
from cctx.parsers.claude_code import parse_session


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
