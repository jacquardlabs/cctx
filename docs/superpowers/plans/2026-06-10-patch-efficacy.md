# Patch Efficacy Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `cctx harvest <project> --efficacy` to measure whether applied CLAUDE.md patches actually reduced the patterns they were meant to fix, by comparing pattern recurrence before vs. after each patch was git-committed.

**Architecture:** No new module — three existing seams compose cleanly. `harvest.py` recovers patch introduction dates via `git log -S` (pure file+subprocess, no analyzer imports). `recommender/evidence.py` buckets session diagnoses into before/after windows. `renderers/terminal.py` classifies and renders the table. `cli.py` orchestrates with the existing `aggregate.run()` as the session loader.

**Tech Stack:** Python 3.10+, rich, click, subprocess (stdlib), pytest + tmp_path fixtures.

**Spec:** `docs/superpowers/specs/2026-06-10-patch-efficacy.md`

---

## File map

| File | Change |
|---|---|
| `cctx/models.py` | Add `EfficacyRow`, `EfficacyReport` dataclasses (after `AggregateReport`, ~line 298) |
| `cctx/harvest.py` | Add `managed_heading_dates(target_dir)` to public API (~after line 277) |
| `cctx/recommender/evidence.py` | Add `efficacy(pairs, heading_dates)` |
| `cctx/renderers/terminal.py` | Add `render_efficacy_report(report, target_dir, project_dir)` |
| `cctx/cli.py` | Add `--efficacy` flag + branch to `harvest` command (~line 531) |
| `tests/test_efficacy.py` | New test file |

---

### Task A: Data models

**Files:**
- Modify: `cctx/models.py` (after `AggregateReport`, before `group_into_exchanges`)
- Test: `tests/test_efficacy.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_efficacy.py`:

```python
"""Tests for patch efficacy report (M17 #90)."""
from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc
_TS = datetime(2026, 5, 1, tzinfo=UTC)


def test_efficacy_row_exists():
    from cctx.models import EfficacyRow
    from cctx.models import FindingKind
    row = EfficacyRow(
        heading="## Retry discipline",
        kind=FindingKind.RETRY_LOOP,
        applied_at=_TS,
        sessions_before=5,
        sessions_after=0,
        total_before=12,
        total_after=11,
        weeks_before=3.0,
        weeks_after=3.0,
    )
    assert row.sessions_before == 5
    assert row.applied_at == _TS


def test_efficacy_report_exists():
    from cctx.models import EfficacyReport
    report = EfficacyReport(rows=[], total_sessions=0, oldest_session=None, newest_session=None)
    assert report.rows == []
    assert report.total_sessions == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_efficacy.py -v
```

Expected: `ImportError: cannot import name 'EfficacyRow' from 'cctx.models'`

- [ ] **Step 3: Add dataclasses to `cctx/models.py`**

Find the end of `AggregateReport` (around line 298) and the start of `# Renderer helper` comment (around line 302). Insert the new dataclasses between them:

```python
@dataclass
class EfficacyRow:
    """One row in a patch efficacy report — before/after session counts for a managed heading."""

    heading: str                  # e.g. "## Retry discipline"
    kind: FindingKind | None      # reverse lookup from MANAGED_HEADINGS; None = not found
    applied_at: datetime | None   # first git commit that introduced this heading; None if unknown
    sessions_before: int          # sessions with this kind's finding before applied_at
    sessions_after: int           # sessions with this kind's finding from applied_at onward
    total_before: int             # total sessions analysed before applied_at
    total_after: int              # total sessions analysed from applied_at onward
    weeks_before: float           # (applied_at - oldest_session_start).days / 7
    weeks_after: float            # (newest_session_start - applied_at).days / 7


@dataclass
class EfficacyReport:
    """Aggregated before/after report across all managed CLAUDE.md headings."""

    rows: list[EfficacyRow]
    total_sessions: int
    oldest_session: datetime | None  # min start_time across all analysed sessions
    newest_session: datetime | None  # max start_time across all analysed sessions
```

