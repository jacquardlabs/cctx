"""Shared data model for cctx.

All dataclasses live here. Pure data containers; no behavior except
the module-level group_into_exchanges() helper.

No imports from: anthropic, click, cctx.parsers, cctx.analyzers,
cctx.renderers, cctx.exporters, cctx.tokenizer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Low-level building blocks
# ---------------------------------------------------------------------------


@dataclass
class Usage:
    """Token usage for a single assistant API call."""

    input_tokens: int
    output_tokens: int
    cache_creation_5m: int  # ephemeral_5m_input_tokens
    cache_creation_1h: int  # ephemeral_1h_input_tokens
    cache_read: int
    service_tier: str | None  # "standard" | "priority" | ...


@dataclass
class ToolUse:
    """A tool_use content block inside an assistant turn."""

    tool_name: str
    tool_use_id: str
    tool_input: dict
    token_count: int = 0
    subagent_session_id: str | None = None  # set when tool_name == "Agent" and child found


@dataclass
class ToolResult:
    """A tool_result content block inside a user turn.

    content is always populated from inline JSONL content — sidecar files
    are NOT the source of truth.
    """

    tool_name: str  # resolved by pairing on tool_use_id
    tool_use_id: str
    content: str  # inline content; always populated
    structured: dict | None  # parallel toolUseResult field (bash, file, etc.)
    is_error: bool
    token_count: int = 0


@dataclass
class Turn:
    """One JSONL line converted to a canonical turn.

    Required fields precede fields with defaults. All nullable required fields
    (parent_uuid, usage, model, stop_reason, duration_ms) have no default —
    callers must pass them explicitly.
    """

    turn_number: int  # 1-based index in SessionTrace.turns
    uuid: str  # JSONL line's uuid
    parent_uuid: str | None
    role: str  # "user" | "assistant" | "tool_result" | "system"
    text: str  # flattened text; image blocks → "<image:{media_type},{N}B>"
    thinking: str  # extended thinking is its own cost category
    tool_uses: list[ToolUse]
    tool_results: list[ToolResult]
    usage: Usage | None  # assistant turns only
    model: str | None  # assistant turns only
    stop_reason: str | None  # "end_turn" | "tool_use" | "stop_sequence" | None
    timestamp: datetime  # tz-aware UTC
    duration_ms: int | None  # gap to next turn; None for the last turn
    # --- defaulted fields ---
    token_count: int = 0  # filled by tokenizer pass
    is_sidechain: bool = False  # defensive insurance against future format drift
    error: str | None = None  # set when isApiErrorMessage was true


@dataclass
class Attachment:
    """A classified attachment line (type == "attachment" in JSONL)."""

    kind: str  # "hook_output"|"mcp_servers"|"skills"|"allowed_tools"|"items"|"other"
    raw: dict  # original attachment payload, verbatim
    content: str | None  # convenience: extracted text content if any
    timestamp: datetime | None
    parent_uuid: str | None


@dataclass
class RawToolResultFile:
    """A sidecar tool-result file discovered on disk (NOT read by the parser)."""

    path: Path
    size_bytes: int
    tool_use_id: str | None  # always None in v1; matching deferred to v1.1


# ---------------------------------------------------------------------------
# Error / warning types
# ---------------------------------------------------------------------------


class ParserError(Exception):
    """Hard parse failure — only raised on unreadable files."""

    def __init__(self, reason: str, *, path: Path, line_number: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.path = path
        self.line_number = line_number


@dataclass
class ParserWarning:
    """Soft parse failure recorded on SessionTrace.warnings."""

    code: str  # "unknown_type"|"malformed_json"|"orphan_agent_call"|...
    detail: str
    line_number: int | None = None
    path: Path | None = None


# ---------------------------------------------------------------------------
# Session-level aggregate
# ---------------------------------------------------------------------------


@dataclass
class SessionTrace:
    """Fully-parsed session; every other module works from this, never raw JSONL."""

    session_id: str
    parent_session_id: str | None  # set on subagent traces
    project_path: str  # decoded from dir name: "-Users-bryan-..." → "/Users/bryan/..."
    cwd: str  # actual cwd observed on the lines
    primary_model: str | None  # most-frequent model; None if no assistant turns
    claude_code_version: str | None
    turns: list[Turn]
    subagents: list[SessionTrace]
    attachments: list[Attachment]
    raw_tool_result_files: list[RawToolResultFile]
    initial_context_tokens: int  # cache_creation_input_tokens from first assistant turn
    tool_names_loaded: list[str]  # union of MCP names + names seen in tool_uses
    start_time: datetime | None  # min timestamp; None for bookkeeping-only sessions
    end_time: datetime | None  # max timestamp; None for bookkeeping-only sessions
    source_path: Path  # the JSONL file this came from
    subagent_meta: dict  # verbatim .meta.json contents (empty for root)
    warnings: list[ParserWarning]
    subagent_parse_errors: list[dict]  # {"path": Path, "reason": str}


# ---------------------------------------------------------------------------
# Autopsy types — M2
# ---------------------------------------------------------------------------


class FindingKind(str, Enum):
    RETRY_LOOP         = "retry_loop"
    SCOPE_CREEP        = "scope_creep"
    STALE_CONTEXT      = "stale_context"
    TOOL_THRASH        = "tool_thrash"
    DEAD_END           = "dead_end"
    FANOUT_WASTE       = "fanout_waste"
    PROJECT_PATTERN    = "project_pattern"
    CACHE_HYGIENE      = "cache_hygiene"
    COMPACTION         = "compaction"
    EXPLORATION_THRASH = "exploration_thrash"
    UNUSED_CONTEXT     = "unused_context"


KIND_LABEL: dict[FindingKind, str] = {
    FindingKind.RETRY_LOOP:         "RETRY LOOP",
    FindingKind.SCOPE_CREEP:        "SCOPE CREEP",
    FindingKind.STALE_CONTEXT:      "STALE CONTEXT",
    FindingKind.TOOL_THRASH:        "TOOL THRASH",
    FindingKind.DEAD_END:           "DEAD END",
    FindingKind.FANOUT_WASTE:       "FANOUT WASTE",
    FindingKind.PROJECT_PATTERN:    "PROJECT PATTERN",
    FindingKind.CACHE_HYGIENE:      "CACHE HYGIENE",
    FindingKind.COMPACTION:         "COMPACTION",
    FindingKind.EXPLORATION_THRASH: "EXPLORATION THRASH",
    FindingKind.UNUSED_CONTEXT:     "UNUSED CONTEXT",
}

# Maps FindingKind to the exact ## heading emitted by its recommender patch
# template. Single source of truth for "which CLAUDE.md sections cctx owns."
# harvest.py imports this (never reaches into recommender/) so emit/sync can
# identify cctx-managed sections without depending on the patch generator.
MANAGED_HEADINGS: dict[FindingKind, str] = {
    FindingKind.RETRY_LOOP:         "## Retry discipline",
    FindingKind.SCOPE_CREEP:        "## Scope discipline",
    FindingKind.STALE_CONTEXT:      "## Context hygiene",
    FindingKind.TOOL_THRASH:        "## Tool-call discipline",
    FindingKind.DEAD_END:           "## Exploration discipline",
    FindingKind.FANOUT_WASTE:       "## Fan-out discipline",
    FindingKind.CACHE_HYGIENE:      "## Cache hygiene",
    FindingKind.COMPACTION:         "## Compaction hygiene",
    FindingKind.EXPLORATION_THRASH: "## Exploration thrash",
    FindingKind.UNUSED_CONTEXT:     "## Context overhead",
}

# Project-specific patterns use a heading that embeds tool+key, so the managed
# section is identified by prefix rather than exact match.
MANAGED_HEADING_PREFIX: str = "## Project-specific: "


class Severity(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


class Confidence(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"


@dataclass
class Finding:
    kind:       FindingKind
    severity:   Severity
    confidence: Confidence
    first_turn: int
    last_turn:  int | None
    evidence:   dict[str, Any]
    cost_usd:   float | None
    summary:    str


@dataclass
class Patch:
    target_file:      str
    description:      str
    unified_diff:     str
    finding_kind:     FindingKind
    evidence_summary: str


@dataclass
class SubagentAttribution:
    """Cost attribution for a single subagent session."""

    session_id:     str
    label:          str        # from Agent tool_input['description'], else prompt[:80]
    total_cost_usd: float      # inclusive: this subagent + its own children
    depth:          int        # 1 = direct child, 2 = grandchild, …
    model:          str | None


@dataclass
class Diagnosis:
    session_id:      str
    findings:        list[Finding]
    inflection_turn: int | None
    patches:         list[Patch]
    total_cost_usd:  float
    waste_cost_usd:  float
    analysed_at:     datetime
    subagent_costs:  list[SubagentAttribution] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if not self.findings:
            return "clean session"
        seen = dict.fromkeys(f.kind for f in self.findings)
        return " + ".join(KIND_LABEL[k] for k in seen)


@dataclass
class KindEvidence:
    kind:              FindingKind
    session_count:     int
    total_waste_usd:   float
    example_summaries: list[str]


@dataclass
class ProjectPattern:
    tool_name:         str
    failure_key:       str
    fix_key:           str
    session_count:     int
    avg_wasted_turns:  float
    total_waste_usd:   float
    example_sessions:  list[str]


@dataclass
class AggregateReport:
    period_label:           str  # human-readable, e.g. "last 7 days" or "2026-05-01..2026-05-15"
    sessions_analysed:      int
    sessions_with_findings: int
    total_cost_usd:         float
    waste_cost_usd:         float
    by_kind:                dict[FindingKind, KindEvidence]
    patches:                list[Patch]
    project_patterns:       list[ProjectPattern] = field(default_factory=list)


@dataclass
class EfficacyRow:
    """One row in a patch efficacy report — before/after session counts for a managed heading."""

    heading: str                  # e.g. "## Retry discipline"
    kind: FindingKind | None      # reverse lookup from MANAGED_HEADINGS; None = not found
    applied_at: datetime | None   # first git commit that introduced this heading; None if unknown
    sessions_before: int          # sessions with this kind's finding before applied_at
    sessions_after: int           # sessions with this kind's finding from applied_at onward
    total_before: int             # total sessions analysed before applied_at
    total_after: int              # total sessions analysed from applied_at onward
    weeks_before: float           # (applied_at - oldest_session_start).days / 7
    weeks_after: float            # (newest_session_start - applied_at).days / 7


@dataclass
class EfficacyReport:
    """Aggregated before/after report across all managed CLAUDE.md headings."""

    rows: list[EfficacyRow]
    total_sessions: int
    oldest_session: datetime | None  # min start_time across all analysed sessions
    newest_session: datetime | None  # max start_time across all analysed sessions


@dataclass
class ProjectDigestRow:
    """One row in the per-project summary table of a CrossProjectDigest."""

    display_name: str
    sessions_analysed: int
    sessions_with_findings: int
    total_cost_usd: float
    waste_cost_usd: float
    top_pattern: str | None  # KIND_LABEL of most-frequent FindingKind, or None


@dataclass
class CrossProjectDigest:
    """Result of cctx autopsy --all --since: per-project rows + rolled-up global evidence."""

    period_label: str
    projects: list[ProjectDigestRow]
    total_cost_usd: float
    total_waste_usd: float
    global_patches: list[Patch]
    global_by_kind: dict[FindingKind, KindEvidence]
    global_project_counts: dict[FindingKind, int]  # distinct projects in which each kind appeared


# ---------------------------------------------------------------------------
# Renderer helper
# ---------------------------------------------------------------------------


def group_into_exchanges(turns: list[Turn]) -> list[list[Turn]]:
    """Group a flat list of turns into render-time exchanges.

    An exchange begins on each ``role == "user"`` or ``role == "tool_result"``
    turn and includes all subsequent assistant turns until the next
    user/tool_result turn.

    Leading non-user/tool_result turns (e.g. an initial system notice before
    the first user message) are gathered into their own exchange at index 0.

    Returns an empty list for empty input.
    """
    if not turns:
        return []

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
