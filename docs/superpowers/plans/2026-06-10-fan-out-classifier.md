# Fan-out Waste Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement M16 #89 — classify wasteful subagent fan-outs (overlapping prompts, failed-then-retried) as a new `FANOUT_WASTE` finding kind with copy-pasteable CLAUDE.md patches.

**Architecture:** A new `fan_out.py` pattern classifier fires on two signals (Signal A: overlapping Agent prompts by Jaccard similarity; Signal B: failed Agent call followed by a similar re-spawn). The classifier returns findings with `cost_usd=None`; a new `_patch_fanout_costs()` in the diagnostician fills in costs from already-computed subagent attributions. Signal C (unused-result) is deferred — the 6-gram approach fires false positives on paraphrased references and is not ship-ready.

**Tech Stack:** Python 3.10+, pytest, `cctx.models`, `cctx.diagnostician`, `cctx.recommender`

---

## Design decisions locked in (do not revisit during implementation)

**Single kind:** `FindingKind.FANOUT_WASTE` — one kind covers both signals; a `"signal": "overlap"|"retry"` key in evidence discriminates them. Three separate kinds (overlap/retry/unused) would require three identical template entries and a duplicate-heading collision in `MANAGED_HEADINGS`; one kind avoids both.

**Two signals only:** Signal A (overlap, Jaccard ≥ 0.65, ≥ 50 words) and Signal B (failed-retry, Jaccard ≥ 0.50, ≥ 30 words). Signal C (unused-result) deferred.

**Empirical threshold basis:** 49 real Agent calls from `with-subagents.jsonl` measured at zero pairs above Jaccard 0.30 on 3-grams (both ≥ 50 words). The 0.65 threshold does not fire on clean implement→review→fix pipelines.

**Sequencing in `run()`:** `fan_out.classify()` runs with the other classifiers → `_patch_costs()` → `_collect_attributions()` → `_patch_fanout_costs()` → deduplicated `waste_cost` computation. The waste dedup prevents a subagent flagged by both overlap AND retry from being double-counted.

---

## Files touched

| File | Change |
|---|---|
| `cctx/models.py` | Add `FANOUT_WASTE` to `FindingKind`, `KIND_LABEL`, `MANAGED_HEADINGS` |
| `cctx/diagnostician/patterns/fan_out.py` | New file — Signal A + B classifier |
| `cctx/diagnostician/__init__.py` | Import fan_out, add `_patch_fanout_costs`, fix `run()` sequencing |
| `cctx/recommender/claude_md.py` | Add `_FANOUT_WASTE_DIFF` + `_TEMPLATES` entry |
| `tests/test_harvest_emit.py` | Update `test_managed_headings_cover_the_five_diagnostic_kinds` → six |
| `tests/test_fanout_classifier.py` | New test file (10 tests) |

---

## Task A: FindingKind.FANOUT_WASTE + models update

**Context:** `cctx/models.py` owns all `FindingKind`, `KIND_LABEL`, and `MANAGED_HEADINGS` constants. The existing test `test_managed_headings_cover_the_five_diagnostic_kinds` does an exact-dict equality check — it will break when a sixth kind is added and must be updated in the same task.

**Files:**
- Modify: `cctx/models.py:169-197`
- Modify: `tests/test_harvest_emit.py:5-13`

- [ ] **Step 1: Write the failing test (KIND_LABEL)**

Add to `tests/test_fanout_classifier.py` (new file):

```python
"""Tests for fan_out classifier (M16 #89) and related models."""
from __future__ import annotations


def test_fanout_waste_kind_exists():
    from cctx.models import FindingKind
    assert FindingKind.FANOUT_WASTE == "fanout_waste"


def test_fanout_waste_has_kind_label():
    from cctx.models import KIND_LABEL, FindingKind
    assert KIND_LABEL[FindingKind.FANOUT_WASTE] == "FANOUT WASTE"


def test_fanout_waste_has_managed_heading():
    from cctx.models import MANAGED_HEADINGS, FindingKind
    assert MANAGED_HEADINGS[FindingKind.FANOUT_WASTE] == "## Fan-out discipline"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/bryan/Projects/cctx && uv run pytest tests/test_fanout_classifier.py::test_fanout_waste_kind_exists tests/test_fanout_classifier.py::test_fanout_waste_has_kind_label tests/test_fanout_classifier.py::test_fanout_waste_has_managed_heading -v
```

Expected: FAIL with `AttributeError: FANOUT_WASTE`

- [ ] **Step 3: Add FANOUT_WASTE to models.py**

