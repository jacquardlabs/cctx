# cctx — debugging and optimization tools for AI agents

An open-source CLI suite that profiles, debugs, and optimizes Claude Code and Agent SDK sessions. Every subcommand is a different lens on the same session data. Think `py-spy` + `clinic.js` + `eslint` but for AI agents.

```
pip install cctx
```

## The pitch (for the README)

You're burning tokens and you don't know where. Your agent gets stuck in retry loops and you can't see it. An MCP server you forgot about loads 24K tokens every turn and you never call it. A grep returns 22K tokens and the agent uses 3 lines. Your CLAUDE.md has contradictions you haven't noticed.

`cctx` reads the session logs Claude Code already writes to disk and tells you what's happening:

```
cctx profile <session>         — where are the tokens going?
cctx analyze <project> --since — what's systematically true across sessions?
cctx cost <session>            — where is the money going?
cctx tools <project> --since   — how are tools being used?
cctx trace <session>           — what happened, step by step?
cctx loops <session>           — is the agent getting stuck?
cctx slow <session>            — what's taking so long?
cctx lint <project>            — is the config any good?
cctx bench <prompt> --runs N   — how consistent is the agent?
cctx export <session> --format — get the data out
```

Every subcommand shares the same parser, tokenizer, and data model. No config, no setup, no API keys. Point it at your session logs and go.

---

## Example: `cctx profile` — context decomposition

```
$ cctx profile ~/.claude/projects/myapp/sessions/abc123

cctx v0.1.0 — context window profiler

Session: abc123 | 25 turns | $1.42 | 4m 32s

Context at final turn: 142,381 / 200,000 tokens (71.2%)

  Component              Tokens    %     Token-turns    Status
  ─────────────────────────────────────────────────────────────
  System prompt          12,400    8.7%   310,000       ok
  Tool descriptions      24,100   16.9%   602,500       ⚠ waste
    github-mcp            8,200                         ✗ never used
    sentry-mcp            3,400                         ✗ never used
    playwright-mcp        6,100                         ~ used once
    filesystem-mcp        4,800                         ✓ active
    context7-mcp          1,600                         ✓ active
  Memory + skills         6,800    4.8%   170,000       ok
  Conversation history   62,400   43.8%  1,021,200
    Turn 5 Read index.ts  12,100                        ⚠ stale (last ref: turn 6)
    Turn 9 Read 4 files   18,300                        ⚠ 3 of 4 stale
    Turn 7 test output     9,400                        ⚠ 91% unreferenced
  Tool results (last)    36,681   25.8%    36,681
    Grep 'handleAuth'    22,400                         ⚠ 847 matches, 3 used
    npm test output       13,081                        ⚠ 184/187 tests passing (noise)

Recommendations:
  1. Enable tool search          → save ~248K token-turns/session (~$0.25)
     Two MCP servers loaded but never used. Tool search lazy-loads descriptions.
     Add to config: tool_search: true

  2. Truncate tool output         → save ~186K token-turns/session (~$0.19)
     Grep and test output averaging 18K tokens, <5% referenced.
     Add hook: output_max_lines: 50

  3. Compact earlier              → save ~142K token-turns/session (~$0.14)
     Context hit 71% by turn 12. Default compaction fires at 95%.
     Set: CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=65

  Est. total savings: $0.58/session (41%)
```

## Example: `cctx analyze` — multi-session meta-analysis

