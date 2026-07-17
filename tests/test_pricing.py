"""Tests for cctx/pricing.py — 2D get_pricing(), longest-prefix match, freshness (#120, #145)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from cctx.pricing import PRICING_LAST_VERIFIED, ModelPricing, get_pricing, price_per_tok

M = 1_000_000


# --- prices verified 2026-07-17 (see pricing.py header) ---------------------


@pytest.mark.parametrize("model, inp, out", [
    # Anthropic — current
    ("claude-fable-5",          10.0, 50.0),
    ("claude-mythos-5",         10.0, 50.0),
    ("claude-mythos-preview",   10.0, 50.0),
    ("claude-opus-4-8",          5.0, 25.0),
    ("claude-opus-4-6",          5.0, 25.0),
    ("claude-sonnet-5",          3.0, 15.0),
    ("claude-sonnet-4-6",        3.0, 15.0),
    ("claude-sonnet-4",          3.0, 15.0),
    ("claude-haiku-4-5",         1.0,  5.0),
    # Anthropic — deprecated but still present in historical logs
    ("claude-opus-4-1",         15.0, 75.0),
    ("claude-haiku-3-5",         0.8,  4.0),
    # OpenAI (from OTEL traces)
    ("gpt-4o",                   2.50, 10.0),
    ("gpt-4o-mini",              0.15,  0.60),
    ("gpt-4.1",                  2.0,   8.0),
    ("gpt-5",                    1.25, 10.0),
    ("gpt-5-mini",               0.25,  2.0),
    ("o3",                       2.0,   8.0),
    ("o4-mini",                  1.10,  4.40),
])
def test_get_pricing_known_models(model, inp, out):
    p = get_pricing(model)
    assert p.input_per_mtok == inp
    assert p.output_per_mtok == out


def test_longest_prefix_wins_opus_version_disambiguation():
    """opus-4-1 ($15, deprecated) and opus-4-8 ($5, current) share the 'claude-opus-4' stem."""
    assert get_pricing("claude-opus-4-8").input_per_mtok == 5.0
    assert get_pricing("claude-opus-4-1").input_per_mtok == 15.0


def test_longest_prefix_wins_with_dated_and_mini_suffixes():
    assert get_pricing("claude-opus-4-8-20251234").input_per_mtok == 5.0  # dated suffix
    assert get_pricing("gpt-4o-mini").input_per_mtok == 0.15             # mini, not gpt-4o
    assert get_pricing("gpt-5-mini").input_per_mtok == 0.25


def test_anthropic_cache_multipliers_present_openai_zeroed():
    claude = get_pricing("claude-sonnet-4-6")
    assert claude.cache_write_5m_mult == 1.25
    assert claude.cache_write_1h_mult == 2.0
    assert claude.cache_read_mult == 0.10
    gpt = get_pricing("gpt-4o")
    assert gpt.cache_write_5m_mult == 0.0
    assert gpt.cache_write_1h_mult == 0.0
    assert gpt.cache_read_mult == 0.0


def test_unknown_model_and_none_fall_back_to_nonzero_default():
    for model in (None, "some-future-model-9", "llama-3-70b"):
        p = get_pricing(model)
        assert p.input_per_mtok > 0
        assert p.output_per_mtok > 0
        assert p == get_pricing(None)  # same default object


def test_default_within_known_anthropic_range():
    d = get_pricing(None)
    assert 0.8 <= d.input_per_mtok <= 15.0
    assert 4.0 <= d.output_per_mtok <= 75.0


def test_price_per_tok_shim_returns_input_per_token():
    assert price_per_tok("claude-sonnet-4-6") == 3.0 / M
    assert price_per_tok("gpt-4o") == 2.50 / M
    assert price_per_tok(None) == get_pricing(None).input_per_mtok / M
    assert price_per_tok("unknown") > 0


def test_model_pricing_is_frozen():
    import dataclasses

    p = get_pricing("gpt-4o")
    assert isinstance(p, ModelPricing)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.input_per_mtok = 999  # type: ignore[misc]


def test_is_known_model_flags_unrecognized():
    """is_known_model() is the 'new model introduced' signal — False == priced at default."""
    from cctx.pricing import is_known_model

    assert is_known_model("claude-opus-4-8") is True
    # claude-sonnet-5 prices the same as _DEFAULT, so only is_known_model
    # distinguishes "listed" from "fell through to the default".
    assert is_known_model("claude-sonnet-5") is True
    assert is_known_model("claude-fable-5") is True
    assert is_known_model("claude-mythos-5") is True
    assert is_known_model("gpt-4o") is True
    assert is_known_model("gpt-4o-2026-01-01") is True   # dated suffix still matches
    assert is_known_model("gpt-6-preview") is False      # future model -> default
    assert is_known_model("llama-3-70b") is False
    assert is_known_model(None) is False


# --- freshness tripwire: CI goes red when the table is stale ----------------


def test_pricing_table_freshness():
    """Forces periodic re-verification. When this fails, check provider pricing
    pages, update the table, and bump PRICING_LAST_VERIFIED."""
    age = date.today() - PRICING_LAST_VERIFIED
    assert age < timedelta(days=180), (
        f"Pricing last verified {PRICING_LAST_VERIFIED} ({age.days} days ago). "
        "Re-verify input/output rates against the Anthropic and OpenAI pricing "
        "pages, add any new model families, and bump PRICING_LAST_VERIFIED."
    )
