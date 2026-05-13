# Claude Code session parser — design

**Status:** approved through brainstorming, awaiting implementation
**Date:** 2026-05-12
**Module:** `cctx/parsers/claude_code.py`
**Pipeline position:** `JSONL on disk → [Parser] → SessionTrace → Tokenizer → Decomposer → Analyzers → Renderers`

## 1. Scope

The Claude Code parser is the entry point of the entire `cctx` data pipeline. It reads a session transcript written by Claude Code to `~/.claude/projects/<project>/<session-id>.jsonl` (plus any sibling `subagents/` and `tool-results/` directories) and produces a fully-populated `SessionTrace` dataclass. Every other module in `cctx` works from `SessionTrace`, never from raw JSONL.

The parser is **structural and lossy**: it converts the file format into the data model and drops session-bookkeeping noise. It is **dependency-free**: no Anthropic SDK, no Pydantic, no MCP libraries. It does **not tokenize**, **does not compute cost**, **does not infer waste**. Each of those is a downstream concern.

This document specifies the parser only. The tokenizer, decomposer, and analyzers are designed separately.

## 2. Empirical findings that shaped this design

The format isn't documented externally. These observations from `~/.claude/projects/` across five real projects (24 session files) drove every contentious decision below.

### 2.1 Line-type inventory

Across the corpus, top-level `type` values seen, with counts from one 8-session sample:

| `type`                  | Count | Purpose                                                  |
|-------------------------|-------|----------------------------------------------------------|
| `assistant`             | 2,492 | One assistant message per line                           |
| `user`                  | 1,629 | Real user prompts, or tool results (polymorphic)         |
| `attachment`            | 316   | Hook outputs, MCP server lists, skills block, etc.       |
| `last-prompt`           | 308   | UI bookkeeping                                           |
| `queue-operation`       | 256   | UI bookkeeping                                           |
| `file-history-snapshot` | 237   | File backup metadata                                     |
| `permission-mode`       | 190   | UI bookkeeping                                           |
| `system`                | 101   | Synthetic notices (compaction, model swaps)              |
| `custom-title`          | 37    | UI bookkeeping                                           |
| `pr-link`               | 15    | UI bookkeeping                                           |
| `ai-title`              | (5)   | UI bookkeeping (seen in smaller scan)                    |

### 2.2 What is and isn't in the JSONL

**Present:** all assistant text, thinking, and tool_use blocks; user messages (string or list-of-blocks); tool_result blocks (inline content); usage data per assistant message (input_tokens, output_tokens, cache_creation_input_tokens split into ephemeral 1h/5m, cache_read_input_tokens, iterations[]); model name; stop_reason; timestamps (ISO 8601 UTC with `Z` suffix); cwd; git branch; Claude Code version; the entire conversation tree via `parentUuid → uuid`.

**Absent:** the API system prompt; the tool-definitions block sent to the API (descriptions, schemas — only fired tool names appear, via `tool_use` blocks); detailed MCP tool metadata. Decomposing those token blocks requires reading `.claude/settings.json` and MCP server configs at analyzer time, not from the JSONL.

### 2.3 The decomposition anchor

The first assistant message's `cache_creation_input_tokens` is the only hard observable for the entire pre-conversation context window. In one test session it was 30,488 tokens. The decomposer subtracts tokenized attachment content from this number; the remainder is "system prompt + tool definitions + internal framing" — undifferentiated by design (5–15% honest gap, displayed as a gray flamegraph slice labeled "system internals (not in logs)").

### 2.4 Attachments are polymorphic

Sampling distinct attachment shapes in real data revealed at least five:

| Shape (detected by payload keys)           | What it carries                                                |
|--------------------------------------------|---------------------------------------------------------------|
| has `hookEvent` and `stdout`               | Hook outputs (SessionStart:startup, SessionStart:compact, …)   |
| has `pendingMcpServers`                    | MCP server names added/removed at session start (names only)   |
| has `skillCount` + `content`               | The available-skills bullet list with `isInitial` flag         |
| has `allowedTools`                         | The permission list                                            |
| has `itemCount`                            | Queued items                                                   |

The parser classifies by **payload key shape**, not by `hookEvent` (which is only present on hook-output attachments). Future shapes land in `kind="other"` with the raw dict preserved.

