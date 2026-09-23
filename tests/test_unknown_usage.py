"""A token field that is not an int is unknown — never 0 tokens, never $0.00."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cctx import diagnostician
from cctx.exporters.jsonl import export_diagnosis
from cctx.parsers.claude_code import _parse_usage, parse_session

GOOD_ITERATION = {
    "input_tokens": 100,
    "output_tokens": 50,
    "cache_read_input_tokens": 10,
    "cache_creation": {"ephemeral_5m_input_tokens": 5, "ephemeral_1h_input_tokens": 0},
}


@pytest.mark.parametrize(
    "raw",
    [
        {"input_tokens": "[SCRUBBED]", "output_tokens": 50},
        {"input_tokens": 100, "output_tokens": 1.5},
        {"input_tokens": 100, "output_tokens": True},
        {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": None},
        {"input_tokens": 100, "output_tokens": 50,
         "cache_creation": {"ephemeral_5m_input_tokens": "[SCRUBBED]"}},
        {"input_tokens": 100, "output_tokens": 50, "cache_creation": "[SCRUBBED]"},
    ],
    ids=["str", "float", "bool", "none", "nested-cache", "cache-not-dict"],
)
def test_non_int_top_level_field_is_unknown(raw: dict) -> None:
    assert _parse_usage(raw) is None


@pytest.mark.parametrize(
    "bad_iteration",
    [
        {**GOOD_ITERATION, "input_tokens": "[SCRUBBED]"},
        {**GOOD_ITERATION, "output_tokens": False},
        {**GOOD_ITERATION, "cache_creation": {"ephemeral_1h_input_tokens": "x"}},
    ],
    ids=["str", "bool", "nested-cache"],
)
def test_one_bad_iteration_is_unknown_not_partial_sum(bad_iteration: dict) -> None:
    raw = {"input_tokens": 100, "output_tokens": 50,
           "iterations": [GOOD_ITERATION, bad_iteration]}
    assert _parse_usage(raw) is None


def test_well_formed_usage_is_unchanged() -> None:
    u = _parse_usage({"iterations": [GOOD_ITERATION, GOOD_ITERATION]})
    assert u is not None
    assert (u.input_tokens, u.output_tokens, u.cache_read, u.cache_creation_5m) == (
        200, 100, 20, 10,
    )
    missing = _parse_usage({"input_tokens": 7})
    assert missing is not None
    assert (missing.input_tokens, missing.output_tokens) == (7, 0)


def _write_session(tmp_path: Path, usages: list[dict]) -> Path:
    session_id = "unknown-usage-sess"
    base = {
        "isSidechain": False,
        "timestamp": "2026-05-14T10:00:00.000Z",
        "sessionId": session_id,
        "version": "2.1.138",
        "cwd": "/Users/test/Projects/demo",
        "gitBranch": "main",
        "userType": "external",
        "entrypoint": "cli",
    }
    lines = [{**base, "type": "user", "uuid": "u1", "parentUuid": None,
              "message": {"role": "user", "content": "hello"}}]
    for i, usage in enumerate(usages, 1):
        lines.append({**base, "type": "assistant", "uuid": f"a{i}",
                      "parentUuid": lines[-1]["uuid"],
                      "message": {"id": f"msg-{i}", "role": "assistant",
                                  "model": "claude-sonnet-4-6",
                                  "content": [{"type": "text", "text": f"reply {i}"}],
                                  "stop_reason": "end_turn", "usage": usage}})
    path = tmp_path / f"{session_id}.jsonl"
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))
    return path


def test_unknown_usage_flows_to_diagnosis_and_export(tmp_path: Path) -> None:
    path = _write_session(tmp_path, [
        {"input_tokens": 1_000, "output_tokens": 500},
        {"input_tokens": 1_000, "output_tokens": 500,
         "iterations": [GOOD_ITERATION, {**GOOD_ITERATION, "input_tokens": "[SCRUBBED]"}]},
    ])
    trace = parse_session(path)
    bad = [t for t in trace.turns if t.role == "assistant"][1]
    assert bad.usage is None

    diagnosis = diagnostician.run(trace)
    assert diagnosis.unknown_usage_turns == [bad.turn_number]

    obj = json.loads(export_diagnosis(diagnosis, trace))
    assert obj["total_cost_usd"] is None
    assert obj["unknown_usage_turns"] == [bad.turn_number]


def test_known_usage_exports_numeric_cost(tmp_path: Path) -> None:
    trace = parse_session(_write_session(tmp_path, [{"input_tokens": 1_000, "output_tokens": 500}]))
    diagnosis = diagnostician.run(trace)
    assert diagnosis.unknown_usage_turns == []
    obj = json.loads(export_diagnosis(diagnosis, trace))
    assert obj["total_cost_usd"] > 0
    assert obj["unknown_usage_turns"] == []


def test_renderers_warn_next_to_cost(tmp_path: Path) -> None:
    import io

    from rich.console import Console

    from cctx.renderers.github import render_github_summary
    from cctx.renderers.terminal import render_diagnosis

    path = _write_session(tmp_path, [{"input_tokens": "[SCRUBBED]", "output_tokens": 5}])
    diagnosis = diagnostician.run(parse_session(path))
    turn = diagnosis.unknown_usage_turns[0]

    buf = io.StringIO()
    render_diagnosis(diagnosis, console=Console(file=buf, width=200, markup=False))
    assert f"Unknown token usage on turn(s) {turn}" in buf.getvalue()
    assert f"Unknown token usage on turn(s) {turn}" in render_github_summary(diagnosis)
