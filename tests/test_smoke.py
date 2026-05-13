"""Sanity checks for the test infrastructure itself."""

from __future__ import annotations

import json

from tests.conftest import (
    make_assistant_line,
    make_tool_result_block,
    make_tool_use_block,
    make_user_line,
)


def test_factories_produce_valid_json():
    """The line factories must produce dicts that round-trip through JSON."""
    a = make_assistant_line(uuid="a1", text="hello")
    u = make_user_line(uuid="u1", content="hi")
    assert json.loads(json.dumps(a))["type"] == "assistant"
    assert json.loads(json.dumps(u))["type"] == "user"


def test_write_jsonl_factory_writes_file(write_jsonl, tmp_path):
    """The write_jsonl fixture writes one line per element, JSON-encoded."""
    path = write_jsonl([{"a": 1}, {"b": 2}])
    contents = path.read_text().splitlines()
    assert len(contents) == 2
    assert json.loads(contents[0]) == {"a": 1}
    assert json.loads(contents[1]) == {"b": 2}


def test_tool_use_and_result_round_trip():
    """tool_use_id matches between use and result blocks."""
    use = make_tool_use_block("toolu_1", "Read", {"file_path": "/x"})
    result = make_tool_result_block("toolu_1", "contents")
    assert use["id"] == result["tool_use_id"]
