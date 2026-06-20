"""Shared token pricing — single source of truth for all cost calculations.

UPDATE THIS when a new Claude model family ships (e.g. claude-opus-5,
claude-haiku-5). Prefix matching means an unrecognized family silently falls
through to _DEFAULT_PRICE_PER_MTOK ($3/Mtok input) — costs stay plausible but
are not family-accurate until the prefix is added here. Prices are input
$/Mtok; see https://www.anthropic.com/pricing for current rates.
"""
from __future__ import annotations

_INPUT_PRICE_PER_MTOK: dict[str, float] = {
    "claude-opus-4":   15.0,
    "claude-sonnet-4":  3.0,
    "claude-haiku-4":   0.8,
}
# Fallback for any model family not listed above. Kept at Sonnet's rate so an
# unknown model yields a mid-range, non-zero estimate rather than $0.
_DEFAULT_PRICE_PER_MTOK = 3.0


def price_per_tok(model: str | None) -> float:
    """Return per-token input price in USD for the given model string."""
    if model is not None:
        for prefix, mtok in _INPUT_PRICE_PER_MTOK.items():
            if model.startswith(prefix):
                return mtok / 1_000_000
    return _DEFAULT_PRICE_PER_MTOK / 1_000_000
