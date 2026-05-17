# M14 Project-Specific Pattern Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect tool-call failure/fix pairs that recur across 3+ sessions in the same project and surface them in `cctx autopsy --since` output with a proposed CLAUDE.md rule.

**Architecture:** `aggregate.run()` returns `list[tuple[Diagnosis, SessionTrace]]` instead of bare Diagnoses. A new `project_specific.detect()` module takes those pairs, finds recurring (failure_key, fix_key) patterns, and returns `list[ProjectPattern]`. The CLI assembles `AggregateReport` with the patterns; the terminal renderer adds a second table below the existing findings table.

**Tech Stack:** Python stdlib only (`collections.defaultdict`, `dataclasses`), existing `cctx.pricing.price_per_tok`. No LLM calls. No new dependencies.

---

## File map

| File | What changes |
|------|-------------|
| `cctx/models.py` | Add `ProjectPattern` dataclass; add `project_patterns` field to `AggregateReport`; add `FindingKind.PROJECT_PATTERN` + `KIND_LABEL` entry |
| `cctx/diagnostician/aggregate.py` | Change return type to `list[tuple[Diagnosis, SessionTrace]]` |
| `cctx/diagnostician/patterns/project_specific.py` | **New** — `detect()` + internal helpers |
| `cctx/recommender/claude_md.py` | Add `generate_from_patterns()` |
| `cctx/renderers/terminal.py` | Extend `render_aggregate()` with project patterns table |
| `cctx/cli.py` | Unpack pairs; wire `project_specific.detect()` and `generate_from_patterns()` in autopsy and harvest `--since` paths |
| `tests/diagnostician/test_project_specific.py` | **New** — unit tests |
| `tests/test_aggregate.py` | Update 2 tests to unpack `(Diagnosis, SessionTrace)` tuples |
| `tests/test_terminal_renderer.py` | Add tests for project patterns table in `render_aggregate` |

---

## Task 1: Data model — `ProjectPattern`, `AggregateReport`, `FindingKind`

**Files:**
- Modify: `cctx/models.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_models_project_pattern.py`:

```python
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
    from cctx.models import FindingKind, KIND_LABEL
    assert FindingKind.PROJECT_PATTERN.value == "project_pattern"
    assert KIND_LABEL[FindingKind.PROJECT_PATTERN] == "PROJECT PATTERN"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_models_project_pattern.py -v
```
Expected: FAIL — `ImportError: cannot import name 'ProjectPattern'`

- [ ] **Step 3: Add `ProjectPattern` to `models.py`**

In `cctx/models.py`, change:
```python
from dataclasses import dataclass
```
to:
```python
from dataclasses import dataclass, field
```

Add `ProjectPattern` immediately before `AggregateReport`:

```python
@dataclass
class ProjectPattern:
    tool_name:         str
    failure_key:       str
    fix_key:           str
    session_count:     int
    avg_wasted_turns:  float
    total_waste_usd:   float
    example_sessions:  list[str]
```

Add `PROJECT_PATTERN` to `FindingKind`:

```python
class FindingKind(str, Enum):
    RETRY_LOOP      = "retry_loop"
    SCOPE_CREEP     = "scope_creep"
    STALE_CONTEXT   = "stale_context"
    TOOL_THRASH     = "tool_thrash"
    DEAD_END        = "dead_end"
    PROJECT_PATTERN = "project_pattern"
```

Add to `KIND_LABEL`:

```python
KIND_LABEL: dict[FindingKind, str] = {
    FindingKind.RETRY_LOOP:       "RETRY LOOP",
    FindingKind.SCOPE_CREEP:      "SCOPE CREEP",
    FindingKind.STALE_CONTEXT:    "STALE CONTEXT",
    FindingKind.TOOL_THRASH:      "TOOL THRASH",
    FindingKind.DEAD_END:         "DEAD END",
    FindingKind.PROJECT_PATTERN:  "PROJECT PATTERN",
}
```

