# cctx Frontend Health Review — 2026-06-20

**Context:** This is the first review. The review was returned inline (the `docs/jaqal/frontend-reviews/` directory did not exist when it ran) and is persisted here afterward.

**Version reviewed:** v1.17.0.

cctx has three output surfaces: a Rich terminal renderer, a Textual TUI, and a Jinja2 HTML report. There is no web frontend. Audits below are scoped to those three surfaces plus the CLI.

---

## Summary

The renderer layer is well-structured, layering rules are mostly honored, and test coverage is solid for the original 3 finding kinds. The main technical debt item is DESIGN.md describing a product that shipped in M1 — it documents 3 finding kinds and a verdict format that have both since been superseded by the live code. The biggest UX risk is a concrete rendering bug: the HTML report's badge CSS covers only 3 of 11 shipped finding kinds, so any session producing `tool_thrash`, `dead_end`, `fanout_waste`, `cache_hygiene`, `compaction`, `exploration_thrash`, or `unused_context` findings renders unstyled `<span class="badge kind-exploration_thrash">` elements with no background color. There is a secondary label-divergence bug in `github.py` that uses a local 5-entry string-keyed dict and falls back to the raw enum value for those 6 kinds, directly violating the DESIGN.md anti-pattern "Never use the raw enum value in user-facing output."

---

## 1. Design System Consistency

### Color palette

The severity palette (`bold red` HIGH / `bold yellow` MEDIUM / `bold green` LOW) is consistent across all three surfaces:

- Terminal: `_SEVERITY_STYLE` dict in `terminal.py:30-34` — exact match.
- HTML: `.sev-high`, `.sev-medium`, `.sev-low` badge classes with matching semantic intent.
- GitHub: `_SEVERITY_EMOJI` maps `"high"/"medium"/"low"` to colored circles — a non-terminal equivalent.
- TUI: renders severity as text in the modal (line 115), no color applied here — minor gap but the modal is supplementary.

Harvest results use `green` for APPLIED, `red` for ERROR, `dim` for SKIPPED (terminal.py:335-340). This matches the DESIGN.md anti-pattern prohibition of `red` for success.

### Finding kind labels — 3 divergent implementations

DESIGN.md says `models.py`'s `KIND_LABEL` is the source of truth. There are 3 separate implementations that have diverged:

1. **`cctx/models.py` `KIND_LABEL`**: 11 entries, `FindingKind` enum-keyed, UPPERCASE with spaces. This is the canonical source.
2. **`cctx/renderers/github.py` `_KIND_LABEL`**: 5 entries, string-keyed (`"retry_loop"` etc.), Title Case. Missing 6 kinds. Fallback on line 62 is `f.kind.value` — raw enum string. This is a live bug for 6 of 11 kinds.
3. **`cctx/renderers/templates/autopsy.html.j2` lines 205 and 229**: inline `f.kind.value.replace("_", " ").upper()`. Matches the canonical output for the current 11 kinds (all use underscores), but will diverge if a future kind uses a non-underscore separator.

`terminal.py` is correct: it uses `_KIND_LABEL = KIND_LABEL` (line 36) with a `.value.upper()` fallback. `trace_tui.py` FindingModal (line 115) uses raw `f.kind.value` directly — a violation of the "never use raw enum value" anti-pattern.

### HTML badge CSS — 8 of 11 kinds have no CSS rule

`autopsy.html.j2` lines 48-50 define `.badge.kind-retry_loop`, `.badge.kind-scope_creep`, `.badge.kind-stale_context`. The template renders class names like `kind-tool_thrash`, `kind-dead_end`, `kind-fanout_waste`, `kind-cache_hygiene`, `kind-compaction`, `kind-exploration_thrash`, `kind-unused_context`, `kind-project_pattern` for all 8 newer kinds. No CSS rules exist for these — the badge renders as unstyled text with no background, making the kind badge invisible against the dark `#0d1117` background.

### Verdict format — models vs. TUI/HTML mismatch + DESIGN.md incorrect

