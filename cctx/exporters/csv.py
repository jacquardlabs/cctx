"""CSV exporter — one row per turn, one header row.

Rows cover the root session *and* every subagent at every depth (DFS order,
matching `Diagnosis.subagent_costs`). Row identity is `(session_id,
turn_number)` — turn numbers restart at 1 in each subagent trace. Filtering
`depth == 0` recovers the root-only table this exporter emitted before #194.
"""
from __future__ import annotations

import csv as _csv
from typing import IO, TYPE_CHECKING

from cctx.pricing import price_per_tok as _price_per_tok

if TYPE_CHECKING:
    from cctx.models import Diagnosis, SessionTrace

COLUMNS = [
    "session_id",
    "turn_number",
    "role",
    "model",
    "input_tokens",
    "cost_usd",
    "tool_names",
    "finding_kinds",
    "is_inflection_turn",
    # Dispatch identity (#194). Appended, so positional consumers of the
    # original nine keep working.
    "depth",
    "parent_session_id",
    "dispatching_tool_use_id",
    "root_dispatch_tool_use_id",
]


def export_turn_rows(diagnosis: Diagnosis, trace: SessionTrace) -> list[dict[str, str]]:
    # Keyed by session, not bare turn number: turn 3 of a subagent is not turn 3
    # of the root. Finding.session_id is None for root findings.
    finding_at: dict[tuple[str, int], list[str]] = {}
    for f in diagnosis.findings:
        key = (f.session_id or trace.session_id, f.first_turn)
        finding_at.setdefault(key, []).append(f.kind.value)

    # Dispatch identity comes from the Diagnosis rather than being recomputed
    # off the trace, so CSV's join key can't drift from JSON's.
    dispatch_by_sid = {
        a.session_id: a.dispatching_tool_use_id or ""
        for a in diagnosis.subagent_costs
    }

    rows: list[dict[str, str]] = []

    def _walk(t: SessionTrace, depth: int, root_dispatch: str) -> None:
        dispatching = dispatch_by_sid.get(t.session_id, "") if depth else ""
        for turn in t.turns:
            input_tokens = turn.usage.input_tokens if turn.usage else 0
            if turn.usage:
                p = _price_per_tok(
                    turn.model,
                    speed=turn.usage.speed,
                    on=turn.timestamp.date() if turn.timestamp else None,
                )
                cost_usd = (
                    turn.usage.input_tokens * p
                    + turn.usage.cache_read * p * 0.1
                    + (turn.usage.cache_creation_5m + turn.usage.cache_creation_1h) * p * 1.25
                )
            else:
                cost_usd = 0.0
            # inflection_turn is detected on root findings only — a subagent
            # turn sharing that number is not the inflection point.
            is_inflection = depth == 0 and turn.turn_number == diagnosis.inflection_turn
            rows.append({
                "session_id": t.session_id,
                "turn_number": str(turn.turn_number),
                "role": turn.role,
                "model": turn.model or "",
                "input_tokens": str(input_tokens),
                "cost_usd": f"{cost_usd:.6f}",
                "tool_names": ",".join(tu.tool_name for tu in turn.tool_uses),
                "finding_kinds": ",".join(finding_at.get((t.session_id, turn.turn_number), [])),
                "is_inflection_turn": "true" if is_inflection else "false",
                "depth": str(depth),
                "parent_session_id": t.parent_session_id or "",
                "dispatching_tool_use_id": dispatching,
                "root_dispatch_tool_use_id": root_dispatch,
            })
        for child in t.subagents:
            # Depth-1 dispatches seed the rollup key; deeper ones inherit it, so
            # a whole subtree groups under the top-level dispatch that spawned it.
            child_dispatch = dispatch_by_sid.get(child.session_id, "")
            _walk(child, depth + 1, child_dispatch if depth == 0 else root_dispatch)

    _walk(trace, 0, "")
    return rows


def write(
    diagnoses: list[tuple[Diagnosis, SessionTrace]],
    out: IO[str],
) -> None:
    writer = _csv.DictWriter(out, fieldnames=COLUMNS)
    writer.writeheader()
    for diagnosis, trace in diagnoses:
        writer.writerows(export_turn_rows(diagnosis, trace))