```
$ cctx analyze ~/.claude/projects/myapp --since 7d

cctx v0.1.0 — multi-session analysis

Project: myapp | 53 sessions | May 5–12, 2026

Overview
  Total spend:          $47.82
  Avg cost/session:     $0.90 (p50: $0.72, p95: $2.14)
  Avg context at end:   128,400 tokens (64.2%)
  Compaction triggered: 39/53 sessions (73.6%)
  Est. wasted spend:    $18.40 (38.5%)

Tool description waste (loaded but unused)
  MCP server          Sessions loaded  Sessions used  Waste rate  Avg tokens
  ──────────────────────────────────────────────────────────────────────────
  github-mcp          53/53 (100%)     6/53 (11%)     89%         8,200
  sentry-mcp          53/53 (100%)     2/53 (4%)      96%         3,400
  playwright-mcp      53/53 (100%)     18/53 (34%)    66%         6,100
  filesystem-mcp      53/53 (100%)     53/53 (100%)   0%          4,800
  context7-mcp        53/53 (100%)     41/53 (77%)    23%         1,600

  → Enable tool search. Est. savings: $8.20/week

Top token consumers (by total token-turns across all sessions)
  Component                Avg tokens   Avg token-turns   Total token-turns
  ─────────────────────────────────────────────────────────────────────────
  Grep results             18,200       243,000           12.9M
  File reads (>5K tokens)  14,600       198,000           10.5M
  Tool descriptions        24,100       602,500            8.4M  ← 38% wasted
  Test output (Bash)       11,300       158,000            6.2M
  System prompt            12,400       310,000            4.1M

Stale content (in context 5+ turns after last reference)
  Pattern                          Frequency    Avg stale tokens
  ─────────────────────────────────────────────────────────────────
  Large file reads (>5K tokens)    82% of reads    11,400
  Test output after fix applied    68% of test runs 8,900
  Grep results after selection     91% of greps    16,200

  → Compact earlier. Set CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60

Trends (last 7 days)
  Cost/session:    ▁▂▂▃▃▅▇  trending up (+22%)
  Context waste:   ▅▅▄▃▃▃▂  trending down (-14%)
  Compaction rate:  ▃▃▃▅▅▆▇  trending up (more sessions hitting limits)

Recommendations (by weekly savings)
  1. Enable tool search                    → save $8.20/week
  2. Add Grep output truncation hook       → save $4.60/week
  3. Lower compaction threshold to 60%     → save $3.10/week
  4. Remove sentry-mcp from this project   → save $1.80/week
  ─────────────────────────────────────────────────────────────
  Total est. savings: $17.70/week (37% of current spend)
```

---

## The full suite

### `cctx profile` — context decomposition

Decomposes a single session's context window into its constituent parts (system prompt, tool descriptions, memory/skills, conversation history, tool results). Computes token-turns (tokens × turns present) for cumulative cost attribution. Detects waste: unused tools, oversized results, stale history. Generates copy-pasteable recommendations with estimated savings.

Flags: `--html` generates an interactive flamegraph report. `--json` outputs raw analysis.

### `cctx analyze` — multi-session meta-analysis

Runs `cctx profile` across all sessions in a project within a date range. Aggregates to find systemic patterns: chronic waste (MCP servers unused in 89% of sessions), drift (cost trending up 22% this week), stale content patterns (grep results go stale 91% of the time), and compaction behavior (fires in 73.6% of sessions between turns 12–15). Recommendations are ranked by weekly dollar savings.

Flags: `--since 7d`, `--since 2w`, `--since 2026-05-01 --until 2026-05-10`, `--html`, `--json`.

### `cctx cost` — cost attribution

Breaks down a session's dollar cost by phase (exploration / implementation / debugging), by model (main agent vs subagents), and by turn. Shows cache efficiency (hit rate, savings from caching). Identifies the costliest turns with explanations.

Phase detection is heuristic: heavy file reads = exploration, heavy edits = implementation, heavy bash + test reruns = debugging. Simple but useful.

```
$ cctx cost <session>

  By model
  ──────────────────────────────────────────────────
  claude-sonnet-4-6 (main)     $1.30  (91.5%)
  claude-haiku-4-5 (subagent)  $0.12  (8.5%)

  Cache efficiency
  ──────────────────────────────────────────────────
  Cache hit rate: 73.4%
  Saved by caching: $0.86

  Costliest turns
  ──────────────────────────────────────────────────
  Turn 9:  $0.18  — Read 4 files + long response
  Turn 14: $0.14  — Extended thinking on debugging
```

### `cctx tools` — tool efficiency report