### 2.5 Subagents live in separate files

Subagents are not inlined into the parent JSONL as sidechain entries. The parent contains `Agent` tool_use blocks; the actual subagent execution is written to `<session-id>/subagents/agent-*.jsonl`, with a small `.meta.json` sibling (67–108 bytes, likely carrying the originating tool_use_id). One session had 42 subagents. Subagents have their own initial `cache_creation_input_tokens` (1,790–3,540 in the sample) and their own `cache_read_input_tokens` from the parent's cache.

### 2.6 Tool-result sidecars are NOT addressed from the JSONL

The `<session-id>/tool-results/*.txt` files exist (some up to 383KB), but their filenames never appear anywhere in the transcript. Inline `tool_result` content tops out at ~23KB in observed data. Conclusion: **inline content is what the model saw.** Sidecars are runtime artifacts of the original (untruncated) tool execution and are useful only for forensic analysis. The parser lists them with sizes but does not read them.

### 2.7 User message content is mostly homogeneous, but not always

A scan of 3,304 user lines with list-shaped content across five projects:

| Block-type signature | Count |
|---------------------|-------|
| `(tool_result,)`     | 3,165 |
| `(text,)`            | 112   |
| `(image, text)`      | 27    |

`text + tool_result` mixes were not seen, but the existence of any heterogeneous case means dispatch must pattern-match on the **set** of block types, not assume homogeneity.

## 3. Public API

```python
# cctx/parsers/claude_code.py

def parse_session(
    session_path: Path,
    *,
    max_subagent_depth: int = 4,
) -> SessionTrace:
    """Parse a Claude Code session.

    `session_path` accepts either the JSONL file itself
        (~/.claude/projects/<proj>/<sid>.jsonl)
    or its sibling directory
        (~/.claude/projects/<proj>/<sid>/).

    Raises ParserError on unreadable files. Soft failures accumulate on
    SessionTrace.warnings; unknown `type` values are skipped with warnings,
    not raised.

    Subagents recurse up to max_subagent_depth (default 4 — circuit breaker,
    not a hard cap; the warning instructs users how to raise it).
    """

class ParserError(Exception):
    """Hard parse failure (only raised on unreadable files)."""
    path: Path
    line_number: int | None
    reason: str

@dataclass
class ParserWarning:
    """Soft parse failure. Recorded on SessionTrace.warnings."""
    code: str          # "unknown_type" | "malformed_json" | "orphan_agent_call" | "orphan_subagent_file" | "encoding_error" | ...
    detail: str
    line_number: int | None = None
    path: Path | None = None
```

The CLI prints a one-line banner summarizing `SessionTrace.warnings` after a parse. `--verbose` prints the full list.

## 4. Data model

All dataclasses live in `cctx/models.py`. They are pure data containers with no behavior. `token_count` fields are placeholders filled by the tokenizer pass — `parse_session` leaves them at 0.

