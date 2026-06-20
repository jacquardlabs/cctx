# Spec: Loaded-but-never-used context waste — MCP servers and deferred tools

**Date:** 2026-06-20  
**Issue:** #91 — M18: Context overhead waste  
**Status:** Shipped — Signal B only (see §3 for why Signal A was dropped)

---

## 1. Empirical scan

**Acceptance criterion:** the spec must open with a real-data scan to determine what tool/skill load information is observable before any design work.

### Sessions scanned

| Session | Project | Records |
|---------|---------|---------|
| `e0aac3b0` | cctx | 1,787 lines, 21 system records |
| `4d26120b` | cctx | ~500 lines, 8 system records |
| `9bf43a03` | cctx | ~500 lines, 13 system records |
| `10a9f2d6` | cctx | current session (this spec) |
| `6360022b` | brainstorming | session with `mcp__` grep hit |
| `fbdc17fb` | brainstorming | session with `mcp__` grep hit |

### What IS present in the JSONL

**`attachment` records with `type: "deferred_tools_delta"`** — appear at session start (and after compaction restores context). Payload:

```json
{
  "type": "deferred_tools_delta",
  "addedNames": [
    "CronCreate", "CronDelete", "CronList",
    "DesignSync", "EnterPlanMode", "EnterWorktree",
    "ExitPlanMode", "ExitWorktree", "Monitor",
    "NotebookEdit", "PushNotification", "RemoteTrigger",
    "TaskCreate", "TaskGet", "TaskList",
    "TaskOutput", "TaskStop", "TaskUpdate",
    "WebFetch", "WebSearch",
    "mcp__claude_ai_Gmail__authenticate",
    "mcp__claude_ai_Gmail__complete_authentication",
    "mcp__claude_ai_Google_Calendar__authenticate",
    "mcp__claude_ai_Google_Calendar__complete_authentication",
    "mcp__claude_ai_Google_Drive__authenticate",
    "mcp__claude_ai_Google_Drive__complete_authentication"
  ],
  "removedNames": [],
  "readdedNames": [],
  "pendingMcpServers": []
}
```

The parser already classifies these as `kind="mcp_servers"` (via `pendingMcpServers` key) and reads `addedNames` into `SessionTrace.tool_names_loaded`. The raw payload is preserved on `att.raw`.

**ToolSearch `tool_use` blocks** — captured in assistant turns. Query format `"select:ToolA,ToolB"` identifies which schemas were explicitly fetched:

```
select:TaskCreate,TaskUpdate
select:TaskCreate,TaskUpdate,TaskList
```

**`preCompactDiscoveredTools` in `compact_boundary` system records** — lists deferred tools that had schemas fetched and were still in context at compaction. Matches ToolSearch query targets. Currently not parsed into the Turn model (only the `content` string is stored), but ToolSearch calls give equivalent coverage.

**`tool_use` blocks (name field)** — records every tool invocation. The complete called-tool set is derivable from `{use.tool_name for turn in trace.turns for use in turn.tool_uses}`.

### What is NOT present in the JSONL

- **`tools` key in message records** — not logged. The API request tool list (full schemas) is never written to the JSONL.
- **ToolSearch result content** — the tool_result blocks following ToolSearch calls contain only 1–2 whitespace characters. Schemas are added to the next API request's `tools` parameter, not stored in the result.
- **Skill body text** — `Skill` tool_use blocks are captured, but the loaded skill body is not in the JSONL.

---

## 2. Feasibility per surface

| Surface | Inventory observable? | Called? | Schema token cost | Verdict |
|---------|----------------------|---------|-------------------|---------|
| Built-in tools (Bash, Read, Edit…) | No — always loaded, no record | Yes, via tool_use | Not per-tool | **Cannot detect** |
| Deferred tools (Task*, mcp__*) | **Yes** — `deferred_tools_delta.addedNames` | Yes, via tool_use | Approximate (schema not in JSONL) | **Feasible** |
| Skills | No — names not in JSONL at load time | Yes, via `Skill` tool_use | Not observable | **Cannot detect** |

**Verdict: Partial feasibility.** The deferred-tools surface (which includes all MCP tools) is fully implementable. Built-in tools and skills cannot be handled in v1.

---

## 3. Design

### Signal taxonomy

**Signal B only — Available MCP tool never called** (shipped)  
MCP tool name listed in `deferred_tools_delta.addedNames` but never invoked across the session. One finding per MCP server where zero of its tools were called.

