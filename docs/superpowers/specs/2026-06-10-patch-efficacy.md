# Patch Efficacy Report — M17 #90

**Issue:** #90
**Date:** 2026-06-10
**Status:** Ready for implementation

---

## Goal

Close the harvest loop by measuring whether applied patches actually reduced the
patterns they were meant to fix. `cctx harvest <project> --efficacy` compares
pattern recurrence before vs. after each managed heading was introduced into
CLAUDE.md, producing a table like:

```
Patch Efficacy Report
Sessions: 23   Range: 2026-04-01 — 2026-06-10

Heading                   Applied     Before          After           Signal
─────────────────────────────────────────────────────────────────────────────
## Retry discipline        2026-05-20  5/12 sessions   0/11 sessions  ✓ effective
## Context hygiene         2026-05-22  3/10 sessions   1/13 sessions  ↓ reduced
## Scope discipline        2026-05-24  1/8 sessions    2/15 sessions  ✗ persisting
## Fan-out discipline      (not in git) —              3/23 sessions  ? no baseline
```

---

## Module layout

No new module. Three existing seams compose cleanly:

| Module | New responsibility |
|---|---|
| `cctx/harvest.py` | `managed_heading_dates(target_dir) -> dict[str, datetime \| None]` — git-based; no analyzer imports |
| `cctx/recommender/evidence.py` | `efficacy(pairs, heading_dates) -> EfficacyReport` — before/after bucketing |
| `cctx/renderers/terminal.py` | `render_efficacy_report(report, target_dir, project_dir)` |
| `cctx/cli.py` | `--efficacy` flag on `harvest` command |
| `cctx/models.py` | `EfficacyRow`, `EfficacyReport` dataclasses |

This matches the issue's Files list exactly and follows "prefer reuse over creation."

---

## Data model (`cctx/models.py`)

```python
@dataclass
class EfficacyRow:
    heading: str                  # e.g. "## Retry discipline"
    kind: FindingKind | None      # reverse lookup from MANAGED_HEADINGS; None = unknown
    applied_at: datetime | None   # first git commit that introduced this heading; None if not found
    sessions_before: int          # sessions with this kind's finding before applied_at
    sessions_after: int           # sessions with this kind's finding from applied_at onward
    total_before: int             # total sessions analysed before applied_at
    total_after: int              # total sessions analysed from applied_at onward
    weeks_before: float           # (applied_at - oldest_session_start).days / 7
    weeks_after: float            # (newest_session_start - applied_at).days / 7

@dataclass
class EfficacyReport:
    rows: list[EfficacyRow]
    total_sessions: int
    oldest_session: datetime | None  # min start_time across all analysed sessions
    newest_session: datetime | None  # max start_time across all analysed sessions
```

`EfficacyRow` and `EfficacyReport` follow the same pure-data pattern as every
other model in this file. No behavior, no imports.

---

## Git-based heading date recovery (`cctx/harvest.py`)

### `managed_heading_dates(target_dir: Path) -> dict[str, datetime | None]`

For every heading in `MANAGED_HEADINGS.values()`, runs:

```bash
git -C <target_dir> log --reverse --format="%ai" -S"<heading>" -- CLAUDE.md
```

- `--reverse`: returns commits oldest-first — the first line is the introduction date.
- `-S"<heading>"` (pickaxe): fires when the occurrence count of the literal string changes
  (add or delete), which is correct for tracking introduction. Safe for all current headings
  (no special regex chars). PROJECT_PATTERN headings are out of scope for v1 (see below).
- `--format="%ai"`: author date, ISO 8601 with timezone offset (`2026-05-20 14:31:00 -0500`).
  Parseable by `datetime.fromisoformat()` in Python 3.11+ (and 3.10 with the `-05:00` form —
  empirically verified: the output uses `-05:00`-style offsets which fromisoformat handles).

Returns `None` for a heading if:
- `target_dir` has no git history, or
- git is not installed, or
- the heading does not appear in any commit on the CLAUDE.md file.