Add `project_patterns` field to `AggregateReport` (at the end, with default so existing construction sites don't break):

```python
@dataclass
class AggregateReport:
    period_label:           str
    sessions_analysed:      int
    sessions_with_findings: int
    total_cost_usd:         float
    waste_cost_usd:         float
    by_kind:                dict[FindingKind, KindEvidence]
    patches:                list[Patch]
    project_patterns:       list[ProjectPattern] = field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_models_project_pattern.py -v
```
Expected: 3 passed

- [ ] **Step 5: Run full suite to check no regressions**

```
pytest -x -q
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add cctx/models.py tests/test_models_project_pattern.py
git commit -m "feat: add ProjectPattern model, AggregateReport.project_patterns, FindingKind.PROJECT_PATTERN"
```

---

## Task 2: `aggregate.run()` — return pairs instead of bare Diagnoses

**Files:**
- Modify: `cctx/diagnostician/aggregate.py`
- Modify: `tests/test_aggregate.py`

- [ ] **Step 1: Update the aggregate tests first**

In `tests/test_aggregate.py`, update the two tests that call `run()`:

```python
def test_run_returns_diagnoses_for_sessions_in_window(tmp_path):
    from cctx.diagnostician.aggregate import run

    _write_session(tmp_path, "session-a")
    _write_session(tmp_path, "session-b")

    start, end = _now_and_window(7)
    pairs = run(tmp_path, start, end)
    assert len(pairs) == 2
    diagnoses = [d for d, _ in pairs]
    session_ids = {d.session_id for d in diagnoses}
    assert "session-a" in session_ids
    assert "session-b" in session_ids


def test_run_excludes_old_sessions(tmp_path):
    from cctx.diagnostician.aggregate import run

    path = _write_session(tmp_path, "old-session")
    old_time = time.time() - 10 * 86400
    os.utime(path, (old_time, old_time))

    _write_session(tmp_path, "new-session")

    start, end = _now_and_window(7)
    pairs = run(tmp_path, start, end)
    assert len(pairs) == 1
    assert pairs[0][0].session_id == "new-session"


def test_run_empty_dir(tmp_path):
    from cctx.diagnostician.aggregate import run

    start, end = _now_and_window(7)
    assert run(tmp_path, start, end) == []
```

- [ ] **Step 2: Run to verify they now fail (old return type)**

```
pytest tests/test_aggregate.py -v
```
Expected: 2 failures (tuple unpack errors), 1 pass (empty dir test still passes)

- [ ] **Step 3: Update `aggregate.py` to return pairs**

Replace the entire `aggregate.py` with:

```python
"""Cross-session aggregator.

run(project_dir, start, end) -> list[tuple[Diagnosis, SessionTrace]]

Discovers session JSONL files in project_dir modified within [start, end],
parses each one, runs the per-session diagnostician, and returns
(Diagnosis, SessionTrace) pairs. The CLI orchestrates recommender and
project-specific detection separately.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from cctx import diagnostician
from cctx.parsers.claude_code import parse_session
from cctx.tokenizer import tokenize_session

if TYPE_CHECKING:
    from cctx.models import Diagnosis, SessionTrace

UTC = timezone.utc


def run(
    project_dir: Path, start: datetime, end: datetime
) -> list[tuple[Diagnosis, SessionTrace]]:
    paths = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)

    result = []
    for path in paths:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if not (start <= mtime <= end):
            continue
        try:
            trace = tokenize_session(parse_session(path))
            diagnosis = diagnostician.run(trace)
            result.append((diagnosis, trace))
        except Exception:
            continue
    return result
```

- [ ] **Step 4: Run aggregate tests**

```
pytest tests/test_aggregate.py -v
```
Expected: 3 passed

- [ ] **Step 5: Run full suite — expect CLI tests to fail on unpacking**

```
pytest -x -q
```
Expected: failures in `test_cli.py` and `test_harvest.py` (if they exist) that call `aggregate.run()` indirectly through the CLI. The CLI currently does `diagnoses = aggregate.run(...)` and then iterates over them as `Diagnosis` objects — those will break. Note these failures; you will fix them in Task 6.

If only `test_aggregate.py` tests change and CLI tests pass (because CLI invocation goes through `click.testing.CliRunner` which catches the error at runtime but the test only checks `exit_code == 0`), then all may still pass at this stage. Either way, continue.

- [ ] **Step 6: Commit**

```bash
git add cctx/diagnostician/aggregate.py tests/test_aggregate.py
git commit -m "feat: aggregate.run() returns (Diagnosis, SessionTrace) pairs"
```

---

## Task 3: `project_specific.detect()` — new module

**Files:**
- Create: `cctx/diagnostician/patterns/project_specific.py`
- Create: `tests/diagnostician/test_project_specific.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/diagnostician/test_project_specific.py`:

```python
"""Tests for cctx/diagnostician/patterns/project_specific.py."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from tests.diagnostician.conftest import (
    make_assistant_turn,
    make_tool_result,
    make_tool_result_turn,
    make_tool_use,
    make_trace,
    make_user_turn,
)

UTC = timezone.utc


def _make_diagnosis(session_id: str):
    from cctx.models import Diagnosis
    return Diagnosis(
        session_id=session_id,
        findings=[],
        inflection_turn=None,
        patches=[],
        total_cost_usd=0.0,
        waste_cost_usd=0.0,
        analysed_at=datetime(2026, 5, 14, 10, tzinfo=UTC),
    )


def _make_pnpm_trace(session_id: str) -> object:
    """Trace: Bash('pnpm install') fails 2×, then Bash('pnpm --filter app build') succeeds."""
    turns = [make_user_turn(1)]
    for i in range(2):
        uid = f"tu-fail-{i:02d}"
        turns.append(make_assistant_turn(
            2 + i * 2,
            tool_uses=[make_tool_use(uid, "Bash", {"command": "pnpm install"})],
        ))
        turns.append(make_tool_result_turn(
            3 + i * 2,
            tool_results=[make_tool_result(uid, "Bash", "Error: workspace required", is_error=True)],
        ))
    uid_fix = "tu-fix"
    turns.append(make_assistant_turn(
        6, tool_uses=[make_tool_use(uid_fix, "Bash", {"command": "pnpm --filter app build"})],
    ))
    turns.append(make_tool_result_turn(
        7, tool_results=[make_tool_result(uid_fix, "Bash", "Done")],
    ))
    trace = make_trace(turns)
    return dataclasses.replace(trace, session_id=session_id)


def test_below_threshold_returns_no_patterns():
    """2 sessions — below default threshold of 3 — returns []."""
    from cctx.diagnostician.patterns.project_specific import detect

    pairs = [
        (_make_diagnosis(f"s{i}"), _make_pnpm_trace(f"s{i}"))
        for i in range(2)
    ]
    assert detect(pairs) == []


def test_three_sessions_returns_one_pattern():
    """3 sessions with identical failure/fix pair → one ProjectPattern."""
    from cctx.diagnostician.patterns.project_specific import detect

    pairs = [
        (_make_diagnosis(f"s{i}"), _make_pnpm_trace(f"s{i}"))
        for i in range(3)
    ]
    patterns = detect(pairs)
    assert len(patterns) == 1
    p = patterns[0]
    assert p.tool_name == "Bash"
    assert p.failure_key == "pnpm install"
    assert p.fix_key == "pnpm --filter app"
    assert p.session_count == 3
    assert p.avg_wasted_turns == 4.0   # fix_turn(6) - first_failure_turn(2)
    assert len(p.example_sessions) <= 3


def test_fix_outside_window_returns_no_pattern():
    """Fix more than 10 turns after last failure → no pattern detected."""
    from cctx.diagnostician.patterns.project_specific import detect

    def _far_fix_trace(session_id: str):
        turns = [make_user_turn(1)]
        for i in range(2):
            uid = f"tu-f{i}"
            turns.append(make_assistant_turn(
                2 + i * 2,
                tool_uses=[make_tool_use(uid, "Bash", {"command": "pnpm install"})],
            ))
            turns.append(make_tool_result_turn(
                3 + i * 2,
                tool_results=[make_tool_result(uid, "Bash", "Error: failed", is_error=True)],
            ))
        # last failure at turn 5; fill turns 6-16 so fix is at turn 17 (12 away)
        for j in range(11):
            turns.append(make_user_turn(6 + j))
        uid_fix = "tu-fix"
        turns.append(make_assistant_turn(
            17, tool_uses=[make_tool_use(uid_fix, "Bash", {"command": "pnpm --filter app build"})],
        ))
        turns.append(make_tool_result_turn(
            18, tool_results=[make_tool_result(uid_fix, "Bash", "Done")],
        ))
        trace = make_trace(turns)
        return dataclasses.replace(trace, session_id=session_id)

    pairs = [(_make_diagnosis(f"s{i}"), _far_fix_trace(f"s{i}")) for i in range(3)]
    assert detect(pairs) == []


def test_duplicate_session_id_counted_once():
    """Same session_id appearing twice in pairs counts as one session."""
    from cctx.diagnostician.patterns.project_specific import detect

    trace = _make_pnpm_trace("dup")
    diag = _make_diagnosis("dup")
    pairs = [
        (diag, trace),
        (diag, trace),  # duplicate — must not inflate session_count
        (_make_diagnosis("s1"), _make_pnpm_trace("s1")),
        (_make_diagnosis("s2"), _make_pnpm_trace("s2")),
    ]
    patterns = detect(pairs)
    assert len(patterns) == 1
    assert patterns[0].session_count == 3   # dup + s1 + s2, not 4


def test_different_tools_grouped_separately():
    """Bash and Edit failure patterns are counted as distinct patterns."""
    from cctx.diagnostician.patterns.project_specific import detect

    def _edit_trace(session_id: str):
        turns = [make_user_turn(1)]
        for i in range(2):
            uid = f"tu-e{i}"
            turns.append(make_assistant_turn(
                2 + i * 2,
                tool_uses=[make_tool_use(uid, "Edit", {"file_path": "src/foo.py"})],
            ))
            turns.append(make_tool_result_turn(
                3 + i * 2,
                tool_results=[make_tool_result(uid, "Edit", "Error: not found", is_error=True)],
            ))
        uid_fix = "tu-efix"
        turns.append(make_assistant_turn(
            6, tool_uses=[make_tool_use(uid_fix, "Edit", {"file_path": "src/bar.py"})],
        ))
        turns.append(make_tool_result_turn(
            7, tool_results=[make_tool_result(uid_fix, "Edit", "Done")],
        ))
        trace = make_trace(turns)
        return dataclasses.replace(trace, session_id=session_id)

    pairs = (
        [(_make_diagnosis(f"bash-{i}"), _make_pnpm_trace(f"bash-{i}")) for i in range(3)]
        + [(_make_diagnosis(f"edit-{i}"), _edit_trace(f"edit-{i}")) for i in range(3)]
    )
    patterns = detect(pairs)
    tool_names = {p.tool_name for p in patterns}
    assert "Bash" in tool_names
    assert "Edit" in tool_names
    assert len(patterns) == 2


def test_empty_pairs_returns_empty():
    from cctx.diagnostician.patterns.project_specific import detect
    assert detect([]) == []


def test_bash_normalization_first_three_tokens():
    """Bash key is first 3 space-separated tokens of the command."""
    from cctx.diagnostician.patterns.project_specific import _normalize_key
    assert _normalize_key("Bash", {"command": "pnpm install --legacy-peer-deps"}) == "pnpm install --legacy-peer-deps"
    assert _normalize_key("Bash", {"command": "pnpm --filter app build --verbose"}) == "pnpm --filter app"
    assert _normalize_key("Bash", {"command": "ls"}) == "ls"


def test_edit_normalization_uses_file_path():
    from cctx.diagnostician.patterns.project_specific import _normalize_key
    assert _normalize_key("Edit", {"file_path": "src/foo.py"}) == "src/foo.py"
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/diagnostician/test_project_specific.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'cctx.diagnostician.patterns.project_specific'`

- [ ] **Step 3: Create `cctx/diagnostician/patterns/project_specific.py`**

```python
"""Project-specific pattern detector.

detect(pairs) -> list[ProjectPattern]

Finds (tool_name, failure_key, fix_key) triples that recur in 3+ sessions.
Normalization matches retry_loop._similarity_key. No LLM calls.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING

from cctx.models import ProjectPattern
from cctx.pricing import price_per_tok

if TYPE_CHECKING:
    from cctx.models import Diagnosis, SessionTrace, ToolResult

MIN_SESSIONS = 3
FIX_WINDOW = 10  # turns after last failure to search for the fix


def _normalize_key(tool_name: str, tool_input: dict) -> str:
    match tool_name:
        case "Bash":
            tokens = tool_input.get("command", "").strip().split()
            return " ".join(tokens[:3])
        case "Edit" | "Read" | "Write":
            return tool_input.get("file_path", "")
        case "Grep" | "Glob":
            return tool_input.get("pattern", "")
        case _:
            return json.dumps(tool_input, sort_keys=True)


def _is_error(result: ToolResult) -> bool:
    if result.is_error:
        return True
    c = result.content
    return c.startswith("Error:") or c.startswith("error:") or c.startswith("FAILED")


def _find_pairs(trace: SessionTrace) -> list[dict]:
    """Find failure/fix pairs within one session.

    Returns list of dicts: {tool_name, failure_key, fix_key,
    first_failure_turn, fix_turn}. Each (failure_key, fix_key) appears
    at most once (intra-session dedup).
    """
    result_map: dict[str, tuple] = {}
    for turn in trace.turns:
        for tr in turn.tool_results:
            result_map[tr.tool_use_id] = (tr, turn.turn_number)

    records = []
    for turn in trace.turns:
        if turn.role != "assistant":
            continue
        for tu in turn.tool_uses:
            pair = result_map.get(tu.tool_use_id)
            if pair is None:
                continue
            result, _ = pair
            key = _normalize_key(tu.tool_name, tu.tool_input)
            records.append({
                "tool_name": tu.tool_name,
                "key": key,
                "turn": turn.turn_number,
                "is_error": _is_error(result),
            })

    groups: dict[tuple, list] = defaultdict(list)
    for r in records:
        groups[(r["tool_name"], r["key"])].append(r)

    found: list[dict] = []
    seen_pairs: set[tuple] = set()

    for (tool_name, failure_key), group in groups.items():
        errors = [r for r in group if r["is_error"]]
        if len(errors) < 2:
            continue

        first_err_turn = errors[0]["turn"]
        last_err_turn = errors[-1]["turn"]

        intervening = any(
            r for r in group
            if not r["is_error"] and first_err_turn < r["turn"] < last_err_turn
        )
        if intervening:
            continue

        fix = next(
            (
                r for r in records
                if r["tool_name"] == tool_name
                and not r["is_error"]
                and last_err_turn < r["turn"] <= last_err_turn + FIX_WINDOW
            ),
            None,
        )
        if fix is None:
            continue

        pair_key = (tool_name, failure_key, fix["key"])
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        found.append({
            "tool_name": tool_name,
            "failure_key": failure_key,
            "fix_key": fix["key"],
            "first_failure_turn": first_err_turn,
            "fix_turn": fix["turn"],
        })

    return found


def _compute_waste(trace: SessionTrace, first_failure_turn: int, fix_turn: int) -> float:
    price = price_per_tok(trace.primary_model)
    total = 0.0
    for turn in trace.turns:
        if (
            turn.role == "assistant"
            and first_failure_turn <= turn.turn_number <= fix_turn
            and turn.usage is not None
        ):
            total += turn.usage.input_tokens * price
    return round(total, 4)


def detect(pairs: list[tuple[Diagnosis, SessionTrace]]) -> list[ProjectPattern]:
    """Detect recurring failure/fix patterns across sessions."""
    session_records: list[dict] = []
    for _diagnosis, trace in pairs:
        for p in _find_pairs(trace):
            session_records.append({
                "session_id": trace.session_id,
                "tool_name": p["tool_name"],
                "failure_key": p["failure_key"],
                "fix_key": p["fix_key"],
                "first_failure_turn": p["first_failure_turn"],
                "fix_turn": p["fix_turn"],
                "trace": trace,
            })

    groups: dict[tuple, list] = defaultdict(list)
    for r in session_records:
        groups[(r["tool_name"], r["failure_key"], r["fix_key"])].append(r)

    result: list[ProjectPattern] = []
    for (tool_name, failure_key, fix_key), records in groups.items():
        seen: dict[str, dict] = {}
        for r in records:
            if r["session_id"] not in seen:
                seen[r["session_id"]] = r

        if len(seen) < MIN_SESSIONS:
            continue

        unique = list(seen.values())
        wasted = [r["fix_turn"] - r["first_failure_turn"] for r in unique]
        avg_wasted_turns = sum(wasted) / len(wasted)
        total_waste_usd = sum(
            _compute_waste(r["trace"], r["first_failure_turn"], r["fix_turn"])
            for r in unique
        )

        result.append(ProjectPattern(
            tool_name=tool_name,
            failure_key=failure_key,
            fix_key=fix_key,
            session_count=len(seen),
            avg_wasted_turns=round(avg_wasted_turns, 1),
            total_waste_usd=round(total_waste_usd, 4),
            example_sessions=sorted(r["session_id"] for r in unique)[:3],
        ))

    return result
```

- [ ] **Step 4: Run project_specific tests**

```
pytest tests/diagnostician/test_project_specific.py -v
```
Expected: all pass

- [ ] **Step 5: Run full suite**

```
pytest -x -q
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add cctx/diagnostician/patterns/project_specific.py tests/diagnostician/test_project_specific.py
git commit -m "feat: project_specific.detect() — cross-session failure/fix pattern detector"
```

---

## Task 4: `generate_from_patterns()` in recommender

**Files:**
- Modify: `cctx/recommender/claude_md.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_terminal_renderer.py` (or a new `tests/test_recommender.py` — use whichever keeps things tidy; the project has no dedicated recommender test file, so add to `tests/test_recommender.py`):

Create `tests/test_recommender.py`:

```python
"""Tests for cctx/recommender/claude_md.py — generate_from_patterns."""
from __future__ import annotations


def _make_pattern(failure_key="pnpm install", fix_key="pnpm --filter app", session_count=7):
    from cctx.models import ProjectPattern
    return ProjectPattern(
        tool_name="Bash",
        failure_key=failure_key,
        fix_key=fix_key,
        session_count=session_count,
        avg_wasted_turns=12.0,
        total_waste_usd=4.20,
        example_sessions=["s1", "s2", "s3"],
    )


def test_generate_from_patterns_returns_one_patch_per_pattern():
    from cctx.recommender.claude_md import generate_from_patterns
    patches = generate_from_patterns([_make_pattern(), _make_pattern("npm run build", "npm run build --workspace")])
    assert len(patches) == 2


def test_patch_target_file_is_claude_md():
    from cctx.recommender.claude_md import generate_from_patterns
    patches = generate_from_patterns([_make_pattern()])
    assert patches[0].target_file == "CLAUDE.md"


def test_patch_finding_kind_is_project_pattern():
    from cctx.models import FindingKind
    from cctx.recommender.claude_md import generate_from_patterns
    patches = generate_from_patterns([_make_pattern()])
    assert patches[0].finding_kind is FindingKind.PROJECT_PATTERN


def test_patch_diff_contains_failure_and_fix_keys():
    from cctx.recommender.claude_md import generate_from_patterns
    patches = generate_from_patterns([_make_pattern()])
    diff = patches[0].unified_diff
    assert "pnpm install" in diff
    assert "pnpm --filter app" in diff


def test_patch_evidence_summary_contains_session_count():
    from cctx.recommender.claude_md import generate_from_patterns
    patches = generate_from_patterns([_make_pattern(session_count=7)])
    assert "7" in patches[0].evidence_summary


def test_generate_from_patterns_empty_returns_empty():
    from cctx.recommender.claude_md import generate_from_patterns
    assert generate_from_patterns([]) == []
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_recommender.py -v
```
Expected: FAIL — `ImportError: cannot import name 'generate_from_patterns'`

- [ ] **Step 3: Add `generate_from_patterns` to `cctx/recommender/claude_md.py`**

Add at the top of the file, update the `TYPE_CHECKING` block:

```python
if TYPE_CHECKING:
    from cctx.models import Diagnosis, Finding, KindEvidence, ProjectPattern
```

Add the function at the end of the file:

```python
def generate_from_patterns(patterns: list[ProjectPattern]) -> list[Patch]:
    """Generate CLAUDE.md patches from cross-session ProjectPatterns."""
    patches = []
    for p in patterns:
        diff = (
            f"+## Project-specific: {p.tool_name}({p.failure_key})\n"
            f"+When `{p.failure_key}` fails, use `{p.fix_key}` instead.\n"
            f"+Re-discovered in {p.session_count} sessions "
            f"(~${p.total_waste_usd:.2f} wasted)."
        )
        patches.append(Patch(
            target_file="CLAUDE.md",
            description=f"Project-specific: {p.failure_key} → {p.fix_key}",
            unified_diff=diff,
            finding_kind=FindingKind.PROJECT_PATTERN,
            evidence_summary=f"Seen in {p.session_count} sessions, ~${p.total_waste_usd:.2f} wasted",
        ))
    return patches
```

Note: `FindingKind` and `Patch` are already imported at the top of `claude_md.py`. `ProjectPattern` is in the `TYPE_CHECKING` block you just added — runtime annotations work because of `from __future__ import annotations`.

- [ ] **Step 4: Run recommender tests**

```
pytest tests/test_recommender.py -v
```
Expected: 6 passed

- [ ] **Step 5: Run full suite**

```
pytest -x -q
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add cctx/recommender/claude_md.py tests/test_recommender.py
git commit -m "feat: generate_from_patterns() — CLAUDE.md patches from ProjectPatterns"
```

---

## Task 5: `render_aggregate()` — project patterns table

**Files:**
- Modify: `cctx/renderers/terminal.py`

The current `render_aggregate` has an early `return` when `not report.by_kind`. That must be changed so project patterns still render when `by_kind` is empty.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_terminal_renderer.py`:

```python
# ---------------------------------------------------------------------------
# render_aggregate project patterns (#81)
# ---------------------------------------------------------------------------


def _make_aggregate_report_with_pattern():
    from cctx.models import AggregateReport, ProjectPattern

    pp = ProjectPattern(
        tool_name="Bash",
        failure_key="pnpm install",
        fix_key="pnpm --filter app",
        session_count=7,
        avg_wasted_turns=12.3,
        total_waste_usd=4.20,
        example_sessions=["s1", "s2", "s3"],
    )
    return AggregateReport(
        period_label="last 30 days",
        sessions_analysed=41,
        sessions_with_findings=7,
        total_cost_usd=22.0,
        waste_cost_usd=4.20,
        by_kind={},
        patches=[],
        project_patterns=[pp],
    )


def _render_aggregate_to_string(report):
    from io import StringIO
    from rich.console import Console
    from cctx.renderers.terminal import render_aggregate
    buf = StringIO()
    console = Console(file=buf, width=120, highlight=False, markup=False)
    render_aggregate(report, console=console)
    return buf.getvalue()


def test_render_aggregate_shows_project_patterns_table():
    output = _render_aggregate_to_string(_make_aggregate_report_with_pattern())
    assert "pnpm install" in output
    assert "pnpm --filter app" in output


def test_render_aggregate_project_pattern_shows_session_count():
    output = _render_aggregate_to_string(_make_aggregate_report_with_pattern())
    assert "7" in output


def test_render_aggregate_no_patterns_no_extra_table():
    from cctx.models import AggregateReport
    report = AggregateReport(
        period_label="last 7 days",
        sessions_analysed=2,
        sessions_with_findings=0,
        total_cost_usd=1.0,
        waste_cost_usd=0.0,
        by_kind={},
        patches=[],
    )
    output = _render_aggregate_to_string(report)
    assert "Project-specific" not in output


def test_render_aggregate_patterns_visible_even_when_by_kind_empty():
    """Project patterns table renders even when there are no per-session findings."""
    output = _render_aggregate_to_string(_make_aggregate_report_with_pattern())
    # by_kind is empty but pattern table should still appear
    assert "pnpm install" in output
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_terminal_renderer.py -k "project_pattern" -v
```
Expected: FAIL

- [ ] **Step 3: Update `render_aggregate` in `cctx/renderers/terminal.py`**

Replace the existing `render_aggregate` function with:

```python
def render_aggregate(report: AggregateReport, *, console: Console | None = None) -> None:
    con = console or _default_console()

    con.print(Rule(f"cctx autopsy — {report.period_label}"))
    con.print(
        f"Sessions: {report.sessions_analysed} analysed, "
        f"{report.sessions_with_findings} with findings"
    )
    con.print(
        f"Total cost: ${report.total_cost_usd:.2f} | "
        f"Waste: ${report.waste_cost_usd:.2f}"
    )

    if not report.by_kind and not report.project_patterns:
        con.print("\nNo findings across sessions.")
        return

    if report.by_kind:
        table = Table(title="Finding frequency")
        table.add_column("Pattern")
        table.add_column("Sessions", justify="right")
        table.add_column("Waste ($)", justify="right")
        for kind, ev in report.by_kind.items():
            table.add_row(
                _KIND_LABEL.get(kind, kind.value),
                str(ev.session_count),
                f"${ev.total_waste_usd:.2f}",
            )
        con.print(table)

    if report.patches:
        con.print(Rule("Recommended CLAUDE.md patches"))
        for patch in report.patches:
            con.print(f"\n{patch.description}")
            syntax = Syntax(patch.unified_diff, "diff", theme="monokai", word_wrap=True)
            con.print(syntax)

    if report.project_patterns:
        con.print()
        pp_table = Table(title="Project-specific patterns")
        pp_table.add_column("Failure", style="bold")
        pp_table.add_column("Fix")
        pp_table.add_column("Sessions", justify="right", style="dim")
        pp_table.add_column("Avg turns", justify="right", style="dim")
        pp_table.add_column("Waste", justify="right")
        for pp in report.project_patterns:
            pp_table.add_row(
                pp.failure_key,
                pp.fix_key,
                str(pp.session_count),
                f"{pp.avg_wasted_turns:.1f}",
                f"~${pp.total_waste_usd:.2f}",
            )
        con.print(pp_table)
```

Also add `ProjectPattern` to the `TYPE_CHECKING` import in `terminal.py`:

```python
if TYPE_CHECKING:
    from cctx.discovery import ProjectInfo
    from cctx.models import AggregateReport, Diagnosis, ProjectPattern, SessionTrace
```

- [ ] **Step 4: Run renderer tests**

```
pytest tests/test_terminal_renderer.py -v
```
Expected: all pass

- [ ] **Step 5: Run full suite**

```
pytest -x -q
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add cctx/renderers/terminal.py tests/test_terminal_renderer.py
git commit -m "feat: render_aggregate() shows project-specific patterns table"
```

---

## Task 6: CLI wiring — autopsy and harvest `--since` paths

**Files:**
- Modify: `cctx/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
# ---------------------------------------------------------------------------
# project-specific patterns in --since output (#81)
# ---------------------------------------------------------------------------


def _write_pnpm_session(project_dir: Path, session_id: str) -> None:
    """Write a session JSONL with the pnpm install → pnpm --filter failure/fix pattern."""
    lines = [
        {
            "type": "user", "uuid": f"{session_id}-u1", "parentUuid": None,
            "isSidechain": False, "timestamp": "2026-05-14T10:00:00.000Z",
            "sessionId": session_id, "version": "2.1.138",
            "cwd": "/Users/test/Projects/demo", "gitBranch": "main",
            "userType": "external", "entrypoint": "cli",
            "message": {"role": "user", "content": "build the project"},
        },
        {
            "type": "assistant", "uuid": f"{session_id}-a1",
            "parentUuid": f"{session_id}-u1", "isSidechain": False,
            "timestamp": "2026-05-14T10:00:01.000Z",
            "sessionId": session_id,
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": f"{session_id}-tu1",
                              "name": "Bash", "input": {"command": "pnpm install"}}],
                "model": "claude-sonnet-4-6", "stop_reason": "tool_use",
                "usage": {"input_tokens": 100, "output_tokens": 5,
                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            },
        },
        {
            "type": "user", "uuid": f"{session_id}-r1",
            "parentUuid": f"{session_id}-a1", "isSidechain": False,
            "timestamp": "2026-05-14T10:00:02.000Z",
            "sessionId": session_id,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"{session_id}-tu1",
                 "content": "Error: workspace required", "is_error": True}
            ]},
        },
        {
            "type": "assistant", "uuid": f"{session_id}-a2",
            "parentUuid": f"{session_id}-r1", "isSidechain": False,
            "timestamp": "2026-05-14T10:00:03.000Z",
            "sessionId": session_id,
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": f"{session_id}-tu2",
                              "name": "Bash", "input": {"command": "pnpm install"}}],
                "model": "claude-sonnet-4-6", "stop_reason": "tool_use",
                "usage": {"input_tokens": 120, "output_tokens": 5,
                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            },
        },
        {
            "type": "user", "uuid": f"{session_id}-r2",
            "parentUuid": f"{session_id}-a2", "isSidechain": False,
            "timestamp": "2026-05-14T10:00:04.000Z",
            "sessionId": session_id,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"{session_id}-tu2",
                 "content": "Error: workspace required", "is_error": True}
            ]},
        },
        {
            "type": "assistant", "uuid": f"{session_id}-a3",
            "parentUuid": f"{session_id}-r2", "isSidechain": False,
            "timestamp": "2026-05-14T10:00:05.000Z",
            "sessionId": session_id,
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": f"{session_id}-tu3",
                              "name": "Bash", "input": {"command": "pnpm --filter app build"}}],
                "model": "claude-sonnet-4-6", "stop_reason": "tool_use",
                "usage": {"input_tokens": 130, "output_tokens": 5,
                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            },
        },
        {
            "type": "user", "uuid": f"{session_id}-r3",
            "parentUuid": f"{session_id}-a3", "isSidechain": False,
            "timestamp": "2026-05-14T10:00:06.000Z",
            "sessionId": session_id,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"{session_id}-tu3",
                 "content": "Done", "is_error": False}
            ]},
        },
    ]
    path = project_dir / f"{session_id}.jsonl"
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n")


