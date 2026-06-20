# Cross-Agent Emit (M15) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `cctx harvest --emit agents [--sync]` so harvested findings are mirrored from CLAUDE.md into `AGENTS.md`, giving multi-agent users one source of truth with many destinations.

**Architecture:** A managed-heading registry in `models.py` is the single source of truth for "which CLAUDE.md sections cctx owns." `harvest.py` gains pure functions that clone this run's patches to the emit target (`retarget_patches`) and build synthetic patches from already-harvested managed sections in CLAUDE.md (`sync_managed_sections`). Both return `list[Patch]` and flow through the existing `preview_patches` / `apply_patches` machinery — the CLI decides preview vs. apply, so `--dry-run` is correct by construction. `cli.py` adds `--emit` (multiple) and `--sync` flags.

**Tech Stack:** Python 3.10+, click/rich-click (CLI only), dataclasses, pytest. No new dependencies.

---

## Branch base (decide before starting)

This plan's Task 2 (`test_registry_matches_templates`) requires the
`TOOL_THRASH` / `DEAD_END` recommender templates added in #106 (PR #107), which
is **open, not yet merged**. Branch M15 off the fix branch so it is stacked:

```bash
git checkout fix/recommender-tool-thrash-dead-end-templates
git checkout -b feat/cross-agent-emit
```

After #107 merges to main, rebase: `git rebase --onto main fix/recommender-tool-thrash-dead-end-templates`.
If #107 is merged before you start, branch off `main` directly instead.

---

## Spec reconciliation (read before starting)

The spec (`docs/superpowers/specs/2026-06-09-cross-agent-emit-design.md`) defines
`sync_managed_sections(...) -> list[ApplyResult]` that *applies patches directly*.
That conflicts with the spec's own `--dry-run` requirement and the
`test_dry_run_no_writes` acceptance test — direct application can't preview.

**Resolution adopted in this plan:** `sync_managed_sections` returns `list[Patch]`
(synthetic patches), not `list[ApplyResult]`, and the CLI routes them through the
same `preview_patches` (dry-run) / `apply_patches` (apply) flow as the fan-out
patches. This matches the codebase's established "CLI decides display/apply"
layering and makes `--dry-run` write nothing without special-casing. Task 9
updates the spec to record this deviation.

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `cctx/models.py` | Managed-heading registry constants | Add `MANAGED_HEADINGS`, `MANAGED_HEADING_PREFIX` |
| `cctx/harvest.py` | Pure patch-targeting + sync logic | Add `EMIT_TARGETS`, `retarget_patches`, `sync_managed_sections` |
| `cctx/cli.py` | Wire `--emit` / `--sync` into `harvest` | Add two options + routing |
| `tests/test_harvest_emit.py` | New test file | Create |
| `docs/superpowers/specs/2026-06-09-cross-agent-emit-design.md` | Record sync-returns-Patch deviation | Edit "New functions" + "Error contract" |
| `PRODUCT.md` | Feature map row | Add on release (Task 10) |

**Layering invariants to honor (verified in Task 8):**
- `harvest.py` imports `MANAGED_HEADINGS` / `MANAGED_HEADING_PREFIX` from `models.py`, never from `recommender/`.
- `harvest.py` does not import `click` or `anthropic`.
- `recommender/` is unchanged by this work.
- Renderers unchanged — AGENTS.md rows render as a second `target_path` group in the existing harvest results table.

---

### Task 1: Managed-heading registry in models.py

**Files:**
- Modify: `cctx/models.py` (add constants after the `FindingKind` enum / `KIND_LABEL`, near line 184)
- Test: `tests/test_harvest_emit.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_harvest_emit.py`:

```python
"""Tests for cctx/harvest.py cross-agent emit (M15) and the managed-heading registry."""
from __future__ import annotations

from pathlib import Path


def test_managed_headings_cover_the_five_diagnostic_kinds():
    from cctx.models import MANAGED_HEADINGS, FindingKind
    assert MANAGED_HEADINGS == {
        FindingKind.RETRY_LOOP:    "## Retry discipline",
        FindingKind.SCOPE_CREEP:   "## Scope discipline",
        FindingKind.STALE_CONTEXT: "## Context hygiene",
        FindingKind.TOOL_THRASH:   "## Tool-call discipline",
        FindingKind.DEAD_END:      "## Exploration discipline",
    }


def test_managed_heading_prefix_is_project_specific():
    from cctx.models import MANAGED_HEADING_PREFIX
    assert MANAGED_HEADING_PREFIX == "## Project-specific: "
```