DESIGN.md states the kind-based verdict is "a future format, not yet implemented." This is wrong. `Diagnosis.verdict` at `models.py:274-278` returns the kind-based format (`"RETRY LOOP + SCOPE CREEP"`). `terminal.py:82-84` renders it directly. Meanwhile `trace_tui.verdict()` (line 52-58) returns `"N findings · $X.XX waste"` and the HTML (line 170-172) also uses count + waste. So the terminal displays kind-based verdict; TUI and HTML display count-based verdict. They disagree.

The `Diagnosis.verdict` property also returns lowercase `"clean session"` (models.py:276), while all other surfaces use `"Clean session"`.

### Subagent cost format — undocumented `.3f`

Terminal (line 122) and HTML template (lines 181, 188) both use `:.3f` / `"%.3f"` for individual subagent costs. DESIGN.md documents only `.2f` and `.4f`. `.3f` is an undocumented third format.

### Patch panel title — raw enum value

`terminal.py:341`: `title = f"Patch {i} of {total} — {result.patch.finding_kind.value}"`. Uses raw `.value` rather than `KIND_LABEL`.

### `_wide_console` — defined but never called

`terminal.py:43-46` defines `_wide_console()` returning `Console(width=200)`. No call site exists. Dead code.

### `group_into_exchanges` — tested but unused by renderers

`models.py:342-369` defines `group_into_exchanges()`. It has unit tests and the docstring says it's for "render-time" use. No renderer imports or calls it.

---

## 2. Accessibility Audit

### HTML report (`autopsy --html`)

