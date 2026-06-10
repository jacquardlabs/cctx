# cctx harvest --emit — Cross-agent layer (M15)

**Issue:** #82  
**Date:** 2026-06-09  
**Status:** Ready for implementation

---

## Goal

Write harvested findings to `AGENTS.md` so developers who use multiple AI coding
tools get the same captured knowledge without manual copy-pasting. CLAUDE.md
remains the source of truth; AGENTS.md is a downstream mirror of the sections
cctx itself manages.

Scope: `AGENTS.md` only in this milestone. Cursor (`.cursor/rules/*.mdc`),
Windsurf (`.windsurf/rules/`), and Copilot (`.github/copilot-instructions.md`)
are follow-on issues to file when user demand exists, since those formats require
either frontmatter metadata or different directory layouts.

---

## Two modes

### 1. Fan-out (`--emit agents`)

`cctx harvest <target> --emit agents` fans the patches from this run out to
`AGENTS.md` alongside the normal CLAUDE.md apply.

Patches targeting `.claude/rules/` or `.claude/skills/` are excluded — those
surfaces are Claude Code-specific and do not translate to other agents.

### 2. Backfill (`--emit agents --sync`)

`--sync` (valid only when `--emit` is also present) mirrors every
cctx-managed section already in CLAUDE.md into the emit target, not just the
patches from this run. Use when AGENTS.md doesn't exist yet and you want to
seed it from everything cctx has accumulated in CLAUDE.md over time.

---

## Managed-heading registry

New constants in `cctx/models.py`:

```python
# Maps FindingKind to the exact ## heading emitted by its patch template.
# Single source of truth for "which CLAUDE.md sections does cctx own."
MANAGED_HEADINGS: dict[FindingKind, str] = {
    FindingKind.RETRY_LOOP:      "## Retry discipline",
    FindingKind.SCOPE_CREEP:     "## Scope discipline",
    FindingKind.STALE_CONTEXT:   "## Context hygiene",
    FindingKind.TOOL_THRASH:     "## Tool-call discipline",
    FindingKind.DEAD_END:        "## Exploration discipline",
}

# Prefix for project-specific patterns (heading includes tool+key, so match by prefix).
MANAGED_HEADING_PREFIX: str = "## Project-specific: "
```

A test in `tests/test_harvest_emit.py` asserts that each template's first
`+##` line equals its `MANAGED_HEADINGS` entry, so the registry and the
recommender templates cannot drift silently.

**`harvest.py` imports the registry from `models.py`** — the existing rule
"harvest does not import from recommender" remains intact.

---

## New functions in `cctx/harvest.py`

### `EMIT_TARGETS`

```python
EMIT_TARGETS: dict[str, str] = {
    "agents": "AGENTS.md",
}
```

Single place to add future targets. CLI `Choice` is derived from its keys.

### `retarget_patches(patches, emit_target) -> list[Patch]`

Clones patches suitable for emission:

- Includes only patches with `target_file == "CLAUDE.md"`.
- Excludes patches targeting `.claude/rules/` or `.claude/skills/` (none
  reach here given the above filter, but stated explicitly for clarity).
- Returns clones via `dataclasses.replace(patch, target_file=EMIT_TARGETS[emit_target])`.

### `sync_managed_sections(target_dir, emit_target) -> list[Patch]`

> **Implementation deviation (2026-06-10):** This function returns
> `list[Patch]` rather than applying patches inline (the original draft returned
> `list[ApplyResult]` and called `apply_patch` itself). The CLI appends these
> patches to the same list it routes through `preview_patches` / `apply_patches`.
> Returning patches keeps `--dry-run` write-free by construction and matches the
> codebase's "CLI decides preview vs. apply" layering — applying inline could not
> preview, contradicting the `--dry-run` requirement and `test_dry_run_no_writes`.

1. Reads `CLAUDE.md` from `target_dir`. Returns empty list if absent.
2. Calls `_parse_sections(content)` (already in `harvest.py`).
3. Keeps sections whose heading is exactly in `MANAGED_HEADINGS.values()` OR
   starts with `MANAGED_HEADING_PREFIX`. The leading `("(preamble)", …)` pair
   matches neither branch and is skipped.
4. For each kept section, constructs a synthetic `Patch` with:
   - `target_file = EMIT_TARGETS[emit_target]`
   - `unified_diff = "\n".join(f"+{line}" for line in [heading] + body.splitlines())`
     so the heading itself is the first line (drives `_fingerprint` dedup)
   - `finding_kind`: reverse-lookup from `MANAGED_HEADINGS` for fixed headings;
     `FindingKind.PROJECT_PATTERN` for `## Project-specific: …` prefixed headings
   - `description = heading`
   - `evidence_summary = "synced from CLAUDE.md"`
