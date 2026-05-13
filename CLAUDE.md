# cctx

Open-source Python CLI suite that profiles, debugs, and optimizes Claude Code and Agent SDK sessions. Reads the JSONL session logs Claude Code already writes to `~/.claude/projects/` and turns them into actionable reports.

The complete project pitch, subcommand catalogue, example outputs, and product positioning are in [`cctx-project-brief.md`](cctx-project-brief.md). Read it once.

## Tech stack

- **Python 3.10+**
- **click** — CLI argument parsing and subcommand routing
- **rich-click** — re-skins click's `--help` through rich (drop-in: `import rich_click as click`). Pure shininess win on the `--help` surface, no behavioral cost
- **rich** — terminal output: tables, colors, sparklines, progress bars, the warn-and-skip banner
- **textual** — the TUI for `cctx trace`
- **anthropic** — token counting only, via `anthropic.count_tokens()` in the tokenizer module. **Not imported anywhere else.**
- **pandas** — multi-session aggregation in `cctx analyze`
- **Jinja2** — HTML report templates for `--html` flag

Explicitly not used: web frameworks, databases, ORMs, async runtimes, cloud SDKs. cctx is a local CLI.

## Architecture

```
Session log (JSONL / SDK trace / Promptfoo JSON)
  ↓
Parser           ← dependency-free; takes a path, returns SessionTrace
  ↓
Tokenizer        ← only place that imports anthropic
  ↓
Decomposer       ← reads MCP configs + CLAUDE.md to enrich names
  ↓
Analyzers        ← one per subcommand, composable
  ↓
Renderers        ← rich (terminal), textual (TUI), Jinja2 (HTML)
  ↓
Exporters        ← jsonl, csv, otel, parquet
```

## Project layout

```
cctx/
├── cli.py              # click + rich-click; routes to subcommands
├── parsers/
│   ├── claude_code.py  # parse ~/.claude JSONL logs (designed in docs/superpowers/specs/2026-05-12-claude-code-parser-design.md)
│   ├── agent_sdk.py    # parse Agent SDK trace output
│   └── promptfoo.py    # parse Promptfoo eval JSON
├── tokenizer.py        # wrapper around anthropic.count_tokens(); the only file allowed to import anthropic
├── models.py           # Turn, ToolUse, ToolResult, Usage, Attachment, RawToolResultFile, SessionTrace + group_into_exchanges() helper
├── analyzers/
│   ├── decomposer.py   # context decomposition (used by profile)
│   ├── waste.py        # waste detection (used by profile, analyze)
│   ├── cost.py         # cost attribution (used by cost, analyze)
│   ├── tools.py        # tool efficiency (used by tools)
│   ├── loops.py        # loop/retry detection (used by loops)
│   ├── latency.py      # timing analysis (used by slow)
│   ├── lint.py         # config static analysis (used by lint)
│   ├── variance.py     # consistency analysis (used by bench)
│   └── aggregator.py   # multi-session stats (used by analyze)
├── renderers/
│   ├── terminal.py     # rich tables, sparklines
│   ├── flamegraph.py   # HTML flamegraph template (Jinja2)
│   └── tui.py          # textual TUI for trace viewer
└── exporters/
    ├── jsonl.py
    ├── csv.py
    ├── otel.py
    └── parquet.py
```

## Layering rules (enforced by convention)

These keep the dependency graph clean so modules stay independently testable and refactorable:

- **Parsers never import the tokenizer, the anthropic SDK, or any analyzer.** A parser takes a path and returns a `SessionTrace` with `token_count: int = 0` placeholders.
- **Tokenizer is the only module that imports `anthropic`.** Everyone else gets token counts pre-populated on the dataclasses.
- **Analyzers never import each other.** They share data via `SessionTrace` and `SessionSummary`. The aggregator composes them, not the analyzers themselves.
- **Renderers never compute analysis.** They take an analyzer's output and render it. Swapping `terminal.py` for `flamegraph.py` should not change a single number.
- **Only `cli.py` imports `click` and `rich_click`.** Everything else uses plain `rich.Console` if it needs to output. Analyzers and parsers return data; the CLI decides how to display it.

## Core design decisions

These came out of the brief and the parser brainstorming session. They apply across the entire suite:

- **Token-turns is the key metric.** `tokens × turns_present`. A component's current size doesn't capture its real cost — a 24K tool description block loaded at turn 1 and present for 25 turns is 600K token-turns. Rank everything by this.
- **Approximate decomposition is fine.** Reconstructing the API request from the JSONL gets you ~85–95% of the actual input_tokens. The remainder is internal framing you can't observe. Show it as a "system internals" slice. Don't pretend to be exact.
- **Binary waste detection only in v1.** "Loaded but never called" is high-confidence and trivially detectable. "Partially used" requires embeddings and is fragile. Ship the binary version.
- **Recommendations must be copy-pasteable.** Every recommendation includes the exact config change, env var, or hook definition. Lower the barrier to action to zero.
- **Single-session AND multi-session, same analyzers.** Where it makes sense, subcommands accept either a session path or a project path with `--since`. Same analyzer, different aggregation level.
- **Group up, never down.** Parse at the finest granularity the source provides. Aggregate in the view layer. (Originated in the parser design — applies everywhere.)
- **Empirical evidence collapses speculative complexity.** Before designing for a hypothetical case, scan real data. The parser spec's tool-result handling was simplified by 80% after one 30-line empirical scan.

## Build order (from the brief)

1. **`cctx profile` + `cctx analyze`** — parser, tokenizer, decomposer, waste detection, aggregation. The foundation.
2. **`cctx cost` + `cctx tools`** — reuses step 1's modules.
3. **`cctx loops` + `cctx slow`** — pattern matching on traces.
4. **`cctx lint`** — different data source (config files), simple and useful.
5. **`cctx trace`** — TUI, highest polish.
6. **`cctx bench`** — requires running agents, ship last.
7. **`cctx export` + `cctx compare`** — utilities.

## Design docs

Feature designs live in `docs/superpowers/specs/`, dated and committed before implementation begins. Each implementation plan in `docs/superpowers/plans/` references its spec. Don't start a feature without one.

Current specs:
- `docs/superpowers/specs/2026-05-12-claude-code-parser-design.md` — the Claude Code JSONL parser.

## GitHub issue structure

The initial breakdown of the brief into trackable work lives in issues #1–#32. New work should follow the same conventions so the board stays coherent.

**Granularity.** One issue = one PR. If a ticket can't reasonably land in a single PR, split it. Cross-cutting infrastructure (e.g. the recommendations engine, used by seven subcommands) gets its own ticket rather than being buried inside the first consumer. Test fixtures that block a parser get their own ticket. High-polish or novel surfaces (e.g. the TUI) split into spec + implementation.

**Milestones.** Build-order phases get milestones (`M0 — Project setup` through `M10 — Release v0.1.0`). Every issue belongs to exactly one milestone. Add a new milestone if a phase is genuinely new; don't reuse an existing milestone for unrelated work.

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
- Brief sections, parser spec sections, CLAUDE.md sections

## Blocked by
- (Posted as a comment with `#N` references after all related issues are filed — GitHub auto-links and surfaces the dependency graph.)
```

**Spec gate inside the ticket.** CLAUDE.md requires specs before implementation. The default is **the spec is the first acceptance-criteria checkbox in the impl ticket**, not a separate ticket. Exceptions: surfaces big enough that the spec is itself a meaningful deliverable (the TUI is the example in the initial set — #20 is spec, #21 is implementation).

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