Never raises. All git failures → `None` for that heading.

**Empirically validated** (see `/tmp/cctx_git_test`): the command correctly returns the
introduction commit's date, including the case where a heading is deleted and re-added
(`--reverse | head -1` yields the original add date, not the re-add date).

---

## Before/after computation (`cctx/recommender/evidence.py`)

### `efficacy(pairs: list[tuple[Diagnosis, SessionTrace]], heading_dates: dict[str, datetime | None]) -> EfficacyReport`

**Session bucketing** — for each managed heading:

1. Build reverse map: `kind -> heading` from `MANAGED_HEADINGS`.
2. For each `(diagnosis, trace)` pair:
   - Skip if `trace.start_time is None` (bookkeeping-only sessions).
   - The session belongs to "before" if `trace.start_time < heading_date`.
   - The session belongs to "after" if `trace.start_time >= heading_date`.
   - A session "matches" the heading's kind if `diagnosis.findings` contains at least one
     finding of that kind.
3. Compute `weeks_before` and `weeks_after`:
   - `weeks_before = max((applied_at - oldest_start).days, 0) / 7`
   - `weeks_after = max((newest_start - applied_at).days, 0) / 7`
   - `oldest_start` / `newest_start` drawn from sessions with non-None `start_time`.
   - If no sessions have non-None `start_time`, both are 0.0.
4. If `applied_at is None`: `sessions_before = 0`, `total_before = 0`, `weeks_before = 0.0`;
   all sessions go into the "after" bucket.

**Signal logic** is computed in the renderer (not in `evidence.py`). `evidence.py` only
produces raw counts.

**v1 scope**: only the six kinds in `MANAGED_HEADINGS`. PROJECT_PATTERN headings are skipped
because there is no single `FindingKind` to count recurrences for; they require a different
attribution strategy.

---

## Signal classification (renderer)

Computed in `render_efficacy_report`, not in the model or evidence module:

```
rate_before = sessions_before / max(weeks_before, 0.5)
rate_after  = sessions_after  / max(weeks_after, 0.5)

"✓ effective"   if sessions_before > 0 AND (rate_after == 0 OR rate_after < rate_before * 0.25)
"↓ reduced"     if sessions_before > 0 AND rate_before * 0.25 <= rate_after < rate_before * 0.75
"✗ persisting"  if sessions_before > 0 AND rate_after >= rate_before * 0.75
"? no baseline" if sessions_before == 0 AND applied_at is not None
"? not in git"  if applied_at is None
```

Rows where `total_before < 3` or `total_after < 3` are labeled `(low sample)` in the
Signal column — e.g. `✓ effective (low sample)`. This is the "honest about confidence"
requirement from acceptance criterion 3.

The `max(weeks, 0.5)` floor prevents divide-by-zero without fabricating high rates;
the minimum meaningful window is half a week. Label the column header "Approx. rate/wk"
to convey the approximation honestly.

---

## CLI surface

```
harvest <target> --efficacy [--target-dir <dir>]
```

- `--efficacy`: new boolean flag. Mutually exclusive with `--check`.
- `target`: the project sessions directory (same constraint as `--since` mode: must be a
  directory). Error with clear message if `target.is_file()`.
- `--target-dir`: directory containing CLAUDE.md (and the git repo to query). Defaults to
  `cwd`. This is the **existing** `--target-dir` option — no new option needed.
- Does NOT run `--apply` or patch generation; purely reporting. Exits 0 after printing the
  table (even if some patterns persist).

Implementation in `cli.py`:
```python
if efficacy_mode:
    if target.is_file():
        raise click.UsageError("--efficacy requires a project directory, not a .jsonl file.")
    resolved_dir = target_dir or Path.cwd()
    from cctx.recommender.evidence import efficacy as run_efficacy
    from cctx.harvest import managed_heading_dates
    from cctx.renderers.terminal import render_efficacy_report
    start = datetime(2020, 1, 1, tzinfo=UTC)
    end   = datetime(2035, 1, 1, tzinfo=UTC)
    pairs = aggregate.run(target, start, end)
    h_dates = managed_heading_dates(resolved_dir)
    report  = run_efficacy(pairs, h_dates)
    render_efficacy_report(report, resolved_dir, target)
    return
```

