"""Stale-context classifier.

Detects large tool results that remained in context well past their last
reference. Uses 3-gram overlap to detect references. Compaction-aware:
staleness resets to zero at compaction events.

Thresholds (per spec):
  T_size  = 2_000 tokens (minimum size to be a candidate)
  N_stale = 5 turns after last reference before "stale"
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from cctx.models import Confidence, Finding, FindingKind, Severity

if TYPE_CHECKING:
    from cctx.models import SessionTrace, Turn

T_SIZE = 2_000   # token threshold
N_STALE = 5      # turns before officially stale
STALE_HIGH_THRESHOLD = 500_000  # token-turns above which → HIGH


def _estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)


def _make_3grams(text: str) -> set[tuple[str, ...]]:
    words = text.lower().split()
    if len(words) < 3:
        return set()
    return {tuple(words[i : i + 3]) for i in range(len(words) - 2)}


def _is_compaction(turn: Turn) -> bool:
    return turn.role == "system" and "compact" in turn.text.lower()


def _classify_impl(trace: SessionTrace) -> list[Finding]:
    # Identify large tool results and their first_seen_turn
    candidates: list[dict] = []  # {uid, tool_name, content, tokens, first_seen_turn}

    for turn in trace.turns:
        for tr in turn.tool_results:
            tokens = tr.token_count if tr.token_count > 0 else _estimate_tokens(tr.content)
            if tokens < T_SIZE:
                continue
            candidates.append({
                "uid": tr.tool_use_id,
                "tool_name": tr.tool_name,
                "content": tr.content,
                "tokens": tokens,
                "first_seen_turn": turn.turn_number,
                "content_3grams": _make_3grams(tr.content),
            })

    if not candidates:
        return []

    # Find the turn number of any compaction events
    compaction_turns: set[int] = {
        t.turn_number for t in trace.turns if _is_compaction(t)
    }

    last_turn_number = max((t.turn_number for t in trace.turns), default=0)

    stale_items: list[dict] = []

    for cand in candidates:
        first_seen = cand["first_seen_turn"]
        content_3grams = cand["content_3grams"]

        # Find last assistant turn with a 3-gram reference to this content
        last_ref = first_seen  # at minimum, the turn it appeared in counts as a reference
        for turn in trace.turns:
            if turn.turn_number <= first_seen:
                continue
            if turn.role != "assistant":
                continue
            turn_3grams = _make_3grams(turn.text)
            if content_3grams & turn_3grams:
                last_ref = turn.turn_number

        # Check for compaction between first_seen and end: if any, skip this item
        if any(ct > first_seen for ct in compaction_turns):
            continue

        turns_stale = last_turn_number - last_ref
        if turns_stale <= N_STALE:
            continue

        token_turns = cand["tokens"] * turns_stale
        stale_items.append({
            "tool_name": cand["tool_name"],
            "content_tokens": cand["tokens"],
            "first_seen_turn": first_seen,
            "last_referenced_turn": last_ref,
            "turns_stale": turns_stale,
            "token_turns": token_turns,
        })

    if not stale_items:
        return []

    total_token_turns = sum(item["token_turns"] for item in stale_items)
    level = Confidence.HIGH if total_token_turns > STALE_HIGH_THRESHOLD else Confidence.MEDIUM
    severity = Severity.HIGH if total_token_turns > STALE_HIGH_THRESHOLD else Severity.MEDIUM

    # first_turn = when the first item became officially stale
    first_stale = min(
        item["last_referenced_turn"] + N_STALE for item in stale_items
    )

    # Summary describes the worst offender
    worst = max(stale_items, key=lambda i: i["token_turns"])
    tokens_k = worst["content_tokens"] // 1000
    summary = (
        f"{tokens_k}K-token {worst['tool_name']} result stale "
        f"{worst['turns_stale']} turns "
        f"(~{total_token_turns:,} token-turns)"
    )

    return [Finding(
        kind=FindingKind.STALE_CONTEXT,
        severity=severity,
        confidence=level,
        first_turn=first_stale,
        last_turn=last_turn_number,
        evidence={"stale_items": stale_items, "total_token_turns": total_token_turns},
        cost_usd=None,
        summary=summary,
    )]


def classify(trace: SessionTrace) -> list[Finding]:
    try:
        return _classify_impl(trace)
    except Exception:
        return []
