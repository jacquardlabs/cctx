"""End-to-end pricing checks: JSONL -> parse -> diagnose -> cost.

Unit tests on get_pricing() cannot catch a break in the parser -> Usage -> pricing
plumbing, which is the only path that carries usage.speed and the session date into a
cost. These tests drive the whole chain and assert exact cost ratios.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cctx.diagnostician import run
from cctx.parsers.claude_code import parse_session
from tests.conftest import make_assistant_line, make_user_line

UTC = timezone.utc


def _diagnose(write_jsonl, *, model, speed="standard", day="2026-07-20", filename="s.jsonl"):
    """One user + one assistant turn with fixed token counts, priced end to end."""
    ts = f"{day}T02:00:00.000Z"
    lines = [
        make_user_line(uuid="u1", content="do the thing", timestamp=ts),
        make_assistant_line(
            uuid="a1",
            parent_uuid="u1",
            text="done",
            model=model,
            speed=speed,
            timestamp=ts,
            input_tokens=1000,
            output_tokens=500,
            cache_read=2000,
            cache_creation_5m=400,
        ),
    ]
    return run(parse_session(write_jsonl(lines, filename=filename)))


def test_fast_mode_turn_costs_exactly_double_the_standard_turn(write_jsonl):
    """Opus 5 fast mode is $10/$50 against $5/$25, and cache multipliers ride the fast
    base rate — so every component doubles, including cache reads and writes."""
    standard = _diagnose(write_jsonl, model="claude-opus-5", filename="std.jsonl")
    fast = _diagnose(write_jsonl, model="claude-opus-5", speed="fast", filename="fast.jsonl")

    assert standard.total_cost_usd == 0.021
    assert fast.total_cost_usd == 0.042


def test_fast_mode_ignored_for_a_model_without_it(write_jsonl):
    """Sonnet 5 has no fast mode; a `fast` marker must not inflate its cost."""
    standard = _diagnose(write_jsonl, model="claude-sonnet-5", filename="s-std.jsonl")
    fast = _diagnose(write_jsonl, model="claude-sonnet-5", speed="fast", filename="s-fast.jsonl")

    assert fast.total_cost_usd == standard.total_cost_usd


def test_session_is_priced_at_the_rate_in_effect_when_it_ran(write_jsonl):
    """Sonnet 5's introductory $2/$10 ends 2026-08-31. A session from before the change
    keeps the intro rate no matter when the autopsy runs; one from after pays $3/$15."""
    intro = _diagnose(write_jsonl, model="claude-sonnet-5", day="2026-08-31", filename="a.jsonl")
    after = _diagnose(write_jsonl, model="claude-sonnet-5", day="2026-09-01", filename="b.jsonl")

    assert intro.total_cost_usd == 0.0084
    assert after.total_cost_usd == 0.0126  # exactly 1.5x — $3/$15 against $2/$10


def test_unscheduled_model_cost_is_independent_of_session_date(write_jsonl):
    a = _diagnose(write_jsonl, model="claude-opus-5", day="2026-01-05", filename="c.jsonl")
    b = _diagnose(write_jsonl, model="claude-opus-5", day="2026-12-31", filename="d.jsonl")

    assert a.total_cost_usd == b.total_cost_usd == 0.021


def test_missing_timestamp_does_not_price_at_the_epoch():
    """Turn.timestamp is non-optional and the parser substitutes the Unix epoch when a
    line carries none. Priced literally, that would resolve every schedule to its earliest
    entry, so the sentinel has to read as "unknown date" instead."""
    from cctx.diagnostician import _billing_date

    assert _billing_date(datetime.fromtimestamp(0, tz=UTC)) is None
    assert _billing_date(None) is None
    assert _billing_date(datetime(2026, 9, 1, 12, 0, tzinfo=UTC)).isoformat() == "2026-09-01"
