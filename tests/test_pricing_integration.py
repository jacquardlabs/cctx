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


def test_waste_cost_uses_the_same_speed_as_total_cost(write_jsonl):
    """A stale-context finding prices token-turns, which span many requests and so read
    the trace's modal speed. Without that, one Diagnosis would report a doubled total cost
    alongside half-rate waste costs."""
    import dataclasses

    from cctx.models import FindingKind, Usage
    from tests.diagnostician.test_stale_context import _stale_trace

    def stale_cost(speed):
        # Real assistant turns always carry usage; the shared builder leaves it None.
        turns = [
            dataclasses.replace(t, usage=Usage(100, 50, 0, 0, 0, "standard", speed))
            if t.role == "assistant" else t
            for t in _stale_trace().turns
        ]
        trace = dataclasses.replace(_stale_trace(), turns=turns, primary_model="claude-opus-5")
        findings = [f for f in run(trace).findings if f.kind is FindingKind.STALE_CONTEXT]
        assert findings, "expected a stale_context finding"
        return findings[0].cost_usd

    standard, fast = stale_cost("standard"), stale_cost("fast")
    assert standard > 0
    assert fast == round(standard * 2, 4)


def test_primary_speed_elects_the_modal_turn_speed(write_jsonl):
    """Trace-level speed is elected like primary_model: most frequent wins, and turns
    without usage or without the field don't vote."""
    ts = "2026-07-20T02:00:00.000Z"
    lines = [make_user_line(uuid="u1", content="go", timestamp=ts)]
    for i, speed in enumerate(("fast", "fast", "standard")):
        lines.append(
            make_assistant_line(
                uuid=f"a{i}", parent_uuid="u1", text="x",
                model="claude-opus-5", speed=speed, timestamp=ts,
            )
        )
    trace = parse_session(write_jsonl(lines, filename="modal.jsonl"))
    assert trace.primary_speed == "fast"

    none_recorded = parse_session(
        write_jsonl([make_user_line(uuid="u1", content="go", timestamp=ts)], filename="empty.jsonl")
    )
    assert none_recorded.primary_speed is None


def test_missing_timestamp_does_not_price_at_the_epoch():
    """Turn.timestamp is non-optional and the parser substitutes the Unix epoch when a
    line carries none. Priced literally, that would resolve every schedule to its earliest
    entry, so the sentinel has to read as "unknown date" instead."""
    from cctx.diagnostician import _billing_date

    assert _billing_date(datetime.fromtimestamp(0, tz=UTC)) is None
    assert _billing_date(None) is None
    assert _billing_date(datetime(2026, 9, 1, 12, 0, tzinfo=UTC)).isoformat() == "2026-09-01"


def test_mixed_model_session_prices_each_turn_at_its_own_model(write_jsonl):
    """total_cost_usd bills each turn at its own model, not the trace's modal one.

    opusplan interleaves opus and sonnet turns inside one session. Pricing the
    whole trace at the modal model understates the expensive turns and
    overstates the cheap ones (#178). This asserts at the analyzer boundary --
    the CSV exporter is one consumer of the same number, not the contract.
    """
    ts = "2026-07-20T02:00:00.000Z"
    lines = [
        make_user_line(uuid="u1", content="go", timestamp=ts),
        make_assistant_line(
            uuid="a1", parent_uuid="u1", text="sonnet turn",
            model="claude-sonnet-4-6", timestamp=ts,
            input_tokens=1000, output_tokens=100,
        ),
        make_assistant_line(
            uuid="a2", parent_uuid="a1", text="opus turn",
            model="claude-opus-5", timestamp=ts,
            input_tokens=1000, output_tokens=100,
        ),
    ]
    diag = run(parse_session(write_jsonl(lines, filename="mixed.jsonl")))

    # Sonnet-4 family: $3/MTok in, $15/MTok out. Opus 5: $5/MTok in, $25/MTok out.
    sonnet = 1000 * 3e-6 + 100 * 15e-6   # 0.0045
    opus = 1000 * 5e-6 + 100 * 25e-6     # 0.0075
    assert diag.total_cost_usd == round(sonnet + opus, 4)

    # The modal model is sonnet (tie broken toward first-seen); pricing the whole
    # trace at it would have produced 2x the sonnet figure.
    assert diag.total_cost_usd != round(sonnet * 2, 4)
