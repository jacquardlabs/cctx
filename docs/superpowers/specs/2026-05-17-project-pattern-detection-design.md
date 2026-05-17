# Project-Specific Pattern Detection Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Detect tool-call failure/fix pairs that recur across multiple sessions in the same project and surface them in `cctx autopsy --since` output with a proposed CLAUDE.md rule.

**Architecture:** A new `project_specific.detect()` module runs after per-session diagnosis, takes `(Diagnosis, SessionTrace)` pairs, and returns `list[ProjectPattern]`. `aggregate.run()` returns those pairs instead of bare Diagnoses. The CLI assembles `AggregateReport` with the patterns appended.

**Tech Stack:** Pure stdlib — `collections.defaultdict`, existing `pricing.price_per_tok`. No LLM calls. No new dependencies.

---

## Motivation

Claude re-discovers project-specific constraints repeatedly. Each re-discovery wastes turns and money. The brief's example: `` `pnpm --filter` re-discovered in 7 sessions this month, costing $4.20. `` Existing classifiers catch *generic* patterns (retry loops, stale context). This feature catches patterns that are specific to a project's toolchain.

---

## Data model

### New: `ProjectPattern` in `models.py`

```python
@dataclass
class ProjectPattern:
    tool_name:        str         # e.g. "Bash"
    failure_key:      str         # normalized failing call, e.g. "pnpm install"
    fix_key:          str         # normalized fix call, e.g. "pnpm --filter app"
    session_count:    int         # sessions that exhibited this failure/fix pair
    avg_wasted_turns: float       # mean turns from first failure to fix
    total_waste_usd:  float       # sum of wasted-turn costs across sessions
    example_sessions: list[str]   # session_ids of up to 3 contributors
```

### Updated: `AggregateReport` in `models.py`

Add one field with a default so existing construction sites stay valid:

```python
project_patterns: list[ProjectPattern] = field(default_factory=list)
```

### Updated: `FindingKind` in `models.py`

Add one value as a patch-labeling anchor (no per-session classifier uses it):

```python
PROJECT_PATTERN = "project_pattern"
```

Add to `KIND_LABEL`:

```python
FindingKind.PROJECT_PATTERN: "PROJECT PATTERN",
```

---

## Detection algorithm

Implemented in `cctx/diagnostician/patterns/project_specific.py`.

Public interface:

```python
def detect(pairs: list[tuple[Diagnosis, SessionTrace]]) -> list[ProjectPattern]:
```

### Step 1 — Normalize tool calls

Reuse the same normalization logic as `retry_loop._similarity_key`:

| Tool | Key |
|------|-----|
| Bash | First 3 space-separated tokens of the command string |
| Edit / Read / Write | `file_path` as-is |
| Grep / Glob | `pattern` |
| Other | `json.dumps(tool_input, sort_keys=True)` |

Bash example: `"pnpm install --legacy-peer-deps"` → `"pnpm install --legacy-peer-deps"` (only 3 tokens); `"pnpm --filter app build"` → `"pnpm --filter app"`.

### Step 2 — Find failure sequences per session

For each `SessionTrace`, build a `tool_use_id → (ToolResult, turn_number)` map. Then scan all assistant turns for tool uses, recording `(tool_name, normalized_key, turn_number, is_error)`.

Group records by `(tool_name, normalized_key)`. A *failure sequence* exists when the same `(tool_name, key)` fails 2+ times with no intervening success of that same `(tool_name, key)` between the first and last failure. This is identical to the retry-loop detection logic.

Error detection (reuse `retry_loop._is_error`):
- `result.is_error` is True, or
- content starts with `"Error:"`, `"error:"`, or `"FAILED"`

### Step 3 — Find the fix

From the turn immediately after the last failure in a failure sequence, scan the next 10 turns for a successful tool call where `tool_name` matches the failing tool. The normalized key of that success is the `fix_key`. If no same-tool success is found within 10 turns, discard this failure sequence — no fix identified.

Record per session: `(tool_name, failure_key, fix_key, first_failure_turn, fix_turn, session_id, model)`.

### Step 4 — Cross-session grouping

Group records by `(tool_name, failure_key, fix_key)`. Each session is counted once per group regardless of how many times the same pair appears within that session (deduplicate on `session_id` before counting). Discard groups with fewer than 3 distinct contributing sessions (threshold default: 3).

For each qualifying group, compute:

- `session_count` — number of distinct contributing sessions
- `avg_wasted_turns` — mean of `(fix_turn - first_failure_turn)` across sessions
- `total_waste_usd` — for each session, sum `price_per_tok(model) × turn.usage.input_tokens` for all assistant turns in `[first_failure_turn, fix_turn]` inclusive; total across all sessions
- `example_sessions` — up to 3 session IDs (first 3 alphabetically)

---

## Architecture changes

### `cctx/diagnostician/aggregate.py`

Change return type from `list[Diagnosis]` to `list[tuple[Diagnosis, SessionTrace]]`. The `SessionTrace` objects are already in memory; this stops discarding them.