```python
@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    cache_creation_5m: int      # ephemeral_5m_input_tokens
    cache_creation_1h: int      # ephemeral_1h_input_tokens
    cache_read: int
    service_tier: str | None    # "standard" | "priority" | ...

@dataclass
class ToolUse:
    tool_name: str
    tool_use_id: str
    tool_input: dict
    token_count: int = 0
    subagent_session_id: str | None = None   # set when tool_name == "Agent" and the matching child file was found

@dataclass
class ToolResult:
    tool_name: str               # resolved by pairing with the originating ToolUse on tool_use_id
    tool_use_id: str
    content: str                 # inline content (always populated — inline is canonical, sidecars are not the source of truth)
    structured: dict | None      # the parallel toolUseResult field (file/{filePath,content,...}, bash/{stdout,exit_code,...}, etc.)
    is_error: bool
    token_count: int = 0

@dataclass
class Turn:
    turn_number: int             # 1-based index in SessionTrace.turns
    uuid: str                    # JSONL line's uuid
    parent_uuid: str | None
    role: str                    # "user" | "assistant" | "tool_result" | "system"
    text: str                    # flattened text content; image blocks become "<image:{media_type},{N}B>" placeholders here
    thinking: str                # separate field — extended thinking is its own cost category
    tool_uses: list[ToolUse]     # multiple allowed; symmetric with tool_results
    tool_results: list[ToolResult]
    usage: Usage | None          # assistant turns only
    model: str | None            # assistant turns only
    stop_reason: str | None      # "end_turn" | "tool_use" | "stop_sequence" | None
    timestamp: datetime          # tz-aware UTC
    duration_ms: int | None      # gap to next turn; None for the last turn
    token_count: int = 0         # total tokens for the whole message
    is_sidechain: bool = False   # safety net; observed always-False in current data
    error: str | None = None     # set when isApiErrorMessage was true

@dataclass
class Attachment:
    kind: str                    # "hook_output" | "mcp_servers" | "skills" | "allowed_tools" | "items" | "other"
    raw: dict                    # original attachment payload, verbatim
    content: str | None          # convenience: extracted text content if any
    timestamp: datetime | None
    parent_uuid: str | None

@dataclass
class RawToolResultFile:
    path: Path
    size_bytes: int
    tool_use_id: str | None      # always None in v1; matching deferred to v1.1 if needed

@dataclass
class SessionTrace:
    session_id: str
    parent_session_id: str | None       # set on subagent traces
    project_path: str                    # decoded from dir name: "-Users-bryan-Projects-cctx" → "/Users/bryan/Projects/cctx"
    cwd: str                             # actual cwd observed on the lines (may differ from project_path if the user cd'd)
    primary_model: str | None            # most frequent model across assistant turns; None if no assistant turns
    claude_code_version: str | None
    turns: list[Turn]
    subagents: list["SessionTrace"]
    attachments: list[Attachment]
    raw_tool_result_files: list[RawToolResultFile]
    initial_context_tokens: int          # cache_creation_input_tokens from the first assistant turn; 0 if no assistant turns
    tool_names_loaded: list[str]         # union of MCP names from pendingMcpServers attachments + names observed in tool_uses
    start_time: datetime | None          # min timestamp across conversational turns; None if there are none (e.g. bookkeeping-only file)
    end_time: datetime | None            # max timestamp across conversational turns; None if there are none
    source_path: Path                    # the JSONL file this came from
    subagent_meta: dict                  # verbatim contents of the child's .meta.json (empty for the root); used by the linker for tool_use_id matching
    warnings: list[ParserWarning]
    subagent_parse_errors: list[dict]    # corrupt child JSONLs that couldn't be parsed; entries: {"path": Path, "reason": str}
```

### 4.1 Why no `tools: list[ToolDefinition]`

The brief drafted a `ToolDefinition` dataclass. The JSONL doesn't carry tool descriptions or schemas — only names. Materializing empty `ToolDefinition(name="Read", description="", schema={})` objects would imply structure that isn't there. `tool_names_loaded: list[str]` is the honest version. The decomposer enriches names with descriptions at analyzer time by reading `.claude/settings.json` and MCP server configs.

### 4.2 Why `text` and `thinking` are separate fields

Extended thinking is its own flamegraph slice and a distinct cost category. Concatenating now would force every downstream analyzer to re-split the content. Keep them separate at the model level — analyzers that only want text iterate `turn.text`; the cost analyzer reads both.

### 4.3 Why `is_sidechain` is on Turn even though it's always False

Defensive insurance against future format drift. If Claude Code starts inlining sidechain content into the parent JSONL (instead of separate subagent files), analyzers can filter without a model change.

### 4.4 Why no `memory` field

The brief proposed `SessionTrace.memory: Optional[str]`. The `~/.claude/projects/<proj>/memory/` directory lives at the **project** level, not the session level, and is shared across all sessions in a project. The parser's job is "this session." The decomposer reads the memory directory once per project at analyzer time and attributes its tokens to the appropriate component. Putting memory on `SessionTrace` would either duplicate it across every session (waste) or imply session-specific scoping that doesn't exist (lie).

## 5. Line-type dispatch

