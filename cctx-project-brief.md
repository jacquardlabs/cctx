# cctx — find out why your Claude Code session went sideways and what it cost you

An open-source Python CLI that diagnoses individual Claude Code sessions: when they went wrong, why they went wrong, what they cost, and what to add to your `CLAUDE.md` so it doesn't happen again.

```
pip install cctx
```

## The pitch (for the README)

Your agent burned 12 turns in a debugging loop and you don't know what triggered it. It re-explained the monorepo structure for the fourth time this week. It read three files it didn't need before getting to the one it did. Your `CLAUDE.md` is fine, but it doesn't know about the patterns that keep biting you.

`cctx` reads the session logs Claude Code already writes to disk and tells you exactly where things went sideways:

```
cctx autopsy <session>          — what went wrong in this session?
cctx autopsy <project> --since  — what patterns repeat across recent sessions?
cctx harvest <session>          — extract the learnings; propose CLAUDE.md diffs
cctx export <session> --format  — get the data out
```

Every command reads logs locally. No API keys (for the parser). No proxy. No SaaS. Point it at a session and go.

`cctx` is built for the moment after something goes wrong — when you scroll back through a long session and try to figure out what happened.

---

## Example: `cctx autopsy` — single-session diagnosis

```
$ cctx autopsy ~/.claude/projects/myapp/abc123.jsonl

cctx v0.1.0 — session autopsy

Session: abc123 | 38 turns | $1.42 | 12 min 18 s
Verdict: ⚠ retry loop + scope creep

Inflection turn
  Turn 14: Bash(npm test) → 3 failures
  Claude attempted the same fix in 3 of the next 4 turns without
  changing approach. Tests failed identically each time.

Diagnosis
  ──────────────────────────────────────────────────────────────────
  ⚠ Retry loop (turns 14–22):  $0.83 wasted
    Same test, same error, fix variants too similar to converge.
    Pattern: Edit→Bash(test)→Edit→Bash(test) without re-reading source.

  ⚠ Scope creep (turns 23–31): $0.52 wasted
    Original prompt: "fix auth bug." Claude began refactoring the
    user model at turn 25 (no explicit request observed).

  ⚠ Stale context: 18,400 tokens × 14 turns
    Turn 9's directory listing (4,800 tokens) was in context from
    turn 9 to end. Last reference: turn 11.

Proposed CLAUDE.md additions
  ──────────────────────────────────────────────────────────────────
  ```diff
  + ## When tests fail
  + If a test fails twice with the same error, stop and re-read the
  + source file before attempting another fix.
  +
  + ## Scope
  + Stick to the task in the prompt. If you spot adjacent issues,
  + name them and ask before fixing.
  ```
  Est. savings if applied: $1.35 per affected session.

  Confidence: high — these patterns repeated in 6 of your last 30 sessions.
```

That's the entire product loop: read one session, name what went wrong, attribute the waste in dollars, generate a specific patch.

## Example: `cctx autopsy --since` — cross-session pattern detection

```
$ cctx autopsy ~/.claude/projects/myapp --since 14d

cctx v0.1.0 — multi-session autopsy

Project: myapp | 41 sessions | May 1–14, 2026

Top failure patterns (ranked by total cost)
  ──────────────────────────────────────────────────────────────────
  1. pnpm requires --filter in monorepo                $4.20 total
     Re-discovered in 7 of 41 sessions. Each session lost ~12 turns
     before learning. Always followed by 3+ failed bash commands.
     → Promote to CLAUDE.md? [diff shown]

  2. Database migrations need explicit transactions    $2.80 total
     Re-discovered in 4 of 41 sessions. Each instance triggered a
     rollback retry. Average 8 turns to converge.
     → Promote to CLAUDE.md? [diff shown]

  3. Retry-without-re-read loop                        $5.40 total
     Observed in 13 of 41 sessions. Pattern: Edit→Bash(test)→Edit
     without intervening Read. Not project-specific; general rule.
     → Promote to CLAUDE.md? [diff shown]

  4. Scope drift on "fix" prompts                      $1.90 total
     Observed in 9 of 41 sessions. Claude began adjacent work
     unprompted in 22% of "fix this" tasks.
     → Promote to CLAUDE.md? [diff shown]

Total recoverable: $14.30 over 14 days. Estimated 60% reduction if
all 4 additions are applied.

Press a number to inspect that pattern. Press p<N> to promote it.
```