```python
# Before
def run(project_dir: Path, start: datetime, end: datetime) -> list[Diagnosis]:

# After
def run(project_dir: Path, start: datetime, end: datetime) -> list[tuple[Diagnosis, SessionTrace]]:
```

The internal loop appends `(diagnosis, trace)` instead of just `diagnosis`.

### `cctx/cli.py` — `autopsy` command (`--since` path)

```python
pairs = aggregate.run(project_dir, start, end)
diagnoses = [d for d, _ in pairs]
project_patterns = project_specific.detect(pairs)
ev = evidence_mod.accumulate(diagnoses)
# ... existing evidence/patch logic ...
report = AggregateReport(
    ...,
    project_patterns=project_patterns,
)
```

### `cctx/cli.py` — `harvest` command (`--since` path)

Same unpack pattern:

```python
pairs = aggregate.run(project_dir, start, end)
diagnoses = [d for d, _ in pairs]
ev = evidence_mod.accumulate(diagnoses)
```

### `cctx/recommender/claude_md.py`

New function:

```python
def generate_from_patterns(patterns: list[ProjectPattern]) -> list[Patch]:
```

For each `ProjectPattern`, generate a `Patch`:

- `target_file`: `"CLAUDE.md"`
- `finding_kind`: `FindingKind.PROJECT_PATTERN`
- `description`: `f"Project-specific: when {pattern.tool_name}({pattern.failure_key}) fails, use {pattern.fix_key}"`
- `evidence_summary`: `f"Seen in {pattern.session_count} sessions, ~${pattern.total_waste_usd:.2f} wasted"`
- `unified_diff`: a unified diff adding a rule block, e.g.:
  ```diff
  +## Project-specific: pnpm --filter
  +When `pnpm install` fails, use `pnpm --filter <package>` instead.
  +Re-discovered in 7 sessions — add this to stop repeating it.
  ```

Called from the CLI `--since` path; resulting patches merged into `AggregateReport.patches`:

```python
pattern_patches = claude_md.generate_from_patterns(project_patterns)
patches = claude_md.generate_from_evidence(ev) + pattern_patches
```

### `cctx/renderers/terminal.py` — `render_aggregate()`

After the existing findings table, if `report.project_patterns` is non-empty, print a second table:

```
┌─ Project-specific patterns ──────────────────────────────────────────┐
│ Failure           Fix                Sessions  Avg turns  Waste       │
│ pnpm install      pnpm --filter app  7         12.3       $4.20       │
└──────────────────────────────────────────────────────────────────────┘
```

If `project_patterns` is empty, print nothing extra — no "no patterns found" noise.

---

## New file

**`cctx/diagnostician/patterns/project_specific.py`** — standalone module, no imports from other classifiers. Imports: `collections.defaultdict`, `cctx.models`, `cctx.pricing`. Single public function `detect()`. Internal helpers: `_normalize_key()` (duplicates the same logic as `retry_loop._similarity_key` locally — do not extract to a shared module yet), `_find_pairs()` per session, `_compute_waste()` per group.

---

## Files changed

| File | Change |
|------|--------|
| `cctx/models.py` | Add `ProjectPattern`, extend `AggregateReport`, add `FindingKind.PROJECT_PATTERN` + `KIND_LABEL` entry |
| `cctx/diagnostician/aggregate.py` | Return `list[tuple[Diagnosis, SessionTrace]]` |
| `cctx/diagnostician/patterns/project_specific.py` | **New** — `detect()` function |
| `cctx/recommender/claude_md.py` | Add `generate_from_patterns()` |
| `cctx/renderers/terminal.py` | Extend `render_aggregate()` for project patterns table |
| `cctx/cli.py` | Unpack pairs in `autopsy` and `harvest` `--since` paths; wire `project_specific.detect()` and `generate_from_patterns()` |
| `tests/diagnostician/test_project_specific.py` | **New** — unit tests for `detect()` |
| `tests/test_cli.py` | Tests for `--since` with project patterns in output |

---

## Testing strategy

**Unit tests for `detect()`** (`tests/diagnostician/test_project_specific.py`):
- Two sessions each with `(pnpm install → fail, pnpm --filter → success)` → no pattern (below threshold of 3)
- Three sessions with the same failure/fix pair → one `ProjectPattern` returned
- Three sessions where fix appears at turn 11 (outside 10-turn window) → no pattern
- Same session contributing the same pair twice → counted once (per-session dedup)
- Mixed tool types (Bash + Edit) → patterns grouped by tool_name separately

**Integration tests** (`tests/test_cli.py`):
- `autopsy --since` on project dir with 3+ matching sessions → output contains pattern table
- `aggregate.run()` returns `list[tuple]` — unpack in existing tests

---

## Non-goals (v1)

- No fuzzy/semantic normalization of Bash commands (Option B filed as a follow-on issue)
- No detection across different projects
- No LLM-assisted summarization of pattern descriptions
- No minimum threshold configuration via CLI flag (hardcoded at 3; future `--min-recurrence N` is straightforward to add)
