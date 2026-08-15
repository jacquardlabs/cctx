"""Shared helpers for diagnostician tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc


def _dt(offset_seconds: int = 0) -> datetime:
    base = datetime(2026, 5, 14, 10, 0, 0, tzinfo=UTC)
    return base + timedelta(seconds=offset_seconds)


def make_tool_use(tool_use_id: str, tool_name: str, tool_input: dict):
    from cctx.models import ToolUse
    return ToolUse(tool_name=tool_name, tool_use_id=tool_use_id, tool_input=tool_input)


def make_tool_result(tool_use_id: str, tool_name: str, content: str, is_error: bool = False):
    from cctx.models import ToolResult
    return ToolResult(
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        content=content,
        structured=None,
        is_error=is_error,
    )


def make_assistant_turn(turn_number: int, tool_uses=None, text: str = ""):
    from cctx.models import Turn
    return Turn(
        turn_number=turn_number,
        uuid=f"uuid-a{turn_number}",
        parent_uuid=None,
        role="assistant",
        text=text,
        thinking="",
        tool_uses=tool_uses or [],
        tool_results=[],
        usage=None,
        model="claude-sonnet-4-6",
        stop_reason="tool_use",
        timestamp=_dt(turn_number * 10),
        duration_ms=500,
    )


def make_tool_result_turn(turn_number: int, tool_results=None):
    from cctx.models import Turn
    return Turn(
        turn_number=turn_number,
        uuid=f"uuid-r{turn_number}",
        parent_uuid=f"uuid-a{turn_number - 1}",
        role="tool_result",
        text="",
        thinking="",
        tool_uses=[],
        tool_results=tool_results or [],
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=_dt(turn_number * 10 + 2),
        duration_ms=100,
    )


def make_user_turn(turn_number: int, text: str = "do the thing"):
    from cctx.models import Turn
    return Turn(
        turn_number=turn_number,
        uuid=f"uuid-u{turn_number}",
        parent_uuid=None,
        role="user",
        text=text,
        thinking="",
        tool_uses=[],
        tool_results=[],
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=_dt(turn_number * 10),
        duration_ms=None,
    )


def make_trace(turns, model: str = "claude-sonnet-4-6"):
    from cctx.models import SessionTrace
    return SessionTrace(
        session_id="test-session",
        parent_session_id=None,
        project_path="/Users/test/Projects/demo",
        cwd="/Users/test/Projects/demo",
        primary_model=model,
        claude_code_version="2.1.138",
        turns=turns,
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=["Edit", "Bash", "Read"],
        start_time=_dt(0),
        end_time=_dt(100),
        source_path=Path("/Users/test/.claude/projects/demo/test-session.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


def make_retry_occurrence(turn: int = 3, key: str = "src/app.py",
                          call: str = "Edit", error: str = "boom"):
    from cctx.models import RetryOccurrence
    return RetryOccurrence(turn=turn, key=key, call=call, error=error)


def make_scope_phrase(turn: int = 5, phrase: str = "while i'm at it",
                      snippet: str = "...while i'm at it, refactor..."):
    from cctx.models import ScopeCreepPhrase
    return ScopeCreepPhrase(turn=turn, phrase=phrase, snippet=snippet)


def make_stale_item(tool_name: str = "Grep", content_tokens: int = 22_000,
                    first_seen_turn: int = 9, last_referenced_turn: int = 9,
                    turns_stale: int = 14, token_turns: int = 308_000):
    from cctx.models import StaleItem
    return StaleItem(
        tool_name=tool_name,
        content_tokens=content_tokens,
        first_seen_turn=first_seen_turn,
        last_referenced_turn=last_referenced_turn,
        turns_stale=turns_stale,
        token_turns=token_turns,
    )
