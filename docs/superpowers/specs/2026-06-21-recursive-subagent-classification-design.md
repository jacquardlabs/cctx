# Design: Recursive subagent classification

**Date:** 2026-06-21
**Status:** Draft
**Issue:** #156 — M29 — Recursive subagent diagnosis

## Overview

cctx runs its per-turn classifier suite against the top-level `SessionTrace` only. Subagents are read for cost attribution (`SubagentAttribution`) and the parent-level fan-out classifier, but a retry loop, stale-context buildup, or tool-thrash that happens *inside* a child session is invisible to autopsy. This is the open half of PRODUCT.md known problem #2 ("subagent diagnosis is shallow").

This design runs the nine single-session classifiers recursively inside every subagent trace (grandchildren included — #118 made the full tree available), attributes each finding to its subagent, and folds interior waste into the session's headline waste number **without double-counting** the cost that the fan-out classifier already charges.

It honors the product principles: no new state (Principle 4), deterministic heuristics, no LLM calls (Principle 5).

## What recurses, what doesn't

| Classifier | Recurses into subagents? | Why |
|---|---|---|
| retry_loop, scope_creep, stale_context, tool_thrash, dead_end, exploration_thrash, unused_context, cache_hygiene, compaction | **Yes** | Per-turn classifiers — a child session is just another sequence of turns |
| `project_specific` | No | Cross-session aggregator (operates on the `--since` window, not one trace) |
| `fan_out` | No | Analyzes the *set* of subagents (overlap/retry), not any one interior; stays parent-level |

## Model change: `Finding.session_id`

`Finding` carries no session identity today — only `first_turn`/`last_turn`, which are meaningful within a single trace's turn numbering. A subagent's "turn 9" collides with the parent's. One new optional field fixes this:

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
    session_id: str | None = None   # NEW — subagent id; None = root trace
```

`session_id` does three jobs: disambiguates colliding turn numbers for display, drives the ancestry dedup check for waste accounting, and lets renderers tag/group. The default `None` keeps every existing `Finding(...)` construction and test working.

## Classification flow (`diagnostician/__init__.py`)

`run()` gains a recursive pass after the parent classification:

```
findings = classify(parent_trace)                 # session_id stays None
for each subagent S in the tree (depth-first):
    sub_findings = classify(S)                     # via _safe_classify, all 9 classifiers
    stamp each with session_id = S.session_id
    findings.extend(sub_findings)
```

Each classifier is invoked through the existing `_safe_classify` wrapper, so a classifier raising inside one subagent never aborts the run. The walk reuses the same tree traversal that `_collect_attributions` already performs.

Root findings keep `session_id = None`; the existing `findings.sort(key=lambda f: f.first_turn)` applies to **root findings only**. Subagent findings are appended in tree order (depth-first) after the sorted root findings, so the parent narrative reads first.

**Per-trace cost patching.** `_patch_costs` derives a finding's `cost_usd` (e.g. stale-context token-turns × input price) from a model price. Subagent findings must be priced at **their own subagent's `primary_model`**, not the parent's — a stale-context finding inside a `gpt-4o` child is priced at gpt-4o, a `claude-opus-4-8` child at Opus. So `_patch_costs` runs once per trace during the recursive pass with that trace's model, before the findings are merged — not as a single parent-model pass over the merged list.

## Waste accounting — full accounting with fan-out dedup

A subagent is counted toward waste **at most once**. The fan-out classifier already charges a flagged subagent's *entire inclusive cost* (it + its children) as waste — the whole run was wasteful (overlap or failed retry). So an interior finding's cost is added only when the run was otherwise useful.

```python
other_waste    = Σ root findings' cost_usd            (excl. FANOUT_WASTE)   # unchanged
fanout_waste   = Σ inclusive cost of fanout-flagged subagents                # unchanged
interior_waste = Σ subagent findings' cost_usd
                 WHERE no ancestor (including the finding's own subagent)
                       is fan-out-flagged                                     # NEW
waste_cost     = min(other_waste + fanout_waste + interior_waste, total_cost)
```

**The dedup rule:** an interior finding contributes to `interior_waste` iff neither its subagent nor any ancestor subagent is in `wasted_sids` (the set of fan-out-flagged subagent session ids). Rationale:

- If the subagent (or an ancestor) is fan-out-flagged, its whole inclusive cost is already in `fanout_waste` — the interior finding is **diagnostic-only** (surfaced and labeled, but not re-charged).
- If the subagent is *not* flagged (its run was useful overall) but has an interior retry loop, that portion *was* wasted within an otherwise-useful run, so it counts.

`SubagentAttribution.total_cost_usd` is inclusive (subagent + its children), so flagging a parent subagent correctly subsumes its grandchildren — hence the **ancestor** check, not just self.

The existing `min(…, total_cost)` cap stays as the backstop against intra-subagent finding overlap (multiple interior findings covering the same turns). This is the *same* bound that already protects the root-findings sum today — not a new class of risk.

**Implementation note:** the dedup needs, for each subagent finding, the chain of ancestor subagent ids. Build a `child_session_id -> parent_session_id` map during the recursive walk (the tree is already traversed for classification), then walk up from each finding's `session_id` checking membership in `wasted_sids`.

## Inflection and verdict

- **Inflection stays root-only.** `inflection.detect()` reasons over `first_turn`, but subagent turn numbers live in a different numbering space — mixing them corrupts it. Inflection is computed from root findings only ("when did *this* session diverge"). Subagent findings do not move it.
- **Verdict reflects full accounting, no change needed.** The count-based headline `N finding(s) · $X waste` already does the right thing once the list and `waste_cost` include subagent findings: `N` = all findings, `$X` = `waste_cost` (now with `interior_waste`). `kind_summary` includes subagent finding kinds, deduped — a retry loop inside a child *is* a retry-loop problem in the session.

## Rendering — flat list with a subagent tag

All four surfaces render the single findings list as today; when `finding.session_id` is set, they prepend a tag resolved from the subagent's `agent_name` (from `subagent_meta`), e.g.:

```
RETRY LOOP  (high confidence) — looped 4× on Edit
[Resolver] RETRY LOOP  (high confidence) — circling the same grep
```

- **terminal.py** — tag prefix in the findings loop and `render_turn`.
- **github.py** — a "Subagent" column value or inline `[label]` in the findings table.
- **report.py / autopsy.html.j2** — `[label]` chip before the kind badge.
- **trace_tui.py** — tag in the `FindingModal` and the table flags via the existing `flags_label` helper.

A label resolver maps `session_id -> agent_name` from the trace's subagent tree (fallback: short session id). The subagent **cost table** already present in autopsy output gives the structural/tree view, so a flat tagged list is sufficient for v1; grouping-by-subagent is deferred (see Out of scope).

## Exporters

`exporters/jsonl.py` adds `session_id` to each serialized finding (machine consumers / CI need to attribute interior findings). `null` for root findings.

## Testing

`tests/diagnostician/` and renderer/exporter tests:

- **Recursion:** a subagent containing a retry-loop pattern → a `RETRY_LOOP` finding with `session_id` = that subagent; grandchild interior finding present (depth-2).
- **Dedup — the critical case:** a subagent that is *both* fan-out-flagged *and* has an interior retry loop → its interior finding is surfaced but its cost is **not** added to `waste_cost` (no double-count). Assert `waste_cost` equals the fan-out-only figure.
- **Counts:** an interior finding in a *non*-flagged subagent *does* raise `waste_cost` by its `cost_usd`.
- **Inflection unchanged:** subagent findings do not alter `inflection_turn`.
- **Rendering:** subagent finding shows its `[label]` tag in terminal + GitHub + HTML; root findings unchanged.
- **Export:** `session_id` present (null for root, subagent id for interior).
- **No regression:** existing `test_diagnostician_subagents` cost figures hold (interior findings on those fixtures, if any, must reconcile).

## Layering

No new dependencies. `models.py` gains one field. The diagnostician already imports the subagent tree; the recursion and dedup are internal to `run()`. Renderers read the new field and the existing `subagent_meta`. No imports cross a layer boundary.

## Out of scope (v1)

- **Grouped-by-subagent display** — a nested "Subagent findings" section per child. Flat-tagged + the cost table cover v1; revisit if deep trees prove cluttered.
- **Per-subagent harvest patches** — interior findings flow into the same recommender; whether a subagent-interior pattern warrants a distinct CLAUDE.md patch vs. the root is a recommender question, deferred.
- **Tree-aware inflection** — a per-subagent "where did this child diverge" marker. Root-only for v1.
- **#100 finding lifecycle** — builds on this (stateless trend over subagent-inclusive findings); separate, deferred.