5. Returns the list of synthetic patches. The CLI routes them through the
   existing `preview_patches` / `apply_patches` machinery, which handles
   idempotency via `_already_present` (the `## Heading` line is the fingerprint)
   and dry-run preview without writing.

---

## CLI changes (`cctx/cli.py`)

```
harvest <target>
  --emit [agents]     Fan out this run's patches to the named target.
                      Multiple targets accepted (future-proofing).
  --sync              With --emit: also mirror already-harvested managed
                      sections from CLAUDE.md to the emit target.
                      Error if used without --emit.
```

`--emit` is `click.option(..., multiple=True, type=click.Choice(list(EMIT_TARGETS)))`.

`--sync` without `--emit` prints an error and exits non-zero.

Both flags compose with the existing `--dry-run`/`--apply` flow:
- `--dry-run` previews all targets (CLAUDE.md rows + AGENTS.md rows).
- Without `--dry-run`, the normal interactive confirmation fires first, showing
  the full diff including emit targets.

`--since` mode: `retarget_patches` runs on the aggregate patches exactly as it
does on single-session patches.

---

## Rendering

The existing results table in `cli.py` groups by `target_path`. No renderer
changes needed — AGENTS.md rows appear as a second group in the same table
under their full path.

---

## Error contract

- Never raises. All failures return `ApplyResult(status=ERROR, message=...)`.
- `--sync` with no CLAUDE.md: `sync_managed_sections` returns `[]` (not an
  error). Because it returns patches rather than applying inline (see the
  deviation note above), there is no `SKIPPED` line for the missing file — the
  empty result simply contributes nothing, and if no other patches exist the CLI
  prints its standard "No patches to apply." message. (The original draft
  emitted a "CLAUDE.md not found — nothing to sync." line; that belonged to the
  inline-apply design and no longer applies.)
- Emit target directory is created by `apply_patch`'s existing `parent.mkdir`.

---

## Out of scope

- Cursor (`.cursor/rules/*.mdc` with frontmatter), Windsurf, Copilot — future issues.
- Format translation / agent-specific adaptation of rule text.
- Drift detection between CLAUDE.md and AGENTS.md after independent edits.
- The `TOOL_THRASH`/`DEAD_END` `KeyError` in `recommender.generate()` when
  findings of those kinds have no `_TEMPLATES` entry — filed separately as a
  bug before M15 implementation begins, since M15 adds those kinds to
  `MANAGED_HEADINGS` and the fix belongs in the recommender, not the emitter.

---

## Testing (`tests/test_harvest_emit.py`)

| Test | Asserts |
|---|---|
| `test_emit_applies_both_targets` | Patch lands in both CLAUDE.md and AGENTS.md |
| `test_emit_excludes_rules_patches` | `.claude/rules/` patch not emitted |
| `test_emit_idempotent` | Second `--emit` run: AGENTS.md unchanged |
| `test_sync_copies_managed_only` | Managed section copied; hand-written section absent from AGENTS.md |
| `test_sync_no_claude_md` | Returns `[]`; AGENTS.md not created |
| `test_sync_idempotent` | Second `--sync` run: no duplicate sections |
| `test_dry_run_no_writes` | Neither CLAUDE.md nor AGENTS.md written |
| `test_sync_without_emit_errors` | `--sync` alone exits non-zero |
| `test_registry_matches_templates` | Each `MANAGED_HEADINGS[k]` equals first `+##` line of `_TEMPLATES[k]`'s diff body |

---

## Layering

No layering rules are broken:
- `harvest.py` imports `MANAGED_HEADINGS` and `MANAGED_HEADING_PREFIX` from
  `models.py`, not from `recommender/`.
- `recommender/` is unchanged.
- `harvest.py` does not import `click` or `anthropic`.

---

## Files touched

| File | Change |
|---|---|
| `cctx/models.py` | Add `MANAGED_HEADINGS`, `MANAGED_HEADING_PREFIX` |
| `cctx/harvest.py` | Add `EMIT_TARGETS`, `retarget_patches`, `sync_managed_sections` |
| `cctx/cli.py` | Add `--emit` + `--sync` to `harvest` command |
| `tests/test_harvest_emit.py` | New test file |
| `PRODUCT.md` | Add cross-agent emit row to feature map (on release) |
