# cctx Design System

Reference for the three output surfaces: Rich terminal, Textual TUI, Jinja2 HTML report.

## Color palette (terminal/TUI)

| State | Rich style |
|---|---|
| HIGH severity | `bold red` |
| MEDIUM severity | `bold yellow` |
| LOW severity | `bold green` |
| Applied/success | `green` |
| Error/failure | `red` |
| Skipped/neutral | `dim` |

## Color palette (HTML report badges)

Every `.badge` pair must clear **WCAG AA 4.5:1**. `.badge` renders at `.7rem`
(11.2px against the 16px root) with `font-weight: 700` — below the 18.66px bold
threshold for the large-text exemption, so the normal-text floor applies.
Enforced for every rule, present and future, by
`tests/renderers/test_report_contrast.py`.

| Class | Background | Text | Ratio |
|---|---|---|---|
| `kind-retry_loop` | `#cf222e` | `#fff` | 5.36 |
| `kind-scope_creep` | `#bc4c00` | `#fff` | 5.03 |
| `kind-stale_context` | `#0550ae` | `#fff` | 7.59 |
| `kind-tool_thrash` | `#bc4b81` | `#fff` | 4.71 |
| `kind-dead_end` | `#8957e5` | `#fff` | 4.61 |
| `kind-fanout_waste` | `#1a7f37` | `#fff` | 5.08 |
| `kind-project_pattern` | `#1f6feb` | `#fff` | 4.63 |
| `kind-cache_hygiene` | `#9e6a03` | `#fff` | 4.65 |
| `kind-compaction` | `#57606a` | `#fff` | 6.39 |
| `kind-exploration_thrash` | `#bf3989` | `#fff` | 5.05 |
| `kind-unused_context` | `#6639ba` | `#fff` | 7.34 |
| `sev-high` | `#6e1507` | `#ff8182` | 4.91 |
| `sev-medium` | `#4d3500` | `#d29922` | 4.56 |
| `sev-low` | `#033a16` | `#3fb950` | 5.10 |
| `sub-label` | `#30363d` | `#adbac7` | 6.17 |

Colors are Primer-scale so new badges sit with the existing set. Color is a
secondary signal only — every badge also carries its kind or severity as text.

## Cost formatting

| Context | Format | Example |
|---|---|---|
| User-facing summary (verdict, totals) | `:.2f` | `$1.42` |
| Per-subagent cost line items (subagent table) | `:.3f` | `$0.214` |
| Per-finding detail (HTML finding cost, terminal "savings if fixed") | `:.4f` | `$0.0082` |

## Finding kind labels

Canonical display form is space-separated uppercase. Never use the raw enum value in user-facing output.

| Enum value | Display label |
|---|---|
| `retry_loop` | `RETRY LOOP` |
| `scope_creep` | `SCOPE CREEP` |
| `stale_context` | `STALE CONTEXT` |
| `tool_thrash` | `TOOL THRASH` |
| `dead_end` | `DEAD END` |
| `fanout_waste` | `FANOUT WASTE` |
| `project_pattern` | `PROJECT PATTERN` |
| `cache_hygiene` | `CACHE HYGIENE` |
| `compaction` | `COMPACTION` |
| `exploration_thrash` | `EXPLORATION THRASH` |
| `unused_context` | `UNUSED CONTEXT` |

The `KIND_LABEL` dict in **`cctx/models.py`** is the single source of truth. Every user-facing surface imports it and keys by the `FindingKind` enum member: `terminal.py` (findings list + patch-panel title), `github.py`, `cli.py` (aggregate drill-down + check findings), and `trace_tui.py` (`finding_modal_text`/`flags_label`). As of M22 there are no local kind-label dicts in any renderer. The HTML template carries one explicit `.badge.kind-<value>` CSS rule per `FindingKind`; the badge *text* still uses the inline `.replace("_", " ").upper()` transform, which is equivalent to `KIND_LABEL` for today's all-underscore enum values.

## Verdict string

The canonical headline is **count-based** and comes from a single source — the
`Diagnosis.verdict` property in `models.py`. Every surface renders it identically:

| State | `Diagnosis.verdict` |
|---|---|
| No findings | `"Clean session"` |
| With findings | `"{n} finding · ${waste:.2f} waste"` when `n == 1`, else `"{n} findings · …"` (e.g. `"2 findings · $0.34 waste"`) |

- `terminal.py`, the HTML template, `trace_tui.verdict()`, `github.py`, and `cli.py --quiet` all delegate to `Diagnosis.verdict` — no surface recomputes the format. A surface may decorate *around* the string (`github.py` prefixes `**Result:** ✅` when clean and appends `(N% of session cost)` when dirty; `--quiet` appends `— {kind_summary}`), but the `Diagnosis.verdict` string itself always appears verbatim. There is no sanctioned exception.
- Kind names render as a **secondary row** via the separate `Diagnosis.kind_summary` property (`"RETRY LOOP + SCOPE CREEP"`, deduped and ordered; empty when clean). The terminal prints it as a dim line under the verdict; per-finding badges carry the same information on the other surfaces.

## Evidence rendering

| Surface | Rendering |
|---|---|
| Terminal | `finding.summary` inline text + `→ savings if fixed` line |
| HTML report | Per-finding `<details>` with evidence as formatted JSON |
| TUI FindingModal | Summary + raw evidence |

`Finding.evidence` is a `dict[str, Any]` whose shape varies per `FindingKind` (e.g. `retry_loop` carries `occurrences`/`loop_length`; `stale_context` carries `stale_items`/`total_token_turns`). The authoritative per-kind schema lives in each producing classifier's module docstring under an `Evidence (Finding.evidence, kind=...)` block (e.g. `cctx/diagnostician/patterns/retry_loop.py`); `recommender/claude_md.py:summarize()` points back to it.

**Three kinds carry typed nested items** — `RETRY_LOOP` (`RetryOccurrence`), `SCOPE_CREEP` (`ScopeCreepPhrase`), and `STALE_CONTEXT` (`StaleItem`), all frozen dataclasses in `cctx/models.py`. They were typed because they are the kinds with more than one consumer: `recommender/claude_md.py:summarize()` and `renderers/trace_tui.py:affected_turns()` both read their nested fields, and previously disagreed on access style — one subscripted and would `KeyError`, the other guarded with `in` and silently degraded. Top-level keys are still read with `.get()` fallbacks so absent evidence degrades to `finding.summary`. The other 8 kinds stay untyped; escalate a kind when a second consumer starts reading its nested items.

## Anti-patterns

- **Never** use `red` style for success states (APPLIED patch = success = green)
- **Never** render evidence dicts as raw `json.dumps` in the primary user-facing path (HTML `<details>` area is OK)
- **Never** define CSS syntax-highlighting classes without corresponding template markup to apply them
- **Never** add a badge/kind class name in a template without a matching CSS rule for every `FindingKind` (the gap is invisible in review — it only shows up as an unstyled badge at render time)
- **Never** define a local `_KIND_LABEL` inside a renderer; import `KIND_LABEL` from `cctx.models` and key by the `FindingKind` enum member, not the `.value` string
- **Never** ship a `.badge` rule whose text/background pair falls below WCAG AA 4.5:1 — badges are below the large-text threshold, so the normal-text floor applies
- **Never** import `click` or `rich_click` outside `cli.py`