Detection:
- Available = `{n for att in trace.attachments if att.kind == "mcp_servers" for n in att.raw.get("addedNames", []) if n.startswith("mcp__")}`
- Called = all `tool_use.tool_name` values in the session
- Fire if all tools for a given server are in `available - called`

Non-MCP deferred tools (TaskCreate, CronCreate, etc.) are standard Claude Code infrastructure and are not flagged.

**Signal A — Schema-fetched but never called** (dropped)  
ToolSearch result content is 1–2 whitespace chars; schema text is not in the JSONL. No honest cost basis. Also not config-actionable — you cannot write a CLAUDE.md rule preventing model-driven ToolSearch calls. Dropped.

### Token-cost attribution

`cost_usd = None` for all findings. The deferred-tools system-reminder format is not in the JSONL, so the per-turn name cost is not directly observable. The finding is config-actionable regardless of dollar estimate.

### Cross-session strengthening

Single-session: fires as `Confidence.MEDIUM` (one data point — could be an atypical session).  
Cross-session (≥3 sessions): fires as `Confidence.HIGH` with evidence `{"session_count": N, "mcp_server": "gmail"}`.

The aggregator in `diagnostician/aggregate.py` already handles cross-session pattern counting. The classifier emits per-session Findings; the aggregator strengthens them.

### Patch proposal

The recommender generates a CLAUDE.md note (not a settings.json edit — settings patching is out of scope for v1):

```diff
+## Context overhead
+
+# MCP server `mcp__claude_ai_Gmail` loaded but never called across 5 sessions
+# (2026-06-01 → 2026-06-20). Remove from .claude/settings.json → mcpServers
+# to reclaim ~1,500 tokens per API request.
```

Target: `CLAUDE.md`, section `## Context overhead` (new managed heading). The heading is added to `MANAGED_HEADINGS` in `models.py`.

---

## 4. Implementation

### New files

**`cctx/diagnostician/patterns/unused_context.py`**

```
run(trace: SessionTrace) -> list[Finding]
```

Logic:
1. Extract `available` from `mcp_servers` attachments (`att.raw["addedNames"]`)
2. Extract `fetched` from ToolSearch `tool_use` blocks (parse `select:` queries)
3. Extract `called` from all `tool_use.tool_name` values
4. Compute Signal A (`fetched - called - {"ToolSearch"}`)
5. Compute Signal B MCP subset (`{n for n in available if n.startswith("mcp__")} - fetched - called`)
6. For each Signal A tool: emit `FindingKind.UNUSED_CONTEXT`, `Severity.WARNING`, `Confidence.MEDIUM`, with `cost_usd` estimate
7. For each Signal B MCP tool: emit `FindingKind.UNUSED_CONTEXT`, `Severity.HINT`, `Confidence.LOW`, `cost_usd=None`

### Modified files

**`cctx/models.py`**
- Add `FindingKind.UNUSED_CONTEXT = "unused_context"` to `FindingKind` enum
- Add `KIND_LABEL[FindingKind.UNUSED_CONTEXT] = "UNUSED CONTEXT"`
- Add `MANAGED_HEADINGS[FindingKind.UNUSED_CONTEXT] = "## Context overhead"`

**`cctx/diagnostician/__init__.py`**
- Import and call `unused_context.run(trace)` in the pattern-classifier pipeline

**`cctx/recommender/claude_md.py`**
- Add case for `FindingKind.UNUSED_CONTEXT` → generate the `## Context overhead` CLAUDE.md patch

**`tests/`**
- `tests/diagnostician/test_unused_context.py` — fixture-based tests:
  - Session with deferred_tools_delta + ToolSearch fetch + tool never called → Signal A fires
  - Session with deferred_tools_delta + mcp tool never fetched or called → Signal B fires
  - Session with no `mcp_servers` attachments → no findings
  - Session with tool fetched AND called → no finding

---

## 5. Out of scope (v1)

- **Settings.json patching** — recommender writes CLAUDE.md notes only; auto-editing `.claude/settings.json` is a follow-up
- **Built-in tool waste** — not observable from JSONL
- **Skills waste** — not observable from JSONL
- **Exact schema token counts** — heuristic only; v2 could retrieve schemas from live MCP servers at analysis time
- **"Partially used" tool waste** — binary detection only, consistent with the project principle