In `cctx/models.py`, update `FindingKind` (line ~169):
```python
class FindingKind(str, Enum):
    RETRY_LOOP    = "retry_loop"
    SCOPE_CREEP   = "scope_creep"
    STALE_CONTEXT = "stale_context"
    TOOL_THRASH   = "tool_thrash"
    DEAD_END      = "dead_end"
    PROJECT_PATTERN = "project_pattern"
    FANOUT_WASTE  = "fanout_waste"
```

Update `KIND_LABEL` (line ~178):
```python
KIND_LABEL: dict[FindingKind, str] = {
    FindingKind.RETRY_LOOP:      "RETRY LOOP",
    FindingKind.SCOPE_CREEP:     "SCOPE CREEP",
    FindingKind.STALE_CONTEXT:   "STALE CONTEXT",
    FindingKind.TOOL_THRASH:     "TOOL THRASH",
    FindingKind.DEAD_END:        "DEAD END",
    FindingKind.PROJECT_PATTERN: "PROJECT PATTERN",
    FindingKind.FANOUT_WASTE:    "FANOUT WASTE",
}
```

Update `MANAGED_HEADINGS` (line ~191):
```python
MANAGED_HEADINGS: dict[FindingKind, str] = {
    FindingKind.RETRY_LOOP:    "## Retry discipline",
    FindingKind.SCOPE_CREEP:   "## Scope discipline",
    FindingKind.STALE_CONTEXT: "## Context hygiene",
    FindingKind.TOOL_THRASH:   "## Tool-call discipline",
    FindingKind.DEAD_END:      "## Exploration discipline",
    FindingKind.FANOUT_WASTE:  "## Fan-out discipline",
}
```

- [ ] **Step 4: Update the exact-dict test in test_harvest_emit.py**

In `tests/test_harvest_emit.py`, replace `test_managed_headings_cover_the_five_diagnostic_kinds` (lines 5–13):
```python
def test_managed_headings_cover_the_six_diagnostic_kinds():
    from cctx.models import MANAGED_HEADINGS, FindingKind
    assert MANAGED_HEADINGS == {
        FindingKind.RETRY_LOOP:    "## Retry discipline",
        FindingKind.SCOPE_CREEP:   "## Scope discipline",
        FindingKind.STALE_CONTEXT: "## Context hygiene",
        FindingKind.TOOL_THRASH:   "## Tool-call discipline",
        FindingKind.DEAD_END:      "## Exploration discipline",
        FindingKind.FANOUT_WASTE:  "## Fan-out discipline",
    }
```

- [ ] **Step 5: Run all three new tests + existing harvest emit tests**

```bash
uv run pytest tests/test_fanout_classifier.py::test_fanout_waste_kind_exists tests/test_fanout_classifier.py::test_fanout_waste_has_kind_label tests/test_fanout_classifier.py::test_fanout_waste_has_managed_heading tests/test_harvest_emit.py -v
```

Expected: all 3 new tests PASS; all harvest emit tests PASS (including the renamed one).

- [ ] **Step 6: Commit**

```bash
git add cctx/models.py tests/test_harvest_emit.py tests/test_fanout_classifier.py
git commit -m "feat: add FindingKind.FANOUT_WASTE + KIND_LABEL + MANAGED_HEADINGS"
```

---

## Task B: fan_out.py classifier (Signal A + Signal B)

**Context:** Pattern classifiers live in `cctx/diagnostician/patterns/`. Each is a module with `classify(trace: SessionTrace) -> list[Finding]` as its public API, wrapped in a try/except that returns `[]` on any error. Module-level constants name all thresholds. `ToolUse.subagent_session_id` is set on Agent calls when the child session was matched; it may be `None` for orphans.

**Files:**
- Create: `cctx/diagnostician/patterns/fan_out.py`
- Modify: `tests/test_fanout_classifier.py`

- [ ] **Step 1: Write test helpers (add to test_fanout_classifier.py)**

Append to `tests/test_fanout_classifier.py`:

