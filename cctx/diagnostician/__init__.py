"""Autopsy diagnostician — public entry point.

run(trace) -> Diagnosis
  Runs all pattern classifiers, detects inflection turn,
  patches stale_context cost attribution, and returns
  a Diagnosis with patches=[] and subagent_costs populated.

The Recommender (cctx.recommender.claude_md) populates patches.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from cctx.diagnostician import inflection
from cctx.diagnostician.patterns import (
    dead_end,
    retry_loop,
    scope_creep,
    stale_context,
    tool_thrash,
)
from cctx.models import Diagnosis, Finding, FindingKind, SubagentAttribution
from cctx.pricing import price_per_tok as _price_per_tok

if TYPE_CHECKING:
    from cctx.models import SessionTrace

UTC = timezone.utc


def _patch_costs(findings: list[Finding], model: str | None) -> list[Finding]:
    price = _price_per_tok(model)
    result = []
    for f in findings:
        if f.kind is FindingKind.STALE_CONTEXT:
            tt = f.evidence.get("total_token_turns", 0)
            f = dataclasses.replace(f, cost_usd=round(tt * price, 4))
        result.append(f)
    return result


def _compute_own_cost(trace: SessionTrace, model: str | None) -> float:
    """Parent-turns-only cost — does not recurse into subagents."""
    price = _price_per_tok(model)
    total = 0.0
    for turn in trace.turns:
        if turn.usage is not None:
            total += turn.usage.input_tokens * price
            total += turn.usage.cache_read * price * 0.1
            cache_writes = turn.usage.cache_creation_5m + turn.usage.cache_creation_1h
            total += cache_writes * price * 1.25
    return round(total, 4)


def _compute_inclusive_cost(trace: SessionTrace) -> float:
    """Recursive cost: own turns + all subagent turns at every depth."""
    own = _compute_own_cost(trace, trace.primary_model)
    return own + sum(_compute_inclusive_cost(sa) for sa in trace.subagents)


def _build_label_map(trace: SessionTrace) -> dict[str, str]:
    """Map child session_id → display label from the parent's Agent ToolUse inputs."""
    label_map: dict[str, str] = {}
    for turn in trace.turns:
        for tu in turn.tool_uses:
            if tu.subagent_session_id:
                ti = tu.tool_input
                label_map[tu.subagent_session_id] = (
                    ti.get("description")
                    or (ti.get("prompt") or "")[:80]
                    or tu.subagent_session_id[:12]
                )
    return label_map


def _collect_attributions(
    trace: SessionTrace,
    depth: int = 1,
    label_map: dict[str, str] | None = None,
) -> list[SubagentAttribution]:
    """Flat DFS list of SubagentAttribution, one per subagent at every depth."""
    if label_map is None:
        label_map = _build_label_map(trace)
    result: list[SubagentAttribution] = []
    for child in trace.subagents:
        label = label_map.get(child.session_id, child.session_id[:12])
        cost = _compute_inclusive_cost(child)
        result.append(SubagentAttribution(
            session_id=child.session_id,
            label=label,
            total_cost_usd=round(cost, 4),
            depth=depth,
            model=child.primary_model,
        ))
        result.extend(_collect_attributions(child, depth + 1, None))
    return result


def run(trace: SessionTrace) -> Diagnosis:
    """Diagnose a single SessionTrace. Returns Diagnosis with patches=[]."""
    findings: list[Finding] = [
        *retry_loop.classify(trace),
        *scope_creep.classify(trace),
        *stale_context.classify(trace),
        *tool_thrash.classify(trace),
        *dead_end.classify(trace),
    ]
    findings.sort(key=lambda f: f.first_turn)

    inflection_turn = inflection.detect(findings)
    findings = _patch_costs(findings, trace.primary_model)

    total_cost = round(_compute_inclusive_cost(trace), 4)
    waste_cost = sum(f.cost_usd for f in findings if f.cost_usd is not None)
    waste_cost = min(waste_cost, total_cost)

    subagent_costs = _collect_attributions(trace)

    return Diagnosis(
        session_id=trace.session_id,
        findings=findings,
        inflection_turn=inflection_turn,
        patches=[],
        total_cost_usd=total_cost,
        waste_cost_usd=round(waste_cost, 4),
        analysed_at=datetime.now(UTC),
        subagent_costs=subagent_costs,
    )
