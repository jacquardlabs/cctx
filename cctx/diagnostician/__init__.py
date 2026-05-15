"""Autopsy diagnostician — public entry point.

run(trace) -> Diagnosis
  Runs all three pattern classifiers, detects inflection turn,
  patches cost attribution for stale_context findings, and returns
  a Diagnosis with patches=[].

The Recommender (cctx.recommender.claude_md) populates patches.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from cctx.diagnostician import inflection
from cctx.diagnostician.patterns import retry_loop, scope_creep, stale_context
from cctx.models import Diagnosis, Finding, FindingKind

if TYPE_CHECKING:
    from cctx.models import SessionTrace

UTC = timezone.utc

# Input token price per token by model prefix (USD)
_INPUT_PRICE_PER_MTOK: dict[str, float] = {
    "claude-opus-4":   15.0,
    "claude-sonnet-4":  3.0,
    "claude-haiku-4":   0.8,
}


def _price_per_tok(model: str | None) -> float:
    for prefix, mtok in _INPUT_PRICE_PER_MTOK.items():
        if model and model.startswith(prefix):
            return mtok / 1_000_000
    return 3.0 / 1_000_000  # default: Sonnet rate


def _patch_costs(findings: list[Finding], model: str | None) -> list[Finding]:
    price = _price_per_tok(model)
    result = []
    for f in findings:
        if f.kind is FindingKind.STALE_CONTEXT:
            tt = f.evidence.get("total_token_turns", 0)
            f = dataclasses.replace(f, cost_usd=round(tt * price, 4))
        result.append(f)
    return result


def _compute_total_cost(trace: SessionTrace, model: str | None) -> float:
    """Approximate total session cost including cache reads and writes.

    Billing rates relative to base input price:
      cache_read:  ×0.10  (read from prompt cache)
      cache_write: ×1.25  (write to prompt cache, both 5-min and 1-hr TTLs)
    """
    price = _price_per_tok(model)
    total = 0.0
    for turn in trace.turns:
        if turn.usage is not None:
            total += turn.usage.input_tokens * price
            total += turn.usage.cache_read * price * 0.1
            cache_writes = turn.usage.cache_creation_5m + turn.usage.cache_creation_1h
            total += cache_writes * price * 1.25
    return round(total, 4)


def run(trace: SessionTrace) -> Diagnosis:
    """Diagnose a single SessionTrace. Returns Diagnosis with patches=[]."""
    findings: list[Finding] = [
        *retry_loop.classify(trace),
        *scope_creep.classify(trace),
        *stale_context.classify(trace),
    ]
    findings.sort(key=lambda f: f.first_turn)

    inflection_turn = inflection.detect(findings)
    findings = _patch_costs(findings, trace.primary_model)

    total_cost = _compute_total_cost(trace, trace.primary_model)
    waste_cost = sum(f.cost_usd for f in findings if f.cost_usd is not None)
    # Waste cannot exceed total session cost — cap as a logical invariant.
    waste_cost = min(waste_cost, total_cost)

    return Diagnosis(
        session_id=trace.session_id,
        findings=findings,
        inflection_turn=inflection_turn,
        patches=[],
        total_cost_usd=total_cost,
        waste_cost_usd=round(waste_cost, 4),
        analysed_at=datetime.now(UTC),
    )
