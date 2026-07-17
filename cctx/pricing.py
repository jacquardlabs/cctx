"""Shared token pricing — single source of truth for all cost calculations.

Covers Anthropic (Claude Code sessions) and OpenAI (OTEL traces). Prices are
per-million-token USD; cache multipliers are relative to base input price and
apply to Anthropic prompt caching only (OpenAI Usage cache fields are zeroed by
the OTEL parser, and these models carry 0.0 multipliers as belt-and-suspenders).

PRICES VERIFIED 2026-07-17 against:
  - Anthropic: https://platform.claude.com/docs/en/about-claude/models/overview
  - OpenAI:    current published API rates (gpt-4o/4.1/5, o3, o4-mini)

WHEN TO UPDATE: the test_pricing_table_freshness tripwire fails CI once
PRICING_LAST_VERIFIED is >180 days old. On failure (or when a new model family
ships), re-check both pricing pages, add/adjust entries, and bump the date.
Model families not listed fall through to _DEFAULT (claude-sonnet rates) — a
plausible non-zero estimate, but not family-accurate. The "prices as of <date>"
line in cctx output is the honest signal that an estimate may be stale.
"""
from __future__ import annotations

import dataclasses
from datetime import date

PRICING_LAST_VERIFIED = date(2026, 7, 17)


@dataclasses.dataclass(frozen=True)
class ModelPricing:
    """Per-MTok input/output USD prices + Anthropic prompt-cache multipliers."""
    input_per_mtok:      float
    output_per_mtok:     float
    cache_write_5m_mult: float = 1.25  # ×base input
    cache_write_1h_mult: float = 2.0   # ×base input
    cache_read_mult:     float = 0.10  # ×base input


_AC = {"cache_write_5m_mult": 1.25, "cache_write_1h_mult": 2.0, "cache_read_mult": 0.10}
_NC = {"cache_write_5m_mult": 0.0, "cache_write_1h_mult": 0.0, "cache_read_mult": 0.0}

# Keyed by model-id prefix. get_pricing() uses the LONGEST matching prefix, so
# version-specific entries (claude-opus-4-8) win over the family stem
# (claude-opus-4), and gpt-4o-mini wins over gpt-4o.
_PRICING: dict[str, ModelPricing] = {
    # --- Anthropic: current ---
    "claude-fable-5":   ModelPricing(10.0, 50.0, **_AC),
    "claude-mythos":    ModelPricing(10.0, 50.0, **_AC),  # mythos-5 + mythos-preview share Fable 5 rates
    "claude-opus-4-8":  ModelPricing(5.0, 25.0, **_AC),
    "claude-opus-4-7":  ModelPricing(5.0, 25.0, **_AC),
    "claude-opus-4-6":  ModelPricing(5.0, 25.0, **_AC),
    "claude-opus-4-5":  ModelPricing(5.0, 25.0, **_AC),
    "claude-sonnet-5":  ModelPricing(3.0, 15.0, **_AC),  # sticker rate; intro $2/$10 through 2026-08-31
    "claude-sonnet-4":  ModelPricing(3.0, 15.0, **_AC),  # 4, 4.5, 4.6 share rates
    "claude-haiku-4-5": ModelPricing(1.0, 5.0, **_AC),
    # --- Anthropic: deprecated/retired, still present in historical logs ---
    "claude-opus-4-1":  ModelPricing(15.0, 75.0, **_AC),
    "claude-opus-4":    ModelPricing(15.0, 75.0, **_AC),  # original Opus 4.0 (dated ids)
    "claude-haiku-3-5": ModelPricing(0.8, 4.0, **_AC),
    # --- OpenAI (from OTEL traces; no prompt-cache billing) ---
    "gpt-4o-mini":      ModelPricing(0.15, 0.60, **_NC),
    "gpt-4o":           ModelPricing(2.50, 10.0, **_NC),
    "gpt-4.1":          ModelPricing(2.0, 8.0, **_NC),
    "gpt-5-mini":       ModelPricing(0.25, 2.0, **_NC),
    "gpt-5":            ModelPricing(1.25, 10.0, **_NC),
    "o4-mini":          ModelPricing(1.10, 4.40, **_NC),
    "o3":               ModelPricing(2.0, 8.0, **_NC),
}

# Unknown/unlisted family fallback — claude-sonnet rates (mid-range, non-zero).
_DEFAULT = ModelPricing(3.0, 15.0, **_AC)


def get_pricing(model: str | None) -> ModelPricing:
    """Return ModelPricing for a model id via longest-prefix match, else _DEFAULT."""
    if model is None:
        return _DEFAULT
    best_prefix = ""
    best = _DEFAULT
    for prefix, mp in _PRICING.items():
        if model.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix, best = prefix, mp
    return best


def is_known_model(model: str | None) -> bool:
    """True if `model` matches a priced family. False means it falls to _DEFAULT —
    the signal that a new/unrecognized model has appeared and the table needs an entry."""
    if model is None:
        return False
    return any(model.startswith(prefix) for prefix in _PRICING)


def price_per_tok(model: str | None) -> float:
    """Per-token INPUT price in USD. Back-compat shim — prefer get_pricing()."""
    return get_pricing(model).input_per_mtok / 1_000_000
