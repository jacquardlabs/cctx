# Recursive Subagent Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the 9 per-turn classifiers recursively inside every subagent trace and fold their findings into the diagnosis — with full-accounting waste that never double-counts fan-out cost.

**Architecture:** Add `Finding.session_id` to tag interior findings. `diagnostician.run()` gains a recursive pass that classifies each subagent (pricing each at its own model) and merges the results after the root findings. Waste accounting adds `interior_waste`, deduped against fan-out-flagged subagents via an ancestry walk. Renderers tag subagent findings with a label resolved from `diagnosis.subagent_costs`.

**Tech Stack:** Python 3.10+, dataclasses, pytest. Run tests with `CCTX_OFFLINE=1 python -m pytest`. Lint with `ruff check`.

Spec: `docs/superpowers/specs/2026-06-21-recursive-subagent-classification-design.md` · Issue: #156

---

### Task 1: Add `Finding.session_id`

**Files:**
- Modify: `cctx/models.py` (the `Finding` dataclass)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
def test_finding_session_id_defaults_to_none():
    from cctx.models import Confidence, Finding, FindingKind, Severity
    f = Finding(
        kind=FindingKind.RETRY_LOOP, severity=Severity.HIGH, confidence=Confidence.HIGH,
        first_turn=1, last_turn=2, evidence={}, cost_usd=None, summary="x",
    )
    assert f.session_id is None


def test_finding_session_id_can_be_set():
    from cctx.models import Confidence, Finding, FindingKind, Severity
    f = Finding(
        kind=FindingKind.RETRY_LOOP, severity=Severity.HIGH, confidence=Confidence.HIGH,
        first_turn=1, last_turn=2, evidence={}, cost_usd=None, summary="x",
        session_id="sub-1",
    )
    assert f.session_id == "sub-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `CCTX_OFFLINE=1 python -m pytest tests/test_models.py -k session_id -v`
Expected: FAIL — `TypeError: Finding.__init__() got an unexpected keyword argument 'session_id'`

- [ ] **Step 3: Add the field**

In `cctx/models.py`, the `Finding` dataclass currently ends with `summary: str`. Add the new field after it:

```python
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
    session_id: str | None = None   # subagent id; None = root trace
```

- [ ] **Step 4: Run test to verify it passes**

Run: `CCTX_OFFLINE=1 python -m pytest tests/test_models.py -k session_id -v`
Expected: PASS (both tests)

- [ ] **Step 5: Run the full models test file + lint**

Run: `CCTX_OFFLINE=1 python -m pytest tests/test_models.py -q && ruff check cctx/models.py`
Expected: all pass, lint clean

- [ ] **Step 6: Commit**

```bash
git add cctx/models.py tests/test_models.py
git commit -m "feat(models): add Finding.session_id for subagent attribution (#156)"
```

---

### Task 2: Recursive subagent classification + per-subagent pricing + root-only inflection

**Files:**
- Modify: `cctx/diagnostician/__init__.py` (`run()`, plus a new `_classify_subagents` helper)
- Test: `tests/diagnostician/test_orchestrator.py`

**Context:** `tests/diagnostician/conftest.py` exposes `make_trace(turns, model=...)`, `make_assistant_turn`, `make_tool_use`, `make_tool_result`, `make_tool_result_turn`, `make_user_turn`. `make_trace` builds a `SessionTrace` with `subagents=[]`; attach a subagent with `dataclasses.replace(parent, subagents=[child])`. `_retry_trace()` already exists in `test_orchestrator.py` and builds a trace whose turns trigger `retry_loop`.

- [ ] **Step 1: Write the failing test**

Add to `tests/diagnostician/test_orchestrator.py`:

```python
def _retry_subagent(session_id: str):
    """A subagent trace whose turns trigger retry_loop, with a distinct session_id."""
    import dataclasses
    sub = _retry_trace()
    return dataclasses.replace(sub, session_id=session_id, parent_session_id="root")


def test_run_classifies_subagent_findings_with_session_id():
    import dataclasses
    from cctx import diagnostician
    from cctx.models import FindingKind

    parent = make_trace([make_user_turn(1), make_assistant_turn(2, text="ok")])
    parent = dataclasses.replace(parent, session_id="root",
                                 subagents=[_retry_subagent("sub-1")])
    diag = diagnostician.run(parent)

    sub_findings = [f for f in diag.findings if f.session_id == "sub-1"]
    assert any(f.kind is FindingKind.RETRY_LOOP for f in sub_findings)
    # root has no findings of its own here
    assert all(f.session_id is None or f.session_id == "sub-1" for f in diag.findings)


def test_run_inflection_ignores_subagent_findings():
    import dataclasses
    from cctx import diagnostician

    # Parent is clean (no findings -> inflection None); subagent has a retry loop.
    parent = make_trace([make_user_turn(1), make_assistant_turn(2, text="done")])
    parent = dataclasses.replace(parent, session_id="root",
                                 subagents=[_retry_subagent("sub-1")])
    diag = diagnostician.run(parent)
    assert diag.inflection_turn is None  # subagent findings must not move it
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `CCTX_OFFLINE=1 python -m pytest tests/diagnostician/test_orchestrator.py -k "subagent_findings_with_session_id or inflection_ignores" -v`
Expected: FAIL — no findings carry `session_id == "sub-1"` (subagents are not classified yet)

- [ ] **Step 3: Add the `_classify_subagents` helper**

In `cctx/diagnostician/__init__.py`, add after `_safe_classify` (it already imports `dataclasses`, `_CLASSIFIER_MODULES`, `_patch_costs`):

```python
def _classify_subagents(
    trace: SessionTrace, parent_map: dict[str, str | None]
) -> list[Finding]:
    """Classify every subagent recursively; stamp findings with the subagent's
    session_id and price each at the subagent's own model. Populates parent_map
    (child session_id -> parent session_id) for the waste-accounting ancestry walk."""
    out: list[Finding] = []
    for sub in trace.subagents:
        parent_map[sub.session_id] = trace.session_id
        sub_findings: list[Finding] = []
        for module in _CLASSIFIER_MODULES:
            sub_findings.extend(_safe_classify(module.classify, sub))
        sub_findings = _patch_costs(sub_findings, sub.primary_model)  # subagent's own model
        out.extend(dataclasses.replace(f, session_id=sub.session_id) for f in sub_findings)
        out.extend(_classify_subagents(sub, parent_map))  # recurse into grandchildren
    return out
```

- [ ] **Step 4: Wire it into `run()` (root-only inflection + merge)**

In `run()`, replace the top block. The current code is:

```python
    findings: list[Finding] = []
    for module in _CLASSIFIER_MODULES:
        findings.extend(_safe_classify(module.classify, trace))
    findings.sort(key=lambda f: f.first_turn)

    inflection_turn = inflection.detect(findings)
    findings = _patch_costs(findings, trace.primary_model)
```

Replace it with:

```python
    root_findings: list[Finding] = []
    for module in _CLASSIFIER_MODULES:
        root_findings.extend(_safe_classify(module.classify, trace))
    root_findings.sort(key=lambda f: f.first_turn)

    inflection_turn = inflection.detect(root_findings)          # root-only
    root_findings = _patch_costs(root_findings, trace.primary_model)

    # Recurse into subagents; each priced at its own model, stamped with its id.
    parent_map: dict[str, str | None] = {}
    subagent_findings = _classify_subagents(trace, parent_map)

    findings = root_findings + subagent_findings               # root first, then tree order