- [ ] **Step 2: Run test to verify it fails**

Run: `CCTX_OFFLINE=1 uv run pytest tests/test_harvest_emit.py -q`
Expected: FAIL with `ImportError: cannot import name 'MANAGED_HEADINGS' from 'cctx.models'`

- [ ] **Step 3: Write minimal implementation**

In `cctx/models.py`, immediately after the `KIND_LABEL` dict (around line 184), add:

```python
# Maps FindingKind to the exact ## heading emitted by its recommender patch
# template. Single source of truth for "which CLAUDE.md sections cctx owns."
# harvest.py imports this (never reaches into recommender/) so emit/sync can
# identify cctx-managed sections without depending on the patch generator.
MANAGED_HEADINGS: dict[FindingKind, str] = {
    FindingKind.RETRY_LOOP:    "## Retry discipline",
    FindingKind.SCOPE_CREEP:   "## Scope discipline",
    FindingKind.STALE_CONTEXT: "## Context hygiene",
    FindingKind.TOOL_THRASH:   "## Tool-call discipline",
    FindingKind.DEAD_END:      "## Exploration discipline",
}

# Project-specific patterns use a heading that embeds tool+key, so the managed
# section is identified by prefix rather than exact match.
MANAGED_HEADING_PREFIX: str = "## Project-specific: "
```

- [ ] **Step 4: Run test to verify it passes**

Run: `CCTX_OFFLINE=1 uv run pytest tests/test_harvest_emit.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add cctx/models.py tests/test_harvest_emit.py
git commit -m "feat: models — MANAGED_HEADINGS registry for cctx-owned CLAUDE.md sections"
```

---

### Task 2: Registry-matches-templates contract test

This locks the registry (`models.py`) and the recommender templates
(`recommender/claude_md.py`) together so they cannot drift silently. The bug
fix in #106 already gave `TOOL_THRASH` / `DEAD_END` templates with the exact
headings this asserts, so this test passes immediately once Task 1 lands — it
is a guard, not a behavior change. (Per TDD we still write it and watch it run.)

**Files:**
- Test: `tests/test_harvest_emit.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_harvest_emit.py`:

```python
def test_registry_matches_templates():
    """Each MANAGED_HEADINGS value equals the first '+##' line of its template diff."""
    from cctx.models import MANAGED_HEADINGS
    from cctx.recommender.claude_md import _TEMPLATES
    for kind, heading in MANAGED_HEADINGS.items():
        assert kind in _TEMPLATES, f"{kind} missing from _TEMPLATES"
        _desc, diff_body, _target = _TEMPLATES[kind]
        first_line = diff_body.splitlines()[0]
        assert first_line == f"+{heading}", (
            f"{kind}: template heading {first_line!r} != registry {('+' + heading)!r}"
        )
```

- [ ] **Step 2: Run test to verify it passes (guard, not RED)**

Run: `CCTX_OFFLINE=1 uv run pytest tests/test_harvest_emit.py::test_registry_matches_templates -v`
Expected: PASS. If it FAILS, a template heading drifted from the registry — fix the registry value in `models.py` or the template in `recommender/claude_md.py` so they match exactly; do not edit the test to pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_harvest_emit.py
git commit -m "test: lock MANAGED_HEADINGS registry to recommender templates"
```

---

### Task 3: EMIT_TARGETS + retarget_patches in harvest.py

**Files:**
- Modify: `cctx/harvest.py` (add after the imports / `ApplyResult` block; new public functions in the "Public API" section)
- Test: `tests/test_harvest_emit.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harvest_emit.py`:

```python
def _patch(target_file="CLAUDE.md", heading="## Retry discipline"):
    from cctx.models import FindingKind, Patch
    return Patch(
        target_file=target_file,
        description="desc",
        unified_diff=f"+{heading}\n+\n+body line",
        finding_kind=FindingKind.RETRY_LOOP,
        evidence_summary="ev",
    )


def test_retarget_clones_claude_md_patches_to_agents():
    from cctx.harvest import retarget_patches
    out = retarget_patches([_patch()], "agents")
    assert len(out) == 1
    assert out[0].target_file == "AGENTS.md"
    # original diff/description preserved
    assert out[0].unified_diff == _patch().unified_diff


