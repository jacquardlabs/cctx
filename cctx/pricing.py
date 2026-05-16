"""Shared token pricing — single source of truth for all cost calculations."""
from __future__ import annotations

_INPUT_PRICE_PER_MTOK: dict[str, float] = {
    "claude-opus-4":   15.0,
    "claude-sonnet-4":  3.0,
    "claude-haiku-4":   0.8,
}
_DEFAULT_PRICE_PER_MTOK = 3.0


def price_per_tok(model: str | None) -> float:
    """Return per-token input price in USD for the given model string."""
    if model is not None:
        for prefix, mtok in _INPUT_PRICE_PER_MTOK.items():
            if model.startswith(prefix):
                return mtok / 1_000_000
    return _DEFAULT_PRICE_PER_MTOK / 1_000_000
