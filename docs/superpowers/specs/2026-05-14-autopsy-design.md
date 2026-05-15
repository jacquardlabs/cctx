# Autopsy v0 — design

**Status:** approved through brainstorming, awaiting implementation
**Date:** 2026-05-14
**Modules:** `cctx/diagnostician/`, `cctx/recommender/`, `cctx/models.py` (M2 additions)
**Pipeline position:** `SessionTrace → [Diagnostician] → Diagnosis → [Recommender] → Diagnosis (with Patches) → Renderers`

## 1. Scope

The autopsy pipeline is the core of cctx's value proposition: given a `SessionTrace` produced by the parser, diagnose *what went wrong*, *when it started*, *what it cost*, and *what to add to CLAUDE.md so it doesn't happen again*.

This document covers the single-session autopsy (`cctx autopsy <session>`) and the cross-session aggregation mode (`cctx autopsy <project> --since <window>`). It does not cover the terminal renderer (`cctx/renderers/terminal.py`), the HTML report renderer, or the trace TUI — those are designed separately as part of the renderer layer.

**What the autopsy pipeline produces:**
- A `Diagnosis` per session: a list of `Finding` objects, an inflection turn, and attributed waste cost.
- A list of `Patch` objects: copy-pasteable unified diffs targeting the user's `CLAUDE.md`.
- (Cross-session) An `AggregateReport`: finding frequencies, total waste, and cross-session–enhanced patches.

**v0 scope boundaries:**
- Three pattern classifiers: retry loop, scope creep, stale context.
- Binary waste detection only: "loaded but never used" / "identical call failed twice" / "in context long past last reference."
- Deterministic classifiers only — no LLM calls, no probabilistic models.
- Single-session diagnosis is the primary path. Cross-session (`--since`) runs per-session diagnosis in a loop and aggregates.
- Main session trace only: subagent internals are not separately diagnosed in v0 (main trace captures most subagent signal via tool calls and tool results; see §8).

## 2. Design decisions

These came from the brainstorming session for this spec. They are recorded here so implementors don't re-litigate them.

### 2.1 Inflection turn definition

`inflection_turn = min(f.first_turn for f in findings)`, or `None` if no findings. This is computed post-classification by `inflection.detect()` (§7). Each classifier sets `first_turn` to the earliest turn where the problem is clearly established (not where the symptom first appeared in a speculative sense — see §6 for per-classifier definitions).

### 2.2 Retry-loop similarity key

Key derivation is tool-aware, not content-hash:

| Tool | Similarity key |
|------|---------------|
| `Bash` | `tool_use.input["command"]` (stripped) |
| `Edit` / `Read` / `Write` | `tool_use.input["file_path"]` |
| `Grep` / `Glob` | `tool_use.input["pattern"]` |
| anything else | `json.dumps(tool_use.input, sort_keys=True)` |

A retry loop requires: same `(tool_name, key)` called at least twice, both calls produced error results, no successful call to the same `(tool_name, key)` between them.

### 2.3 Scope-creep detection: conservative v0

v0 fires only on explicit re-scoping phrases in assistant turn text. No structural heuristics (task-count, turn-count, tool-diversity). Phrase matching only.

### 2.4 Stale-context thresholds

`T_size = 2_000` tokens (minimum size to be a stale-context candidate), `N_stale = 5` turns (turns after last reference before "stale"), reference detection via 3-gram overlap. Compaction-aware: token-turn accumulation resets to zero at compaction events. One Finding per session (all stale items bundled in `evidence`).

### 2.5 Confidence assignment

Classifier-driven:
- `retry_loop`: always `HIGH` (duplicate failing call = unambiguous evidence)
- `scope_creep`: always `MEDIUM` (phrase match = indicative, not certain)
- `stale_context`: `MEDIUM` if total_token_turns ≤ 500K; `HIGH` if > 500K

### 2.6 Cost attribution

Only `stale_context` findings carry `cost_usd` in v0. `retry_loop` and `scope_creep` cost None (no clean counterfactual exists). Cost is computed by the orchestrator (§8), not by individual classifiers, using a centralized model-price table keyed on `session.primary_model`.