def test_retarget_excludes_non_claude_md_patches():
    from cctx.harvest import retarget_patches
    rules_patch = _patch(target_file=".claude/rules/foo.md")
    out = retarget_patches([_patch(), rules_patch], "agents")
    assert len(out) == 1
    assert out[0].target_file == "AGENTS.md"


def test_emit_targets_has_agents():
    from cctx.harvest import EMIT_TARGETS
    assert EMIT_TARGETS["agents"] == "AGENTS.md"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `CCTX_OFFLINE=1 uv run pytest tests/test_harvest_emit.py -k "retarget or emit_targets" -q`
Expected: FAIL with `ImportError: cannot import name 'retarget_patches'` / `EMIT_TARGETS`

- [ ] **Step 3: Write minimal implementation**

In `cctx/harvest.py`, add `import dataclasses` to the top imports, and add to the "Public API" section:

```python
# Maps an --emit target name to the destination filename. Single place to add
# future targets (Cursor, Windsurf, Copilot) when demand exists.
EMIT_TARGETS: dict[str, str] = {
    "agents": "AGENTS.md",
}


def retarget_patches(patches: list[Patch], emit_target: str) -> list[Patch]:
    """Clone CLAUDE.md-targeted patches to the emit target's file.

    Only patches whose target_file is exactly "CLAUDE.md" are emitted —
    .claude/rules/ and .claude/skills/ patches are Claude Code-specific and do
    not translate to other agents. Returns clones; inputs are unmodified.
    """
    dest = EMIT_TARGETS[emit_target]
    return [
        dataclasses.replace(p, target_file=dest)
        for p in patches
        if p.target_file == "CLAUDE.md"
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `CCTX_OFFLINE=1 uv run pytest tests/test_harvest_emit.py -k "retarget or emit_targets" -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add cctx/harvest.py tests/test_harvest_emit.py
git commit -m "feat: harvest — EMIT_TARGETS + retarget_patches (fan-out to AGENTS.md)"
```

---

### Task 4: sync_managed_sections in harvest.py

Backfill: mirror every cctx-managed section already in CLAUDE.md into the emit
target. Returns synthetic `Patch` objects (NOT ApplyResults — see Spec
reconciliation) so the CLI routes them through the normal preview/apply flow.

**Files:**
- Modify: `cctx/harvest.py`
- Test: `tests/test_harvest_emit.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harvest_emit.py`:

```python
def test_sync_returns_managed_sections_only(tmp_path):
    from cctx.harvest import sync_managed_sections
    (tmp_path / "CLAUDE.md").write_text(
        "# Project\n\n"
        "## Retry discipline\n\nRetry rule body.\n\n"
        "## My hand-written section\n\nNot managed by cctx.\n\n"
        "## Project-specific: Bash(pnpm install)\n\nUse pnpm --filter.\n",
        encoding="utf-8",
    )
    patches = sync_managed_sections(tmp_path, "agents")
    headings = {p.unified_diff.splitlines()[0] for p in patches}
    assert "+## Retry discipline" in headings
    assert "+## Project-specific: Bash(pnpm install)" in headings
    assert "+## My hand-written section" not in headings
    assert all(p.target_file == "AGENTS.md" for p in patches)


def test_sync_finding_kind_reverse_lookup(tmp_path):
    from cctx.models import FindingKind
    from cctx.harvest import sync_managed_sections
    (tmp_path / "CLAUDE.md").write_text(
        "## Context hygiene\n\nbody\n\n"
        "## Project-specific: Bash(x)\n\nbody\n",
        encoding="utf-8",
    )
    patches = sync_managed_sections(tmp_path, "agents")
    by_heading = {p.unified_diff.splitlines()[0]: p.finding_kind for p in patches}
    assert by_heading["+## Context hygiene"] is FindingKind.STALE_CONTEXT
    assert by_heading["+## Project-specific: Bash(x)"] is FindingKind.PROJECT_PATTERN


def test_sync_no_claude_md_returns_empty(tmp_path):
    from cctx.harvest import sync_managed_sections
    assert sync_managed_sections(tmp_path, "agents") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `CCTX_OFFLINE=1 uv run pytest tests/test_harvest_emit.py -k sync -q`
Expected: FAIL with `ImportError: cannot import name 'sync_managed_sections'`

- [ ] **Step 3: Write minimal implementation**

In `cctx/harvest.py`, update the `TYPE_CHECKING` import to also pull `FindingKind`,
and add a module-level import of the registry (top of file, runtime import — it is
plain data, no layering violation):

