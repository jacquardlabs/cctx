# Claude Code Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Claude Code JSONL parser at `cctx/parsers/claude_code.py` plus its supporting data model at `cctx/models.py`, per the approved spec at `docs/superpowers/specs/2026-05-12-claude-code-parser-design.md`.

**Architecture:** Single-pass streaming parser. One function (`parse_session`) takes a path, returns a fully-populated `SessionTrace`. Parser is dependency-free (no anthropic SDK, no click, no rich). Subagents are parsed recursively (the same function handles parent and child files). Token counts are left as 0 placeholders — a separate tokenizer pass (not part of this plan) fills them later.

**Tech Stack:** Python 3.10+, stdlib only for the parser itself. Dev deps: `pytest`, `ruff` (lint + format). Test fixtures: hand-built synthetic JSONL for TDD; anonymized real-data fixtures for integration coverage.

**Spec sections this plan covers:** §3 (public API), §4 (data model), §5 (line-type dispatch), §6 (attachment classification), §7 (subagent stitching), §8 (tool-result content), §9 (error handling), §10 (testing strategy). Open questions from §11 are noted in tasks where they're resolved.

---

## File structure

Files created by this plan:

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, dev deps, ruff/pytest config |
| `cctx/__init__.py` | Package marker, version export |
| `cctx/models.py` | All dataclasses (`Turn`, `ToolUse`, `ToolResult`, `Usage`, `Attachment`, `RawToolResultFile`, `SessionTrace`, `ParserWarning`), plus `ParserError` exception and `group_into_exchanges()` helper |
| `cctx/parsers/__init__.py` | Package marker |
| `cctx/parsers/claude_code.py` | The parser — `parse_session()` plus private helpers |
| `tests/__init__.py` | Package marker |
| `tests/conftest.py` | Shared pytest fixtures: tempdir factories, synthetic-JSONL builders |
| `tests/test_models.py` | Unit tests for dataclass invariants and `group_into_exchanges()` |
| `tests/test_parser_claude_code.py` | Unit tests for the parser (TDD-driven across most tasks) |
| `tests/test_parser_integration.py` | Integration tests against tier-1 real fixtures |
| `tests/fixtures/real/` | Anonymized real-session fixtures (created by task 25) |
| `tests/fixtures/synthetic/` | Hand-built minimal JSONL files for adversarial cases |
| `scripts/anonymize_fixture.py` | Reproducible anonymization script for capturing new real fixtures |

The parser is a single file by design. If it grows beyond ~500 lines during implementation, consider splitting the attachment classifier and the subagent linker into private sibling modules (`_attachments.py`, `_subagents.py`) — but only if needed.

---

## Conventions

- **Python version:** 3.10+. We use `from __future__ import annotations` everywhere so `X | None` works under 3.10.
- **Test runner:** `pytest` from the repo root.
- **Linter/formatter:** `ruff check` and `ruff format`.
- **Commit messages:** Conventional Commits style (`feat:`, `test:`, `chore:`, `refactor:`, `fix:`). One commit per task unless a task explicitly bundles multiple.
- **Test placement:** Unit tests in `tests/test_*.py`; integration in `tests/test_parser_integration.py`.
- **Imports:** Stdlib only inside `cctx/parsers/` and `cctx/models.py`. `pytest` is the only allowed import in tests beyond stdlib.
- **No `print()`:** The parser never prints. Warnings accumulate on `SessionTrace.warnings`. The CLI (not in this plan) renders them.

---

## Task 1: Project setup

**Files:**
- Create: `pyproject.toml`
- Create: `cctx/__init__.py`
- Create: `cctx/parsers/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "cctx"
version = "0.0.1"
description = "Profile, debug, and optimize Claude Code and Agent SDK sessions"
readme = "cctx-project-brief.md"
requires-python = ">=3.10"
license = "MIT"
authors = [{ name = "Jacquard Labs" }]

# Runtime dependencies are intentionally empty for this plan.
# The parser is stdlib-only. Subsequent feature plans will add
# anthropic, click, rich-click, rich, textual, pandas, Jinja2.
dependencies = []

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.6",
]

[tool.hatch.build.targets.wheel]
packages = ["cctx"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-ra --strict-markers"

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "F",   # pyflakes
    "W",   # pycodestyle warnings
    "I",   # isort
    "UP",  # pyupgrade
    "B",   # bugbear
    "SIM", # simplify
]

[tool.ruff.format]
quote-style = "double"
```

- [ ] **Step 2: Create package markers**

`cctx/__init__.py`:
```python
"""cctx: profile, debug, and optimize Claude Code and Agent SDK sessions."""

__version__ = "0.0.1"
```

`cctx/parsers/__init__.py`:
```python
"""Parsers for session log formats."""
```

`tests/__init__.py`: empty file.

- [ ] **Step 3: Install dev environment**

Run:
```bash
cd /Users/bryan/Projects/cctx
.venv/bin/python -m ensurepip --upgrade
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
```

Expected: pytest and ruff installed; `cctx` package importable from the venv.

- [ ] **Step 4: Verify install**

```bash
.venv/bin/python -c "import cctx; print(cctx.__version__)"
.venv/bin/pytest --version
.venv/bin/ruff --version
```

Expected: prints `0.0.1`, then pytest version, then ruff version. No errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml cctx/__init__.py cctx/parsers/__init__.py tests/__init__.py
git commit -m "chore: project setup with pytest and ruff"
```

---

## Task 2: Test infrastructure (conftest helpers)

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

This task builds the synthetic-JSONL factory used by every subsequent test. It's a one-time investment that makes every later test a 3-line construction.

- [ ] **Step 1: Write `tests/conftest.py`**

```python
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


def make_tool_result_block(tool_use_id: str, content: str | list[dict], is_error: bool = False) -> dict:
    """Construct a synthetic tool_result content block (lives inside a user line)."""
    block: dict = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
    }
    if is_error:
        block["is_error"] = True
    return block
```

- [ ] **Step 2: Write a smoke test that exercises the factory**

`tests/test_smoke.py`:
```python
"""Sanity checks for the test infrastructure itself."""

from __future__ import annotations

import json

from tests.conftest import (
    make_assistant_line,
    make_tool_result_block,
    make_tool_use_block,
    make_user_line,
)


def test_factories_produce_valid_json():
    """The line factories must produce dicts that round-trip through JSON."""
    a = make_assistant_line(uuid="a1", text="hello")
    u = make_user_line(uuid="u1", content="hi")
    assert json.loads(json.dumps(a))["type"] == "assistant"
    assert json.loads(json.dumps(u))["type"] == "user"


def test_write_jsonl_factory_writes_file(write_jsonl, tmp_path):
    """The write_jsonl fixture writes one line per element, JSON-encoded."""
    path = write_jsonl([{"a": 1}, {"b": 2}])
    contents = path.read_text().splitlines()
    assert len(contents) == 2
    assert json.loads(contents[0]) == {"a": 1}
    assert json.loads(contents[1]) == {"b": 2}


def test_tool_use_and_result_round_trip():
    """tool_use_id matches between use and result blocks."""
    use = make_tool_use_block("toolu_1", "Read", {"file_path": "/x"})
    result = make_tool_result_block("toolu_1", "contents")
    assert use["id"] == result["tool_use_id"]
```

- [ ] **Step 3: Run smoke tests**

```bash
cd /Users/bryan/Projects/cctx
.venv/bin/pytest tests/test_smoke.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/test_smoke.py
git commit -m "test: scaffold conftest with JSONL line factories"
```

---

## Task 3: Define the data model

**Files:**
- Create: `cctx/models.py`
- Create: `tests/test_models.py`

This task defines every dataclass from §4 of the spec, plus `ParserError`, `ParserWarning`, and the `group_into_exchanges()` helper. No parser logic yet — pure types.

- [ ] **Step 1: Write the failing test for dataclass instantiation**

`tests/test_models.py`:
```python
"""Unit tests for the cctx data model."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cctx.models import (
    Attachment,
    ParserError,
    ParserWarning,
    RawToolResultFile,
    SessionTrace,
    ToolResult,
    ToolUse,
    Turn,
    Usage,
    group_into_exchanges,
)


def test_usage_instantiates():
    u = Usage(
        input_tokens=10,
        output_tokens=20,
        cache_creation_5m=0,
        cache_creation_1h=100,
        cache_read=50,
        service_tier="standard",
    )
    assert u.input_tokens == 10


def test_tool_use_instantiates_with_defaults():
    t = ToolUse(tool_name="Read", tool_use_id="toolu_1", tool_input={"file_path": "/x"})
    assert t.token_count == 0
    assert t.subagent_session_id is None


def test_tool_result_instantiates_with_defaults():
    r = ToolResult(
        tool_name="Read",
        tool_use_id="toolu_1",
        content="contents",
        structured=None,
        is_error=False,
    )
    assert r.token_count == 0


def test_turn_instantiates_with_defaults():
    t = Turn(
        turn_number=1,
        uuid="u1",
        parent_uuid=None,
        role="user",
        text="hi",
        thinking="",
        tool_uses=[],
        tool_results=[],
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=datetime(2026, 5, 13, tzinfo=timezone.utc),
        duration_ms=None,
    )
    assert t.token_count == 0
    assert t.is_sidechain is False
    assert t.error is None


def test_attachment_instantiates():
    a = Attachment(
        kind="hook_output",
        raw={"hookEvent": "SessionStart"},
        content="some text",
        timestamp=None,
        parent_uuid=None,
    )
    assert a.kind == "hook_output"


def test_raw_tool_result_file_instantiates():
    r = RawToolResultFile(path=Path("/x/y.txt"), size_bytes=100, tool_use_id=None)
    assert r.tool_use_id is None


def test_session_trace_instantiates_with_required_fields():
    s = SessionTrace(
        session_id="abc",
        parent_session_id=None,
        project_path="/Users/test/Projects/demo",
        cwd="/Users/test/Projects/demo",
        primary_model=None,
        claude_code_version="2.1.138",
        turns=[],
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=None,
        end_time=None,
        source_path=Path("/x/abc.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )
    assert s.session_id == "abc"
    assert s.turns == []


def test_parser_error_is_exception():
    e = ParserError(path=Path("/x"), line_number=None, reason="oops")
    assert isinstance(e, Exception)
    assert e.reason == "oops"


def test_parser_warning_is_dataclass_not_exception():
    w = ParserWarning(code="unknown_type", detail="foo")
    assert not isinstance(w, Exception)
    assert w.line_number is None


def test_group_into_exchanges_empty():
    assert group_into_exchanges([]) == []


def test_group_into_exchanges_one_user_one_assistant():
    ts = datetime(2026, 5, 13, tzinfo=timezone.utc)
    u = Turn(
        turn_number=1, uuid="u1", parent_uuid=None, role="user", text="hi",
        thinking="", tool_uses=[], tool_results=[], usage=None, model=None,
        stop_reason=None, timestamp=ts, duration_ms=None,
    )
    a = Turn(
        turn_number=2, uuid="a1", parent_uuid="u1", role="assistant", text="hello",
        thinking="", tool_uses=[], tool_results=[], usage=None, model=None,
        stop_reason="end_turn", timestamp=ts, duration_ms=None,
    )
    exchanges = group_into_exchanges([u, a])
    assert len(exchanges) == 1
    assert exchanges[0] == [u, a]


def test_group_into_exchanges_multiple():
    ts = datetime(2026, 5, 13, tzinfo=timezone.utc)
    def turn(n, role, parent):
        return Turn(
            turn_number=n, uuid=f"t{n}", parent_uuid=parent, role=role,
            text="", thinking="", tool_uses=[], tool_results=[], usage=None,
            model=None, stop_reason=None, timestamp=ts, duration_ms=None,
        )
    turns = [
        turn(1, "user", None),
        turn(2, "assistant", "t1"),
        turn(3, "tool_result", "t2"),
        turn(4, "assistant", "t3"),
        turn(5, "user", "t4"),
        turn(6, "assistant", "t5"),
    ]
    exchanges = group_into_exchanges(turns)
    assert [[t.turn_number for t in ex] for ex in exchanges] == [[1, 2], [3, 4], [5, 6]]
```

- [ ] **Step 2: Run test to confirm failure**

```bash
.venv/bin/pytest tests/test_models.py -v
```

Expected: All fail with `ImportError: cannot import name '...' from 'cctx.models'` (module doesn't exist yet).

- [ ] **Step 3: Implement `cctx/models.py`**

```python
"""Data model for cctx.