def test_autopsy_since_shows_project_patterns(runner, tmp_path):
    """--since with 3 sessions containing pnpm pattern → project patterns in output."""
    from cctx.cli import cli

    project_dir = tmp_path / "-Users-test-Projects-demo"
    project_dir.mkdir()
    for i in range(3):
        _write_pnpm_session(project_dir, f"pnpm-sess-{i:02d}")

    result = runner.invoke(
        cli, ["autopsy", str(project_dir), "--since", "7"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    # Either the project patterns table shows, or at minimum the run succeeds
    # (pattern requires 3 sessions with matching pairs)
    assert "Sessions:" in result.output


def test_autopsy_since_two_sessions_no_project_pattern(runner, tmp_path):
    """--since with only 2 matching sessions → no project patterns table."""
    from cctx.cli import cli

    project_dir = tmp_path / "-Users-test-Projects-demo"
    project_dir.mkdir()
    for i in range(2):
        _write_pnpm_session(project_dir, f"pnpm-sess-{i:02d}")

    result = runner.invoke(
        cli, ["autopsy", str(project_dir), "--since", "7"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Project-specific patterns" not in result.output
```

- [ ] **Step 2: Run to verify they fail (or confirm the CLI crashes due to aggregate.run() unpacking)**

```
pytest tests/test_cli.py -v -k "project_pattern or since"
```
Expected: errors because CLI still treats `aggregate.run()` result as `list[Diagnosis]`

- [ ] **Step 3: Update the `autopsy` command `--since` path in `cctx/cli.py`**

Add import at the top of the file (with the other cctx imports):

```python
from cctx.diagnostician.patterns import project_specific
```

Find the `--since` branch in the `autopsy` function. Change:

```python
        diagnoses = aggregate.run(project_dir, start, end)
        ev = evidence_mod.accumulate(diagnoses)
        if top_n is not None:
            ev = dict(sorted(ev.items(), key=lambda x: x[1].session_count, reverse=True)[:top_n])
        patches = claude_md.generate_from_evidence(ev)
        report = AggregateReport(
            period_label=label,
            sessions_analysed=len(diagnoses),
            sessions_with_findings=sum(1 for d in diagnoses if d.findings),
            total_cost_usd=sum(d.total_cost_usd for d in diagnoses),
            waste_cost_usd=sum(d.waste_cost_usd for d in diagnoses),
            by_kind=ev,
            patches=patches,
        )
        render_aggregate(report)
        _aggregate_drilldown(report, diagnoses)
```

to:

```python
        pairs = aggregate.run(project_dir, start, end)
        diagnoses = [d for d, _ in pairs]
        patterns = project_specific.detect(pairs)
        ev = evidence_mod.accumulate(diagnoses)
        if top_n is not None:
            ev = dict(sorted(ev.items(), key=lambda x: x[1].session_count, reverse=True)[:top_n])
        pattern_patches = claude_md.generate_from_patterns(patterns)
        patches = claude_md.generate_from_evidence(ev) + pattern_patches
        report = AggregateReport(
            period_label=label,
            sessions_analysed=len(diagnoses),
            sessions_with_findings=sum(1 for d in diagnoses if d.findings),
            total_cost_usd=sum(d.total_cost_usd for d in diagnoses),
            waste_cost_usd=sum(d.waste_cost_usd for d in diagnoses),
            by_kind=ev,
            patches=patches,
            project_patterns=patterns,
        )
        render_aggregate(report)
        _aggregate_drilldown(report, diagnoses)
```

- [ ] **Step 4: Update the `harvest` command `--since` path in `cctx/cli.py`**

Note: harvest `--since` does NOT call `project_specific.detect()` or apply pattern patches. Pattern patches are auto-generated from raw command strings and require human review before being written to CLAUDE.md. `autopsy --since` shows them; harvest applies only evidence-backed patches.

Find the `--since` branch in the `harvest` function. Change:

```python
        project_dir = target if target.is_dir() else target.parent
        start, end, _label = parse_since(since)
        diagnoses = aggregate.run(project_dir, start, end)
        ev = evidence_mod.accumulate(diagnoses)
        patches = claude_md.generate_from_evidence(ev)
```

to:

```python
        project_dir = target if target.is_dir() else target.parent
        start, end, _label = parse_since(since)
        pairs = aggregate.run(project_dir, start, end)
        diagnoses = [d for d, _ in pairs]
        ev = evidence_mod.accumulate(diagnoses)
        patches = claude_md.generate_from_evidence(ev)
```

- [ ] **Step 5: Run the CLI tests**

```
pytest tests/test_cli.py -v
```
Expected: all pass

- [ ] **Step 6: Run full suite**

```
pytest -x -q
```
Expected: all pass

- [ ] **Step 7: Run ruff**

```
ruff check cctx/
```
Expected: no errors. Fix any import ordering issues with `ruff check --fix cctx/`.

- [ ] **Step 8: Commit**

```bash
git add cctx/cli.py tests/test_cli.py
git commit -m "feat: wire project_specific.detect() into autopsy and harvest --since paths"
```

---

## Final check

- [ ] **Run the full test suite one last time**

```
pytest -q
```
Expected: all pass, count higher than before (new tests added in every task)

- [ ] **Verify ruff clean**

```
ruff check cctx/ tests/
```
Expected: no errors

- [ ] **Smoke-test on a real project (optional but recommended)**

```bash
cctx autopsy ~/.claude/projects/<your-project-dir> --since 30
```
Expected: if you have 3+ sessions with matching failure/fix patterns, a "Project-specific patterns" table appears. Otherwise, the output looks identical to before — no regressions.