```python
from cctx.models import MANAGED_HEADINGS, MANAGED_HEADING_PREFIX
```

Then add to the Public API section:

```python
# Reverse map: exact managed heading -> the FindingKind that owns it.
_HEADING_TO_KIND = {heading: kind for kind, heading in MANAGED_HEADINGS.items()}


def sync_managed_sections(target_dir: Path, emit_target: str) -> list[Patch]:
    """Build synthetic patches mirroring CLAUDE.md's cctx-managed sections.

    Reads CLAUDE.md in target_dir, keeps sections whose heading is an exact
    MANAGED_HEADINGS value or starts with MANAGED_HEADING_PREFIX, and returns
    one Patch per kept section targeting the emit file. Returns [] if CLAUDE.md
    is absent. The CLI routes these through preview_patches / apply_patches, so
    idempotency and dry-run come for free from the existing machinery.
    """
    from cctx.models import FindingKind, Patch  # local import: avoid import cycle at module load

    claude_md = target_dir / "CLAUDE.md"
    if not claude_md.exists():
        return []

    dest = EMIT_TARGETS[emit_target]
    content = claude_md.read_text(encoding="utf-8")
    patches: list[Patch] = []

    for heading, body in _parse_sections(content):
        is_fixed = heading in _HEADING_TO_KIND
        is_prefixed = heading.startswith(MANAGED_HEADING_PREFIX)
        if not (is_fixed or is_prefixed):
            continue

        kind = _HEADING_TO_KIND[heading] if is_fixed else FindingKind.PROJECT_PATTERN
        diff_lines = [heading] + body.splitlines()
        unified_diff = "\n".join(f"+{line}" for line in diff_lines)
        patches.append(Patch(
            target_file=dest,
            description=heading,
            unified_diff=unified_diff,
            finding_kind=kind,
            evidence_summary="synced from CLAUDE.md",
        ))

    return patches
```

Note: `_parse_sections` yields a leading `("(preamble)", ...)` pair whose heading
matches neither branch, so it is correctly skipped.

- [ ] **Step 4: Run tests to verify they pass**

Run: `CCTX_OFFLINE=1 uv run pytest tests/test_harvest_emit.py -k sync -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add cctx/harvest.py tests/test_harvest_emit.py
git commit -m "feat: harvest — sync_managed_sections backfills CLAUDE.md into emit target"
```

---

### Task 5: Idempotency of emit + sync through preview/apply

Proves the existing fingerprint dedup (`_already_present`) covers the new
patches end-to-end: a second apply of the same retargeted/synced patches is a
no-op. No production code — these are integration tests over Tasks 3–4 + the
existing `apply_patches`.

**Files:**
- Test: `tests/test_harvest_emit.py`

- [ ] **Step 1: Write the tests**

Append to `tests/test_harvest_emit.py`:

```python
def test_emit_apply_then_reapply_is_idempotent(tmp_path):
    from cctx.harvest import retarget_patches, apply_patches, ApplyStatus
    patches = retarget_patches([_patch()], "agents")
    first = apply_patches(patches, tmp_path)
    assert [r.status for r in first] == [ApplyStatus.APPLIED]
    second = apply_patches(patches, tmp_path)
    assert [r.status for r in second] == [ApplyStatus.SKIPPED]
    # AGENTS.md contains the heading exactly once
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert text.count("## Retry discipline") == 1


def test_sync_apply_then_reapply_is_idempotent(tmp_path):
    from cctx.harvest import sync_managed_sections, apply_patches, ApplyStatus
    (tmp_path / "CLAUDE.md").write_text(
        "## Retry discipline\n\nRetry rule body.\n", encoding="utf-8"
    )
    patches = sync_managed_sections(tmp_path, "agents")
    apply_patches(patches, tmp_path)
    second = apply_patches(patches, tmp_path)
    assert all(r.status is ApplyStatus.SKIPPED for r in second)
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert text.count("## Retry discipline") == 1
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `CCTX_OFFLINE=1 uv run pytest tests/test_harvest_emit.py -k idempotent -q`
Expected: PASS (2 passed). If FAIL, the synthetic diff's first `## ` line isn't
matching `_fingerprint`/`_already_present` — check the heading is emitted verbatim.

- [ ] **Step 3: Commit**

```bash
git add tests/test_harvest_emit.py
git commit -m "test: emit + sync idempotency through apply_patches"
```

