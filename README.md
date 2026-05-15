# cctx

Diagnose your Claude Code sessions — find out when they went wrong, why they cost what they did, and what to add to your `CLAUDE.md` so it doesn't happen again.

## Install

```
pip install cctx
```

## Quick start

Point cctx at a session file from `~/.claude/projects/`:

```
cctx autopsy ~/.claude/projects/<project>/<session>.jsonl
```

## Commands

### `cctx autopsy <session>` — diagnose a session

Runs three pattern classifiers (retry loop, scope creep, stale context) and shows findings with attributed cost.

```
cctx autopsy ~/.claude/projects/myapp/abc123.jsonl
```

Options:
- `--html FILE` — write a self-contained HTML report instead of terminal output

### `cctx autopsy <project> --since N` — cross-session patterns

Analyse all sessions in a project directory modified in the last N days.

```
cctx autopsy ~/.claude/projects/myapp --since 7
```

### `cctx harvest <session>` — apply patches to CLAUDE.md

After autopsy finds issues, harvest proposes copy-pasteable CLAUDE.md additions.

```
cctx harvest ~/.claude/projects/myapp/abc123.jsonl --dry-run
cctx harvest ~/.claude/projects/myapp/abc123.jsonl --apply
```

### `cctx export <session>` — export session data

Export session analysis as JSONL or CSV for external tools.

```
cctx export ~/.claude/projects/myapp/abc123.jsonl --format csv --out session.csv
```

### `cctx trace <session>` — interactive TUI

Step through the session turn by turn with findings overlaid.

```
cctx trace ~/.claude/projects/myapp/abc123.jsonl
```

## What cctx detects

| Pattern | What it means |
|---|---|
| **Retry loop** | The same tool call failing 2+ times with no successful fix |
| **Scope creep** | Assistant expanding scope mid-task ("while I'm here, let me also...") |
| **Stale context** | Large tool results sitting in context long after they're useful |

## Cost attribution

cctx estimates session cost using Anthropic's billing rates (input, cache reads at 10%, cache writes at 125%). Stale context waste is attributed as `content_tokens × billed_turns_stale`. These are approximations; actual API billing may differ slightly.

## Requirements

- Python 3.10+
- Claude Code session logs at `~/.claude/projects/`
- No API key required for analysis (optional for exact token counting)

## Session log location

Claude Code writes session logs to `~/.claude/projects/<url-encoded-project-path>/<session-id>.jsonl`. The project path is URL-encoded with `-` replacing `/`, so `/Users/you/Projects/myapp` becomes `-Users-you-Projects-myapp`.

## License

MIT