### 2.7 Patch format

Append-style unified diffs in v0. The `unified_diff` field carries `+`-prefixed lines showing what to add to CLAUDE.md. The renderer presents these as fenced diff blocks. In v1, if we read the user's current CLAUDE.md, we can generate contextual diffs at an exact insertion point; for now, honest append is correct. Patches are deterministic template strings — no LLM calls.

## 3. New dataclasses (added to `cctx/models.py`)

All new types extend `models.py`. Existing dataclasses (`Turn`, `ToolUse`, `ToolResult`, `Usage`, `Attachment`, `SessionTrace`, etc.) are unchanged.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class FindingKind(str, Enum):
    RETRY_LOOP    = "retry_loop"
    SCOPE_CREEP   = "scope_creep"
    STALE_CONTEXT = "stale_context"


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
    first_turn: int                 # inflection candidate; always set
    last_turn:  int | None          # span end; None for single-turn findings
    evidence:   dict[str, Any]      # classifier-specific payload (see §6)
    cost_usd:   float | None        # attributed waste; None if uncomputable
    summary:    str                 # one-line for terminal badge


@dataclass
class Patch:
    target_file:      str           # "CLAUDE.md" or ".claude/rules/<slug>.md"
    description:      str           # one-line: what this adds/changes
    unified_diff:     str           # paste-ready diff (append-style in v0)
    finding_kind:     FindingKind   # which finding generated this
    evidence_summary: str           # abbreviated backing evidence for display


@dataclass
class Diagnosis:
    session_id:      str
    findings:        list[Finding]  # sorted by first_turn ascending
    inflection_turn: int | None     # min(f.first_turn for f in findings), or None
    patches:         list[Patch]    # populated by Recommender; empty until then
    total_cost_usd:  float          # session total from SessionTrace usage
    waste_cost_usd:  float          # sum(f.cost_usd for f in findings if f.cost_usd)
    analysed_at:     datetime


@dataclass
class KindEvidence:
    kind:              FindingKind
    session_count:     int
    total_waste_usd:   float
    example_summaries: list[str]    # up to 3 abbreviated evidence strings


@dataclass
class AggregateReport:
    window:                 timedelta
    sessions_analysed:      int
    sessions_with_findings: int
    total_cost_usd:         float
    waste_cost_usd:         float
    by_kind:                dict[FindingKind, KindEvidence]
    patches:                list[Patch]
```

### 3.1 Why `severity` and `confidence` are separate

`severity` = impact (badge color in the terminal renderer). `confidence` = certainty (footnote). A cheap retry loop is HIGH confidence but LOW severity. A large stale-context blob is HIGH severity. Conflating them would cause the renderer to over-alert on certain-but-minor findings.

### 3.2 Why `waste_cost_usd` is stored rather than derived

So JSONL export round-trips cleanly and renderers don't recompute it. The value is the sum of `f.cost_usd` values known at Diagnosis construction time; if cost_usd is later patched by the recommender (it isn't in v0 but could be in v1), the stored value needs an update anyway.

### 3.3 Why `patches = []` on the Diagnosis returned by the orchestrator

The Recommender is a separate module with separate tests. The orchestrator returns `Diagnosis(patches=[])`. The CLI calls `recommender.generate(diagnosis)` to get the patch-populated Diagnosis. `dataclasses.replace(diagnosis, patches=patches)` keeps the pattern immutable.

### 3.4 `KindEvidence` lives in `models.py`

It's a data container, not analysis logic. Both `diagnostician/aggregate.py` and `recommender/evidence.py` import it from `models.py`, avoiding any cross-boundary import between diagnostician and recommender.

## 4. Classifier contracts

```python
# Shared signature for all three classifiers.
def classify(trace: SessionTrace) -> list[Finding]:
    ...
