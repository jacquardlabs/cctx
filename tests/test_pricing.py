"""Tests for cctx/pricing.py — price_per_tok() and the unknown-family fallback (#145)."""
from __future__ import annotations

from cctx.pricing import _DEFAULT_PRICE_PER_MTOK, price_per_tok


def test_known_families_priced_by_prefix():
    assert price_per_tok("claude-opus-4-8") == 15.0 / 1_000_000
    assert price_per_tok("claude-sonnet-4-6") == 3.0 / 1_000_000
    assert price_per_tok("claude-haiku-4-5") == 0.8 / 1_000_000


def test_unknown_family_falls_back_to_nonzero():
    """A future/unknown family (e.g. claude-opus-5) must still get a non-zero price.

    Guards the silent-$0 failure mode: a new model family the table doesn't know
    about should fall through to the default, not produce zero-cost diagnoses.
    """
    price = price_per_tok("claude-opus-5-future")
    assert price > 0
    assert price == _DEFAULT_PRICE_PER_MTOK / 1_000_000


def test_none_model_falls_back_to_nonzero():
    assert price_per_tok(None) == _DEFAULT_PRICE_PER_MTOK / 1_000_000
    assert price_per_tok(None) > 0


def test_fallback_within_known_family_range():
    """Fallback sits between the cheapest and priciest known family — a sane mid-range."""
    cheapest = 0.8 / 1_000_000
    priciest = 15.0 / 1_000_000
    fallback = _DEFAULT_PRICE_PER_MTOK / 1_000_000
    assert cheapest <= fallback <= priciest
