"""Cache-hygiene classifier.

Detects sessions with low KV-cache hit rates and identifies the likely cause
of the miss. A cache miss costs ~10× more than a cache hit on Sonnet
($3/MTok vs $0.30/MTok), making this one of the highest-value findings.

Thresholds:
  MIN_TOTAL_TOKENS         = 5_000  — skip tiny sessions
  HIT_RATE_THRESHOLD       = 0.50   — below this → fire finding
  HALF_DROP_THRESHOLD      = 0.20   — early_rate - late_rate drop to flag as degrading
  WASTE_BASELINE_HIT_RATE  = 0.50   — economic baseline for cost estimation, kept
                                      separate from HIT_RATE_THRESHOLD so retuning
                                      detection sensitivity doesn't silently move
                                      dollar output (diagnostician/__init__.py).
                                      Note: this waste is counterfactual (tokens
                                      that would have been cache hits at a healthy
                                      rate), not observed like other findings' cost.

Evidence (Finding.evidence, kind=CACHE_HYGIENE):
    overall_hit_rate
    early_hit_rate
    late_hit_rate
    total_tokens
    cause
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from cctx.diagnostician.patterns.compaction import is_compaction_turn
from cctx.models import Confidence, Finding, FindingKind, Severity

if TYPE_CHECKING:
    from cctx.models import SessionTrace, Turn

MIN_TOTAL_TOKENS = 5_000
HIT_RATE_THRESHOLD = 0.50
HALF_DROP_THRESHOLD = 0.20
WASTE_BASELINE_HIT_RATE = 0.50


def _hit_rate(turns: list[Turn]) -> float:
    total_in = sum(
        t.usage.input_tokens + t.usage.cache_read for t in turns if t.usage
    )
    total_cached = sum(t.usage.cache_read for t in turns if t.usage)
    return total_cached / total_in if total_in > 0 else 0.0


def _detect_cause(trace: SessionTrace, assistant_turns: list[Turn]) -> str | None:
    """Identify the most likely cause of low cache hit rate from JSONL signals."""

    # Compaction events invalidate the cache entirely.
    compaction_turns = [t for t in trace.turns if is_compaction_turn(t)]
    if compaction_turns:
        return (
            f"context compacted at turn {compaction_turns[0].turn_number}"
            " (cache invalidated)"
        )

    # Many tools loaded means the tool-definition prefix is large and unstable.
    if len(trace.tool_names_loaded) > 20:
        return (
            "large tool definition surface (>20 tools loaded)"
            " reduces prefix stability"
        )

    # No cached tokens on turn 1 with a non-trivial prompt suggests the
    # prompt prefix differs each session and cannot be cached.
    if assistant_turns and assistant_turns[0].usage:
        first = assistant_turns[0].usage
        if first.cache_read == 0 and first.input_tokens > 1000:
            return (
                "no cached tokens on turn 1"
                " — prompt prefix may not be stable across sessions"
            )

    return None


def classify(trace: SessionTrace) -> list[Finding]:
    assistant_turns = [t for t in trace.turns if t.role == "assistant" and t.usage]
    if not assistant_turns:
        return []

    total_tokens = sum(
        t.usage.input_tokens + t.usage.cache_read for t in assistant_turns
    )
    if total_tokens < MIN_TOTAL_TOKENS:
        return []

    overall_rate = _hit_rate(assistant_turns)
    if overall_rate >= HIT_RATE_THRESHOLD:
        return []

    # Split into halves to detect in-session degradation.
    mid = len(assistant_turns) // 2
    early_rate = _hit_rate(assistant_turns[:mid]) if mid > 0 else overall_rate
    late_rate = (
        _hit_rate(assistant_turns[mid:]) if mid < len(assistant_turns) else overall_rate
    )

    cause = _detect_cause(trace, assistant_turns)
    severity = Severity.HIGH if overall_rate < 0.25 else Severity.MEDIUM
    degrading = early_rate - late_rate > HALF_DROP_THRESHOLD

    summary_parts = [f"cache hit rate {overall_rate:.0%}"]
    if degrading:
        summary_parts.append(
            f"degraded from {early_rate:.0%} (first half)"
            f" to {late_rate:.0%} (second half)"
        )
    if cause:
        summary_parts.append(cause)

    return [
        Finding(
            kind=FindingKind.CACHE_HYGIENE,
            severity=severity,
            confidence=Confidence.MEDIUM,
            first_turn=assistant_turns[0].turn_number,
            last_turn=assistant_turns[-1].turn_number,
            evidence={
                "overall_hit_rate": round(overall_rate, 3),
                "early_hit_rate": round(early_rate, 3),
                "late_hit_rate": round(late_rate, 3),
                "total_tokens": total_tokens,
                "cause": cause,
            },
            cost_usd=None,
            summary="; ".join(summary_parts),
        )
    ]


