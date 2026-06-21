"""Tests for pure-Python helpers in cctx/renderers/trace_tui.py.

Textual Pilot (async UI) tests are omitted — the pure functions cover
correctness of the logic; the TUI is exercised manually.
"""

from __future__ import annotations

from datetime import datetime, timezone

from tests.diagnostician.conftest import (
    make_assistant_turn,
    make_trace,
    make_user_turn,
)


def _make_finding(first_turn: int, last_turn: int | None = None, waste: float = 0.5):
    from cctx.models import Confidence, Finding, FindingKind, Severity

    # Build evidence so stale_context extraction produces the expected range
    stale_items = []
    if last_turn is not None and last_turn > first_turn:
        stale_items = [{"last_referenced_turn": first_turn - 1, "token_turns": 100}]

    return Finding(
        kind=FindingKind.STALE_CONTEXT,
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=first_turn,
        last_turn=last_turn,
        evidence={"stale_items": stale_items, "total_token_turns": 100} if stale_items else {},
        cost_usd=waste,
        summary=f"test finding at turn {first_turn}",
    )


def _make_diagnosis(findings, waste_cost_usd: float = 0.0):
    from cctx.models import Diagnosis

    return Diagnosis(
        session_id="test-session",
        findings=findings,
        inflection_turn=None,
        patches=[],
        total_cost_usd=1.0,
        waste_cost_usd=waste_cost_usd,
        analysed_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# affected_turns
# ---------------------------------------------------------------------------


def test_affected_turns_no_last_turn():
    """Finding with last_turn=None → only first_turn in the set."""
    from cctx.renderers.trace_tui import affected_turns

    trace = make_trace([make_user_turn(1)])
    f = _make_finding(1, last_turn=None)
    assert affected_turns(f, trace) == frozenset({1})


def test_affected_turns_stale_context_range():
    """STALE_CONTEXT finding with stale_items — returns turns after last_referenced_turn."""
    from cctx.renderers.trace_tui import affected_turns

    trace = make_trace([make_user_turn(i) for i in range(1, 10)])

    from cctx.models import Confidence, Finding, FindingKind, Severity
    f = Finding(
        kind=FindingKind.STALE_CONTEXT,
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=3,
        last_turn=7,
        evidence={
            "stale_items": [{"last_referenced_turn": 2, "token_turns": 100}],
            "total_token_turns": 100,
        },
        cost_usd=None,
        summary="stale",
    )
    # Turns after last_referenced_turn=2, up to last_turn=7 → {3,4,5,6,7}
    assert affected_turns(f, trace) == frozenset({3, 4, 5, 6, 7})


def test_affected_turns_same_start_end():
    """first_turn == last_turn → single-element frozenset."""
    from cctx.models import Confidence, Finding, FindingKind, Severity
    from cctx.renderers.trace_tui import affected_turns
    trace = make_trace([make_user_turn(5)])
    f = Finding(
        kind=FindingKind.STALE_CONTEXT,
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=5,
        last_turn=5,
        evidence={
            "stale_items": [{"last_referenced_turn": 4, "token_turns": 50}],
            "total_token_turns": 50,
        },
        cost_usd=None,
        summary="stale",
    )
    assert affected_turns(f, trace) == frozenset({5})


def test_affected_turns_retry_loop():
    """RETRY_LOOP finding uses occurrences[].turn — sparse turns, not a range."""
    from cctx.models import Confidence, Finding, FindingKind, Severity
    from cctx.renderers.trace_tui import affected_turns

    trace = make_trace([make_user_turn(i) for i in range(1, 10)])
    f = Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=3,
        last_turn=7,
        evidence={
            "occurrences": [
                {"turn": 3, "key": "f.py", "call": "Edit", "error": "err"},
                {"turn": 7, "key": "f.py", "call": "Edit", "error": "err"},
            ],
            "loop_length": 2,
        },
        cost_usd=None,
        summary="retry",
    )
    # Only the specific error turns, NOT 3,4,5,6,7
    assert affected_turns(f, trace) == frozenset({3, 7})


def test_affected_turns_scope_creep():
    """SCOPE_CREEP finding uses phrases[].turn."""
    from cctx.models import Confidence, Finding, FindingKind, Severity
    from cctx.renderers.trace_tui import affected_turns

    trace = make_trace([make_user_turn(i) for i in range(1, 10)])
    f = Finding(
        kind=FindingKind.SCOPE_CREEP,
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=4,
        last_turn=4,
        evidence={"phrases": [{"turn": 4, "phrase": "let me also", "snippet": "..."}]},
        cost_usd=None,
        summary="scope",
    )
    assert affected_turns(f, trace) == frozenset({4})


