"""Tests for cctx/diagnostician/__init__.py — run(trace) -> Diagnosis."""
from __future__ import annotations

import pytest

from tests.diagnostician.conftest import (
    make_assistant_turn,
    make_tool_result,
    make_tool_result_turn,
    make_tool_use,
    make_trace,
    make_user_turn,
)


def _make_usage(input_tokens=0, cache_read=0, cache_creation_5m=0, cache_creation_1h=0):
    from cctx.models import Usage
    return Usage(
        input_tokens=input_tokens,
        output_tokens=0,
        cache_creation_5m=cache_creation_5m,
        cache_creation_1h=cache_creation_1h,
        cache_read=cache_read,
        service_tier=None,
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


def test_compute_own_cost_bills_output_and_split_cache():
    """Output tokens are billed; 5m/1h cache writes use distinct multipliers (#120)."""
    import dataclasses

    from cctx.diagnostician import _compute_own_cost
    from cctx.models import Usage

    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_5m=1_000_000,
        cache_creation_1h=1_000_000,
        cache_read=1_000_000,
        service_tier=None,
    )
    turn = dataclasses.replace(make_assistant_turn(1, text="x"), usage=usage)
    trace = make_trace([turn], model="claude-sonnet-4-6")

    cost = _compute_own_cost(trace, "claude-sonnet-4-6")
    # sonnet $3 in / $15 out; cache 5m 1.25x, 1h 2.0x, read 0.1x of $3:
    # 3 + 15 + 3*1.25 + 3*2.0 + 3*0.1 = 28.05
    assert cost == 28.05


def test_run_records_unknown_models():
    """A non-None model priced at default is recorded — the 'new model' signal (#120)."""
    from cctx import diagnostician

    trace = make_trace([make_assistant_turn(1, text="x")], model="gpt-6-preview")
    diag = diagnostician.run(trace)
    assert "gpt-6-preview" in diag.unknown_models


def test_run_no_unknown_models_for_known_model():
    from cctx import diagnostician

    trace = make_trace([make_assistant_turn(1, text="x")], model="claude-sonnet-4-6")
    diag = diagnostician.run(trace)
    assert diag.unknown_models == []


def test_run_isolates_a_failing_classifier(monkeypatch):
    """A classifier that raises must not crash run(); other findings survive (#137).

    Patches unused_context, which has no internal try/except — so the isolation
    can only come from the orchestrator's _safe_classify wrapper.
    """
    from cctx import diagnostician
    from cctx.diagnostician.patterns import unused_context
    from cctx.models import FindingKind

    def boom(trace):
        raise RuntimeError("classifier exploded")

    monkeypatch.setattr(unused_context, "classify", boom)

    diagnosis = diagnostician.run(_retry_trace())  # must not raise
    assert FindingKind.RETRY_LOOP in [f.kind for f in diagnosis.findings]


def test_inflection_turn_set_to_min_first_turn():
    from cctx import diagnostician

    # Scope creep fires on turn 2 text; retry loop fires on turn 4 (second failure)
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
    assert len(diagnosis.findings) >= 2, "Need multiple findings to test min"
    min_turn = min(f.first_turn for f in diagnosis.findings)
    assert diagnosis.inflection_turn == min_turn


def test_findings_sorted_by_first_turn():
    from cctx import diagnostician

    # Scope creep fires on turn 2 text; retry loop fires on turn 4 (second failure)
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
    assert len(diagnosis.findings) >= 2, "Need multiple findings to test sort order"
    turns_list = [f.first_turn for f in diagnosis.findings]
    assert turns_list == sorted(turns_list)


def test_patches_empty_at_orchestrator_exit():
    from cctx import diagnostician

    diagnosis = diagnostician.run(_retry_trace())
    assert diagnosis.patches == []


def test_stale_context_cost_usd_patched():
    """stale_context findings get cost_usd from the orchestrator."""
    from cctx import diagnostician
    from cctx.models import FindingKind

    # 160 × 10 words × 1.3 ≈ 2080 tokens — above T_SIZE=2000
    _LARGE = ("The search results show many TODO items across the codebase. " * 160).strip()
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
    assert len(stale) == 1
    assert stale[0].cost_usd is not None
    assert stale[0].cost_usd > 0


def test_total_cost_includes_cache_read():
    """_compute_total_cost includes cache_read at 10% and cache_writes at 125%."""
    import dataclasses

    from cctx import diagnostician

    # Sonnet price = $3/MTok = 3e-6 per token
    # input:        1_000 tokens × 1.00 = 1_000 effective tokens
    # cache_read: 100_000 tokens × 0.10 = 10_000 effective tokens
    # cache_write: 10_000 tokens × 1.25 = 12_500 effective tokens
    # total effective = 23_500 × 3e-6 = $0.0705
    t = make_assistant_turn(2, text="ok")
    t = dataclasses.replace(
        t,
        usage=_make_usage(input_tokens=1_000, cache_read=100_000, cache_creation_5m=10_000),
    )
    trace = make_trace([make_user_turn(1), t], model="claude-sonnet-4-6")
    diagnosis = diagnostician.run(trace)
    assert diagnosis.total_cost_usd == pytest.approx(0.0705, abs=1e-4)


def test_waste_never_exceeds_total_cost():
    """waste_cost_usd is capped at total_cost_usd."""
    from cctx import diagnostician

    # Manufacture a session where naive waste would exceed total:
    # large stale result + no cache reads → cheap total but high estimated waste
    _LARGE = ("The search results show many TODO items across the codebase. " * 160).strip()
    uid = "toolu_big"
    turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use(uid, "Bash", {"command": "grep TODO ."})]),
        make_tool_result_turn(3, tool_results=[make_tool_result(uid, "Bash", _LARGE)]),
    ]
    for i in range(20):
        t = 4 + i * 2
        uid2 = f"toolu_s{i}"
        turns.append(make_assistant_turn(t, tool_uses=[make_tool_use(uid2, "Read", {"file_path": "x.py"})]))
        turns.append(make_tool_result_turn(t + 1, tool_results=[make_tool_result(uid2, "Read", "ok")]))
    trace = make_trace(turns)
    diagnosis = diagnostician.run(trace)
    assert diagnosis.waste_cost_usd <= diagnosis.total_cost_usd


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