```python
match line["type"]:
    case "assistant":
        # → Turn(role="assistant"), usage from message.usage,
        #   content blocks dispatched: text → Turn.text, thinking → Turn.thinking,
        #   tool_use → Turn.tool_uses[], server_tool_use / advisor_tool_result → preserved in Turn.text marker
        ...

    case "user":
        content = message["content"]
        if isinstance(content, str):
            # → Turn(role="user", text=content)
            ...
        elif isinstance(content, list):
            block_types = {b["type"] for b in content}
            if "tool_result" in block_types:
                # → Turn(role="tool_result")
                #   tool_results[] from tool_result blocks; sibling text/image folded into Turn.text defensively
                ...
            else:
                # → Turn(role="user")
                #   text blocks concatenated; image blocks become "<image:{media_type},{N}B>" placeholders in Turn.text
                ...

    case "system":
        # → Turn(role="system", text=...)
        # Synthetic notices Claude Code injects (compaction events, model swaps).
        # Rare. Loop / waste detectors filter by role.

    case "attachment":
        # → Attachment classified by payload-key shape (see §6).

    case "last-prompt" | "permission-mode" | "ai-title" | "custom-title" \
       | "queue-operation" | "file-history-snapshot" | "pr-link":
        # Dropped. Counted into a hidden dropped_bookkeeping counter (not on SessionTrace;
        # surfaced only via --verbose) so users can verify what was skipped.

    case _:
        # Unknown type — warn-and-skip, counted, surfaced in the CLI banner.
        warnings.append(ParserWarning(code="unknown_type", detail=line["type"]))
```

### 5.1 Warn-and-skip banner format

```
⚠ cctx parser: skipped 3 unknown line types in session abc123:
    "compact_summary" (×4), "memory_write" (×2), "tool_search_result" (×1)
  This usually means Claude Code is newer than your cctx parser.
  Run: pip install --upgrade cctx
```

Printed once per CLI invocation, deduplicated across multiple sessions. `cctx analyze` over 53 sessions prints one banner summarizing the entire batch.

### 5.2 Usage iterations

The `iterations[]` array in usage represents API-internal retries. In most lines there is a single element duplicating the top-level numbers. In a few, top-level numbers and the sum across iterations diverge. **The parser defensively re-derives Usage from the sum of iterations[]**, not from the top-level fields. Per-iteration breakdown is dropped; if anyone later wants it, the raw JSONL is on disk.

## 6. Attachment classification

```python
def classify_attachment(payload: dict) -> str:
    if "hookEvent" in payload:        return "hook_output"
    if "pendingMcpServers" in payload: return "mcp_servers"
    if "skillCount" in payload:        return "skills"
    if "allowedTools" in payload:      return "allowed_tools"
    if "itemCount" in payload:         return "items"
    return "other"
```

