"""Autopsy diagnostician — public entry point.

run(trace) -> Diagnosis
  Runs all pattern classifiers, detects inflection turn,
  patches stale_context cost attribution, and returns
  a Diagnosis with patches=[] and subagent_costs populated.

The Recommender (cctx.recommender.claude_md) populates patches.
"""
from __future__ import annotations

import dataclasses
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from cctx.diagnostician import inflection
from cctx.diagnostician.patterns import (
    cache_hygiene,
    compaction,
    dead_end,
    exploration_thrash,
    fan_out,
    retry_loop,
    scope_creep,
    stale_context,
    tool_thrash,
    unused_context,
)
from cctx.models import Diagnosis, Finding, FindingKind, SubagentAttribution
from cctx.pricing import get_pricing as _get_pricing
from cctx.pricing import is_known_model as _is_known_model

if TYPE_CHECKING:
    from cctx.models import SessionTrace

UTC = timezone.utc

# Single-session classifiers, run in order. Each is invoked through
# _safe_classify so one classifier raising never aborts the whole diagnosis.
# A tuple of modules (not bound functions) keeps `module.classify` a call-time
# lookup, so the error policy lives in exactly one place.
_CLASSIFIER_MODULES = (
    retry_loop,
    scope_creep,
    stale_context,
    tool_thrash,
    dead_end,
    fan_out,
    cache_hygiene,
    compaction,
    exploration_thrash,
    unused_context,
)

# Recursed into subagents (the 9 per-turn classifiers). fan_out is excluded: it
# analyzes the *set* of a trace's subagents (overlap/retry), not interior turns,
# and is computed once at the root via _patch_fanout_costs / the waste block.
_PER_TURN_CLASSIFIER_MODULES = tuple(m for m in _CLASSIFIER_MODULES if m is not fan_out)


def _safe_classify(classify, trace: SessionTrace) -> list[Finding]:
    """Run one classifier, isolating failures so the diagnosis still completes."""
    try:
        return classify(trace)
    except Exception:
        return []


def _classify_subagents(
    trace: SessionTrace, parent_map: dict[str, str | None]
) -> list[Finding]:
    """Classify every subagent recursively; stamp findings with the subagent's
    session_id and price each at the subagent's own model. Populates parent_map
    (child session_id -> parent session_id) for the waste-accounting ancestry walk."""
    out: list[Finding] = []
    for sub in trace.subagents:
        parent_map[sub.session_id] = trace.session_id
        sub_findings: list[Finding] = []
        for module in _PER_TURN_CLASSIFIER_MODULES:
            sub_findings.extend(_safe_classify(module.classify, sub))
        sub_findings = _patch_costs(sub_findings, sub)  # priced at subagent's own model/date/speed
        out.extend(dataclasses.replace(f, session_id=sub.session_id) for f in sub_findings)
        out.extend(_classify_subagents(sub, parent_map))  # recurse into grandchildren
    return out


def _has_flagged_ancestor(
    session_id: str | None, parent_map: dict[str, str | None], wasted_sids: set[str]
) -> bool:
    """True if session_id or any ancestor subagent is fan-out-flagged."""
    seen: set[str] = set()
    cur = session_id
    while cur is not None and cur not in seen:
        if cur in wasted_sids:
            return True
        seen.add(cur)
        cur = parent_map.get(cur)
    return False


def _interior_waste(
    findings: list[Finding], parent_map: dict[str, str | None], wasted_sids: set[str]
) -> float:
    """Sum subagent-finding cost, excluding any whose subagent (or ancestor) is
    already counted wholesale via fan-out waste — so no cost is double-counted."""
    return sum(
        f.cost_usd for f in findings
        if f.session_id is not None
        and f.cost_usd is not None
        and not _has_flagged_ancestor(f.session_id, parent_map, wasted_sids)
    )


# Rates can change on an announced date, so cost lookups carry the date the session ran.
# Turn.timestamp is non-optional and the parser substitutes the Unix epoch when a line
# has no timestamp — anything predating Claude is that sentinel, not a billing date.
_PRICING_DATE_FLOOR = date(2023, 1, 1)


def _billing_date(ts: datetime | None) -> date | None:
    """Date to price a turn or trace at. None means "unknown" — get_pricing uses today."""
    if ts is None:
        return None
    d = ts.date()
    return d if d >= _PRICING_DATE_FLOOR else None


# Findings whose evidence carries a plain token count already attributable to
# waste — priced at the trace's modal input rate. Token-turns/re-fetches span
# many requests, so the modal rate (not any one turn's) is the honest number.
_TOKEN_EVIDENCE_KEY: dict[FindingKind, str] = {
    FindingKind.STALE_CONTEXT: "total_token_turns",
    FindingKind.TOOL_THRASH: "total_waste_tokens",
    FindingKind.EXPLORATION_THRASH: "total_waste_tokens",
    FindingKind.COMPACTION: "total_refetch_tokens",
}

