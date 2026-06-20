# Spec: Cross-project digest — `cctx autopsy --all --since`

**Date:** 2026-06-20  
**Issue:** #94 — M21: Cross-project digest  
**Status:** Ready for implementation

---

## 1. Goal

`cctx autopsy --all --since 7d` iterates over every project under `~/.claude/projects/`, runs the existing per-project aggregate pipeline on each, and renders a two-part digest:

1. **Per-project summary table** — project name, sessions analysed, cost, waste, top pattern.
2. **Global patterns table** — `FindingKind`s recurring across ≥2 distinct projects, with patches targeting `~/.claude/CLAUDE.md` (the global Claude config).

The primary use case is the weekly review pass: one command instead of one `cctx autopsy <project> --since 7d` per project.

---

## 2. Design

### 2.1 CLI changes

New flag on `autopsy`:

```
--all    Aggregate across all projects in ~/.claude/projects/ (requires --since).
```

Validation:
- `--all` requires `--since`
- `--all` is mutually exclusive with a non-default `target` argument and with `--latest`
- `--html` and `--github-summary` are not supported with `--all`

When `--all` is set, `target` defaults to `None`; no path argument is accepted.

### 2.2 Pipeline (reuse, never rebuild)

```
list_projects()                       ← discovery.py, already exists
  │
  └─ for each project with sessions in window:
       aggregate.run(project_dir, start, end)   ← already exists; returns per-project pairs
         │
         └─ evidence_mod.accumulate(diagnoses)  ← already exists; per-project by_kind
              │
              └─ AggregateReport (per-project)  ← already built in current --since path
```

Per-project `AggregateReport` is built exactly as the current `--since` path builds it. No new analysis path.

### 2.3 Global pattern detection

After collecting per-project `AggregateReport`s:

```python
# Count distinct projects in which each FindingKind appeared
project_kind_counts: dict[FindingKind, int] = Counter(
    kind
    for report in per_project_reports
    for kind in report.by_kind
)
global_kinds = {k for k, n in project_kind_counts.items() if n >= 2}
```

Roll up `KindEvidence` for global kinds across all projects:

```python
global_ev: dict[FindingKind, KindEvidence] = {}
for kind in global_kinds:
    all_ev = [r.by_kind[kind] for r in per_project_reports if kind in r.by_kind]
    global_ev[kind] = KindEvidence(
        kind=kind,
        session_count=sum(e.session_count for e in all_ev),
        total_waste_usd=sum(e.total_waste_usd for e in all_ev),
        example_summaries=[s for e in all_ev for s in e.example_summaries][:3],
    )
```

Generate patches from `global_ev`, then override `target_file` to `~/.claude/CLAUDE.md`:

```python
import dataclasses
global_patches = claude_md.generate_from_evidence(global_ev)
global_patches = [dataclasses.replace(p, target_file="~/.claude/CLAUDE.md") for p in global_patches]
```

### 2.4 Data model — new types in `models.py`

```python
@dataclass
class ProjectDigestRow:
    display_name: str
    sessions_analysed: int
    sessions_with_findings: int
    total_cost_usd: float
    waste_cost_usd: float
    top_pattern: str | None  # KIND_LABEL of most frequent FindingKind, or None

@dataclass
class CrossProjectDigest:
    period_label: str
    projects: list[ProjectDigestRow]
    total_cost_usd: float
    total_waste_usd: float
    global_patches: list[Patch]
    global_by_kind: dict[FindingKind, KindEvidence]
```

`CrossProjectDigest` is not a subtype of `AggregateReport`. It holds the per-project rows and the rolled-up global evidence, but delegates per-project detail to the existing `AggregateReport`.

### 2.5 Renderer — `render_cross_project_digest()`

New function in `renderers/terminal.py`:

```
cctx autopsy — cross-project digest  (last 7 days)
───────────────────────────────────────────────────
Projects: 4 analysed | Total: $3.24 | Waste: $0.71
```

**Per-project table:**

| Project              | Sessions | Cost   | Waste  | Top pattern     |
|----------------------|----------|--------|--------|-----------------|
| ~/Projects/cctx      | 12       | $1.80  | $0.31  | STALE CONTEXT   |
| ~/Projects/api       | 5        | $0.98  | $0.22  | RETRY LOOP      |
| ~/Projects/frontend  | 3        | $0.46  | $0.18  | TOOL THRASH     |

**Global patterns (2+ projects):**

| Pattern         | Projects | Sessions | Waste   |
|-----------------|----------|----------|---------|
| STALE CONTEXT   | 3        | 17       | $0.53   |

Then patches under `Recommended ~/.claude/CLAUDE.md patches`.

If no global patterns, print "No cross-project patterns in this window." and skip the second table and patches.

### 2.6 JSON output (`--json`)

New function `export_cross_project_digest()` in `exporters/jsonl.py`:

```json
{
  "period_label": "last 7 days",
  "total_cost_usd": 3.24,
  "total_waste_usd": 0.71,
  "projects": [
    {
      "display_name": "~/Projects/cctx",
      "sessions_analysed": 12,
      "sessions_with_findings": 8,
      "total_cost_usd": 1.80,
      "waste_cost_usd": 0.31,
      "top_pattern": "STALE CONTEXT"
    }
  ],
  "global_by_kind": {
    "stale_context": {
      "project_count": 3,
      "session_count": 17,
      "total_waste_usd": 0.53
    }
  },
  "global_patches": [
    {
      "target_file": "~/.claude/CLAUDE.md",
      "finding_kind": "stale_context",
      "description": "Add context hygiene rule",
      "evidence_summary": "..."
    }
  ]
}
```

---

## 3. Edge cases

- **No sessions in window for a project:** skip that project (0-session rows omitted from table)
- **All projects empty in window:** emit "No sessions found in this window across all projects."
- **Single project with matches:** per-project table has 1 row; global patterns section absent (need ≥2)
- **`CCTX_PROJECTS_DIR` env var:** `list_projects()` already honors it; no special handling needed

---

## 4. Implementation plan

### New files
- `tests/test_cross_project_digest.py`

### Modified files
- `cctx/models.py` — add `ProjectDigestRow`, `CrossProjectDigest`
- `cctx/cli.py` — add `--all` flag, `--all` execution path in `autopsy`
- `cctx/renderers/terminal.py` — add `render_cross_project_digest()`
- `cctx/exporters/jsonl.py` — add `export_cross_project_digest()`

### Test coverage
- Multi-project fixture tree (via `CCTX_PROJECTS_DIR` + `tmp_path`)
- Global pattern fires when same kind in ≥2 projects
- No global pattern when each kind appears in only 1 project
- Empty window → empty digest
- `--all` without `--since` raises `UsageError`
- `--json` serializes `CrossProjectDigest`

---

## 5. Out of scope (v1)

- Per-project drill-down in `--all` mode (still available via separate `--since` invocation)
- Interactive drilldown prompt in `--all` mode
- `--top N` filter on global patterns
- Project-specific pattern aggregation across projects
