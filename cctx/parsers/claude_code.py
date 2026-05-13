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