```

All classifiers are pure functions: no side effects, no I/O. Return `[]` on empty or degenerate traces (zero turns, no tool calls). Never raise — swallow internal errors and return `[]`.

**One Finding per classifier per session in v0.** `first_turn` = earliest instance; all instances are bundled in `evidence`. Cross-session aggregation unpacks evidence later.

## 5. Retry-loop classifier (`cctx/diagnostician/patterns/retry_loop.py`)

Detects repeated identical-failing tool calls with no intervening successful fix.

**Algorithm:**
1. Walk assistant turns; collect `(tool_name, key, turn_number, result_is_error)` per tool call, using the key derivation in §2.2.
2. Group by `(tool_name, key)`.
3. For each group with ≥ 2 calls: check that:
   - Both calls produced error results, AND
   - No successful call to the same `(tool_name, key)` occurred between them.
4. A tool result is an error if `tool_result.is_error` is truthy, OR if content starts with `"Error:"` / `"error:"` / `"FAILED"`.

**Evidence shape:**
```python
{
    "occurrences": [
        {"turn": int, "key": str, "call": str, "error": str},
        ...
    ],
    "loop_length": int,  # number of failing calls
}
```

**`first_turn`:** turn of the *second* failing call (the loop is established then, not on the first call).

**Severity:**
- `HIGH` if `loop_length >= 4`
- `MEDIUM` if `loop_length == 2` or `3`

**Confidence:** always `HIGH`.

**`cost_usd`:** `None` in v0.

**`Finding.summary` for retry_loop:**
```
"Edit(src/foo.py) failed 3× between turns 12–16"
```

## 6. Scope-creep classifier (`cctx/diagnostician/patterns/scope_creep.py`)

Detects explicit re-scoping phrases in assistant turn text.

**Phrase list (case-insensitive, checked against `turn.text.lower()`):**
```python
SCOPE_PHRASES = [
    "i'll also fix",
    "while i'm here",
    "let me also",
    "i also noticed",
    "while we're at it",
    "i should also",
    "additionally, i'll",
    "i noticed that",
]
```

`"i noticed that"` is only counted when followed within 20 characters by an action verb (fix, add, update, change, remove, clean, refactor) to avoid false positives on factual observations.

**Algorithm:**
1. Walk assistant turns with non-empty `turn.text`.
2. Check `turn.text.lower()` for any phrase in `SCOPE_PHRASES`.
3. On match, record `{"turn": int, "phrase": str, "snippet": str}` where `snippet` is the 80-char window around the match.
4. Emit one Finding; `first_turn` = earliest matching turn.

**Evidence shape:**
```python
{
    "phrases": [
        {"turn": int, "phrase": str, "snippet": str},
        ...
    ]
}
```

**`first_turn`:** turn of the first phrase match.

**Severity:** `MEDIUM` always (phrase match = plausible signal, not certain).

**Confidence:** always `MEDIUM`.

**`cost_usd`:** `None` in v0.

**`Finding.summary` for scope_creep:**
```
"'while I'm here' at turn 23 (2 scope expansions total)"
```

## 7. Stale-context classifier (`cctx/diagnostician/patterns/stale_context.py`)

Detects large tool results that remained in context well past their last reference, accumulating token-turn waste.

**Thresholds:** `T_size = 2_000` tokens, `N_stale = 5` turns, 3-gram reference detection.

**Algorithm:**
1. Walk turns; identify all inline tool results with estimated `content_tokens > T_size`. Content tokens estimated as `len(content.split()) * 1.3` in offline mode; exact from the tokenizer when pre-populated on `ToolResult.token_count > 0`.
2. For each candidate, find `last_referenced_turn`: the last turn in which a 3-gram from the tool result's content appears in any subsequent assistant turn's text.
3. `turns_stale = (last_turn_in_session) - last_referenced_turn`.
4. **Compaction reset:** if a compaction `system` turn occurs between `first_seen_turn` and `last_turn_in_session`, reset: the compaction purged the stale content. The item is excluded from the Finding.
5. When `turns_stale > N_stale`, the item is stale. Compute `token_turns = content_tokens × turns_stale`.
6. Accumulate across all stale items; emit one Finding.

**Evidence shape:**
```python
{
    "stale_items": [
        {
            "tool_name": str,
            "content_tokens": int,
            "first_seen_turn": int,
            "last_referenced_turn": int,
            "turns_stale": int,
            "token_turns": int,
        },
        ...
    ],
    "total_token_turns": int,
}
```

**`first_turn`:** `last_referenced_turn + N_stale` of the first item to go stale. (Loading a large result isn't the problem; failing to use it is. The inflection is when waste starts accumulating.)

**Confidence and severity (scale together):**
- `total_token_turns ≤ 500K` → `MEDIUM` / `MEDIUM`
- `total_token_turns > 500K` → `HIGH` / `HIGH`

**`cost_usd`:** computed by the orchestrator (§8), not by this classifier.

**`Finding.summary` for stale_context:**
```
"22K-token Bash result stale for 14 turns (~308K token-turns, ~$0.92)"
```

## 8. Orchestrator (`cctx/diagnostician/__init__.py`)

Public entry point: `run(trace: SessionTrace) -> Diagnosis`.

```python
def run(trace: SessionTrace) -> Diagnosis:
    # 1. Run classifiers (order-independent)
    findings: list[Finding] = [
        *retry_loop.classify(trace),
        *scope_creep.classify(trace),
        *stale_context.classify(trace),
    ]

    # 2. Sort ascending by first_turn
    findings.sort(key=lambda f: f.first_turn)

    # 3. Detect inflection
    inflection_turn = inflection.detect(findings)

    # 4. Patch cost_usd onto stale_context findings
    findings = _patch_costs(findings, trace)

    # 5. Compute session totals
    total_cost_usd = _compute_total_cost(trace)
    waste_cost_usd = sum(f.cost_usd for f in findings if f.cost_usd is not None)

    return Diagnosis(
        session_id      = trace.session_id,
        findings        = findings,
        inflection_turn = inflection_turn,
        patches         = [],
        total_cost_usd  = total_cost_usd,
        waste_cost_usd  = waste_cost_usd,
        analysed_at     = datetime.now(UTC),
    )