# Findings whose evidence carries specific wasted-request turn numbers — priced
# as the whole request (input+output+cache) at that turn's own date/speed via
# _compute_own_cost, since a wasted retry costs the full round-trip, not just
# the error message.
_TURN_EVIDENCE_KEY: dict[FindingKind, str] = {
    FindingKind.RETRY_LOOP: "waste_turns",
    FindingKind.DEAD_END: "waste_turns",
}


def _patch_costs(findings: list[Finding], trace: SessionTrace) -> list[Finding]:
    """Fill cost_usd on findings, priced from `trace`'s own model/date/speed.

    CACHE_HYGIENE is priced separately: it's counterfactual waste (tokens that
    would have been cache hits at a healthy baseline rate), not observed waste
    like every other kind here — see cache_hygiene.WASTE_BASELINE_HIT_RATE.

    cost_usd stays None (rather than becoming 0.0) when a finding's own waste
    basis computes to zero — e.g. a tool_thrash burst that turns out to be all
    errors (excluded; that's retry_loop's cost) or a compaction with no
    re-fetches. Every renderer/exporter branches on cost_usd is not None to
    decide whether to print a dollar figure, so None vs. 0.0 is a real,
    load-bearing distinction — collapsing "no data" and "zero waste" into a
    single None keeps that check honest everywhere without special-casing
    each consumer.
    """
    on = _billing_date(trace.start_time)
    pricing = _get_pricing(trace.primary_model, speed=trace.primary_speed, on=on)
    price = pricing.input_per_mtok / 1_000_000

    result = []
    for f in findings:
        cost: float | None = None
        token_key = _TOKEN_EVIDENCE_KEY.get(f.kind)
        turn_key = _TURN_EVIDENCE_KEY.get(f.kind)
        if token_key is not None:
            tokens = f.evidence.get(token_key, 0)
            cost = tokens * price
        elif turn_key is not None:
            waste_turns = set(f.evidence.get(turn_key, []))
            cost = _compute_own_cost(trace, trace.primary_model, turn_numbers=waste_turns)
        elif f.kind is FindingKind.CACHE_HYGIENE:
            total_tokens = f.evidence.get("total_tokens", 0)
            hit_rate = f.evidence.get("overall_hit_rate", 0.0)
            miss_tokens = total_tokens * max(0.0, cache_hygiene.WASTE_BASELINE_HIT_RATE - hit_rate)
            miss_penalty = price * (1 - pricing.cache_read_mult)
            cost = miss_tokens * miss_penalty

        if cost is not None and round(cost, 4) > 0:
            f = dataclasses.replace(f, cost_usd=round(cost, 4))
        result.append(f)
    return result


def _patch_fanout_costs(
    findings: list[Finding],
    subagent_costs: list[SubagentAttribution],
) -> list[Finding]:
    """Fill cost_usd on FANOUT_WASTE findings from subagent attribution data.

    For overlap findings: picks the cheaper of the two subagents as waste.
    For retry findings: attributes the full cost of the failed subagent.
    Populates evidence['subagent_session_ids'] so run()'s dedup pass works.
    """
    cost_map = {a.session_id: a.total_cost_usd for a in subagent_costs}
    result: list[Finding] = []
    for f in findings:
        if f.kind is FindingKind.FANOUT_WASTE:
            signal = f.evidence.get("signal")
            if signal == "overlap":
                pair = [sid for sid in f.evidence.get("overlap_pair", []) if sid is not None]
                if pair:
                    cheaper_cost, cheaper_sid = min(
                        (cost_map.get(sid, 0.0), sid) for sid in pair
                    )
                    f = dataclasses.replace(
                        f,
                        cost_usd=round(cheaper_cost, 4),
                        evidence={**f.evidence, "subagent_session_ids": [cheaper_sid]},
                    )
            elif signal == "retry":
                failed_sid = f.evidence.get("failed_session_id")
                if failed_sid is not None:
                    cost = cost_map.get(failed_sid, 0.0)
                    f = dataclasses.replace(
                        f,
                        cost_usd=round(cost, 4),
                        evidence={**f.evidence, "subagent_session_ids": [failed_sid]},
                    )
        result.append(f)
    return result


def _collect_unknown_models(trace: SessionTrace) -> list[str]:
    """Distinct non-None model ids priced at the default rate (unrecognized family).

    Walks the trace and all subagents so a new model anywhere in the tree is
    flagged — the "new model introduced" half of pricing freshness.
    """
    seen: dict[str, None] = {}

    def _walk(t: SessionTrace) -> None:
        m = t.primary_model
        if m is not None and not _is_known_model(m):
            seen.setdefault(m, None)
        for sa in t.subagents:
            _walk(sa)

    _walk(trace)
    return list(seen)


