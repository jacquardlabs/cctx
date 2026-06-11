"""JSONL exporter — one JSON object per session line."""
from __future__ import annotations

import json
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from cctx.models import AggregateReport, Diagnosis, SessionTrace


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
        "subagent_costs": [
            {
                "session_id": a.session_id,
                "label":      a.label,
                "cost_usd":   a.total_cost_usd,
                "depth":      a.depth,
                "model":      a.model,
            }
            for a in diagnosis.subagent_costs
        ],
    }
    return json.dumps(obj)


def export_aggregate(report: AggregateReport) -> str:
    """Serialize an AggregateReport to a JSON string."""
    by_kind = {
        k.value: {
            "session_count": v.session_count,
            "total_waste_usd": v.total_waste_usd,
            "example_summaries": v.example_summaries,
        }
        for k, v in report.by_kind.items()
    }
    patches = [
        {
            "target_file": p.target_file,
            "finding_kind": p.finding_kind.value,
            "description": p.description,
            "evidence_summary": p.evidence_summary,
        }
        for p in report.patches
    ]
    project_patterns = [
        {
            "tool_name": pp.tool_name,
            "failure_key": pp.failure_key,
            "fix_key": pp.fix_key,
            "session_count": pp.session_count,
            "avg_wasted_turns": pp.avg_wasted_turns,
            "total_waste_usd": pp.total_waste_usd,
            "example_sessions": pp.example_sessions,
        }
        for pp in report.project_patterns
    ]
    obj = {
        "period_label": report.period_label,
        "sessions_analysed": report.sessions_analysed,
        "sessions_with_findings": report.sessions_with_findings,
        "total_cost_usd": report.total_cost_usd,
        "waste_cost_usd": report.waste_cost_usd,
        "by_kind": by_kind,
        "patches": patches,
        "project_patterns": project_patterns,
    }
    return json.dumps(obj)


def write(
    diagnoses: list[tuple[Diagnosis, SessionTrace]],
    out: IO[str],
    *,
    include_content: bool = True,
) -> None:
    for diagnosis, trace in diagnoses:
        out.write(export_diagnosis(diagnosis, trace, include_content=include_content) + "\n")
