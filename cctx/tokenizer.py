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


def tokenize_session(trace: SessionTrace) -> SessionTrace:
    """Walk a SessionTrace and populate token_count fields in place. Returns the same trace."""
    counter = _build_counter()
    _tokenize_trace_recursively(trace, counter)
    return trace


def _build_counter():
    """Return a callable str -> int. Heuristic in offline mode; live API otherwise."""
    if os.environ.get("CCTX_OFFLINE") == "1":
        return _heuristic_token_count
    return _make_live_counter()


def _heuristic_token_count(text: str) -> int:
    return len(text) // 4


def _make_live_counter():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _heuristic_token_count
    import anthropic  # lazy: offline mode never loads the SDK

    client = anthropic.Anthropic(api_key=api_key)
    cache: dict[str, int] = {}

    def count(text: str) -> int:
        if text in cache:
            return cache[text]
        result = client.messages.count_tokens(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": text or " "}],
        )
        n = result.input_tokens
        cache[text] = n
        return n

    return count


def _tokenize_trace_recursively(trace: SessionTrace, counter) -> None:
    for turn in trace.turns:
        _tokenize_turn(turn, counter)
    for child in trace.subagents:
        _tokenize_trace_recursively(child, counter)


def _tokenize_turn(turn: Turn, counter) -> None:
    narrative = ((turn.text or "") + ("\n" + turn.thinking if turn.thinking else "")).strip()
    if narrative:
        turn.token_count = counter(narrative)

    for use in turn.tool_uses:
        use.token_count = counter(json.dumps(use.tool_input, sort_keys=True))

    for result in turn.tool_results:
        result.token_count = counter(result.content or "")