---

### Task 6: Fix preview_patches cross-target dedup (latent bug M15 exposes)

`preview_patches` dedups by heading string alone (`harvest.py:165,184` —
`seen_fingerprints: set[str]`), ignoring the target file. M15 is the first
feature to emit the same heading to two files (CLAUDE.md + AGENTS.md), so it is
the first to trigger the bug: preview marks the CLAUDE.md patch APPLIED, adds
the heading to `seen`, then wrongly marks the AGENTS.md patch SKIPPED "already
present" even though AGENTS.md doesn't contain it. `apply_patches` is per-file
and correct, so this is a preview/apply divergence that corrupts the interactive
`applicable` count and makes `--dry-run` lie. **Confirmed empirically.** Fix
preview before wiring the CLI, since both `--dry-run` and the default path feed
`preview_patches`.

**Files:**
- Modify: `cctx/harvest.py:161-201` (`preview_patches` — key dedup by `(target_path, fingerprint)`)
- Test: `tests/test_harvest_emit.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_harvest_emit.py`:

```python
def test_preview_same_heading_different_targets_both_applied(tmp_path):
    """Two patches with the same heading but different target files must both
    preview as APPLIED — dedup is per-(file, heading), not heading-only."""
    from cctx.models import FindingKind, Patch
    from cctx.harvest import preview_patches, ApplyStatus
    diff = "+## Retry discipline\n+\n+body"
    patches = [
        Patch("CLAUDE.md", "d", diff, FindingKind.RETRY_LOOP, "e"),
        Patch("AGENTS.md", "d", diff, FindingKind.RETRY_LOOP, "e"),
    ]
    statuses = [r.status for r in preview_patches(patches, tmp_path)]
    assert statuses == [ApplyStatus.APPLIED, ApplyStatus.APPLIED]


def test_preview_same_heading_same_target_dedups(tmp_path):
    """Two patches with the same heading AND same target: second is SKIPPED."""
    from cctx.models import FindingKind, Patch
    from cctx.harvest import preview_patches, ApplyStatus
    diff = "+## Retry discipline\n+\n+body"
    patches = [
        Patch("AGENTS.md", "d", diff, FindingKind.RETRY_LOOP, "e"),
        Patch("AGENTS.md", "d", diff, FindingKind.RETRY_LOOP, "e"),
    ]
    statuses = [r.status for r in preview_patches(patches, tmp_path)]
    assert statuses == [ApplyStatus.APPLIED, ApplyStatus.SKIPPED]
```

- [ ] **Step 2: Run tests to verify they fail (only the first)**

Run: `CCTX_OFFLINE=1 uv run pytest tests/test_harvest_emit.py -k "preview_same_heading" -q`
Expected: `test_preview_same_heading_different_targets_both_applied` FAILS (second
status is SKIPPED, not APPLIED); `test_preview_same_heading_same_target_dedups`
already PASSES (it documents the behavior to preserve).

- [ ] **Step 3: Write minimal implementation**

In `cctx/harvest.py`, change `preview_patches` to key the seen-set by
`(target_path, fingerprint)`:

```python
    # Track (target_path, fingerprint) already "seen" within this preview run.
    # Keyed by target so the same heading to different files both apply.
    seen_fingerprints: set[tuple[Path, str]] = set()
```

and inside the loop:

```python
        if fp is not None and (
            _already_present(content, fp) or (target_path, fp) in seen_fingerprints
        ):
            results.append(ApplyResult(
                patch=patch,
                status=ApplyStatus.SKIPPED,
                target_path=target_path,
                message=f"already present: {fp}",
            ))
        else:
            if fp is not None:
                seen_fingerprints.add((target_path, fp))
            results.append(ApplyResult(...))  # unchanged body
```

