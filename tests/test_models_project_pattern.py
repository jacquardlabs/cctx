"""Tests for M14 model additions."""
from __future__ import annotations


def test_project_pattern_instantiates():
    from cctx.models import ProjectPattern
    pp = ProjectPattern(
        tool_name="Bash",
        failure_key="pnpm install",
        fix_key="pnpm --filter app",
        session_count=3,
        avg_wasted_turns=5.0,
        total_waste_usd=1.50,
        example_sessions=["sess-1", "sess-2", "sess-3"],
    )
    assert pp.session_count == 3
    assert pp.tool_name == "Bash"


def test_aggregate_report_project_patterns_defaults_to_empty():
    from cctx.models import AggregateReport
    report = AggregateReport(
        period_label="last 7 days",
        sessions_analysed=3,
        sessions_with_findings=0,
        total_cost_usd=0.0,
        waste_cost_usd=0.0,
        by_kind={},
        patches=[],
    )
    assert report.project_patterns == []


def test_finding_kind_project_pattern_value():
    from cctx.models import KIND_LABEL, FindingKind
    assert FindingKind.PROJECT_PATTERN.value == "project_pattern"
    assert KIND_LABEL[FindingKind.PROJECT_PATTERN] == "PROJECT PATTERN"
