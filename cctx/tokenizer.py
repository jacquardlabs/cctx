"""cctx tokenizer.

The ONLY module in cctx allowed to import `anthropic`. Wraps
anthropic.messages.count_tokens() and walks a parsed SessionTrace,
populating token_count fields on Turns, ToolUses, and ToolResults.

Honors CCTX_OFFLINE=1 to skip live API calls and use a len(text)//4
heuristic instead — useful for CI, air-gapped environments, or quick
relative-proportion estimates.
"""

from __future__ import annotations

import json
import os

from cctx.models import SessionTrace, Turn

# Tokenization is model-specific: Claude Opus 4.7 and later use a newer tokenizer that
# produces ~30% more tokens for the same text than Sonnet 4.6 and earlier. Each trace is
# counted against the model that actually ran it (subagents included), so token-turns
# attribution and its dollar cost stay consistent with what was billed. The default
# covers sessions that record no model, and non-Anthropic models from OTEL traces — for
# those, a Claude tokenizer is an approximation, but a much closer one than the heuristic.
DEFAULT_COUNT_MODEL = "claude-sonnet-5"


def tokenize_session(trace: SessionTrace) -> SessionTrace:
    """Walk a SessionTrace and populate token_count fields in place. Returns the same trace."""
    counter_for = _build_counter_factory()
    _tokenize_trace_recursively(trace, counter_for)
    return trace


def _build_counter_factory():
    """Return a callable model -> (str -> int). Heuristic offline; live API otherwise."""
    if os.environ.get("CCTX_OFFLINE") == "1":
        return lambda model: _heuristic_token_count
    return _make_live_counter_factory()


def _heuristic_token_count(text: str) -> int:
    return len(text) // 4


def count_model_for(model: str | None) -> str:
    """API-callable Anthropic model id for count_tokens.

    Strips Claude Code's `[1m]`-style context-window suffix, which appears in session
    logs but is not a model id the API accepts. Non-Anthropic models (OTEL traces carry
    ids like `gpt-4o`) fall back to the default — count_tokens would reject them.
    """
    if not model or not model.startswith("claude-"):
        return DEFAULT_COUNT_MODEL
    return model.split("[", 1)[0] or DEFAULT_COUNT_MODEL


def _make_live_counter_factory():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return lambda model: _heuristic_token_count
    import anthropic  # lazy: offline mode never loads the SDK

    client = anthropic.Anthropic(api_key=api_key)
    cache: dict[tuple[str, str], int] = {}
    uncountable: set[str] = set()

    def counter_for(model: str | None):
        count_model = count_model_for(model)

        def count(text: str) -> int:
            key = (count_model, text)
            if key in cache:
                return cache[key]
            if count_model in uncountable:
                return _heuristic_token_count(text)
            try:
                result = client.messages.count_tokens(
                    model=count_model,
                    messages=[{"role": "user", "content": text or " "}],
                )
            except Exception:
                # Retired model id, or the API is unreachable — degrade this model to the
                # heuristic rather than aborting the autopsy.
                uncountable.add(count_model)
                return _heuristic_token_count(text)
            n = result.input_tokens
            cache[key] = n
            return n

        return count

    return counter_for


def _tokenize_trace_recursively(trace: SessionTrace, counter_for) -> None:
    counter = counter_for(trace.primary_model)
    for turn in trace.turns:
        _tokenize_turn(turn, counter)
    for child in trace.subagents:
        _tokenize_trace_recursively(child, counter_for)


def _tokenize_turn(turn: Turn, counter) -> None:
    narrative = ((turn.text or "") + ("\n" + turn.thinking if turn.thinking else "")).strip()
    if narrative:
        turn.token_count = counter(narrative)

    for use in turn.tool_uses:
        use.token_count = counter(json.dumps(use.tool_input, sort_keys=True))

    for result in turn.tool_results:
        result.token_count = counter(result.content or "")