The `EfficacyRow` fields match the spec exactly. `kind: FindingKind | None` allows `None` for
PROJECT_PATTERN headings (out of v1 scope but kept for future). The forward reference
`list[EfficacyRow]` in `EfficacyReport` works because both classes are in the same file.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_efficacy.py::test_efficacy_row_exists tests/test_efficacy.py::test_efficacy_report_exists -v
```

Expected: PASS

- [ ] **Step 5: Run full suite to check for regressions**

```bash
uv run pytest --tb=short -q
```

Expected: all tests pass (previously 498).

- [ ] **Step 6: Commit**

```bash
git add cctx/models.py tests/test_efficacy.py
git commit -m "feat: EfficacyRow + EfficacyReport dataclasses (M17 #90)"
```

---

### Task B: `harvest.managed_heading_dates`

**Files:**
- Modify: `cctx/harvest.py` (add to public API section, after `apply_patches`)
- Test: `tests/test_efficacy.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_efficacy.py`:

```python
# ---------------------------------------------------------------------------
# managed_heading_dates — Task B
# ---------------------------------------------------------------------------

def _make_git_repo_with_headings(tmp_path):
    """Create a git repo with a CLAUDE.md that has ## Retry discipline."""
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "CLAUDE.md").write_text("# Project\n\n## Retry discipline\n\nBody.\n")
    subprocess.run(["git", "add", "CLAUDE.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "add retry"], cwd=tmp_path, check=True)


def test_managed_heading_dates_returns_datetime_for_present_heading(tmp_path):
    _make_git_repo_with_headings(tmp_path)
    from cctx.harvest import managed_heading_dates
    dates = managed_heading_dates(tmp_path)
    assert "## Retry discipline" in dates
    assert dates["## Retry discipline"] is not None
    assert isinstance(dates["## Retry discipline"], datetime)


def test_managed_heading_dates_returns_none_for_absent_heading(tmp_path):
    _make_git_repo_with_headings(tmp_path)
    from cctx.harvest import managed_heading_dates
    dates = managed_heading_dates(tmp_path)
    # Headings not committed to CLAUDE.md → None
    assert dates["## Context hygiene"] is None
    assert dates["## Fan-out discipline"] is None


def test_managed_heading_dates_no_git_returns_all_none(tmp_path):
    """No git repo → all headings map to None; no exception raised."""
    (tmp_path / "CLAUDE.md").write_text("## Retry discipline\n\nBody.\n")
    from cctx.harvest import managed_heading_dates
    dates = managed_heading_dates(tmp_path)
    assert all(v is None for v in dates.values())


def test_managed_heading_dates_covers_all_managed_headings(tmp_path):
    """Return dict has a key for every heading in MANAGED_HEADINGS."""
    from cctx.harvest import managed_heading_dates
    from cctx.models import MANAGED_HEADINGS
    dates = managed_heading_dates(tmp_path)
    for heading in MANAGED_HEADINGS.values():
        assert heading in dates, f"Missing: {heading}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_efficacy.py -k "managed_heading" -v
```

Expected: `ImportError` or `AttributeError: module 'cctx.harvest' has no attribute 'managed_heading_dates'`

- [ ] **Step 3: Add `managed_heading_dates` to `cctx/harvest.py`**

Add to the top-level imports of `harvest.py` (after existing imports, before TYPE_CHECKING block):

```python
import subprocess
from datetime import datetime
```

Then after the `apply_patches` function (around line 277, before the `# harvest --check` comment block), add:

```python
def managed_heading_dates(target_dir: Path) -> dict[str, datetime | None]:
    """Return the git introduction date for each MANAGED_HEADINGS heading.

    For each heading, runs:
        git log --reverse --format="%ai" -S"<heading>" -- CLAUDE.md

    --reverse gives oldest-first; the first line is the introduction commit's date.
    -S (pickaxe) fires when the occurrence count of the literal string changes —
    correct for "when was this heading first added."

    Returns None for any heading that:
      - does not appear in CLAUDE.md's git history, or
      - target_dir has no git repo, or
      - git is not installed.
    Never raises.
    """
    result: dict[str, datetime | None] = {}
    for heading in MANAGED_HEADINGS.values():
        try:
            proc = subprocess.run(
                ["git", "log", "--reverse", "--format=%ai", f"-S{heading}", "--", "CLAUDE.md"],
                cwd=target_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = proc.stdout.strip().splitlines()
            result[heading] = datetime.fromisoformat(lines[0]) if lines else None
        except Exception:  # noqa: BLE001
            result[heading] = None
    return result
```

Note: `MANAGED_HEADINGS` is already imported at the top of `harvest.py` from `cctx.models`.
The `subprocess` and `datetime` imports need to be added.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_efficacy.py -k "managed_heading" -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add cctx/harvest.py tests/test_efficacy.py
git commit -m "feat: managed_heading_dates — git-based patch introduction dates (M17 #90)"
```

---

### Task C: `evidence.efficacy`

**Files:**
- Modify: `cctx/recommender/evidence.py`
- Test: `tests/test_efficacy.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_efficacy.py`:

```python
# ---------------------------------------------------------------------------
# evidence.efficacy — Task C
# ---------------------------------------------------------------------------

from pathlib import Path

from cctx.models import (
    Confidence,
    Diagnosis,
    Finding,
    FindingKind,
    SessionTrace,
    Severity,
    ToolResult,
    ToolUse,
    Turn,
    Usage,
)

_USAGE = Usage(100, 50, 0, 0, 0, None)

_APPLIED_AT = datetime(2026, 5, 15, tzinfo=UTC)
_BEFORE_TS  = datetime(2026, 5, 1, tzinfo=UTC)
_AFTER_TS   = datetime(2026, 5, 20, tzinfo=UTC)


def _make_trace(start_time: datetime | None) -> SessionTrace:
    return SessionTrace(
        session_id="s1",
        parent_session_id=None,
        project_path="/test",
        cwd="/test",
        primary_model="claude-sonnet-4-6",
        claude_code_version="1.0",
        turns=[],
        subagents=[],
        attachments=[],
        raw_tool_result_files=[],
        initial_context_tokens=0,
        tool_names_loaded=[],
        start_time=start_time,
        end_time=start_time,
        source_path=Path("/test/session.jsonl"),
        subagent_meta={},
        warnings=[],
        subagent_parse_errors=[],
    )


def _make_diagnosis(kind: FindingKind | None = None) -> Diagnosis:
    from datetime import datetime as dt
    findings = []
    if kind is not None:
        findings.append(Finding(
            kind=kind,
            severity=Severity.MEDIUM,
            confidence=Confidence.MEDIUM,
            first_turn=1, last_turn=2,
            evidence={},
            cost_usd=0.01,
            summary="test",
        ))
    return Diagnosis(
        session_id="s1",
        findings=findings,
        inflection_turn=None,
        patches=[],
        total_cost_usd=0.01,
        waste_cost_usd=0.0,
        analysed_at=dt(2026, 6, 10, tzinfo=UTC),
    )


def test_efficacy_splits_before_after():
    """Sessions before applied_at go in before bucket; sessions after go in after bucket."""
    from cctx.recommender.evidence import efficacy
    heading = "## Retry discipline"
    pairs = [
        (_make_diagnosis(FindingKind.RETRY_LOOP), _make_trace(_BEFORE_TS)),   # before, matches
        (_make_diagnosis(None), _make_trace(_BEFORE_TS)),                      # before, no match
        (_make_diagnosis(FindingKind.RETRY_LOOP), _make_trace(_AFTER_TS)),    # after, matches
        (_make_diagnosis(None), _make_trace(_AFTER_TS)),                       # after, no match
    ]
    heading_dates = {heading: _APPLIED_AT}
    report = efficacy(pairs, heading_dates)
    rows = {r.heading: r for r in report.rows}
    row = rows[heading]
    assert row.sessions_before == 1
    assert row.total_before == 2
    assert row.sessions_after == 1
    assert row.total_after == 2
    assert report.total_sessions == 4


def test_efficacy_applied_at_none_all_sessions_go_after():
    """When applied_at is None, all sessions with non-None start_time go to 'after'."""
    from cctx.recommender.evidence import efficacy
    heading = "## Retry discipline"
    pairs = [
        (_make_diagnosis(FindingKind.RETRY_LOOP), _make_trace(_BEFORE_TS)),
        (_make_diagnosis(None), _make_trace(_AFTER_TS)),
    ]
    report = efficacy(pairs, {heading: None})
    row = next(r for r in report.rows if r.heading == heading)
    assert row.sessions_before == 0
    assert row.total_before == 0
    assert row.sessions_after == 1   # one matches
    assert row.total_after == 2     # both are in "after"


def test_efficacy_skips_none_start_time():
    """Sessions with start_time=None are excluded from all counts."""
    from cctx.recommender.evidence import efficacy
    heading = "## Retry discipline"
    pairs = [
        (_make_diagnosis(FindingKind.RETRY_LOOP), _make_trace(None)),   # bookkeeping
        (_make_diagnosis(FindingKind.RETRY_LOOP), _make_trace(_AFTER_TS)),
    ]
    report = efficacy(pairs, {heading: _APPLIED_AT})
    assert report.total_sessions == 1   # only the one with a real start_time
    row = next(r for r in report.rows if r.heading == heading)
    assert row.sessions_after == 1
    assert row.total_after == 1


def test_efficacy_weeks_before_after():
    """weeks_before and weeks_after are computed from oldest/newest session start_time."""
    from cctx.recommender.evidence import efficacy
    heading = "## Retry discipline"
    oldest = datetime(2026, 5, 1, tzinfo=UTC)   # 14 days before applied_at
    newest = datetime(2026, 5, 29, tzinfo=UTC)  # 14 days after applied_at
    pairs = [
        (_make_diagnosis(None), _make_trace(oldest)),
        (_make_diagnosis(None), _make_trace(newest)),
    ]
    report = efficacy(pairs, {heading: _APPLIED_AT})  # applied_at = 2026-05-15
    row = next(r for r in report.rows if r.heading == heading)
    assert abs(row.weeks_before - 2.0) < 0.1   # 14 days / 7 = 2 weeks
    assert abs(row.weeks_after - 2.0) < 0.1


def test_efficacy_all_six_headings_in_report():
    """Report contains one row per managed heading."""
    from cctx.models import MANAGED_HEADINGS
    from cctx.recommender.evidence import efficacy
    heading_dates = {h: None for h in MANAGED_HEADINGS.values()}
    report = efficacy([], heading_dates)
    assert len(report.rows) == len(MANAGED_HEADINGS)
    headings_in_report = {r.heading for r in report.rows}
    assert headings_in_report == set(MANAGED_HEADINGS.values())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_efficacy.py -k "efficacy_splits or efficacy_applied or efficacy_skips or efficacy_weeks or efficacy_all_six" -v
```

Expected: `ImportError: cannot import name 'efficacy' from 'cctx.recommender.evidence'`

- [ ] **Step 3: Add `efficacy()` to `cctx/recommender/evidence.py`**

Add imports at the top of `evidence.py` (below existing imports):

```python
from datetime import datetime, timezone

from cctx.models import Diagnosis, EfficacyReport, EfficacyRow, FindingKind, KindEvidence, MANAGED_HEADINGS, SessionTrace
```

Actually the existing imports already have `Diagnosis, FindingKind, KindEvidence` — update carefully. The file currently imports:

```python
from cctx.models import Diagnosis, FindingKind, KindEvidence
```

Change to:

```python
from datetime import datetime, timezone as _UTC

from cctx.models import (
    Diagnosis,
    EfficacyReport,
    EfficacyRow,
    FindingKind,
    KindEvidence,
    MANAGED_HEADINGS,
    SessionTrace,
)
```

Then append the `efficacy` function at the bottom of `evidence.py`:

```python
_HEADING_TO_KIND: dict[str, FindingKind] = {v: k for k, v in MANAGED_HEADINGS.items()}


def efficacy(
    pairs: list[tuple[Diagnosis, SessionTrace]],
    heading_dates: dict[str, datetime | None],
) -> EfficacyReport:
    """Compute before/after session counts for each managed CLAUDE.md heading.

    For each heading in heading_dates:
      - Sessions with start_time < applied_at → "before" bucket.
      - Sessions with start_time >= applied_at → "after" bucket.
      - Sessions with start_time=None are skipped entirely.
      - If applied_at is None: all sessions go into "after" (no baseline).

    Returns an EfficacyReport with one EfficacyRow per heading.
    """
    # Collect sessions with valid start_times only
    valid_pairs = [(d, t) for d, t in pairs if t.start_time is not None]

    oldest = min((t.start_time for _, t in valid_pairs), default=None)
    newest = max((t.start_time for _, t in valid_pairs), default=None)

    rows: list[EfficacyRow] = []

    for heading, applied_at in heading_dates.items():
        kind = _HEADING_TO_KIND.get(heading)

        before_pairs = []
        after_pairs = []
        for diag, trace in valid_pairs:
            assert trace.start_time is not None  # invariant from valid_pairs filter above
            if applied_at is None or trace.start_time >= applied_at:
                after_pairs.append((diag, trace))
            else:
                before_pairs.append((diag, trace))

        def _matches(diag: Diagnosis, k: FindingKind | None) -> bool:
            if k is None:
                return False
            return any(f.kind is k for f in diag.findings)

        sessions_before = sum(1 for d, _ in before_pairs if _matches(d, kind))
        sessions_after  = sum(1 for d, _ in after_pairs  if _matches(d, kind))

        # Compute week spans
        if applied_at is not None and oldest is not None:
            weeks_before = max((applied_at - oldest).days, 0) / 7
        else:
            weeks_before = 0.0

        if applied_at is not None and newest is not None:
            weeks_after = max((newest - applied_at).days, 0) / 7
        elif newest is not None and oldest is not None:
            weeks_after = max((newest - oldest).days, 0) / 7
        else:
            weeks_after = 0.0

        rows.append(EfficacyRow(
            heading=heading,
            kind=kind,
            applied_at=applied_at,
            sessions_before=sessions_before,
            sessions_after=sessions_after,
            total_before=len(before_pairs),
            total_after=len(after_pairs),
            weeks_before=weeks_before,
            weeks_after=weeks_after,
        ))

    return EfficacyReport(
        rows=rows,
        total_sessions=len(valid_pairs),
        oldest_session=oldest,
        newest_session=newest,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_efficacy.py -k "efficacy_splits or efficacy_applied or efficacy_skips or efficacy_weeks or efficacy_all_six" -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add cctx/recommender/evidence.py tests/test_efficacy.py
git commit -m "feat: evidence.efficacy — before/after session bucketing (M17 #90)"
```

---

### Task D: `render_efficacy_report`

**Files:**
- Modify: `cctx/renderers/terminal.py`
- Test: `tests/test_efficacy.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_efficacy.py`:

```python
# ---------------------------------------------------------------------------
# render_efficacy_report — Task D
# ---------------------------------------------------------------------------

from io import StringIO
from rich.console import Console


def _make_report(rows=None, total=0, oldest=None, newest=None):
    from cctx.models import EfficacyReport
    return EfficacyReport(rows=rows or [], total_sessions=total, oldest_session=oldest, newest_session=newest)


def _make_row(
    heading="## Retry discipline",
    kind=None,
    applied_at=_APPLIED_AT,
    sb=5, sa=0, tb=12, ta=11,
    wb=3.0, wa=3.0,
):
    from cctx.models import EfficacyRow, FindingKind
    return EfficacyRow(
        heading=heading,
        kind=kind or FindingKind.RETRY_LOOP,
        applied_at=applied_at,
        sessions_before=sb, sessions_after=sa,
        total_before=tb, total_after=ta,
        weeks_before=wb, weeks_after=wa,
    )


def _console() -> Console:
    return Console(file=StringIO(), highlight=False, markup=False)


def test_render_efficacy_no_sessions(tmp_path):
    """Empty pairs → 'No sessions found' message."""
    from cctx.renderers.terminal import render_efficacy_report
    con = _console()
    render_efficacy_report(_make_report(), tmp_path, tmp_path, console=con)
    out = con.file.getvalue()
    assert "No sessions" in out


def test_render_efficacy_not_in_git(tmp_path):
    """applied_at=None → '(not in git)' in output."""
    from cctx.renderers.terminal import render_efficacy_report
    con = _console()
    row = _make_row(applied_at=None)
    report = _make_report(rows=[row], total=5)
    render_efficacy_report(report, tmp_path, tmp_path, console=con)
    out = con.file.getvalue()
    assert "not in git" in out


def test_render_efficacy_effective_signal(tmp_path):
    """rate_after == 0 with baseline → '✓ effective'."""
    from cctx.renderers.terminal import render_efficacy_report
    con = _console()
    row = _make_row(sb=5, sa=0, tb=12, ta=11, wb=3.0, wa=3.0)
    report = _make_report(rows=[row], total=23)
    render_efficacy_report(report, tmp_path, tmp_path, console=con)
    out = con.file.getvalue()
    assert "effective" in out


def test_render_efficacy_persisting_signal(tmp_path):
    """High rate_after relative to rate_before → '✗ persisting'."""
    from cctx.renderers.terminal import render_efficacy_report
    con = _console()
    row = _make_row(sb=5, sa=4, tb=8, ta=8, wb=2.0, wa=2.0)
    report = _make_report(rows=[row], total=16)
    render_efficacy_report(report, tmp_path, tmp_path, console=con)
    out = con.file.getvalue()
    assert "persisting" in out


def test_render_efficacy_no_baseline(tmp_path):
    """sessions_before == 0 with a known applied_at → '? no baseline'."""
    from cctx.renderers.terminal import render_efficacy_report
    con = _console()
    row = _make_row(sb=0, sa=3, tb=0, ta=12, wb=0.0, wa=3.0)
    report = _make_report(rows=[row], total=12)
    render_efficacy_report(report, tmp_path, tmp_path, console=con)
    out = con.file.getvalue()
    assert "no baseline" in out


def test_render_efficacy_low_sample(tmp_path):
    """total_before < 3 → '(low sample)' in output."""
    from cctx.renderers.terminal import render_efficacy_report
    con = _console()
    row = _make_row(sb=1, sa=0, tb=2, ta=5, wb=1.0, wa=3.0)
    report = _make_report(rows=[row], total=7)
    render_efficacy_report(report, tmp_path, tmp_path, console=con)
    out = con.file.getvalue()
    assert "low sample" in out
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_efficacy.py -k "render_efficacy" -v
```

Expected: `ImportError: cannot import name 'render_efficacy_report' from 'cctx.renderers.terminal'`

- [ ] **Step 3: Add `render_efficacy_report` to `cctx/renderers/terminal.py`**

At the top of `terminal.py`, the existing TYPE_CHECKING block imports `AggregateReport, Diagnosis, SessionTrace`. Add `EfficacyReport` and `EfficacyRow` to it:

```python
if TYPE_CHECKING:
    from cctx.discovery import ProjectInfo
    from cctx.models import AggregateReport, Diagnosis, EfficacyReport, EfficacyRow, SessionTrace
```

Add this function at the end of `terminal.py` (after `render_sessions`):

```python
def _efficacy_signal(row: EfficacyRow) -> str:
    """Classify efficacy: ✓ effective | ↓ reduced | ✗ persisting | ? no baseline | ? not in git."""
    if row.applied_at is None:
        return "? not in git"
    if row.sessions_before == 0:
        return "? no baseline"
    rate_before = row.sessions_before / max(row.weeks_before, 0.5)
    rate_after  = row.sessions_after  / max(row.weeks_after,  0.5)
    low = "(low sample)" if row.total_before < 3 or row.total_after < 3 else ""
    if rate_after == 0 or rate_after < rate_before * 0.25:
        return f"✓ effective{' ' + low if low else ''}"
    if rate_after < rate_before * 0.75:
        return f"↓ reduced{' ' + low if low else ''}"
    return f"✗ persisting{' ' + low if low else ''}"


def render_efficacy_report(
    report: EfficacyReport,
    target_dir: Path,
    project_dir: Path,
    *,
    console: Console | None = None,
) -> None:
    """Render patch efficacy table to terminal."""
    con = console or _default_console()

    if report.total_sessions == 0:
        con.print(f"No sessions found in {project_dir}.")
        return

    if not report.rows:
        con.print(f"No managed headings found in CLAUDE.md at {target_dir / 'CLAUDE.md'}.")
        return

    # Header
    range_str = ""
    if report.oldest_session and report.newest_session:
        oldest = report.oldest_session.strftime("%Y-%m-%d")
        newest = report.newest_session.strftime("%Y-%m-%d")
        range_str = f"   Range: {oldest} — {newest}"
    con.print(Rule("cctx harvest --efficacy"))
    con.print(f"Sessions: {report.total_sessions}{range_str}")
    con.print(f"CLAUDE.md: {target_dir / 'CLAUDE.md'}")
    con.print()

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
    table.add_column("Heading", style="bold", no_wrap=True)
    table.add_column("Applied", no_wrap=True)
    table.add_column("Before", no_wrap=True)
    table.add_column("After", no_wrap=True)
    table.add_column("Signal", no_wrap=True)

    _SIGNAL_STYLE = {
        "✓": "bold green",
        "↓": "bold yellow",
        "✗": "bold red",
        "?": "dim",
    }

    for row in report.rows:
        applied = row.applied_at.strftime("%Y-%m-%d") if row.applied_at else Text("(not in git)", style="dim")
        if row.applied_at is None:
            before_str = "—"
        else:
            before_str = f"{row.sessions_before}/{row.total_before} sessions"
        after_str = f"{row.sessions_after}/{row.total_after} sessions"
        signal = _efficacy_signal(row)
        first_char = signal[0] if signal else "?"
        signal_style = _SIGNAL_STYLE.get(first_char, "")
        table.add_row(row.heading, applied, before_str, after_str, Text(signal, style=signal_style))

    con.print(table)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_efficacy.py -k "render_efficacy" -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add cctx/renderers/terminal.py tests/test_efficacy.py
git commit -m "feat: render_efficacy_report — efficacy table renderer (M17 #90)"
```

---

### Task E: `harvest --efficacy` CLI flag

**Files:**
- Modify: `cctx/cli.py`
- Test: `tests/test_efficacy.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_efficacy.py`:

```python
# ---------------------------------------------------------------------------
# CLI integration — Task E
# ---------------------------------------------------------------------------

def test_cli_efficacy_requires_directory(tmp_path):
    """--efficacy with a .jsonl file path → usage error."""
    from click.testing import CliRunner
    from cctx.cli import cli
    session_file = tmp_path / "session.jsonl"
    session_file.write_text("{}\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["harvest", str(session_file), "--efficacy"])
    assert result.exit_code != 0
    assert "directory" in result.output.lower() or "directory" in str(result.exception).lower()


def test_cli_efficacy_empty_project(tmp_path):
    """--efficacy on a directory with no sessions → 'No sessions found'."""
    from click.testing import CliRunner
    from cctx.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, [
        "harvest", str(tmp_path), "--efficacy",
        "--target-dir", str(tmp_path),
    ])
    assert result.exit_code == 0
    assert "No sessions" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_efficacy.py -k "cli_efficacy" -v
```

Expected: tests fail with unexpected exit code or missing `--efficacy` option.

- [ ] **Step 3: Add `--efficacy` to `cctx/cli.py`**

Add the `render_efficacy_report` to the top-level imports from `cctx.renderers.terminal`:

```python
from cctx.renderers.terminal import (
    render_aggregate,
    render_aggregate_drilldown,
    render_diagnosis,
    render_efficacy_report,
    render_harvest_results,
    render_projects,
    render_sessions,
    render_turn,
)
```

Add the `--efficacy` option to the `harvest` command. It goes after the `--sync` option decoration (around line 588), before `def harvest(`:

```python
@click.option(
    "--efficacy",
    "efficacy_mode",
    is_flag=True,
    default=False,
    help="Report whether applied patches reduced their target patterns (before vs. after).",
)
```

Add `efficacy_mode: bool` to the `harvest` function signature:

```python
def harvest(
    target: Path,
    since: str | None,
    apply_mode: bool,
    dry_run: bool,
    target_dir: Path | None,
    check_mode: bool,
    check_severity: str,
    emit_targets: tuple[str, ...],
    sync_mode: bool,
    efficacy_mode: bool,
) -> None:
```

Add the efficacy branch at the top of the `harvest` function body, after the `sync_mode` guard and before the `check_mode` branch:

```python
    if efficacy_mode:
        if target.is_file():
            raise click.UsageError(
                "--efficacy requires a project directory, not a .jsonl file."
            )
        resolved_dir = target_dir or Path.cwd()
        from cctx.recommender.evidence import efficacy as _efficacy
        from cctx.harvest import managed_heading_dates
        start = datetime(2020, 1, 1, tzinfo=UTC)
        end   = datetime(2035, 1, 1, tzinfo=UTC)
        pairs = aggregate.run(target, start, end)
        h_dates = managed_heading_dates(resolved_dir)
        report  = _efficacy(pairs, h_dates)
        render_efficacy_report(report, resolved_dir, target)
        return
```

The full `harvest` function body preamble (with the new branch added first) becomes:

```python
def harvest(...) -> None:
    """Apply autopsy patches to CLAUDE.md."""
    from cctx.harvest import (
        apply_patches,
        check_claude_md,
        preview_patches,
        retarget_patches,
        sync_managed_sections,
    )

    if sync_mode and not emit_targets:
        raise click.UsageError("--sync requires --emit.")

    if efficacy_mode:
        if target.is_file():
            raise click.UsageError(
                "--efficacy requires a project directory, not a .jsonl file."
            )
        resolved_dir = target_dir or Path.cwd()
        from cctx.recommender.evidence import efficacy as _efficacy
        from cctx.harvest import managed_heading_dates
        start = datetime(2020, 1, 1, tzinfo=UTC)
        end   = datetime(2035, 1, 1, tzinfo=UTC)
        pairs = aggregate.run(target, start, end)
        h_dates = managed_heading_dates(resolved_dir)
        report  = _efficacy(pairs, h_dates)
        render_efficacy_report(report, resolved_dir, target)
        return

    if check_mode:
        ...  # existing code unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_efficacy.py -k "cli_efficacy" -v
```

Expected: both CLI tests PASS.

- [ ] **Step 5: Run the complete test suite**

```bash
uv run pytest --tb=short -q
```

Expected: all tests pass (no regressions).

- [ ] **Step 6: Run ruff lint**

```bash
uv run ruff check cctx/cli.py cctx/renderers/terminal.py cctx/recommender/evidence.py cctx/harvest.py cctx/models.py tests/test_efficacy.py
```

Fix any issues. Common ones:
- `E501` (line too long) — break long lines
- `I001` (import order) — run `uv run ruff check --fix`
- `F401` (unused import) — remove

- [ ] **Step 7: Commit**

```bash
git add cctx/cli.py tests/test_efficacy.py
git commit -m "feat: harvest --efficacy CLI flag (M17 #90)"
```

---

## Final check

- [ ] Run `uv run pytest --tb=short -q` — all tests pass
- [ ] Run `uv run ruff check cctx/ tests/` — no lint errors
- [ ] Manually verify the table renders on a real project:

```bash
uv run cctx harvest ~/.claude/projects/<your-project> --efficacy --target-dir .
```

Expected: a table showing "No sessions found" (if no sessions) OR a populated efficacy table
with before/after counts and signal column.