def test_affected_turns_empty_evidence_fallback():
    """Finding with empty evidence falls back to first_turn only."""
    from cctx.models import Confidence, Finding, FindingKind, Severity
    from cctx.renderers.trace_tui import affected_turns

    trace = make_trace([make_user_turn(i) for i in range(1, 5)])
    f = Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=2,
        last_turn=4,
        evidence={},  # empty
        cost_usd=None,
        summary="retry",
    )
    assert affected_turns(f, trace) == frozenset({2})


# ---------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------


def test_verdict_clean_session():
    """No findings → 'Clean session'."""
    from cctx.renderers.trace_tui import verdict

    diag = _make_diagnosis([], waste_cost_usd=0.0)
    assert verdict(diag) == "Clean session"


def test_verdict_single_finding():
    """One finding → singular 'finding', shows waste amount."""
    from cctx.renderers.trace_tui import verdict

    f = _make_finding(1, last_turn=3, waste=0.42)
    diag = _make_diagnosis([f], waste_cost_usd=0.42)
    result = verdict(diag)
    assert "1 finding" in result
    assert "0.42" in result
    assert "findings" not in result  # must be singular


def test_verdict_multiple_findings():
    """Multiple findings → plural 'findings', shows waste."""
    from cctx.renderers.trace_tui import verdict

    f1 = _make_finding(1, last_turn=3, waste=0.30)
    f2 = _make_finding(5, last_turn=7, waste=0.20)
    diag = _make_diagnosis([f1, f2], waste_cost_usd=0.50)
    result = verdict(diag)
    assert "2 findings" in result
    assert "0.50" in result


def test_verdict_zero_waste():
    """Findings present but zero waste → still shows finding count."""
    from cctx.renderers.trace_tui import verdict

    f = _make_finding(1, last_turn=1, waste=0.0)
    diag = _make_diagnosis([f], waste_cost_usd=0.0)
    result = verdict(diag)
    assert "1 finding" in result
    assert "0.00" in result


def test_verdict_delegates_to_diagnosis_verdict():
    """trace_tui.verdict() must be the canonical Diagnosis.verdict (single source)."""
    from cctx.renderers.trace_tui import verdict

    f = _make_finding(1, last_turn=3, waste=0.42)
    diag = _make_diagnosis([f], waste_cost_usd=0.42)
    assert verdict(diag) == diag.verdict


# ---------------------------------------------------------------------------
# finding_modal_text / flags_label — KIND_LABEL, never the raw enum (#136)
# ---------------------------------------------------------------------------


def _finding_of_kind(kind):
    from cctx.models import Confidence, Finding, Severity

    return Finding(
        kind=kind,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=1,
        last_turn=2,
        evidence={},
        cost_usd=0.01,
        summary="circling",
    )


def test_finding_modal_text_uses_kind_label():
    from cctx.models import FindingKind
    from cctx.renderers.trace_tui import finding_modal_text

    text = finding_modal_text([_finding_of_kind(FindingKind.EXPLORATION_THRASH)])
    assert "EXPLORATION THRASH" in text
    assert "exploration_thrash" not in text


def test_finding_modal_text_empty():
    from cctx.renderers.trace_tui import finding_modal_text

    assert finding_modal_text([]) == "No findings."


def test_flags_label_uses_kind_label():
    from cctx.models import FindingKind
    from cctx.renderers.trace_tui import flags_label

    label = flags_label([_finding_of_kind(FindingKind.FANOUT_WASTE)])
    assert label == "FANOUT WASTE"


# ---------------------------------------------------------------------------
# _build_flagged_index
# ---------------------------------------------------------------------------


def test_build_flagged_index_empty():
    """No findings → empty dict."""
    from cctx.renderers.trace_tui import _build_flagged_index

    trace = make_trace([make_user_turn(1), make_assistant_turn(2)])
    assert _build_flagged_index([], trace) == {}


def test_build_flagged_index_single_finding():
    """Single finding spanning turns 2-4 → entries for turns 2, 3, 4 only."""
    from cctx.renderers.trace_tui import _build_flagged_index

    trace = make_trace([make_user_turn(i) for i in range(1, 6)])
    f = _make_finding(2, last_turn=4)
    index = _build_flagged_index([f], trace)
    assert set(index.keys()) == {2, 3, 4}
    assert index[2] == [f]
    assert index[3] == [f]
    assert index[4] == [f]


def test_build_flagged_index_overlap():
    """Two overlapping findings merge correctly at shared turns."""
    from cctx.renderers.trace_tui import _build_flagged_index

    trace = make_trace([make_user_turn(i) for i in range(1, 10)])
    f1 = _make_finding(2, last_turn=5)
    f2 = _make_finding(4, last_turn=7)
    index = _build_flagged_index([f1, f2], trace)
    assert set(index.keys()) == {2, 3, 4, 5, 6, 7}
    assert index[2] == [f1]
    assert index[3] == [f1]
    assert f1 in index[4] and f2 in index[4]
    assert f1 in index[5] and f2 in index[5]
    assert index[6] == [f2]
    assert index[7] == [f2]


