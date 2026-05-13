"""Shared pytest fixtures for cctx tests."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import pytest


@pytest.fixture
def write_jsonl(tmp_path: Path):
    """Factory that writes a JSONL file from a sequence of dicts.

    Returns a callable: write_jsonl(lines, filename="session.jsonl") -> Path.
    """

    def _write(lines: Iterable[dict], filename: str = "session.jsonl") -> Path:
        path = tmp_path / filename
        with path.open("w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
        return path

    return _write


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    """A project-shaped session directory: <tmp>/<encoded-project>/<session-id>.jsonl
    plus optional sibling <session-id>/subagents/ and <session-id>/tool-results/.
    """
    project = tmp_path / "-Users-test-Projects-demo"
    project.mkdir()
    return project


def make_assistant_line(
    uuid: str,
    parent_uuid: str | None = None,
    *,
    text: str = "",
    thinking: str = "",
    tool_uses: list[dict] | None = None,
    model: str = "claude-sonnet-4-6",
    stop_reason: str = "end_turn",
    timestamp: str = "2026-05-13T02:00:00.000Z",
    cache_creation_5m: int = 0,
    cache_creation_1h: int = 0,
    cache_read: int = 0,
    input_tokens: int = 10,
    output_tokens: int = 20,
    session_id: str = "test-session",
    version: str = "2.1.138",
    cwd: str = "/Users/test/Projects/demo",
) -> dict:
    """Construct a synthetic assistant line as it would appear in a JSONL transcript."""
    content: list[dict] = []
    if thinking:
        content.append({"type": "thinking", "thinking": thinking, "signature": "sig"})
    if text:
        content.append({"type": "text", "text": text})
    if tool_uses:
        content.extend(tool_uses)

    return {
        "type": "assistant",
        "uuid": uuid,
        "parentUuid": parent_uuid,
        "isSidechain": False,
        "timestamp": timestamp,
        "sessionId": session_id,
        "version": version,
        "cwd": cwd,
        "gitBranch": "main",
        "userType": "external",
        "entrypoint": "cli",
        "requestId": f"req_{uuid}",
        "message": {
            "model": model,
            "id": f"msg_{uuid}",
            "type": "message",
            "role": "assistant",
            "content": content,
            "stop_reason": stop_reason,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation_5m + cache_creation_1h,
                "cache_read_input_tokens": cache_read,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": cache_creation_5m,
                    "ephemeral_1h_input_tokens": cache_creation_1h,
                },
                "service_tier": "standard",
                "iterations": [
                    {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cache_creation_input_tokens": cache_creation_5m + cache_creation_1h,
                        "cache_read_input_tokens": cache_read,
                        "cache_creation": {
                            "ephemeral_5m_input_tokens": cache_creation_5m,
                            "ephemeral_1h_input_tokens": cache_creation_1h,
                        },
                        "type": "message",
                    }
                ],
            },
        },
    }


def make_user_line(
    uuid: str,
    parent_uuid: str | None = None,
    *,
    content: str | list[dict] = "hello",
    tool_use_result: dict | None = None,
    timestamp: str = "2026-05-13T02:00:00.000Z",
    session_id: str = "test-session",
    version: str = "2.1.138",
    cwd: str = "/Users/test/Projects/demo",
) -> dict:
    """Construct a synthetic user line. `content` is either a string or a list of blocks."""
    line: dict = {
        "type": "user",
        "uuid": uuid,
        "parentUuid": parent_uuid,
        "isSidechain": False,
        "timestamp": timestamp,
        "sessionId": session_id,
        "version": version,
        "cwd": cwd,
        "gitBranch": "main",
        "userType": "external",
        "entrypoint": "cli",
        "message": {"role": "user", "content": content},
    }
    if tool_use_result is not None:
        line["toolUseResult"] = tool_use_result
    return line


def make_tool_use_block(tool_use_id: str, tool_name: str, tool_input: dict | None = None) -> dict:
    """Construct a synthetic tool_use content block."""
    return {
        "type": "tool_use",
        "id": tool_use_id,
        "name": tool_name,
        "caller": {"type": "direct"},
        "input": tool_input or {},
    }


def make_tool_result_block(
    tool_use_id: str, content: str | list[dict], is_error: bool = False
) -> dict:
    """Construct a synthetic tool_result content block (lives inside a user line)."""
    block: dict = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
    }
    if is_error:
        block["is_error"] = True
    return block
