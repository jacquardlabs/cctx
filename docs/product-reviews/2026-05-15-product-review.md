# cctx Product Health Review — 2026-05-15

First review. No prior product-review to compare against. PRODUCT.md does not exist; Part 3 proposes a greenfield draft rather than a diff.

Source documents treated as product truth: `cctx-project-brief.md` (product pitch, examples, growth staircase) and `CLAUDE.md` (build order, architecture decisions). These two documents are in tension in places; the review names those tensions explicitly.

---

## Part 1 — Is the product brief still true?

### 1. Persona check

The brief does not define named personas. It describes the user implicitly: a developer who runs Claude Code regularly, reviews session history to understand what went wrong, and maintains a `CLAUDE.md`. The user is hands-on, cost-aware, and already familiar with the agent workflow.

**Recent feature history verdict:** Every PR since the pivot stays inside this persona's orbit. The parser, tokenizer, diagnostician, recommender, harvest, export, trace TUI — all are tools for a developer looking at their own sessions after the fact. There is no drift toward enterprise users, toward teams, toward dashboards, or toward hypothetical use cases that the primary persona doesn't own. The build has been remarkably focused.

One soft signal: `harvest` introduces an interactive confirmation flow (`click.confirm`). That is appropriate for the persona and adds no scope risk. Still: interactive flows are harder to compose in scripts; the `--apply` and `--dry-run` flags address this well.

**Verdict: No persona drift detected.**

### 2. Principles check

The brief states eight design decisions. Evaluating each against the shipped code:

**"Diagnose the specific session, not the aggregate."**
Honored. The diagnostician always runs per-session. The aggregator calls the per-session pipeline and collects results. The aggregate renderer is explicitly separate.
No recent decision bent this principle.