(Leave the `would append` / `target not supported` branches exactly as they are.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `CCTX_OFFLINE=1 uv run pytest tests/test_harvest_emit.py -k "preview_same_heading" -q`
Expected: PASS (2 passed). Then run the existing harvest suite to confirm no
regression in single-target dedup: `CCTX_OFFLINE=1 uv run pytest tests/test_harvest.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add cctx/harvest.py tests/test_harvest_emit.py
git commit -m "fix: harvest — preview_patches dedup per (target, heading) not heading-only"
```

---

### Task 7: Wire --emit / --sync into the harvest CLI command

**Files:**
- Modify: `cctx/cli.py:530-650` (the `harvest` command — add two options, extend the signature, route emit/sync into the patch list before preview/apply)
- Test: `tests/test_harvest_emit.py` (CliRunner end-to-end)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harvest_emit.py`. These mirror how `tests/test_cli.py`
invokes the CLI (check that file for the exact `CliRunner` import + a single-
session fixture path you can reuse; if none is reusable, the `--sync` and error
tests below need no session file and should be implemented first):

```python
from click.testing import CliRunner


def test_sync_without_emit_errors(tmp_path):
    from cctx.cli import cli
    (tmp_path / "CLAUDE.md").write_text("## Retry discipline\n\nbody\n", encoding="utf-8")
    runner = CliRunner()
    # --sync requires --emit; a session target is still required positionally,
    # but the error must fire before any parsing of the session.
    result = runner.invoke(cli, [
        "harvest", str(tmp_path), "--since", "7",
        "--sync", "--target-dir", str(tmp_path),
    ])
    assert result.exit_code != 0
    assert "--sync" in result.output and "--emit" in result.output


def test_sync_dry_run_writes_nothing(tmp_path):
    from cctx.cli import cli
    (tmp_path / "CLAUDE.md").write_text("## Retry discipline\n\nbody\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "harvest", str(tmp_path), "--since", "7",
        "--emit", "agents", "--sync", "--dry-run",
        "--target-dir", str(tmp_path),
    ])
    assert result.exit_code == 0
    assert not (tmp_path / "AGENTS.md").exists()


def test_sync_apply_creates_agents_md(tmp_path):
    from cctx.cli import cli
    (tmp_path / "CLAUDE.md").write_text("## Retry discipline\n\nbody\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "harvest", str(tmp_path), "--since", "7",
        "--emit", "agents", "--sync", "--apply",
        "--target-dir", str(tmp_path),
    ])
    assert result.exit_code == 0
    assert (tmp_path / "AGENTS.md").exists()
    assert "## Retry discipline" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
```

Note on `--since 7` with an empty project dir: **confirmed** —
`aggregate.run` globs `project_dir.glob("*.jsonl")` (`aggregate.py:29`), so a
sessionless `tmp_path` returns `[]` (no raise) and `patches` is empty. `--sync`
then contributes the synthetic patches from CLAUDE.md, which is exactly what
these tests exercise. No `.jsonl` fixture needed for the `--sync` tests.

- [ ] **Step 2: Run tests to verify they fail**

Run: `CCTX_OFFLINE=1 uv run pytest tests/test_harvest_emit.py -k "sync_without_emit or sync_dry_run or sync_apply_creates" -q`
Expected: FAIL — `--emit`/`--sync` are unknown options (exit code 2, "No such option").

- [ ] **Step 3: Write minimal implementation**

In `cctx/cli.py`, add two options to the `harvest` command decorator stack
(after `--check-severity`, before `def harvest`):

```python
@click.option(
    "--emit",
    "emit_targets",
    multiple=True,
    type=click.Choice(list(EMIT_TARGETS)),
    help="Also write applicable patches to another agent's instruction file "
         "(e.g. AGENTS.md). Repeatable.",
)
@click.option(
    "--sync",
    "sync_mode",
    is_flag=True,
    default=False,
    help="With --emit: also mirror already-harvested cctx-managed sections "
         "from CLAUDE.md into the emit target.",
)
```

Add `EMIT_TARGETS` to the existing harvest import line and extend the function
signature:

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
) -> None:
    """Apply autopsy patches to CLAUDE.md (optionally mirrored to other agents)."""
    from cctx.harvest import (
        EMIT_TARGETS, apply_patches, check_claude_md, preview_patches,
        retarget_patches, sync_managed_sections,
    )

    if sync_mode and not emit_targets:
        raise click.UsageError("--sync requires --emit.")
```

(Place the `--sync requires --emit` guard at the very top of the function body,
before `--check`, so it fires regardless of other flags. Move the existing
`from cctx.harvest import ...` line's contents into the multi-name import above
and delete the old single-line import.)

Then, after `patches` is computed (the `if/else` block ending at line ~627) and
before the `if not patches:` check, append emit + sync patches. Capture the
CLAUDE.md-only base once so retarget always clones from the original list:

```python
    base = patches
    for t in emit_targets:
        emitted = retarget_patches(base, t)
        if sync_mode:
            emitted = emitted + sync_managed_sections(resolved_dir, t)
        patches = patches + emitted
```

