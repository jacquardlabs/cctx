"""Tests for cctx/diagnostician/__init__.py — run(trace) -> Diagnosis."""
from __future__ import annotations

from tests.diagnostician.conftest import (
    make_assistant_turn,
    make_tool_result,
    make_tool_result_turn,
    make_tool_use,
    make_trace,
    make_user_turn,
)


def _retry_trace():
    """Edit(src/foo.py) fails twice — triggers retry_loop."""
    uid1, uid2 = "toolu_01", "toolu_02"
    err = "Error: file not found"
    fp = "src/foo.py"
    return make_trace([
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use(uid1, "Edit", {"file_path": fp})]),
        make_tool_result_turn(3, tool_results=[make_tool_result(uid1, "Edit", err, is_error=True)]),
        make_assistant_turn(4, tool_uses=[make_tool_use(uid2, "Edit", {"file_path": fp})]),
        make_tool_result_turn(5, tool_results=[make_tool_result(uid2, "Edit", err, is_error=True)]),
    ])


def test_clean_trace_returns_no_findings():
    from cctx import diagnostician

    trace = make_trace([make_user_turn(1), make_assistant_turn(2, text="Done.")])
    diagnosis = diagnostician.run(trace)
    assert diagnosis.findings == []
    assert diagnosis.inflection_turn is None
    assert diagnosis.patches == []
    assert diagnosis.total_cost_usd == 0.0
    assert diagnosis.waste_cost_usd == 0.0


def test_retry_loop_finding_present():
    from cctx import diagnostician
    from cctx.models import FindingKind

    diagnosis = diagnostician.run(_retry_trace())
    kinds = [f.kind for f in diagnosis.findings]
    assert FindingKind.RETRY_LOOP in kinds


def test_inflection_turn_set_to_min_first_turn():
    from cctx import diagnostician

    diagnosis = diagnostician.run(_retry_trace())
    min_turn = min(f.first_turn for f in diagnosis.findings)
    assert diagnosis.inflection_turn == min_turn


def test_findings_sorted_by_first_turn():
    from cctx import diagnostician

    diagnosis = diagnostician.run(_retry_trace())
    turns = [f.first_turn for f in diagnosis.findings]
    assert turns == sorted(turns)


def test_patches_empty_at_orchestrator_exit():
    from cctx import diagnostician

    diagnosis = diagnostician.run(_retry_trace())
    assert diagnosis.patches == []


def test_stale_context_cost_usd_patched():
    """stale_context findings get cost_usd from the orchestrator."""
    from cctx import diagnostician
    from cctx.models import FindingKind

    # Build a trace with a large stale result
    _LARGE = ("grep output " * 200).strip()
    uid = "toolu_grep"
    turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use(uid, "Bash", {"command": "grep TODO ."})]),
        make_tool_result_turn(3, tool_results=[make_tool_result(uid, "Bash", _LARGE)]),
    ]
    for i in range(8):
        t = 4 + i * 2
        uid2 = f"toolu_s{i}"
        turns.append(
            make_assistant_turn(
                t, tool_uses=[make_tool_use(uid2, "Read", {"file_path": f"f{i}.py"})]
            )
        )
        turns.append(
            make_tool_result_turn(t + 1, tool_results=[make_tool_result(uid2, "Read", "x")])
        )
    trace = make_trace(turns, model="claude-sonnet-4-6")

    diagnosis = diagnostician.run(trace)
    stale = [f for f in diagnosis.findings if f.kind is FindingKind.STALE_CONTEXT]
    if stale:
        assert stale[0].cost_usd is not None
        assert stale[0].cost_usd > 0


def test_retry_and_scope_both_detected():
    """Two classifiers fire; inflection_turn = min of both first_turns."""
    from cctx import diagnostician
    from cctx.models import FindingKind

    uid1, uid2 = "toolu_01", "toolu_02"
    err = "Error: not found"
    turns = [
        make_user_turn(1),
        make_assistant_turn(
            2,
            text="While I'm here, let me also fix formatting.",
            tool_uses=[make_tool_use(uid1, "Edit", {"file_path": "a.py"})],
        ),
        make_tool_result_turn(3, tool_results=[make_tool_result(uid1, "Edit", err, is_error=True)]),
        make_assistant_turn(4, tool_uses=[make_tool_use(uid2, "Edit", {"file_path": "a.py"})]),
        make_tool_result_turn(5, tool_results=[make_tool_result(uid2, "Edit", err, is_error=True)]),
    ]
    diagnosis = diagnostician.run(make_trace(turns))
    kinds = {f.kind for f in diagnosis.findings}
    assert FindingKind.RETRY_LOOP in kinds
    assert FindingKind.SCOPE_CREEP in kinds
    assert diagnosis.inflection_turn == min(f.first_turn for f in diagnosis.findings)
