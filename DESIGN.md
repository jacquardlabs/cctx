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
| Per-finding detail | `:.4f` | `$0.0082` |

## Finding kind labels

Canonical display form is space-separated uppercase. Never use the raw enum value in user-facing output.

| Enum value | Display label |
|---|---|
| `retry_loop` | `RETRY LOOP` |
| `scope_creep` | `SCOPE CREEP` |
| `stale_context` | `STALE CONTEXT` |

Use `_KIND_LABEL` dict in `renderers/terminal.py` as the source of truth. The HTML template currently uses `.replace("_", " ").upper()` inline — this is equivalent for the three current kinds but will diverge if a new kind uses a non-underscore separator.

## Verdict string

Format across all surfaces: `"Clean session"` (no findings) or `"{n} finding(s) · ${waste:.2f} waste"` (with findings).

The brief examples use `"⚠ retry loop + scope creep"` (kind-based) — that is a future format, not yet implemented.

## Evidence rendering

| Surface | Rendering |
|---|---|
| Terminal | `finding.summary` inline text |
| HTML report | Per-finding `<details>` with evidence as formatted JSON (TODO: structured per-kind in v0.2) |
| TUI FindingModal | Summary + raw evidence (TODO: structured per-kind in v0.2) |

## Anti-patterns

- **Never** use `red` style for success states (APPLIED patch = success = green)
- **Never** render evidence dicts as raw `json.dumps` in the primary user-facing path (HTML verdict area is OK for v0; structured per-kind in v0.2)
- **Never** define CSS syntax-highlighting classes without corresponding template markup to apply them
- **Never** import `click` or `rich_click` outside `cli.py`
