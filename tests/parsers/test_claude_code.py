"""Unit tests for the Claude Code JSONL parser."""

from __future__ import annotations

import pytest

from cctx.models import ParserError
from cctx.parsers.claude_code import parse_session
from tests.conftest import (
    make_assistant_line,
    make_tool_result_block,
    make_tool_use_block,
    make_user_line,
)


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


# --- Task 6: Assistant lines with text, thinking, and usage ---


def test_assistant_line_text_and_thinking_separate(write_jsonl):
    path = write_jsonl([make_assistant_line(uuid="a1", text="hello", thinking="reasoning…")])
    trace = parse_session(path)
    assert len(trace.turns) == 1
    turn = trace.turns[0]
    assert turn.role == "assistant"
    assert turn.text == "hello"
    assert turn.thinking == "reasoning…"
    assert turn.model == "claude-sonnet-4-6"
    assert turn.stop_reason == "end_turn"


def test_assistant_usage_populated(write_jsonl):
    path = write_jsonl(
        [
            make_assistant_line(
                uuid="a1",
                text="hi",
                input_tokens=5,
                output_tokens=15,
                cache_creation_5m=100,
                cache_creation_1h=200,
                cache_read=50,
            )
        ]
    )
    trace = parse_session(path)
    u = trace.turns[0].usage
    assert u is not None
    assert u.input_tokens == 5
    assert u.output_tokens == 15
    assert u.cache_creation_5m == 100
    assert u.cache_creation_1h == 200
    assert u.cache_read == 50
    assert u.service_tier == "standard"


def test_assistant_with_no_text_or_thinking(write_jsonl):
    """Assistant message with only tool_use blocks — text/thinking are empty strings, not None."""
    path = write_jsonl(
        [make_assistant_line(uuid="a1", tool_uses=[make_tool_use_block("toolu_1", "Read")])]
    )
    trace = parse_session(path)
    turn = trace.turns[0]
    assert turn.text == ""
    assert turn.thinking == ""


def test_assistant_concatenates_multiple_text_blocks(write_jsonl):
    """Multiple text blocks in the same message are joined."""
    line = make_assistant_line(uuid="a1", text="part one")
    # Add a second text block manually.
    line["message"]["content"].append({"type": "text", "text": "part two"})
    path = write_jsonl([line])
    trace = parse_session(path)
    assert trace.turns[0].text == "part one\npart two"


# --- Task 7: Tool use blocks on assistant lines ---


def test_single_tool_use_block(write_jsonl):
    use = make_tool_use_block("toolu_1", "Read", {"file_path": "/x"})
    path = write_jsonl([make_assistant_line(uuid="a1", tool_uses=[use])])
    trace = parse_session(path)
    turn = trace.turns[0]
    assert len(turn.tool_uses) == 1
    tu = turn.tool_uses[0]
    assert tu.tool_name == "Read"
    assert tu.tool_use_id == "toolu_1"
    assert tu.tool_input == {"file_path": "/x"}
    assert tu.subagent_session_id is None


def test_multiple_parallel_tool_uses_in_one_message(write_jsonl):
    """An assistant message firing 3 parallel tool calls produces ONE Turn with 3 tool_uses."""
    uses = [
        make_tool_use_block("toolu_1", "Read", {"file_path": "/a"}),
        make_tool_use_block("toolu_2", "Read", {"file_path": "/b"}),
        make_tool_use_block("toolu_3", "Grep", {"pattern": "foo"}),
    ]
    path = write_jsonl([make_assistant_line(uuid="a1", tool_uses=uses)])
    trace = parse_session(path)
    turn = trace.turns[0]
    assert len(turn.tool_uses) == 3
    assert [tu.tool_name for tu in turn.tool_uses] == ["Read", "Read", "Grep"]
    assert [tu.tool_use_id for tu in turn.tool_uses] == ["toolu_1", "toolu_2", "toolu_3"]


# --- Task 8: User lines with tool_result content ---


def test_user_line_with_tool_result_becomes_tool_result_role(write_jsonl):
    block = make_tool_result_block("toolu_1", "file contents")
    path = write_jsonl(
        [
            make_assistant_line(uuid="a1", tool_uses=[make_tool_use_block("toolu_1", "Read")]),
            make_user_line(uuid="u1", parent_uuid="a1", content=[block]),
        ]
    )
    trace = parse_session(path)
    assert len(trace.turns) == 2
    tr_turn = trace.turns[1]
    assert tr_turn.role == "tool_result"
    assert len(tr_turn.tool_results) == 1
    tr = tr_turn.tool_results[0]
    assert tr.tool_use_id == "toolu_1"
    assert tr.content == "file contents"
    assert tr.is_error is False
    assert tr.tool_name == "Read"  # paired in from the originating ToolUse