`raw` always contains the verbatim payload; `content` is populated from the first usable text field (`stdout`'s `additionalContext` for hook outputs, `content` for skills/items, etc.). Unknown shapes land in `"other"` without a warning — attachments are inherently polymorphic.

## 7. Subagent stitching

**Discovery.** After parsing the parent JSONL, look for `<parent-dir>/<session-id>/subagents/agent-*.jsonl`. Glob for `.jsonl` files; the `.meta.json` siblings are auxiliary.

**Recursive parse.** Each child is parsed by recursively calling `parse_session()` with its path, incrementing depth. The default `max_subagent_depth=4` is a circuit breaker; deeper chains emit a `ParserWarning` instructing how to raise the cap.

**Linking.** For each child:

1. Set `child.parent_session_id = parent.session_id`.
2. Find the originating `Agent` `ToolUse` in `parent.turns` by:
   - exact match: `child.subagent_meta.get("tool_use_id") == use.tool_use_id`, or
   - fallback: timestamp proximity + `use.tool_input.get("subagent_type")`.
3. If found, set `use.subagent_session_id = child.session_id`.
4. If not found, emit `ParserWarning(code="orphan_subagent_file", detail=child.session_id)`. Keep the child in `parent.subagents` — orphaned subagent files still cost tokens.

**Reverse orphans.** Parent `Agent` tool_use blocks with no matching child file (interrupted sessions, lost files): `use.subagent_session_id` stays `None`, `ParserWarning(code="orphan_agent_call")` is emitted. The cost/loop analyzers know how to handle `None`.

**Meta.json.** Preserved verbatim on `SessionTrace.subagent_meta: dict` (small enough — typically 67–108 bytes). The parser doesn't model its internal schema in v1; the linker uses `tool_use_id` if present, falls back otherwise.

**Tool-results at subagent depth.** Each child JSONL's sibling `tool-results/` directory (if present) is enumerated for the child's `raw_tool_result_files`. Falls back to empty list if no such directory.

## 8. Tool-result content handling

**Inline is canonical.** `ToolResult.content` is always populated from the inline `tool_result` block. No sidecar dereferencing, no lazy loading, no path indirection. The full parsed `SessionTrace` fits in memory (6MB JSONL → tens of MB in objects; ToolResult content tops out at ~23KB inline).

**Sidecars exposed separately.** `SessionTrace.raw_tool_result_files` is populated by `os.listdir` + `os.path.getsize` on `<sid>/tool-results/*.txt`. Contents are NOT read. Useful for:

- `cctx export --include-raw` (the user explicitly asks for forensic dump).
- A specific decomposer signal: "raw output was 383KB but the model only saw 22KB — 94% truncated." Aggregate-level "X MB of raw output across this session" works without per-file tool_use_id matching.

`RawToolResultFile.tool_use_id` is `None` in v1. Per-file matching is a v1.1 nicety if reliable signal emerges.

## 9. Error handling

| Situation                                               | Behavior                                                                                |
|---------------------------------------------------------|-----------------------------------------------------------------------------------------|
| Unknown `type` value                                    | Skip, count, `ParserWarning(code="unknown_type")`, surfaced in CLI banner.              |
| Malformed JSON line                                     | Skip, `ParserWarning(code="malformed_json")` with line number and reason.               |
| Truncated final line (session killed mid-write)         | Detect (last line lacks `\n` and fails JSON parse). Drop silently — common, harmless.   |
| `parentUuid` referencing an unseen uuid                 | Keep the Turn; `ParserWarning(code="orphan_parent")`.                                   |
| Subagent JSONL exists but is corrupt                    | `SessionTrace.subagent_parse_errors` gets an entry; parent parse succeeds.              |
| `subagents/` or `tool-results/` dirs missing            | Normal; empty lists, no warning.                                                        |
| Main JSONL file missing or unreadable                   | `ParserError` raised. The only hard failure mode.                                       |
| Non-UTF-8 bytes in a line                               | `errors="replace"`, `ParserWarning(code="encoding_error")` per affected line.           |
| Timestamps without timezone                             | Assume UTC (consistent with observed data: ISO 8601 with `Z` suffix). Stored tz-aware.  |
| `Agent` tool_use with no matching child file            | `use.subagent_session_id = None`, `ParserWarning(code="orphan_agent_call")`.             |
| Child JSONL with no matching parent `Agent` tool_use    | Include in `parent.subagents` with `parent_session_id` set, `ParserWarning(code="orphan_subagent_file")`. |

The contract: produce a valid `SessionTrace` for any file we can open. Hard failure only on unreadable input.

## 10. Testing strategy

### 10.1 Two-tier fixtures

**Tier 1 — Anonymized real-data fixtures** (`tests/fixtures/real/`). Capture 5–7 real sessions covering the matrix:

- Small session (~25 turns, no subagents, no sidecars) — happy path.
- Medium session with subagents (~5–10 children) — recursion.
- Session with `SessionStart:compact` attachment — compaction detection by analyzer.
- Session with mixed `[text, image]` user array — heterogeneous content dispatch.
- Session with sidecar files present in `tool-results/` — raw-file enumeration without reading.
- **Edge: user-only session** (one user turn, then abandoned). Verifies `initial_context_tokens = 0`, `primary_model = None`, `start_time == end_time`, no crash.

Anonymization driven by `scripts/anonymize_fixture.py`:

- Replace `/Users/<name>/...` paths with `/Users/test/...`.
- Truncate `toolUseResult.file.content` to 200 chars.
- Scrub git branch names to `test-branch`.
- Replace session UUIDs and tool_use_ids with deterministic test IDs.
- Preserve all structural shapes (types, keys, sizes) so the parser doesn't notice it's reading fixtures.

Reproducible — re-runnable when Claude Code's format drifts.

**Tier 2 — Synthetic adversarial fixtures** (`tests/fixtures/synthetic/`). Hand-crafted minimal JSONL files exercising:

- Malformed JSON line in the middle.
- Truncated final line.
- Unknown `type` value (verifies banner generation).
- Orphan subagent reference (Agent call with no child file).
- Orphan subagent file (no parent Agent call).
- Mixed content arrays.
- Empty session (just bookkeeping types).
- Iterations array with top-level/sum mismatch.
- Subagent at depth = 5 (verifies circuit-breaker warning).
- Attachment of unknown shape (verifies `kind="other"` without warning).

### 10.2 Assertions

- **Golden `SessionTrace` shapes** for happy paths — `parse_session(fixture) == expected_pickle`. Regenerated when intentional changes are made.
- **Invariants** checked on every fixture:
  - `turn_number` is contiguous starting at 1.
  - Every `ToolUse.tool_use_id` referenced by a downstream `ToolResult` matches.
  - Subagent traces have non-empty `parent_session_id`.
  - If both `start_time` and `end_time` are set, `start_time <= end_time`. (Both may be `None` for a bookkeeping-only session.)
  - `warnings` contains the expected codes for adversarial cases.
- **Performance benchmark:** parse a 6MB session in under 500ms on a modern laptop. Enforced by a benchmark test using the largest available fixture.

### 10.3 Non-goals at this layer

The parser is NOT responsible for:

- Token counts — `token_count: int = 0` is a placeholder filled by the tokenizer pass. Tests must not assert specific token counts at parser level; they break when the tokenizer changes.
- Cost — that's the cost analyzer.
- Decomposition — that's the decomposer.
- MCP tool descriptions — they aren't in the JSONL.
- Round-trip serialization — the parser is lossy by design (drops bookkeeping); a `parse → serialize → diff` test would be testing the wrong invariant.

## 11. Open questions deferred to implementation

These are minor and don't block the design. They get resolved by writing the code against real data.

1. **`.meta.json` schema.** Working hypothesis: carries the originating tool_use_id. Verify on first real subagent fixture. If absent, fallback discriminator is timestamp + subagent_type.
2. **`server_tool_use` and `advisor_tool_result` block handling.** Observed in small numbers. Inline them into `Turn.text` with a marker comment for v1; if any analyzer needs them as first-class fields later, add them then.
3. **`.cctx-tokens` cache file location.** Originally proposed as a side-effect of lazy sidecar reading, which we've now eliminated. Re-evaluate at the tokenizer-pass design stage — the tokenizer may want its own cache for repeated `cctx analyze` runs, but it's no longer a parser concern.
4. **Cross-platform path handling.** All observed data is macOS. Claude Code on Linux/Windows likely uses different path conventions in `cwd` and project-dir naming. Use `pathlib` everywhere, but actual cross-platform behavior needs verification when Linux/Windows fixtures are available.

## 12. What this design deliberately does not do

- It does not pretend to know the system prompt or tool definitions (the JSONL doesn't carry them).
- It does not dereference sidecar tool-result files (inline content is canonical).
- It does not call the tokenizer (separation of concerns, dependency hygiene).
- It does not fail on schema drift (warn-and-skip with visible reporting).
- It does not collapse subagent context into the parent (each subagent is a full `SessionTrace`).
- It does not split `Turn`s by content block (one JSONL line = one Turn; usage attribution stays clean).
- It does not group `Turn`s into "exchanges" (that's a renderer-layer concern, served by `group_into_exchanges()` in `cctx/models.py`).
- It does not validate that the data "makes sense" (the parser is a normalizer, not a validator).

## 13. Architectural principles to preserve

These came out of brainstorming and are worth keeping in mind for the tokenizer / decomposer / analyzer designs that follow:

- **Group up, never down.** Parse at the finest granularity the source provides (per-line, per-block where it matters). Aggregate in the view layer. You can always coarsen later; refining once aggregated is impossible without re-parsing.
- **Empirical evidence collapses speculative complexity.** Five sections of this spec changed materially after running a 30-line scanner against real data. Build the simplest thing that fits what's actually there.
- **Be honest about what you can't know.** The system prompt and tool descriptions aren't in the JSONL. The decomposition gap is visible as a labeled "system internals" slice, not hidden behind a guess.
- **Lossy normalization, not lossless conversion.** Drop session-bookkeeping noise. Surface what was dropped via `--verbose`. Don't preserve everything just in case.