```python
# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

from datetime import datetime, timezone
from pathlib import Path

from cctx.models import (
    Attachment, RawToolResultFile, SessionTrace, ToolResult, ToolUse, Turn, Usage,
)

_TS = datetime(2026, 6, 10, tzinfo=timezone.utc)
_USAGE = Usage(100, 50, 0, 0, 0, None)


def _tu(tool_name: str, uid: str, tool_input: dict, subagent_session_id: str | None = None) -> ToolUse:
    return ToolUse(
        tool_name=tool_name,
        tool_use_id=uid,
        tool_input=tool_input,
        subagent_session_id=subagent_session_id,
    )


def _tr(tool_name: str, uid: str, content: str = "ok", is_error: bool = False) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        tool_use_id=uid,
        content=content,
        structured=None,
        is_error=is_error,
    )


def _turn(n: int, role: str, tool_uses: list | None = None, tool_results: list | None = None, text: str = "") -> Turn:
    return Turn(
        turn_number=n,
        uuid=f"uuid-{n}",
        parent_uuid=None,
        role=role,
        text=text,
        thinking="",
        tool_uses=tool_uses or [],
        tool_results=tool_results or [],
        usage=_USAGE if role == "assistant" else None,
        model="claude-sonnet-4-6",
        stop_reason="tool_use" if tool_uses else "end_turn",
        timestamp=_TS,
        duration_ms=100,
    )


def _trace(turns: list[Turn]) -> SessionTrace:
    return SessionTrace(
        session_id="test-session",
        parent_session_id=None,
        project_path="/test",
        cwd="/test",
        primary_model="claude-sonnet-4-6",
        claude_code_version="1.0",
        turns=turns,
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=_TS,
        end_time=_TS,
        source_path=Path("/test/session.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


# Prompts used in Signal A tests.
# _LONG_OVERLAP_A and _LONG_OVERLAP_B share ~85% of 3-gram content (Jaccard >> 0.65).
_LONG_OVERLAP_A = (
    "Please analyze the entire authentication module in this Python codebase. "
    "Look for security vulnerabilities including SQL injection XSS CSRF tokens "
    "session management password hashing and input validation. Report all findings "
    "with file names and line numbers. Focus on the auth directory."
)

_LONG_OVERLAP_B = (
    "Please analyze the entire authentication module in this Python codebase. "
    "Look for security vulnerabilities including SQL injection XSS CSRF tokens "
    "session management password hashing and input validation. Report all findings "
    "with file names and line numbers. Focus on the login forms."
)

# _LONG_DISTINCT_A and _LONG_DISTINCT_B have near-zero 3-gram overlap (Jaccard < 0.10).
_LONG_DISTINCT_A = (
    "Please explore the database layer of this codebase. Examine ORM models "
    "migration files query patterns connection pooling transaction handling "
    "schema relationships indexes and any N+1 query problems you can find."
)

_LONG_DISTINCT_B = (
    "Please implement a new REST API endpoint for user registration. The endpoint "
    "should validate email format hash passwords using bcrypt store results in the "
    "users table send a confirmation email and return a JWT token on success."
)

# Short prompts (< 50 words) for the threshold guard tests.
_SHORT_SIMILAR_A = "Analyze the authentication module for security issues."
_SHORT_SIMILAR_B = "Analyze the authentication module for security vulnerabilities."

# Retry test prompts — both ≥ 30 words, Jaccard ≥ 0.50.
_RETRY_ORIGINAL = (
    "Read the failing test file tests/test_auth.py and diagnose why the "
    "test_login_redirect test is failing. Check the session management code "
    "in auth/session.py and report what needs to be fixed."
)
_RETRY_SIMILAR = (
    "Read the failing test file tests/test_auth.py and understand why the "
    "test_login_redirect test is failing. Review the session management code "
    "in auth/session.py and report what needs to be fixed."
)
_RETRY_DIFFERENT = (
    "Implement the new user dashboard feature as described in the specification "
    "document. Create the frontend components backend API and database schema "
    "following the existing patterns in the codebase."
)
```

- [ ] **Step 2: Write classifier tests (add to test_fanout_classifier.py)**

Append to `tests/test_fanout_classifier.py`:

```python
# ---------------------------------------------------------------------------
# Signal A — Overlapping prompts
# ---------------------------------------------------------------------------

def test_no_agents_no_findings():
    from cctx.diagnostician.patterns.fan_out import classify
    trace = _trace([_turn(1, "user", text="hello"), _turn(2, "assistant", text="hi")])
    assert classify(trace) == []


def test_single_agent_no_findings():
    from cctx.diagnostician.patterns.fan_out import classify
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": _LONG_OVERLAP_A}, "child-1")]),
    ])
    assert classify(trace) == []


def test_overlapping_prompts_fires():
    from cctx.diagnostician.patterns.fan_out import classify
    from cctx.models import FindingKind
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": _LONG_OVERLAP_A}, "child-1")]),
        _turn(2, "assistant", tool_uses=[_tu("Agent", "tu2", {"prompt": _LONG_OVERLAP_B}, "child-2")]),
    ])
    findings = classify(trace)
    assert len(findings) == 1
    assert findings[0].kind is FindingKind.FANOUT_WASTE
    assert findings[0].evidence["signal"] == "overlap"
    assert findings[0].evidence["jaccard"] >= 0.65
    assert "child-1" in findings[0].evidence["overlap_pair"]
    assert "child-2" in findings[0].evidence["overlap_pair"]


def test_non_overlapping_prompts_clean():
    from cctx.diagnostician.patterns.fan_out import classify
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": _LONG_DISTINCT_A}, "child-1")]),
        _turn(2, "assistant", tool_uses=[_tu("Agent", "tu2", {"prompt": _LONG_DISTINCT_B}, "child-2")]),
    ])
    assert classify(trace) == []


def test_short_prompts_below_overlap_threshold_clean():
    """Prompts under 50 words must not be compared even if textually similar."""
    from cctx.diagnostician.patterns.fan_out import classify
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": _SHORT_SIMILAR_A}, "child-1")]),
        _turn(2, "assistant", tool_uses=[_tu("Agent", "tu2", {"prompt": _SHORT_SIMILAR_B}, "child-2")]),
    ])
    assert classify(trace) == []


# ---------------------------------------------------------------------------
# Signal B — Failed-retry
# ---------------------------------------------------------------------------

def test_failed_retry_fires():
    from cctx.diagnostician.patterns.fan_out import classify
    from cctx.models import FindingKind
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": _RETRY_ORIGINAL}, "child-1")]),
        _turn(2, "user", tool_results=[_tr("Agent", "tu1", "Error: timeout", is_error=True)]),
        _turn(3, "assistant", tool_uses=[_tu("Agent", "tu2", {"prompt": _RETRY_SIMILAR}, "child-2")]),
    ])
    findings = classify(trace)
    assert len(findings) == 1
    assert findings[0].kind is FindingKind.FANOUT_WASTE
    assert findings[0].evidence["signal"] == "retry"
    assert findings[0].evidence["jaccard"] >= 0.50
    assert findings[0].evidence.get("failed_session_id") == "child-1"


def test_failed_no_retry_clean():
    """is_error=True followed by a DIFFERENT Agent prompt → no finding."""
    from cctx.diagnostician.patterns.fan_out import classify
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": _RETRY_ORIGINAL}, "child-1")]),
        _turn(2, "user", tool_results=[_tr("Agent", "tu1", "Error", is_error=True)]),
        _turn(3, "assistant", tool_uses=[_tu("Agent", "tu2", {"prompt": _RETRY_DIFFERENT}, "child-2")]),
    ])
    assert classify(trace) == []


def test_failed_retry_short_prompts_clean():
    """Retry prompts under 30 words must not trigger even if similar."""
    from cctx.diagnostician.patterns.fan_out import classify
    trace = _trace([
        _turn(1, "assistant", tool_uses=[_tu("Agent", "tu1", {"prompt": "Fix the bug."}, "child-1")]),
        _turn(2, "user", tool_results=[_tr("Agent", "tu1", "Error", is_error=True)]),
        _turn(3, "assistant", tool_uses=[_tu("Agent", "tu2", {"prompt": "Fix the bug please."}, "child-2")]),
    ])
    assert classify(trace) == []
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/test_fanout_classifier.py -k "not kind_exists and not kind_label and not managed_heading" -v
```

Expected: all 8 signal tests fail with `ModuleNotFoundError: cctx.diagnostician.patterns.fan_out`

- [ ] **Step 4: Implement fan_out.py**

Create `cctx/diagnostician/patterns/fan_out.py`:

```python
"""Fan-out waste classifier.

classify(trace) -> list[Finding]

Signal A — OVERLAP: Two Agent calls with Jaccard ≥ 0.65 on word 3-grams,
    both prompts ≥ 50 words.
Signal B — RETRY: Agent ToolResult is_error=True followed by the next Agent
    call with Jaccard ≥ 0.50 on word 3-grams, both prompts ≥ 30 words.

Signal C (unused-result) is deferred — the 6-gram approach fires false
positives on paraphrased references and is not ship-ready.

cost_usd is set to None here; _patch_fanout_costs() in diagnostician/__init__.py
fills it in from SubagentAttribution data after run() collects attributions.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from cctx.models import Confidence, Finding, FindingKind, Severity

if TYPE_CHECKING:
    from cctx.models import SessionTrace, ToolUse

# ---------------------------------------------------------------------------
# Thresholds — documented here, not tuned at runtime
# ---------------------------------------------------------------------------

OVERLAP_JACCARD: float = 0.65   # minimum Jaccard on word 3-grams for overlap
OVERLAP_MIN_WORDS: int = 50     # both prompts must be this long

RETRY_JACCARD: float = 0.50     # minimum Jaccard for failed-retry detection
RETRY_MIN_WORDS: int = 30       # both prompts must be this long


# ---------------------------------------------------------------------------
# N-gram helpers
# ---------------------------------------------------------------------------

def _word_ngrams(text: str, n: int) -> set[tuple[str, ...]]:
    words = text.lower().split()
    if len(words) < n:
        return set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _get_prompt(tu: ToolUse) -> str:
    return tu.tool_input.get("prompt") or tu.tool_input.get("description") or ""


# ---------------------------------------------------------------------------
# Signal A — Overlapping subagent prompts
# ---------------------------------------------------------------------------

def _signal_overlap(agent_calls: list[tuple[int, ToolUse]]) -> list[Finding]:
    findings: list[Finding] = []
    for i in range(len(agent_calls)):
        turn_i, tu_i = agent_calls[i]
        p_i = _get_prompt(tu_i)
        words_i = p_i.split()
        if len(words_i) < OVERLAP_MIN_WORDS:
            continue
        ng_i = _word_ngrams(p_i, 3)
        for j in range(i + 1, len(agent_calls)):
            turn_j, tu_j = agent_calls[j]
            p_j = _get_prompt(tu_j)
            words_j = p_j.split()
            if len(words_j) < OVERLAP_MIN_WORDS:
                continue
            ng_j = _word_ngrams(p_j, 3)
            score = _jaccard(ng_i, ng_j)
            if score < OVERLAP_JACCARD:
                continue
            findings.append(Finding(
                kind=FindingKind.FANOUT_WASTE,
                severity=Severity.MEDIUM,
                confidence=Confidence.MEDIUM,
                first_turn=min(turn_i, turn_j),
                last_turn=max(turn_i, turn_j),
                evidence={
                    "signal": "overlap",
                    "overlap_pair": [tu_i.subagent_session_id, tu_j.subagent_session_id],
                    "jaccard": round(score, 3),
                    "prompt_a": p_i[:80],
                    "prompt_b": p_j[:80],
                    "subagent_session_ids": [],  # filled by _patch_fanout_costs
                },
                cost_usd=None,
                summary=f"Overlapping subagent prompts (Jaccard {score:.2f})",
            ))
    return findings


# ---------------------------------------------------------------------------
# Signal B — Failed subagent re-spawned with similar prompt
# ---------------------------------------------------------------------------

def _signal_retry(
    agent_calls: list[tuple[int, ToolUse]],
    result_map: dict[str, tuple[bool, str]],  # tool_use_id → (is_error, content)
) -> list[Finding]:
    findings: list[Finding] = []
    for k, (turn_k, tu_k) in enumerate(agent_calls):
        is_error, _content = result_map.get(tu_k.tool_use_id, (False, ""))
        if not is_error:
            continue
        # Find the immediate next Agent call (by list order, which is turn order)
        if k + 1 >= len(agent_calls):
            continue
        turn_next, tu_next = agent_calls[k + 1]
        p_failed = _get_prompt(tu_k)
        p_retry = _get_prompt(tu_next)
        if len(p_failed.split()) < RETRY_MIN_WORDS or len(p_retry.split()) < RETRY_MIN_WORDS:
            continue
        score = _jaccard(_word_ngrams(p_failed, 3), _word_ngrams(p_retry, 3))
        if score < RETRY_JACCARD:
            continue
        findings.append(Finding(
            kind=FindingKind.FANOUT_WASTE,
            severity=Severity.HIGH,
            confidence=Confidence.HIGH,
            first_turn=turn_k,
            last_turn=turn_next,
            evidence={
                "signal": "retry",
                "failed_session_id": tu_k.subagent_session_id,
                "jaccard": round(score, 3),
                "failed_prompt": p_failed[:80],
                "retry_prompt": p_retry[:80],
                "subagent_session_ids": [],  # filled by _patch_fanout_costs
            },
            cost_usd=None,
            summary=f"Failed subagent re-spawned with similar prompt (Jaccard {score:.2f})",
        ))
    return findings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _classify_impl(trace: SessionTrace) -> list[Finding]:
    # Collect Agent ToolUse in turn order
    agent_calls: list[tuple[int, ToolUse]] = []
    result_map: dict[str, tuple[bool, str]] = {}

    for turn in trace.turns:
        for tu in turn.tool_uses:
            if tu.tool_name == "Agent":
                agent_calls.append((turn.turn_number, tu))
        for tr in turn.tool_results:
            if tr.tool_name == "Agent":
                result_map[tr.tool_use_id] = (tr.is_error, tr.content)

    if len(agent_calls) < 2:
        return []

    findings: list[Finding] = [
        *_signal_overlap(agent_calls),
        *_signal_retry(agent_calls, result_map),
    ]
    return findings


def classify(trace: SessionTrace) -> list[Finding]:
    try:
        return _classify_impl(trace)
    except Exception:
        return []
```

- [ ] **Step 5: Run classifier tests**

