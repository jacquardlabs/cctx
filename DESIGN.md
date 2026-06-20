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

The `KIND_LABEL` dict in **`cctx/models.py`** is the single source of truth (`terminal.py` imports it as `_KIND_LABEL = KIND_LABEL`). Always import it and key by the `FindingKind` enum member.

Two surfaces currently diverge from this and are tracked as bugs:
- `renderers/github.py` defines a local 5-entry `_KIND_LABEL` keyed by `.value` string and falls back to the raw enum value for 6 kinds (tracked in #129).
- The HTML template uses `.replace("_", " ").upper()` inline — equivalent for today's all-underscore kinds, but will diverge if a future kind uses a non-underscore separator, and lacks per-kind badge CSS for 8 kinds (tracked in #128).

## Verdict string

Two formats are live, and the surfaces currently disagree:

| Format | Source | Surfaces |
|---|---|---|
| Kind-based: `"RETRY LOOP + SCOPE CREEP"` | `Diagnosis.verdict` (`models.py`) | Terminal |
| Count-based: `"{n} finding(s) · ${waste:.2f} waste"` | `renderers/trace_tui.py:verdict()`, HTML template | TUI, HTML report |

The clean-session string also diverges: `Diagnosis.verdict` returns lowercase `"clean session"` (terminal inherits it), while the TUI and HTML hard-code `"Clean session"`. The capitalized form is canonical (tracked in #138).

**Recommended canonical:** count-based headline (`"{n} finding(s) · ${waste:.2f} waste"`) with kind names rendered as a secondary badge row — it is more scannable and already used by two of three surfaces. Unifying the three surfaces on one format is tracked in #139. Until that lands, document the divergence here rather than pretend it is resolved.

## Evidence rendering

| Surface | Rendering |
|---|---|
| Terminal | `finding.summary` inline text + `→ savings if fixed` line |
| HTML report | Per-finding `<details>` with evidence as formatted JSON |
| TUI FindingModal | Summary + raw evidence |

`Finding.evidence` is a `dict[str, Any]` whose shape varies per `FindingKind` (e.g. `retry_loop` carries `occurrences`/`loop_length`; `stale_context` carries `stale_items`/`total_token_turns`). The recommender reads specific keys with `.get()` fallbacks. Documenting the per-kind evidence schema is tracked in #145.

## Anti-patterns

- **Never** use `red` style for success states (APPLIED patch = success = green)
- **Never** render evidence dicts as raw `json.dumps` in the primary user-facing path (HTML `<details>` area is OK)
- **Never** define CSS syntax-highlighting classes without corresponding template markup to apply them
- **Never** add a badge/kind class name in a template without a matching CSS rule for every `FindingKind` (the gap is invisible in review — it only shows up as an unstyled badge at render time)
- **Never** define a local `_KIND_LABEL` inside a renderer; import `KIND_LABEL` from `cctx.models` and key by the `FindingKind` enum member, not the `.value` string
- **Never** import `click` or `rich_click` outside `cli.py`
