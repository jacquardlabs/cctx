# Harvest --check Depth Design

**Goal:** Extend `cctx harvest --check` beyond dead references and empty sections to catch contradictory rules, redundant rules, and stale function/class name references.

**Architecture:** Three new detection functions added to `cctx/harvest.py`, all called from the existing `check_claude_md()` entry point. `CheckFinding` gains a `severity` field. CLI gains `--check-severity` threshold flag.

**Tech Stack:** Pure stdlib — `re`, `pathlib`, `subprocess` for grepping. No LLM calls. No new dependencies.

---

## Motivation

The current `harvest --check` catches structural problems (dead file paths, empty sections). It misses semantic problems: two rules telling Claude to do opposite things, two rules that say the same thing in different words, and rules referencing functions that no longer exist in the codebase. These are the issues that erode CLAUDE.md quality over time.

---

## Data model changes

### `CheckSeverity` enum (new, in `harvest.py`)

```python
class CheckSeverity(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"
```

Defined locally in `harvest.py` — no runtime import from `models.py` needed.

### Updated `CheckFinding`

```python
@dataclass
class CheckFinding:
    heading:  str            # ## section where this was found
    issue:    CheckIssue
    severity: CheckSeverity  # NEW
    detail:   str
```

### Updated `CheckIssue`

Three new values:

```python
CONTRADICTION    = "contradiction"    # two rules give conflicting directives
REDUNDANCY       = "redundancy"       # two rules say the same thing
STALE_IDENTIFIER = "stale_identifier" # backtick-quoted function no longer in codebase
```

### Severity assignments

| CheckIssue | Severity |
|---|---|
| `DEAD_FILE_REF` | MEDIUM |
| `DEAD_SKILL_REF` | MEDIUM |
| `EMPTY_SECTION` | MEDIUM |
| `CONTRADICTION` | HIGH |
| `REDUNDANCY` | MEDIUM |
| `STALE_IDENTIFIER` | LOW |

---

## Detection algorithms

### `check_contradictions(sections: list[tuple[str, str]]) -> list[CheckFinding]`

Scans each section body for sentences/bullets containing the words `always` or `never` (case-insensitive). Extracts the next non-stopword token after the keyword as the **subject** (e.g., "Always use tabs" → subject `tabs`; "Never use tabs" → subject `tabs`).

Stopwords excluded from subject extraction: `a`, `an`, `the`, `to`, `be`, `is`, `are`, `was`, `were`, `in`, `on`, `at`, `of`, `for`, `with`, `and`, `or`, `not`, `it`, `this`, `that`, `you`, `your`.

Builds `subject → list[(polarity, heading)]` where polarity is `"always"` or `"never"`. Any subject that appears under both polarities across any section pair is a contradiction. Reports both headings in `detail`.

Returns `CheckFinding` with `severity=HIGH`.

### `check_redundancy(sections: list[tuple[str, str]]) -> list[CheckFinding]`

For each pair of sections, computes **Jaccard similarity** on word sets:

```
J(A, B) = |A ∩ B| / |A ∪ B|
```

Where words are lowercased, stripped of punctuation, and filtered to remove stopwords (same list as above). Pairs with J ≥ 0.8 are flagged as `REDUNDANCY`. Reports both headings and the score in `detail` (e.g., `"## Retry discipline" and "## Failure handling" are 83% similar`).

O(n²) over sections — safe in practice since CLAUDE.md rarely exceeds 30 sections. Only section bodies with ≥ 5 words are eligible (avoids false positives on short sections).

Returns `CheckFinding` with `severity=MEDIUM`. The finding `heading` is the first section of the pair.

### `check_staleness(sections: list[tuple[str, str]], project_dir: Path) -> list[CheckFinding]`

Scans each section body for backtick-quoted tokens matching:
- Ends with `()`
- Stripped name is ≥ 8 characters (e.g., `tokenize_session()` qualifies; `run()` does not)
- Does not contain `/` or `.` (those are file paths, already handled)

For each qualifying identifier, strips the `()` suffix and searches for that string using `pathlib.glob` + file reading (avoids subprocess portability issues):