def _compute_own_cost(
    trace: SessionTrace, model: str | None, turn_numbers: set[int] | None = None
) -> float:
    """Parent-turns-only cost — does not recurse into subagents.

    Prices input AND output tokens at the model's per-type rate (get_pricing),
    plus prompt-cache reads/writes at the model's cache multipliers (5-min and
    1-hr writes billed separately; all zero for non-Anthropic models).

    Priced per turn rather than per session, because two request-level facts move the
    rate: usage.speed (fast mode bills at premium rates) and the turn's date (a session
    can straddle an announced rate change).

    turn_numbers, when given, restricts pricing to that subset — used to cost
    specific wasted requests (e.g. retry_loop's repeat attempts) rather than
    the whole trace.
    """
    trace_on = _billing_date(trace.start_time)
    total = 0.0
    for turn in trace.turns:
        if turn_numbers is not None and turn.turn_number not in turn_numbers:
            continue
        u = turn.usage
        if u is None:
            continue
        p = _get_pricing(model, speed=u.speed, on=_billing_date(turn.timestamp) or trace_on)
        in_tok = p.input_per_mtok / 1_000_000
        out_tok = p.output_per_mtok / 1_000_000
        total += u.input_tokens * in_tok
        total += u.output_tokens * out_tok
        total += u.cache_read * in_tok * p.cache_read_mult
        total += u.cache_creation_5m * in_tok * p.cache_write_5m_mult
        total += u.cache_creation_1h * in_tok * p.cache_write_1h_mult
    return round(total, 4)


def _compute_inclusive_cost(trace: SessionTrace) -> float:
    """Recursive cost: own turns + all subagent turns at every depth."""
    own = _compute_own_cost(trace, trace.primary_model)
    return own + sum(_compute_inclusive_cost(sa) for sa in trace.subagents)


def _build_dispatch_map(trace: SessionTrace) -> dict[str, tuple[str, str]]:
    """Map child session_id → (display label, dispatching tool_use_id) from
    the parent's Agent ToolUse inputs."""
    dispatch_map: dict[str, tuple[str, str]] = {}
    for turn in trace.turns:
        for tu in turn.tool_uses:
            if tu.subagent_session_id:
                ti = tu.tool_input
                label = (
                    ti.get("description")
                    or (ti.get("prompt") or "")[:80]
                    or tu.subagent_session_id[:12]
                )
                dispatch_map[tu.subagent_session_id] = (label, tu.tool_use_id)
    return dispatch_map


def _collect_attributions(
    trace: SessionTrace,
    depth: int = 1,
    dispatch_map: dict[str, tuple[str, str]] | None = None,
) -> list[SubagentAttribution]:
    """Flat DFS list of SubagentAttribution, one per subagent at every depth."""
    if dispatch_map is None:
        dispatch_map = _build_dispatch_map(trace)
    result: list[SubagentAttribution] = []
    for child in trace.subagents:
        label, dispatching_tool_use_id = dispatch_map.get(
            child.session_id, (child.session_id[:12], None)
        )
        cost = _compute_inclusive_cost(child)
        result.append(SubagentAttribution(
            session_id=child.session_id,
            label=label,
            total_cost_usd=round(cost, 4),
            depth=depth,
            model=child.primary_model,
            dispatching_tool_use_id=dispatching_tool_use_id,
        ))
        result.extend(_collect_attributions(child, depth + 1, None))
    return result


def run(trace: SessionTrace) -> Diagnosis:
    """Diagnose a single SessionTrace. Returns Diagnosis with patches=[]."""
    root_findings: list[Finding] = []
    for module in _CLASSIFIER_MODULES:
        root_findings.extend(_safe_classify(module.classify, trace))
    root_findings.sort(key=lambda f: f.first_turn)

    inflection_turn = inflection.detect(root_findings)          # root-only
    root_findings = _patch_costs(root_findings, trace)

    # Recurse into subagents; each priced at its own model, stamped with its id.
    parent_map: dict[str, str | None] = {}
    subagent_findings = _classify_subagents(trace, parent_map)

    findings = root_findings + subagent_findings               # root first, then tree order

    # Fan-out cost patching requires attributions first.
    subagent_costs = _collect_attributions(trace)
    findings = _patch_fanout_costs(findings, subagent_costs)

    total_cost = round(_compute_inclusive_cost(trace), 4)

    # Deduplicate fan-out waste: a subagent flagged by both overlap AND retry
    # must not be double-counted. Collect unique wasted session IDs, sum once.
    cost_map = {a.session_id: a.total_cost_usd for a in subagent_costs}
    wasted_sids: set[str] = set()
    for f in findings:
        if f.kind is FindingKind.FANOUT_WASTE:
            wasted_sids.update(f.evidence.get("subagent_session_ids", []))
    fanout_waste = sum(cost_map.get(sid, 0.0) for sid in wasted_sids)
    other_waste = sum(
        f.cost_usd for f in findings
        if f.session_id is None
        and f.cost_usd is not None
        and f.kind is not FindingKind.FANOUT_WASTE
    )
    interior_waste = _interior_waste(findings, parent_map, wasted_sids)
    waste_cost = min(other_waste + fanout_waste + interior_waste, total_cost)

    return Diagnosis(
        session_id=trace.session_id,
        findings=findings,
        inflection_turn=inflection_turn,
        patches=[],
        total_cost_usd=total_cost,
        waste_cost_usd=round(waste_cost, 4),
        analysed_at=datetime.now(UTC),
        subagent_costs=subagent_costs,
        unknown_models=_collect_unknown_models(trace),
    )
