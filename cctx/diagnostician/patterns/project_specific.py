"""Project-specific pattern detector.

detect(pairs) -> list[ProjectPattern]

Finds (tool_name, failure_key, fix_key) triples that recur in 3+ sessions.
Bash normalization uses first 3 tokens for cross-session fuzzy matching
(intentionally looser than retry_loop). No LLM calls.

Unlike the single-session classifiers, this is cross-session and emits
ProjectPattern objects (not Finding objects), so it populates no
Finding.evidence dict. The recommender turns each ProjectPattern directly
into a PROJECT_PATTERN Patch (see recommender/claude_md.py).
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING

from cctx.models import ProjectPattern
from cctx.pricing import price_per_tok

if TYPE_CHECKING:
    from cctx.models import Diagnosis, SessionTrace, ToolResult

MIN_SESSIONS = 3
FIX_WINDOW = 10  # turns after last failure to search for the fix


def _normalize_key(tool_name: str, tool_input: dict) -> str:
    match tool_name:
        case "Bash":
            tokens = tool_input.get("command", "").strip().split()
            return " ".join(tokens[:3])
        case "Edit" | "Read" | "Write":
            return tool_input.get("file_path", "")
        case "Grep" | "Glob":
            return tool_input.get("pattern", "")
        case _:
            return json.dumps(tool_input, sort_keys=True)


def _is_error(result: ToolResult) -> bool:
    if result.is_error:
        return True
    c = result.content
    return c.startswith("Error:") or c.startswith("error:") or c.startswith("FAILED")


def _find_pairs(trace: SessionTrace) -> list[dict]:
    """Find failure/fix pairs within one session."""
    result_map: dict[str, ToolResult] = {}
    for turn in trace.turns:
        for tr in turn.tool_results:
            result_map[tr.tool_use_id] = tr

    records = []
    for turn in trace.turns:
        if turn.role != "assistant":
            continue
        for tu in turn.tool_uses:
            result = result_map.get(tu.tool_use_id)
            if result is None:
                continue
            key = _normalize_key(tu.tool_name, tu.tool_input)
            records.append({
                "tool_name": tu.tool_name,
                "key": key,
                "turn": turn.turn_number,
                "is_error": _is_error(result),
            })

    groups: dict[tuple, list] = defaultdict(list)
    for r in records:
        groups[(r["tool_name"], r["key"])].append(r)

    found: list[dict] = []
    seen_pairs: set[tuple] = set()

    for (tool_name, failure_key), group in groups.items():
        errors = [r for r in group if r["is_error"]]
        if len(errors) < 2:
            continue

        first_err_turn = errors[0]["turn"]
        last_err_turn = errors[-1]["turn"]

        intervening = any(
            r for r in group
            if not r["is_error"] and first_err_turn < r["turn"] < last_err_turn
        )
        if intervening:
            continue

        fix = next(
            (
                r for r in records
                if r["tool_name"] == tool_name
                and not r["is_error"]
                and r["key"] != failure_key
                and last_err_turn < r["turn"] <= last_err_turn + FIX_WINDOW
            ),
            None,
        )
        if fix is None:
            continue

        pair_key = (tool_name, failure_key, fix["key"])
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        found.append({
            "tool_name": tool_name,
            "failure_key": failure_key,
            "fix_key": fix["key"],
            "first_failure_turn": first_err_turn,
            "fix_turn": fix["turn"],
        })

    return found


def _compute_waste(trace: SessionTrace, first_failure_turn: int, fix_turn: int) -> float:
    # Priced at the session's own date so an announced rate change applies to the
    # sessions it actually covers, not to whenever the autopsy runs.
    on = trace.start_time.date() if trace.start_time else None
    price = price_per_tok(trace.primary_model, on=on)
    total = 0.0
    for turn in trace.turns:
        if (
            turn.role == "assistant"
            and first_failure_turn <= turn.turn_number <= fix_turn
            and turn.usage is not None
        ):
            total += turn.usage.input_tokens * price
    return round(total, 4)


def detect(pairs: list[tuple[Diagnosis, SessionTrace]]) -> list[ProjectPattern]:
    """Detect recurring failure/fix patterns across sessions."""
    session_records: list[dict] = []
    for _diagnosis, trace in pairs:
        for p in _find_pairs(trace):
            session_records.append({
                "session_id": trace.session_id,
                "tool_name": p["tool_name"],
                "failure_key": p["failure_key"],
                "fix_key": p["fix_key"],
                "first_failure_turn": p["first_failure_turn"],
                "fix_turn": p["fix_turn"],
                "trace": trace,
            })

    groups: dict[tuple, list] = defaultdict(list)
    for r in session_records:
        groups[(r["tool_name"], r["failure_key"], r["fix_key"])].append(r)

    result: list[ProjectPattern] = []
    for (tool_name, failure_key, fix_key), records in groups.items():
        seen: dict[str, dict] = {}
        for r in records:
            if r["session_id"] not in seen:
                seen[r["session_id"]] = r

        if len(seen) < MIN_SESSIONS:
            continue

        unique = list(seen.values())
        wasted = [r["fix_turn"] - r["first_failure_turn"] for r in unique]
        avg_wasted_turns = sum(wasted) / len(wasted)
        total_waste_usd = sum(
            _compute_waste(r["trace"], r["first_failure_turn"], r["fix_turn"])
            for r in unique
        )

        result.append(ProjectPattern(
            tool_name=tool_name,
            failure_key=failure_key,
            fix_key=fix_key,
            session_count=len(seen),
            avg_wasted_turns=round(avg_wasted_turns, 1),
            total_waste_usd=round(total_waste_usd, 4),
            example_sessions=sorted(r["session_id"] for r in unique)[:3],
        ))

    return result
