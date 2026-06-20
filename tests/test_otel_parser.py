"""Tests for cctx/parsers/otel.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_otel_file_returns_list() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert isinstance(result, list)
    assert len(result) == 1


def test_parse_otel_file_session_id_is_trace_id() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_handoff.jsonl")
    assert result[0].session_id == "aabbccddeeff00112233445566778899"


def test_parse_otel_file_source_path_set() -> None:
    from cctx.parsers.otel import parse_otel_file

    path = FIXTURES / "otel_handoff.jsonl"
    result = parse_otel_file(path)
    assert result[0].source_path == path


def test_parse_otel_file_fanout_returns_one_trace() -> None:
    from cctx.parsers.otel import parse_otel_file

    result = parse_otel_file(FIXTURES / "otel_fanout.jsonl")
    assert len(result) == 1
    assert result[0].session_id == "bbccddee00112233bbccddee00112233"