```bash
uv run pytest tests/test_fanout_classifier.py -k "not kind_exists and not kind_label and not managed_heading" -v
```

Expected: all 8 signal tests PASS.

- [ ] **Step 6: Run the full test suite to check for regressions**

```bash
uv run pytest --tb=short -q
```

Expected: all tests pass (fan_out.py not yet imported by diagnostician, so no wiring yet).

- [ ] **Step 7: Commit**

```bash
git add cctx/diagnostician/patterns/fan_out.py tests/test_fanout_classifier.py
git commit -m "feat: fan_out classifier — Signal A (overlap) + Signal B (retry)"
```

---

## Task C: Wire classifier + cost patching into diagnostician

**Context:** `cctx/diagnostician/__init__.py` orchestrates all classifiers. Its `run()` function currently:
1. Calls all classifiers (lines 108–114)
2. Calls `_patch_costs()` for STALE_CONTEXT cost attribution (line 118)
3. Computes `total_cost` + `waste_cost` (lines 120–122)
4. Calls `_collect_attributions()` for subagent table (line 124)

The ordering must become: classify (including fan_out) → `_patch_costs` → `_collect_attributions` → `_patch_fanout_costs` → compute `waste_cost`. This ensures fan-out findings have costs when `waste_cost` is summed, and the sum is deduplicated so one subagent flagged by both signals isn't double-counted.

**Files:**
- Modify: `cctx/diagnostician/__init__.py`
- Modify: `tests/test_fanout_classifier.py` (add _patch_fanout_costs tests)

- [ ] **Step 1: Write failing tests for _patch_fanout_costs**

Append to `tests/test_fanout_classifier.py`:

```python
# ---------------------------------------------------------------------------
# _patch_fanout_costs — unit tests
# ---------------------------------------------------------------------------

def test_patch_fanout_costs_overlap_picks_cheaper():
    """overlap finding: cost_usd = cheaper subagent's cost; subagent_session_ids updated."""
    import dataclasses
    from cctx.diagnostician import _patch_fanout_costs
    from cctx.models import (
        Confidence, Finding, FindingKind, Severity, SubagentAttribution,
    )
    finding = Finding(
        kind=FindingKind.FANOUT_WASTE,
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=1, last_turn=2,
        evidence={
            "signal": "overlap",
            "overlap_pair": ["child-1", "child-2"],
            "jaccard": 0.72,
            "prompt_a": "x", "prompt_b": "y",
            "subagent_session_ids": [],
        },
        cost_usd=None,
        summary="test",
    )
    attrs = [
        SubagentAttribution("child-1", "label1", 0.05, 1, "claude-sonnet-4-6"),
        SubagentAttribution("child-2", "label2", 0.02, 1, "claude-sonnet-4-6"),
    ]
    patched = _patch_fanout_costs([finding], attrs)
    assert len(patched) == 1
    assert patched[0].cost_usd == 0.02           # cheaper one
    assert patched[0].evidence["subagent_session_ids"] == ["child-2"]


def test_patch_fanout_costs_retry_sets_failed_cost():
    """retry finding: cost_usd = the failed subagent's cost."""
    from cctx.diagnostician import _patch_fanout_costs
    from cctx.models import (
        Confidence, Finding, FindingKind, Severity, SubagentAttribution,
    )
    finding = Finding(
        kind=FindingKind.FANOUT_WASTE,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=1, last_turn=3,
        evidence={
            "signal": "retry",
            "failed_session_id": "child-1",
            "jaccard": 0.55,
            "failed_prompt": "x", "retry_prompt": "y",
            "subagent_session_ids": [],
        },
        cost_usd=None,
        summary="test",
    )
    attrs = [
        SubagentAttribution("child-1", "label1", 0.08, 1, "claude-sonnet-4-6"),
    ]
    patched = _patch_fanout_costs([finding], attrs)
    assert patched[0].cost_usd == 0.08
    assert patched[0].evidence["subagent_session_ids"] == ["child-1"]
```

- [ ] **Step 2: Run those tests to verify they fail**

```bash
uv run pytest tests/test_fanout_classifier.py::test_patch_fanout_costs_overlap_picks_cheaper tests/test_fanout_classifier.py::test_patch_fanout_costs_retry_sets_failed_cost -v
```

Expected: FAIL with `ImportError: cannot import name '_patch_fanout_costs'`

- [ ] **Step 3: Add fan_out import and _patch_fanout_costs to diagnostician/__init__.py**

In `cctx/diagnostician/__init__.py`, add `fan_out` to the existing imports block:
```python
from cctx.diagnostician.patterns import (
    dead_end,
    fan_out,
    retry_loop,
    scope_creep,
    stale_context,
    tool_thrash,
)
```

