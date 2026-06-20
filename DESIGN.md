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

## Cost formatting

| Context | Format | Example |
|---|---|---|
| User-facing summary (verdict, totals) | `:.2f` | `$1.42` |
| Per-subagent cost line items (subagent table) | `:.3f` | `$0.214` |
| Per-finding detail | `:.4f` | `$0.0082` |

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

The `KIND_LABEL` dict in **`cctx/models.py`** is the single source of truth. Every user-facing surface imports it and keys by the `FindingKind` enum member: `terminal.py` (findings list + patch-panel title), `github.py`, `cli.py` (`--quiet`), and `trace_tui.py` (`finding_modal_text`/`flags_label`). As of M22 there are no local kind-label dicts in any renderer. The HTML template carries one explicit `.badge.kind-<value>` CSS rule per `FindingKind`; the badge *text* still uses the inline `.replace("_", " ").upper()` transform, which is equivalent to `KIND_LABEL` for today's all-underscore enum values.

## Verdict string

The canonical headline is **count-based** and comes from a single source — the
`Diagnosis.verdict` property in `models.py`. Every surface renders it identically:

| State | `Diagnosis.verdict` |
|---|---|
| No findings | `"Clean session"` |
| With findings | `"{n} finding(s) · ${waste:.2f} waste"` (e.g. `"2 findings · $0.34 waste"`) |

- `terminal.py`, the HTML template, and `trace_tui.verdict()` all delegate to `Diagnosis.verdict` — no surface recomputes the format.
- Kind names render as a **secondary row** via the separate `Diagnosis.kind_summary` property (`"RETRY LOOP + SCOPE CREEP"`, deduped and ordered; empty when clean). The terminal prints it as a dim line under the verdict; per-finding badges carry the same information on the other surfaces.

## Evidence rendering

| Surface | Rendering |
|---|---|
| Terminal | `finding.summary` inline text + `→ savings if fixed` line |
| HTML report | Per-finding `<details>` with evidence as formatted JSON |
| TUI FindingModal | Summary + raw evidence |

`Finding.evidence` is a `dict[str, Any]` whose shape varies per `FindingKind` (e.g. `retry_loop` carries `occurrences`/`loop_length`; `stale_context` carries `stale_items`/`total_token_turns`). The recommender reads specific keys with `.get()` fallbacks. The authoritative per-kind schema lives in each producing classifier's module docstring under an `Evidence (Finding.evidence, kind=...)` block (e.g. `cctx/diagnostician/patterns/retry_loop.py`); `recommender/claude_md.py:summarize()` points back to it.

## Anti-patterns

- **Never** use `red` style for success states (APPLIED patch = success = green)
- **Never** render evidence dicts as raw `json.dumps` in the primary user-facing path (HTML `<details>` area is OK)
- **Never** define CSS syntax-highlighting classes without corresponding template markup to apply them
- **Never** add a badge/kind class name in a template without a matching CSS rule for every `FindingKind` (the gap is invisible in review — it only shows up as an unstyled badge at render time)
- **Never** define a local `_KIND_LABEL` inside a renderer; import `KIND_LABEL` from `cctx.models` and key by the `FindingKind` enum member, not the `.value` string
- **Never** import `click` or `rich_click` outside `cli.py`
