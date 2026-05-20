# Design: `claude agents --json` Live Integration

**Date:** 2026-05-19  
**Status:** Draft

## Overview

Claude Code recently added `claude agents --json`, which returns a JSON array of all live Claude sessions with their `sessionId`, `cwd`, `status` (busy/idle), `pid`, and `kind` (interactive/background). This spec describes integrating that data into two cctx surfaces:

1. **`cctx watch`** — use live session data to find the active session more precisely and short-circuit the idle timeout when the session exits
2. **`cctx ls`** — show a live status badge (green `●`) next to sessions that are currently running

OTEL `agent_id`/`parent_agent_id` spans are explicitly out of scope — they are a separate telemetry stream not present in the JSONL logs cctx reads.

## New module: `cctx/agents.py`

A single-responsibility module for querying the Claude Code process list. Imports only stdlib (`subprocess`, `json`, `datetime`, `dataclasses`). No imports from any other cctx module.

### Data model

```python
@dataclass
class LiveSession:
    session_id: str    # matches JSONL filename stem
    cwd: str
    status: str        # "busy" | "idle"
    pid: int
    kind: str          # "interactive" | "background"
    started_at: datetime
```

### Public API

```python
def live_sessions() -> list[LiveSession]:
    """Shell out to `claude agents --json`. Returns [] on any failure."""
```

`live_sessions()` runs `["claude", "agents", "--json"]` with a 2-second timeout. It catches and swallows all failures silently, returning `[]`:

- `FileNotFoundError` — `claude` not on PATH
- `subprocess.TimeoutExpired` — command hung
- Non-zero exit code
- `json.JSONDecodeError` — malformed output
- Missing or unexpected keys in a record (per-record, not all-or-nothing)

No exception ever propagates to callers. Callers treat `[]` as "live data unavailable, fall back to existing behavior."

## Changes to `watcher.py`

### Session detection

`_find_active_session(project_dir)` gains a primary path before the existing mtime fallback:

1. Call `live_sessions()`
2. Filter to sessions where `_encode_path(Path(live_session.cwd)) == project_dir.name` — i.e. encode the live session's raw `cwd` the same way `discovery._encode_path()` does and compare to the project directory name
3. If a match is found, resolve `project_dir / f"{live_session.session_id}.jsonl"` and return it if the file exists
4. If `live_sessions()` returns `[]` or no match, fall back to the existing `max(..., key=st_mtime)` heuristic

### Idle detection

The `_tail()` loop currently waits `_IDLE_TIMEOUT = 30.0` seconds of no file growth before declaring done. With live data available, we can short-circuit:

- The idle check path (file size not grown) calls `live_sessions()` once
- If the watched `session_id` is no longer present in the result (session exited), declare done immediately — we don't rely on the `status` field value, just presence/absence
- The 30s timeout remains as the fallback when `claude` is not on PATH or `live_sessions()` returns `[]`

`live_sessions()` is called **only when file growth has already stalled**, never on every tick during active sessions. No subprocess overhead during normal operation.

## Changes to `renderers/terminal.py`

`render_sessions()` and `render_projects()` gain an optional parameter:

```python
def render_sessions(sessions: list[SessionMeta], live_ids: frozenset[str] = frozenset(), ...) -> None
def render_projects(projects: list[ProjectInfo], live_ids: frozenset[str] = frozenset(), ...) -> None
```

When a session's `session_id` is in `live_ids`, the row is decorated with a green `●` and the status string (e.g. `● busy`). When `live_ids` is empty, output is identical to today — no visual change for users without a live session.

`SessionMeta` and `ProjectInfo` are not modified. Live state is strictly a view-layer concern.

## Changes to `cli.py`

The `ls` command calls `live_sessions()` once before rendering, builds `live_ids = frozenset(s.session_id for s in live_sessions())`, and passes it to the renderer. No other commands are affected.

## Layering

| Module | Imports from `agents.py`? |
|---|---|
| `agents.py` | — (no cctx imports) |
| `watcher.py` | yes — `live_sessions()` |
| `cli.py` | yes — `live_sessions()` |
| `renderers/terminal.py` | no — receives `live_ids: frozenset[str]` from CLI |
| `discovery.py` | no |

`agents.py` sits at the same layer as `discovery.py` — both are data-access modules below the CLI.

## Error handling summary

All error handling is contained in `agents.py`. Callers need no try/except blocks. The contract is: `live_sessions()` always returns a list, possibly empty.

## Testing

**`agents.py`**
- Mock `subprocess.run` to return a valid JSON fixture → verify correct `LiveSession` list returned
- Mock to raise `FileNotFoundError` → verify `[]` returned
- Mock to return malformed JSON → verify `[]` returned
- Mock to return JSON with a missing field → verify that record is skipped, others parsed correctly

**`watcher.py`**
- Patch `live_sessions()` to return a matching session → verify `_find_active_session()` returns the JSONL by session_id, not mtime
- Patch `live_sessions()` to return `[]` → verify mtime fallback still works
- Patch `live_sessions()` to return a list not including the watched session_id → verify `_tail()` exits immediately instead of waiting 30s

**`renderers/terminal.py`**
- Call `render_sessions()` with a non-empty `live_ids` containing one session ID → verify `●` badge appears in output
- Call with empty `live_ids` → verify output unchanged from today

## Files touched

- `cctx/agents.py` — new file
- `cctx/watcher.py` — `_find_active_session()` and `_tail()` updated
- `cctx/renderers/terminal.py` — `render_sessions()` and `render_projects()` gain `live_ids` param
- `cctx/cli.py` — `ls` command fetches `live_sessions()` and passes `live_ids` to renderer
- `tests/test_agents.py` — new test file
- `tests/test_watcher.py` — extended with live-session cases
- `tests/test_renderers.py` — extended with live badge snapshot