- **Heading hierarchy:** Single `<h1>` → `<h2>` sections. Correct, no gaps.
- **Interactive elements:** `<details>`/`<summary>` are natively keyboard accessible.
- **Color-only information:** Timeline bars use CSS class to distinguish roles; each `<div>` has a `title` attribute as a partial mitigation (screen readers won't read `title` without a gesture).
- **Color contrast — amber badge:** `.badge.kind-scope_creep` uses `#d29922` background with `#fff` text at `.7rem` bold — contrast ≈ 2.9:1, likely fails WCAG AA (needs 4.5:1).
- **`lang` attribute:** `<html lang="en">` present. Correct.
- **Skip-to-content link:** Not present. Low severity for a single-use generated report.

### Textual TUI (`cctx trace`)

- **Keyboard navigation:** `DataTable` arrow keys, `Enter` opens `ToolResultModal`, `f` opens `FindingModal`, `?` opens `HelpScreen`, `q`/`Escape` dismiss. All in the Footer. Complete.
- **Color-only information:** Flagged turns use `[bold red]` markup for all cells; the `Flags` column carries the kind name as text — redundant non-color cue. Conforming.
- **FindingModal:** Renders `f.kind.value` raw — usable but inconsistent.

### Terminal output (rich)

No interactive elements. Standard terminal accessibility. No cctx-specific issues.

---

## 3. Frontend Code Quality

### Component architecture

The 4 renderer files are appropriately narrow (none exceeds 540 lines). Layering rules substantially honored, two exceptions:

1. `discovery.py:170` does `from click.shell_completion import CompletionItem` — crosses the "only `cli.py` imports `click`" boundary (deferred import inside a shell_complete callback).
2. `_render_check_findings()` in `cli.py:150-181` uses `rich.Console`/`rich.Rule` directly — rendering logic in the CLI layer. Belongs in `terminal.py`.

### `launch()` in `trace_tui.py` — nested class anti-pattern

`launch()` (line 75) carries `# noqa: C901` and contains 4 nested class definitions plus `TraceTUI().run()` — ~220 lines in a single function body. The deferred-import rationale is real, but the UI classes can't be unit-tested as written.

### Performance

No obvious bottlenecks. All rendering is synchronous and single-pass. The watcher polls at 1s — known limitation.

### Test coverage of renderer layer

Good coverage of the original 3 finding kinds. Neither `test_terminal_renderer.py` nor `test_report.py` exercises the 8 newer kinds. The HTML badge CSS bug would have been caught by a test that instantiates a `TOOL_THRASH` finding and asserts the badge class has a styled background color.

---

## 4. Responsive Spot-Check

**Terminal width robustness:**
- `autopsy` output inherits terminal width; Rich wraps gracefully.
- `render_efficacy_report` uses `no_wrap=True` columns; the signal is printed separately per row to avoid truncation. Well-considered.
- TUI DataTable fixed columns total ~84 chars minimum. Fits 80-col terminals barely; long Flags content (e.g. `"exploration_thrash, cache_hygiene"`) overflows the 22-char column.

**HTML report (`--html`):**
- `<meta name="viewport">` present (line 5).
- `max-width: 900px; margin: 0 auto` on `<main>`; `padding: 2rem 1rem` on body.
- Timeline uses `flex-wrap: wrap`; costs `<dl>` uses `grid-template-columns: auto 1fr`. No horizontal overflow expected at 375px.

---

## Critical (fix this week)

**C1. HTML badge CSS missing for 8 of 11 finding kinds.** *(tracked: #128)*
Any session with `TOOL_THRASH`, `DEAD_END`, `FANOUT_WASTE`, `CACHE_HYGIENE`, `COMPACTION`, `EXPLORATION_THRASH`, `UNUSED_CONTEXT`, or `PROJECT_PATTERN` findings renders invisible badges. Add CSS rules (neutral fallback `.badge[class*="kind-"]` plus per-kind colors).
File: `cctx/renderers/templates/autopsy.html.j2`

**C2. `github.py` renders raw enum values for 6 of 11 finding kinds.** *(tracked: #129)*
`fanout_waste`, `project_pattern`, `cache_hygiene`, `compaction`, `exploration_thrash`, `unused_context` fall through to `f.kind.value`. Replace the local dict with `from cctx.models import KIND_LABEL`; key by enum member.
File: `cctx/renderers/github.py`

---

## Important (fix this month)

**I1. TUI `FindingModal` uses raw `f.kind.value`.** *(tracked: #136)* — `trace_tui.py:115`.
**I2. Harvest patch panel title uses raw `finding_kind.value`.** *(tracked: #136)* — `terminal.py:341`.
**I3. Verdict format inconsistency across surfaces.** *(tracked: #139)* — terminal kind-based vs TUI/HTML count-based. Canonize count-based as the headline.
**I4. `Diagnosis.verdict` returns lowercase `"clean session"`.** *(tracked: #138)* — `models.py:276`.
**I5. `_render_check_findings()` rendering logic inside `cli.py`.** *(tracked: #135)* — move to `terminal.py`.
**I6. DESIGN.md documents stale product state.** *(resolved: PR #147)* — kind count, verdict format, evidence rendering TODO, `.3f` format, TUI FindingModal TODO.

---

## Track (revisit next review)

**T1. `launch()` in `trace_tui.py` — 220-line function with 4 nested classes.** *(tracked: #146)*
**T2. `_wide_console()` in `terminal.py:43` — dead code.** *(tracked: #144)*
**T3. `group_into_exchanges()` in `models.py:342` — tested but unused by renderers.** *(tracked: #144)*
**T4. `discovery.py:170` imports from `click.shell_completion`.** *(tracked: #134)*
**T5. HTML timeline encodes role via color only (partial `title` mitigation).**
**T6. HTML amber badge contrast** (`.badge.kind-scope_creep` likely fails WCAG AA at small size).
**T7. Renderer test coverage gap for newer finding kinds.** *(tracked: #143)*

---

## Metrics Snapshot

| Metric | Value |
|---|---|
| Renderer files | 4 Python modules + 1 Jinja2 template |
| Total renderer lines | 976 Python + 265 HTML/CSS (template) = 1,241 |
| CSS (inline in template) | ~160 lines in single `<style>` block; no external files |
| Renderer test files | 5 |
| Accessibility issues — Critical | 0 |
| Accessibility issues — Moderate | 2 (timeline color-only, amber badge contrast) |
| Accessibility issues — Low | 1 (no skip-link in HTML) |
| Design system deviations | 6 (C1, C2, I1, I2, I3, I4) |
| KIND_LABEL divergences | 3 implementations |
| HTML badge CSS gaps | 8 of 11 finding kinds |
| Unused code | 2 items (_wide_console, group_into_exchanges) |
| DESIGN.md stale items | 5 (resolved by PR #147) |

---

## Previous Reviews

No prior frontend reviews. This is the baseline. No trend comparison available.
