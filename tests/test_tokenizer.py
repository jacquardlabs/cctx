"""Tests for cctx.tokenizer using the offline heuristic mode (no live API)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from cctx.models import SessionTrace, ToolResult, ToolUse, Turn


def _make_minimal_trace(
    *,
    turns: list[Turn] | None = None,
    subagents: list[SessionTrace] | None = None,
    primary_model: str | None = None,
) -> SessionTrace:
    return SessionTrace(
        session_id="test",
        parent_session_id=None,
        project_path="/p",
        cwd="/p",
        primary_model=primary_model,
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


def test_count_model_strips_claude_code_context_suffix():
    """Claude Code logs `claude-opus-5[1m]`; count_tokens only accepts the bare id."""
    from cctx.tokenizer import DEFAULT_COUNT_MODEL, count_model_for

    assert count_model_for("claude-opus-5[1m]") == "claude-opus-5"
    assert count_model_for("claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"
    assert count_model_for(None) == DEFAULT_COUNT_MODEL
    assert count_model_for("") == DEFAULT_COUNT_MODEL


def test_count_model_falls_back_for_non_anthropic_models():
    """OTEL traces carry ids like `gpt-4o`; count_tokens would reject them, so they get a
    Claude tokenizer rather than degrading to the len//4 heuristic."""
    from cctx.tokenizer import DEFAULT_COUNT_MODEL, count_model_for

    assert count_model_for("gpt-4o") == DEFAULT_COUNT_MODEL
    assert count_model_for("gpt-5-mini") == DEFAULT_COUNT_MODEL
    assert count_model_for("o3") == DEFAULT_COUNT_MODEL


def test_otel_trace_is_counted_with_a_claude_tokenizer(monkeypatch):
    """Regression: per-trace model selection must not send `gpt-4o` to count_tokens."""
    recorder: list[str] = []
    _install_fake_anthropic(monkeypatch, recorder)
    from cctx.tokenizer import DEFAULT_COUNT_MODEL, tokenize_session

    trace = _make_minimal_trace(turns=[_make_turn(text="otel text")], primary_model="gpt-4o")
    tokenize_session(trace)

    assert recorder == [DEFAULT_COUNT_MODEL]
    assert trace.turns[0].token_count == 42


def _install_fake_anthropic(monkeypatch, recorder: list[str], fail_for: tuple[str, ...] = ()):
    """Inject a stub `anthropic` module so the live-counter path is exercised offline."""
    import types

    class _Messages:
        def count_tokens(self, *, model, messages):
            recorder.append(model)
            if model in fail_for:
                raise RuntimeError("model not found")
            return types.SimpleNamespace(input_tokens=42)

    class _Anthropic:
        def __init__(self, api_key=None):
            self.messages = _Messages()

    module = types.ModuleType("anthropic")
    module.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", module)
    monkeypatch.delenv("CCTX_OFFLINE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")


def test_live_counter_counts_each_trace_against_its_own_model(monkeypatch):
    """Opus 4.7+ tokenizes ~30% higher than Sonnet 4.6 and earlier, so a session must be
    counted against the model that ran it — and a subagent against its own."""
    recorder: list[str] = []
    _install_fake_anthropic(monkeypatch, recorder)
    from cctx.tokenizer import tokenize_session

    child = _make_minimal_trace(
        turns=[_make_turn(text="subagent text")], primary_model="claude-haiku-4-5"
    )
    parent = _make_minimal_trace(
        turns=[_make_turn(text="parent text")],
        subagents=[child],
        primary_model="claude-opus-5[1m]",
    )
    tokenize_session(parent)

    assert recorder == ["claude-opus-5", "claude-haiku-4-5"]
    assert parent.turns[0].token_count == 42
    assert parent.subagents[0].turns[0].token_count == 42


def test_live_counter_falls_back_to_heuristic_for_uncountable_model(monkeypatch):
    """A retired model id (or an unreachable API) degrades to the heuristic, once."""
    recorder: list[str] = []
    _install_fake_anthropic(monkeypatch, recorder, fail_for=("claude-3-5-haiku-20241022",))
    from cctx.tokenizer import tokenize_session

    trace = _make_minimal_trace(
        turns=[_make_turn(text="a" * 40), _make_turn(text="b" * 80)],
        primary_model="claude-3-5-haiku-20241022",
    )
    tokenize_session(trace)

    assert [t.token_count for t in trace.turns] == [10, 20]  # len//4 heuristic
    assert len(recorder) == 1  # the failing model is not retried per turn


def test_no_anthropic_import_in_offline_mode(monkeypatch):
    sys.modules.pop("anthropic", None)
    monkeypatch.setenv("CCTX_OFFLINE", "1")
    from cctx.tokenizer import tokenize_session

    trace = _make_minimal_trace(turns=[_make_turn(text="hi")])
    tokenize_session(trace)
    assert "anthropic" not in sys.modules
