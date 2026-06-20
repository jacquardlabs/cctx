"""Tests for cctx/parsers/otel.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_otel_file_returns_list() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert isinstance(result, list)
    assert len(result) == 1


def test_parse_otel_file_session_id_is_trace_id() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert result[0].session_id == "aabbccddeeff00112233445566778899"


def test_parse_otel_file_source_path_set() -> None:
    from cctx.parsers.otel import parse_otel_file

    path = FIXTURES / "otel_handoff.jsonl"
    result = parse_otel_file(path)
    assert result[0].source_path == path


def test_parse_otel_file_fanout_returns_one_trace() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_fanout.jsonl")
    assert len(result) == 1
    assert result[0].session_id == "bbccddee00112233bbccddee00112233"


def test_handoff_root_has_one_turn() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    root = result[0]
    assert len(root.turns) == 1


def test_handoff_turn_role_is_assistant() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    turn = result[0].turns[0]
    assert turn.role == "assistant"


def test_handoff_turn_usage_populated() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    usage = result[0].turns[0].usage
    assert usage is not None
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 350


def test_handoff_turn_model() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert result[0].turns[0].model == "gpt-4o"


def test_handoff_turn_number_is_one_based() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert result[0].turns[0].turn_number == 1


def test_handoff_primary_model() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert result[0].primary_model == "gpt-4o"


def test_handoff_start_end_times_set() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    trace = result[0]
    assert trace.start_time is not None
    assert trace.end_time is not None
    assert trace.end_time > trace.start_time


def test_handoff_turn_has_one_tool_use() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    turn = result[0].turns[0]
    assert len(turn.tool_uses) == 1
    assert turn.tool_uses[0].tool_name == "check_priority"
    assert turn.tool_uses[0].tool_use_id == "call_abc123"


def test_handoff_turn_has_one_tool_result() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    turn = result[0].turns[0]
    assert len(turn.tool_results) == 1
    result_obj = turn.tool_results[0]
    assert result_obj.tool_name == "check_priority"
    assert result_obj.tool_use_id == "call_abc123"
    assert result_obj.content == "high"
    assert result_obj.is_error is False


def test_tool_names_loaded_contains_tool() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert "check_priority" in result[0].tool_names_loaded


def test_fanout_orchestrator_has_two_tool_uses() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_fanout.jsonl")
    turn = result[0].turns[0]
    assert len(turn.tool_uses) == 2
    tool_names = {tu.tool_name for tu in turn.tool_uses}
    assert tool_names == {"run_subagent"}
    call_ids = {tu.tool_use_id for tu in turn.tool_uses}
    assert call_ids == {"call_sub1", "call_sub2"}


def test_handoff_produces_one_subagent() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    root = result[0]
    assert len(root.subagents) == 1


def test_handoff_subagent_agent_name_in_meta() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    child = result[0].subagents[0]
    assert child.subagent_meta.get("agent_name") == "ResolutionAgent"


def test_handoff_subagent_has_one_turn() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    child = result[0].subagents[0]
    assert len(child.turns) == 1
    assert child.turns[0].usage is not None
    assert child.turns[0].usage.input_tokens == 2000
    assert child.turns[0].usage.output_tokens == 500


def test_handoff_subagent_parent_session_id_set() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    child = result[0].subagents[0]
    assert child.parent_session_id == "aa00000000000001"


def test_fanout_produces_two_subagents() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_fanout.jsonl")
    root = result[0]
    assert len(root.subagents) == 2


def test_fanout_subagent_names() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_fanout.jsonl")
    names = {s.subagent_meta.get("agent_name") for s in result[0].subagents}
    assert names == {"SubAgent1", "SubAgent2"}


def test_fanout_subagents_each_have_one_turn() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_fanout.jsonl")
    for sub in result[0].subagents:
        assert len(sub.turns) == 1
        assert sub.turns[0].role == "assistant"