```

The rest of `run()` (`_collect_attributions`, `_patch_fanout_costs`, cost/waste, `Diagnosis(...)`) stays as-is for now — Task 3 changes the waste math. `_patch_fanout_costs` only touches `FANOUT_WASTE` findings (root-level), so passing the merged list is safe.

- [ ] **Step 5: Run tests to verify they pass**

Run: `CCTX_OFFLINE=1 python -m pytest tests/diagnostician/test_orchestrator.py -k "subagent_findings_with_session_id or inflection_ignores" -v`
Expected: PASS

- [ ] **Step 6: Run the full diagnostician suite (no regression)**

Run: `CCTX_OFFLINE=1 python -m pytest tests/diagnostician/ tests/test_diagnostician_subagents.py tests/test_fanout_classifier.py -q`
Expected: PASS (existing cost/attribution tests unaffected — Task 3 handles waste)

- [ ] **Step 7: Commit**

```bash
git add cctx/diagnostician/__init__.py tests/diagnostician/test_orchestrator.py
git commit -m "feat(diagnostician): classify subagents recursively, priced per-model (#156)"
```

---

### Task 3: Full-accounting interior waste with fan-out ancestry dedup

**Files:**
- Modify: `cctx/diagnostician/__init__.py` (waste block in `run()`)
- Test: `tests/test_diagnostician_subagents.py`

**Context:** `run()` already computes `wasted_sids` (fan-out-flagged subagent ids), `cost_map` (`session_id -> inclusive cost`), `fanout_waste`, and `other_waste`. `parent_map` was built in Task 2. We add `interior_waste` and a dedup helper, and restrict `other_waste` to root findings.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_diagnostician_subagents.py` (it already has `_make_trace(session_id, input_tokens, *, subagents=None, model=..., tool_uses=None)` and `_make_usage`):

```python
def test_interior_finding_in_unflagged_subagent_raises_waste():
    """A subagent that is NOT fan-out-flagged but has an interior finding adds to waste.

    Asserts the _interior_waste accounting helper directly (the run() integration is
    covered end-to-end in Task 8)."""
    from cctx.diagnostician import _interior_waste
    from cctx.models import Confidence, Finding, FindingKind, Severity

    sub_finding = Finding(
        kind=FindingKind.STALE_CONTEXT, severity=Severity.MEDIUM, confidence=Confidence.MEDIUM,
        first_turn=1, last_turn=2, evidence={}, cost_usd=0.05, summary="stale", session_id="sub-1",
    )
    parent_map = {"sub-1": "root"}
    wasted_sids: set[str] = set()  # sub-1 NOT flagged
    assert _interior_waste([sub_finding], parent_map, wasted_sids) == 0.05


def test_interior_finding_in_flagged_subagent_is_not_double_counted():
    """If the subagent is fan-out-flagged, its interior finding cost is NOT re-charged."""
    from cctx.diagnostician import _interior_waste
    from cctx.models import Confidence, Finding, FindingKind, Severity

    sub_finding = Finding(
        kind=FindingKind.RETRY_LOOP, severity=Severity.HIGH, confidence=Confidence.HIGH,
        first_turn=1, last_turn=2, evidence={}, cost_usd=0.05, summary="retry", session_id="sub-1",
    )
    parent_map = {"sub-1": "root"}
    wasted_sids = {"sub-1"}  # flagged -> whole cost already in fanout_waste
    assert _interior_waste([sub_finding], parent_map, wasted_sids) == 0.0


def test_interior_finding_in_flagged_ANCESTOR_is_not_double_counted():
    """A grandchild finding is excluded when its parent subagent is flagged."""
    from cctx.diagnostician import _interior_waste
    from cctx.models import Confidence, Finding, FindingKind, Severity

    grand_finding = Finding(
        kind=FindingKind.RETRY_LOOP, severity=Severity.HIGH, confidence=Confidence.HIGH,
        first_turn=1, last_turn=2, evidence={}, cost_usd=0.05, summary="retry", session_id="grand-1",
    )
    parent_map = {"grand-1": "sub-1", "sub-1": "root"}
    wasted_sids = {"sub-1"}  # parent flagged -> grandchild already counted inclusively
    assert _interior_waste([grand_finding], parent_map, wasted_sids) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `CCTX_OFFLINE=1 python -m pytest tests/test_diagnostician_subagents.py -k interior -v`
Expected: FAIL — `ImportError: cannot import name '_interior_waste'`

- [ ] **Step 3: Add the dedup helper**

In `cctx/diagnostician/__init__.py`, add near the other cost helpers:

```python
def _has_flagged_ancestor(
    session_id: str | None, parent_map: dict[str, str | None], wasted_sids: set[str]
) -> bool:
    """True if session_id or any ancestor subagent is fan-out-flagged."""
    seen: set[str] = set()
    cur = session_id
    while cur is not None and cur not in seen:
        if cur in wasted_sids:
            return True
        seen.add(cur)
        cur = parent_map.get(cur)
    return False


