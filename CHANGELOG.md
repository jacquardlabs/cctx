# CHANGELOG

<!-- version list -->

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
