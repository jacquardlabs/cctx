"""Tests for cctx/diagnostician/patterns/stale_context.py."""
from __future__ import annotations

from tests.diagnostician.conftest import (
    make_assistant_turn,
    make_tool_result,
    make_tool_result_turn,
    make_tool_use,
    make_trace,
    make_user_turn,
)

# A large content string: >2000 tokens. 160 reps × 10 words × 1.3 = 2080 tokens at 1.3 factor.
_LARGE_CONTENT = ("The search results show many TODO items across the codebase. " * 160).strip()
# A 3-gram that appears in _LARGE_CONTENT, for reference detection tests
_LARGE_CONTENT_3GRAM = "search results show"


def _stale_trace(n_silent_turns: int = 6, content: str = _LARGE_CONTENT):
    """
    Trace where a large Bash result goes unreferenced for n_silent_turns.
    Turn 1: user prompt
    Turn 2: assistant Bash tool_use
    Turn 3: tool_result with large content (last reference is here implicitly)
    Turns 4..4+n_silent_turns: assistant+user turns with no reference to content
    """
    uid = "toolu_bash_01"
    turns = [
        make_user_turn(1, "find all TODOs"),
        make_assistant_turn(2, tool_uses=[make_tool_use(uid, "Bash", {"command": "grep -r TODO ."})]),
        make_tool_result_turn(3, tool_results=[make_tool_result(uid, "Bash", content)]),
    ]
    for i in range(n_silent_turns):
        t = 4 + i * 2
        uid2 = f"toolu_silent_{i}"
        turns.append(make_assistant_turn(t, tool_uses=[make_tool_use(uid2, "Read", {"file_path": "other.py"})]))
        turns.append(make_tool_result_turn(t + 1, tool_results=[make_tool_result(uid2, "Read", "some content")]))
    return make_trace(turns)


def test_empty_trace_returns_empty():
    from cctx.diagnostician.patterns.stale_context import classify

    assert classify(make_trace([])) == []


def test_small_result_ignored():
    """Tool results under T_size=2000 tokens are not candidates."""
    from cctx.diagnostician.patterns.stale_context import classify

    uid = "toolu_small"
    turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use(uid, "Bash", {"command": "ls"})]),
        make_tool_result_turn(3, tool_results=[make_tool_result(uid, "Bash", "file1.py\nfile2.py")]),
    ]
    assert classify(make_trace(turns)) == []


def test_large_result_stays_referenced_no_finding():
    """Large result referenced in every subsequent turn — not stale."""
    from cctx.diagnostician.patterns.stale_context import classify

    uid = "toolu_grep"
    turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use(uid, "Bash", {"command": "grep -r TODO ."})]),
        make_tool_result_turn(3, tool_results=[make_tool_result(uid, "Bash", _LARGE_CONTENT)]),
        # Reference the content in subsequent turns
        make_assistant_turn(4, text=f"Based on {_LARGE_CONTENT_3GRAM}, I see several items."),
        make_user_turn(5),
        make_assistant_turn(6, text=f"Continuing with {_LARGE_CONTENT_3GRAM} analysis."),
    ]
    assert classify(make_trace(turns)) == []


def test_detects_stale_large_result():
    from cctx.diagnostician.patterns.stale_context import classify
    from cctx.models import FindingKind

    findings = classify(_stale_trace(n_silent_turns=6))
    assert len(findings) == 1
    f = findings[0]
    assert f.kind is FindingKind.STALE_CONTEXT
    assert f.evidence["total_token_turns"] > 0
    assert len(f.evidence["stale_items"]) == 1


def test_first_turn_is_after_n_stale():
    """first_turn = last_referenced_turn + N_stale (= 5)."""
    from cctx.diagnostician.patterns.stale_context import classify

    findings = classify(_stale_trace(n_silent_turns=6))
    item = findings[0].evidence["stale_items"][0]
    expected_first_turn = item["last_referenced_turn"] + 5
    assert findings[0].first_turn == expected_first_turn


def test_confidence_medium_below_500k_token_turns():
    from cctx.diagnostician.patterns.stale_context import classify
    from cctx.models import Confidence, Severity

    findings = classify(_stale_trace(n_silent_turns=6))
    # With ~2080 tokens × turns_stale → well below 500K → MEDIUM
    f = findings[0]
    assert f.confidence is Confidence.MEDIUM
    assert f.severity is Severity.MEDIUM


def test_confidence_high_above_500k_token_turns():
    from cctx.diagnostician.patterns.stale_context import classify
    from cctx.models import Confidence, Severity

    # ~2500 tokens × 200 billed assistant turns ≈ 500K token-turns → HIGH
    big_content = (_LARGE_CONTENT * 2)[:12000]
    findings = classify(_stale_trace(n_silent_turns=200, content=big_content))
    assert len(findings) == 1
    assert findings[0].evidence["total_token_turns"] > 500_000
    assert findings[0].confidence is Confidence.HIGH
    assert findings[0].severity is Severity.HIGH


def test_cost_usd_is_none_from_classifier():
    """Classifier returns cost_usd=None; orchestrator patches it."""
    from cctx.diagnostician.patterns.stale_context import classify

    findings = classify(_stale_trace(n_silent_turns=6))
    assert findings[0].cost_usd is None


def test_compaction_resets_stale_count(tmp_path):
    """A compaction system turn resets staleness — item excluded from finding."""
    from cctx.diagnostician.patterns.stale_context import classify
    from cctx.models import Turn
    from tests.diagnostician.conftest import _dt

    uid = "toolu_grep_c"
    compaction_turn = Turn(
        turn_number=4,
        uuid="uuid-compact",
        parent_uuid=None,
        role="system",
        text="<compaction>context was compacted</compaction>",
        thinking="",
        tool_uses=[],
        tool_results=[],
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=_dt(40),
        duration_ms=None,
    )
    turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use(uid, "Bash", {"command": "grep TODO ."})]),
        make_tool_result_turn(3, tool_results=[make_tool_result(uid, "Bash", _LARGE_CONTENT)]),
        compaction_turn,
        make_assistant_turn(5),
        make_assistant_turn(7),
        make_assistant_turn(9),
        make_assistant_turn(11),
        make_assistant_turn(13),
    ]
    # After compaction at turn 4, the large result is gone — no finding expected
    assert classify(make_trace(turns)) == []