Which tools are being called, how often, how much they cost, and how often they fail. Identifies error patterns (Edit's "old_str not found" after compaction), oversized returns (Grep averaging 18K tokens), and unused tools.

Works on single sessions or multi-session with `--since`.

```
$ cctx tools <project> --since 7d

  53 sessions | 1,847 tool calls

  Tool               Calls   Errors  Avg tokens   Avg latency  Total cost
  ──────────────────────────────────────────────────────────────────────────
  Read               612     2       4,200        0.3s         $8.42
  Grep               234     0       18,200       1.2s         $6.84
  Bash               156     31      11,300       4.8s         $5.12
  Edit               189     12      800          0.2s         $1.22

  Patterns
  ──────────────────────────────────────────────────────────────────────────
  ⚠ Bash: 19.9% error rate. Top: "command not found" (12x)
  ⚠ Grep: avg 18,200 tokens, median referenced: 3 lines
  ⚠ Edit: 6.3% error rate, all "old_str not found" — likely compaction
```

### `cctx trace` — TUI trace viewer

Terminal-based step-through viewer of a completed session. Each turn is a card showing user message, assistant response (truncated), tool calls with token counts, and running context/cost meter. Navigate with arrow keys. Press enter to expand tool result payloads. Press `c` for per-turn context decomposition.

Not a fork-and-replay debugger — just a readable, navigable view of what happened.

```
$ cctx trace <session>

  ┌─ Turn 1 ──────────────────────────────────────────────┐
  │ User: Fix the authentication bug in the login flow    │
  │                                                        │
  │ Assistant: I'll investigate the login flow. Let me     │
  │ start by reading the relevant files.                   │
  │                                                        │
  │ → Read auth/login.ts (4,200 tokens)                   │
  │ → Read auth/middleware.ts (2,800 tokens)               │
  │                                                        │
  │ Context: 24,400 / 200,000 (12.2%)   Cost so far: $0.04│
  └────────────────────────────────────────────────────────┘

  [↑/↓ navigate] [enter: expand tool results] [t: token view]
  [f: filter by tool] [c: context breakdown] [q: quit]
```

### `cctx loops` — retry and loop detection

Detects when the agent gets stuck: retrying a failing test without changing approach, re-reading a file it already had in context, calling the same tool with the same arguments repeatedly. Reports the token cost of each loop and suggests CLAUDE.md instructions to prevent them.

```
$ cctx loops <session>

  Loop 1 (turns 14-18): Test retry loop
  ──────────────────────────────────────────────────────────
  Turn 14: Bash(npm test) → 3 failures
  Turn 15: Edit(auth.ts) → fix attempt
  Turn 16: Bash(npm test) → same 3 failures
  Turn 17: Edit(auth.ts) → same fix, different line
  Turn 18: Bash(npm test) → same 3 failures

  Pattern: retried 3x without changing approach
  Token cost: 34,200 tokens ($0.38)
  Suggestion: Add to CLAUDE.md: "If tests fail twice with the
  same errors, stop and reassess before retrying."
```

Detection: pattern matching on tool sequences. Same tool + same args within N turns = redundant. Same tool + same error + retry = loop. Simple heuristics, high confidence.

### `cctx slow` — latency profiling

Where is wall-clock time going? Breaks down by model inference, tool execution (per tool), and rate-limit waits. Identifies the slowest turns. Requires timestamps in the trace (Agent SDK provides these).

```
$ cctx slow <session>

  Session: 4m 32s total

  By category                    Time      %
  ──────────────────────────────────────────
  Model inference               2m 48s    61.8%
  Tool execution                1m 12s    26.5%
    Bash (npm test)               42s
    playwright:screenshot          18s
  Waiting (rate limits)            32s    11.8%
```

### `cctx lint` — config static analysis

Analyzes CLAUDE.md, `.claude/settings.json`, MCP server configs, and hooks for common problems. Doesn't analyze traces — analyzes config files. Three categories: quality (contradictions, vague instructions, nonexistent tool references), efficiency (tool search disabled, no compaction override, oversized CLAUDE.md), security (sandboxing, permissions).

Cross-references with `cctx analyze` data when available — "tool search is disabled *and based on your actual usage it's costing you $8.20/week*."

```
$ cctx lint <project>

  CLAUDE.md
  ──────────────────────────────────────────────────────────
  ⚠ Line 12 vs 34: potential contradiction
    "Always use TypeScript" vs "Use Python for data processing"

  ✗ Line 22: references tool "SearchAndReplace"
    → This tool doesn't exist. Did you mean "Edit"?

  ⚠ Line 45: "Be careful with the database"
    → Not actionable. What specifically should the agent avoid?

  Settings
  ──────────────────────────────────────────────────────────
  ⚠ tool_search: false — est. $8.20/week wasted (from cctx analyze)
  ⚠ No compaction threshold override — est. $3.10/week (from cctx analyze)
  ✓ Sandboxing: enabled
```

### `cctx bench` — variance testing

Run the same prompt N times and measure consistency. Reports mean/std/p5/p95 for cost, turns, duration, and tool calls. Identifies what drives variance (file read count, grep result size, retry loops). Flags outliers.

This is the only subcommand that requires running the agent (not just parsing logs), so it requires the Agent SDK and an API key.

```
$ cctx bench "Review this PR for bugs" --runs 10 --dataset ./test-prs/

  10 runs × 20 test PRs = 200 executions

  Cost         mean: $0.094    std: $0.031    p5: $0.052    p95: $0.148
  Turns        mean: 8.2       std: 2.1
  Duration     mean: 14.6s     std: 4.8s

  High variance driven by:
    - File read count (r=0.82 with cost)
    - Grep result size (r=0.71 with cost)
```

### `cctx export` — data export

Export parsed traces in standard formats for external analysis.

```
cctx export <session> --format jsonl      # normalized trace
cctx export <session> --format csv        # one row per turn
cctx export <session> --format otel       # OpenTelemetry spans
cctx export <project> --since 7d --format parquet  # multi-session for pandas
```

### `cctx compare` — before/after comparison

Compare two sessions or two time periods. Designed for measuring the impact of config changes: "I enabled tool search on May 5. Did it actually reduce cost?"

```
cctx compare <session-a> <session-b>
cctx compare --before 2026-05-05 --after 2026-05-05 <project>
```

---

## What it is NOT

- Not a dashboard, not a SaaS, not a desktop app
- Not real-time in v1 (analyzes completed sessions)
- Not exact (context decomposition is approximate — there's a 5-15% gap for internal API framing that can't be observed from outside)
- Not a profiler for Cursor, Codex, or other non-Anthropic tools (v1 targets Claude Code + Agent SDK only)
- Not an agent itself (except `cctx bench`, all subcommands analyze logs, they don't run agents)

## Data sources

### Claude Code sessions (primary target)
Claude Code writes JSONL transcripts to `~/.claude/projects/<project>/<session>/`. Each line is a message event with role, content, and (for assistant messages) usage data. The tool also reads session_memory files for auto-memory content.

### Agent SDK traces
The SDK emits AssistantMessage objects with usage (input_tokens, output_tokens, cache_creation, cache_read) and tool call content. If the user runs cctx as a hook or wrapper, capture the full message stream.

### Promptfoo eval output
Promptfoo captures tool calls in response.metadata.toolCalls and can emit OpenTelemetry spans. Parse the eval output JSON for post-hoc analysis of eval runs.

## Architecture

```
Session log (JSONL / SDK trace / Promptfoo JSON)
  ↓
Parser (normalize to common trace format)
  ↓
Tokenizer (anthropic.count_tokens() on each component)
  ↓
Decomposer (assign each token block to a category)
  ↓
Analyzers (one per subcommand, composable):
  ├── decomposer.py     — context decomposition (profile)
  ├── waste.py           — waste detection (profile, analyze)
  ├── cost.py            — cost attribution (cost, analyze)
  ├── tools.py           — tool efficiency (tools)
  ├── loops.py           — loop/retry detection (loops)
  ├── latency.py         — timing analysis (slow)
  ├── lint.py            — config static analysis (lint)
  ├── variance.py        — consistency analysis (bench)
  └── aggregator.py      — multi-session stats (analyze)
  ↓
Renderers:
  ├── Terminal (rich tables, sparklines, colored output)
  ├── TUI (textual app for trace viewer)
  └── HTML (flamegraph, trend charts)
  ↓
Exporters:
  ├── jsonl, csv, otel, parquet
```

### Project layout

```
cctx/
├── cli.py              # click CLI, routes to subcommands
├── parsers/
│   ├── claude_code.py  # parse ~/.claude JSONL logs
│   ├── agent_sdk.py    # parse Agent SDK trace output
│   └── promptfoo.py    # parse Promptfoo eval JSON
├── tokenizer.py        # wrapper around anthropic.count_tokens()
├── models.py           # Turn, SessionTrace, SessionSummary, ProjectAnalysis
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
│   ├── flamegraph.py   # HTML flamegraph template
│   └── tui.py          # textual TUI for trace viewer
└── exporters/
    ├── jsonl.py
    ├── csv.py
    ├── otel.py
    └── parquet.py
```

### Common data model

```python
@dataclass
class Turn:
    turn_number: int
    role: str  # "user" | "assistant" | "tool_result"
    content: str
    token_count: int
    tool_name: Optional[str]
    tool_input: Optional[dict]
    timestamp: Optional[datetime]
    duration_ms: Optional[int]
    error: Optional[str]

@dataclass
class SessionTrace:
    session_id: str
    project_path: str
    turns: list[Turn]
    system_prompt: Optional[str]
    tools: list[ToolDefinition]
    memory: Optional[str]
    usage_per_step: list[Usage]
    start_time: datetime
    end_time: datetime

@dataclass
class SessionSummary:
    session_id: str
    timestamp: datetime
    duration_seconds: float
    turn_count: int
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    context_at_end: int
    compaction_triggered: bool
    compaction_turn: Optional[int]
    tools_loaded: list[str]
    tools_used: list[str]
    component_token_turns: dict
    waste_token_turns: int
    loop_count: int
    loop_waste_tokens: int
    recommendations: list[str]

@dataclass
class ProjectAnalysis:
    project_path: str
    date_range: tuple[datetime, datetime]
    sessions: list[SessionSummary]
    total_cost: float
    avg_cost_per_session: float
    median_cost_per_session: float
    p95_cost_per_session: float
    total_waste_cost: float
    waste_rate: float
    tool_waste_rates: dict[str, float]
    stale_content_rates: dict[str, float]
    daily_trends: dict[str, list[float]]
    recommendations: list[Recommendation]
```

## Key design decisions

### Approximate decomposition is fine
The API's input_tokens count includes internal framing you can't see. Your reconstructed total will be ~85-95% of the actual. Show the gap as "internal/other" in the output. Don't pretend to be exact. The value is in the relative proportions and waste detection, not in precise accounting.

### Token-turns is the key metric
A component's current token count doesn't capture its real cost. A 24K tool description block loaded at turn 1 and present for 25 turns costs 600K token-turns. A 22K grep result that arrived at turn 24 costs 22K token-turns. Token-turns = tokens × turns_present. Rank everything by this metric.

### Binary waste detection only (v1)
"This MCP server was loaded but none of its tools were ever called" — high confidence, trivially detectable. "This tool result was partially used" — low confidence, requires embeddings, fragile. Ship the binary version. Don't guess about partial use until there's a reliable method.

### Stale history detection via last-referenced heuristic
For each content block in conversation history, scan subsequent assistant responses for token overlap (exact n-gram matching). If zero overlap for N+ turns, flag as "likely stale." Conservative and cheap to compute.

### Recommendations must be copy-pasteable
Every recommendation includes the exact config change, env var, or hook definition. Lower the barrier to action to zero.

### Every subcommand works single-session AND multi-session
Where it makes sense, subcommands accept either a session path or a project path with `--since`. Single-session gives details. Multi-session gives patterns. Same analyzer, different aggregation level.

## Multi-session analysis

### What it sees that single-session can't

**Chronic waste.** "github-mcp unused in 47 of 50 sessions" is a verdict, not a data point.

**Drift.** "Average context waste increased from 22% to 38% over the last two weeks."

**Systemic stale content.** "Grep results go stale in 91% of sessions."

**Compaction behavior.** "Fires in 73% of sessions between turns 12–15. Lower the threshold."

**Cost projections.** "This project will cost $192/month. With fixes: $121/month."

### The compare command

`cctx compare --before 2026-05-05 --after 2026-05-05` splits sessions at a date boundary and compares aggregate metrics. Designed for measuring config change impact. Shows before/after with percentage change.

### Data model additions

See `SessionSummary` and `ProjectAnalysis` in the data model section above. The aggregator builds a `ProjectAnalysis` from a list of `SessionSummary` objects using pandas groupby and describe.

## Tech stack

- Python 3.10+
- anthropic SDK (for token counting via the tokenizer)
- rich (for terminal output — tables, colors, progress bars, sparklines)
- textual (for the TUI trace viewer)
- click (for CLI interface)
- pandas (for multi-session aggregation)
- Jinja2 (for HTML report templates)
- No web framework. No database. No cloud.

## What makes this get stars

1. **Immediate value on first run.** `pip install cctx && cctx profile ~/.claude/projects/myapp/sessions/latest` produces a useful report in under 10 seconds. No config, no setup, no API keys.

2. **The "oh shit" moment.** "github-mcp: 8,200 tokens, never used, costing you $0.25/session."

3. **The "oh shit" moment, compounded.** `cctx analyze --since 30d` → "you've wasted $74 this month on unused MCP servers."

4. **The suite is one install.** `pip install cctx` gives you ten tools, not one. Each one is useful on its own. Together they're comprehensive.

5. **Good README.** Show terminal output for every subcommand. Show a before/after with `cctx compare`. Include a flamegraph screenshot. Blog post explaining token-turns.

6. **Works with what people already have.** No instrumentation. No config changes. Reads the session logs that already exist.

7. **Respects the developer.** No telemetry, no cloud, no sign-up. Everything local.

## Build order

1. **cctx profile + cctx analyze** — the foundation. Parser, tokenizer, decomposer, waste detection, aggregation. (2–3 weekends)
2. **cctx cost + cctx tools** — reuses everything from step 1, low-hanging fruit. (1 weekend)
3. **cctx loops + cctx slow** — pattern matching on traces. (1 weekend)
4. **cctx lint** — different data source (config files) but simple and useful. (1 weekend)
5. **cctx trace** — TUI, more UI work, highest polish. (1–2 weekends)
6. **cctx bench** — requires running agents, ship last. (1–2 weekends)
7. **cctx export + cctx compare** — utilities, add when someone asks.

## Stretch goals (after v1)

- **VS Code extension** showing flamegraph in a webview panel after a session
- **GitHub Action** running `cctx analyze` on CI, commenting on PRs with context diffs
- **Claude Code skill** (`/cctx`) running analysis from within a session
- **Live mode** using a filesystem watcher — updates the report as the session progresses
- **MCP server** exposing cctx analysis as tools, so agents can profile their own sessions
- **Cross-project analysis** comparing patterns across different projects
- **Team aggregation** across multiple developers sharing a project

## Non-goals

- Don't build a web app
- Don't build user accounts or auth
- Don't add a database
- Don't try to be real-time in v1
- Don't try to detect partial-use waste with embeddings in v1
- Don't try to profile Cursor, Codex, or other non-Anthropic tools in v1
- Don't build fork-and-replay debugging in v1

## First session prompt

Start Claude Code with:

"Read this project brief. We're building cctx, an open-source Python CLI suite that profiles, debugs, and optimizes Claude Code and Agent SDK sessions. It has 10 subcommands that share a common parser, tokenizer, and data model. Start by exploring the JSONL format that Claude Code writes to ~/.claude/projects/ — what does a session transcript actually look like? What fields are available? Then design the parser that normalizes it into our common trace format (the Turn and SessionTrace dataclasses). We'll build the tokenizer integration and decomposer next, then cctx profile, then cctx analyze, then the rest of the suite one at a time."
