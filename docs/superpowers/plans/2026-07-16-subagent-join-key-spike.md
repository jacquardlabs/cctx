# Subagent Join Key Spike (#193) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out issue #193 — confirm whether any cctx export format exposes a subagent/sidechain join key at dispatch granularity, pin the finding as executable regression tests, then (per explicit user direction to roll the follow-up into this session rather than deferring it) implement the join key where it can be added cleanly.

**Architecture:** Starts as a spike (no production changes) to confirm and pin the finding with two characterization tests. The finding: no export format carries the join key. User then directed implementing the fix now rather than only filing a follow-up. Scoped to JSON/JSONL only — `SubagentAttribution` already sits at the right granularity there, so adding `dispatching_tool_use_id` is a clean field addition. CSV needs a real design pass (bucketing findings by `session_id` instead of colliding turn_numbers) that doesn't belong in this session, so its follow-up issue stays filed-but-unimplemented and #193 closes noting that split.

**Tech Stack:** Python 3.10+, pytest, `uv` (this worktree's local `.venv` — `uv run pytest` bootstraps it), `gh`/`ghj` CLI for GitHub actions.

## Global Constraints

- Branch: this plan's commits land on the current worktree branch `worktree-i193` — confirm this is the intended feature branch for #193 before committing (see Task 0).
- `jacquardlabs/cctx` is an org repo — use `ghj` (not bare `gh`) for issue create/comment/close per the user's multi-account gh routing convention, so the active account doesn't 403.
- Follow this repo's GitHub issue body template (Phase/Module/Goal/Acceptance criteria/Files/References/Blocked by) and `area:*`-only labels for the follow-up issue (see `CLAUDE.md` → "GitHub issue structure").
- Tests follow the existing `tests/exporters/test_csv.py` / `test_jsonl.py` conventions: local dataclass construction, no fixtures-on-disk, `dataclasses.replace` for variants where an existing helper doesn't cover the shape needed.
- Actions in Task 4 (filing the follow-up issue) and Task 8 (closing issues) are visible to others and hard to fully reverse — confirm with the user before running them, per the "Executing actions with care" guidance. Do not run them unattended.
- CSV is explicitly out of scope for Tasks 5–6 (implementation) — only the follow-up issue in Task 4 documents it. Do not extend CSV inline without a separate design pass.

## Finding (confirmed by direct inspection, 2026-07-16)

No current export format (`jsonl`, `csv`, `json`) exposes a subagent/sidechain join key at dispatch granularity:

- **CSV** (`cctx/exporters/csv.py`): `export_turn_rows` iterates only `trace.turns` — the root session. Subagent turns never appear as rows at all, and `COLUMNS` has no `tool_use_id` or `subagent_session_id` field. Verified empirically: a trace with one dispatching turn (`ToolUse(tool_name="Task", tool_use_id="tu-dispatch", subagent_session_id="child-session")`) and a subagent with its own turn produces exactly **one** CSV row — the child's turn is silently dropped.
- **JSON/JSONL** (`cctx/exporters/jsonl.py`): `subagent_costs` (built from `Diagnosis.subagent_costs: list[SubagentAttribution]`) carries each subagent's own `session_id`, `label`, `cost_usd`, `depth`, `model` — but never the parent `tool_use_id` that dispatched it. You get subagent-level cost totals, not a per-dispatch join key.
- **The model layer already has the data**: `ToolUse.subagent_session_id` (`cctx/models.py:45`, "set when tool_name == 'Agent' and child found"), stamped by the parser at `cctx/parsers/claude_code.py:454`. The join key exists internally; it's just never surfaced through any export path.

Per #193's exit criteria, this means: do not implement inline — document the gap and file a follow-up exporter enhancement.

---

### Task 0: Confirm the feature branch

**Files:** none (bookkeeping only)

- [ ] **Step 1: Confirm branch**

```bash
git branch --show-current
```

Expected: `worktree-i193`. If this doesn't match what you expect for #193's work, stop and ask before proceeding — do not commit to the wrong branch.

- [ ] **Step 2: Record it in the work ledger (if resuming via `/work-on`)**

```bash
gate-ledger work-set --slug "subagent-join-key-spike" --branch "worktree-i193"
```

---

### Task 1: Regression test — CSV export drops subagent dispatch entirely

**Files:**
- Modify: `tests/exporters/test_csv.py`

**Interfaces:**
- Consumes: `cctx.exporters.csv.COLUMNS`, `cctx.exporters.csv.write` (existing, unchanged); `cctx.models.SessionTrace`, `Turn`, `ToolUse`, `Usage`, `Diagnosis` (existing, unchanged)
- Produces: `test_csv_export_has_no_subagent_dispatch_join_key` (test only — no new production interface)

- [ ] **Step 1: Write the test**

Add to the end of `tests/exporters/test_csv.py`:

```python
def test_csv_export_has_no_subagent_dispatch_join_key() -> None:
    """Characterizes #193's finding: CSV rows carry no field linking a parent
    turn's Task/Agent tool_use_id to the subagent session it dispatched, and
    subagent turns are never exported as rows at all — export_turn_rows only
    iterates trace.turns (the root session), never trace.subagents.
    """
    import dataclasses

    from cctx.exporters.csv import COLUMNS, write
    from cctx.models import ToolUse

    child_turn = _make_turn(1)
    child_trace = _make_trace(session_id="child-session", turns=[child_turn])

    dispatch_tool_use = ToolUse(
        tool_name="Task",
        tool_use_id="tu-dispatch",
        tool_input={"description": "child task"},
        subagent_session_id="child-session",
    )
    dispatch_turn = dataclasses.replace(
        _make_turn(1, tool_names=[]),
        tool_uses=[dispatch_tool_use],
    )
    trace = dataclasses.replace(
        _make_trace(turns=[dispatch_turn]),
        subagents=[child_trace],
    )
    diagnosis = _make_diagnosis(findings=[])

    buf = io.StringIO()
    write([(diagnosis, trace)], buf)

    # No column exposes the dispatch join key.
    assert "tool_use_id" not in COLUMNS
    assert "subagent_session_id" not in COLUMNS

    # The child session's own turn never appears as a row — only the
    # parent's dispatch_turn does.
    _, rows = _read_csv(buf.getvalue())
    assert len(rows) == 1
    assert rows[0]["session_id"] == "sess-xyz"
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run pytest tests/exporters/test_csv.py::test_csv_export_has_no_subagent_dispatch_join_key -v`
Expected: `PASSED` — this is a characterization test pinning current (confirmed-absent) behavior, not a red/green TDD cycle. There is no implementation change in this task.

- [ ] **Step 3: Commit**

```bash
git add tests/exporters/test_csv.py
git commit -m "test: pin CSV export's absent subagent dispatch join key (#193)"
```

---

### Task 2: Regression test — JSON/JSONL `subagent_costs` has no dispatch join key

**Files:**
- Modify: `tests/exporters/test_jsonl.py`

**Interfaces:**
- Consumes: `cctx.exporters.jsonl.export_diagnosis` (existing, unchanged); `cctx.models.SubagentAttribution`, `Diagnosis` (existing, unchanged)
- Produces: `test_jsonl_subagent_costs_has_no_dispatch_join_key` (test only)

- [ ] **Step 1: Write the test**

Add to the end of `tests/exporters/test_jsonl.py`:

```python
def test_jsonl_subagent_costs_has_no_dispatch_join_key() -> None:
    """Characterizes #193's finding: subagent_costs entries carry the
    subagent's own session_id/label/cost/depth/model, but never the parent
    tool_use_id that dispatched it — so JSON/JSONL export gives subagent-level
    totals, not a per-dispatch join key.
    """
    import dataclasses

    from cctx.exporters.jsonl import export_diagnosis
    from cctx.models import SubagentAttribution

    diag = _make_diagnosis()
    trace = _make_trace()
    diag = dataclasses.replace(diag, subagent_costs=[
        SubagentAttribution(
            session_id="child-1",
            label="My task",
            total_cost_usd=0.020,
            depth=1,
            model="claude-sonnet-4",
        )
    ])
    data = json.loads(export_diagnosis(diag, trace))
    entry = data["subagent_costs"][0]

    assert set(entry.keys()) == {"session_id", "label", "cost_usd", "depth", "model"}
    assert "tool_use_id" not in entry
    assert "dispatching_tool_use_id" not in entry
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run pytest tests/exporters/test_jsonl.py::test_jsonl_subagent_costs_has_no_dispatch_join_key -v`
Expected: `PASSED` — same characterization-test note as Task 1.

- [ ] **Step 3: Commit**

```bash
git add tests/exporters/test_jsonl.py
git commit -m "test: pin JSON/JSONL export's absent subagent dispatch join key (#193)"
```

---

### Task 3: Full verification pass

**Files:** none (verification only, no commit)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass, including the 24 pre-existing exporter tests plus the 2 new ones (26 total in `tests/exporters/`).

- [ ] **Step 2: Run lint**

Run: `uv run ruff check cctx tests`
Expected: no new violations introduced by the two test additions.

---

### Task 4: File the follow-up exporter-enhancement issue

**Files:** none (GitHub action only)

**Scope note:** narrowed to JSON/JSONL during planning. CSV's `export_turn_rows` emits root-only turns with `finding_kinds`/`is_inflection_turn` columns keyed by root turn numbers; making it carry subagent rows means bucketing findings by `session_id` (turn numbers restart at 1 in every subagent trace, so raw turn-number keys collide across sessions) — a real design question, not a mechanical field addition. JSON/JSONL's `subagent_costs` already sits at exactly the granularity jig/studious need (one entry per dispatched subagent), so this issue — and Tasks 5–6 below — implement the join key there only. CSV's absence is called out explicitly as a known, deliberately deferred limitation.

**This task performs an action visible to others (creating a GitHub issue) — confirm with the user before running it.**

- [ ] **Step 1: File the issue**

```bash
ghj issue create --repo jacquardlabs/cctx \
  --title "exporter: CSV export still has no subagent dispatch join key (JSON/JSONL fixed in #193)" \
  --label "area:exporter" \
  --body "$(cat <<'EOF'
**Phase:** (unmilestoned — future work)
**Module:** `cctx/exporters/csv.py`

## Goal
Spike #193 confirmed no cctx export format exposed a subagent/sidechain dispatch join key. The JSON/JSONL side was fixed in the same session (`SubagentAttribution.dispatching_tool_use_id`, populated in `cctx/diagnostician/__init__.py`, emitted by `cctx/exporters/jsonl.py`). CSV was deliberately left out of that fix: `export_turn_rows` (`cctx/exporters/csv.py`) only iterates `trace.turns` (the root session) — subagent turns never appear as rows at all, and there's no column identifying a dispatching `tool_use_id`. Extending CSV isn't a drop-in field addition like JSON was — `finding_kinds`/`is_inflection_turn` are currently keyed by raw turn_number, which restarts at 1 in every subagent trace, so mixing root and subagent rows into one flat table requires bucketing findings by `session_id` first. That's a real design question (does a CSV consumer even want nested subagent rows flattened into the parent table, or a separate export mode?) deserving its own pass rather than a bolt-on.

## Acceptance criteria
- [ ] Design decision made and documented: how subagent turns are represented as CSV rows (new column(s), row identity, and how `finding_kinds`/`is_inflection_turn` are correctly scoped per `session_id` rather than colliding on turn_number)
- [ ] `cctx/exporters/csv.py` emits subagent turns as rows (recursing into `trace.subagents`), with a column identifying the dispatching `tool_use_id`
- [ ] `tests/exporters/test_csv.py::test_csv_export_has_no_subagent_dispatch_join_key` (added by #193) is updated to assert presence instead of absence
- [ ] Layering invariants honored — no new imports from `click`/`anthropic` in `cctx/exporters/`

## Files
- `cctx/exporters/csv.py`
- `tests/exporters/test_csv.py`

## References
- #193 (spike; JSON/JSONL fix landed in the same session)
- #88 (per-subagent cost attribution)

## Blocked by
- None
EOF
)"
```

Capture the returned issue number from this command's output — it's needed for Task 8.

---

### Task 5: `SubagentAttribution.dispatching_tool_use_id` — model + diagnostician

**Files:**
- Modify: `cctx/models.py:254-262` (`SubagentAttribution` dataclass)
- Modify: `cctx/diagnostician/__init__.py:212-247` (`_build_label_map` → `_build_dispatch_map`, `_collect_attributions`)
- Test: `tests/test_diagnostician_subagents.py`

**Interfaces:**
- Consumes: `cctx.models.ToolUse.subagent_session_id` / `.tool_use_id` (existing, unchanged); `SessionTrace.turns`, `.subagents` (existing, unchanged)
- Produces: `SubagentAttribution.dispatching_tool_use_id: str | None` — consumed by Task 6's exporter change

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_diagnostician_subagents.py`:

```python
def test_attribution_records_dispatching_tool_use_id():
    """SubagentAttribution.dispatching_tool_use_id is the parent's Agent/Task
    tool_use_id that dispatched this subagent — the join key jig/studious use
    to correlate a dispatch-time routing decision with its actual cost (#193
    follow-up)."""
    from cctx.diagnostician import run
    child = _make_trace("child-1", input_tokens=1_000)
    tu = _agent_tu("child-1", description="Explore the codebase")
    parent = _make_trace("parent", input_tokens=1_000, subagents=[child], tool_uses=[tu])
    diag = run(parent)
    assert diag.subagent_costs[0].dispatching_tool_use_id == "tu_child-1"


def test_attribution_dispatching_tool_use_id_none_when_orphaned():
    """Unlinked subagent (no matching ToolUse) gets dispatching_tool_use_id=None."""
    from cctx.diagnostician import run
    child = _make_trace("child-unlinked-session", input_tokens=1_000)
    parent = _make_trace("parent", input_tokens=1_000, subagents=[child])
    diag = run(parent)
    assert diag.subagent_costs[0].dispatching_tool_use_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_diagnostician_subagents.py -k dispatching_tool_use_id -v`
Expected: both `FAIL` with `AttributeError: 'SubagentAttribution' object has no attribute 'dispatching_tool_use_id'`

- [ ] **Step 3: Add the field to `SubagentAttribution`**

In `cctx/models.py`, the `SubagentAttribution` dataclass currently reads:

```python
@dataclass
class SubagentAttribution:
    """Cost attribution for a single subagent session."""

    session_id:     str
    label:          str        # from Agent tool_input['description'], else prompt[:80]
    total_cost_usd: float      # inclusive: this subagent + its own children
    depth:          int        # 1 = direct child, 2 = grandchild, …
    model:          str | None
```

Change it to:

```python
@dataclass
class SubagentAttribution:
    """Cost attribution for a single subagent session."""

    session_id:     str
    label:          str        # from Agent tool_input['description'], else prompt[:80]
    total_cost_usd: float      # inclusive: this subagent + its own children
    depth:          int        # 1 = direct child, 2 = grandchild, …
    model:          str | None
    dispatching_tool_use_id: str | None = None  # parent's Agent/Task tool_use_id;
    # None when no matching ToolUse was found (orphaned/unlinked subagent).
```

- [ ] **Step 4: Populate it in the diagnostician**

In `cctx/diagnostician/__init__.py`, this function currently reads:

```python
def _build_label_map(trace: SessionTrace) -> dict[str, str]:
    """Map child session_id → display label from the parent's Agent ToolUse inputs."""
    label_map: dict[str, str] = {}
    for turn in trace.turns:
        for tu in turn.tool_uses:
            if tu.subagent_session_id:
                ti = tu.tool_input
                label_map[tu.subagent_session_id] = (
                    ti.get("description")
                    or (ti.get("prompt") or "")[:80]
                    or tu.subagent_session_id[:12]
                )
    return label_map


def _collect_attributions(
    trace: SessionTrace,
    depth: int = 1,
    label_map: dict[str, str] | None = None,
) -> list[SubagentAttribution]:
    """Flat DFS list of SubagentAttribution, one per subagent at every depth."""
    if label_map is None:
        label_map = _build_label_map(trace)
    result: list[SubagentAttribution] = []
    for child in trace.subagents:
        label = label_map.get(child.session_id, child.session_id[:12])
        cost = _compute_inclusive_cost(child)
        result.append(SubagentAttribution(
            session_id=child.session_id,
            label=label,
            total_cost_usd=round(cost, 4),
            depth=depth,
            model=child.primary_model,
        ))
        result.extend(_collect_attributions(child, depth + 1, None))
    return result
```

Replace both functions with:

```python
def _build_dispatch_map(trace: SessionTrace) -> dict[str, tuple[str, str]]:
    """Map child session_id → (display label, dispatching tool_use_id) from
    the parent's Agent ToolUse inputs."""
    dispatch_map: dict[str, tuple[str, str]] = {}
    for turn in trace.turns:
        for tu in turn.tool_uses:
            if tu.subagent_session_id:
                ti = tu.tool_input
                label = (
                    ti.get("description")
                    or (ti.get("prompt") or "")[:80]
                    or tu.subagent_session_id[:12]
                )
                dispatch_map[tu.subagent_session_id] = (label, tu.tool_use_id)
    return dispatch_map


def _collect_attributions(
    trace: SessionTrace,
    depth: int = 1,
    dispatch_map: dict[str, tuple[str, str]] | None = None,
) -> list[SubagentAttribution]:
    """Flat DFS list of SubagentAttribution, one per subagent at every depth."""
    if dispatch_map is None:
        dispatch_map = _build_dispatch_map(trace)
    result: list[SubagentAttribution] = []
    for child in trace.subagents:
        label, dispatching_tool_use_id = dispatch_map.get(
            child.session_id, (child.session_id[:12], None)
        )
        cost = _compute_inclusive_cost(child)
        result.append(SubagentAttribution(
            session_id=child.session_id,
            label=label,
            total_cost_usd=round(cost, 4),
            depth=depth,
            model=child.primary_model,
            dispatching_tool_use_id=dispatching_tool_use_id,
        ))
        result.extend(_collect_attributions(child, depth + 1, None))
    return result
```

This is the only caller of `_build_label_map`/`_collect_attributions` in the codebase — no other file references either name.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_diagnostician_subagents.py -v`
Expected: all tests in the file `PASS`, including the 2 new ones (confirm no regression in the existing label/depth/orphan-fallback tests, which exercise the same code path).

- [ ] **Step 6: Commit**

```bash
git add cctx/models.py cctx/diagnostician/__init__.py tests/test_diagnostician_subagents.py
git commit -m "feat: add dispatching_tool_use_id to SubagentAttribution (#193 follow-up)"
```

---

### Task 6: Emit `dispatching_tool_use_id` in JSON/JSONL export

**Files:**
- Modify: `cctx/exporters/jsonl.py` (the `subagent_costs` list comprehension inside `export_diagnosis`)
- Modify: `tests/exporters/test_jsonl.py` (flip `test_jsonl_subagent_costs_has_no_dispatch_join_key` to assert presence)

**Interfaces:**
- Consumes: `SubagentAttribution.dispatching_tool_use_id` (Task 5, now available)
- Produces: `subagent_costs[i]["dispatching_tool_use_id"]` in the exported JSON/JSONL object

- [ ] **Step 1: Update the exporter**

In `cctx/exporters/jsonl.py`, `export_diagnosis` currently builds:

```python
        "subagent_costs": [
            {
                "session_id": a.session_id,
                "label":      a.label,
                "cost_usd":   a.total_cost_usd,
                "depth":      a.depth,
                "model":      a.model,
            }
            for a in diagnosis.subagent_costs
        ],
```

Change it to:

```python
        "subagent_costs": [
            {
                "session_id":              a.session_id,
                "label":                   a.label,
                "cost_usd":                a.total_cost_usd,
                "depth":                   a.depth,
                "model":                   a.model,
                "dispatching_tool_use_id": a.dispatching_tool_use_id,
            }
            for a in diagnosis.subagent_costs
        ],
```

- [ ] **Step 2: Flip the characterization test to assert presence**

In `tests/exporters/test_jsonl.py`, replace the existing `test_jsonl_subagent_costs_has_no_dispatch_join_key` function (added by Task 2) with:

```python
def test_jsonl_subagent_costs_has_dispatch_join_key() -> None:
    """subagent_costs entries carry dispatching_tool_use_id — the parent
    turn's Agent/Task tool_use_id that dispatched this subagent — closing
    the gap characterized by #193."""
    import dataclasses

    from cctx.exporters.jsonl import export_diagnosis
    from cctx.models import SubagentAttribution

    diag = _make_diagnosis()
    trace = _make_trace()
    diag = dataclasses.replace(diag, subagent_costs=[
        SubagentAttribution(
            session_id="child-1",
            label="My task",
            total_cost_usd=0.020,
            depth=1,
            model="claude-sonnet-4",
            dispatching_tool_use_id="tu_abc123",
        )
    ])
    data = json.loads(export_diagnosis(diag, trace))
    entry = data["subagent_costs"][0]

    assert entry["dispatching_tool_use_id"] == "tu_abc123"
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `uv run pytest tests/exporters/test_jsonl.py tests/test_diagnostician_subagents.py -v`
Expected: all `PASS`, including `test_export_diagnosis_includes_subagent_costs` (unaffected — it doesn't assert an exact key set) and the newly renamed test.

- [ ] **Step 4: Commit**

```bash
git add cctx/exporters/jsonl.py tests/exporters/test_jsonl.py
git commit -m "feat: emit dispatching_tool_use_id in JSON/JSONL export (#193 follow-up)"
```

---

### Task 7: Full verification pass

**Files:** none (verification only, no commit)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass (762 pre-existing + 2 from Task 1 + 1 renamed-not-added from Task 2/6 + 2 new from Task 5 = 766 total).

- [ ] **Step 2: Run lint**

Run: `uv run ruff check cctx tests`
Expected: no new violations.

---

### Task 8: Close the follow-up issue and #193

**Files:** none (GitHub actions only)

**This task performs actions visible to others (closing GitHub issues) — confirm with the user before running any command in this task.**

- [ ] **Step 1: Close the follow-up issue (Task 4) as scoped to CSV only**

The JSON/JSONL half of that issue's original motivation is now done; the issue itself (filed in Task 4) was already scoped to CSV-only per the Task 4 scope note, so it stays open as filed — no action needed here unless Task 4's issue body needs a correction. Skip this step if Task 4's issue was filed with the CSV-only scope already reflected (it was, per Task 4's body text above).

- [ ] **Step 2: Close #193 with findings**

Substitute `<FOLLOWUP_ISSUE_NUMBER>` with the number captured in Task 4.

```bash
ghj issue close 193 --repo jacquardlabs/cctx --comment "$(cat <<'EOF'
Confirmed: no export format exposed a subagent/sidechain join key at dispatch granularity. Fixed for JSON/JSONL in this same session; CSV remains a known gap (filed separately, see below).

- **JSON/JSONL** (`cctx/exporters/jsonl.py`): `subagent_costs` entries now carry `dispatching_tool_use_id` — the parent turn's Agent/Task `tool_use_id` that dispatched the subagent — sourced from `SubagentAttribution.dispatching_tool_use_id` (`cctx/models.py`), populated in `cctx/diagnostician/__init__.py`'s `_build_dispatch_map`/`_collect_attributions`. This is the join key: match a dispatch-time routing decision's `tool_use_id` against this field to get that dispatch's actual cost.
- **CSV** (`cctx/exporters/csv.py`): still has no join key and doesn't export subagent turns as rows at all. Extending it isn't a drop-in field addition — `finding_kinds`/`is_inflection_turn` are keyed by raw turn_number, which collides across subagent traces, so it needs its own design pass. Filed separately: #<FOLLOWUP_ISSUE_NUMBER>.

Regression tests: `tests/exporters/test_csv.py::test_csv_export_has_no_subagent_dispatch_join_key` (still documents the CSV gap), `tests/exporters/test_jsonl.py::test_jsonl_subagent_costs_has_dispatch_join_key` (now asserts presence), `tests/test_diagnostician_subagents.py::test_attribution_records_dispatching_tool_use_id` and `::test_attribution_dispatching_tool_use_id_none_when_orphaned`.
EOF
)"
```

---

## Self-Review

**Spec coverage** — this plan closes out #193's three exit-criteria checkboxes directly: Tasks 1–2 confirm and pin the finding (checkbox 1); Task 8 Step 2 documents it on the issue (checkbox 2's "if present" branch now partially applies — JSON/JSONL is present after Tasks 5–6 — and checkbox 3's "if absent" branch applies to the CSV remainder: filed as its own issue in Task 4 rather than implemented inline). Tasks 5–6 are the "roll it into this session" implementation the user asked for beyond #193's original no-inline-implementation scope, deliberately narrowed to JSON/JSONL with the CSV rationale documented in Task 4's scope note rather than silently dropped.

**Placeholder scan** — no TBD/TODO; `<NEW_ISSUE_NUMBER>` in Task 4 Step 2 is not a placeholder in the prohibited sense — it's a value only known after Step 1's `gh` call returns, substituted by whoever executes the task, same as any two-step gh workflow.

**Type consistency** — `ToolUse`, `SessionTrace`, `SubagentAttribution`, `Diagnosis` field names in Tasks 1–2 match `cctx/models.py` exactly as read on 2026-07-16; both test snippets were run standalone against the actual codebase before being written into this plan and confirmed passing.