```

**Cost attribution (`_patch_costs`):**

```python
_INPUT_PRICE_PER_MTOK: dict[str, float] = {
    "claude-opus-4":    15.0,
    "claude-sonnet-4":   3.0,
    "claude-haiku-4":    0.8,
}

def _price_per_tok(model: str | None) -> float:
    for prefix, mtok in _INPUT_PRICE_PER_MTOK.items():
        if model and model.startswith(prefix):
            return mtok / 1_000_000
    return 3.0 / 1_000_000  # default: Sonnet rate

def _patch_costs(findings: list[Finding], trace: SessionTrace) -> list[Finding]:
    price = _price_per_tok(trace.primary_model)
    return [
        dataclasses.replace(
            f,
            cost_usd=round(f.evidence.get("total_token_turns", 0) * price, 4)
        ) if f.kind is FindingKind.STALE_CONTEXT else f
        for f in findings
    ]
```

**Session total (`_compute_total_cost`):** sum of `turn.usage.input_tokens × price_per_tok(trace.primary_model)` across all turns with non-None usage. Output tokens are not separately priced in v0 (honest approximation — output price varies per model and is a smaller fraction of typical session cost).

**Cost approximation caveat:** v0 uses uncached input price across all turns. Prompt-cache hits in Claude's billing are ~10% of full input price; this means `total_cost_usd` and `waste_cost_usd` both overstate actual billing when the cache hit rate is high (commonly 60–80% for long sessions). The overstatement is intentional and consistent — the goal is a directionally-correct waste signal, not a receipt. The brief's example numbers use the same approximation.

**Subagent handling (v0):** main session trace only. The main trace captures most subagent signal:
- Large subagent outputs that sit in the main context for many turns are caught by `stale_context` on the main trace.
- Retry loops that keep spawning a failing subagent with identical inputs are caught by `retry_loop` (same tool key, repeated errors in the main trace).

What is missed: patterns entirely self-contained within a subagent's own session. v1 extension: recurse `run()` on each `trace.subagents`, collect sub-`Diagnosis` objects, surface them as a separate section. `Diagnosis` will need `sub_diagnoses: list[Diagnosis] = field(default_factory=list)`.

**Invariants:**
- `findings` is sorted ascending by `first_turn` before `inflection.detect()` and before `Diagnosis` construction.
- `patches = []` at orchestrator exit. The Recommender is the only writer of patches.
- The orchestrator never imports `click`, `rich`, or `anthropic`.

## 9. Inflection detection (`cctx/diagnostician/inflection.py`)

```python
def detect(findings: list[Finding]) -> int | None:
    """Return the earliest first_turn across all findings, or None."""
    if not findings:
        return None
    return min(f.first_turn for f in findings)