This keeps `patches` a single `list[Patch]` that flows through the existing
preview/apply/confirm logic unchanged — AGENTS.md rows render in the same table
under their own `target_path` group, and `--dry-run` previews without writing.
(`retarget_patches` filters to `target_file == "CLAUDE.md"`, so appended
AGENTS.md patches are never double-emitted; capturing `base` makes that explicit.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `CCTX_OFFLINE=1 uv run pytest tests/test_harvest_emit.py -q`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add cctx/cli.py tests/test_harvest_emit.py
git commit -m "feat: cli — harvest --emit / --sync cross-agent emit (#82)"
```

---

### Task 8: Full suite + layering verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `CCTX_OFFLINE=1 uv run pytest -q`
Expected: PASS — all prior tests plus the new `test_harvest_emit.py`. Investigate any failure before continuing.

- [ ] **Step 2: Verify layering invariants**

Run:
```bash
grep -nE "import (click|rich_click|anthropic)" cctx/harvest.py
grep -nE "from cctx.recommender|import recommender" cctx/harvest.py
git diff --name-only main -- cctx/recommender/
```
Expected: first two greps print nothing; the third prints nothing (recommender untouched).

- [ ] **Step 3: Smoke-test the CLI help**

Run: `CCTX_OFFLINE=1 uv run cctx harvest --help`
Expected: `--emit` and `--sync` appear with their help text; `--emit` shows choice `[agents]`.

- [ ] **Step 4: Commit (if any incidental fixes were needed)**

Only if Steps 1–3 surfaced a fix. Otherwise skip.

---

### Task 9: Update the spec to record the sync-returns-Patch deviation

**Files:**
- Modify: `docs/superpowers/specs/2026-06-09-cross-agent-emit-design.md`

- [ ] **Step 1: Edit the `sync_managed_sections` subsection**

In the "New functions in `cctx/harvest.py`" section, change the signature line
and step 5 to reflect that the function returns `list[Patch]` and the CLI
applies them via the existing preview/apply flow (not `apply_patch` inside the
function). Add a one-line note: "Returning patches (rather than applying inline)
keeps `--dry-run` write-free and matches the codebase's CLI-decides-apply
layering."

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-06-09-cross-agent-emit-design.md
git commit -m "docs: spec — sync_managed_sections returns patches for dry-run safety"
```

---

### Task 10: PRODUCT.md feature row + PR

**Files:**
- Modify: `PRODUCT.md` (add a cross-agent emit row to the feature map — match the existing table format; read the file first to find the right section/columns)

- [ ] **Step 1: Add the feature-map row**

Read `PRODUCT.md`, locate the harvest/feature table, and add a row for
`harvest --emit agents [--sync]` describing cross-agent emit to AGENTS.md.
Match the surrounding row format exactly.

- [ ] **Step 2: Commit**

```bash
git add PRODUCT.md
git commit -m "docs: PRODUCT.md — cross-agent emit (harvest --emit agents)"
```

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin <branch>
gh pr create --base main --title "feat: cctx harvest --emit — cross-agent layer to AGENTS.md (#82)" --body "<summary + test plan; Closes #82>"
```

The PR body should note: AGENTS.md-only this milestone (Cursor/Windsurf/Copilot
are follow-on issues per the spec's "Out of scope"), depends on #106 (recommender
templates) being merged first.

---

## Self-review notes

- **Spec coverage:** `--emit agents` (Task 3 + 7), `--sync` backfill (Task 4 + 7),
  rules/skills exclusion (Task 3), idempotency (Task 5), per-target preview
  correctness (Task 6), `--dry-run` no-write (Task 7), `--sync` without `--emit`
  errors (Task 7), registry-matches-templates (Task 2), managed registry (Task 1).
  The spec's multi-`--emit` acceptance item is satisfied structurally
  (`multiple=True` + the `for t in emit_targets` loop); with only `agents`
  registered today there is one real target — note this in the PR rather than
  adding a second fake target to test multiplicity.
- **Cursor/Windsurf/Copilot** acceptance items from the *issue* (#82) are
  explicitly descoped by the *spec* to follow-on issues; the PR notes this so the
  issue can be closed with that scope statement (or those checkboxes moved to new
  issues).
- **Deviation flagged:** `sync_managed_sections` returns `list[Patch]` not
  `list[ApplyResult]` (Task 9 updates the spec). Confirm with the reviewer.