def test_tool_result_content_can_be_list_of_text_blocks(write_jsonl):
    """tool_result.content is sometimes a list of {type, text} blocks; flatten to a string."""
    block = make_tool_result_block(
        "toolu_1",
        [{"type": "text", "text": "line one"}, {"type": "text", "text": "line two"}],
    )
    path = write_jsonl(
        [
            make_assistant_line(uuid="a1", tool_uses=[make_tool_use_block("toolu_1", "Bash")]),
            make_user_line(uuid="u1", parent_uuid="a1", content=[block]),
        ]
    )
    trace = parse_session(path)
    tr = trace.turns[1].tool_results[0]
    assert tr.content == "line one\nline two"


def test_three_parallel_tool_results_in_one_user_line(write_jsonl):
    """Parallel tool calls produce one user line with multiple tool_result blocks."""
    path = write_jsonl(
        [
            make_assistant_line(
                uuid="a1",
                tool_uses=[
                    make_tool_use_block("toolu_1", "Read", {"file_path": "/a"}),
                    make_tool_use_block("toolu_2", "Read", {"file_path": "/b"}),
                    make_tool_use_block("toolu_3", "Grep", {"pattern": "x"}),
                ],
            ),
            make_user_line(
                uuid="u1",
                parent_uuid="a1",
                content=[
                    make_tool_result_block("toolu_1", "a-contents"),
                    make_tool_result_block("toolu_2", "b-contents"),
                    make_tool_result_block("toolu_3", "no matches"),
                ],
            ),
        ]
    )
    trace = parse_session(path)
    assert len(trace.turns) == 2
    tr_turn = trace.turns[1]
    assert tr_turn.role == "tool_result"
    assert [tr.tool_use_id for tr in tr_turn.tool_results] == ["toolu_1", "toolu_2", "toolu_3"]
    assert [tr.tool_name for tr in tr_turn.tool_results] == ["Read", "Read", "Grep"]


def test_tool_result_is_error_flag(write_jsonl):
    block = make_tool_result_block("toolu_1", "tool execution failed", is_error=True)
    path = write_jsonl(
        [
            make_assistant_line(uuid="a1", tool_uses=[make_tool_use_block("toolu_1", "Bash")]),
            make_user_line(uuid="u1", parent_uuid="a1", content=[block]),
        ]
    )
    trace = parse_session(path)
    assert trace.turns[1].tool_results[0].is_error is True


def test_tool_result_structured_field_populated_from_tool_use_result(write_jsonl):
    """The parallel toolUseResult field on the line goes onto ToolResult.structured."""
    block = make_tool_result_block("toolu_1", "short content")
    line = make_user_line(
        uuid="u1",
        content=[block],
        tool_use_result={
            "type": "text",
            "file": {"filePath": "/a", "content": "...", "numLines": 10},
        },
    )
    path = write_jsonl(
        [
            make_assistant_line(uuid="a1", tool_uses=[make_tool_use_block("toolu_1", "Read")]),
            line,
        ]
    )
    trace = parse_session(path)
    tr = trace.turns[1].tool_results[0]
    assert tr.structured is not None
    assert tr.structured["file"]["filePath"] == "/a"


# --- Task 9: Mixed [text, image] and text-block-list user content ---


def test_user_line_with_text_and_image_blocks(write_jsonl):
    """Mixed [text, image] arrays (seen in real data) dispatch to role='user'."""
    content = [
        {"type": "text", "text": "look at this:"},
        {"type": "image", "source": {"media_type": "image/png", "data": "aGVsbG8="}},
    ]
    path = write_jsonl([make_user_line(uuid="u1", content=content)])
    trace = parse_session(path)
    assert len(trace.turns) == 1
    turn = trace.turns[0]
    assert turn.role == "user"
    assert "look at this:" in turn.text
    assert "<image:image/png," in turn.text


def test_user_line_with_only_text_block_list(write_jsonl):
    """Some user lines have content=[{type:text,...}] instead of a bare string."""
    content = [{"type": "text", "text": "hello from a list"}]
    path = write_jsonl([make_user_line(uuid="u1", content=content)])
    trace = parse_session(path)
    assert trace.turns[0].role == "user"
    assert trace.turns[0].text == "hello from a list"