```

**Why a named module for one line:** the concept of "session inflection" is the product's central claim. Naming it creates a stable extension point for v1, where inflection might be detected from turn-level signals that precede any classifier finding (rising error rate, assistant apology language, step-change in token usage). Embedding this logic in the orchestrator would require a grep-and-refactor later.

**Renderer retrieval of the triggering finding:**
```python
trigger = next((f for f in diagnosis.findings if f.first_turn == diagnosis.inflection_turn), None)
```

The `Diagnosis` stores only `inflection_turn: int | None`. The renderer resolves the triggering finding from the findings list.

## 10. Recommender (`cctx/recommender/claude_md.py`)

Takes a `Diagnosis` with `patches=[]` and returns a new `Diagnosis` with patches populated.

```python
def generate(diagnosis: Diagnosis) -> Diagnosis:
    patches = [_make_patch(f) for f in diagnosis.findings]
    return dataclasses.replace(diagnosis, patches=patches)
```

**Patch templates (v0 — deterministic, append-style):**

`retry_loop`:
```diff
+## Retry discipline
+
+If the same command or file operation fails twice with the same error, stop and
+diagnose before retrying. Read the relevant file, check the full error message,
+confirm paths exist. Try a meaningfully different approach — never repeat the
+exact failing call a third time.
```

`scope_creep`:
```diff
+## Scope discipline
+
+Finish the stated task before picking up anything else. If you notice an adjacent
+issue while working, note it as a TODO comment but do not fix it unless explicitly
+asked. One task at a time.
```

`stale_context`:
```diff
+## Context hygiene
+
+Large tool outputs (grep results, file reads over ~2K tokens) go stale quickly.
+After a result has served its purpose, do not carry it through 5+ additional turns
+without re-referencing it. Prefer re-running the tool over dragging stale context
+forward — the compaction system handles removal.
```

**Evidence summary format per finding kind:**

| Kind | Format |
|---|---|
| `retry_loop` | `"Edit(src/foo.py) failed 3× between turns 12–16"` |
| `scope_creep` | `"'while I'm here' at turn 23"` |
| `stale_context` | `"22K-token Bash result stale 14 turns (~308K token-turns, ~$0.92)"` |

**Cross-session entry point:**

```python
def generate_from_evidence(
    evidence: dict[FindingKind, KindEvidence],
) -> list[Patch]:
    """Like generate(), but for the --since aggregation path.

    Produces one Patch per FindingKind present in evidence. Each patch body
    is the same template as the single-session version, with an Evidence line
    appended when session_count >= 2:

        Evidence: appeared in 8 of 12 sessions in the past 7 days (~$4.30 wasted).

    When session_count == 1, produces an identical patch to the single-session path.
    """
```

**Layering invariant:** the Recommender never calls back into the Diagnostician. It never reads the session log. It never calls `anthropic`. Templates are hardcoded strings in v0.

## 11. Evidence accumulation (`cctx/recommender/evidence.py`)

```python
def accumulate(diagnoses: list[Diagnosis]) -> dict[FindingKind, KindEvidence]:
    result: dict[FindingKind, KindEvidence] = {}
    for d in diagnoses:
        for f in d.findings:
            ev = result.setdefault(
                f.kind, KindEvidence(f.kind, 0, 0.0, [])
            )
            ev.session_count   += 1
            ev.total_waste_usd += f.cost_usd or 0.0
            if len(ev.example_summaries) < 3:
                ev.example_summaries.append(_summarize(f))
    return result