Add `_patch_fanout_costs` after `_patch_costs` (around line 41):
```python
def _patch_fanout_costs(
    findings: list[Finding],
    subagent_costs: list[SubagentAttribution],
) -> list[Finding]:
    """Fill cost_usd on FANOUT_WASTE findings from subagent attribution data.

    For overlap findings: picks the cheaper of the two subagents as waste.
    For retry findings: attributes the full cost of the failed subagent.
    Populates evidence['subagent_session_ids'] so run()'s dedup pass works.
    """
    cost_map = {a.session_id: a.total_cost_usd for a in subagent_costs}
    result: list[Finding] = []
    for f in findings:
        if f.kind is FindingKind.FANOUT_WASTE:
            signal = f.evidence.get("signal")
            if signal == "overlap":
                pair = [sid for sid in f.evidence.get("overlap_pair", []) if sid is not None]
                if pair:
                    cheaper_cost, cheaper_sid = min(
                        (cost_map.get(sid, 0.0), sid) for sid in pair
                    )
                    f = dataclasses.replace(
                        f,
                        cost_usd=round(cheaper_cost, 4),
                        evidence={**f.evidence, "subagent_session_ids": [cheaper_sid]},
                    )
            elif signal == "retry":
                failed_sid = f.evidence.get("failed_session_id")
                if failed_sid is not None:
                    cost = cost_map.get(failed_sid, 0.0)
                    f = dataclasses.replace(
                        f,
                        cost_usd=round(cost, 4),
                        evidence={**f.evidence, "subagent_session_ids": [failed_sid]},
                    )
        result.append(f)
    return result
```

- [ ] **Step 4: Update run() to wire fan_out and fix sequencing**

Replace the `run()` function body in `cctx/diagnostician/__init__.py`:

```python
def run(trace: SessionTrace) -> Diagnosis:
    """Diagnose a single SessionTrace. Returns Diagnosis with patches=[]."""
    findings: list[Finding] = [
        *retry_loop.classify(trace),
        *scope_creep.classify(trace),
        *stale_context.classify(trace),
        *tool_thrash.classify(trace),
        *dead_end.classify(trace),
        *fan_out.classify(trace),
    ]
    findings.sort(key=lambda f: f.first_turn)

    inflection_turn = inflection.detect(findings)
    findings = _patch_costs(findings, trace.primary_model)

    # Fan-out cost patching requires attributions first.
    subagent_costs = _collect_attributions(trace)
    findings = _patch_fanout_costs(findings, subagent_costs)

    total_cost = round(_compute_inclusive_cost(trace), 4)

    # Deduplicate fan-out waste: a subagent flagged by both overlap AND retry
    # must not be double-counted. Collect unique wasted session IDs, sum once.
    cost_map = {a.session_id: a.total_cost_usd for a in subagent_costs}
    wasted_sids: set[str] = set()
    for f in findings:
        if f.kind is FindingKind.FANOUT_WASTE:
            wasted_sids.update(f.evidence.get("subagent_session_ids", []))
    fanout_waste = sum(cost_map.get(sid, 0.0) for sid in wasted_sids)
    other_waste = sum(
        f.cost_usd for f in findings
        if f.cost_usd is not None and f.kind is not FindingKind.FANOUT_WASTE
    )
    waste_cost = min(other_waste + fanout_waste, total_cost)

    return Diagnosis(
        session_id=trace.session_id,
        findings=findings,
        inflection_turn=inflection_turn,
        patches=[],
        total_cost_usd=total_cost,
        waste_cost_usd=round(waste_cost, 4),
        analysed_at=datetime.now(UTC),
        subagent_costs=subagent_costs,
    )
```

- [ ] **Step 5: Run the two _patch_fanout_costs tests**

```bash
uv run pytest tests/test_fanout_classifier.py::test_patch_fanout_costs_overlap_picks_cheaper tests/test_fanout_classifier.py::test_patch_fanout_costs_retry_sets_failed_cost -v
```

Expected: both PASS.

- [ ] **Step 6: Run the full test suite**

```bash
uv run pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add cctx/diagnostician/__init__.py
git commit -m "feat: wire fan_out classifier into diagnostician, add _patch_fanout_costs"
```

---

## Task D: Recommender template

**Context:** `cctx/recommender/claude_md.py` holds patch templates keyed by `FindingKind` in `_TEMPLATES`. Each entry is `(description, diff_body, target_file)` where `diff_body` is a unified-diff string with `+` prefix on every line. The `test_registry_matches_templates` test in `tests/test_harvest_emit.py` asserts that every `MANAGED_HEADINGS[k]` equals the first `+##` line of `_TEMPLATES[k]`'s diff — this is the correctness gate.

