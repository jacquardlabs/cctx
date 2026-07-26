"""Shared token pricing — single source of truth for all cost calculations.

Covers Anthropic (Claude Code sessions) and OpenAI (OTEL traces). Prices are
per-million-token USD; cache multipliers are relative to base input price and
apply to Anthropic prompt caching only (OpenAI Usage cache fields are zeroed by
the OTEL parser, and these models carry 0.0 multipliers as belt-and-suspenders).

PRICES VERIFIED 2026-07-26 against:
  - Anthropic: https://platform.claude.com/docs/en/about-claude/pricing
  - OpenAI:    current published API rates (gpt-4o/4.1/5, o3, o4-mini)

Two rates vary independently of the model id, so get_pricing() takes both as
keyword arguments:
  - `on`   — the session's date. Announced rate changes live in _SCHEDULE, so a
             session is priced at the rate that was in effect when it ran.
  - `speed`— the request's usage.speed. "fast" bills at fast-mode rates (_FAST_MODE).

WHEN TO UPDATE: the test_pricing_table_freshness tripwire fails CI once
PRICING_LAST_VERIFIED is >180 days old. On failure (or when a new model family
ships), re-check both pricing pages, add/adjust entries, and bump the date.
Model families not listed fall through to _DEFAULT (claude-sonnet-4.x rates) — a
plausible non-zero estimate, but not family-accurate. The "prices as of <date>"
line in cctx output is the honest signal that an estimate may be stale.
"""
from __future__ import annotations

import dataclasses
from datetime import date

PRICING_LAST_VERIFIED = date(2026, 7, 26)


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
    "claude-mythos":    ModelPricing(10.0, 50.0, **_AC),  # mythos-5/preview → Fable 5 rates
    "claude-opus-5":    ModelPricing(5.0, 25.0, **_AC),
    "claude-opus-4-8":  ModelPricing(5.0, 25.0, **_AC),
    "claude-opus-4-7":  ModelPricing(5.0, 25.0, **_AC),
    "claude-opus-4-6":  ModelPricing(5.0, 25.0, **_AC),
    "claude-opus-4-5":  ModelPricing(5.0, 25.0, **_AC),
    "claude-sonnet-5":  ModelPricing(2.0, 10.0, **_AC),  # intro rate; see _SCHEDULE
    "claude-sonnet-4":  ModelPricing(3.0, 15.0, **_AC),  # 4, 4.5, 4.6 share rates
    "claude-haiku-4-5": ModelPricing(1.0, 5.0, **_AC),
    # --- Anthropic: deprecated/retired, still present in historical logs ---
    "claude-opus-4-1":  ModelPricing(15.0, 75.0, **_AC),
    "claude-opus-4":    ModelPricing(15.0, 75.0, **_AC),  # original Opus 4.0 (dated ids)
    "claude-3-5-haiku": ModelPricing(0.8, 4.0, **_AC),  # pre-4.6 ids put family after version
    # --- OpenAI (from OTEL traces; no prompt-cache billing) ---
    "gpt-4o-mini":      ModelPricing(0.15, 0.60, **_NC),
    "gpt-4o":           ModelPricing(2.50, 10.0, **_NC),
    "gpt-4.1":          ModelPricing(2.0, 8.0, **_NC),
    "gpt-5-mini":       ModelPricing(0.25, 2.0, **_NC),
    "gpt-5":            ModelPricing(1.25, 10.0, **_NC),
    "o4-mini":          ModelPricing(1.10, 4.40, **_NC),
    "o3":               ModelPricing(2.0, 8.0, **_NC),
}

# Announced FUTURE rate changes, keyed by the same prefixes as _PRICING and ordered
# oldest-first. The _PRICING entry is the rate in effect until the first date here, so a
# rate is never written twice. Matching happens on the prefix, so id variants
# (claude-sonnet-5[1m]) inherit the schedule.
_SCHEDULE: dict[str, tuple[tuple[date, ModelPricing], ...]] = {
    # Sonnet 5 introductory pricing runs through 2026-08-31.
    "claude-sonnet-5": ((date(2026, 9, 1), ModelPricing(3.0, 15.0, **_AC)),),
}

# Fast mode (research preview) — Claude Opus 5 and Opus 4.8 only, first-party API only.
# Cache multipliers stack on top of the fast base rate. Every other model ignores
# speed="fast": Opus 4.6 runs at standard speed and bills standard, Opus 4.7 rejects the
# request outright. Selected on usage.speed == "fast" exactly; Claude Code writes
# "standard" on every session observed locally, so this path is modeled from the
# documented API field, not from an observed fast-mode session.
_FAST_MODE: dict[str, ModelPricing] = {
    "claude-opus-5":   ModelPricing(10.0, 50.0, **_AC),
    "claude-opus-4-8": ModelPricing(10.0, 50.0, **_AC),
}

# Unknown/unlisted family fallback — claude-sonnet-4.x rates (mid-range, non-zero).
_DEFAULT = ModelPricing(3.0, 15.0, **_AC)


def get_pricing(
    model: str | None,
    *,
    speed: str | None = None,
    on: date | None = None,
) -> ModelPricing:
    """Return ModelPricing for a model id via longest-prefix match, else _DEFAULT.

    `on` is the date the session ran, which selects among announced rate changes; it
    defaults to today, so callers without a session date get the current rate. `speed` is
    the request's usage.speed — "fast" bills at fast-mode rates where the model has them.
    """
    prefix = _match_prefix(model)
    if prefix is None:
        return _DEFAULT
    if speed == "fast" and prefix in _FAST_MODE:
        return _FAST_MODE[prefix]
    return _rate_on(prefix, on or date.today())


def _match_prefix(model: str | None) -> str | None:
    """Longest _PRICING prefix matching `model`, or None if no family matches."""
    if model is None:
        return None
    best: str | None = None
    for prefix in _PRICING:
        if model.startswith(prefix) and (best is None or len(prefix) > len(best)):
            best = prefix
    return best


def _rate_on(prefix: str, on: date) -> ModelPricing:
    """Rate in effect for `prefix` on `on` — _PRICING unless a transition has passed."""
    rate = _PRICING[prefix]
    for effective_from, scheduled in _SCHEDULE.get(prefix, ()):
        if on >= effective_from:
            rate = scheduled
    return rate


def is_known_model(model: str | None) -> bool:
    """True if `model` matches a priced family. False means it falls to _DEFAULT —
    the signal that a new/unrecognized model has appeared and the table needs an entry."""
    if model is None:
        return False
    return any(model.startswith(prefix) for prefix in _PRICING)


def price_per_tok(
    model: str | None,
    *,
    speed: str | None = None,
    on: date | None = None,
) -> float:
    """Per-token INPUT price in USD. Back-compat shim — prefer get_pricing()."""
    return get_pricing(model, speed=speed, on=on).input_per_mtok / 1_000_000
