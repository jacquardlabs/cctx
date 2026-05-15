"""CSV exporter — one row per turn, one header row."""
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
]


def export_turn_rows(diagnosis: Diagnosis, trace: SessionTrace) -> list[dict[str, str]]:
    finding_at: dict[int, list[str]] = {}
    for f in diagnosis.findings:
        finding_at.setdefault(f.first_turn, []).append(f.kind.value)

    rows = []
    for turn in trace.turns:
        input_tokens = turn.usage.input_tokens if turn.usage else 0
        if turn.usage:
            p = _price_per_tok(turn.model)
            cost_usd = (
                turn.usage.input_tokens * p
                + turn.usage.cache_read * p * 0.1
                + (turn.usage.cache_creation_5m + turn.usage.cache_creation_1h) * p * 1.25
            )
        else:
            cost_usd = 0.0
        is_inflection = turn.turn_number == diagnosis.inflection_turn
        rows.append({
            "session_id": trace.session_id,
            "turn_number": str(turn.turn_number),
            "role": turn.role,
            "model": turn.model or "",
            "input_tokens": str(input_tokens),
            "cost_usd": f"{cost_usd:.6f}",
            "tool_names": ",".join(tu.tool_name for tu in turn.tool_uses),
            "finding_kinds": ",".join(finding_at.get(turn.turn_number, [])),
            "is_inflection_turn": "true" if is_inflection else "false",
        })
    return rows


def write(
    diagnoses: list[tuple[Diagnosis, SessionTrace]],
    out: IO[str],
) -> None:
    writer = _csv.DictWriter(out, fieldnames=COLUMNS)
    writer.writeheader()
    for diagnosis, trace in diagnoses:
        writer.writerows(export_turn_rows(diagnosis, trace))
