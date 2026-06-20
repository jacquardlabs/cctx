"""Retry-loop classifier.

Detects repeated identical-failing tool calls with no intervening successful
fix. One Finding per session — all loops bundled into a single Finding with
all occurrences in evidence.

Evidence (Finding.evidence, kind=RETRY_LOOP):
    occurrences
    loop_length
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING

from cctx.models import Confidence, Finding, FindingKind, Severity

if TYPE_CHECKING:
    from cctx.models import SessionTrace, ToolResult


def _similarity_key(tool_name: str, tool_input: dict) -> str:
    match tool_name:
        case "Bash":
            return tool_input.get("command", "").strip()
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
    return (
        c.startswith("Error:")
        or c.startswith("error:")
        or c.startswith("FAILED")
    )


def classify(trace: SessionTrace) -> list[Finding]:
    # Build tool_use_id → (ToolResult, turn_number) map
    result_map: dict[str, tuple[ToolResult, int]] = {}
    for turn in trace.turns:
        for tr in turn.tool_results:
            result_map[tr.tool_use_id] = (tr, turn.turn_number)

    # Collect all tool calls with their error status
    # Each entry: (tool_name, key, turn_number, is_error, tool_use_id)
    Record = tuple[str, str, int, bool, str]
    records: list[Record] = []
    for turn in trace.turns:
        if turn.role != "assistant":
            continue
        for tu in turn.tool_uses:
            pair = result_map.get(tu.tool_use_id)
            if pair is None:
                continue
            result, _ = pair
            key = _similarity_key(tu.tool_name, tu.tool_input)
            records.append((tu.tool_name, key, turn.turn_number, _is_error(result), tu.tool_use_id))

    # Group by (tool_name, key)
    groups: dict[tuple[str, str], list[Record]] = defaultdict(list)
    for rec in records:
        groups[(rec[0], rec[1])].append(rec)

    loop_occurrences: list[dict] = []

    for (tool_name, key), group in groups.items():
        error_recs = [r for r in group if r[3]]
        if len(error_recs) < 2:
            continue

        first_err_turn = error_recs[0][2]
        last_err_turn = error_recs[-1][2]

        # Check for any successful call between the first and last error
        intervening_success = any(
            r for r in group
            if not r[3] and first_err_turn < r[2] < last_err_turn
        )
        if intervening_success:
            continue

        loop_occurrences.append({
            "tool_name": tool_name,
            "key": key,
            "error_recs": error_recs,
        })

    if not loop_occurrences:
        return []

    # Flatten all error records and build evidence
    all_errors: list[Record] = sorted(
        (r for occ in loop_occurrences for r in occ["error_recs"]),
        key=lambda r: r[2],
    )

    loop_length = len(all_errors)
    # first_turn = turn of the second failing call (loop established here)
    second_errors = []
    for occ in loop_occurrences:
        if len(occ["error_recs"]) >= 2:
            second_errors.append(occ["error_recs"][1][2])
    first_turn = min(second_errors)
    last_turn = max(r[2] for r in all_errors)

    severity = Severity.HIGH if loop_length >= 4 else Severity.MEDIUM

    evidence_occurrences = []
    for r in all_errors:
        result, _ = result_map[r[4]]
        evidence_occurrences.append({
            "turn": r[2],
            "key": r[1],
            "call": r[0],
            "error": result.content[:120],
        })

    # Summary: describe the first loop
    first_occ = loop_occurrences[0]
    first_err = first_occ["error_recs"]
    tool_label = f"{first_occ['tool_name']}({first_occ['key'][:40]})"
    summary = f"{tool_label} failed {loop_length}× between turns {first_err[0][2]}–{last_turn}"

    return [Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=severity,
        confidence=Confidence.HIGH,
        first_turn=first_turn,
        last_turn=last_turn,
        evidence={"occurrences": evidence_occurrences, "loop_length": loop_length},
        cost_usd=None,
        summary=summary,
    )]