**"Token-turns is a useful metric for stale-content attribution."**
Honored in `stale_context.py`: `token_turns = content_tokens × billed_stale_turns` where `billed_stale` counts only assistant turns, not user/tool_result turns. The cost fix PR (#55) explicitly refined this. This is the most technically careful implementation in the codebase.

**"Approximate decomposition is fine."**
Honored in the diagnostician's `_compute_total_cost`. Cache reads and writes are approximated at 0.1× and 1.25× base rate. The tokenizer's offline fallback uses word-count heuristics. The system internals gap is not surfaced to the user in terminal output, which is a mild gap against the stated principle ("The system internals slice is honest; don't pretend to be exact"). The terminal renderer shows total cost without a confidence annotation.

**"Binary waste detection only in v1."**
Fully honored. `harvest.py:_is_supported_target` accepts only `CLAUDE.md`, not `rules`, `skill`, or `ADR`. The `dead_end.py` and `tool_thrash.py` pattern files listed in the brief do not exist. This is disciplined scoping, not drift — the classifier files that do exist are high-confidence.

**"Patches must be copy-pasteable."**
Honored. `claude_md.py` generates append-style unified diffs. `harvest.py:apply_patch` appends cleanly and checks for duplicate headings. The actual diff content is template-driven, not LLM-generated, which keeps it deterministic and always copy-pasteable.

**"Single-session AND cross-session, same diagnostician."**
Honored. `aggregate.run` calls `diagnostician.run` in a loop. The recommender handles both paths separately (`generate` vs `generate_from_evidence`) which is the right split — evidence accumulation is inherently different from single-session diagnosis.

**"Group up, never down."**
Honored at the parser level (per-JSONL-line granularity). Honored at the aggregate level (individual session Diagnoses collected before any aggregation). Clean.

**"Deterministic over LLM-assisted in v0."**
Fully honored. No `anthropic` calls anywhere except the tokenizer's `count_tokens`. The diagnostician is entirely heuristic. There are no LLM-generated patch texts.

**Verdict: Principles are honored consistently. One mild gap: the cost approximation honesty principle is not surfaced in output.**

### 3. Feature map accuracy

The brief's v0 surface is four subcommands. Comparing against `cli.py`:

| Brief claim | Shipped | Gap |
|---|---|---|
| `cctx autopsy <session>` | Yes | See flag gaps below |
| `cctx autopsy <project> --since` | Yes | `--since` accepts `int` (days) only, not `7d`/`2w`/date range/`--until`/`--top N` as brief shows |
| `cctx export <session> --format` | Partial | Only `jsonl` and `csv` shipped. `html` and `json` not in `exporters/`. The CLI `--format` `Choice` lists only `["jsonl","csv"]` |
| `cctx trace <session>` | Yes | Non-interactive as described |
| `cctx harvest <session>` | Yes — ahead of schedule | Brief calls this "v1". It shipped in M5 before M6 release |

**Pattern classifiers:**
Brief lists 5 classifiers: retry_loop, scope_creep, stale_context, dead_end, tool_thrash.
`cctx/diagnostician/patterns/` contains: `retry_loop.py`, `scope_creep.py`, `stale_context.py`.
`dead_end.py` and `tool_thrash.py` do not exist.

**FindingKind enum in `models.py` lists exactly 3 variants:** `RETRY_LOOP`, `SCOPE_CREEP`, `STALE_CONTEXT`. No enum entries for the two unshipped classifiers. This is internally consistent — the models were narrowed to match the shipped scope. Clean.

**Patch targets:**
Brief's `Patch.target` is `Literal["CLAUDE.md","rules","skill","ADR"]`.
Shipped `Patch.target_file: str` with `harvest.py` accepting only `"CLAUDE.md"`. Other targets return `SKIPPED`. Code comments explicitly note "v0". This is intentional narrowing, not drift.

**Export formats:**
Brief shows `--format jsonl/html/json/csv`. Only `jsonl` and `csv` exist. `html` export moved to `autopsy --html` (HTML report renderer `renderers/report.py` is a single-session rendering surface, not an exporter). `json` export is not shipped. The brief's `exporters/html.py` and `exporters/json.py` stubs are listed in the project layout but these files don't exist in the codebase.

**Terminal output shape:**
Brief's example output includes a `Verdict: ⚠ retry loop + scope creep` headline. The terminal renderer (`terminal.py`) has no verdict line — it renders per-finding badges and the `inflection_turn` number. The brief also shows the aggregate output with an interactive "Press a number to inspect" prompt. The shipped aggregate renderer is read-only (no interactivity).

**`Diagnosis` dataclass:**
Brief defines `Diagnosis` with a `verdict: str` field. Shipped `Diagnosis` in `models.py` has no `verdict` field — it has `inflection_turn`, `findings`, `patches`, `total_cost_usd`, `waste_cost_usd`, `analysed_at`. This is a deliberate simplification: verdict is implied by the findings list.

**Version:**
Brief example outputs show `cctx v0.1.0`. `pyproject.toml` has `version = "0.0.1"`. The project is not yet at `0.1.0`. This is consistent with M6 ("Release v0.1.0") being the final milestone.

**pyproject description:**
Current `description = "Profile, debug, and optimize Claude Code and Agent SDK sessions"`. This reads broader than the product actually is (no "optimize", no "Agent SDK" support). The narrower pitch — "Diagnose Claude Code sessions: when they went wrong, why, and what to add to CLAUDE.md" — is more accurate.

### 4. "Not building" check

Brief's explicit non-goals: no SaaS, no agents, no real-time in v1, no fork-and-replay, no multi-provider, no eval framework competition, no exact cost decomposition, no reckless dependencies.

None of these have crept in. The harvest subcommand is the closest thing to a boundary test — it writes to disk — but it writes to `CLAUDE.md` which is explicitly what the product is supposed to produce as output. Not a violation.

`pandas` is listed in the brief as optional for cross-session aggregation. It is listed in `CLAUDE.md` similarly. It is not in `pyproject.toml` dependencies. The aggregator uses only stdlib and the existing diagnostician. This is good scope discipline.

**No "not building" boundary crossings detected.**

### 5. Known problems freshness

The brief and CLAUDE.md do not maintain a formal "known problems" list. Observed gaps that should be tracked:

**Problems that were present in the brief and are now fixed:**
- The parser design spec existed before implementation (shipped as #35). No gap there.
- CI was a known gap (issue #2); shipped as PR #38.
- Fixture corpus was a known gap (issue #3); shipped as PR #36.

**Active gaps that should be treated as known problems before M6 release:**

1. **Brief advertises 5 pattern classifiers; 3 are shipped.** The brief reads as a promise. If M6 ships without narrowing this claim, users installing from PyPI will look for patterns that don't fire.

2. **Export formats mismatch.** Brief says `--format html/json` exist. They don't. The brief should be updated to reflect that `html` is `autopsy --html` and `json` is not in v0.1.0.

3. **`--since` flag accepts integers only, not the string formats shown in brief.** `cctx autopsy --since 7d` will fail; `--since 7` works. User-facing help text says `DAYS` (integer), which is clear — but the brief's examples (`--since 7d`, `--since 2w`, `--since 2026-05-01 --until`) are wrong.

4. **No `README.md`.** `pyproject.toml` points to `cctx-project-brief.md` as the readme. The brief is written as an internal design document (it contains architecture diagrams, build order, a "First session prompt" for Claude). This is fine for now but is a release blocker: PyPI will render `cctx-project-brief.md` as the package readme, which would confuse package users.

5. **Version mismatch.** `pyproject.toml` is `0.0.1`. Brief examples show `0.1.0`. M6 is supposed to be the `0.1.0` release — this is the expected state, not a bug, but it means M6's first task is the version bump.

6. **`pyproject.toml` description is inaccurate.** "Profile, debug, and optimize Claude Code and Agent SDK sessions" overstates scope and mentions Agent SDK which is not supported.

---

## Part 2 — Product coherence

### Does this feel like one product?

Yes. The data model is the connective tissue: `SessionTrace` → `Diagnosis` → `Patch` → applied to `CLAUDE.md`. Every subcommand operates on this same chain. A user who understands one subcommand can predict what the others do. The flow is:

1. `autopsy` — understand what happened and why, get proposed CLAUDE.md patches
2. `harvest` — apply those patches (or review them first with `--dry-run`)
3. `export` — save the session data for external analysis
4. `trace` — step through the session interactively with findings overlaid

This is a coherent product loop. The commands reinforce each other rather than being independent silos.

### Feature interaction

The `autopsy → harvest` path is smooth: `autopsy` produces `Patches`, `harvest` applies them. The bridge is explicit in both the code and the CLI design.

The `autopsy → export` path is also clean: `export` re-runs `autopsy` internally (parses, diagnoses, runs recommender) before exporting. This is slightly redundant if a user has already run `autopsy` on the same session, but it is stateless and fast, so this is not a practical problem.

The `trace` command runs the full diagnosis pipeline internally, which means the TUI shows the same findings as `autopsy` would. This is correct behavior — the trace view is a navigable rendering of the same analysis, not a different analysis.

The `--since` cross-session path is wired through the same per-session diagnostician as single-session mode, which is what the brief intended. The evidence accumulator in `recommender/evidence.py` is correctly invoked only on the cross-session path.

**Natural connections not yet built:**
- The aggregate output lists recurring patterns but does not link back to which sessions contributed to each pattern. A "drill down from aggregate to session" path exists in the brief's interactive mock (`Press a number to inspect that pattern`) but is not in the shipped CLI. This is a missing interaction that would make the aggregate more useful.

### Complexity audit

Asking "if we removed this, would users notice and care?" for each feature:

- `autopsy` (single-session): This is the entire product. Cannot remove.
- `autopsy --since`: Adds genuine value by surfacing recurring patterns. Users who run cctx regularly would notice immediately. Keep.
- `harvest`: Closes the loop from diagnosis to action. Without it, users must manually copy-paste the diff. High value. Keep.
- `harvest --dry-run` / `--apply` flags: Both necessary for a write-to-disk operation. These flags add no complexity burden — they prevent harm.
- `export jsonl`: Useful for users who want to feed diagnosis data into other tools or build dashboards. Low daily use; high ceiling for power users. Keep.
- `export csv`: Similar value to jsonl for spreadsheet users. Keep.
- `trace` TUI: This is a high-complexity surface (Textual, interactive, async). It surfaces real value (navigable session view with finding overlay) but is the hardest feature to maintain. The question is not whether to remove it but whether it works reliably enough for v0.1.0. Given CI passes and it launched in PR #57, treat as shipped.

No feature is clearly deadweight.

### Onboarding path

Target: new user gets to core value in under 60 seconds.

**Actual path:**
1. `pip install cctx` — fast
2. User needs to locate a session file in `~/.claude/projects/<project>/`. The project directory name is URL-encoded (e.g., `-Users-bryan-Projects-myapp`). This is friction point 1: the user has to know where to look and which file to pick.
3. `cctx autopsy ~/.claude/projects/<encoded-name>/<session>.jsonl` — this is a long path to type. Friction point 2.
4. Output renders in the terminal. If there are no findings, "No findings — session looks clean." is accurate but may feel anticlimactic.

**Friction points:**
- No `cctx ls` or equivalent to list available sessions. Users have to navigate the filesystem manually.
- The URL-encoded project directory names (`-Users-bryan-Projects-myapp`) are opaque. The brief's examples use clean names; reality is messier.
- No brief "first run" hint in the CLI itself. `cctx --help` shows the subcommands but gives no path to a first session.

These are not blockers for v0 (the brief calls cctx a tool for developers who already know where their logs live) but they are friction that will reduce first-run success rates at PyPI distribution scale.

---

## Part 3 — Proposed PRODUCT.md (greenfield)

Since no PRODUCT.md exists, the following is a proposed first draft — not a diff. This document captures only the product layer (personas, principles, feature map, non-goals, known problems). Architecture and layering rules remain in CLAUDE.md where they belong.

---

```markdown
# PRODUCT.md — cctx

## What is this

cctx is a local Python CLI that reads Claude Code session logs and tells you what went wrong, why it cost what it did, and what to add to your CLAUDE.md so it doesn't happen again.

It is a forensic tool, not a monitoring tool. You reach for it after a session — when something felt off, when the bill was higher than expected, or on a weekly review pass.

## Primary persona

**The regular Claude Code user** who:
- Runs multiple Claude Code sessions per day across one or more projects
- Maintains a CLAUDE.md and wants it to get smarter over time
- Is willing to read a terminal report and act on its suggestions
- Cares about cost and session quality but does not need a dashboard
- Is comfortable with the command line and with `~/.claude/projects/` on disk

This persona is already the target; everything shipped to date serves them directly.

## What cctx is NOT for

- Teams or organizations (no shared reports, no access control, no multi-user state)
- Real-time monitoring (completed sessions only in v0 and v1)
- General cost dashboards (CodeBurn covers that; cctx is forensic)
- Multi-provider support (Claude Code only in v0/v1)
- Users who do not read session transcripts or maintain CLAUDE.md

## Product principles

**1. Forensic, not ambient.**
cctx is used after something goes wrong, not as background infrastructure. Every feature should be justified by this use case: "I just ran a session, something went sideways, I want to know what."

**2. Output must be actionable.**
Every report should produce at least one thing the user can do immediately. Findings without patches are incomplete. Patches must be copy-pasteable or auto-applicable.

**3. Honest about uncertainty.**
Costs are approximated (85–95% of actual). Pattern classifiers fire only on high-confidence signals. Low-confidence signals are shown with explicit confidence labels. "System internals" token budget is never hidden or misattributed.

**4. Local and stateless.**
No network calls in the core analysis path (tokenizer may call the API for token counting; that is opt-in). No persistent database. No telemetry. No account. Users own their data.

**5. Deterministic.**
Pattern classifiers are heuristics, not LLM calls. The same session file produces the same output every time. Testable on fixtures. Predictable cost to run.

**6. Small surface, deep on each command.**
Four commands. No command is shallow. Users should be able to learn the product in an afternoon and trust what it tells them.

## Feature map (v0.1.0)

### Shipped

| Feature | Command | Status |
|---|---|---|
| Single-session diagnosis | `cctx autopsy <session>` | Shipped (M2) |
| Cross-session pattern detection | `cctx autopsy <project> --since N` | Shipped (M2) |
| HTML report | `cctx autopsy <session> --html FILE` | Shipped (M2/PR#59) |
| Session trace TUI | `cctx trace <session>` | Shipped (M3) |
| JSONL export | `cctx export <session> --format jsonl` | Shipped (M4) |
| CSV export | `cctx export <session> --format csv` | Shipped (M4) |
| Harvest (CLAUDE.md patcher) | `cctx harvest <session>` | Shipped (M5) |
| Cross-session harvest | `cctx harvest <project> --since N` | Shipped (M5) |

### Pattern classifiers (v0.1.0)

| Pattern | Status |
|---|---|
| Retry loop | Shipped |
| Scope creep | Shipped |
| Stale context | Shipped |
| Dead-end exploration | Not shipped in v0 |
| Tool thrashing | Not shipped in v0 |

### NOT in v0.1.0

- `--format json` and `--format html` on `export` (html moved to `autopsy --html`; json not scheduled)
- `--since` string formats (`7d`, `2w`, date ranges, `--until`, `--top N`) — accepts integer days only
- Patch targets other than `CLAUDE.md` (rules, skills, ADR — v1+)
- Interactive aggregate drill-down ("press N to inspect pattern") — read-only in v0
- `cctx ls` / session discovery helper
- Dead-end and tool-thrash classifiers

## What we are NOT building

- A SaaS or cloud product
- An agent (cctx reads logs; it does not call the Anthropic API except optionally for token counting)
- A real-time watcher (v2+ roadmap item)
- Multi-provider support (v3+ roadmap item)
- A fork-and-replay debugger
- A general eval or testing framework

## Known problems (as of 2026-05-15)

**Release blockers for v0.1.0 (M6):**

1. **No README.md.** `pyproject.toml` uses `cctx-project-brief.md` as the readme. The brief contains architecture diagrams and an internal "First session prompt" that should not be on PyPI. A user-facing README.md is required before publish.

2. **`pyproject.toml` description is inaccurate.** Current: "Profile, debug, and optimize Claude Code and Agent SDK sessions." Accurate: "Diagnose Claude Code sessions — find what went wrong, what it cost, and what to add to CLAUDE.md."

3. **Version is `0.0.1`.** M6 requires bumping to `0.1.0`.

4. **Brief example outputs show unshipped features.** The `cctx-project-brief.md` (which currently IS the readme) shows 5 pattern classifiers, 4 export formats, string `--since` arguments, a `Verdict` headline, and interactive aggregate output. None of these are accurate for the shipped CLI. Before PyPI publish, either ship them or update the brief.

**Active gaps (non-blocking for v0.1.0 but worth tracking):**

5. **Cost approximation honesty not surfaced in output.** The terminal renderer shows `$X.XX` total cost with no confidence annotation. The brief says "The system internals slice is honest; don't pretend to be exact" — this is a principle not yet expressed to users in output.

6. **No session discovery helper.** Users must manually navigate URL-encoded project directories in `~/.claude/projects/` to find session files. First-run friction.

7. **Aggregate output is read-only.** The brief's example shows an interactive aggregate view. Shipped aggregate is a static table. The interactive drill-down is a meaningful UX gap that the brief implicitly promises.
```

---

## Summary

The shipped product is more disciplined than the brief. The brief over-promises on classifiers (5 vs 3 shipped), export formats (4 vs 2), `--since` flexibility, terminal output shape, and interactivity. The code internals are clean: layering invariants are honored, tests pass (250 green), the data model flows coherently through every subcommand.

The primary action item before M6 / v0.1.0 release is aligning the public-facing documents with the actual shipped scope:

1. Write a user-facing `README.md` to replace `cctx-project-brief.md` as the PyPI readme.
2. Update `pyproject.toml` description.
3. Bump version to `0.1.0` in `pyproject.toml`.
4. Either ship or explicitly defer dead_end/tool_thrash classifiers, JSON export, and string `--since` parsing — and update the brief to match whichever choice is made.

The product coherence is strong. The four-verb surface (autopsy / harvest / export / trace) is tight, the persona is unambiguous, and no boundary-crossing features have crept in. The brief is the drift; the code is not.