```

`_summarize(f)` produces the same one-liner as `Patch.evidence_summary` (shared helper).

The cross-session patch template adds an evidence line when `session_count >= 2`:
```diff
+Evidence: appeared in 8 of 12 sessions in the past 7 days (~$4.30 wasted).
```

## 12. Cross-session aggregator (`cctx/diagnostician/aggregate.py`)

Public entry point for `--since` mode: `run(project_dir, window) -> list[Diagnosis]`.

```python
def run(project_dir: Path, window: timedelta) -> list[Diagnosis]:
    cutoff = datetime.now(UTC) - window
    paths  = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    result = []
    for path in paths:
        if datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff:
            continue
        trace     = parse_session(path)
        diagnosis = diagnostician.run(trace)
        result.append(diagnosis)
    return result
```

Session discovery: glob `*.jsonl` in the project directory (the `~/.claude/projects/<encoded-path>/` directory), filter by mtime ≥ cutoff. No cache, no database — each run re-parses. Acceptable for ≤ 30 sessions over 7 days; v1 can add a pickle cache if re-parsing is too slow on large corpora.

**CLI orchestration for `--since`:** the CLI calls across the diagnostician/recommender boundary; the modules themselves do not:

```python
# cli.py
diagnoses = aggregate.run(project_dir, window=timedelta(days=7))
evidence  = evidence_mod.accumulate(diagnoses)
patches   = claude_md.generate_from_evidence(evidence)
report    = AggregateReport(
    window=window,
    sessions_analysed=len(diagnoses),
    sessions_with_findings=sum(1 for d in diagnoses if d.findings),
    total_cost_usd=sum(d.total_cost_usd for d in diagnoses),
    waste_cost_usd=sum(d.waste_cost_usd for d in diagnoses),
    by_kind=evidence,
    patches=patches,
)
renderer.render_aggregate(report)
```

**Layering invariant:** `diagnostician/aggregate.py` never imports from `recommender/`. `recommender/evidence.py` never imports from `diagnostician/`. The CLI orchestrates across that boundary.

## 13. Testing strategy

### 13.1 Unit tests per classifier

Each classifier gets its own test module (`tests/test_retry_loop.py`, etc.) with:

- **Happy path:** fixture with the exact pattern present → exactly one Finding returned with correct `kind`, `first_turn`, `confidence`, `severity`, and evidence shape.
- **No finding:** fixture with zero occurrences → empty list.
- **Boundary cases:**
  - `retry_loop`: two calls with a successful call between them → no finding. Two calls with different keys → no finding. Two calls, only one errored → no finding.
  - `scope_creep`: phrase in user turn (not assistant) → no finding. Exact phrase in a longer word (substring) → configurable, but for v0 use whole-phrase match (space or punctuation boundary).
  - `stale_context`: large result but referenced within N_stale turns → no finding. Large result across a compaction event → no finding. Two large results, one stale one not → finding for one item only.
- **Empty trace:** `classify(empty_trace)` → `[]`, no raise.
- **Confidence/severity thresholds:** stale_context at exactly 500K token-turns → MEDIUM; at 500K+1 → HIGH.

### 13.2 Orchestrator tests

- Runs all three classifiers; emits a Diagnosis with correct `findings`, `inflection_turn`, `waste_cost_usd`.
- Verifies `patches = []` at orchestrator exit.
- Verifies stale_context `cost_usd` is computed (non-None) and retry_loop/scope_creep remain `None`.
- Verifies `findings` sorted by `first_turn`.
- Uses fixtures that trigger multiple classifiers: `inflection_turn` = min of their `first_turn` values.

### 13.3 Recommender tests

- Each finding kind produces a Patch with the correct `target_file`, non-empty `unified_diff`, correct `finding_kind`, and a non-empty `evidence_summary`.
- `generate(diagnosis)` returns a new Diagnosis with `len(patches) == len(findings)`.
- Original Diagnosis is not mutated.

### 13.4 Aggregator tests

- `aggregate.run()` with a tmp directory of two fixture JSONL files both within window → returns two Diagnoses.
- A file with mtime before the cutoff → excluded.
- `evidence.accumulate()` correctly tallies `session_count` and `total_waste_usd`.
- Cross-session patch includes evidence line only when `session_count >= 2`.

### 13.5 Fixtures for autopsy tests

Extend the existing `tests/fixtures/claude_code/` corpus with:

- `with-retry-loop/` — a session with ≥ 2 identical failing tool calls with no fix between them.
- `with-scope-creep/` — a session with ≥ 1 explicit re-scoping phrase in an assistant turn.
- `with-stale-context/` — a session with a large tool result that goes unreferenced for > 5 turns.
- `with-all-three/` — a session triggering all three classifiers; used for orchestrator and inflection tests.
- `clean/` — an alias for the existing `short-clean/` fixture; zero findings expected.

Fixtures should be minimal (the smallest session that demonstrates the pattern) to keep test runtime fast.

### 13.6 Non-goals at this layer

The diagnostician is NOT responsible for:

- Rendering — tests assert on data structures, not on terminal output.
- Accurate dollar costs to the cent — tests verify cost_usd is non-None and positive for stale_context; they do not assert exact values (the price table may change).
- Token counting — `ToolResult.token_count` may be 0 (offline mode); tests for stale_context should set realistic non-zero values on fixture ToolResults.

## 14. Open questions deferred to implementation

1. **3-gram reference detection implementation.** The approach is correct; the specific Python implementation (sliding window over `content.split()`, checking against a set of turn-text 3-grams) needs profiling on long sessions. If it's too slow, replace with a faster string-search heuristic.

2. **Bash command key normalization.** "Stripped" means `strip()`. Does collapsing internal whitespace improve dedup for multi-line heredoc commands? Decide during retry_loop implementation against real fixtures.

3. **`"i noticed that"` action-verb guard.** The 20-character look-ahead for action verbs after `"i noticed that"` may need tuning. Validate against real sessions before shipping.

4. **Model price table completeness.** New Claude models are released regularly. The `_INPUT_PRICE_PER_MTOK` table needs a maintenance policy. For now: startswith-prefix matching plus a Sonnet default. Add a `ParserWarning`-style log line when the default is used.

5. **Compaction detection in stale-context.** The parser emits compaction events as `Turn(role="system", ...)`. The stale_context classifier identifies these by checking `turn.role == "system"` and `"compact" in turn.text.lower()`. Verify against the `with-compaction` fixture.

## 15. What this design deliberately does not do

- **No LLM calls.** All classifiers are deterministic heuristics. The "deterministic core" principle is from CLAUDE.md and is non-negotiable in v0.
- **No speculative cost attribution.** retry_loop and scope_creep carry `cost_usd=None` because there is no honest counterfactual. Inventing a number would undermine trust in the findings that do have attributed costs.
- **No per-subagent diagnosis.** Main trace only in v0. Subagent internals are deferred to v1 to avoid the turn-numbering complexity of merging sub-trace findings into a parent Diagnosis.
- **No partial-use detection.** "Loaded but partially used" is fragile. Binary: stale after N_stale turns, or not.
- **No cross-classifier state sharing.** Each classifier receives the full SessionTrace independently. They do not communicate. If a future classifier needs output from another (e.g., "retry loops that caused scope creep"), that composition is the orchestrator's job.
- **No configuration file.** Thresholds (`T_size`, `N_stale`, etc.) are constants in v0. v1 can read them from `.cctx.toml` if users need tuning.
- **No streaming output.** The orchestrator runs all three classifiers to completion and returns a fully-populated Diagnosis. Streaming findings to the renderer mid-analysis is a v1 nicety.
