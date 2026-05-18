# Harvest --check Depth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `cctx harvest --check` with three new detectors — contradiction, redundancy, and stale identifier — each with an explicit severity level, and expose a `--check-severity` CLI flag to control the exit-1 threshold.

**Architecture:** All detection logic lives in `cctx/harvest.py`. A new `CheckSeverity` enum is added; `CheckFinding` gains a `severity` field; `check_claude_md` is refactored to call four sub-functions. The CLI gains `--check-severity` and renders severity badges.

**Tech Stack:** Pure stdlib — `re`, `pathlib`. No new dependencies.

---

## File map

| File | What changes |
|------|-------------|
| `cctx/harvest.py` | Add `CheckSeverity`; update `CheckFinding` + `CheckIssue`; add `_words()`, `_STOPWORDS`, `_FUNC_REF_RE`; add `check_contradictions()`, `check_redundancy()`, `check_staleness()`; refactor existing loop into `_check_structure()`; update `check_claude_md()` |
| `cctx/cli.py` | Add `--check-severity` option; update `harvest()` signature + check-mode block; update `_render_check_findings()` |
| `tests/test_harvest_check.py` | Add tests for each new detector and severity/exit-code behaviour |

---

## Task 1: Data model — CheckSeverity, updated CheckFinding, new CheckIssue values

**Files:**
- Modify: `cctx/harvest.py:30-42`
- Test: `tests/test_harvest_check.py`

- [ ] **Step 1: Write failing tests for the new model**

Add to `tests/test_harvest_check.py`:

```python
def test_check_severity_enum_exists():
    from cctx.harvest import CheckSeverity
    assert CheckSeverity.LOW.value == "low"
    assert CheckSeverity.MEDIUM.value == "medium"
    assert CheckSeverity.HIGH.value == "high"


def test_check_issue_has_new_values():
    from cctx.harvest import CheckIssue
    assert CheckIssue.CONTRADICTION.value == "contradiction"
    assert CheckIssue.REDUNDANCY.value == "redundancy"
    assert CheckIssue.STALE_IDENTIFIER.value == "stale_identifier"


def test_check_finding_has_severity():
    from cctx.harvest import CheckFinding, CheckIssue, CheckSeverity
    f = CheckFinding(
        heading="## Test",
        issue=CheckIssue.EMPTY_SECTION,
        severity=CheckSeverity.MEDIUM,
        detail="no content",
    )
    assert f.severity is CheckSeverity.MEDIUM


def test_existing_checks_have_medium_severity(tmp_path):
    from cctx.harvest import CheckSeverity, check_claude_md
    (tmp_path / "CLAUDE.md").write_text(
        "## Dead ref\n\nSee `missing/module.py`.\n"
    )
    findings = check_claude_md(tmp_path)
    assert findings
    assert all(f.severity is CheckSeverity.MEDIUM for f in findings)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_harvest_check.py::test_check_severity_enum_exists \
    tests/test_harvest_check.py::test_check_issue_has_new_values \
    tests/test_harvest_check.py::test_check_finding_has_severity \
    tests/test_harvest_check.py::test_existing_checks_have_medium_severity -v
```

Expected: 4 FAILED (ImportError or AttributeError)

- [ ] **Step 3: Implement data model changes in `cctx/harvest.py`**

Replace the existing `CheckIssue` and `CheckFinding` block (lines 31–41) with:

```python
class CheckSeverity(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class CheckIssue(str, Enum):
    DEAD_FILE_REF    = "dead_file_ref"
    DEAD_SKILL_REF   = "dead_skill_ref"
    EMPTY_SECTION    = "empty_section"
    CONTRADICTION    = "contradiction"
    REDUNDANCY       = "redundancy"
    STALE_IDENTIFIER = "stale_identifier"


@dataclass
class CheckFinding:
    heading:  str
    issue:    CheckIssue
    severity: CheckSeverity
    detail:   str
```

Then update every `CheckFinding(...)` construction site inside `check_claude_md` to add `severity=CheckSeverity.MEDIUM`. There are three:

```python
# Empty section
findings.append(CheckFinding(
    heading=heading,
    issue=CheckIssue.EMPTY_SECTION,
    severity=CheckSeverity.MEDIUM,
    detail=f"{heading!r} has no content",
))

# Dead skill ref
findings.append(CheckFinding(
    heading=heading,
    issue=CheckIssue.DEAD_SKILL_REF,
    severity=CheckSeverity.MEDIUM,
    detail=f"skill not found: {match.group(1)!r}",
))

# Dead file ref
findings.append(CheckFinding(
    heading=heading,
    issue=CheckIssue.DEAD_FILE_REF,
    severity=CheckSeverity.MEDIUM,
    detail=f"file not found: {token!r}",
))
```

- [ ] **Step 4: Run all harvest check tests**

```bash
uv run pytest tests/test_harvest_check.py -v
```

Expected: All tests PASS (both old and new).

- [ ] **Step 5: Commit**

```bash
git add cctx/harvest.py tests/test_harvest_check.py
git commit -m "feat: CheckSeverity enum, severity field on CheckFinding, new CheckIssue values"
```

---

## Task 2: `check_contradictions()` detector

**Files:**
- Modify: `cctx/harvest.py` — add after `_parse_sections()`
- Test: `tests/test_harvest_check.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_harvest_check.py`:

```python
def test_contradiction_detected_across_sections():
    from cctx.harvest import CheckIssue, check_contradictions
    sections = [
        ("## Formatting", "Always use tabs for indentation."),
        ("## Style", "Never use tabs, use spaces instead."),
    ]
    findings = check_contradictions(sections)
    assert len(findings) == 1
    assert findings[0].issue is CheckIssue.CONTRADICTION


def test_no_contradiction_same_polarity():
    from cctx.harvest import check_contradictions
    sections = [
        ("## A", "Always use tabs."),
        ("## B", "Always use spaces."),
    ]
    # Both say "always" — no contradiction
    assert check_contradictions(sections) == []


def test_no_contradiction_different_subjects():
    from cctx.harvest import check_contradictions
    sections = [
        ("## A", "Always use tabs."),
        ("## B", "Never import numpy."),
    ]
    assert check_contradictions(sections) == []


def test_contradiction_severity_is_high():
    from cctx.harvest import CheckSeverity, check_contradictions
    sections = [
        ("## A", "Always use tabs."),
        ("## B", "Never use tabs."),
    ]
    findings = check_contradictions(sections)
    assert findings[0].severity is CheckSeverity.HIGH
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_harvest_check.py::test_contradiction_detected_across_sections \
    tests/test_harvest_check.py::test_no_contradiction_same_polarity \
    tests/test_harvest_check.py::test_no_contradiction_different_subjects \
    tests/test_harvest_check.py::test_contradiction_severity_is_high -v
```

Expected: 4 FAILED (ImportError: cannot import name `check_contradictions`)

- [ ] **Step 3: Implement shared helpers and `check_contradictions` in `harvest.py`**

Add after the `_KNOWN_EXTENSIONS` set and before `_parse_sections`:

```python
_STOPWORDS = {
    "a", "an", "the", "to", "be", "is", "are", "was", "were",
    "in", "on", "at", "of", "for", "with", "and", "or", "not",
    "it", "this", "that", "you", "your", "use", "do",
}

_ALWAYS_NEVER_RE = re.compile(
    r"\b(always|never)\b(.+?)(?:[.!?\n]|$)", re.IGNORECASE
)

_FUNC_REF_RE = re.compile(r"`([^`/.\s]+)\(\)`")


def _words(text: str) -> set[str]:
    tokens = re.findall(r"\b[a-zA-Z_]\w*\b", text.lower())
    return {t for t in tokens if t not in _STOPWORDS}
```

Then add `check_contradictions` after `_parse_sections`:

```python
def check_contradictions(
    sections: list[tuple[str, str]],
) -> list[CheckFinding]:
    from collections import defaultdict
    subject_map: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for heading, body in sections:
        for match in _ALWAYS_NEVER_RE.finditer(body):
            polarity = match.group(1).lower()
            clause = match.group(2)
            for word in _words(clause):
                subject_map[word].append((polarity, heading))

    findings: list[CheckFinding] = []
    seen: set[tuple[str, str]] = set()
    for word, occurrences in subject_map.items():
        always_headings = [h for p, h in occurrences if p == "always"]
        never_headings = [h for p, h in occurrences if p == "never"]
        if always_headings and never_headings:
            key = (always_headings[0], never_headings[0])
            if key not in seen:
                seen.add(key)
                findings.append(CheckFinding(
                    heading=always_headings[0],
                    issue=CheckIssue.CONTRADICTION,
                    severity=CheckSeverity.HIGH,
                    detail=(
                        f"'{word}' is 'always' in {always_headings[0]!r}"
                        f" but 'never' in {never_headings[0]!r}"
                    ),
                ))
    return findings
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_harvest_check.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add cctx/harvest.py tests/test_harvest_check.py
git commit -m "feat: check_contradictions() — always/never keyword heuristic"
```

---

## Task 3: `check_redundancy()` detector

**Files:**
- Modify: `cctx/harvest.py` — add after `check_contradictions`
- Test: `tests/test_harvest_check.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_harvest_check.py`:

```python
def test_redundancy_detected_similar_sections():
    from cctx.harvest import CheckIssue, check_redundancy
    body = "stop retrying after two failures diagnose before retrying"
    sections = [
        ("## Retry discipline", body),
        ("## Failure handling", body + " check error message"),
    ]
    findings = check_redundancy(sections)
    assert len(findings) == 1
    assert findings[0].issue is CheckIssue.REDUNDANCY


def test_no_redundancy_different_sections():
    from cctx.harvest import check_redundancy
    sections = [
        ("## Retry discipline", "stop retrying after two failures diagnose before"),
        ("## Scope creep", "finish stated task before picking up anything else"),
    ]
    assert check_redundancy(sections) == []


def test_short_section_not_eligible():
    from cctx.harvest import check_redundancy
    sections = [
        ("## A", "stop retry"),           # 2 words after stopword removal — not eligible
        ("## B", "stop retry"),
    ]
    assert check_redundancy(sections) == []


def test_redundancy_severity_is_medium():
    from cctx.harvest import CheckSeverity, check_redundancy
    body = "stop retrying after two failures diagnose before retrying"
    sections = [
        ("## A", body),
        ("## B", body),
    ]
    findings = check_redundancy(sections)
    assert findings[0].severity is CheckSeverity.MEDIUM
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_harvest_check.py::test_redundancy_detected_similar_sections \
    tests/test_harvest_check.py::test_no_redundancy_different_sections \
    tests/test_harvest_check.py::test_short_section_not_eligible \
    tests/test_harvest_check.py::test_redundancy_severity_is_medium -v
```

Expected: 4 FAILED (ImportError: cannot import name `check_redundancy`)

- [ ] **Step 3: Implement `check_redundancy` in `harvest.py`**

Add after `check_contradictions`:

```python
def check_redundancy(
    sections: list[tuple[str, str]],
) -> list[CheckFinding]:
    eligible = [
        (heading, body, _words(body))
        for heading, body in sections
        if len(_words(body)) >= 5
    ]
    findings: list[CheckFinding] = []
    for i in range(len(eligible)):
        for j in range(i + 1, len(eligible)):
            h1, _, w1 = eligible[i]
            h2, _, w2 = eligible[j]
            union = w1 | w2
            if not union:
                continue
            jaccard = len(w1 & w2) / len(union)
            if jaccard >= 0.8:
                findings.append(CheckFinding(
                    heading=h1,
                    issue=CheckIssue.REDUNDANCY,
                    severity=CheckSeverity.MEDIUM,
                    detail=f"{h1!r} and {h2!r} are {jaccard:.0%} similar",
                ))
    return findings
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_harvest_check.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add cctx/harvest.py tests/test_harvest_check.py
git commit -m "feat: check_redundancy() — Jaccard similarity ≥ 0.8 on section word sets"
```

---

## Task 4: `check_staleness()` detector

**Files:**
- Modify: `cctx/harvest.py` — add after `check_redundancy`
- Test: `tests/test_harvest_check.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_harvest_check.py`:

```python
def test_stale_identifier_flagged(tmp_path):
    from cctx.harvest import CheckIssue, check_staleness
    (tmp_path / "app.py").write_text("def some_other_fn(): pass\n")
    sections = [("## Guide", "Call `deleted_helper()` before running.")]
    findings = check_staleness(sections, tmp_path)
    assert any(f.issue is CheckIssue.STALE_IDENTIFIER for f in findings)
    assert any("deleted_helper" in f.detail for f in findings)


def test_existing_identifier_not_flagged(tmp_path):
    from cctx.harvest import check_staleness
    (tmp_path / "app.py").write_text("def tokenize_session(): pass\n")
    sections = [("## Guide", "Use `tokenize_session()` to count tokens.")]
    assert check_staleness(sections, tmp_path) == []


def test_short_identifier_not_eligible(tmp_path):
    from cctx.harvest import check_staleness
    (tmp_path / "app.py").write_text("def other(): pass\n")
    # "run" is 3 chars — below 8-char minimum
    sections = [("## Guide", "Call `run()` to start.")]
    assert check_staleness(sections, tmp_path) == []


def test_no_source_files_skips_staleness(tmp_path):
    from cctx.harvest import check_staleness
    # No .py/.ts/.js files in tmp_path
    sections = [("## Guide", "Call `deleted_helper()` before running.")]
    assert check_staleness(sections, tmp_path) == []


def test_staleness_severity_is_low(tmp_path):
    from cctx.harvest import CheckSeverity, check_staleness
    (tmp_path / "app.py").write_text("def other_fn(): pass\n")
    sections = [("## Guide", "Use `deleted_helper()` to process.")]
    findings = check_staleness(sections, tmp_path)
    assert findings[0].severity is CheckSeverity.LOW
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_harvest_check.py::test_stale_identifier_flagged \
    tests/test_harvest_check.py::test_existing_identifier_not_flagged \
    tests/test_harvest_check.py::test_short_identifier_not_eligible \
    tests/test_harvest_check.py::test_no_source_files_skips_staleness \
    tests/test_harvest_check.py::test_staleness_severity_is_low -v
```

Expected: 5 FAILED (ImportError: cannot import name `check_staleness`)

- [ ] **Step 3: Implement `check_staleness` in `harvest.py`**

Add after `check_redundancy`:

```python
def check_staleness(
    sections: list[tuple[str, str]],
    project_dir: Path,
) -> list[CheckFinding]:
    _EXCLUDED = {".git", ".venv", "node_modules", "__pycache__"}
    source_files = [
        f
        for f in (
            list(project_dir.rglob("*.py"))
            + list(project_dir.rglob("*.ts"))
            + list(project_dir.rglob("*.js"))
        )
        if not any(part in _EXCLUDED for part in f.parts)
    ]
    if not source_files:
        return []

    source_text = "\n".join(
        f.read_text(encoding="utf-8", errors="ignore") for f in source_files
    )

    findings: list[CheckFinding] = []
    for heading, body in sections:
        for match in _FUNC_REF_RE.finditer(body):
            name = match.group(1)
            if len(name) < 8:
                continue
            if name not in source_text:
                findings.append(CheckFinding(
                    heading=heading,
                    issue=CheckIssue.STALE_IDENTIFIER,
                    severity=CheckSeverity.LOW,
                    detail=f"'{name}()' not found in project source files",
                ))
    return findings
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_harvest_check.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add cctx/harvest.py tests/test_harvest_check.py
git commit -m "feat: check_staleness() — backtick function refs grepped against project source"
```

---

## Task 5: Wire detectors into `check_claude_md`

**Files:**
- Modify: `cctx/harvest.py` — refactor `check_claude_md`
- Test: `tests/test_harvest_check.py`

- [ ] **Step 1: Write integration test**

Add to `tests/test_harvest_check.py`:

```python
def test_check_claude_md_runs_all_detectors(tmp_path):
    """check_claude_md returns findings from all four check types."""
    from cctx.harvest import CheckIssue, check_claude_md

    # Create a source file so staleness check runs
    (tmp_path / "app.py").write_text("def other_function(): pass\n")

    content = "\n".join([
        "## Formatting",
        "Always use tabs for indentation.",
        "",
        "## Style",
        "Never use tabs, use spaces.",
        "",
        "## Dead ref",
        "See `missing/module.py`.",
        "",
        "## Stale",
        "Call `deleted_helper()` to process.",
    ])
    (tmp_path / "CLAUDE.md").write_text(content)

    findings = check_claude_md(tmp_path)
    issues = {f.issue for f in findings}
    assert CheckIssue.CONTRADICTION in issues
    assert CheckIssue.DEAD_FILE_REF in issues
    assert CheckIssue.STALE_IDENTIFIER in issues
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_harvest_check.py::test_check_claude_md_runs_all_detectors -v
```

Expected: FAIL — `check_claude_md` doesn't call the new detectors yet.

- [ ] **Step 3: Refactor `check_claude_md` in `harvest.py`**

Extract the existing per-section loop into a private `_check_structure` function, then call all four:

```python
def _check_structure(
    sections: list[tuple[str, str]],
    target_dir: Path,
) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    for heading, body in sections:
        body_stripped = body.strip()

        if heading != "(preamble)" and not body_stripped:
            findings.append(CheckFinding(
                heading=heading,
                issue=CheckIssue.EMPTY_SECTION,
                severity=CheckSeverity.MEDIUM,
                detail=f"{heading!r} has no content",
            ))
            continue

        for match in _SKILL_REF_RE.finditer(body):
            skill_path_str = match.group(1).lstrip("./")
            candidates = [
                target_dir / skill_path_str,
                Path.home() / skill_path_str,
            ]
            if not any(c.exists() for c in candidates):
                findings.append(CheckFinding(
                    heading=heading,
                    issue=CheckIssue.DEAD_SKILL_REF,
                    severity=CheckSeverity.MEDIUM,
                    detail=f"skill not found: {match.group(1)!r}",
                ))

        for match in _FILE_REF_RE.finditer(body):
            token = match.group(1)
            p = Path(token)
            if p.suffix not in _KNOWN_EXTENSIONS:
                continue
            if token.startswith("http") or "{" in token or "<" in token:
                continue
            candidate = target_dir / token
            if not candidate.exists() and not Path(token).exists():
                findings.append(CheckFinding(
                    heading=heading,
                    issue=CheckIssue.DEAD_FILE_REF,
                    severity=CheckSeverity.MEDIUM,
                    detail=f"file not found: {token!r}",
                ))
    return findings


def check_claude_md(target_dir: Path) -> list[CheckFinding]:
    """Audit CLAUDE.md in target_dir for deterministically detectable issues.

    Checks:
      - Dead file/skill references and empty sections (MEDIUM)
      - Contradictory always/never rules (HIGH)
      - Redundant sections with Jaccard ≥ 0.8 (MEDIUM)
      - Stale backtick-quoted function identifiers ≥ 8 chars (LOW)

    Returns an empty list if CLAUDE.md doesn't exist (not an error).
    """
    claude_md = target_dir / "CLAUDE.md"
    if not claude_md.exists():
        return []

    content = claude_md.read_text(encoding="utf-8")
    sections = _parse_sections(content)
    return (
        _check_structure(sections, target_dir)
        + check_contradictions(sections)
        + check_redundancy(sections)
        + check_staleness(sections, target_dir)
    )
```

Delete the old `check_claude_md` body (the per-section loop that used to be there).

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest tests/test_harvest_check.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add cctx/harvest.py tests/test_harvest_check.py
git commit -m "feat: wire all four detectors into check_claude_md"
```

---

## Task 6: CLI — `--check-severity` flag and severity badges

**Files:**
- Modify: `cctx/cli.py:144-165` (`_render_check_findings`) and `cctx/cli.py:545-567` (harvest command)
- Test: `tests/test_harvest_check.py`

- [ ] **Step 1: Write failing CLI tests**

Add to `tests/test_harvest_check.py`:

```python
def test_check_severity_high_exits_zero_on_medium_findings(tmp_path):
    """--check-severity HIGH: MEDIUM findings don't trigger exit 1."""
    from click.testing import CliRunner
    from cctx.cli import cli

    (tmp_path / "CLAUDE.md").write_text(
        "## Dead ref\n\nSee `missing/module.py`.\n"
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["harvest", str(tmp_path), "--check", "--check-severity", "HIGH",
         "--target-dir", str(tmp_path)],
    )
    assert result.exit_code == 0


def test_check_severity_low_exits_one_on_any_finding(tmp_path):
    """--check-severity LOW: any finding triggers exit 1."""
    from click.testing import CliRunner
    from cctx.cli import cli

    (tmp_path / "app.py").write_text("def other_fn(): pass\n")
    (tmp_path / "CLAUDE.md").write_text(
        "## Guide\n\nUse `deleted_helper()` to process.\n"
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["harvest", str(tmp_path), "--check", "--check-severity", "LOW",
         "--target-dir", str(tmp_path)],
    )
    assert result.exit_code == 1


def test_check_severity_in_help():
    from click.testing import CliRunner
    from cctx.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["harvest", "--help"])
    assert "--check-severity" in result.output


def test_check_output_shows_severity_badge(tmp_path):
    from click.testing import CliRunner
    from cctx.cli import cli

    (tmp_path / "CLAUDE.md").write_text(
        "## Dead ref\n\nSee `missing/module.py`.\n"
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["harvest", str(tmp_path), "--check", "--target-dir", str(tmp_path)],
    )
    # MED badge should appear for DEAD_FILE_REF (MEDIUM severity)
    assert "[MED]" in result.output or "MED" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_harvest_check.py::test_check_severity_high_exits_zero_on_medium_findings \
    tests/test_harvest_check.py::test_check_severity_low_exits_one_on_any_finding \
    tests/test_harvest_check.py::test_check_severity_in_help \
    tests/test_harvest_check.py::test_check_output_shows_severity_badge -v
```

Expected: FAILED — `--check-severity` not yet wired.

- [ ] **Step 3: Add `--check-severity` option to `harvest` command in `cli.py`**

Add this option block just before the existing `--check` option (around line 545):

```python
@click.option(
    "--check-severity",
    "check_severity",
    default="MEDIUM",
    type=click.Choice(["LOW", "MEDIUM", "HIGH"], case_sensitive=False),
    show_default=True,
    help="Minimum severity that causes --check to exit 1.",
)
```

Add `check_severity: str` to the `harvest` function signature:

```python
def harvest(
    target: Path,
    since: str | None,
    apply_mode: bool,
    dry_run: bool,
    target_dir: Path | None,
    check_mode: bool,
    check_severity: str,
) -> None:
```

Replace the `check_mode` block (currently ~3 lines) with:

```python
if check_mode:
    from cctx.harvest import CheckSeverity, check_claude_md
    resolved_dir = target_dir or Path.cwd()
    findings = check_claude_md(resolved_dir)
    _render_check_findings(findings, resolved_dir)
    _SEVERITY_ORDER = {
        CheckSeverity.LOW: 0,
        CheckSeverity.MEDIUM: 1,
        CheckSeverity.HIGH: 2,
    }
    threshold = CheckSeverity(check_severity.lower())
    triggering = [
        f for f in findings
        if _SEVERITY_ORDER[f.severity] >= _SEVERITY_ORDER[threshold]
    ]
    raise SystemExit(1 if triggering else 0)
```

- [ ] **Step 4: Update `_render_check_findings` in `cli.py`**

Replace the existing `_render_check_findings` function body:

```python
def _render_check_findings(findings: list, target_dir: Path) -> None:
    """Print harvest --check results to stdout using rich."""
    from rich.console import Console
    from rich.rule import Rule

    from cctx.harvest import CheckIssue, CheckSeverity

    con = Console()
    claude_md_path = target_dir / "CLAUDE.md"
    con.print(Rule(f"cctx harvest --check — {claude_md_path}"))
    if not findings:
        con.print("✓ CLAUDE.md looks clean — no issues found.")
        return
    con.print(f"{len(findings)} issue(s) found:\n")
    _ISSUE_LABEL = {
        CheckIssue.DEAD_FILE_REF:    "dead file reference",
        CheckIssue.DEAD_SKILL_REF:   "dead skill reference",
        CheckIssue.EMPTY_SECTION:    "empty section",
        CheckIssue.CONTRADICTION:    "contradiction",
        CheckIssue.REDUNDANCY:       "redundancy",
        CheckIssue.STALE_IDENTIFIER: "stale identifier",
    }
    _SEV_BADGE = {
        CheckSeverity.HIGH:   "[HIGH]",
        CheckSeverity.MEDIUM: "[MED] ",
        CheckSeverity.LOW:    "[LOW] ",
    }
    for f in findings:
        badge = _SEV_BADGE.get(f.severity, "      ")
        label = _ISSUE_LABEL.get(f.issue, f.issue.value)
        con.print(f"  {badge}  [{f.heading}]  {label}: {f.detail}")
```

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest -q
```

Expected: All tests PASS.

- [ ] **Step 6: Run ruff**

```bash
uv run ruff check cctx tests
```

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add cctx/cli.py tests/test_harvest_check.py
git commit -m "feat: --check-severity flag and severity badges in harvest --check output"
```
