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

**Multi-provider.** `parsers/otel.py` (shipped v1.12.0) parses OTLP `gen_ai.*` spans, so `cctx autopsy <trace>` also diagnoses OpenAI Agents SDK and LangGraph sessions exported via OTEL. `cli._detect_source()` sniffs the first lines of a trace file and routes to the Claude Code or OTEL parser. Both parsers return the same `SessionTrace`, so everything downstream is provider-agnostic. See `docs/quickstart-otel.md`.

## Architecture

```
Session log (Claude Code JSONL on disk)
  ↓
Parser           ← dependency-free; takes a path, returns SessionTrace
  ↓
Tokenizer        ← only place that imports anthropic; offline-mode safe for CI
  ↓
Diagnostician    ← per-turn investigation: inflection detection + pattern
                   classifiers (retry loop, scope creep, stale context,
                   tool thrash, dead end, fan-out waste, cache hygiene,
                   compaction, exploration thrash, unused context;
                   project-specific runs cross-session). Produces a Diagnosis.
  ↓
Recommender      ← turns Findings into Patches: copy-pasteable CLAUDE.md /
                   rule / skill diffs, evidence-backed when cross-session.
  ↓
Renderers        ← rich (terminal), Jinja2 (HTML report), textual (trace
                   TUI overlay).
  ↓
Exporters        ← jsonl, csv.
```

## Project layout

```
cctx/
├── cli.py              # click + rich-click; routes all 7 subcommands
│                       # (ls, autopsy, harvest, watch, trace, export, init).
├── parsers/
│   ├── claude_code.py  # SHIPPED. Parse ~/.claude JSONL logs.
│   └── otel.py         # SHIPPED (v1.12.0). Parse OTLP gen_ai.* spans —
│                       # OpenAI Agents SDK, LangGraph. Same SessionTrace out.
├── tokenizer.py        # SHIPPED. anthropic.count_tokens wrapper; CCTX_OFFLINE heuristic.
├── pricing.py          # SHIPPED. get_pricing() -> ModelPricing (2D input/output +
│                       # cache mults) via longest-prefix match; Anthropic + OpenAI.
│                       # PRICING_LAST_VERIFIED date + freshness tripwire test. Single
│                       # source of truth for cost; price_per_tok() kept as a shim.
├── models.py           # SHIPPED. Turn, ToolUse, ToolResult, Usage, Attachment,
│                       # RawToolResultFile, SessionTrace, Finding, Patch, Diagnosis,
│                       # SubagentAttribution, KIND_LABEL, MANAGED_HEADINGS,
│                       # AggregateReport, CrossProjectDigest.
├── diagnostician/
│   ├── __init__.py     # public: run(trace) -> Diagnosis. Wires the classifiers,
│   │                   # runs the 9 per-turn ones recursively inside each subagent
│   │                   # (priced per-model), + per-subagent cost attribution.
│   ├── inflection.py   # detect the turn where the session diverged
│   └── patterns/
│   │   ├── retry_loop.py
│   │   ├── scope_creep.py
│   │   ├── stale_context.py
│   │   ├── tool_thrash.py
│   │   ├── dead_end.py
│   │   ├── fan_out.py            # subagent overlap + retry waste
│   │   ├── cache_hygiene.py      # KV-cache hit rate + cause
│   │   ├── compaction.py         # compaction events + re-fetch waste
│   │   ├── exploration_thrash.py # read-heavy circling without progress
│   │   ├── unused_context.py     # MCP servers loaded but never called
│   │   └── project_specific.py   # cross-session only -> PROJECT_PATTERN
├── aggregate.py        # SHIPPED. Cross-session pipeline ORCHESTRATOR + report assembly:
│                       # run() globs sessions and runs parse -> tokenize ->
│                       # diagnostician.run per session; run_all_projects() does that
│                       # across every project. build_aggregate_report() and
│                       # build_cross_project_digest() own the rollup — pure over
│                       # diagnosed pairs, so --since, --all and harvest --since all
│                       # compute from one formula. Lives at top level — it
│                       # orchestrates and assembles, it does not analyse.
├── recommender/
│   ├── claude_md.py    # Finding -> Patch (CLAUDE.md diff proposals)
│   └── evidence.py     # session-count + dollar evidence accumulation; efficacy()
│                       # before/after bucketing for harvest --efficacy.
├── harvest.py          # SHIPPED. apply_patch, preview_patches, apply_patches, check_claude_md —
│                       # append-only, idempotent patching with fingerprint-based deduplication.
│                       # v2: patches route to any .md target (rules/, skills/). Patch-apply
│                       # core + the harvest --check audit only.
├── emit.py             # SHIPPED. Cross-agent emit (harvest --emit/--sync): EMIT_TARGETS,
│                       # retarget_patches, sync_managed_sections, managed_heading_dates.
│                       # Imports harvest's apply core — never the reverse.
├── hook_installer.py   # SHIPPED (v1.11.0). cctx init — install/remove SessionEnd hook.
├── agents.py           # SHIPPED (v1.5.0). live_sessions() via `claude agents --json`.
├── discovery.py        # SHIPPED. list_projects(), latest_session() — navigate ~/.claude/projects/
├── watcher.py          # SHIPPED. cctx watch — poll active session, surface findings live.
├── renderers/
│   ├── terminal.py     # rich rendering of Diagnosis, AggregateReport, CrossProjectDigest,
│   │                   # efficacy report, projects, sessions
│   ├── github.py       # GitHub Actions job summary renderer (--github-summary)
│   ├── report.py       # Jinja2 HTML report (cctx autopsy --html)
│   └── trace_tui.py    # textual TUI with autopsy findings overlaid
└── exporters/
    ├── jsonl.py
    ├── csv.py
    └── json.py
```

