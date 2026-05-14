# cctx

Open-source Python CLI that diagnoses individual Claude Code sessions: when they went wrong, why they went wrong, what they cost, and what to add to your `CLAUDE.md` so it doesn't happen again. Reads the JSONL session logs Claude Code writes to `~/.claude/projects/` and produces actionable autopsy reports.

The complete product pitch, example outputs, growth staircase, and positioning vs. adjacent tools are in [`cctx-project-brief.md`](cctx-project-brief.md). Read it once.

## Tech stack

- **Python 3.10+**
- **click** — CLI argument parsing and subcommand routing
- **rich-click** — re-skins click's `--help` through rich (drop-in: `import rich_click as click`). Pure shininess win on the `--help` surface, no behavioral cost
- **rich** — terminal output: tables, banners, severity badges, diff blocks
- **textual** — the TUI for `cctx trace`
- **anthropic** — token counting only, via `anthropic.messages.count_tokens` in the tokenizer module. **Not imported anywhere else.**
- **pandas** — optional, only inside the cross-session aggregator if/when row-level work justifies it. Stdlib-first.
- **Jinja2** — HTML report templates for `cctx autopsy --html`

Explicitly not used: web frameworks, databases, ORMs, async runtimes, cloud SDKs. cctx is a local CLI.

## Architecture

```
Session log (Claude Code JSONL on disk)
  ↓
Parser           ← dependency-free; takes a path, returns SessionTrace
  ↓
Tokenizer        ← only place that imports anthropic; offline-mode safe for CI
  ↓
Diagnostician    ← per-turn investigation: inflection detection + pattern
                   classifiers (retry loop, scope creep, stale context).
                   Produces a Diagnosis.
  ↓
Recommender      ← turns Findings into Patches: copy-pasteable CLAUDE.md /
                   rule / skill diffs, evidence-backed when cross-session.
  ↓
Renderers        ← rich (terminal), Jinja2 (HTML report), textual (trace
                   TUI overlay).
  ↓
Exporters        ← jsonl, csv, html, json.
```

## Project layout

```
cctx/
├── cli.py              # click + rich-click; routes to autopsy / trace / export
├── parsers/
│   └── claude_code.py  # SHIPPED. Parse ~/.claude JSONL logs.
│                       # Spec: docs/superpowers/specs/2026-05-12-claude-code-parser-design.md
├── tokenizer.py        # SHIPPED. anthropic.count_tokens wrapper; CCTX_OFFLINE heuristic.
├── models.py           # SHIPPED. Turn, ToolUse, ToolResult, Usage, Attachment,
│                       # RawToolResultFile, SessionTrace + group_into_exchanges().
│                       # M2 extends with Finding, Patch, Diagnosis.
├── diagnostician/
│   ├── __init__.py     # public: run(trace) -> Diagnosis
│   ├── inflection.py   # detect the turn where the session diverged
│   ├── patterns/
│   │   ├── retry_loop.py
│   │   ├── scope_creep.py
│   │   └── stale_context.py
│   └── aggregate.py    # cross-session pattern aggregator (--since mode)
├── recommender/
│   ├── claude_md.py    # Finding -> Patch (CLAUDE.md diff proposals)
│   └── evidence.py     # session-count + dollar evidence accumulation
├── renderers/
│   ├── terminal.py     # rich rendering of a Diagnosis
│   ├── report.py       # Jinja2 HTML report (cctx autopsy --html)
│   └── trace_tui.py    # textual TUI with autopsy findings overlaid
└── exporters/
    ├── jsonl.py
    ├── csv.py
    ├── html.py
    └── json.py
```

## Layering rules (enforced by convention)

These keep the dependency graph clean so modules stay independently testable and refactorable:

- **Parsers never import the tokenizer, the anthropic SDK, or any analyzer.** A parser takes a path and returns a `SessionTrace` with `token_count: int = 0` placeholders.
- **Tokenizer is the only module that imports `anthropic`.** Everyone else gets token counts pre-populated on the dataclasses.
- **Analyzers (diagnostician, recommender, aggregate) never import each other across boundary lines.** Inside the diagnostician package, helpers can compose freely. The recommender takes a Diagnosis and emits Patches without reaching back into the diagnostician's internals.
- **Renderers never compute analysis.** They take an analyzer's output and render it. Swapping `terminal.py` for `report.py` should not change a single number or finding.
- **Only `cli.py` imports `click` and `rich_click`.** Everything else uses plain `rich.Console` if it needs to output. Analyzers and parsers return data; the CLI decides how to display it.

## Core design decisions

These came out of the brief, the parser brainstorming session, and the autopsy pivot. They apply across the entire codebase:

- **Diagnose the specific session, not the aggregate.** cctx is forensic. CodeBurn covers daily cost tracking; cctx is "what went sideways here, and what do I add to CLAUDE.md so it doesn't happen again."
- **Token-turns is a useful metric for stale-content attribution.** `tokens × turns_present`, compaction-aware. A 22K grep result sitting in context for 14 turns after its last reference costs ~310K token-turns of waste. This is how stale-context findings attribute their dollar cost.
- **Approximate decomposition is fine.** Reconstructing the API request from the JSONL gets you ~85–95% of the actual `input_tokens`. The remainder is internal framing you can't observe. The system internals slice is honest; don't pretend to be exact.
- **Binary waste detection only in v1.** "Loaded but never called" is high-confidence. "Partially used" is fragile. Ship the binary version.
- **Patches must be copy-pasteable.** Every Patch carries a unified diff against a target file (CLAUDE.md, rules, skill, ADR). Lower the barrier to action to zero.
- **Single-session AND cross-session, same diagnostician.** `cctx autopsy <session>` and `cctx autopsy <project> --since <window>` go through the same per-session pipeline; the aggregator runs after.
- **Group up, never down.** Parse at the finest granularity the source provides (per JSONL line). Aggregate in the view layer. (Originated in the parser design — applies everywhere.)
- **Empirical evidence collapses speculative complexity.** Before designing for a hypothetical case, scan real data. The parser spec's tool-result handling was simplified by 80% after one 30-line empirical scan.
- **Deterministic over LLM-assisted in v0.** Pattern classifiers use heuristics, not LLM calls. (Future v1+ harvest may invoke an LLM for summarization, opt-in with API key.) The deterministic core has predictable cost and is testable on fixtures.

