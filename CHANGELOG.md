# CHANGELOG

<!-- version list -->

## v1.7.0 (2026-06-11)

### Bug Fixes

- Jsonl exporter — subagent_costs in dict literal; fix import sort
  ([#109](https://github.com/jacquardlabs/cctx/pull/109),
  [`d1bc0fa`](https://github.com/jacquardlabs/cctx/commit/d1bc0fa039070ecfa671f38f5c43c864ed17e61a))

- Remove unused ToolResult import in test_diagnostician_subagents
  ([#109](https://github.com/jacquardlabs/cctx/pull/109),
  [`d1bc0fa`](https://github.com/jacquardlabs/cctx/commit/d1bc0fa039070ecfa671f38f5c43c864ed17e61a))

### Documentation

- Restore billing-rate explanation in _compute_own_cost
  ([#109](https://github.com/jacquardlabs/cctx/pull/109),
  [`d1bc0fa`](https://github.com/jacquardlabs/cctx/commit/d1bc0fa039070ecfa671f38f5c43c864ed17e61a))

### Features

- Diagnostician — inclusive cost + per-subagent attribution
  ([#109](https://github.com/jacquardlabs/cctx/pull/109),
  [`d1bc0fa`](https://github.com/jacquardlabs/cctx/commit/d1bc0fa039070ecfa671f38f5c43c864ed17e61a))

- HTML report + JSON exporter — subagent_costs output
  ([#109](https://github.com/jacquardlabs/cctx/pull/109),
  [`d1bc0fa`](https://github.com/jacquardlabs/cctx/commit/d1bc0fa039070ecfa671f38f5c43c864ed17e61a))

- Per-subagent cost attribution in autopsy (#88)
  ([#109](https://github.com/jacquardlabs/cctx/pull/109),
  [`d1bc0fa`](https://github.com/jacquardlabs/cctx/commit/d1bc0fa039070ecfa671f38f5c43c864ed17e61a))

- SubagentAttribution model + Diagnosis.subagent_costs field
  ([#109](https://github.com/jacquardlabs/cctx/pull/109),
  [`d1bc0fa`](https://github.com/jacquardlabs/cctx/commit/d1bc0fa039070ecfa671f38f5c43c864ed17e61a))

- Terminal renderer — subagent cost table in autopsy output
  ([#109](https://github.com/jacquardlabs/cctx/pull/109),
  [`d1bc0fa`](https://github.com/jacquardlabs/cctx/commit/d1bc0fa039070ecfa671f38f5c43c864ed17e61a))


## v1.6.0 (2026-06-10)

### Bug Fixes

- Harvest — preview_patches dedup per (target, heading) not heading-only
  ([#108](https://github.com/jacquardlabs/cctx/pull/108),
  [`afa964c`](https://github.com/jacquardlabs/cctx/commit/afa964c68b445030e1fafe9f41c67a0de4afcd2d))

- Harvest — shorten local-import comment under 100-char line limit
  ([#108](https://github.com/jacquardlabs/cctx/pull/108),
  [`afa964c`](https://github.com/jacquardlabs/cctx/commit/afa964c68b445030e1fafe9f41c67a0de4afcd2d))

### Documentation

- Harvest — correct misleading local-import comment
  ([#108](https://github.com/jacquardlabs/cctx/pull/108),
  [`afa964c`](https://github.com/jacquardlabs/cctx/commit/afa964c68b445030e1fafe9f41c67a0de4afcd2d))

- Spec deviation note (sync returns patches) + PRODUCT.md cross-agent emit row
  ([#108](https://github.com/jacquardlabs/cctx/pull/108),
  [`afa964c`](https://github.com/jacquardlabs/cctx/commit/afa964c68b445030e1fafe9f41c67a0de4afcd2d))

### Features

- Cctx harvest --emit — cross-agent layer to AGENTS.md (#82)
  ([#108](https://github.com/jacquardlabs/cctx/pull/108),
  [`afa964c`](https://github.com/jacquardlabs/cctx/commit/afa964c68b445030e1fafe9f41c67a0de4afcd2d))

- Cli — harvest --emit / --sync cross-agent emit
  ([#108](https://github.com/jacquardlabs/cctx/pull/108),
  [`afa964c`](https://github.com/jacquardlabs/cctx/commit/afa964c68b445030e1fafe9f41c67a0de4afcd2d))

- Harvest — EMIT_TARGETS + retarget_patches (fan-out to AGENTS.md)
  ([#108](https://github.com/jacquardlabs/cctx/pull/108),
  [`afa964c`](https://github.com/jacquardlabs/cctx/commit/afa964c68b445030e1fafe9f41c67a0de4afcd2d))

- Harvest — sync_managed_sections backfills CLAUDE.md into emit target
  ([#108](https://github.com/jacquardlabs/cctx/pull/108),
  [`afa964c`](https://github.com/jacquardlabs/cctx/commit/afa964c68b445030e1fafe9f41c67a0de4afcd2d))

- Models — MANAGED_HEADINGS registry for cctx-owned CLAUDE.md sections
  ([#108](https://github.com/jacquardlabs/cctx/pull/108),
  [`afa964c`](https://github.com/jacquardlabs/cctx/commit/afa964c68b445030e1fafe9f41c67a0de4afcd2d))

### Testing

- Emit + sync idempotency through apply_patches
  ([#108](https://github.com/jacquardlabs/cctx/pull/108),
  [`afa964c`](https://github.com/jacquardlabs/cctx/commit/afa964c68b445030e1fafe9f41c67a0de4afcd2d))

- End-to-end fan-out to both targets; spec: reconcile sync error contract
  ([#108](https://github.com/jacquardlabs/cctx/pull/108),
  [`afa964c`](https://github.com/jacquardlabs/cctx/commit/afa964c68b445030e1fafe9f41c67a0de4afcd2d))

- Lock MANAGED_HEADINGS registry to recommender templates
  ([#108](https://github.com/jacquardlabs/cctx/pull/108),
  [`afa964c`](https://github.com/jacquardlabs/cctx/commit/afa964c68b445030e1fafe9f41c67a0de4afcd2d))


## v1.5.1 (2026-06-10)

### Bug Fixes

- Recommender — add TOOL_THRASH/DEAD_END patch templates
  ([#107](https://github.com/jacquardlabs/cctx/pull/107),
  [`3c79d58`](https://github.com/jacquardlabs/cctx/commit/3c79d58a55af106d3fd81542e70b8f892569185c))

### Documentation

- Product review 2026-06-09 + M15 cross-agent emit spec
  ([#107](https://github.com/jacquardlabs/cctx/pull/107),
  [`3c79d58`](https://github.com/jacquardlabs/cctx/commit/3c79d58a55af106d3fd81542e70b8f892569185c))


## v1.5.0 (2026-05-20)

### Bug Fixes

- Agents.py — guard against non-list JSON, tighten patch targets
  ([`c41c42c`](https://github.com/jacquardlabs/cctx/commit/c41c42cb366904fc332638b8f97ee042f17b45c2))

- Renderer — guard order, tmp_path fixtures, missing no-badge tests
  ([`8f26afd`](https://github.com/jacquardlabs/cctx/commit/8f26afdf27c63641942b434e47a2fb7b24d38068))

- Watcher — hermetic tests, reuse _encode_path, rename clarity
  ([`a7b52de`](https://github.com/jacquardlabs/cctx/commit/a7b52def47b13447d956476a0ec6782fe2d0247b))

### Documentation

- Implementation plan for claude agents live integration
  ([`2136adf`](https://github.com/jacquardlabs/cctx/commit/2136adf0697a695d27f438f0368e7bd5ba406e89))

- Spec for claude agents --json live session integration
  ([`0df2381`](https://github.com/jacquardlabs/cctx/commit/0df23813a90c66e57d0d39c6b959859b89a5c057))

### Features

- Add agents.py — live_sessions() via claude agents --json
  ([`83b704f`](https://github.com/jacquardlabs/cctx/commit/83b704ffbe4303dbd316257a01eb0b59307c0e06))

- Cctx ls — pass live_statuses to renderer for live session badges
  ([`65445d7`](https://github.com/jacquardlabs/cctx/commit/65445d75a213bf26401fe044a2409d2ce0efbcb1))

- Render_sessions/render_projects — live status badges via live_statuses param
  ([`3d77687`](https://github.com/jacquardlabs/cctx/commit/3d776879c9ce03a622361c2b804e5986d40f37a1))

- Watcher — live session detection + early idle exit via claude agents --json
  ([`a11481c`](https://github.com/jacquardlabs/cctx/commit/a11481c2126fead87e1f92bfecc7bf5ac3f39d1a))


## v1.4.0 (2026-05-20)

### Bug Fixes

- Deduplicate harvest check import, align severity badge output
  ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))

- Move defaultdict import to top-level, add _words() return type
  ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))

- Use removeprefix instead of lstrip to preserve .claude/skills/ dot prefix
  ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))

### Documentation

- M15 harvest --check depth design spec ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))

- M15 harvest --check depth implementation plan
  ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))

### Features

- --check-severity flag and severity badges in harvest --check output
  ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))

- Check_contradictions() — always/never keyword heuristic
  ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))

- Check_redundancy() — Jaccard similarity ≥ 0.8 on section word sets
  ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))

- Check_staleness() — backtick function refs grepped against project source
  ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))

- CheckSeverity enum, severity field on CheckFinding, new CheckIssue values
  ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))

- Harvest --check depth — contradiction, redundancy, staleness detectors + --check-severity
  ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))

- Wire all four detectors into check_claude_md ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))

### Refactoring

- Check_redundancy — compute _words once per section, remove dead union guard
  ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))

- Check_staleness — module-level _STALENESS_EXCLUDED, min-len in regex, per-file search
  ([#87](https://github.com/jacquardlabs/cctx/pull/87),
  [`ee08734`](https://github.com/jacquardlabs/cctx/commit/ee0873431383b285769195efc4b2f70f5d07cdeb))


## v1.3.0 (2026-05-17)

### Bug Fixes

- Drop unused turn_number from result_map in _find_pairs
  ([#86](https://github.com/jacquardlabs/cctx/pull/86),
  [`cefc438`](https://github.com/jacquardlabs/cctx/commit/cefc438f9ff638ba2abf529663b5e24707f03bbb))

- Restore WHY comment, fix_key != failure_key guard, tighten tuple annotation
  ([#86](https://github.com/jacquardlabs/cctx/pull/86),
  [`cefc438`](https://github.com/jacquardlabs/cctx/commit/cefc438f9ff638ba2abf529663b5e24707f03bbb))

- Ruff lint failures (E501, F401, E741, I001) ([#86](https://github.com/jacquardlabs/cctx/pull/86),
  [`cefc438`](https://github.com/jacquardlabs/cctx/commit/cefc438f9ff638ba2abf529663b5e24707f03bbb))

### Documentation

- M14 project-pattern-detection implementation plan
  ([#86](https://github.com/jacquardlabs/cctx/pull/86),
  [`cefc438`](https://github.com/jacquardlabs/cctx/commit/cefc438f9ff638ba2abf529663b5e24707f03bbb))

- M14 project-specific pattern detection design spec
  ([#86](https://github.com/jacquardlabs/cctx/pull/86),
  [`cefc438`](https://github.com/jacquardlabs/cctx/commit/cefc438f9ff638ba2abf529663b5e24707f03bbb))

- Note why harvest --since skips project_specific.detect()
  ([#86](https://github.com/jacquardlabs/cctx/pull/86),
  [`cefc438`](https://github.com/jacquardlabs/cctx/commit/cefc438f9ff638ba2abf529663b5e24707f03bbb))

### Features

- Add ProjectPattern model, AggregateReport.project_patterns, FindingKind.PROJECT_PATTERN
  ([#86](https://github.com/jacquardlabs/cctx/pull/86),
  [`cefc438`](https://github.com/jacquardlabs/cctx/commit/cefc438f9ff638ba2abf529663b5e24707f03bbb))

- Aggregate.run() returns (Diagnosis, SessionTrace) pairs
  ([#86](https://github.com/jacquardlabs/cctx/pull/86),
  [`cefc438`](https://github.com/jacquardlabs/cctx/commit/cefc438f9ff638ba2abf529663b5e24707f03bbb))

- Generate_from_patterns() — CLAUDE.md patches from ProjectPatterns
  ([#86](https://github.com/jacquardlabs/cctx/pull/86),
  [`cefc438`](https://github.com/jacquardlabs/cctx/commit/cefc438f9ff638ba2abf529663b5e24707f03bbb))

- M14 project-specific pattern detection ([#86](https://github.com/jacquardlabs/cctx/pull/86),
  [`cefc438`](https://github.com/jacquardlabs/cctx/commit/cefc438f9ff638ba2abf529663b5e24707f03bbb))

- Project_specific.detect() — cross-session failure/fix pattern detector
  ([#86](https://github.com/jacquardlabs/cctx/pull/86),
  [`cefc438`](https://github.com/jacquardlabs/cctx/commit/cefc438f9ff638ba2abf529663b5e24707f03bbb))

- Render_aggregate() shows project-specific patterns table
  ([#86](https://github.com/jacquardlabs/cctx/pull/86),
  [`cefc438`](https://github.com/jacquardlabs/cctx/commit/cefc438f9ff638ba2abf529663b5e24707f03bbb))

- Wire project_specific.detect() into autopsy and harvest --since paths
  ([#86](https://github.com/jacquardlabs/cctx/pull/86),
  [`cefc438`](https://github.com/jacquardlabs/cctx/commit/cefc438f9ff638ba2abf529663b5e24707f03bbb))


## v1.2.0 (2026-05-17)

### Features

- --until DATE, autopsy --json, export --format json (M12 #77 #78 #79)
  ([#84](https://github.com/jacquardlabs/cctx/pull/84),
  [`803b5f1`](https://github.com/jacquardlabs/cctx/commit/803b5f190404679ddef4cbbec7478d04c57b8413))


## v1.1.0 (2026-05-17)

### Chores

- Add skip-existing to pypi publish action
  ([`23d7e16`](https://github.com/jacquardlabs/cctx/commit/23d7e16e18074da3c25899ba98298100ad3c1ad3))

### Features

- M9 polish — verdict headline, --top N, --turn N
  ([#83](https://github.com/jacquardlabs/cctx/pull/83),
  [`b0d2f27`](https://github.com/jacquardlabs/cctx/commit/b0d2f273a373c5a2f52c9de3a3fb2721da59c4f5))

- M9 polish — verdict headline, --top N, and --turn N
  ([#83](https://github.com/jacquardlabs/cctx/pull/83),
  [`b0d2f27`](https://github.com/jacquardlabs/cctx/commit/b0d2f273a373c5a2f52c9de3a3fb2721da59c4f5))

### Refactoring

- Cache verdict, fix markup=False bug, use reverse=True
  ([#83](https://github.com/jacquardlabs/cctx/pull/83),
  [`b0d2f27`](https://github.com/jacquardlabs/cctx/commit/b0d2f273a373c5a2f52c9de3a3fb2721da59c4f5))


## v1.0.0 (2026-05-17)

### Continuous Integration

- Add python-semantic-release for fully automated CD
  ([`9844921`](https://github.com/jacquardlabs/cctx/commit/98449213e5b3bd597c47d54e4d5043e245adafe4))

- Add workflow_dispatch to release.yml for manual trigger
  ([`08ac9f8`](https://github.com/jacquardlabs/cctx/commit/08ac9f80eb6ceee7b57155852febc4274cbaf3b0))


## v0.2.0 (2026-05-16)

### Bug Fixes

- Ruff lint — B904, E402, E501, F841 across cli, tests, and renderers
  ([`fa7105f`](https://github.com/jacquardlabs/cctx/commit/fa7105fef340d89136f1996b86824e30d080a730))

- Trace TUI token sum within line-length limit
  ([`5b7416c`](https://github.com/jacquardlabs/cctx/commit/5b7416c5b92790cfe66f1e53f20891ecaf6e03b0))

### Chores

- Bump version to 0.2.0, update PRODUCT.md and CLAUDE.md
  ([`828ed49`](https://github.com/jacquardlabs/cctx/commit/828ed4997df9f4a264669bc38f4b10588a151f1c))

### Documentation

- Add CI usage section clarifying harvest is local-only
  ([`c526408`](https://github.com/jacquardlabs/cctx/commit/c526408a35749858e1c0b0b6ba42aea95bb8f621))

### Features

- **#64,#63**: Tool-thrash and dead-end exploration classifiers
  ([`14f8f45`](https://github.com/jacquardlabs/cctx/commit/14f8f45f9d3f4ef2fefac374d3e4cea36185c60d))

- **#65**: Harvest v2 — route patches to any .md target (.claude/rules/, .claude/skills/)
  ([`06ef9b7`](https://github.com/jacquardlabs/cctx/commit/06ef9b7a8ae9abacea54c2c826efc3fb6e6e80be))

- **#66**: Cctx harvest --check audits CLAUDE.md for dead refs and empty sections
  ([`a3be1d0`](https://github.com/jacquardlabs/cctx/commit/a3be1d0923d387b6830b10c7c2c5acf34a3b8917))

- **#67**: Interactive aggregate drill-down; --check docs in README
  ([`3db5429`](https://github.com/jacquardlabs/cctx/commit/3db5429dede40777b23d83e32a4b15a8c0e82a16))

- **#68**: --since accepts 7d, 2w, YYYY-MM-DD, and date ranges
  ([`434d7c4`](https://github.com/jacquardlabs/cctx/commit/434d7c448406e0a5465380ed395e1fadaa1c0db1))

- **#69**: Annotate costs as estimates (~85–95%) in terminal and HTML output
  ([`5a49889`](https://github.com/jacquardlabs/cctx/commit/5a49889bd43555d30a58c2b78eddf6acbb0d8e97))

- **#70**: Cctx watch — live waste signals during an active session
  ([`f533a13`](https://github.com/jacquardlabs/cctx/commit/f533a13e1f087da00457ce7b8215934f20c403a2))

- **#72**: Cctx autopsy --github-summary writes findings to GitHub Actions job summary
  ([`df91256`](https://github.com/jacquardlabs/cctx/commit/df91256b58b75a9bbe9594a000b00dee2ac2fbc5))

- **#73**: Cctx GitHub Action (composite) + --fail-on-findings flag
  ([`9229584`](https://github.com/jacquardlabs/cctx/commit/9229584ea192ce1b1ee6718721d981cba0ca13e0))

### Refactoring

- Consolidate KIND_LABEL, fix private import, clean up watcher tests
  ([`31ad4d7`](https://github.com/jacquardlabs/cctx/commit/31ad4d75885eed9c8238c4eb1c08bd5d1ba51a15))


## v0.1.0 (2026-05-16)

- Initial Release