## Layering rules (enforced by convention)

These keep the dependency graph clean so modules stay independently testable and refactorable:

- **Parsers never import the tokenizer, the anthropic SDK, or any analyzer.** A parser takes a path and returns a `SessionTrace` with `token_count: int = 0` placeholders.
- **Tokenizer is the only module that imports `anthropic`.** Everyone else gets token counts pre-populated on the dataclasses.
- **Analyzers (diagnostician, recommender) never import each other across boundary lines.** Inside the diagnostician package, helpers can compose freely. The recommender takes a Diagnosis and emits Patches without reaching back into the diagnostician's internals.
- **`aggregate.py` is the cross-session pipeline orchestrator and owns report assembly, but is not an analyzer.** It sits above the analyzers — it may call parser, tokenizer, `diagnostician.run`, the cross-session `project_specific.detect`, and the recommender's `generate_from_evidence`/`generate_from_patterns` to drive the pipeline and roll the results up. It lives at the top level (`cctx/aggregate.py`), not inside `diagnostician/`. Likewise `emit.py` is the cross-agent emit layer that imports `harvest`'s patch-apply core — never the reverse.
- **Cross-session report assembly (`AggregateReport`, `CrossProjectDigest`) lives in `aggregate.py`, never in a click command body.** `cli.py` parses arguments, calls a builder, and renders. Before this rule the `--since` and `--all` rollups were separate implementations inside command bodies and had already diverged. Documented exception: `build_aggregate_report(detect_project_patterns=False)` has two deliberate callers — the digest, whose `ProjectDigestRow` carries no `ProjectPattern` slot, and `harvest --since`, because pattern patches need human review (autopsy displays them; harvest can auto-apply).
- **Renderers and exporters never compute analysis.** They take an analyzer's output and render or serialize it — no cost arithmetic, no re-derivation. `Diagnosis.turn_costs` is how per-turn cost reaches `exporters/csv.py`. Swapping `terminal.py` for `report.py` or `csv.py` should not change a single number or finding.
- **Only `cli.py` imports `click` and `rich_click`.** Everything else uses plain `rich.Console` if it needs to output. Analyzers and parsers return data; the CLI decides how to display it.
- **Source-format detection lives in `cli._detect_source()`.** When adding a parser (e.g. a third trace format), add a branch there. Each parser still returns a `SessionTrace`, so nothing downstream of the parser changes.

## Core design decisions

These came out of the brief, the parser brainstorming session, and the autopsy pivot. They apply across the entire codebase:

- **Diagnose the specific session, not the aggregate.** cctx is forensic. CodeBurn covers daily cost tracking; cctx is "what went sideways here, and what do I add to CLAUDE.md so it doesn't happen again."
- **Token-turns is a useful metric for stale-content attribution.** `tokens × turns_present`, compaction-aware. A 22K grep result sitting in context for 14 turns after its last reference costs ~310K token-turns of waste. This is how stale-context findings attribute their dollar cost.
- **Approximate decomposition is fine.** Reconstructing the API request from the JSONL gets you ~85–95% of the actual `input_tokens`. The remainder is internal framing you can't observe. The system internals slice is honest; don't pretend to be exact.
- **Binary waste detection only in v1.** "Loaded but never called" is high-confidence. "Partially used" is fragile. Ship the binary version.
- **Patches must be copy-pasteable.** Every Patch carries a unified diff against a target file (CLAUDE.md, rules, skill, ADR). Lower the barrier to action to zero.
- **Single-session AND cross-session, same diagnostician.** `cctx autopsy <session>` and `cctx autopsy <project> --since <window>` go through the same per-session pipeline; the aggregator runs after.
- **Group up, never down.** Parse at the finest granularity the source provides (per JSONL line). Aggregate in the view layer. (Originated in the parser design — applies everywhere.)
- **`Finding.evidence` stays `dict[str, Any]`; its nested items are typed per kind, on demand.** The authoritative per-kind schema lives in each producing classifier's module docstring under an `Evidence (Finding.evidence, kind=...)` block. Three kinds — `RETRY_LOOP`, `SCOPE_CREEP`, `STALE_CONTEXT` — carry frozen dataclasses (`RetryOccurrence`, `ScopeCreepPhrase`, `StaleItem` in `models.py`) constructed by the classifier at the boundary. **Escalation trigger: a second consumer starts reading a kind's nested items.** Those three tripped it — `recommender/claude_md.py:summarize()` and `renderers/trace_tui.py:affected_turns()` both read them, and had diverged on access style (subscript vs. `in`-guard), so a schema change would `KeyError` in one and silently degrade in the other. The remaining 8 kinds have one consumer each and stay untyped; type a kind when it trips the trigger, not before.
- **Empirical evidence collapses speculative complexity.** Before designing for a hypothetical case, scan real data. The parser spec's tool-result handling was simplified by 80% after one 30-line empirical scan.
- **Deterministic over LLM-assisted in v0.** Pattern classifiers use heuristics, not LLM calls. (Future v1+ harvest may invoke an LLM for summarization, opt-in with API key.) The deterministic core has predictable cost and is testable on fixtures.

## Build order (post-pivot)