def test_build_flagged_index_no_last_turn():
    """Finding with last_turn=None → only its first_turn is indexed."""
    from cctx.renderers.trace_tui import _build_flagged_index

    trace = make_trace([make_user_turn(i) for i in range(1, 5)])
    f = _make_finding(3, last_turn=None)
    index = _build_flagged_index([f], trace)
    assert set(index.keys()) == {3}
    assert index[3] == [f]


# ---------------------------------------------------------------------------
# Textual Pilot UI tests (#146)
#
# build_app() returns the App without running it, so App.run_test() (Pilot)
# can drive it headlessly. Tests are sync wrappers around asyncio.run() so they
# don't depend on pytest-asyncio being active. Screen identity is asserted via
# type(...).__name__ since the modal classes are nested inside build_app().
# ---------------------------------------------------------------------------


def _simple_trace():
    return make_trace([
        make_user_turn(1),
        make_assistant_turn(2, text="working on it"),
        make_assistant_turn(3, text="done"),
    ])


def _clean_diag():
    from cctx.models import Diagnosis

    return Diagnosis(
        session_id="sess-tui",
        findings=[],
        inflection_turn=None,
        patches=[],
        total_cost_usd=0.0,
        waste_cost_usd=0.0,
        analysed_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
    )


def _diag_flagging_turn_1():
    """A diagnosis whose finding's affected turns include turn 1 (first table row)."""
    from cctx.models import Confidence, Diagnosis, Finding, FindingKind, Severity

    finding = Finding(
        kind=FindingKind.TOOL_THRASH,  # else-branch in affected_turns -> range(first, last+1)
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=1,
        last_turn=1,
        evidence={},
        cost_usd=0.05,
        summary="thrashing on the same tool",
    )
    return Diagnosis(
        session_id="sess-tui",
        findings=[finding],
        inflection_turn=1,
        patches=[],
        total_cost_usd=1.0,
        waste_cost_usd=0.05,
        analysed_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
    )


def test_build_app_populates_turn_table():
    import asyncio

    from textual.widgets import DataTable

    from cctx.renderers.trace_tui import build_app

    trace = _simple_trace()

    async def scenario():
        app = build_app(trace, _clean_diag())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#turns", DataTable)
            assert table.row_count == len(trace.turns)

    asyncio.run(scenario())


def test_help_screen_opens_and_closes():
    import asyncio

    from cctx.renderers.trace_tui import build_app

    async def scenario():
        app = build_app(_simple_trace(), _clean_diag())
        async with app.run_test() as pilot:
            await pilot.press("question_mark")
            await pilot.pause()
            assert type(app.screen).__name__ == "HelpScreen"
            await pilot.press("escape")
            await pilot.pause()
            assert type(app.screen).__name__ != "HelpScreen"

    asyncio.run(scenario())


def test_quit_binding_exits_app():
    import asyncio

    from cctx.renderers.trace_tui import build_app

    async def scenario():
        app = build_app(_simple_trace(), _clean_diag())
        async with app.run_test() as pilot:
            await pilot.press("q")
            await pilot.pause()
        # context exits cleanly == app stopped on quit
        assert app.is_running is False

    asyncio.run(scenario())


def test_finding_modal_opens_on_flagged_turn():
    import asyncio

    from cctx.renderers.trace_tui import build_app

    diag = _diag_flagging_turn_1()

    async def scenario():
        app = build_app(_simple_trace(), diag)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f")  # cursor starts on row 0 == turn 1 (flagged)
            await pilot.pause()
            assert type(app.screen).__name__ == "FindingModal"

    asyncio.run(scenario())


def test_finding_modal_text_tags_subagent_finding():
    import dataclasses

    from cctx.models import FindingKind
    from cctx.renderers.trace_tui import finding_modal_text

    f = dataclasses.replace(_finding_of_kind(FindingKind.RETRY_LOOP), session_id="sub-1")
    text = finding_modal_text([f], sub_labels={"sub-1": "Resolver"})
    assert "[Resolver]" in text
    assert "RETRY LOOP" in text


def test_finding_modal_text_root_finding_has_no_tag():
    from cctx.models import FindingKind
    from cctx.renderers.trace_tui import finding_modal_text

    text = finding_modal_text([_finding_of_kind(FindingKind.RETRY_LOOP)])
    assert "[bold]RETRY LOOP" in text  # kind label directly after bold, no [tag] inserted