These dataclasses are pure data containers — no behavior beyond the
group_into_exchanges() helper. They are populated by the parser and
read by every downstream module (tokenizer, decomposer, analyzers,
renderers, exporters).

Token-count fields are placeholders left at 0 by the parser; the
tokenizer pass fills them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Usage:
    """API usage data attached to a single assistant message."""

    input_tokens: int
    output_tokens: int
    cache_creation_5m: int
    cache_creation_1h: int
    cache_read: int
    service_tier: str | None


@dataclass
class ToolUse:
    """A tool_use content block from an assistant message."""

    tool_name: str
    tool_use_id: str
    tool_input: dict
    token_count: int = 0
    subagent_session_id: str | None = None  # set when tool_name == "Agent" and a child file matched


@dataclass
class ToolResult:
    """A tool_result content block from a user line."""

    tool_name: str  # resolved by pairing with the originating ToolUse on tool_use_id
    tool_use_id: str
    content: str  # inline content is canonical; sidecars are not the source of truth
    structured: dict | None  # the parallel toolUseResult field
    is_error: bool
    token_count: int = 0


@dataclass
class Turn:
    """One JSONL line, normalized.

    The role is one of "user", "assistant", "tool_result", or "system".
    Image blocks become "<image:{media_type},{N}B>" placeholders in `text`.
    """

    turn_number: int
    uuid: str
    parent_uuid: str | None
    role: str
    text: str
    thinking: str
    tool_uses: list[ToolUse]
    tool_results: list[ToolResult]
    usage: Usage | None  # assistant turns only
    model: str | None  # assistant turns only
    stop_reason: str | None
    timestamp: datetime
    duration_ms: int | None
    token_count: int = 0
    is_sidechain: bool = False
    error: str | None = None


@dataclass
class Attachment:
    """A non-conversational record from the JSONL: hook output, MCP list, skills, etc."""

    kind: str  # "hook_output" | "mcp_servers" | "skills" | "allowed_tools" | "items" | "other"
    raw: dict  # original attachment payload, verbatim
    content: str | None  # convenience: extracted text content if available
    timestamp: datetime | None
    parent_uuid: str | None


@dataclass
class RawToolResultFile:
    """A file in <session-id>/tool-results/ (not read by the parser)."""

    path: Path
    size_bytes: int
    tool_use_id: str | None  # always None in v1; matching deferred to v1.1


@dataclass
class ParserWarning:
    """A soft parse failure. Accumulates on SessionTrace.warnings."""

    code: str
    detail: str
    line_number: int | None = None
    path: Path | None = None


class ParserError(Exception):
    """A hard parse failure. Only raised on unreadable files."""

    def __init__(self, path: Path, line_number: int | None, reason: str):
        super().__init__(f"{path}: {reason}" + (f" (line {line_number})" if line_number else ""))
        self.path = path
        self.line_number = line_number
        self.reason = reason


@dataclass
class SessionTrace:
    """A fully-parsed Claude Code session.

    `start_time` and `end_time` are None for bookkeeping-only files (no
    conversational turns). The parser never raises for missing data — soft
    failures accumulate on `warnings`.
    """

    session_id: str
    parent_session_id: str | None  # set on subagent traces
    project_path: str  # decoded from dir name
    cwd: str
    primary_model: str | None
    claude_code_version: str | None
    turns: list[Turn]
    subagents: list[SessionTrace]
    attachments: list[Attachment]
    raw_tool_result_files: list[RawToolResultFile]
    initial_context_tokens: int  # cache_creation_input_tokens from the first assistant turn
    tool_names_loaded: list[str]
    start_time: datetime | None
    end_time: datetime | None
    source_path: Path
    subagent_meta: dict  # verbatim .meta.json contents; empty for the root
    warnings: list[ParserWarning]
    subagent_parse_errors: list[dict]  # entries: {"path": Path, "reason": str}


def group_into_exchanges(turns: list[Turn]) -> list[list[Turn]]:
    """Group turns into user→assistant exchanges for display.

    An exchange starts with a user or tool_result turn and includes
    all subsequent assistant turns until the next user/tool_result.
    """
    exchanges: list[list[Turn]] = []
    current: list[Turn] = []
    for turn in turns:
        if turn.role in ("user", "tool_result") and current:
            exchanges.append(current)
            current = []
        current.append(turn)
    if current:
        exchanges.append(current)
    return exchanges
```

- [ ] **Step 4: Run tests to confirm passing**

```bash
.venv/bin/pytest tests/test_models.py -v
```

Expected: 12 passed.

- [ ] **Step 5: Run ruff**

```bash
.venv/bin/ruff check cctx tests
.venv/bin/ruff format --check cctx tests
```

Expected: no issues. If `ruff format --check` reports formatting, run `.venv/bin/ruff format cctx tests` and re-stage.

- [ ] **Step 6: Commit**

```bash
git add cctx/models.py tests/test_models.py
git commit -m "feat: data model (Turn, ToolUse, ToolResult, Usage, Attachment, SessionTrace)"
```

---

## Task 4: `parse_session` entry point + path handling

**Files:**
- Create: `cctx/parsers/claude_code.py`
- Create: `tests/test_parser_claude_code.py`

The first task in the TDD sequence. Establish the public entry point: accept either a JSONL file or a sibling directory, raise `ParserError` on unreadable input, return a minimal `SessionTrace` for an empty file.

- [ ] **Step 1: Write failing tests**

`tests/test_parser_claude_code.py`:
```python
"""Unit tests for the Claude Code JSONL parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cctx.models import ParserError
from cctx.parsers.claude_code import parse_session


def test_missing_file_raises_parser_error(tmp_path):
    with pytest.raises(ParserError) as exc:
        parse_session(tmp_path / "does-not-exist.jsonl")
    assert "does-not-exist" in exc.value.reason


def test_empty_file_returns_minimal_trace(write_jsonl):
    path = write_jsonl([])
    trace = parse_session(path)
    assert trace.turns == []
    assert trace.attachments == []
    assert trace.source_path == path
    assert trace.warnings == []
    assert trace.start_time is None
    assert trace.end_time is None
    assert trace.initial_context_tokens == 0
    assert trace.primary_model is None


def test_accepts_directory_path(tmp_path, write_jsonl):
    """parse_session accepts either the JSONL file or its sibling directory."""
    # Layout: <tmp>/abc123.jsonl with sibling <tmp>/abc123/
    jsonl = write_jsonl([], filename="abc123.jsonl")
    sibling_dir = tmp_path / "abc123"
    sibling_dir.mkdir()

    # When given the directory, parser finds the .jsonl by name.
    trace = parse_session(sibling_dir)
    assert trace.source_path == jsonl
    assert trace.session_id == "abc123"


def test_project_path_decoded_from_dirname(tmp_path):
    """Project path is decoded from the parent dir name's leading-dash convention."""
    project = tmp_path / "-Users-test-Projects-demo"
    project.mkdir()
    jsonl = project / "abc123.jsonl"
    jsonl.write_text("")

    trace = parse_session(jsonl)
    assert trace.project_path == "/Users/test/Projects/demo"
    assert trace.session_id == "abc123"
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
```

Expected: ImportError — `cctx.parsers.claude_code` doesn't exist yet.

- [ ] **Step 3: Implement minimal `parse_session`**

`cctx/parsers/claude_code.py`:
```python
"""Claude Code JSONL session parser.

Public API: parse_session(path) -> SessionTrace.
"""

from __future__ import annotations

from pathlib import Path

from cctx.models import (
    ParserError,
    SessionTrace,
)