1. **M0 — Project setup.** SHIPPED. (#1)
2. **M1 — Foundation.** SHIPPED — parser, tokenizer, models, fixtures, CI. (#2–#6, plus PR #38)
3. **M2 — Autopsy v0.** SHIPPED — single-session diagnosis + cross-session pattern detection. (#9, #10, #40–#49)
4. **M3 — Trace TUI** with autopsy overlay. SHIPPED. (PR #57)
5. **M4 — Export.** SHIPPED — jsonl + csv exporters (html moved to autopsy --html; json deferred). (PR #54)
6. **M5 — Harvest v1.** SHIPPED — CLAUDE.md target only; promote autopsy findings to durable CLAUDE.md diffs. (PR #56)
7. **M6 — Release v0.1.0.** SHIPPED — README, version bump, PyPI publish, GitHub Action (composite), session discovery (`cctx ls`). (#31, #32, #62, #73)
8. **M7 — v0.2.0.** SHIPPED — `cctx watch` live mode, `--github-summary`, `--fail-on-findings`, harvest v2 multi-target, `harvest --check`, tool-thrash + dead-end classifiers, `--since` string formats, interactive aggregate drill-down.
9. **v1.x.** SHIPPED. Milestone numbers track issues, not release order, and several features shipped without a milestone tag. See `CHANGELOG.md` for the per-release detail. Highlights, in release order:
   - **v1.1–v1.2 (M9, M12)** — verdict headline, `--top N`, `--turn N`, `--until DATE`, `--json` diagnosis, `--format json` on `export`.
   - **v1.3 (M14)** — project-specific cross-session pattern detection.
   - **v1.4 (M13)** — `harvest --check` depth (contradiction, redundancy, staleness) + `--check-severity`.
   - **v1.5** — `agents.py` live sessions via `claude agents --json`; `cctx ls` live badges; watcher early idle exit.
   - **v1.6 (M15)** — cross-agent emit: `harvest --emit agents [--sync]` to `AGENTS.md`; `MANAGED_HEADINGS` registry.
   - **v1.7 + v1.8 (M16)** — per-subagent cost attribution + `SubagentAttribution`; fan-out waste classifier.
   - **v1.9 (M17)** — `harvest --efficacy`: before/after patch efficacy measurement.
   - **v1.10** — `autopsy --json` aggregate output for `--since` mode.
   - **v1.11 (M19)** — `cctx init` SessionEnd hook installer; `autopsy --quiet`.
   - **v1.12** — OTEL parser: OpenAI Agents SDK / LangGraph support via `parsers/otel.py` + `_detect_source()`.
   - **v1.13** — KV-cache hygiene classifier; OTEL LangGraph quickstart.
   - **v1.14** — savings framing + health grade behind `--health`.
   - **v1.15 (M20)** — compaction findings classifier.
   - **v1.16** — exploration thrash classifier.
   - **v1.17 (M18)** — unused-context classifier (MCP loaded but never called).
   - **v1.18 (M21)** — cross-project digest: `cctx autopsy --all --since`.

Future, not yet milestoned:
- **Cross-agent layer breadth** — emit to `.cursorrules`, `.windsurfrules`, GitHub Copilot instructions (`AGENTS.md` shipped v1.6.0).
- **Subagent-aware diagnosis** — recursively classify per-subagent patterns, not just attribute cost + fan-out waste.

## Design docs

Feature designs live in `docs/superpowers/specs/`, dated and committed before implementation begins. Each implementation plan in `docs/superpowers/plans/` references its spec. Don't start a feature without one.

Specs landed on main (see `docs/superpowers/specs/` for the full set):
- `2026-05-12-claude-code-parser-design.md` — Claude Code JSONL parser.
- `2026-05-14-autopsy-design.md` — autopsy v0 (single + cross-session).
- `2026-05-14-harvest-design.md` — CLAUDE.md patcher.
- `2026-05-14-trace-tui-design.md` — Textual trace TUI.
- `2026-05-17-harvest-check-depth-design.md` — `harvest --check` contradiction/redundancy/staleness.
- `2026-05-17-project-pattern-detection-design.md` — cross-session project-specific patterns.
- `2026-05-19-claude-agents-live-integration-design.md` — `claude agents --json` live integration.
- `2026-06-09-cross-agent-emit-design.md` — `harvest --emit` to AGENTS.md.
- `2026-06-19-otel-parser-design.md` — OTLP / OpenAI Agents SDK parser.
- `2026-06-20-cross-project-digest.md` — `autopsy --all --since`.

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

## Review workflow

### Context documents

- **PRODUCT.md** — product context, personas, principles, feature map. Read before any product decision.
- **DESIGN.md** — design system, colors, typography, component patterns. Read before any UI work.

### Quality gates

| Gate | When | Command |
|------|------|---------|
| Should we build? | Before any engineering | `/gate-should-we-build [idea]` |
| Design review | After design doc, before implementation | `/gate-design-review` |
| Audit | After implementation, before acceptance | `/audit` |
| Acceptance | After audit passes, before merge | `/gate-acceptance` |

### Periodic reviews

| Review | Cadence | Command |
|--------|---------|---------|
| Codebase health | Weekly or pre-milestone | `/review-codebase-health` |
| Frontend health | Monthly or post-UI-sprint | `/review-frontend-health` |
| Architecture | Quarterly or pre-major-feature | `/review-architecture` |
| Product health | Monthly | `/review-product-health` |
| README drift | After a release or feature batch | `/review-readme` |
| All reviews | As needed | `/deep-review` |

### After each review

1. Fix any **critical** findings before the next feature
2. File **important** findings as tasks to address this cycle
3. Track **minor** findings — they compound if ignored
4. Update context docs if the review surfaced changes:
   - `/review-product-health` updates PRODUCT.md
   - `/review-frontend-health` updates DESIGN.md
   - `/review-architecture` updates CLAUDE.md