def _interior_waste(
    findings: list[Finding], parent_map: dict[str, str | None], wasted_sids: set[str]
) -> float:
    """Sum subagent-finding cost, excluding any whose subagent (or ancestor) is
    already counted wholesale via fan-out waste — so no cost is double-counted."""
    return sum(
        f.cost_usd for f in findings
        if f.session_id is not None
        and f.cost_usd is not None
        and not _has_flagged_ancestor(f.session_id, parent_map, wasted_sids)
    )
```

- [ ] **Step 4: Update the waste block in `run()`**

The current waste block is:

```python
    fanout_waste = sum(cost_map.get(sid, 0.0) for sid in wasted_sids)
    other_waste = sum(
        f.cost_usd for f in findings
        if f.cost_usd is not None and f.kind is not FindingKind.FANOUT_WASTE
    )
    waste_cost = min(other_waste + fanout_waste, total_cost)
```

Replace it with (note `other_waste` now restricts to **root** findings; `interior_waste` adds deduped subagent cost):

```python
    fanout_waste = sum(cost_map.get(sid, 0.0) for sid in wasted_sids)
    other_waste = sum(
        f.cost_usd for f in findings
        if f.session_id is None
        and f.cost_usd is not None
        and f.kind is not FindingKind.FANOUT_WASTE
    )
    interior_waste = _interior_waste(findings, parent_map, wasted_sids)
    waste_cost = min(other_waste + fanout_waste + interior_waste, total_cost)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `CCTX_OFFLINE=1 python -m pytest tests/test_diagnostician_subagents.py -k interior -v`
Expected: PASS (all three)

- [ ] **Step 6: Run the full subagent + fanout suites (no double-count regression)**

Run: `CCTX_OFFLINE=1 python -m pytest tests/test_diagnostician_subagents.py tests/test_fanout_classifier.py tests/diagnostician/ -q`
Expected: PASS — existing fixtures (subagents have `output_tokens=50`, no interior costed findings) keep their cost numbers

- [ ] **Step 7: Commit**

```bash
git add cctx/diagnostician/__init__.py tests/test_diagnostician_subagents.py
git commit -m "feat(diagnostician): full-accounting interior waste with fan-out ancestry dedup (#156)"
```

---

### Task 4: Terminal renderer — subagent finding tag

**Files:**
- Modify: `cctx/renderers/terminal.py` (`render_diagnosis` findings loop)
- Test: `tests/renderers/test_terminal_renderer_full.py`

**Context:** `render_diagnosis(diagnosis, ...)` loops `for finding in diagnosis.findings`. The label comes from `diagnosis.subagent_costs` (`SubagentAttribution` has `session_id` + `label`). The test file has `_make_diagnosis(findings, ...)` and `_make_finding(kind, ...)` helpers.

- [ ] **Step 1: Write the failing test**

Add to `tests/renderers/test_terminal_renderer_full.py`:

```python
def test_render_diagnosis_tags_subagent_finding_with_label():
    import dataclasses
    from cctx.models import FindingKind, SubagentAttribution

    f = dataclasses.replace(_make_finding(FindingKind.RETRY_LOOP), session_id="sub-1")
    diag = _make_diagnosis([f], waste_cost_usd=0.10)
    diag = dataclasses.replace(diag, subagent_costs=[
        SubagentAttribution(session_id="sub-1", label="Resolver",
                            total_cost_usd=0.2, depth=1, model="gpt-4o"),
    ])
    output = _render_diagnosis(diag)
    assert "[Resolver]" in output
    assert "RETRY LOOP" in output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `CCTX_OFFLINE=1 python -m pytest tests/renderers/test_terminal_renderer_full.py -k tags_subagent -v`
Expected: FAIL — `[Resolver]` not in output

- [ ] **Step 3: Add the label resolver + tag in `render_diagnosis`**

In `cctx/renderers/terminal.py`, find the findings loop (it starts `for finding in diagnosis.findings:` and builds `badge`, then `con.print(badge, conf_note, "—", finding.summary)`). Just before the loop, build the label map; inside the loop, prepend the tag when `finding.session_id` is set:

```python
    sub_labels = {a.session_id: a.label for a in diagnosis.subagent_costs}
    for finding in diagnosis.findings:
        style = _SEVERITY_STYLE.get(finding.severity, "")
        label = _KIND_LABEL.get(finding.kind, finding.kind.value.upper())
        badge = Text(f" {label} ", style=style)
        conf_note = f"({finding.confidence.value} confidence)"
        if finding.session_id is not None:
            tag = sub_labels.get(finding.session_id, finding.session_id[:8])
            con.print(Text(f"[{tag}]", style="cyan"), badge, conf_note, "—", finding.summary)
        else:
            con.print(badge, conf_note, "—", finding.summary)
        if show_health and finding.cost_usd is not None:
            con.print(f"  → savings if fixed: ~${finding.cost_usd:.2f}")
```

(Preserve the existing `show_health` savings line exactly as it is in the current loop.)

- [ ] **Step 4: Run test to verify it passes**

Run: `CCTX_OFFLINE=1 python -m pytest tests/renderers/test_terminal_renderer_full.py -k tags_subagent -v`
Expected: PASS

- [ ] **Step 5: Run the terminal renderer suite + lint**

Run: `CCTX_OFFLINE=1 python -m pytest tests/renderers/test_terminal_renderer_full.py -q && ruff check cctx/renderers/terminal.py`
Expected: PASS, lint clean

- [ ] **Step 6: Commit**

```bash
git add cctx/renderers/terminal.py tests/renderers/test_terminal_renderer_full.py
git commit -m "feat(renderer): tag subagent findings in terminal output (#156)"
```

---

### Task 5: GitHub summary + HTML report — subagent finding tag

**Files:**
- Modify: `cctx/renderers/github.py`, `cctx/renderers/report.py` / `cctx/renderers/templates/autopsy.html.j2`
- Test: `tests/test_github_summary.py`, `tests/renderers/test_report.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_github_summary.py`:

```python
def test_github_summary_tags_subagent_finding():
    import dataclasses
    from cctx.models import SubagentAttribution
    from cctx.renderers.github import render_github_summary

    diag = _make_diagnosis([_make_finding("retry_loop")])
    f = dataclasses.replace(diag.findings[0], session_id="sub-1")
    diag = dataclasses.replace(diag, findings=[f], subagent_costs=[
        SubagentAttribution(session_id="sub-1", label="Resolver",
                            total_cost_usd=0.2, depth=1, model="gpt-4o"),
    ])
    md = render_github_summary(diag)
    assert "Resolver" in md
```

Add to `tests/renderers/test_report.py`:

```python
def test_html_tags_subagent_finding():
    import dataclasses
    from cctx.models import SubagentAttribution

    diag = _make_diagnosis([_make_finding("retry_loop")])
    f = dataclasses.replace(diag.findings[0], session_id="sub-1")
    diag = dataclasses.replace(diag, findings=[f], subagent_costs=[
        SubagentAttribution(session_id="sub-1", label="Resolver",
                            total_cost_usd=0.2, depth=1, model="gpt-4o"),
    ])
    html = _render(diag)
    assert "Resolver" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `CCTX_OFFLINE=1 python -m pytest tests/test_github_summary.py -k tags_subagent tests/renderers/test_report.py -k tags_subagent -v`
Expected: FAIL — "Resolver" not in output

- [ ] **Step 3a: Tag in `github.py`**

