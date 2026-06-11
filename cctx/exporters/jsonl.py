"""JSONL exporter — one JSON object per session line."""
from __future__ import annotations

import json
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from cctx.models import Diagnosis, SessionTrace


def export_diagnosis(
    diagnosis: Diagnosis,
    trace: SessionTrace,
    *,
    include_content: bool = True,
) -> str:
    findings = []
    for f in diagnosis.findings:
        d: dict[str, object] = {
            "kind": f.kind.value,
            "severity": f.severity.value,
            "confidence": f.confidence.value,
            "first_turn": f.first_turn,
            "last_turn": f.last_turn,
            "cost_usd": f.cost_usd,
        }
        if include_content:
            d["summary"] = f.summary
        findings.append(d)

    patches = []
    for p in diagnosis.patches:
        d = {
            "target_file": p.target_file,
            "finding_kind": p.finding_kind.value,
            "description": p.description,
        }
        if include_content:
            d["evidence_summary"] = p.evidence_summary
        patches.append(d)

    obj = {
        "session_id": diagnosis.session_id,
        "analysed_at": diagnosis.analysed_at.isoformat(),
        "total_cost_usd": diagnosis.total_cost_usd,
        "waste_cost_usd": diagnosis.waste_cost_usd,
        "inflection_turn": diagnosis.inflection_turn,
        "finding_count": len(diagnosis.findings),
        "findings": findings,
        "patches": patches,
        "turn_count": len(trace.turns),
        "model": trace.primary_model,
    }
    obj["subagent_costs"] = [
        {
            "session_id": a.session_id,
            "label":      a.label,
            "cost_usd":   a.total_cost_usd,
            "depth":      a.depth,
            "model":      a.model,
        }
        for a in diagnosis.subagent_costs
    ]
    return json.dumps(obj)


def write(
    diagnoses: list[tuple[Diagnosis, SessionTrace]],
    out: IO[str],
    *,
    include_content: bool = True,
) -> None:
    for diagnosis, trace in diagnoses:
        out.write(export_diagnosis(diagnosis, trace, include_content=include_content) + "\n")