## Build order (post-pivot)

1. **M0 — Project setup.** SHIPPED. (#1)
2. **M1 — Foundation.** SHIPPED — parser, tokenizer, models, fixtures, CI. (#2–#6, plus PR #38)
3. **M2 — Autopsy v0.** Single-session diagnosis + cross-session pattern detection. The wedge product. (#9, #10, #40–#49)
4. **M3 — Trace TUI** with autopsy overlay. (#20, #21)
5. **M4 — Export.** jsonl + csv + html + json. (#24, #27)
6. **M5 — Harvest v1.** Promote autopsy findings to durable CLAUDE.md / rules / skill / ADR diffs. (Issues TBD after autopsy lands.)
7. **M6 — Release v0.1.0.** README polish + PyPI publish. (#31, #32)

Future, not yet milestoned:
- **Memory hygiene** (`cctx harvest --check`) — audit existing CLAUDE.md and memory files for staleness / contradictions / dead skills.
- **Live mode** (`cctx watch`) — filesystem watcher on `~/.claude/projects` to surface waste signals during a session.
- **Cross-agent layer** — emit the same captured knowledge as `.cursorrules`, `AGENTS.md`, `.windsurfrules`, GitHub Copilot instructions.

## Design docs

Feature designs live in `docs/superpowers/specs/`, dated and committed before implementation begins. Each implementation plan in `docs/superpowers/plans/` references its spec. Don't start a feature without one.

Current specs landed on main:
- `docs/superpowers/specs/2026-05-12-claude-code-parser-design.md` — the Claude Code JSONL parser.

In progress / pending:
- `docs/superpowers/specs/<date>-autopsy-design.md` — autopsy v0 design (#40). The next spec to be brainstormed.

## GitHub issue structure

The post-pivot board is anchored to autopsy. New work should follow the same conventions so the board stays coherent.

**Granularity.** One issue = one PR. If a ticket can't reasonably land in a single PR, split it. Cross-cutting infrastructure gets its own ticket rather than being buried inside the first consumer. Test fixtures that block a feature get their own ticket. High-polish or novel surfaces (e.g. the TUI) split into spec + implementation.

**Milestones.** Phases get milestones (`M0 — Project setup` through `M6 — Release v0.1.0`). Every issue belongs to exactly one milestone. Add a new milestone if a phase is genuinely new; don't reuse an existing milestone for unrelated work.

**Labels.** Use `area:*` labels only (parser, analyzer, cli, renderer, exporter, tokenizer, tui, models, infra, docs). An issue can have multiple `area:` labels if it touches multiple layers. Don't invent new label taxonomies (priority, type, status) — milestones + the issue board cover that.

**Body template.** Every issue has these sections, in this order:

```markdown
**Phase:** Mn — <phase name>
**Module:** `path/to/file.py` (or files plural)

## Goal
One paragraph: what this delivers and why.

## Acceptance criteria
- [ ] Spec at `docs/superpowers/specs/<date>-<slug>.md` reviewed first (if a spec is warranted — see below)
- [ ] Concrete, testable items
- [ ] Tests that prove the behavior
- [ ] Layering invariants honored (e.g. "no imports from `anthropic`")

## Files
- Exact paths the PR touches

## References
- Brief sections, prior spec sections, CLAUDE.md sections

## Blocked by
- (Posted as a comment with `#N` references after all related issues are filed — GitHub auto-links and surfaces the dependency graph.)
```

**Spec gate inside the ticket.** CLAUDE.md requires specs before implementation. The default is **the spec is the first acceptance-criteria checkbox in the implementation ticket**, not a separate ticket. Exceptions: surfaces big enough that the spec is itself a meaningful deliverable (the autopsy v0 design is #40 — separate from the implementation tickets that consume it).

**Dependencies.** After filing a batch of issues, post a comment on each blocked ticket: `Blocked by #N, #M`. GitHub auto-links and shows the parent/child relationship in the timeline. Don't try to encode the dep graph in the issue body — it goes stale and is painful to maintain.

**Granularity smell tests** (use these when proposing a new ticket):
- *Too thick* — needs two specs, two reviewers, or PRs in two different areas (`area:parser` + `area:cli`). Split along the layering boundary.
- *Too thin* — the entire ticket fits in a 5-line PR with no tests. Combine with its sibling.
- *Hidden dependency* — the work assumes something exists that isn't filed yet. File that first or note it as blocked-by.

## Working in this repo

- The brief is authoritative for product scope. Don't rewrite it during implementation; if scope needs to change, amend the brief deliberately.
- Specs are authoritative for module design. Don't deviate during implementation without updating the spec.
- When implementing a feature: write the spec, get it reviewed, then write the plan (via the superpowers `writing-plans` skill), then implement.
- The parser is dependency-free by design. If you find yourself adding `import anthropic` or `import click` inside `parsers/`, stop — that work belongs in `tokenizer.py` or `cli.py`.
- The tokenizer's offline mode (`CCTX_OFFLINE=1`) is the default for CI and tests. Live tokenization happens only when the CLI explicitly opts in and `ANTHROPIC_API_KEY` is set.