This is the bridge to `cctx harvest`: cross-session patterns are evidence-backed promotions, not guesses.

---

## The growth staircase

`cctx` ships in v0 as session autopsy and grows along one axis: from per-session diagnosis to multi-session learning to live prevention to cross-agent portability.

```
v0 — Autopsy                cctx autopsy <session>
                            → diagnose one session, propose CLAUDE.md fix.

v0.x — Cross-session        cctx autopsy --since 30d
                            → recurring patterns become evidence-backed
                              CLAUDE.md additions.

v1 — Harvest                cctx harvest <session>
                            → extract everything worth persisting:
                              CLAUDE.md additions, rules, skill drafts,
                              ADR seeds. Diffs proposed against each
                              destination file.

v1.x — Memory hygiene       cctx harvest --check
                            → audit existing CLAUDE.md and memory files
                              against captured sessions: stale entries,
                              contradictions, never-fired skills.

v2 — Live mode              cctx watch
                            → filesystem watcher on ~/.claude/projects.
                              Surface waste signals during the session
                              before they compound. Optional.

v3 — Cross-agent layer      cctx harvest --emit cursor-rules
                            → write the same captured knowledge to
                              .cursorrules, AGENTS.md, .windsurfrules,
                              GitHub Copilot instructions. One source of
                              truth, many destinations.
```

Each step is motivated by user pull from the previous one. v0 is the wedge. v1 is where the accumulating value compounds.

---

## The v0 suite

Four subcommands. Small surface; deep on each.

### `cctx autopsy <session>` — single-session diagnosis

Reads one session JSONL. Identifies the inflection turn (where things went off the rails), classifies failure patterns (retry loop, scope creep, stale context, dead-end exploration, tool-thrashing), attributes dollar waste, generates copy-pasteable CLAUDE.md diffs.

Flags: `--json` for machine-readable output, `--html` for a shareable report, `--turn N` to focus on a specific turn.

### `cctx autopsy <project> --since` — cross-session pattern detection

Runs `autopsy` across all sessions in a project within a date range. Aggregates recurring failure patterns and proposes promotions to CLAUDE.md as evidence-backed diffs (with session counts and dollar totals).

Flags: `--since 7d`, `--since 2w`, `--since 2026-05-01 --until 2026-05-10`, `--top N` (show top N patterns).

### `cctx export <session> --format` — data export

Export raw session data + autopsy findings in standard formats for external analysis.

```
cctx export <session> --format jsonl     # normalized trace + diagnosis
cctx export <session> --format html      # report card with charts
cctx export <session> --format json      # findings only
cctx export <project> --since 7d --format csv
```

### `cctx trace <session>` — step-through viewer

TUI for navigating a session turn by turn. Each turn shows user message, assistant response, tool calls with cost. The autopsy diagnosis is overlaid: turns flagged as part of a retry loop or scope drift glow red. Press enter on a flagged turn to see the diagnosis snippet for that pattern.

Not a fork-and-replay debugger. Just a navigable view of what happened with the autopsy annotations attached.

---

## What `cctx` is NOT