**Files:**
- Modify: `cctx/recommender/claude_md.py`

- [ ] **Step 1: Verify test_registry_matches_templates currently passes (prerequisite check)**

```bash
uv run pytest tests/test_harvest_emit.py::test_registry_matches_templates -v
```

Expected: FAIL — `FANOUT_WASTE missing from _TEMPLATES`. (Task A added FANOUT_WASTE to MANAGED_HEADINGS but not to _TEMPLATES yet.)

- [ ] **Step 2: Add _FANOUT_WASTE_DIFF and _TEMPLATES entry**

In `cctx/recommender/claude_md.py`, after `_DEAD_END_DIFF` (line ~58), add:

```python
_FANOUT_WASTE_DIFF = """\
+## Fan-out discipline
+
+Before spawning multiple subagents in parallel, state what each one will return
+and verify the tasks don't overlap. After each subagent completes, confirm its
+result is actually consumed by the parent before spawning retries. Retry only
+after changing something meaningful about the task — identical re-spawns waste
+the full subagent cost with no new information."""
```

Update `_TEMPLATES` to include the new kind:

```python
_TEMPLATES: dict[FindingKind, tuple[str, str, str]] = {
    # kind → (description, diff_body, target_file)
    FindingKind.RETRY_LOOP:    ("Add retry discipline rule", _RETRY_LOOP_DIFF, "CLAUDE.md"),
    FindingKind.SCOPE_CREEP:   ("Add scope discipline rule", _SCOPE_CREEP_DIFF, "CLAUDE.md"),
    FindingKind.STALE_CONTEXT: ("Add context hygiene rule", _STALE_CONTEXT_DIFF, "CLAUDE.md"),
    FindingKind.TOOL_THRASH:   ("Add tool-call discipline rule", _TOOL_THRASH_DIFF, "CLAUDE.md"),
    FindingKind.DEAD_END:      ("Add exploration discipline rule", _DEAD_END_DIFF, "CLAUDE.md"),
    FindingKind.FANOUT_WASTE:  ("Add fan-out discipline rule", _FANOUT_WASTE_DIFF, "CLAUDE.md"),
}
```

- [ ] **Step 3: Run test_registry_matches_templates**

```bash
uv run pytest tests/test_harvest_emit.py::test_registry_matches_templates -v
```

Expected: PASS.

- [ ] **Step 4: Run the full test suite**

```bash
uv run pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add cctx/recommender/claude_md.py
git commit -m "feat: add _FANOUT_WASTE_DIFF template to recommender"
```

---

## Self-Review

### 1. Spec coverage

| Spec requirement | Task |
|---|---|
| `FANOUT_OVERLAP`, `FANOUT_RETRY`, `FANOUT_UNUSED` FindingKinds | Task A — unified as `FANOUT_WASTE`; spec allows this; Signal C deferred per architecture note |
| `KIND_LABEL` entries | Task A |
| `MANAGED_HEADINGS` entry `"## Fan-out discipline"` | Task A |
| New classifier `cctx/diagnostician/patterns/fan_out.py` | Task B |
| Signal A: Jaccard ≥ 0.65, word 3-grams, both ≥ 50 words | Task B |
| Signal B: failed Agent + similar re-spawn, Jaccard ≥ 0.50, both ≥ 30 words | Task B |
| `diagnostician/__init__.py` import + call | Task C |
| Cost attribution via `_patch_fanout_costs` | Task C |
| `run()` sequencing fixed (waste_cost computed after patching) | Task C |
| Dedup: same subagent flagged twice doesn't double-count | Task C |
| `_FANOUT_WASTE_DIFF` template + `_TEMPLATES` entry | Task D |
| `test_registry_matches_templates` passes | Task D (validates) |
| `test_managed_headings_cover_the_five_diagnostic_kinds` updated | Task A |

All spec requirements covered. Signal C deferred by design.

### 2. Placeholder scan

No TBDs, no "similar to Task N" references, all code blocks are complete. ✓

### 3. Type consistency

- `_patch_fanout_costs(findings: list[Finding], subagent_costs: list[SubagentAttribution]) -> list[Finding]` — consistent across Tasks C's definition and test.
- `_tu`, `_tr`, `_turn`, `_trace` helpers defined once in Task B and used in Tasks B+C tests (test file is one file). ✓
- `FindingKind.FANOUT_WASTE` added in Task A; used in Tasks B, C, D. ✓
- `evidence["subagent_session_ids"]` key: set to `[]` in fan_out.py (Task B), filled by `_patch_fanout_costs` (Task C), read in `run()`'s dedup loop (Task C). ✓
