"""Tool-thrash classifier.

Detects repeated identical tool calls (same tool name + same canonicalized
input) within a session, regardless of whether they succeed or fail.

Distinct from retry_loop, which requires is_error on results. Tool-thrash
fires on successful repeated identical calls — the assistant calling
Read(file_path="x") five times is wasteful even if every call succeeds.

One Finding per session; all thrashing tools are bundled into a single
Finding with evidence listing each burst.

Thresholds:
  MIN_REPEATS = 3  — a tool must appear ≥ 3 times with identical input
  WINDOW      = 20 — calls must occur within a 20-turn window

Evidence (Finding.evidence, kind=TOOL_THRASH):
    bursts
    total_calls
    total_waste_tokens  — content tokens of repeat calls (all but the first
                          occurrence per key). Errored occurrences are excluded
                          from the count — those are retry_loop's domain, and
                          double-counting them would inflate waste_cost_usd.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING

from cctx.diagnostician.patterns.stale_context import _estimate_tokens
from cctx.models import Confidence, Finding, FindingKind, Severity

if TYPE_CHECKING:
    from cctx.models import SessionTrace, ToolResult

MIN_REPEATS = 3
WINDOW = 20


def _canon_key(tool_name: str, tool_input: dict) -> str:
    """Stable hashable key from tool name + inputs."""
    match tool_name:
        case "Bash":
            return f"Bash:{tool_input.get('command', '').strip()}"
        case "Read":
            return f"Read:{tool_input.get('file_path', '')}"
        case "Write" | "Edit":
            return f"{tool_name}:{tool_input.get('file_path', '')}"
        case "Grep" | "Glob":
            return f"{tool_name}:{tool_input.get('pattern', '')}"
        case _:
            return f"{tool_name}:{json.dumps(tool_input, sort_keys=True)}"


def classify(trace: SessionTrace) -> list[Finding]:
    result_map: dict[str, ToolResult] = {}
    for turn in trace.turns:
        for tr in turn.tool_results:
            result_map[tr.tool_use_id] = tr

    # Collect (turn_number, tool_name, canon_key, tool_use_id) for every tool call
    calls: list[tuple[int, str, str, str]] = []
    for turn in trace.turns:
        if turn.role != "assistant":
            continue
        for tu in turn.tool_uses:
            key = _canon_key(tu.tool_name, tu.tool_input)
            calls.append((turn.turn_number, tu.tool_name, key, tu.tool_use_id))

    if not calls:
        return []

    # Group by canon key; find groups with ≥ MIN_REPEATS within any WINDOW-turn span
    groups: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for turn_num, tool_name, key, tool_use_id in calls:
        groups[key].append((turn_num, tool_name, tool_use_id))

    bursts: list[dict] = []

    for key, occurrences in groups.items():
        if len(occurrences) < MIN_REPEATS:
            continue

        # Find the tightest window containing ≥ MIN_REPEATS calls
        turns = [o[0] for o in occurrences]
        tool_name = occurrences[0][1]

        # Sliding window over sorted turns
        for i in range(len(turns)):
            window_calls = [t for t in turns[i:] if t - turns[i] <= WINDOW]
            if len(window_calls) >= MIN_REPEATS:
                waste_tokens = 0
                for _, _, tool_use_id in occurrences[1:]:  # first call is legitimate
                    result = result_map.get(tool_use_id)
                    if result is None or result.is_error:
                        continue
                    waste_tokens += (
                        result.token_count if result.token_count > 0
                        else _estimate_tokens(result.content)
                    )
                bursts.append({
                    "tool_name": tool_name,
                    "key": key,
                    "count": len(occurrences),
                    "first_turn": turns[0],
                    "last_turn": turns[-1],
                    "waste_tokens": waste_tokens,
                })
                break  # one burst record per key

    if not bursts:
        return []

    # Build single Finding covering all bursts
    all_first = min(b["first_turn"] for b in bursts)
    all_last = max(b["last_turn"] for b in bursts)
    total_calls = sum(b["count"] for b in bursts)
    total_waste_tokens = sum(b["waste_tokens"] for b in bursts)
    severity = Severity.HIGH if total_calls >= 6 else Severity.MEDIUM

    # Summary: describe the most-repeated tool
    worst = max(bursts, key=lambda b: b["count"])
    label = worst["key"][:60]
    summary = f"{worst['tool_name']}({label!r}) called {worst['count']}× identically"
    if len(bursts) > 1:
        summary += f" (+{len(bursts) - 1} other tool(s))"

    return [Finding(
        kind=FindingKind.TOOL_THRASH,
        severity=severity,
        confidence=Confidence.HIGH,
        first_turn=all_first,
        last_turn=all_last,
        evidence={
            "bursts": bursts,
            "total_calls": total_calls,
            "total_waste_tokens": total_waste_tokens,
        },
        cost_usd=None,
        summary=summary,
    )]