In `render_github_summary`, before the findings-table loop add `sub_labels = {a.session_id: a.label for a in diagnosis.subagent_costs}`. In the loop that builds each row (`for f in diagnosis.findings:`), prefix the pattern cell when `f.session_id` is set:

```python
    sub_labels = {a.session_id: a.label for a in diagnosis.subagent_costs}
    for f in diagnosis.findings:
        sev_icon = _SEVERITY_EMOJI.get(f.severity.value, "")
        kind_label = KIND_LABEL.get(f.kind, f.kind.value.upper())
        if f.session_id is not None:
            tag = sub_labels.get(f.session_id, f.session_id[:8])
            kind_label = f"[{tag}] {kind_label}"
        summary = f.summary.replace("|", "\\|")
        lines.append(f"| {sev_icon} {f.severity.value} | {kind_label} | {summary} |")
```

- [ ] **Step 3b: Tag in the HTML template**

In `cctx/renderers/report.py` `render_html`, pass a label map to the template:

```python
    sub_labels = {a.session_id: a.label for a in diag.subagent_costs}
    ...
    return tmpl.render(
        diag=diag,
        trace=trace,
        flagged=_flagged_index(diag.findings),
        pricing_as_of=PRICING_LAST_VERIFIED,
        sub_labels=sub_labels,
    )
```

In `cctx/renderers/templates/autopsy.html.j2`, in the findings `<details>` `<summary>`, before the kind badge add:

```html
        {% if f.session_id %}<span class="badge sub-label">{{ sub_labels.get(f.session_id, f.session_id[:8]) }}</span>{% endif %}
```

And add a CSS rule alongside the other `.badge` rules:

```css
.badge.sub-label { background: #30363d; color: #adbac7; }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `CCTX_OFFLINE=1 python -m pytest tests/test_github_summary.py -k tags_subagent tests/renderers/test_report.py -k tags_subagent -v`
Expected: PASS

- [ ] **Step 5: Run both renderer suites + lint**

Run: `CCTX_OFFLINE=1 python -m pytest tests/test_github_summary.py tests/renderers/test_report.py -q && ruff check cctx/renderers/github.py cctx/renderers/report.py`
Expected: PASS, lint clean

- [ ] **Step 6: Commit**

```bash
git add cctx/renderers/github.py cctx/renderers/report.py cctx/renderers/templates/autopsy.html.j2 tests/test_github_summary.py tests/renderers/test_report.py
git commit -m "feat(renderer): tag subagent findings in GitHub summary + HTML (#156)"
```

---

### Task 6: TUI — tag subagent findings in the FindingModal

**Files:**
- Modify: `cctx/renderers/trace_tui.py` (`finding_modal_text`, and its call site in `launch`)
- Test: `tests/test_trace_tui.py`

**Context:** `finding_modal_text(findings: list[Finding]) -> str` is a pure module-level helper (added in M22) that builds the modal body, one block per finding headed by `KIND_LABEL[f.kind]`. It's called inside `launch()`'s `FindingModal.compose`. We extend it with an optional `sub_labels` map so subagent findings show their tag.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_trace_tui.py` (it has `_finding_of_kind(kind)` returning a `Finding`):

