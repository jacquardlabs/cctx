"""Tests for cctx/diagnostician/patterns/scope_creep.py."""
from __future__ import annotations

from tests.diagnostician.conftest import (
    make_assistant_turn,
    make_trace,
    make_user_turn,
)


def _trace_with_phrase(phrase: str, turn_number: int = 3):
    """Trace where an assistant turn contains a scope-creep phrase."""
    return make_trace([
        make_user_turn(1, "add a new function"),
        make_user_turn(2, ""),
        make_assistant_turn(turn_number, text=f"I'll implement that. {phrase} clean up the imports."),
    ])


def test_empty_trace_returns_empty():
    from cctx.diagnostician.patterns.scope_creep import classify

    assert classify(make_trace([])) == []


def test_clean_trace_returns_empty():
    from cctx.diagnostician.patterns.scope_creep import classify

    turns = [
        make_user_turn(1, "add function"),
        make_assistant_turn(2, text="Done, I added the function."),
    ]
    assert classify(make_trace(turns)) == []


def test_detects_while_im_here():
    from cctx.diagnostician.patterns.scope_creep import classify
    from cctx.models import Confidence, FindingKind, Severity

    findings = classify(_trace_with_phrase("While I'm here, let me also"))
    assert len(findings) == 1
    f = findings[0]
    assert f.kind is FindingKind.SCOPE_CREEP
    assert f.confidence is Confidence.MEDIUM
    assert f.severity is Severity.MEDIUM
    assert f.first_turn == 3


def test_detects_let_me_also():
    from cctx.diagnostician.patterns.scope_creep import classify

    findings = classify(_trace_with_phrase("Let me also"))
    assert len(findings) == 1


def test_detects_i_also_noticed():
    from cctx.diagnostician.patterns.scope_creep import classify

    findings = classify(_trace_with_phrase("I also noticed"))
    assert len(findings) == 1


def test_detects_ill_also_fix():
    from cctx.diagnostician.patterns.scope_creep import classify

    findings = classify(_trace_with_phrase("I'll also fix"))
    assert len(findings) == 1


def test_detects_while_were_at_it():
    from cctx.diagnostician.patterns.scope_creep import classify

    findings = classify(_trace_with_phrase("While we're at it"))
    assert len(findings) == 1


def test_phrase_in_user_turn_ignored():
    """Scope-creep phrases only count in assistant turns."""
    from cctx.diagnostician.patterns.scope_creep import classify

    turns = [
        make_user_turn(1, "fix it, and while I'm here let me also check"),
        make_assistant_turn(2, text="Done."),
    ]
    assert classify(make_trace(turns)) == []


def test_multiple_phrases_first_turn_wins():
    """One Finding total; first_turn = earliest phrase occurrence."""
    from cctx.diagnostician.patterns.scope_creep import classify

    turns = [
        make_user_turn(1),
        make_assistant_turn(2, text="While I'm here, I'll fix this."),
        make_assistant_turn(4, text="I also noticed the formatting."),
    ]
    findings = classify(make_trace(turns))
    assert len(findings) == 1
    assert findings[0].first_turn == 2
    assert len(findings[0].evidence["phrases"]) == 2


def test_cost_usd_is_none():
    from cctx.diagnostician.patterns.scope_creep import classify

    findings = classify(_trace_with_phrase("While I'm here"))
    assert findings[0].cost_usd is None


def test_summary_mentions_phrase_and_turn():
    from cctx.diagnostician.patterns.scope_creep import classify

    findings = classify(_trace_with_phrase("While I'm here"))
    assert "turn" in findings[0].summary.lower() or "3" in findings[0].summary