```python
source_files = (
    list(project_dir.rglob("*.py")) +
    list(project_dir.rglob("*.ts")) +
    list(project_dir.rglob("*.js"))
)
# Exclude common non-project trees
source_files = [
    f for f in source_files
    if not any(part in {".git", ".venv", "node_modules", "__pycache__"}
               for part in f.parts)
]
```

If `source_files` is empty (project has no Python/TS/JS files), **skip staleness checking entirely** — no source to search means every identifier would false-positive.

If `source_files` is non-empty but the identifier string is not found in any file's text, flags as `STALE_IDENTIFIER`.

Returns `CheckFinding` with `severity=LOW`.

---

## `check_claude_md` changes

Calls all four checks in sequence:

```python
def check_claude_md(target_dir: Path) -> list[CheckFinding]:
    ...
    sections = _parse_sections(content)
    findings: list[CheckFinding] = []
    findings += _check_structure(sections)          # existing: dead refs, empty sections
    findings += check_contradictions(sections)
    findings += check_redundancy(sections)
    findings += check_staleness(sections, target_dir)
    return findings
```

All existing findings get `severity=CheckSeverity.MEDIUM` added.

---

## CLI changes

### `harvest --check-severity` flag (new)

```
--check-severity [LOW|MEDIUM|HIGH]   Minimum severity that triggers exit 1 (default: MEDIUM)
```

Exit code logic:

```python
threshold = CheckSeverity(check_severity.lower())
_SEVERITY_ORDER = {CheckSeverity.LOW: 0, CheckSeverity.MEDIUM: 1, CheckSeverity.HIGH: 2}
triggering = [f for f in findings if _SEVERITY_ORDER[f.severity] >= _SEVERITY_ORDER[threshold]]
raise SystemExit(1 if triggering else 0)
```

All findings are **rendered regardless of threshold** — the threshold only controls exit code.

### `_render_check_findings` changes

Adds a severity badge to each finding line:

```
[HIGH]  ## Retry discipline  contradiction: "tabs" is "always" here and "never" in ## Formatting
[MED]   ## Dead ref          file not found: 'src/styles/theme.py'
[LOW]   ## Guide             stale identifier: deleted_helper() not found in project
```

`_ISSUE_LABEL` dict in `cli.py` extended with three new entries.

---

## Files changed

| File | Change |
|------|--------|
| `cctx/harvest.py` | Add `CheckSeverity`, update `CheckFinding`, add `CONTRADICTION`/`REDUNDANCY`/`STALE_IDENTIFIER` to `CheckIssue`, add `check_contradictions()`, `check_redundancy()`, `check_staleness()`, update `check_claude_md()` to call all and assign severities |
| `cctx/cli.py` | Add `--check-severity` flag, update exit code logic, update `_render_check_findings` with severity badges and new issue labels |
| `tests/test_harvest_check.py` | New tests for contradiction, redundancy, staleness, and severity threshold behaviour |

---

## Testing strategy

All tests use `tmp_path` inline strings — no fixture files needed.

**Contradiction:**
- "Always use tabs" in one section + "Never use tabs" in another → `CONTRADICTION` HIGH
- Two sections with non-overlapping always/never subjects → no finding

**Redundancy:**
- Two sections with nearly identical text → `REDUNDANCY` MEDIUM
- Two sections with clearly different content → no finding
- Section with < 5 words → not eligible

**Staleness:**
- `` `tokenize_session()` `` with that identifier in a project `.py` file → no finding
- `` `deleted_helper()` `` with no match → `STALE_IDENTIFIER` LOW
- `` `run()` `` (7 chars stripped) → not eligible (< 8 chars)
- `` `src/foo.py` `` (contains `/`) → not eligible (file path)

**Severity / exit code:**
- `--check-severity HIGH` + only MEDIUM findings → exit 0
- `--check-severity LOW` + any finding → exit 1
- Default (`MEDIUM`) + HIGH finding → exit 1

---

## Non-goals (v1)

- No LLM-assisted semantic contradiction or redundancy detection
- No cross-file checking (only `CLAUDE.md`, not `rules/` or `skills/`)
- No auto-fix suggestions for redundant sections
