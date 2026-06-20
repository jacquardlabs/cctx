"""Compaction-event classifier.

Detects context-window compaction events and surfaces them as first-class
findings. Also attributes re-fetch waste: files read before compaction that
are read again after (token cost of the re-read attributed to the compaction).

Exported helpers:
  is_compaction_turn(turn) — canonical compaction predicate used by
    stale_context.py and dead_end.py (replaces their local implementations).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from cctx.models import Confidence, Finding, FindingKind, Severity

if TYPE_CHECKING:
    from cctx.models import SessionTrace, Turn


def is_compaction_turn(turn: Turn) -> bool:
    """True if this turn represents a context-window compaction event."""
    if turn.role == "system" and "compact" in turn.text.lower():
        return True
    return turn.text.startswith("<context_window")


def _classify_impl(trace: SessionTrace) -> list[Finding]:
    compaction_turns = [t for t in trace.turns if is_compaction_turn(t)]
    if not compaction_turns:
        return []

    first_compaction_turn = compaction_turns[0].turn_number

    # Build map of files read before first compaction: key → token_count
    pre_reads: dict[str, int] = {}
    for turn in trace.turns:
        if turn.turn_number >= first_compaction_turn:
            break
        for tu in turn.tool_uses:
            if tu.tool_name == "Read":
                fp = tu.tool_input.get("file_path", "")
                if not fp:
                    continue
                # Find matching tool result to get token count
                for tr in turn.tool_results:
                    if tr.tool_use_id == tu.tool_use_id:
                        toks = (
                            tr.token_count
                            if tr.token_count > 0
                            else len(tr.content.split()) * 4 // 3
                        )
                        pre_reads[f"Read:{fp}"] = toks

    # Detect re-fetches after compaction (first occurrence only per file)
    re_fetches: list[dict] = []
    for turn in trace.turns:
        if turn.turn_number <= first_compaction_turn:
            continue
        for tu in turn.tool_uses:
            if tu.tool_name == "Read":
                fp = tu.tool_input.get("file_path", "")
                key = f"Read:{fp}"
                if key in pre_reads:
                    re_fetches.append({
                        "tool_name": tu.tool_name,
                        "path": fp,
                        "turn": turn.turn_number,
                        "tokens": pre_reads[key],
                    })
                    del pre_reads[key]  # only flag first re-fetch per file

    total_refetch_tokens = sum(r["tokens"] for r in re_fetches)
    n_compactions = len(compaction_turns)
    compaction_turn_numbers = [t.turn_number for t in compaction_turns]

    severity = Severity.HIGH if re_fetches else Severity.LOW
    confidence = Confidence.HIGH

    parts = [
        f"{n_compactions} compaction event{'s' if n_compactions > 1 else ''} "
        f"(turn{'s' if n_compactions > 1 else ''} "
        f"{', '.join(str(n) for n in compaction_turn_numbers)})"
    ]
    if re_fetches:
        n_files = len(re_fetches)
        parts.append(
            f"{n_files} file{'s' if n_files > 1 else ''} re-fetched after compaction "
            f"(~{total_refetch_tokens:,} tokens)"
        )
    summary = "; ".join(parts)

    return [Finding(
        kind=FindingKind.COMPACTION,
        severity=severity,
        confidence=confidence,
        first_turn=compaction_turn_numbers[0],
        last_turn=compaction_turn_numbers[-1],
        evidence={
            "n_compactions": n_compactions,
            "compaction_turns": compaction_turn_numbers,
            "re_fetches": re_fetches,
            "total_refetch_tokens": total_refetch_tokens,
        },
        cost_usd=None,
        summary=summary,
    )]


def classify(trace: SessionTrace) -> list[Finding]:
    try:
        return _classify_impl(trace)
    except Exception:
        return []
