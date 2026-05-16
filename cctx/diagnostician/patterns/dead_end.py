"""Dead-end exploration classifier.

Detects when the assistant pursues an approach, hits repeated failures, and
then pivots to a different tool or input — indicating wasted exploration cost.

Signal: a run of N_FAIL_MIN consecutive errors on the same (tool, key),
followed by the assistant switching to a different tool or a different
canonicalized input. The pivot is what distinguishes dead-end from retry_loop;
retry_loop keeps hitting the same wall with no change; dead-end is when it
eventually gives up and tries something else.

Compaction-aware: a compaction event (turn.text starts with "<context_window")
resets the error run counter — prior state is gone.

Thresholds:
  N_FAIL_MIN = 2  — minimum consecutive errors before a backtrack counts
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from cctx.models import Confidence, Finding, FindingKind, Severity

if TYPE_CHECKING:
    from cctx.models import SessionTrace, ToolResult

N_FAIL_MIN = 2


def _canon_key(tool_name: str, tool_input: dict) -> str:
    match tool_name:
        case "Bash":
            return tool_input.get("command", "").strip()
        case "Read" | "Write" | "Edit":
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


def _classify_impl(trace: SessionTrace) -> list[Finding]:
    # Build tool_use_id → ToolResult map
    result_map: dict[str, ToolResult] = {}
    for turn in trace.turns:
        for tr in turn.tool_results:
            result_map[tr.tool_use_id] = tr

    dead_ends: list[dict] = []

    # Walk assistant turns in order, tracking current error run
    # State: (tool_name, key, error_count, first_error_turn)
    run_tool: str | None = None
    run_key: str | None = None
    run_count: int = 0
    run_first_turn: int = 0

    for turn in trace.turns:
        # Compaction resets state
        if turn.text.startswith("<context_window"):
            run_tool = run_key = None
            run_count = 0
            continue

        if turn.role != "assistant":
            continue

        for tu in turn.tool_uses:
            result = result_map.get(tu.tool_use_id)
            if result is None:
                continue

            key = _canon_key(tu.tool_name, tu.tool_input)
            errored = _is_error(result)

            if errored:
                if tu.tool_name == run_tool and key == run_key:
                    # Continuing the same failing approach
                    run_count += 1
                else:
                    # New failing approach — reset
                    run_tool = tu.tool_name
                    run_key = key
                    run_count = 1
                    run_first_turn = turn.turn_number
            else:
                # Successful call — check if it's a pivot away from an error run
                if run_count >= N_FAIL_MIN:
                    pivoted = tu.tool_name != run_tool or key != run_key
                    if pivoted:
                        dead_ends.append({
                            "failed_tool": run_tool,
                            "failed_key": run_key,
                            "fail_count": run_count,
                            "first_fail_turn": run_first_turn,
                            "pivot_turn": turn.turn_number,
                            "pivot_tool": tu.tool_name,
                        })
                # Reset — success ends the run
                run_tool = run_key = None
                run_count = 0

    if not dead_ends:
        return []

    total_fails = sum(d["fail_count"] for d in dead_ends)
    all_first = min(d["first_fail_turn"] for d in dead_ends)
    all_last = max(d["pivot_turn"] for d in dead_ends)
    severity = Severity.HIGH if total_fails >= 5 else Severity.MEDIUM

    worst = max(dead_ends, key=lambda d: d["fail_count"])
    label = worst["failed_key"][:50]
    summary = (
        f"{worst['failed_tool']}({label!r}) failed {worst['fail_count']}× "
        f"(turns {worst['first_fail_turn']}–{worst['pivot_turn']}), then pivoted"
    )
    if len(dead_ends) > 1:
        summary += f" (+{len(dead_ends) - 1} other dead-end(s))"

    return [Finding(
        kind=FindingKind.DEAD_END,
        severity=severity,
        confidence=Confidence.HIGH,
        first_turn=all_first,
        last_turn=all_last,
        evidence={"dead_ends": dead_ends, "total_fails": total_fails},
        cost_usd=None,
        summary=summary,
    )]


def classify(trace: SessionTrace) -> list[Finding]:
    try:
        return _classify_impl(trace)
    except Exception:
        return []
