"""Exploration-thrash classifier.

Detects when the assistant circles with repeated read/search tool calls
instead of making progress — high ratio of read-only tools to write/execute
tools in a window, or repeated identical discovery commands, with no file
edits or test runs in N consecutive turns.

Signals:
  1. Sliding window of WINDOW_SIZE consecutive assistant turns where ≥ 80%
     of tool calls are read-only and no Write/Edit appears.
  2. Any (tool_name, key) read-only pair called ≥ REPEAT_THRESHOLD times
     across the full session.

Evidence (Finding.evidence, kind=EXPLORATION_THRASH):
    thrash_windows
    repeated_reads
"""
from __future__ import annotations

import json
from collections import Counter
from typing import TYPE_CHECKING

from cctx.models import Confidence, Finding, FindingKind, Severity

if TYPE_CHECKING:
    from cctx.models import SessionTrace

WINDOW_SIZE = 6
READ_RATIO_THRESHOLD = 0.80
REPEAT_THRESHOLD = 3

_READ_TOOLS = frozenset({"Read", "Grep", "Glob"})
_WRITE_TOOLS = frozenset({"Write", "Edit", "NotebookEdit"})

_READ_BASH_PREFIXES = (
    "ls",
    "find",
    "cat",
    "head",
    "tail",
    "grep",
    "rg",
    "ag",
    "wc",
    "file",
    "stat",
    "echo",
    "pwd",
    "which",
    "type",
    "less",
    "git log",
    "git diff",
    "git show",
    "git status",
    "git blame",
)


def _is_read_only(tool_name: str, tool_input: dict) -> bool:
    if tool_name in _READ_TOOLS:
        return True
    if tool_name in _WRITE_TOOLS:
        return False
    if tool_name == "Bash":
        cmd = tool_input.get("command", "").lstrip()
        return any(cmd.startswith(p) for p in _READ_BASH_PREFIXES)
    return False


def _tool_key(tool_name: str, tool_input: dict) -> str:
    """Canonical key for deduplication."""
    match tool_name:
        case "Bash":
            return tool_input.get("command", "").strip()
        case "Read" | "Write" | "Edit":
            return tool_input.get("file_path", "")
        case "Grep" | "Glob":
            return tool_input.get("pattern", "")
        case _:
            return json.dumps(tool_input, sort_keys=True)


def classify(trace: SessionTrace) -> list[Finding]:
    # Only look at assistant turns with tool calls
    active_turns = [
        t for t in trace.turns
        if t.role == "assistant" and t.tool_uses
    ]

    thrash_windows: list[dict] = []

    # Sliding window detection — requires at least WINDOW_SIZE active turns
    for i in range(max(0, len(active_turns) - WINDOW_SIZE + 1)):
        window = active_turns[i : i + WINDOW_SIZE]
        all_calls = [
            (tu.tool_name, tu.tool_input)
            for t in window
            for tu in t.tool_uses
        ]
        if not all_calls:
            continue
        read_count = sum(
            1 for name, inp in all_calls if _is_read_only(name, inp)
        )
        ratio = read_count / len(all_calls)
        has_write = any(name in _WRITE_TOOLS for name, _ in all_calls)

        if ratio >= READ_RATIO_THRESHOLD and not has_write:
            # Avoid double-counting overlapping windows that cover the same turns
            if (
                thrash_windows
                and thrash_windows[-1]["last_turn"] >= window[0].turn_number
            ):
                continue
            thrash_windows.append({
                "first_turn": window[0].turn_number,
                "last_turn": window[-1].turn_number,
                "read_ratio": round(ratio, 2),
                "total_calls": len(all_calls),
            })

    # Repeated identical reads
    read_call_counts: Counter[str] = Counter()
    read_call_turns: dict[str, list[int]] = {}
    for turn in trace.turns:
        if turn.role != "assistant":
            continue
        for tu in turn.tool_uses:
            if _is_read_only(tu.tool_name, tu.tool_input):
                key = f"{tu.tool_name}:{_tool_key(tu.tool_name, tu.tool_input)}"
                read_call_counts[key] += 1
                read_call_turns.setdefault(key, []).append(turn.turn_number)

    repeated_reads: list[dict] = []
    for key, count in read_call_counts.items():
        if count >= REPEAT_THRESHOLD:
            tool_name, _, call_key = key.partition(":")
            repeated_reads.append({
                "tool_name": tool_name,
                "key": call_key[:60],
                "count": count,
                "turns": read_call_turns[key],
            })

    if not thrash_windows and not repeated_reads:
        return []

    severity = Severity.HIGH if thrash_windows else Severity.MEDIUM
    confidence = Confidence.MEDIUM

    parts = []
    if thrash_windows:
        parts.append(
            f"{len(thrash_windows)} exploration thrash window"
            f"{'s' if len(thrash_windows) > 1 else ''} "
            f"(turns {thrash_windows[0]['first_turn']}–{thrash_windows[-1]['last_turn']}, "
            f"{thrash_windows[0]['read_ratio']:.0%} read-only)"
        )
    if repeated_reads:
        worst = max(repeated_reads, key=lambda r: r["count"])
        parts.append(
            f"{worst['tool_name']}({worst['key']!r}) called {worst['count']}× identically"
        )
    summary = "; ".join(parts)

    all_first = min(
        [w["first_turn"] for w in thrash_windows]
        + [r["turns"][0] for r in repeated_reads]
    )
    all_last = max(
        [w["last_turn"] for w in thrash_windows]
        + [r["turns"][-1] for r in repeated_reads]
    )

    return [Finding(
        kind=FindingKind.EXPLORATION_THRASH,
        severity=severity,
        confidence=confidence,
        first_turn=all_first,
        last_turn=all_last,
        evidence={
            "thrash_windows": thrash_windows,
            "repeated_reads": repeated_reads,
        },
        cost_usd=None,
        summary=summary,
    )]