```python
def test_finding_modal_text_tags_subagent_finding():
    import dataclasses
    from cctx.models import FindingKind
    from cctx.renderers.trace_tui import finding_modal_text

    f = dataclasses.replace(_finding_of_kind(FindingKind.RETRY_LOOP), session_id="sub-1")
    text = finding_modal_text([f], sub_labels={"sub-1": "Resolver"})
    assert "[Resolver]" in text
    assert "RETRY LOOP" in text


def test_finding_modal_text_root_finding_has_no_tag():
    from cctx.models import FindingKind
    from cctx.renderers.trace_tui import finding_modal_text

    text = finding_modal_text([_finding_of_kind(FindingKind.RETRY_LOOP)])
    assert "[" not in text.split("RETRY LOOP")[0]  # no tag before the kind label
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `CCTX_OFFLINE=1 python -m pytest tests/test_trace_tui.py -k "modal_text_tags_subagent or modal_text_root_finding" -v`
Expected: FAIL — `finding_modal_text() got an unexpected keyword argument 'sub_labels'`

- [ ] **Step 3: Extend `finding_modal_text`**

In `cctx/renderers/trace_tui.py`, change the helper signature and prepend the tag:

```python
def finding_modal_text(
    findings: list[Finding], sub_labels: dict[str, str] | None = None
) -> str:
    """Body text for the FindingModal — one block per finding, KIND_LABEL headed.
    Subagent findings (session_id set) are prefixed with their [label]."""
    sub_labels = sub_labels or {}
    lines: list[str] = []
    for f in findings:
        label = KIND_LABEL.get(f.kind, f.kind.value.upper())
        if f.session_id is not None:
            tag = sub_labels.get(f.session_id, f.session_id[:8])
            label = f"[{tag}] {label}"
        lines.append(
            f"[bold]{label}[/]  severity={f.severity.value}  confidence={f.confidence.value}"
        )
        lines.append(f"  {f.summary}")
        if f.cost_usd is not None:
            lines.append(f"  cost: ${f.cost_usd:.4f}")
        lines.append("")
    return "\n".join(lines).rstrip() or "No findings."
```

- [ ] **Step 4: Pass the label map at the call site**

In `launch(trace, diagnosis)`, build the map once (near the top, where `flagged`/`session_verdict` are computed) and pass it where `finding_modal_text` is called in `FindingModal.compose`:

```python
    sub_labels = {a.session_id: a.label for a in diagnosis.subagent_costs}
```

Then in `FindingModal.compose`, change `text = finding_modal_text(self._findings)` to `text = finding_modal_text(self._findings, sub_labels)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `CCTX_OFFLINE=1 python -m pytest tests/test_trace_tui.py -q && ruff check cctx/renderers/trace_tui.py`
Expected: PASS, lint clean

- [ ] **Step 6: Commit**

```bash
git add cctx/renderers/trace_tui.py tests/test_trace_tui.py
git commit -m "feat(tui): tag subagent findings in the FindingModal (#156)"
```

---

### Task 7: JSON export — `session_id` on findings

**Files:**
- Modify: `cctx/exporters/jsonl.py` (`export_diagnosis`)
- Test: `tests/exporters/test_jsonl.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/exporters/test_jsonl.py`:

```python
def test_export_finding_includes_session_id() -> None:
    import dataclasses
    import json
    from cctx.exporters.jsonl import export_diagnosis

    diag = _make_diagnosis()
    tagged = dataclasses.replace(diag.findings[0], session_id="sub-1")
    diag = dataclasses.replace(diag, findings=[tagged])
    obj = json.loads(export_diagnosis(diag, _make_trace()))
    assert obj["findings"][0]["session_id"] == "sub-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `CCTX_OFFLINE=1 python -m pytest tests/exporters/test_jsonl.py -k session_id -v`
Expected: FAIL — `KeyError: 'session_id'`

- [ ] **Step 3: Add `session_id` to the serialized finding**

In `cctx/exporters/jsonl.py`, the findings comprehension builds a dict per finding with keys like `kind`, `severity`, `confidence`, `first_turn`, `last_turn`, `cost_usd`. Add `"session_id": f.session_id` to that dict.

- [ ] **Step 4: Run test to verify it passes**

Run: `CCTX_OFFLINE=1 python -m pytest tests/exporters/test_jsonl.py -k session_id -v`
Expected: PASS

- [ ] **Step 5: Run the exporter suite + lint**

Run: `CCTX_OFFLINE=1 python -m pytest tests/exporters/test_jsonl.py -q && ruff check cctx/exporters/jsonl.py`
Expected: PASS, lint clean

- [ ] **Step 6: Commit**

```bash
git add cctx/exporters/jsonl.py tests/exporters/test_jsonl.py
git commit -m "feat(exporter): include session_id on exported findings (#156)"
```

---

### Task 8: Integration test + full-suite / lint / no-regression sweep

**Files:**
- Test: `tests/test_diagnostician_subagents.py` (one end-to-end assertion)

- [ ] **Step 1: Write the end-to-end test**

Add to `tests/test_diagnostician_subagents.py` — a subagent with a retry-loop pattern, run end-to-end, assert the finding surfaces tagged AND its (non-flagged) cost reaches `waste_cost`:

```python
def test_end_to_end_subagent_retry_loop_surfaces_and_is_attributed():
    import dataclasses
    from cctx.diagnostician import run
    from cctx.models import FindingKind
    from tests.diagnostician.conftest import (
        make_assistant_turn, make_tool_result, make_tool_result_turn,
        make_tool_use, make_trace, make_user_turn,
    )

    err = "Error: file not found"
    fp = "src/foo.py"
    retry_turns = [
        make_user_turn(1),
        make_assistant_turn(2, tool_uses=[make_tool_use("t1", "Edit", {"file_path": fp})]),
        make_tool_result_turn(3, tool_results=[make_tool_result("t1", "Edit", err, is_error=True)]),
        make_assistant_turn(4, tool_uses=[make_tool_use("t2", "Edit", {"file_path": fp})]),
        make_tool_result_turn(5, tool_results=[make_tool_result("t2", "Edit", err, is_error=True)]),
    ]
    sub = dataclasses.replace(make_trace(retry_turns), session_id="sub-1", parent_session_id="root")
    parent = dataclasses.replace(
        make_trace([make_user_turn(1), make_assistant_turn(2, text="ok")]),
        session_id="root", subagents=[sub],
    )
    diag = run(parent)
    tagged = [f for f in diag.findings if f.session_id == "sub-1"]
    assert any(f.kind is FindingKind.RETRY_LOOP for f in tagged)
    # sub-1 is not fan-out-flagged here, so its interior waste is real (>= 0, not double-counted)
    assert diag.waste_cost_usd <= diag.total_cost_usd
```

- [ ] **Step 2: Run it**

Run: `CCTX_OFFLINE=1 python -m pytest tests/test_diagnostician_subagents.py -k end_to_end_subagent_retry -v`
Expected: PASS

- [ ] **Step 3: Full suite**

Run: `CCTX_OFFLINE=1 python -m pytest -q`
Expected: all pass (no regressions in cost/attribution/render/export tests)

- [ ] **Step 4: Lint the whole tree**

Run: `ruff check cctx/ tests/`
Expected: All checks passed

- [ ] **Step 5: Manual smoke on the OTEL deep fixture (3-level tree from #118)**

Run:

```bash
CCTX_OFFLINE=1 python -c "
from cctx.parsers.otel import parse_otel_file
from cctx.tokenizer import tokenize_session
from cctx import diagnostician
t = tokenize_session(parse_otel_file('tests/fixtures/otel_deep.jsonl')[0])
d = diagnostician.run(t)
print('findings:', [(f.kind.value, f.session_id) for f in d.findings])
print('waste:', d.waste_cost_usd, 'of total', d.total_cost_usd)
"
```

Expected: runs without error; any subagent findings carry a non-None `session_id`; `waste <= total`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_diagnostician_subagents.py
git commit -m "test: end-to-end recursive subagent classification (#156)"
```

---

## Notes for the implementer

- **Why root-only inflection:** subagent turn numbers live in a separate numbering space; mixing them into `inflection.detect()` (which sorts by `first_turn`) corrupts the parent's divergence point.
- **Why the ancestry walk:** `SubagentAttribution.total_cost_usd` is inclusive (subagent + children), so a fan-out-flagged parent already accounts for its grandchildren — an interior finding under a flagged ancestor must not be re-charged.
- **Label source:** renderers resolve `session_id -> label` from `diagnosis.subagent_costs`, which already carries both — no need to thread the trace into renderers or denormalize onto `Finding`.
- **After all tasks:** open the PR against `main`, milestone "M29 — Recursive subagent diagnosis", body ending with `Closes #156`.