---

## Rendering (`cctx/renderers/terminal.py`)

### `render_efficacy_report(report, target_dir, project_dir)`

Rich table:

```
  cctx harvest --efficacy
  Sessions: 23   Range: 2026-04-01 — 2026-06-10
  CLAUDE.md: /path/to/target/CLAUDE.md

  Heading                   Applied      Before           After            Signal
  ─────────────────────────────────────────────────────────────────────────────────
  ## Retry discipline        2026-05-20   5/12 sessions    0/11 sessions   ✓ effective
  ## Context hygiene         2026-05-22   3/10 sessions    1/13 sessions   ↓ reduced
  ## Scope discipline        2026-05-24   1/8 sessions     2/15 sessions   ✗ persisting
  ## Tool-call discipline    2026-05-24   0/8 sessions     0/15 sessions   ? no baseline
  ## Fan-out discipline      (not in git) —                3/23 sessions   ? not in git
```

- Heading column: dim the `## ` prefix, bold the heading name.
- Applied column: `(not in git)` in dim style when `applied_at is None`.
- Before/After columns: `{matching}/{total} sessions` format. Show `—` for Before when
  `applied_at is None`.
- Signal column: color-coded — green ✓, yellow ↓, red ✗, dim ?.
- If `report.rows` is empty: print "No managed headings found in CLAUDE.md at <path>."
- If `total_sessions == 0`: print "No sessions found in <project_dir>."

---

## Layering

| Rule | Respected? |
|---|---|
| `harvest.py` does not import diagnostician/recommender | ✓ — uses only subprocess + MANAGED_HEADINGS |
| `evidence.py` does not import harvest | ✓ — receives pre-computed `heading_dates` dict from CLI |
| Renderers do not compute analysis | ✓ — signal logic is in renderer (presentation, not analysis) |
| Only `cli.py` imports click | ✓ |
| Only `tokenizer.py` imports anthropic | ✓ |

---

## Testing (`tests/test_efficacy.py`)

| Test | What it asserts |
|---|---|
| `test_efficacy_all_before` | Sessions all before applied_at → sessions_before=N, sessions_after=0 |
| `test_efficacy_all_after` | applied_at=None → sessions_before=0, total_before=0 |
| `test_efficacy_split` | Mix of before/after sessions correctly bucketed |
| `test_efficacy_no_matching_findings` | Sessions exist but none have matching kind → 0/N |
| `test_efficacy_skips_none_start_time` | Sessions with start_time=None excluded from counts |
| `test_efficacy_report_total_sessions` | total_sessions = count of sessions with non-None start_time |
| `test_managed_heading_dates_no_git` | No git repo in target_dir → all None values, no exception |
| `test_render_efficacy_no_sessions` | Empty pairs → "No sessions found" message |
| `test_render_efficacy_not_in_git` | applied_at=None → "(not in git)" and "? not in git" signal |

---

## Out of scope (v1)

- PROJECT_PATTERN headings (fuzzy attribution; filed as follow-on)
- `--format json` export of efficacy report
- Week-over-week trend charts
- Efficacy report inside `autopsy --since` output (could be a later addition)

---

## Files touched

| File | Change |
|---|---|
| `cctx/models.py` | Add `EfficacyRow`, `EfficacyReport` dataclasses |
| `cctx/harvest.py` | Add `managed_heading_dates(target_dir) -> dict[str, datetime \| None]` |
| `cctx/recommender/evidence.py` | Add `efficacy(pairs, heading_dates) -> EfficacyReport` |
| `cctx/renderers/terminal.py` | Add `render_efficacy_report(report, target_dir, project_dir)` |
| `cctx/cli.py` | Add `--efficacy` flag to `harvest` command |
| `tests/test_efficacy.py` | New test file |
