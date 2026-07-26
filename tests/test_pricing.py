"""Tests for cctx/pricing.py — 2D get_pricing(), longest-prefix match, freshness (#120, #145)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from cctx.pricing import PRICING_LAST_VERIFIED, ModelPricing, get_pricing, price_per_tok

M = 1_000_000


# --- prices verified 2026-07-26 (see pricing.py header) ---------------------


@pytest.mark.parametrize("model, inp, out", [
    # Anthropic — current
    ("claude-fable-5",          10.0, 50.0),
    ("claude-mythos-5",         10.0, 50.0),
    ("claude-mythos-preview",   10.0, 50.0),
    ("claude-opus-5",            5.0, 25.0),
    ("claude-opus-4-8",          5.0, 25.0),
    ("claude-opus-4-6",          5.0, 25.0),
    # claude-sonnet-5 has a scheduled rate change — see the dated tests below, which pin
    # `on=` rather than depending on when the suite runs.
    ("claude-sonnet-4-6",        3.0, 15.0),
    ("claude-sonnet-4",          3.0, 15.0),
    ("claude-haiku-4-5",         1.0,  5.0),
    # Anthropic — deprecated but still present in historical logs
    ("claude-opus-4-1",         15.0, 75.0),
    ("claude-3-5-haiku-20241022", 0.8, 4.0),
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


def test_claude_code_1m_context_suffix_prices_as_base_model():
    """Claude Code logs the 1M-context variant as `<model>[1m]`; no long-context premium."""
    assert get_pricing("claude-opus-5[1m]").input_per_mtok == 5.0
    assert get_pricing("claude-opus-4-8[1m]").input_per_mtok == 5.0
    # Sonnet 5's rate is date-scheduled, so pin the date rather than trusting the clock.
    assert get_pricing("claude-sonnet-5[1m]", on=date(2026, 8, 31)).input_per_mtok == 2.0


def test_opus_5_is_not_captured_by_the_opus_4_stem():
    """Opus 5 ($5/$25) must not fall through to _DEFAULT or the Opus 4.0 stem ($15/$75)."""
    p = get_pricing("claude-opus-5")
    assert (p.input_per_mtok, p.output_per_mtok) == (5.0, 25.0)
    assert p != get_pricing(None)


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
    assert is_known_model("claude-opus-5") is True
    assert is_known_model("claude-opus-5[1m]") is True
    assert is_known_model("claude-sonnet-5") is True
    assert is_known_model("claude-fable-5") is True
    assert is_known_model("claude-mythos-5") is True
    # Claude Code's placeholder model for locally-generated assistant messages.
    # The parser normalizes it to None, so it never reaches pricing as a model id.
    assert is_known_model("<synthetic>") is False
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


# --- scheduled rate changes: a session is priced at the rate it ran under -----


def test_sonnet_5_intro_rate_applies_before_the_scheduled_change():
    """Introductory $2/$10 runs through 2026-08-31; standard $3/$15 starts 2026-09-01."""
    intro = get_pricing("claude-sonnet-5", on=date(2026, 8, 31))
    assert (intro.input_per_mtok, intro.output_per_mtok) == (2.0, 10.0)
    standard = get_pricing("claude-sonnet-5", on=date(2026, 9, 1))
    assert (standard.input_per_mtok, standard.output_per_mtok) == (3.0, 15.0)
    later = get_pricing("claude-sonnet-5", on=date(2027, 3, 1))
    assert (later.input_per_mtok, later.output_per_mtok) == (3.0, 15.0)


def test_scheduled_change_applies_to_model_id_variants():
    """The schedule is keyed by matched prefix, so `[1m]` and dated ids inherit it."""
    assert get_pricing("claude-sonnet-5[1m]", on=date(2026, 8, 31)).input_per_mtok == 2.0
    assert get_pricing("claude-sonnet-5[1m]", on=date(2026, 9, 1)).input_per_mtok == 3.0


def test_unscheduled_model_ignores_the_session_date():
    for on in (date(2024, 1, 1), date(2026, 9, 1), date(2030, 1, 1)):
        assert get_pricing("claude-opus-5", on=on).input_per_mtok == 5.0


def test_schedule_entries_reference_priced_prefixes_in_date_order():
    """_SCHEDULE holds only future transitions for prefixes _PRICING already knows, and
    _rate_on()'s last-match-wins resolution requires them oldest-first."""
    from cctx.pricing import _PRICING, _SCHEDULE

    assert set(_SCHEDULE) <= set(_PRICING)
    for prefix, transitions in _SCHEDULE.items():
        dates = [d for d, _ in transitions]
        assert dates == sorted(dates), f"{prefix} transitions are out of order"


# --- fast mode: premium rates on the models that support it -------------------


def test_fast_mode_doubles_opus_rates_and_scales_cache_multipliers():
    """Fast mode is $10/$50 on Opus 5 / Opus 4.8; cache multipliers stack on the fast base."""
    for model in ("claude-opus-5", "claude-opus-4-8", "claude-opus-5[1m]"):
        p = get_pricing(model, speed="fast")
        assert (p.input_per_mtok, p.output_per_mtok) == (10.0, 50.0), model
        assert p.cache_write_5m_mult == 1.25
        assert p.cache_read_mult == 0.10


def test_standard_and_absent_speed_use_standard_rates():
    for speed in (None, "standard"):
        p = get_pricing("claude-opus-5", speed=speed)
        assert (p.input_per_mtok, p.output_per_mtok) == (5.0, 25.0)


def test_fast_mode_roster_is_pinned_to_the_models_that_support_it():
    """Fast mode is Opus 5 and Opus 4.8 only. Pinning the roster is what catches a wrong
    entry — asserting a non-fast model keeps its rate passes either way."""
    from cctx.pricing import _FAST_MODE, _PRICING

    assert set(_FAST_MODE) == {"claude-opus-5", "claude-opus-4-8"}
    assert set(_FAST_MODE) <= set(_PRICING)


def test_fast_mode_ignored_on_models_without_it():
    """Opus 4.6 runs at standard speed and bills standard; Opus 4.7 rejects the request
    outright; Sonnet and Fable have no fast mode. None of them get the premium rate."""
    assert get_pricing("claude-opus-4-7", speed="fast").input_per_mtok == 5.0
    assert get_pricing("claude-opus-4-6", speed="fast").input_per_mtok == 5.0
    assert get_pricing("claude-fable-5", speed="fast").input_per_mtok == 10.0  # its own rate
    assert get_pricing("claude-sonnet-5", speed="fast", on=date(2026, 8, 31)).input_per_mtok == 2.0
    assert get_pricing("some-future-model-9", speed="fast") == get_pricing(None)


def test_price_per_tok_shim_forwards_speed_and_date():
    assert price_per_tok("claude-opus-5", speed="fast") == 10.0 / M
    assert price_per_tok("claude-sonnet-5", on=date(2026, 9, 1)) == 3.0 / M
