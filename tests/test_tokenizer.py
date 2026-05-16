"""Tests for cctx.tokenizer using the offline heuristic mode (no live API)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cctx.models import SessionTrace, ToolResult, ToolUse, Turn


def _make_minimal_trace(
    *,
    turns: list[Turn] | None = None,
    subagents: list[SessionTrace] | None = None,
) -> SessionTrace:
    return SessionTrace(
        session_id="test",
        parent_session_id=None,
        project_path="/p",
        cwd="/p",
        primary_model=None,
        claude_code_version=None,
        turns=turns or [],
        subagents=subagents or [],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=None,
        end_time=None,
        source_path=Path("/p/test.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


def _make_turn(
    role: str = "user",
    *,
    text: str = "",
    thinking: str = "",
    tool_uses: list[ToolUse] | None = None,
    tool_results: list[ToolResult] | None = None,
) -> Turn:
    return Turn(
        turn_number=1,
        uuid="u",
        parent_uuid=None,
        role=role,
        text=text,
        thinking=thinking,
        tool_uses=tool_uses or [],
        tool_results=tool_results or [],
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=datetime(2026, 5, 13, tzinfo=timezone.utc),
        duration_ms=None,
    )


def test_tokenize_populates_turn_token_count(monkeypatch):
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.tokenizer import tokenize_session

    trace = _make_minimal_trace(turns=[_make_turn(text="hello world")])
    tokenize_session(trace)
    assert trace.turns[0].token_count > 0


def test_tokenize_populates_tool_use_and_result(monkeypatch):
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.tokenizer import tokenize_session

    use = ToolUse(tool_name="Read", tool_use_id="t1", tool_input={"file_path": "/x"})
    result = ToolResult(
        tool_name="Read",
        tool_use_id="t1",
        content="some contents",
        structured=None,
        is_error=False,
    )
    trace = _make_minimal_trace(
        turns=[
            _make_turn("assistant", text="reading", tool_uses=[use]),
            _make_turn("tool_result", tool_results=[result]),
        ]
    )
    tokenize_session(trace)
    assert trace.turns[0].tool_uses[0].token_count > 0
    assert trace.turns[1].tool_results[0].token_count > 0


def test_tokenize_recurses_into_subagents(monkeypatch):
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.tokenizer import tokenize_session

    child = _make_minimal_trace(turns=[_make_turn(text="subagent text")])
    parent = _make_minimal_trace(subagents=[child])
    tokenize_session(parent)
    assert parent.subagents[0].turns[0].token_count > 0


def test_tokenize_missing_api_key_falls_back_to_heuristic(monkeypatch):
    """No API key and no CCTX_OFFLINE → heuristic fallback, not RuntimeError."""
    monkeypatch.delenv("CCTX_OFFLINE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from cctx.tokenizer import tokenize_session

    trace = _make_minimal_trace(turns=[_make_turn(text="hello world")])
    tokenize_session(trace)
    # "hello world" is 11 chars → 11//4 = 2 tokens via heuristic
    assert trace.turns[0].token_count > 0


def test_tokenize_is_idempotent(monkeypatch):
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.tokenizer import tokenize_session

    trace = _make_minimal_trace(turns=[_make_turn(text="repeated")])
    tokenize_session(trace)
    first = trace.turns[0].token_count
    tokenize_session(trace)
    assert trace.turns[0].token_count == first


def test_no_anthropic_import_in_offline_mode(monkeypatch):
    sys.modules.pop("anthropic", None)
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.tokenizer import tokenize_session

    trace = _make_minimal_trace(turns=[_make_turn(text="hi")])
    tokenize_session(trace)
    assert "anthropic" not in sys.modules