- **Not a cost dashboard.** [CodeBurn](https://github.com/getagentseal/codeburn) is excellent at that. `cctx` is forensic — used when something went wrong, not for daily monitoring. Different abstraction level. Install both.
- **Not a transcript viewer.** Many of those exist. `cctx trace` is one component of `cctx autopsy`; it overlays diagnosis on the transcript, it doesn't render the transcript for browsing.
- **Not real-time in v1.** v2 adds a watcher; v1 analyzes completed sessions.
- **Not a fork-and-replay debugger.** Maybe one day. Not v0.
- **Not multi-provider.** Claude Code only in v1. Cursor, Codex, etc. would be future ports of the autopsy logic — but the parser is Claude-Code-specific by design.
- **Not an agent.** `cctx` reads logs. The optional harvest-suggestion quality may benefit from LLM-assisted summarization later (opt-in, with an API key); the core autopsy is deterministic.

---

## What makes `cctx` get stars

1. **Immediate, concrete value on first run.** `pip install cctx && cctx autopsy <session>` produces an actionable report in under 10 seconds. The output is anchored to verifiable facts: "you spent $0.83 on these 8 turns" is either true or it isn't.
2. **The "oh shit" moment.** "Claude re-discovered `pnpm --filter` in 7 sessions this month, costing you $4.20." Followed by an exact CLAUDE.md line to add.
3. **Compounding value.** Every session diagnosed teaches the next. After two weeks, rolling cctx back would mean rolling back a smarter `CLAUDE.md`.
4. **Honest about what it doesn't know.** Tokens it can't attribute are labeled "system internals (not in logs)" rather than guessed. Patterns it sees only once are shown but not promoted to CLAUDE.md.
5. **Works with what people already have.** Reads `~/.claude/projects/` directly. No instrumentation, no config changes, no API keys.
6. **Respects the developer.** Local-only. No telemetry. No cloud. No sign-up.
7. **One install, four sharp tools.** `pip install cctx` ships autopsy + cross-session + trace + export. Small enough to learn in an afternoon.

---

## Architecture

```
Session log (JSONL on disk)
  ↓
Parser           ← dependency-free; takes a path, returns SessionTrace
                   (already shipped; subagent-aware, attachment-classified)
  ↓
Tokenizer        ← only place that imports anthropic; offline mode for CI
                   (already shipped)
  ↓
Diagnostician    ← per-turn investigation: inflection detection, retry-loop
                   pattern matching, scope-creep heuristics, stale-context
                   scoring. Produces a Diagnosis.
  ↓
Recommender      ← takes Diagnosis + (optional) cross-session pattern set;
                   produces CLAUDE.md / rule diff proposals with evidence.
  ↓
Renderer         ← rich (terminal), HTML report, JSON. The trace TUI
                   (textual) is a renderer too: it overlays diagnosis
                   findings on the transcript view.
  ↓
Exporter         ← jsonl, csv, html, json
```

### Project layout

```
cctx/
├── cli.py              # click + rich-click; routes to subcommands
├── parsers/
│   └── claude_code.py  # SHIPPED. JSONL parser.
├── tokenizer.py        # SHIPPED. anthropic.count_tokens wrapper.
├── models.py           # SHIPPED. Turn, ToolUse, ToolResult, SessionTrace.
│                       # Extended in v0.1 with Diagnosis + Finding + Patch.
├── diagnostician/
│   ├── inflection.py   # identify the turn where the session diverged
│   ├── patterns/
│   │   ├── retry_loop.py
│   │   ├── scope_creep.py
│   │   ├── stale_context.py
│   │   ├── dead_end.py
│   │   └── tool_thrash.py
│   └── aggregate.py    # cross-session pattern detection (--since mode)
├── recommender/
│   ├── claude_md.py    # generate CLAUDE.md diff proposals from findings
│   └── evidence.py     # attach session counts + dollar totals to each diff
├── renderers/
│   ├── terminal.py     # rich tables + verdict banner + diff blocks
│   ├── report.py       # HTML report card (Jinja2)
│   └── trace_tui.py    # textual TUI overlay
└── exporters/
    ├── jsonl.py
    ├── csv.py
    ├── html.py
    └── json.py
```

### Data model additions (v0.1)

The existing `SessionTrace`, `Turn`, `ToolUse`, `ToolResult` stay. New dataclasses for the diagnostician:

```python
@dataclass
class Finding:
    pattern: str                 # "retry_loop" | "scope_creep" | "stale_context" | ...
    severity: Literal["low", "medium", "high"]
    inflection_turn: int         # the turn where this pattern emerged
    affected_turns: list[int]
    cost_wasted_usd: float
    tokens_wasted: int
    description: str             # one-paragraph human-readable
    suggested_patch: Patch | None

@dataclass
class Patch:
    target: Literal["CLAUDE.md", "rules", "skill", "ADR"]
    diff: str                    # standard unified diff format
    rationale: str               # why this would prevent the pattern
    confidence: Literal["low", "medium", "high"]
    evidence_sessions: list[str] # session_ids that exhibited the pattern

@dataclass
class Diagnosis:
    session_id: str
    verdict: str                 # short headline, e.g. "retry loop + scope creep"
    findings: list[Finding]
    total_cost_wasted_usd: float
    total_tokens_wasted: int
```

---

## What's already shipped (M0 + M1 foundation)

The pivot doesn't reset anything. As of the cctx pivot commit:

- **#1** project scaffolding (pyproject, package layout, ruff + pytest config)
- **#2** GitHub Actions CI (matrix on Python 3.10–3.13)
- **#3** sanitized real-session fixture corpus (5 fixtures: short-clean, with-subagents, with-tool-results, with-compaction, with-attachments) + reproducible `scrub.py` script
- **#4** `cctx/models.py` (`Turn`, `ToolUse`, `ToolResult`, `Usage`, `Attachment`, `SessionTrace`, `Recommendation`, `SessionSummary`, `ProjectAnalysis`, plus `ParserError` / `ParserWarning` and `group_into_exchanges()`)
- **#5** `cctx/parsers/claude_code.py` — full JSONL parser with subagent recursion, attachment classification, compaction-event handling, warn-and-skip diagnostics
- **#6** `cctx/tokenizer.py` — `anthropic.count_tokens` wrapper with offline-mode (`CCTX_OFFLINE=1`) fallback

93 tests on main, CI green, parser parses a 6 MB session in ~70 ms.

The parser was built to support exactly the kind of forensic analysis autopsy needs: per-turn detail, subagent recursion, attachment polymorphism. Nothing about the foundation changes.

---

## Build order (post-pivot)

1. **Brief + issue triage** ← this PR. Close obsolete tickets; open new ones for the autopsy roadmap.
2. **Autopsy v0** — brainstorm + design + plan + implement.
   - Inflection detection
   - Retry-loop classifier
   - Scope-creep classifier
   - Stale-context detector
   - `Diagnosis` + `Finding` + `Patch` data model
   - CLI subcommand
   - Terminal renderer
   - HTML report renderer
3. **Autopsy cross-session (`--since` mode)** — pattern aggregation across multiple sessions.
4. **Trace TUI** — overlay diagnosis on the transcript view.
5. **Export** — jsonl + csv + html + json formats.
6. **Harvest v1** — promote autopsy findings to CLAUDE.md/rules/skill/ADR diffs.

v0 is roughly 4–6 focused PRs after the foundation we already have.

## Tech stack

Unchanged from the original brief:

- Python 3.10+
- `anthropic` SDK — token counting only, in the tokenizer module
- `click` + `rich-click` — CLI
- `rich` — terminal output
- `textual` — the TUI for `cctx trace`
- `pandas` — cross-session aggregation in `--since` mode
- `Jinja2` — HTML report templates
- No web framework, no database, no async, no cloud, no telemetry.

## Non-goals

- **Don't build a SaaS.** Local-only.
- **Don't run agents.** `cctx` reads logs. (Future LLM-assisted summarization for harvest may be opt-in with explicit user consent + API key.)
- **Don't compete with CodeBurn on daily cost dashboards.** Different abstraction level; cctx is forensic.
- **Don't compete with general eval frameworks (promptfoo et al.).** cctx may generate evals from real sessions as a side effect of cross-session pattern detection later, not as a primary product.
- **Don't try multi-provider in v1.** Claude Code only.
- **Don't try fork-and-replay debugging in v1.** Maybe v3+.
- **Don't try to be exact about context decomposition.** The "system internals" gap is honest.
- **Don't add dependencies recklessly.** The parser is stdlib-only; the analyzer layers are pure Python + the existing deps.

---

## First session prompt (post-pivot)

Start Claude Code with:

"Read this project brief. We're building cctx, a session-autopsy CLI for Claude Code. The foundation — parser, tokenizer, models, fixtures, CI — is already shipped on main. Start by brainstorming the v0 design for `cctx autopsy <session>`: inflection-turn detection, the failure-pattern classifiers (retry loop, scope creep, stale context), the `Diagnosis` / `Finding` / `Patch` data model, and the CLAUDE.md-diff output format. Then design spec → plan → implement, one issue per PR."