def parse_session(session_path: Path, *, max_subagent_depth: int = 4) -> SessionTrace:
    """Parse a Claude Code session.

    Accepts either:
      - the JSONL file itself (~/.claude/projects/<proj>/<sid>.jsonl), or
      - its sibling directory (~/.claude/projects/<proj>/<sid>/).

    Raises ParserError on unreadable input. Soft failures accumulate on
    SessionTrace.warnings.
    """
    session_path = Path(session_path)
    jsonl_path = _resolve_jsonl_path(session_path)

    if not jsonl_path.exists():
        raise ParserError(
            path=jsonl_path,
            line_number=None,
            reason=f"file not found: {jsonl_path}",
        )

    session_id = jsonl_path.stem
    project_dir = jsonl_path.parent
    project_path = _decode_project_path(project_dir.name)

    return SessionTrace(
        session_id=session_id,
        parent_session_id=None,
        project_path=project_path,
        cwd=project_path,
        primary_model=None,
        claude_code_version=None,
        turns=[],
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=None,
        end_time=None,
        source_path=jsonl_path,
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


def _resolve_jsonl_path(path: Path) -> Path:
    """Accept either the JSONL file or its sibling directory."""
    if path.is_dir():
        # Convention: directory <sid>/ has a sibling file <sid>.jsonl
        return path.parent / f"{path.name}.jsonl"
    return path


def _decode_project_path(dir_name: str) -> str:
    """Decode Claude Code's project dir naming convention.

    Example: '-Users-bryan-Projects-cctx' -> '/Users/bryan/Projects/cctx'

    The convention is that '/' in the original path becomes '-'. We naively
    reverse this by replacing '-' with '/'; in the rare case a real path
    contains '-' the reconstruction is lossy. The decomposer should prefer
    SessionTrace.cwd (observed from line data) when an exact path matters.
    """
    if not dir_name.startswith("-"):
        return dir_name
    return dir_name.replace("-", "/")
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Lint**

```bash
.venv/bin/ruff check cctx tests
.venv/bin/ruff format cctx tests
```

- [ ] **Step 6: Commit**

```bash
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): entry point with path resolution and project decoding"
```

---

## Task 5: Parse simple user lines (string content)

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_parser_claude_code.py`:
```python
from tests.conftest import make_user_line


def test_single_user_line_string_content(write_jsonl):
    path = write_jsonl([make_user_line(uuid="u1", content="hello world")])
    trace = parse_session(path)
    assert len(trace.turns) == 1
    turn = trace.turns[0]
    assert turn.turn_number == 1
    assert turn.uuid == "u1"
    assert turn.role == "user"
    assert turn.text == "hello world"
    assert turn.thinking == ""
    assert turn.tool_uses == []
    assert turn.tool_results == []
    assert turn.usage is None
    assert turn.model is None
    assert turn.parent_uuid is None


def test_user_line_timestamp_parsed_to_utc(write_jsonl):
    path = write_jsonl([make_user_line(uuid="u1", content="x", timestamp="2026-05-13T02:00:00.123Z")])
    trace = parse_session(path)
    ts = trace.turns[0].timestamp
    assert ts.tzinfo is not None
    assert ts.isoformat().startswith("2026-05-13T02:00:00")
    assert trace.start_time == ts
    assert trace.end_time == ts


def test_multiple_user_lines_numbered_in_order(write_jsonl):
    path = write_jsonl([
        make_user_line(uuid="u1", content="first", timestamp="2026-05-13T02:00:00.000Z"),
        make_user_line(uuid="u2", parent_uuid="u1", content="second", timestamp="2026-05-13T02:00:01.000Z"),
        make_user_line(uuid="u3", parent_uuid="u2", content="third", timestamp="2026-05-13T02:00:02.000Z"),
    ])
    trace = parse_session(path)
    assert [t.turn_number for t in trace.turns] == [1, 2, 3]
    assert [t.text for t in trace.turns] == ["first", "second", "third"]
    assert trace.start_time != trace.end_time
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v -k "user_line or multiple_user"
```

Expected: 3 failures — turns list is empty (parser doesn't read lines yet).

- [ ] **Step 3: Implement line iteration and user dispatch**

Replace `cctx/parsers/claude_code.py` with:

```python
"""Claude Code JSONL session parser."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cctx.models import (
    ParserError,
    SessionTrace,
    Turn,
)


def parse_session(session_path: Path, *, max_subagent_depth: int = 4) -> SessionTrace:
    session_path = Path(session_path)
    jsonl_path = _resolve_jsonl_path(session_path)

    if not jsonl_path.exists():
        raise ParserError(
            path=jsonl_path,
            line_number=None,
            reason=f"file not found: {jsonl_path}",
        )

    session_id = jsonl_path.stem
    project_dir = jsonl_path.parent
    project_path = _decode_project_path(project_dir.name)

    turns: list[Turn] = []

    for line_number, raw in _iter_lines(jsonl_path):
        if raw is None:
            continue
        line_type = raw.get("type")
        if line_type == "user":
            turn = _parse_user_line(raw)
            if turn is not None:
                turns.append(turn)

    # Number turns 1-based and compute start/end.
    for i, turn in enumerate(turns, start=1):
        turn.turn_number = i

    start_time = turns[0].timestamp if turns else None
    end_time = turns[-1].timestamp if turns else None

    return SessionTrace(
        session_id=session_id,
        parent_session_id=None,
        project_path=project_path,
        cwd=project_path,
        primary_model=None,
        claude_code_version=None,
        turns=turns,
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=start_time,
        end_time=end_time,
        source_path=jsonl_path,
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


def _iter_lines(path: Path):
    """Yield (line_number, parsed_dict) for each line in the file.

    Yields (line_number, None) for lines that cannot be parsed; the caller
    decides how to record those.
    """
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_number, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield line_number, json.loads(stripped)
            except json.JSONDecodeError:
                yield line_number, None


def _parse_user_line(raw: dict) -> Turn | None:
    """Build a Turn from a `type: "user"` JSONL line."""
    message = raw.get("message") or {}
    content = message.get("content")

    text = content if isinstance(content, str) else ""

    return Turn(
        turn_number=0,  # set by caller after collection
        uuid=raw.get("uuid", ""),
        parent_uuid=raw.get("parentUuid"),
        role="user",
        text=text,
        thinking="",
        tool_uses=[],
        tool_results=[],
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=_parse_timestamp(raw.get("timestamp")),
        duration_ms=None,
        is_sidechain=bool(raw.get("isSidechain", False)),
    )


def _parse_timestamp(value: str | None) -> datetime:
    """Parse an ISO 8601 timestamp. Accepts both 'Z' suffix and '+00:00'."""
    if not value:
        # Fallback for synthetic edge cases; should never be reached with real data.
        return datetime.fromtimestamp(0, tz=__import__("datetime").timezone.utc)
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _resolve_jsonl_path(path: Path) -> Path:
    if path.is_dir():
        return path.parent / f"{path.name}.jsonl"
    return path


def _decode_project_path(dir_name: str) -> str:
    if not dir_name.startswith("-"):
        return dir_name
    return dir_name.replace("-", "/")
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Lint**

```bash
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
```

- [ ] **Step 6: Commit**

```bash
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): handle user lines with string content"
```

---

## Task 6: Parse assistant lines (text + thinking + usage)

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

- [ ] **Step 1: Add failing tests**

```python
from tests.conftest import make_assistant_line


def test_assistant_line_text_and_thinking_separate(write_jsonl):
    path = write_jsonl([make_assistant_line(uuid="a1", text="hello", thinking="reasoning…")])
    trace = parse_session(path)
    assert len(trace.turns) == 1
    turn = trace.turns[0]
    assert turn.role == "assistant"
    assert turn.text == "hello"
    assert turn.thinking == "reasoning…"
    assert turn.model == "claude-sonnet-4-6"
    assert turn.stop_reason == "end_turn"


def test_assistant_usage_populated(write_jsonl):
    path = write_jsonl([
        make_assistant_line(
            uuid="a1",
            text="hi",
            input_tokens=5,
            output_tokens=15,
            cache_creation_5m=100,
            cache_creation_1h=200,
            cache_read=50,
        )
    ])
    trace = parse_session(path)
    u = trace.turns[0].usage
    assert u is not None
    assert u.input_tokens == 5
    assert u.output_tokens == 15
    assert u.cache_creation_5m == 100
    assert u.cache_creation_1h == 200
    assert u.cache_read == 50
    assert u.service_tier == "standard"


def test_assistant_with_no_text_or_thinking(write_jsonl):
    """Assistant message with only tool_use blocks → text and thinking are empty strings, not None."""
    from tests.conftest import make_tool_use_block

    path = write_jsonl([
        make_assistant_line(uuid="a1", tool_uses=[make_tool_use_block("toolu_1", "Read")])
    ])
    trace = parse_session(path)
    turn = trace.turns[0]
    assert turn.text == ""
    assert turn.thinking == ""


def test_assistant_concatenates_multiple_text_blocks(write_jsonl):
    """Multiple text blocks in the same message are joined."""
    line = make_assistant_line(uuid="a1", text="part one")
    # Add a second text block manually.
    line["message"]["content"].append({"type": "text", "text": "part two"})
    path = write_jsonl([line])
    trace = parse_session(path)
    assert trace.turns[0].text == "part one\npart two"
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v -k "assistant"
```

Expected: 4 failures (parser only handles user lines).

- [ ] **Step 3: Implement assistant dispatch**

In `cctx/parsers/claude_code.py`, update the import and add the `_parse_assistant_line` and `_parse_usage` functions, and route `assistant` in the main loop:

```python
from cctx.models import (
    ParserError,
    SessionTrace,
    Turn,
    Usage,
)
```

Add to the dispatch loop inside `parse_session`:

```python
        elif line_type == "assistant":
            turn = _parse_assistant_line(raw)
            if turn is not None:
                turns.append(turn)
```

Add the parsing helpers:

```python
def _parse_assistant_line(raw: dict) -> Turn | None:
    """Build a Turn from a `type: "assistant"` JSONL line."""
    message = raw.get("message") or {}
    content_blocks = message.get("content") or []

    text_parts: list[str] = []
    thinking_parts: list[str] = []

    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "thinking":
            thinking_parts.append(block.get("thinking", ""))
        # tool_use and server_tool_use handled in later tasks.

    return Turn(
        turn_number=0,
        uuid=raw.get("uuid", ""),
        parent_uuid=raw.get("parentUuid"),
        role="assistant",
        text="\n".join(text_parts),
        thinking="\n".join(thinking_parts),
        tool_uses=[],
        tool_results=[],
        usage=_parse_usage(message.get("usage")),
        model=message.get("model"),
        stop_reason=message.get("stop_reason"),
        timestamp=_parse_timestamp(raw.get("timestamp")),
        duration_ms=None,
        is_sidechain=bool(raw.get("isSidechain", False)),
        error=("api_error" if raw.get("isApiErrorMessage") else None),
    )


def _parse_usage(raw: dict | None) -> Usage | None:
    """Build a Usage from the message.usage dict.

    Defensive sum of iterations[] if present and divergent — spec §5.2.
    """
    if not isinstance(raw, dict):
        return None

    iterations = raw.get("iterations")
    if isinstance(iterations, list) and iterations:
        # Sum across iterations defensively.
        input_t = sum(it.get("input_tokens", 0) for it in iterations)
        output_t = sum(it.get("output_tokens", 0) for it in iterations)
        cache_read = sum(it.get("cache_read_input_tokens", 0) for it in iterations)
        cache_5m = sum(
            (it.get("cache_creation") or {}).get("ephemeral_5m_input_tokens", 0)
            for it in iterations
        )
        cache_1h = sum(
            (it.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0)
            for it in iterations
        )
    else:
        input_t = raw.get("input_tokens", 0)
        output_t = raw.get("output_tokens", 0)
        cache_read = raw.get("cache_read_input_tokens", 0)
        cache_obj = raw.get("cache_creation") or {}
        cache_5m = cache_obj.get("ephemeral_5m_input_tokens", 0)
        cache_1h = cache_obj.get("ephemeral_1h_input_tokens", 0)

    return Usage(
        input_tokens=input_t,
        output_tokens=output_t,
        cache_creation_5m=cache_5m,
        cache_creation_1h=cache_1h,
        cache_read=cache_read,
        service_tier=raw.get("service_tier"),
    )
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
```

Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): assistant lines with text, thinking, and usage"
```

---

## Task 7: Parse tool_use blocks on assistant lines

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

- [ ] **Step 1: Add failing tests**

```python
from tests.conftest import make_tool_use_block


def test_single_tool_use_block(write_jsonl):
    use = make_tool_use_block("toolu_1", "Read", {"file_path": "/x"})
    path = write_jsonl([make_assistant_line(uuid="a1", tool_uses=[use])])
    trace = parse_session(path)
    turn = trace.turns[0]
    assert len(turn.tool_uses) == 1
    tu = turn.tool_uses[0]
    assert tu.tool_name == "Read"
    assert tu.tool_use_id == "toolu_1"
    assert tu.tool_input == {"file_path": "/x"}
    assert tu.subagent_session_id is None


def test_multiple_parallel_tool_uses_in_one_message(write_jsonl):
    """An assistant message firing 3 parallel tool calls produces ONE Turn with 3 tool_uses."""
    uses = [
        make_tool_use_block("toolu_1", "Read", {"file_path": "/a"}),
        make_tool_use_block("toolu_2", "Read", {"file_path": "/b"}),
        make_tool_use_block("toolu_3", "Grep", {"pattern": "foo"}),
    ]
    path = write_jsonl([make_assistant_line(uuid="a1", tool_uses=uses)])
    trace = parse_session(path)
    turn = trace.turns[0]
    assert len(turn.tool_uses) == 3
    assert [tu.tool_name for tu in turn.tool_uses] == ["Read", "Read", "Grep"]
    assert [tu.tool_use_id for tu in turn.tool_uses] == ["toolu_1", "toolu_2", "toolu_3"]
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py::test_single_tool_use_block tests/test_parser_claude_code.py::test_multiple_parallel_tool_uses_in_one_message -v
```

Expected: failures — `tool_uses` is empty.

- [ ] **Step 3: Extend `_parse_assistant_line` to collect tool_use blocks**

Update import:
```python
from cctx.models import (
    ParserError,
    SessionTrace,
    ToolUse,
    Turn,
    Usage,
)
```

Inside `_parse_assistant_line`, replace the content-block loop with:
```python
    tool_uses: list[ToolUse] = []
    text_parts: list[str] = []
    thinking_parts: list[str] = []

    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "thinking":
            thinking_parts.append(block.get("thinking", ""))
        elif block_type == "tool_use":
            tool_uses.append(
                ToolUse(
                    tool_name=block.get("name", ""),
                    tool_use_id=block.get("id", ""),
                    tool_input=block.get("input", {}) if isinstance(block.get("input"), dict) else {},
                )
            )
        elif block_type in ("server_tool_use", "advisor_tool_result"):
            # Inline a marker so the text remains useful; structured handling deferred.
            text_parts.append(f"<{block_type}:{block.get('id', '')}>")
```

In the `Turn(...)` construction, set `tool_uses=tool_uses`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
```

Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): tool_use blocks on assistant lines"
```

---

## Task 8: Parse user lines with tool_result content

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

The spec's revised dispatch rule (§5): if any block in a user message is `tool_result`, the Turn's role is `"tool_result"`. The originating ToolUse's `tool_name` is paired in afterward.

- [ ] **Step 1: Add failing tests**

```python
from tests.conftest import make_tool_result_block


def test_user_line_with_tool_result_becomes_tool_result_role(write_jsonl):
    block = make_tool_result_block("toolu_1", "file contents")
    path = write_jsonl([
        make_assistant_line(uuid="a1", tool_uses=[make_tool_use_block("toolu_1", "Read")]),
        make_user_line(uuid="u1", parent_uuid="a1", content=[block]),
    ])
    trace = parse_session(path)
    assert len(trace.turns) == 2
    tr_turn = trace.turns[1]
    assert tr_turn.role == "tool_result"
    assert len(tr_turn.tool_results) == 1
    tr = tr_turn.tool_results[0]
    assert tr.tool_use_id == "toolu_1"
    assert tr.content == "file contents"
    assert tr.is_error is False
    assert tr.tool_name == "Read"  # paired in from the originating ToolUse


def test_tool_result_content_can_be_list_of_text_blocks(write_jsonl):
    """tool_result.content is sometimes a list of {type, text} blocks; flatten to a string."""
    block = make_tool_result_block(
        "toolu_1",
        [{"type": "text", "text": "line one"}, {"type": "text", "text": "line two"}],
    )
    path = write_jsonl([
        make_assistant_line(uuid="a1", tool_uses=[make_tool_use_block("toolu_1", "Bash")]),
        make_user_line(uuid="u1", parent_uuid="a1", content=[block]),
    ])
    trace = parse_session(path)
    tr = trace.turns[1].tool_results[0]
    assert tr.content == "line one\nline two"


def test_three_parallel_tool_results_in_one_user_line(write_jsonl):
    """Parallel tool calls produce one user line with multiple tool_result blocks → one Turn with 3 tool_results."""
    path = write_jsonl([
        make_assistant_line(
            uuid="a1",
            tool_uses=[
                make_tool_use_block("toolu_1", "Read", {"file_path": "/a"}),
                make_tool_use_block("toolu_2", "Read", {"file_path": "/b"}),
                make_tool_use_block("toolu_3", "Grep", {"pattern": "x"}),
            ],
        ),
        make_user_line(
            uuid="u1",
            parent_uuid="a1",
            content=[
                make_tool_result_block("toolu_1", "a-contents"),
                make_tool_result_block("toolu_2", "b-contents"),
                make_tool_result_block("toolu_3", "no matches"),
            ],
        ),
    ])
    trace = parse_session(path)
    assert len(trace.turns) == 2
    tr_turn = trace.turns[1]
    assert tr_turn.role == "tool_result"
    assert [tr.tool_use_id for tr in tr_turn.tool_results] == ["toolu_1", "toolu_2", "toolu_3"]
    assert [tr.tool_name for tr in tr_turn.tool_results] == ["Read", "Read", "Grep"]


def test_tool_result_is_error_flag(write_jsonl):
    block = make_tool_result_block("toolu_1", "tool execution failed", is_error=True)
    path = write_jsonl([
        make_assistant_line(uuid="a1", tool_uses=[make_tool_use_block("toolu_1", "Bash")]),
        make_user_line(uuid="u1", parent_uuid="a1", content=[block]),
    ])
    trace = parse_session(path)
    assert trace.turns[1].tool_results[0].is_error is True


def test_tool_result_structured_field_populated_from_tool_use_result(write_jsonl):
    """The parallel toolUseResult field on the line goes onto ToolResult.structured."""
    block = make_tool_result_block("toolu_1", "short content")
    line = make_user_line(
        uuid="u1",
        content=[block],
        tool_use_result={
            "type": "text",
            "file": {"filePath": "/a", "content": "...", "numLines": 10},
        },
    )
    path = write_jsonl([
        make_assistant_line(uuid="a1", tool_uses=[make_tool_use_block("toolu_1", "Read")]),
        line,
    ])
    trace = parse_session(path)
    tr = trace.turns[1].tool_results[0]
    assert tr.structured is not None
    assert tr.structured["file"]["filePath"] == "/a"
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v -k "tool_result"
```

Expected: 5 failures.

- [ ] **Step 3: Implement user-line dispatch with tool_result handling**

Update import:
```python
from cctx.models import (
    ParserError,
    SessionTrace,
    ToolResult,
    ToolUse,
    Turn,
    Usage,
)
```

Replace `_parse_user_line` with:

```python
def _parse_user_line(raw: dict) -> Turn | None:
    """Build a Turn from a `type: "user"` JSONL line.

    Pattern-matches on the set of content block types so heterogeneous arrays
    don't fall through to the unknown-type path. tool_name on each ToolResult
    is set to "" here; the pairing pass fills it from prior ToolUses.
    """
    message = raw.get("message") or {}
    content = message.get("content")

    if isinstance(content, str):
        text = content
        tool_results: list[ToolResult] = []
        role = "user"
    elif isinstance(content, list):
        block_types = {b.get("type") for b in content if isinstance(b, dict)}
        if "tool_result" in block_types:
            role = "tool_result"
            text = ""  # tool_result lines have no narrative text
            tool_results = _extract_tool_results(content, structured=raw.get("toolUseResult"))
        else:
            role = "user"
            text = _flatten_user_blocks(content)
            tool_results = []
    else:
        # Defensive: unexpected content shape — keep as empty user turn with a marker.
        role = "user"
        text = ""
        tool_results = []

    return Turn(
        turn_number=0,
        uuid=raw.get("uuid", ""),
        parent_uuid=raw.get("parentUuid"),
        role=role,
        text=text,
        thinking="",
        tool_uses=[],
        tool_results=tool_results,
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=_parse_timestamp(raw.get("timestamp")),
        duration_ms=None,
        is_sidechain=bool(raw.get("isSidechain", False)),
    )


def _extract_tool_results(content: list, *, structured: dict | None) -> list[ToolResult]:
    """Extract ToolResult objects from a list of content blocks.

    `structured` is the parallel toolUseResult field; it's attached to every
    ToolResult in this turn because a JSONL line carries one toolUseResult
    even when there are multiple tool_result blocks. The decomposer can
    inspect it; the parser doesn't try to split.
    """
    results: list[ToolResult] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_result":
            continue
        raw_content = block.get("content")
        if isinstance(raw_content, str):
            content_str = raw_content
        elif isinstance(raw_content, list):
            content_str = "\n".join(
                b.get("text", "") for b in raw_content if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            content_str = ""
        results.append(
            ToolResult(
                tool_name="",  # filled by pairing pass
                tool_use_id=block.get("tool_use_id", ""),
                content=content_str,
                structured=structured,
                is_error=bool(block.get("is_error", False)),
            )
        )
    return results


def _flatten_user_blocks(content: list) -> str:
    """Join text blocks and inline image placeholders for a user-role list-content message."""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "image":
            source = block.get("source") or {}
            media_type = source.get("media_type", "?")
            data = source.get("data", "")
            size = len(data) if isinstance(data, str) else 0
            parts.append(f"<image:{media_type},{size}B>")
    return "\n".join(parts)
```

Then add a pairing pass to `parse_session`, after the loop and before turn numbering:

```python
    _pair_tool_results(turns)

    # Number turns 1-based ...
```

And implement `_pair_tool_results`:

```python
def _pair_tool_results(turns: list[Turn]) -> None:
    """Populate ToolResult.tool_name by matching tool_use_id against earlier ToolUses."""
    by_id: dict[str, str] = {}
    for turn in turns:
        for use in turn.tool_uses:
            if use.tool_use_id:
                by_id[use.tool_use_id] = use.tool_name
        for result in turn.tool_results:
            if result.tool_use_id and not result.tool_name:
                result.tool_name = by_id.get(result.tool_use_id, "")
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
```

Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): tool_result blocks with tool_name pairing"
```

---

## Task 9: User lines with mixed `[text, image]` content

**Files:**
- Modify: `tests/test_parser_claude_code.py`

The dispatch from Task 8 already handles this — the test just validates it.

- [ ] **Step 1: Add test**

```python
def test_user_line_with_text_and_image_blocks(write_jsonl):
    """Mixed [text, image] arrays (seen in real data) dispatch to role='user'."""
    content = [
        {"type": "text", "text": "look at this:"},
        {"type": "image", "source": {"media_type": "image/png", "data": "aGVsbG8="}},
    ]
    path = write_jsonl([make_user_line(uuid="u1", content=content)])
    trace = parse_session(path)
    assert len(trace.turns) == 1
    turn = trace.turns[0]
    assert turn.role == "user"
    assert "look at this:" in turn.text
    assert "<image:image/png," in turn.text


def test_user_line_with_only_text_block_list(write_jsonl):
    """Some user lines have content=[{type:text,...}] instead of a bare string."""
    content = [{"type": "text", "text": "hello from a list"}]
    path = write_jsonl([make_user_line(uuid="u1", content=content)])
    trace = parse_session(path)
    assert trace.turns[0].role == "user"
    assert trace.turns[0].text == "hello from a list"
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v -k "image or only_text_block"
```

Expected: both pass (Task 8's dispatch already handles this).

- [ ] **Step 3: Commit**

```bash
git add tests/test_parser_claude_code.py
git commit -m "test(parser): mixed [text, image] and text-block-list user content"
```

---

## Task 10: Parse `system` lines

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

System lines are synthetic notices Claude Code injects (compaction events, model swaps). They become Turns with `role="system"`.

- [ ] **Step 1: Add failing test**

```python
def test_system_line_becomes_system_turn(write_jsonl):
    line = {
        "type": "system",
        "uuid": "s1",
        "parentUuid": None,
        "isSidechain": False,
        "timestamp": "2026-05-13T02:00:00.000Z",
        "sessionId": "test-session",
        "content": "Compaction triggered at 95% context.",
    }
    path = write_jsonl([line])
    trace = parse_session(path)
    assert len(trace.turns) == 1
    turn = trace.turns[0]
    assert turn.role == "system"
    assert "Compaction" in turn.text
```

- [ ] **Step 2: Run test to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py::test_system_line_becomes_system_turn -v
```

Expected: failure (no Turn produced).

- [ ] **Step 3: Implement system dispatch**

In `parse_session`'s loop, add:
```python
        elif line_type == "system":
            turn = _parse_system_line(raw)
            if turn is not None:
                turns.append(turn)
```

Add helper:
```python
def _parse_system_line(raw: dict) -> Turn | None:
    """Build a Turn from a `type: "system"` line (compaction notices, model swaps)."""
    text = raw.get("content") or raw.get("message", {}).get("content") or ""
    if isinstance(text, list):
        text = _flatten_user_blocks(text)
    return Turn(
        turn_number=0,
        uuid=raw.get("uuid", ""),
        parent_uuid=raw.get("parentUuid"),
        role="system",
        text=str(text),
        thinking="",
        tool_uses=[],
        tool_results=[],
        usage=None,
        model=None,
        stop_reason=None,
        timestamp=_parse_timestamp(raw.get("timestamp")),
        duration_ms=None,
        is_sidechain=bool(raw.get("isSidechain", False)),
    )
```

- [ ] **Step 4: Run tests and commit**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): system lines"
```

---

## Task 11: Attachment classification

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

Spec §6: classify by payload-key shape, preserve `raw` verbatim, unknown shapes → `"other"` with no warning.

- [ ] **Step 1: Add failing tests**

```python
def _make_attachment_line(payload: dict, uuid: str = "att1") -> dict:
    return {
        "type": "attachment",
        "uuid": uuid,
        "parentUuid": None,
        "isSidechain": False,
        "timestamp": "2026-05-13T02:00:00.000Z",
        "sessionId": "test-session",
        "attachment": payload,
    }


def test_attachment_hook_output_classified(write_jsonl):
    payload = {
        "hookEvent": "SessionStart",
        "hookName": "SessionStart:startup",
        "stdout": '{"hookSpecificOutput": {"additionalContext": "some text"}}',
        "stderr": "",
        "exitCode": 0,
        "durationMs": 100,
    }
    path = write_jsonl([_make_attachment_line(payload)])
    trace = parse_session(path)
    assert len(trace.turns) == 0  # attachments are NOT turns
    assert len(trace.attachments) == 1
    a = trace.attachments[0]
    assert a.kind == "hook_output"
    assert a.raw == payload
    assert a.content == "some text"


def test_attachment_mcp_servers_classified(write_jsonl):
    payload = {
        "pendingMcpServers": True,
        "addedLines": ["github-mcp", "sentry-mcp"],
        "addedNames": ["github-mcp", "sentry-mcp"],
        "readdedNames": [],
        "removedNames": [],
    }
    path = write_jsonl([_make_attachment_line(payload)])
    trace = parse_session(path)
    assert trace.attachments[0].kind == "mcp_servers"


def test_attachment_skills_classified(write_jsonl):
    payload = {"skillCount": 3, "content": "- skill-a\n- skill-b\n- skill-c", "isInitial": True}
    path = write_jsonl([_make_attachment_line(payload)])
    trace = parse_session(path)
    a = trace.attachments[0]
    assert a.kind == "skills"
    assert a.content == "- skill-a\n- skill-b\n- skill-c"


def test_attachment_allowed_tools_classified(write_jsonl):
    payload = {"allowedTools": ["Read", "Edit"]}
    path = write_jsonl([_make_attachment_line(payload)])
    trace = parse_session(path)
    assert trace.attachments[0].kind == "allowed_tools"


def test_attachment_items_classified(write_jsonl):
    payload = {"itemCount": 2, "content": "items"}
    path = write_jsonl([_make_attachment_line(payload)])
    trace = parse_session(path)
    assert trace.attachments[0].kind == "items"


def test_attachment_unknown_shape_classified_as_other_no_warning(write_jsonl):
    payload = {"someFutureKey": "value"}
    path = write_jsonl([_make_attachment_line(payload)])
    trace = parse_session(path)
    assert trace.attachments[0].kind == "other"
    assert trace.attachments[0].raw == payload
    assert trace.warnings == []  # unknown attachment shapes do NOT warn (polymorphic by design)
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v -k "attachment"
```

Expected: 6 failures.

- [ ] **Step 3: Implement attachment dispatch and classifier**

Update import:
```python
from cctx.models import (
    Attachment,
    ParserError,
    SessionTrace,
    ToolResult,
    ToolUse,
    Turn,
    Usage,
)
```

In `parse_session`, declare `attachments: list[Attachment] = []` near `turns: list[Turn] = []`. Add to the dispatch loop:

```python
        elif line_type == "attachment":
            att = _parse_attachment_line(raw)
            if att is not None:
                attachments.append(att)
```

Pass `attachments=attachments` to the `SessionTrace(...)` construction.

Add helpers:

```python
def _parse_attachment_line(raw: dict) -> Attachment | None:
    """Build an Attachment from a `type: "attachment"` line.

    Classification is by payload-key shape, not by hookEvent (which is only
    present on hook-output attachments). Unknown shapes are preserved with
    kind="other" — no warning, attachments are inherently polymorphic.
    """
    payload = raw.get("attachment")
    if not isinstance(payload, dict):
        return None

    kind = _classify_attachment_shape(payload)
    content = _extract_attachment_content(kind, payload)
    timestamp = raw.get("timestamp")

    return Attachment(
        kind=kind,
        raw=payload,
        content=content,
        timestamp=_parse_timestamp(timestamp) if timestamp else None,
        parent_uuid=raw.get("parentUuid"),
    )


def _classify_attachment_shape(payload: dict) -> str:
    if "hookEvent" in payload:
        return "hook_output"
    if "pendingMcpServers" in payload:
        return "mcp_servers"
    if "skillCount" in payload:
        return "skills"
    if "allowedTools" in payload:
        return "allowed_tools"
    if "itemCount" in payload:
        return "items"
    return "other"


def _extract_attachment_content(kind: str, payload: dict) -> str | None:
    """Best-effort extraction of human-readable content from an attachment.

    Returns None when nothing useful is present.
    """
    if kind == "hook_output":
        stdout = payload.get("stdout") or ""
        try:
            parsed = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            return stdout or None
        hook_specific = parsed.get("hookSpecificOutput") or {}
        return hook_specific.get("additionalContext") or stdout or None

    if kind in ("skills", "items"):
        c = payload.get("content")
        return c if isinstance(c, str) and c else None

    return None
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
```

Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): attachment classification by payload-key shape"
```

---

## Task 12: Drop bookkeeping line types silently

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

Spec §5: drop `last-prompt`, `permission-mode`, `ai-title`, `custom-title`, `queue-operation`, `file-history-snapshot`, `pr-link` silently. They should NOT trigger unknown-type warnings.

- [ ] **Step 1: Add failing test**

```python
BOOKKEEPING_TYPES = [
    "last-prompt",
    "permission-mode",
    "ai-title",
    "custom-title",
    "queue-operation",
    "file-history-snapshot",
    "pr-link",
]


def test_bookkeeping_types_dropped_silently(write_jsonl):
    """Known bookkeeping types are dropped without warning."""
    lines = [{"type": t, "sessionId": "test"} for t in BOOKKEEPING_TYPES]
    lines.append(make_user_line(uuid="u1", content="real message"))
    path = write_jsonl(lines)
    trace = parse_session(path)
    assert len(trace.turns) == 1
    assert trace.turns[0].text == "real message"
    assert trace.warnings == []
```

- [ ] **Step 2: Run test to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py::test_bookkeeping_types_dropped_silently -v
```

Expected: failure — bookkeeping types currently produce warnings (after Task 13, but right now they fall through to nothing — actually this test currently passes by accident because the dispatch doesn't warn yet. Run anyway to confirm baseline).

- [ ] **Step 3: Add the bookkeeping set to the dispatch**

Define near the top of `cctx/parsers/claude_code.py`:
```python
_BOOKKEEPING_TYPES = frozenset({
    "last-prompt",
    "permission-mode",
    "ai-title",
    "custom-title",
    "queue-operation",
    "file-history-snapshot",
    "pr-link",
})
```

In `parse_session`'s loop, after the existing branches, add:
```python
        elif line_type in _BOOKKEEPING_TYPES:
            # Known bookkeeping — drop silently.
            continue
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): drop known bookkeeping line types silently"
```

---

## Task 13: Warn-and-skip for unknown line types

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

- [ ] **Step 1: Add failing tests**

```python
def test_unknown_line_type_produces_warning(write_jsonl):
    lines = [
        {"type": "tool_search_result", "uuid": "x1", "sessionId": "test"},
        {"type": "memory_write", "uuid": "x2", "sessionId": "test"},
        make_user_line(uuid="u1", content="real"),
    ]
    path = write_jsonl(lines)
    trace = parse_session(path)
    assert len(trace.turns) == 1
    codes = [w.code for w in trace.warnings]
    details = [w.detail for w in trace.warnings]
    assert codes == ["unknown_type", "unknown_type"]
    assert "tool_search_result" in details
    assert "memory_write" in details


def test_unknown_line_with_no_type_field_warns(write_jsonl):
    """A JSONL line missing the 'type' field is also unknown."""
    path = write_jsonl([{"uuid": "no-type"}])
    trace = parse_session(path)
    assert len(trace.warnings) == 1
    assert trace.warnings[0].code == "unknown_type"
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v -k "unknown"
```

Expected: failures — warnings list is empty.

- [ ] **Step 3: Implement warn-and-skip**

Update the parser. Add a `warnings: list[ParserWarning] = []` accumulator in `parse_session`. Modify the dispatch loop's else branch:

```python
        else:
            warnings.append(
                ParserWarning(
                    code="unknown_type",
                    detail=str(line_type) if line_type else "<missing>",
                    line_number=line_number,
                    path=jsonl_path,
                )
            )
```

Update the import:
```python
from cctx.models import (
    Attachment,
    ParserError,
    ParserWarning,
    SessionTrace,
    ToolResult,
    ToolUse,
    Turn,
    Usage,
)
```

Pass `warnings=warnings` to the `SessionTrace(...)` construction.

- [ ] **Step 4: Run tests and commit**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): warn-and-skip for unknown line types"
```

---

## Task 14: Malformed JSON and encoding handling

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

- [ ] **Step 1: Add failing tests**

```python
def test_malformed_json_line_warns_and_continues(tmp_path):
    """A bad JSON line in the middle is skipped with a warning; surrounding lines parse fine."""
    path = tmp_path / "broken.jsonl"
    good_line = json.dumps(make_user_line(uuid="u1", content="before"))
    bad_line = "{not valid json"
    after_line = json.dumps(make_user_line(uuid="u2", parent_uuid="u1", content="after"))
    path.write_text(good_line + "\n" + bad_line + "\n" + after_line + "\n")
    trace = parse_session(path)
    assert [t.text for t in trace.turns] == ["before", "after"]
    codes = [w.code for w in trace.warnings]
    assert codes == ["malformed_json"]
    assert trace.warnings[0].line_number == 2


def test_truncated_final_line_dropped_silently(tmp_path):
    """A final line lacking a newline AND failing JSON parse is silently dropped (interrupted write)."""
    path = tmp_path / "truncated.jsonl"
    good = json.dumps(make_user_line(uuid="u1", content="hi"))
    truncated = '{"type":"assistant","uu'  # cut off mid-line, no trailing newline
    path.write_text(good + "\n" + truncated)
    trace = parse_session(path)
    assert len(trace.turns) == 1
    assert trace.turns[0].text == "hi"
    # No warning for the truncated last line specifically.
    malformed = [w for w in trace.warnings if w.code == "malformed_json"]
    assert malformed == []
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v -k "malformed or truncated"
```

Expected: failures — currently we don't warn on bad JSON or distinguish truncation.

- [ ] **Step 3: Update `_iter_lines` and parser**

Replace `_iter_lines` with a version that signals truncation vs. malformed:

```python
def _iter_lines(path: Path):
    """Yield (line_number, parsed_dict_or_None, is_last_line_truncated).

    For a final line that lacks a newline AND fails JSON parse, the third
    tuple element is True — the caller can drop it silently. For
    mid-file JSON failures, the third element is False — the caller
    records a malformed_json warning.
    """
    raw_bytes = path.read_bytes()
    lines = raw_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)

    for i, line in enumerate(lines):
        line_number = i + 1
        is_last = (i == len(lines) - 1)
        ends_with_newline = line.endswith("\n")
        stripped = line.strip()
        if not stripped:
            continue
        try:
            yield line_number, json.loads(stripped), False
        except json.JSONDecodeError:
            truncated_final = is_last and not ends_with_newline
            yield line_number, None, truncated_final
```

Update the consumer loop in `parse_session`:

```python
    for line_number, raw, truncated in _iter_lines(jsonl_path):
        if raw is None:
            if not truncated:
                warnings.append(
                    ParserWarning(
                        code="malformed_json",
                        detail="failed to parse JSON",
                        line_number=line_number,
                        path=jsonl_path,
                    )
                )
            continue
        line_type = raw.get("type")
        # ... existing dispatch ...
```

- [ ] **Step 4: Run tests and commit**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): malformed JSON warn and truncated-final-line drop"
```

---

## Task 15: Populate `initial_context_tokens`

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

Spec §4: `initial_context_tokens` is `cache_creation_input_tokens` from the first assistant turn (sum of 5m + 1h). 0 if there are no assistant turns.

- [ ] **Step 1: Add failing tests**

```python
def test_initial_context_tokens_from_first_assistant(write_jsonl):
    path = write_jsonl([
        make_user_line(uuid="u1", content="hi"),
        make_assistant_line(
            uuid="a1", parent_uuid="u1", text="hello",
            cache_creation_5m=1000, cache_creation_1h=29000,
        ),
        make_assistant_line(  # later assistant turn should be ignored for this anchor
            uuid="a2", parent_uuid="a1", text="more",
            cache_creation_5m=0, cache_creation_1h=500,
        ),
    ])
    trace = parse_session(path)
    assert trace.initial_context_tokens == 30000


def test_initial_context_tokens_zero_when_no_assistant_turns(write_jsonl):
    path = write_jsonl([make_user_line(uuid="u1", content="hi then abandoned")])
    trace = parse_session(path)
    assert trace.initial_context_tokens == 0
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v -k "initial_context_tokens"
```

Expected: failure on the first test — currently always 0.

- [ ] **Step 3: Compute the anchor in `parse_session`**

After the loop but before constructing `SessionTrace`, add:

```python
    initial_context_tokens = 0
    for turn in turns:
        if turn.role == "assistant" and turn.usage is not None:
            initial_context_tokens = turn.usage.cache_creation_5m + turn.usage.cache_creation_1h
            break
```

Pass `initial_context_tokens=initial_context_tokens` to the `SessionTrace(...)` construction.

- [ ] **Step 4: Run tests and commit**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): initial_context_tokens from first assistant turn"
```

---

## Task 16: Populate `tool_names_loaded`, `primary_model`, `claude_code_version`, `cwd`

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

- [ ] **Step 1: Add failing tests**

```python
import collections


def test_tool_names_loaded_from_mcp_attachment_and_observed_uses(write_jsonl):
    mcp_attachment = {
        "type": "attachment",
        "uuid": "att1",
        "parentUuid": None,
        "isSidechain": False,
        "timestamp": "2026-05-13T02:00:00.000Z",
        "sessionId": "test",
        "attachment": {
            "pendingMcpServers": True,
            "addedNames": ["github-mcp", "sentry-mcp"],
        },
    }
    path = write_jsonl([
        mcp_attachment,
        make_assistant_line(uuid="a1", tool_uses=[
            make_tool_use_block("toolu_1", "Read"),
            make_tool_use_block("toolu_2", "Bash"),
        ]),
    ])
    trace = parse_session(path)
    assert sorted(trace.tool_names_loaded) == sorted(["github-mcp", "sentry-mcp", "Read", "Bash"])


def test_primary_model_is_most_frequent(write_jsonl):
    path = write_jsonl([
        make_assistant_line(uuid="a1", text="x", model="claude-sonnet-4-6"),
        make_assistant_line(uuid="a2", parent_uuid="a1", text="y", model="claude-sonnet-4-6"),
        make_assistant_line(uuid="a3", parent_uuid="a2", text="z", model="claude-opus-4-6"),
    ])
    trace = parse_session(path)
    assert trace.primary_model == "claude-sonnet-4-6"


def test_primary_model_none_with_no_assistant_turns(write_jsonl):
    path = write_jsonl([make_user_line(uuid="u1", content="hi")])
    trace = parse_session(path)
    assert trace.primary_model is None


def test_version_and_cwd_from_first_line_with_them(write_jsonl):
    path = write_jsonl([
        make_user_line(uuid="u1", content="hi", cwd="/Users/test/Projects/demo"),
        make_assistant_line(uuid="a1", parent_uuid="u1", text="hello", version="2.1.138"),
    ])
    trace = parse_session(path)
    assert trace.claude_code_version == "2.1.138"
    assert trace.cwd == "/Users/test/Projects/demo"
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v -k "tool_names_loaded or primary_model or version_and_cwd"
```

Expected: failures.

- [ ] **Step 3: Implement metadata computation**

After the existing post-loop computation, add a metadata pass. Pass the result to `SessionTrace(...)`.

```python
    # Metadata pass.
    primary_model = _most_common([t.model for t in turns if t.role == "assistant" and t.model])
    claude_code_version = _first_present_field(jsonl_path, "version", turns)
    observed_cwd = _first_present_field(jsonl_path, "cwd", turns) or project_path

    tool_names_loaded = _collect_tool_names(turns, attachments)
```

Add helpers:

```python
def _most_common(values: list[str]) -> str | None:
    """Return the most frequent value, or None if the list is empty."""
    if not values:
        return None
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0]


def _first_present_field(jsonl_path: Path, field_name: str, turns: list[Turn]) -> str | None:
    """Re-scan the file to find the first non-null value of a top-level field.

    Cheap: stops at first hit. Used for fields we don't store on Turn (cwd, version).
    """
    with jsonl_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            value = obj.get(field_name)
            if value:
                return str(value)
    return None


def _collect_tool_names(turns: list[Turn], attachments: list[Attachment]) -> list[str]:
    """Union of MCP names from pendingMcpServers attachments + names observed in tool_uses."""
    names: list[str] = []
    seen: set[str] = set()
    # MCP names from attachments.
    for att in attachments:
        if att.kind != "mcp_servers":
            continue
        for n in att.raw.get("addedNames", []) or []:
            if isinstance(n, str) and n not in seen:
                seen.add(n)
                names.append(n)
    # Observed tool uses.
    for turn in turns:
        for use in turn.tool_uses:
            if use.tool_name and use.tool_name not in seen:
                seen.add(use.tool_name)
                names.append(use.tool_name)
    return names
```

Pass through to `SessionTrace`:
```python
        primary_model=primary_model,
        claude_code_version=claude_code_version,
        cwd=observed_cwd,
        tool_names_loaded=tool_names_loaded,
```

- [ ] **Step 4: Run tests and commit**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): primary_model, tool_names_loaded, version, cwd metadata"
```

---

## Task 17: Enumerate `raw_tool_result_files`

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

Spec §8: list `<sid>/tool-results/*.txt` with sizes, do NOT read contents.

- [ ] **Step 1: Add failing tests**

```python
def test_raw_tool_result_files_enumerated(session_dir):
    sid = "abc123"
    jsonl = session_dir / f"{sid}.jsonl"
    jsonl.write_text("")
    tr_dir = session_dir / sid / "tool-results"
    tr_dir.mkdir(parents=True)
    (tr_dir / "a.txt").write_bytes(b"x" * 100)
    (tr_dir / "b.txt").write_bytes(b"y" * 250)

    trace = parse_session(jsonl)
    files = sorted(trace.raw_tool_result_files, key=lambda r: r.path.name)
    assert len(files) == 2
    assert files[0].path.name == "a.txt"
    assert files[0].size_bytes == 100
    assert files[0].tool_use_id is None  # v1: matching deferred
    assert files[1].size_bytes == 250


def test_raw_tool_result_files_empty_when_dir_missing(write_jsonl):
    path = write_jsonl([])
    trace = parse_session(path)
    assert trace.raw_tool_result_files == []
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v -k "raw_tool_result_files"
```

Expected: failures.

- [ ] **Step 3: Implement enumeration**

After the metadata pass, add:

```python
    raw_tool_result_files = _enumerate_raw_tool_result_files(jsonl_path)
```

Pass `raw_tool_result_files=raw_tool_result_files` to `SessionTrace`.

Update import:
```python
from cctx.models import (
    Attachment,
    ParserError,
    ParserWarning,
    RawToolResultFile,
    SessionTrace,
    ToolResult,
    ToolUse,
    Turn,
    Usage,
)
```

Add helper:
```python
def _enumerate_raw_tool_result_files(jsonl_path: Path) -> list[RawToolResultFile]:
    """List <sid>/tool-results/*.txt with sizes. Does NOT read contents."""
    sid = jsonl_path.stem
    tr_dir = jsonl_path.parent / sid / "tool-results"
    if not tr_dir.is_dir():
        return []
    return [
        RawToolResultFile(path=p, size_bytes=p.stat().st_size, tool_use_id=None)
        for p in sorted(tr_dir.glob("*.txt"))
    ]
```

- [ ] **Step 4: Run tests and commit**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): enumerate raw tool-result sidecar files without reading"
```

---

## Task 18: Subagent discovery and recursive parsing

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

Spec §7: glob `<sid>/subagents/agent-*.jsonl`, recursively call `parse_session`, set `parent_session_id` on each child.

- [ ] **Step 1: Add failing tests**

```python
def test_subagent_files_discovered_and_parsed(session_dir):
    sid = "parent-sid"
    jsonl = session_dir / f"{sid}.jsonl"
    jsonl.write_text(json.dumps(make_user_line(uuid="u1", content="hi", session_id=sid)) + "\n")

    sub_dir = session_dir / sid / "subagents"
    sub_dir.mkdir(parents=True)
    child_jsonl = sub_dir / "agent-aaa.jsonl"
    child_jsonl.write_text(
        json.dumps(make_user_line(uuid="cu1", content="subagent prompt", session_id="agent-aaa")) + "\n"
    )

    trace = parse_session(jsonl)
    assert len(trace.subagents) == 1
    child = trace.subagents[0]
    assert child.session_id == "agent-aaa"
    assert child.parent_session_id == sid
    assert len(child.turns) == 1


def test_subagents_empty_when_dir_missing(write_jsonl):
    path = write_jsonl([make_user_line(uuid="u1", content="hi")])
    trace = parse_session(path)
    assert trace.subagents == []


def test_subagent_meta_loaded_when_present(session_dir):
    sid = "parent-sid"
    jsonl = session_dir / f"{sid}.jsonl"
    jsonl.write_text("")
    sub_dir = session_dir / sid / "subagents"
    sub_dir.mkdir(parents=True)
    (sub_dir / "agent-aaa.jsonl").write_text("")
    (sub_dir / "agent-aaa.meta.json").write_text(json.dumps({"tool_use_id": "toolu_42"}))

    trace = parse_session(jsonl)
    assert len(trace.subagents) == 1
    assert trace.subagents[0].subagent_meta == {"tool_use_id": "toolu_42"}
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v -k "subagent"
```

Expected: failures.

- [ ] **Step 3: Implement subagent discovery in `parse_session`**

Add a `_depth` parameter for internal recursion tracking:

```python
def parse_session(
    session_path: Path,
    *,
    max_subagent_depth: int = 4,
    _depth: int = 0,
    _parent_session_id: str | None = None,
) -> SessionTrace:
    ...
```

After the metadata pass, before `SessionTrace(...)` construction:

```python
    subagents, subagent_parse_errors = _parse_subagents(
        jsonl_path, max_subagent_depth=max_subagent_depth, depth=_depth, parent_session_id=session_id,
    )
```

Read the session's own `parent_session_id` from the keyword argument (in the recursive case the parent passes it):

```python
    parent_session_id = _parent_session_id
```

If this is a child (depth > 0), also try to load `<sid>.meta.json`:

```python
    subagent_meta: dict = {}
    if _depth > 0:
        meta_path = jsonl_path.with_suffix(".meta.json")
        if meta_path.exists():
            try:
                subagent_meta = json.loads(meta_path.read_text())
            except json.JSONDecodeError:
                subagent_meta = {}
```

Pass through to SessionTrace.

Add the discovery helper:

```python
def _parse_subagents(
    parent_jsonl: Path, *, max_subagent_depth: int, depth: int, parent_session_id: str,
) -> tuple[list[SessionTrace], list[dict]]:
    """Discover and recursively parse subagent JSONLs.

    Returns (subagents, parse_errors). Each subagent trace has parent_session_id set.
    """
    if depth >= max_subagent_depth:
        return [], []

    sid = parent_jsonl.stem
    sub_dir = parent_jsonl.parent / sid / "subagents"
    if not sub_dir.is_dir():
        return [], []

    subagents: list[SessionTrace] = []
    errors: list[dict] = []
    for child_jsonl in sorted(sub_dir.glob("agent-*.jsonl")):
        try:
            child = parse_session(
                child_jsonl,
                max_subagent_depth=max_subagent_depth,
                _depth=depth + 1,
                _parent_session_id=parent_session_id,
            )
            subagents.append(child)
        except ParserError as e:
            errors.append({"path": child_jsonl, "reason": e.reason})
    return subagents, errors
```

- [ ] **Step 4: Run tests and commit**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): discover and recursively parse subagent files"
```

---

## Task 19: Link `subagent_session_id` on parent `Agent` ToolUses

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

Spec §7: after parsing children, look up the originating `Agent` tool_use in the parent and stamp `subagent_session_id`.

- [ ] **Step 1: Add failing tests**

```python
def test_agent_tool_use_linked_to_subagent_via_meta_tool_use_id(session_dir):
    sid = "parent-sid"
    jsonl = session_dir / f"{sid}.jsonl"
    # Parent has an Agent tool_use with id toolu_42.
    parent_assistant = make_assistant_line(
        uuid="a1",
        tool_uses=[make_tool_use_block("toolu_42", "Agent", {"subagent_type": "doc-auditor"})],
        session_id=sid,
    )
    jsonl.write_text(json.dumps(parent_assistant) + "\n")

    # Child file with matching meta.
    sub_dir = session_dir / sid / "subagents"
    sub_dir.mkdir(parents=True)
    (sub_dir / "agent-aaa.jsonl").write_text(
        json.dumps(make_user_line(uuid="cu1", content="prompt", session_id="agent-aaa")) + "\n"
    )
    (sub_dir / "agent-aaa.meta.json").write_text(json.dumps({"tool_use_id": "toolu_42"}))

    trace = parse_session(jsonl)
    assert trace.turns[0].tool_uses[0].subagent_session_id == "agent-aaa"


def test_orphan_agent_call_warns_and_keeps_subagent_session_id_none(session_dir):
    sid = "parent-sid"
    jsonl = session_dir / f"{sid}.jsonl"
    parent_assistant = make_assistant_line(
        uuid="a1",
        tool_uses=[make_tool_use_block("toolu_orphan", "Agent", {"subagent_type": "x"})],
        session_id=sid,
    )
    jsonl.write_text(json.dumps(parent_assistant) + "\n")
    # No subagents/ dir at all.

    trace = parse_session(jsonl)
    assert trace.turns[0].tool_uses[0].subagent_session_id is None
    codes = [w.code for w in trace.warnings]
    assert "orphan_agent_call" in codes


def test_orphan_subagent_file_warns_but_is_kept(session_dir):
    sid = "parent-sid"
    jsonl = session_dir / f"{sid}.jsonl"
    # Parent has NO Agent tool_uses.
    jsonl.write_text(json.dumps(make_user_line(uuid="u1", content="hi", session_id=sid)) + "\n")

    sub_dir = session_dir / sid / "subagents"
    sub_dir.mkdir(parents=True)
    (sub_dir / "agent-stray.jsonl").write_text(
        json.dumps(make_user_line(uuid="cu1", content="stray", session_id="agent-stray")) + "\n"
    )

    trace = parse_session(jsonl)
    assert len(trace.subagents) == 1  # kept
    assert trace.subagents[0].parent_session_id == sid
    codes = [w.code for w in trace.warnings]
    assert "orphan_subagent_file" in codes
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v -k "linked_to_subagent or orphan"
```

Expected: failures.

- [ ] **Step 3: Implement linking and orphan detection**

After `subagents, subagent_parse_errors = _parse_subagents(...)`, add a linking pass:

```python
    _link_subagents(turns, subagents, warnings, jsonl_path)
```

Add helper:

```python
def _link_subagents(
    turns: list[Turn],
    subagents: list[SessionTrace],
    warnings: list[ParserWarning],
    path: Path,
) -> None:
    """Stamp ToolUse.subagent_session_id and emit orphan warnings.

    Linking strategy (spec §7):
      1. Exact: child.subagent_meta["tool_use_id"] matches a parent ToolUse.tool_use_id.
      2. Fallback: not implemented in v1; orphans warn.

    Both directions of orphan are warned:
      - orphan_agent_call: parent has an Agent ToolUse with no matching child.
      - orphan_subagent_file: child exists but no parent ToolUse claimed it.
    """
    # Index parent Agent tool_uses by tool_use_id.
    agent_uses_by_id: dict[str, ToolUse] = {}
    for turn in turns:
        for use in turn.tool_uses:
            if use.tool_name == "Agent" and use.tool_use_id:
                agent_uses_by_id[use.tool_use_id] = use

    matched_use_ids: set[str] = set()
    for child in subagents:
        meta_tool_use_id = (child.subagent_meta or {}).get("tool_use_id")
        if meta_tool_use_id and meta_tool_use_id in agent_uses_by_id:
            agent_uses_by_id[meta_tool_use_id].subagent_session_id = child.session_id
            matched_use_ids.add(meta_tool_use_id)
        else:
            warnings.append(
                ParserWarning(
                    code="orphan_subagent_file",
                    detail=f"subagent {child.session_id} has no matching parent Agent tool_use",
                    path=path,
                )
            )

    # Agent tool_uses that never got linked.
    for use_id, use in agent_uses_by_id.items():
        if use_id not in matched_use_ids:
            warnings.append(
                ParserWarning(
                    code="orphan_agent_call",
                    detail=f"Agent tool_use {use_id} has no matching subagent file",
                    path=path,
                )
            )
```

- [ ] **Step 4: Run tests and commit**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): link subagent_session_id and emit orphan warnings"
```

---

## Task 20: `max_subagent_depth` circuit breaker

**Files:**
- Modify: `cctx/parsers/claude_code.py`
- Modify: `tests/test_parser_claude_code.py`

- [ ] **Step 1: Add failing test**

```python
def test_max_subagent_depth_circuit_breaker(session_dir):
    """Nested subagents beyond max_subagent_depth are not parsed and a warning is emitted."""
    sid = "root"
    jsonl = session_dir / f"{sid}.jsonl"
    jsonl.write_text("")

    # Build a chain: root → child1 → child2
    sub1 = session_dir / sid / "subagents"
    sub1.mkdir(parents=True)
    (sub1 / "agent-child1.jsonl").write_text("")

    sub2 = session_dir / sid / "subagents" / "agent-child1" / "subagents"
    sub2.mkdir(parents=True)
    (sub2 / "agent-child2.jsonl").write_text("")

    # max_subagent_depth=1 → root parses child1 but stops before child2.
    trace = parse_session(jsonl, max_subagent_depth=1)
    assert len(trace.subagents) == 1
    child1 = trace.subagents[0]
    assert child1.subagents == []  # not recursed into
    # Warning emitted on child1.
    depth_warnings = [w for w in child1.warnings if w.code == "max_subagent_depth"]
    assert len(depth_warnings) == 1
```

- [ ] **Step 2: Run test to confirm failure**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py::test_max_subagent_depth_circuit_breaker -v
```

Expected: failure — depth check is silent currently.

- [ ] **Step 3: Add warning when depth cap hit**

In `_parse_subagents`, replace the early return with:

```python
    if depth >= max_subagent_depth:
        sub_dir = parent_jsonl.parent / parent_jsonl.stem / "subagents"
        if sub_dir.is_dir() and any(sub_dir.glob("agent-*.jsonl")):
            return [], [{"path": sub_dir, "reason": "max_subagent_depth reached"}]
        return [], []
```

That puts an entry in `subagent_parse_errors`, but the test wants it on `warnings`. Update the design: emit a `ParserWarning(code="max_subagent_depth")` from the parent's `parse_session`. Pass `warnings` in by reference.

Cleanest approach: have `parse_session` accept an internal `_warnings_sink` parameter and have `_parse_subagents` add to it.

Actually simpler: just have `_parse_subagents` return a third value — warnings to add to the parent. Update its signature:

```python
def _parse_subagents(
    parent_jsonl: Path, *, max_subagent_depth: int, depth: int, parent_session_id: str,
) -> tuple[list[SessionTrace], list[dict], list[ParserWarning]]:
    if depth >= max_subagent_depth:
        sub_dir = parent_jsonl.parent / parent_jsonl.stem / "subagents"
        has_children = sub_dir.is_dir() and any(sub_dir.glob("agent-*.jsonl"))
        if has_children:
            return [], [], [
                ParserWarning(
                    code="max_subagent_depth",
                    detail=f"depth {depth} reached at {sub_dir}; raise max_subagent_depth to recurse deeper",
                    path=parent_jsonl,
                )
            ]
        return [], [], []
    # ... rest unchanged ...
    return subagents, errors, []
```

In `parse_session`:
```python
    subagents, subagent_parse_errors, depth_warnings = _parse_subagents(
        jsonl_path, max_subagent_depth=max_subagent_depth, depth=_depth, parent_session_id=session_id,
    )
    warnings.extend(depth_warnings)
```

- [ ] **Step 4: Run tests and commit**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py -v
.venv/bin/ruff check cctx tests && .venv/bin/ruff format cctx tests
git add cctx/parsers/claude_code.py tests/test_parser_claude_code.py
git commit -m "feat(parser): max_subagent_depth circuit breaker with warning"
```

---

## Task 21: Performance benchmark test

**Files:**
- Modify: `tests/test_parser_claude_code.py`

Spec §10.2: parse a 6MB session in under 500ms.

- [ ] **Step 1: Add the benchmark test**

```python
import time


def test_performance_budget_6mb_under_500ms(write_jsonl):
    """Synthetic 6MB session must parse in under 500ms on a modern laptop.

    This is a soft guardrail: if the budget is exceeded, the obvious lever is
    swapping `json` for `orjson` or `msgspec`. Test will be skipped on CI
    without performance machines — uses pytest.mark.benchmark when present.
    """
    # Build ~6MB of synthetic lines: assistants with ~12KB text each.
    big_text = "x" * 12_000
    target_bytes = 6 * 1024 * 1024
    lines: list[dict] = []
    parent_uuid = None
    accumulated = 0
    i = 0
    while accumulated < target_bytes:
        a = make_assistant_line(uuid=f"a{i}", parent_uuid=parent_uuid, text=big_text)
        lines.append(a)
        parent_uuid = f"a{i}"
        accumulated += len(json.dumps(a))
        i += 1

    path = write_jsonl(lines)
    actual_size = path.stat().st_size
    assert actual_size >= 6 * 1024 * 1024

    start = time.perf_counter()
    trace = parse_session(path)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(trace.turns) == len(lines)
    assert elapsed_ms < 500, f"parsed {actual_size / 1_000_000:.2f}MB in {elapsed_ms:.1f}ms (budget: 500ms)"
```

- [ ] **Step 2: Run the benchmark**

```bash
.venv/bin/pytest tests/test_parser_claude_code.py::test_performance_budget_6mb_under_500ms -v
```

Expected: pass. If it fails, the parser needs optimization (likely candidates: switch `json.loads` to `orjson.loads`, or pre-compile the dispatch).

- [ ] **Step 3: Commit**

```bash
git add tests/test_parser_claude_code.py
git commit -m "test(parser): 6MB-in-under-500ms performance budget"
```

---

## Task 22: Anonymization script for real-data fixtures

**Files:**
- Create: `scripts/anonymize_fixture.py`
- Create: `tests/fixtures/real/.gitkeep`

This script makes capturing tier-1 fixtures from `~/.claude/projects/` reproducible.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Anonymize a Claude Code session JSONL for use as a test fixture.

Usage:
    scripts/anonymize_fixture.py <source.jsonl> <destination.jsonl>

Behavior:
- Replaces user home paths (/Users/<name>/...) with /Users/test/...
- Replaces session UUIDs and tool_use_ids with deterministic IDs (sha1-truncated).
- Truncates toolUseResult.file.content fields longer than 200 chars.
- Scrubs git branch names to "test-branch".
- Preserves all structural shapes (types, keys, sizes).

Also copies the sibling <session-id>/ directory (subagents + tool-results)
if present, with the same transformations applied.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

_HOME_PATH = re.compile(r"/Users/[^/\"]+")


def _stable_id(prefix: str, original: str) -> str:
    h = hashlib.sha1(original.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{h}"


def _walk(obj):
    """Yield (parent, key_or_index, value) for every node in a nested structure."""
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            yield obj, k, v
            yield from _walk(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield obj, i, v
            yield from _walk(v)


def anonymize(line: dict) -> dict:
    """Return an anonymized copy of one parsed JSONL line."""
    out = json.loads(json.dumps(line))  # deep copy

    # Top-level scrubs.
    if "cwd" in out:
        out["cwd"] = _HOME_PATH.sub("/Users/test", out["cwd"])
    if "gitBranch" in out and out["gitBranch"] not in (None, "HEAD"):
        out["gitBranch"] = "test-branch"

    # Walk and transform.
    for parent, key, value in _walk(out):
        if isinstance(value, str):
            parent[key] = _HOME_PATH.sub("/Users/test", value)
        elif isinstance(value, dict):
            # Truncate file.content > 200 chars.
            if key == "file" and isinstance(value, dict) and isinstance(value.get("content"), str):
                if len(value["content"]) > 200:
                    value["content"] = value["content"][:200] + "...[truncated]"

    return out


def anonymize_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("r", encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # drop malformed lines from the fixture
            fout.write(json.dumps(anonymize(obj)) + "\n")


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 1

    src = Path(sys.argv[1]).resolve()
    dst = Path(sys.argv[2]).resolve()

    if not src.exists():
        print(f"source not found: {src}", file=sys.stderr)
        return 1

    anonymize_file(src, dst)

    # Copy sibling directory if present.
    sibling = src.parent / src.stem
    if sibling.is_dir():
        dst_sibling = dst.parent / dst.stem
        if dst_sibling.exists():
            shutil.rmtree(dst_sibling)
        dst_sibling.mkdir(parents=True)
        for sub_jsonl in (sibling / "subagents").glob("*.jsonl") if (sibling / "subagents").exists() else []:
            anonymize_file(sub_jsonl, dst_sibling / "subagents" / sub_jsonl.name)
        # Meta files copy verbatim.
        for meta in (sibling / "subagents").glob("*.meta.json") if (sibling / "subagents").exists() else []:
            (dst_sibling / "subagents" / meta.name).parent.mkdir(parents=True, exist_ok=True)
            (dst_sibling / "subagents" / meta.name).write_text(meta.read_text())
        # tool-results/ copy verbatim (no anonymization — they're size-only references).
        tr = sibling / "tool-results"
        if tr.exists():
            dst_tr = dst_sibling / "tool-results"
            dst_tr.mkdir(parents=True, exist_ok=True)
            for f in tr.glob("*.txt"):
                shutil.copy2(f, dst_tr / f.name)

    print(f"anonymized {src} -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Make it executable and create the fixtures dir**

```bash
chmod +x scripts/anonymize_fixture.py
mkdir -p tests/fixtures/real tests/fixtures/synthetic
touch tests/fixtures/real/.gitkeep tests/fixtures/synthetic/.gitkeep
```

- [ ] **Step 3: Smoke-test the script against the live JSONL of this session**

(Optional — for development verification. Don't commit the resulting fixture from this step.)

```bash
ls ~/.claude/projects/-Users-bryan-Projects-cctx/*.jsonl | head -1
# Pick one of those files and try:
.venv/bin/python scripts/anonymize_fixture.py \
    <(some-path>.jsonl) /tmp/test-fixture.jsonl
head -1 /tmp/test-fixture.jsonl
```

Expected: a valid JSONL line with `/Users/test/...` instead of the original home path.

- [ ] **Step 4: Commit**

```bash
git add scripts/anonymize_fixture.py tests/fixtures/
git commit -m "chore: anonymization script for capturing real-session fixtures"
```

---

## Task 23: Capture and commit tier-1 real fixtures

**Files:**
- Create: `tests/fixtures/real/<5–6 anonymized sessions>`
- Create: `tests/test_parser_integration.py`

This task captures actual sessions from `~/.claude/projects/`, runs them through the parser, and confirms the parser produces non-empty, sensible output without warnings (other than expected ones). This is the tier-1 "real data" check from spec §10.1.

- [ ] **Step 1: Capture fixtures covering the matrix**

Spec §10.1 fixture matrix:
- small session (~25 turns, no subagents/sidecars)
- medium session with subagents
- session with `SessionStart:compact` attachment
- session with mixed `[text, image]` user array
- session with sidecar files
- empty/abandoned user-only session

Find candidates with a short script:

```bash
.venv/bin/python <<'PY'
import json
from pathlib import Path
root = Path.home() / ".claude/projects"
for proj in sorted(root.iterdir()):
    if not proj.is_dir(): continue
    for jsonl in sorted(proj.glob("*.jsonl")):
        sid = jsonl.stem
        sibling = proj / sid
        sub_dir = sibling / "subagents"
        tr_dir = sibling / "tool-results"
        # Quick stats.
        lines = jsonl.read_text(errors="replace").splitlines()
        n = len(lines)
        size_kb = jsonl.stat().st_size // 1024
        has_compact = any('"SessionStart:compact"' in l for l in lines)
        has_image = any('"type":"image"' in l for l in lines)
        n_subs = len(list(sub_dir.glob("agent-*.jsonl"))) if sub_dir.is_dir() else 0
        n_sidecars = len(list(tr_dir.glob("*.txt"))) if tr_dir.is_dir() else 0
        print(f"{proj.name}/{sid} | {n:4d}L {size_kb:>5}KB | subs={n_subs} sidecars={n_sidecars} compact={has_compact} image={has_image}")
PY
```

Manually select 5–6 covering the matrix above. For each chosen session:

```bash
.venv/bin/python scripts/anonymize_fixture.py \
    ~/.claude/projects/<proj>/<sid>.jsonl \
    tests/fixtures/real/<short-descriptive-name>.jsonl
```

Suggested names:
- `small-no-subagents.jsonl`
- `medium-with-subagents.jsonl`
- `with-compact.jsonl`
- `with-image.jsonl`
- `with-sidecars.jsonl`
- `user-only-abandoned.jsonl`

- [ ] **Step 2: Write integration test**

`tests/test_parser_integration.py`:
```python
"""Integration tests: parse real (anonymized) sessions and assert basic invariants."""

from __future__ import annotations

from pathlib import Path

import pytest

from cctx.parsers.claude_code import parse_session

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "real"


@pytest.mark.parametrize("fixture_path", sorted(FIXTURE_DIR.glob("*.jsonl")), ids=lambda p: p.name)
def test_real_fixture_parses_without_unknown_type_warnings(fixture_path):
    """Every real fixture should parse to a non-error SessionTrace.

    Unknown-type warnings indicate the parser is missing a line type — those
    fail this test. Other warnings (orphan, malformed_json on damaged lines)
    are acceptable and recorded.
    """
    trace = parse_session(fixture_path)

    unknown_warnings = [w for w in trace.warnings if w.code == "unknown_type"]
    assert unknown_warnings == [], (
        f"{fixture_path.name}: unexpected unknown_type warnings: "
        + ", ".join(w.detail for w in unknown_warnings)
    )


@pytest.mark.parametrize("fixture_path", sorted(FIXTURE_DIR.glob("*.jsonl")), ids=lambda p: p.name)
def test_real_fixture_invariants(fixture_path):
    trace = parse_session(fixture_path)

    # Turn numbers are 1-based contiguous.
    for i, turn in enumerate(trace.turns, start=1):
        assert turn.turn_number == i, f"non-contiguous turn_number at index {i - 1}"

    # tool_results have tool_name resolved when their tool_use_id matches an earlier tool_use.
    used_ids = {use.tool_use_id for turn in trace.turns for use in turn.tool_uses}
    for turn in trace.turns:
        for r in turn.tool_results:
            if r.tool_use_id in used_ids:
                assert r.tool_name != "", f"tool_result with id {r.tool_use_id} unpaired"

    # If start/end set, ordering holds.
    if trace.start_time and trace.end_time:
        assert trace.start_time <= trace.end_time

    # Subagents have parent_session_id pointing back.
    for sub in trace.subagents:
        assert sub.parent_session_id == trace.session_id
```

- [ ] **Step 3: Run integration tests**

```bash
.venv/bin/pytest tests/test_parser_integration.py -v
```

Expected: all parametric cases pass. If any unknown_type warnings appear, the parser is missing a real-world line type — investigate and add a dispatch case (probably bookkeeping; extend `_BOOKKEEPING_TYPES`).

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/real/ tests/test_parser_integration.py
git commit -m "test: tier-1 anonymized real-session fixtures and invariants"
```

---

## Task 24: Synthetic adversarial fixtures

**Files:**
- Create: `tests/fixtures/synthetic/*.jsonl`
- Modify: `tests/test_parser_integration.py`

Spec §10.1 tier-2: hand-built minimal JSONL files exercising adversarial cases not naturally covered by inline test JSONL.

Most adversarial cases are already covered by the inline tests built during tasks 4–20. This task ensures permanent fixture files exist for cases worth re-running on every commit and worth eyeballing as documentation.

- [ ] **Step 1: Create the synthetic fixtures**

For each, write a small Python script-let inside the file's docstring or comment header is fine; the actual file is hand-built JSONL.

`tests/fixtures/synthetic/malformed_middle.jsonl`:
```
{"type":"user","uuid":"u1","parentUuid":null,"isSidechain":false,"timestamp":"2026-05-13T02:00:00.000Z","sessionId":"test","message":{"role":"user","content":"before"}}
{not valid json
{"type":"user","uuid":"u2","parentUuid":"u1","isSidechain":false,"timestamp":"2026-05-13T02:00:01.000Z","sessionId":"test","message":{"role":"user","content":"after"}}
```

`tests/fixtures/synthetic/truncated_final_line.jsonl`:
```
{"type":"user","uuid":"u1","parentUuid":null,"isSidechain":false,"timestamp":"2026-05-13T02:00:00.000Z","sessionId":"test","message":{"role":"user","content":"complete"}}
{"type":"assistant","uuid":"a1","parentUuid":"u1","isSidech
```
(Note: no trailing newline on the last line.)

`tests/fixtures/synthetic/unknown_type.jsonl`:
```
{"type":"tool_search_result","uuid":"x1","sessionId":"test"}
{"type":"user","uuid":"u1","parentUuid":null,"isSidechain":false,"timestamp":"2026-05-13T02:00:00.000Z","sessionId":"test","message":{"role":"user","content":"hi"}}
```

`tests/fixtures/synthetic/bookkeeping_only.jsonl`:
```
{"type":"last-prompt","sessionId":"test"}
{"type":"permission-mode","sessionId":"test","permissionMode":"default"}
{"type":"ai-title","sessionId":"test","aiTitle":"x"}
```

`tests/fixtures/synthetic/unknown_attachment_shape.jsonl`:
```
{"type":"attachment","uuid":"att1","parentUuid":null,"isSidechain":false,"timestamp":"2026-05-13T02:00:00.000Z","sessionId":"test","attachment":{"someFutureKey":"value","otherFutureKey":123}}
```

- [ ] **Step 2: Add a parametric integration test**

Append to `tests/test_parser_integration.py`:

```python
SYNTHETIC_DIR = Path(__file__).parent / "fixtures" / "synthetic"


def test_synthetic_malformed_middle_warns_continues_parses_both_sides():
    trace = parse_session(SYNTHETIC_DIR / "malformed_middle.jsonl")
    assert [t.text for t in trace.turns] == ["before", "after"]
    assert any(w.code == "malformed_json" for w in trace.warnings)


def test_synthetic_truncated_final_line_silently_dropped():
    trace = parse_session(SYNTHETIC_DIR / "truncated_final_line.jsonl")
    assert len(trace.turns) == 1
    # No malformed_json warning for the truncated last line.
    assert not any(w.code == "malformed_json" for w in trace.warnings)


def test_synthetic_unknown_type_warns():
    trace = parse_session(SYNTHETIC_DIR / "unknown_type.jsonl")
    assert any(w.code == "unknown_type" and w.detail == "tool_search_result" for w in trace.warnings)


def test_synthetic_bookkeeping_only_no_warnings():
    trace = parse_session(SYNTHETIC_DIR / "bookkeeping_only.jsonl")
    assert trace.turns == []
    assert trace.warnings == []
    assert trace.start_time is None
    assert trace.end_time is None


def test_synthetic_unknown_attachment_shape_no_warning():
    trace = parse_session(SYNTHETIC_DIR / "unknown_attachment_shape.jsonl")
    assert len(trace.attachments) == 1
    assert trace.attachments[0].kind == "other"
    assert trace.warnings == []
```

- [ ] **Step 3: Run integration tests**

```bash
.venv/bin/pytest tests/test_parser_integration.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/synthetic/ tests/test_parser_integration.py
git commit -m "test: tier-2 synthetic adversarial fixtures"
```

---

## Task 25: Final verification

**Files:**
- None modified; this is a verification task.

- [ ] **Step 1: Full test suite**

```bash
.venv/bin/pytest -v
```

Expected: 100% pass.

- [ ] **Step 2: Lint clean**

```bash
.venv/bin/ruff check cctx tests scripts
.venv/bin/ruff format --check cctx tests scripts
```

Expected: no issues.

- [ ] **Step 3: Coverage spot check**

Confirm by reading the parser file that every spec §5 line-type case has a corresponding test:

| Spec line type | Test |
|---|---|
| `assistant` (text/thinking) | Task 6 |
| `assistant` (tool_use) | Task 7 |
| `user` (string) | Task 5 |
| `user` ([text]) | Task 9 |
| `user` ([image, text]) | Task 9 |
| `user` ([tool_result]) | Task 8 |
| `system` | Task 10 |
| `attachment` (5 kinds + other) | Task 11 |
| bookkeeping types | Task 12 |
| unknown types | Task 13 |
| malformed JSON | Task 14 |
| truncated final | Task 14 |
| iterations sum | Task 6 (via factory's default iterations) |
| initial_context_tokens | Task 15 |
| primary_model / version / cwd | Task 16 |
| tool_names_loaded | Task 16 |
| raw_tool_result_files | Task 17 |
| subagent discovery | Task 18 |
| subagent linking | Task 19 |
| orphan handling | Task 19 |
| max_subagent_depth | Task 20 |
| performance budget | Task 21 |
| real fixtures | Task 23 |
| synthetic adversarial | Task 24 |

- [ ] **Step 4: Push to remote**

```bash
git push origin main
```

- [ ] **Step 5: Mark the implementation done**

Update the spec's status from "approved through brainstorming, awaiting implementation" to "implemented; see commits on main from <date>." This is a small edit to `docs/superpowers/specs/2026-05-12-claude-code-parser-design.md`.

```bash
git add docs/superpowers/specs/2026-05-12-claude-code-parser-design.md
git commit -m "docs: mark parser spec as implemented"
git push origin main
```

---

## Notes for the implementer

- **TDD discipline:** every task in 5–20 follows "write failing test → confirm red → implement → confirm green → commit." Don't skip the red-confirm step; tests that "pass" without an implementation are testing the wrong thing.
- **Don't add features:** if a step says "implement the dispatch for X," do only that. Other functionality is in later tasks. The plan accumulates incrementally.
- **Don't add abstractions:** the parser is one file. If you find yourself wanting to extract a class hierarchy, stop — it's not needed.
- **Don't tokenize:** every `token_count` field stays at 0. The tokenizer is a separate module in a future plan.
- **Don't read sidecar tool-result files:** spec §8 — they're listed, not read. Reading them is the decomposer's job.
- **Commit per task:** the plan is structured so each task ends in a green test suite. Commits are cheap; granular history is the point.
- **If a real fixture surfaces a missing case** (an unknown line type, a content-block variant we didn't anticipate), don't shoehorn it. Add a new dispatch case in the parser with its own test, then re-run.
