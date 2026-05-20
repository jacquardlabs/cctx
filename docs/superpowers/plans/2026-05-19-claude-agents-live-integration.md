# claude agents --json Live Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate `claude agents --json` into cctx so `cctx watch` detects live sessions precisely and `cctx ls` shows live status badges.

**Architecture:** New `cctx/agents.py` module shells out to `claude agents --json` and returns a list of `LiveSession` dataclasses; `watcher.py` uses it for session detection and early idle exit; `renderers/terminal.py` accepts a `live_statuses` dict and renders green `●` badges; `cli.py` wires the ls command.

**Tech Stack:** Python stdlib (`subprocess`, `json`, `dataclasses`, `datetime`), rich for badges, pytest + unittest.mock for tests.

---

## File map

| Action | File | Purpose |
|---|---|---|
| Create | `cctx/agents.py` | `live_sessions() -> list[LiveSession]`; all subprocess logic |
| Create | `tests/test_agents.py` | Unit tests for agents.py |
| Modify | `cctx/watcher.py` | Use `live_sessions()` in `_find_active_session` + `_tail` |
| Modify | `tests/test_watcher.py` | New tests for live-detection paths |
| Modify | `cctx/renderers/terminal.py` | `live_statuses` param on `render_sessions` + `render_projects` |
| Modify | `tests/test_terminal_renderer.py` | Live badge snapshot tests |
| Modify | `cctx/cli.py` | `ls` fetches `live_sessions()` and passes `live_statuses` |

---

## Task 1: Create `cctx/agents.py`

**Files:**
- Create: `cctx/agents.py`
- Create: `tests/test_agents.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agents.py`:

```python
"""Tests for cctx/agents.py."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

_SAMPLE_JSON = json.dumps([
    {
        "pid": 12345,
        "cwd": "/Users/user/Projects/myapp",
        "kind": "interactive",
        "startedAt": 1779239605842,
        "sessionId": "abc123de-0000-0000-0000-000000000000",
        "status": "busy",
    },
    {
        "pid": 12346,
        "cwd": "/Users/user/Projects/other",
        "kind": "background",
        "startedAt": 1779239605000,
        "sessionId": "def456gh-0000-0000-0000-000000000000",
        "status": "idle",
    },
])


def _mock_run(stdout: str, returncode: int = 0) -> MagicMock:
    mock = MagicMock()
    mock.stdout = stdout
    mock.returncode = returncode
    return mock


def test_live_sessions_parses_valid_json() -> None:
    from cctx.agents import live_sessions

    with patch("subprocess.run", return_value=_mock_run(_SAMPLE_JSON)):
        result = live_sessions()

    assert len(result) == 2
    assert result[0].session_id == "abc123de-0000-0000-0000-000000000000"
    assert result[0].cwd == "/Users/user/Projects/myapp"
    assert result[0].status == "busy"
    assert result[0].pid == 12345
    assert result[0].kind == "interactive"
    assert result[1].status == "idle"
    assert result[1].kind == "background"


def test_live_sessions_returns_empty_when_claude_not_found() -> None:
    from cctx.agents import live_sessions

    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = live_sessions()

    assert result == []


def test_live_sessions_returns_empty_on_timeout() -> None:
    from cctx.agents import live_sessions

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["claude"], 2)):
        result = live_sessions()

    assert result == []


def test_live_sessions_returns_empty_on_nonzero_exit() -> None:
    from cctx.agents import live_sessions

    with patch("subprocess.run", return_value=_mock_run("", returncode=1)):
        result = live_sessions()

    assert result == []


def test_live_sessions_returns_empty_on_bad_json() -> None:
    from cctx.agents import live_sessions

    with patch("subprocess.run", return_value=_mock_run("not valid json")):
        result = live_sessions()

    assert result == []


def test_live_sessions_skips_bad_records_keeps_good() -> None:
    from cctx.agents import live_sessions

    # First record missing required "sessionId"; second is valid.
    data = json.dumps([
        {"pid": 1, "cwd": "/foo", "startedAt": 1000000000000},
        {
            "pid": 99,
            "cwd": "/bar",
            "kind": "interactive",
            "startedAt": 1779239605842,
            "sessionId": "good-session-id",
            "status": "busy",
        },
    ])
    with patch("subprocess.run", return_value=_mock_run(data)):
        result = live_sessions()

    assert len(result) == 1
    assert result[0].session_id == "good-session-id"


def test_live_session_started_at_is_utc_datetime() -> None:
    from datetime import timezone

    from cctx.agents import live_sessions

    with patch("subprocess.run", return_value=_mock_run(_SAMPLE_JSON)):
        result = live_sessions()

    assert result[0].started_at.tzinfo == timezone.utc
    # 1779239605842 ms → reasonable year
    assert result[0].started_at.year >= 2025
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_agents.py -v
```

Expected: `ModuleNotFoundError: No module named 'cctx.agents'` or similar — all tests fail.

- [ ] **Step 3: Create `cctx/agents.py`**

```python
"""Live Claude Code agent query via `claude agents --json`.

Public API:
    live_sessions() -> list[LiveSession]
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class LiveSession:
    session_id: str    # matches JSONL filename stem in ~/.claude/projects/
    cwd: str
    status: str        # "busy" | "idle"
    pid: int
    kind: str          # "interactive" | "background"
    started_at: datetime


def live_sessions() -> list[LiveSession]:
    """Query `claude agents --json`. Returns [] on any failure."""
    try:
        result = subprocess.run(
            ["claude", "agents", "--json"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except FileNotFoundError:
        return []
    except subprocess.TimeoutExpired:
        return []

    if result.returncode != 0:
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    sessions: list[LiveSession] = []
    for item in data:
        try:
            sessions.append(
                LiveSession(
                    session_id=item["sessionId"],
                    cwd=item["cwd"],
                    status=item.get("status", "unknown"),
                    pid=int(item["pid"]),
                    kind=item.get("kind", "interactive"),
                    started_at=datetime.fromtimestamp(
                        item["startedAt"] / 1000, tz=timezone.utc
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return sessions
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_agents.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add cctx/agents.py tests/test_agents.py
git commit -m "feat: add agents.py — live_sessions() via claude agents --json"
```

---

## Task 2: Update `watcher.py` — live session detection + idle short-circuit

**Files:**
- Modify: `cctx/watcher.py`
- Modify: `tests/test_watcher.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_watcher.py`:

```python
def test_find_active_session_prefers_live_session(tmp_path: Path) -> None:
    """When live_sessions() returns a cwd match, that JSONL wins over mtime."""
    import time
    from datetime import datetime, timezone
    from unittest.mock import patch

    from cctx.agents import LiveSession

    # Build a fake project dir whose name equals the encoded cwd.
    cwd_path = tmp_path / "myproject"
    cwd_path.mkdir()
    encoded_name = cwd_path.resolve().as_posix().replace("/", "-")
    project_dir = tmp_path / encoded_name
    project_dir.mkdir()

    # live-session.jsonl is OLDER by mtime; other-session.jsonl is NEWER.
    live_jl = project_dir / "live-session.jsonl"
    other_jl = project_dir / "other-session.jsonl"
    live_jl.write_text("{}\n")
    time.sleep(0.02)
    other_jl.write_text("{}\n")

    live = [LiveSession(
        session_id="live-session",
        cwd=str(cwd_path),
        status="busy",
        pid=1,
        kind="interactive",
        started_at=datetime.now(timezone.utc),
    )]

    with patch("cctx.watcher.live_sessions", return_value=live):
        from cctx.watcher import _find_active_session
        result = _find_active_session(project_dir)

    assert result == live_jl


def test_find_active_session_falls_back_to_mtime_when_no_live(tmp_path: Path) -> None:
    """When live_sessions() returns [], mtime fallback picks the newest file."""
    import time
    from unittest.mock import patch

    old = tmp_path / "old.jsonl"
    new = tmp_path / "new.jsonl"
    old.write_text("{}\n")
    time.sleep(0.02)
    new.write_text("{}\n")

    with patch("cctx.watcher.live_sessions", return_value=[]):
        from cctx.watcher import _find_active_session
        result = _find_active_session(tmp_path)

    assert result == new


def test_tail_exits_early_when_session_leaves_live_list(
    tmp_path: Path, monkeypatch
) -> None:
    """_tail exits as soon as the session disappears from live_sessions(), not after 30s."""
    import time as _time
    from datetime import datetime, timezone
    from unittest.mock import patch

    import cctx.watcher as watcher_mod
    from cctx.agents import LiveSession

    session_path = tmp_path / "abc123.jsonl"
    session_path.write_text("{}\n")

    live_session = LiveSession(
        session_id="abc123",
        cwd=str(tmp_path),
        status="busy",
        pid=1,
        kind="interactive",
        started_at=datetime.now(timezone.utc),
    )

    call_count: dict[str, int] = {"n": 0}

    def fake_live_sessions() -> list[LiveSession]:
        call_count["n"] += 1
        return [live_session] if call_count["n"] == 1 else []

    monkeypatch.setattr(watcher_mod, "_IDLE_TIMEOUT", 30.0)  # would be slow if hit
    monkeypatch.setattr(watcher_mod, "_POLL_INTERVAL", 0.01)

    start = _time.monotonic()
    with patch("cctx.watcher.live_sessions", side_effect=fake_live_sessions):
        count = watcher_mod._tail(session_path)
    elapsed = _time.monotonic() - start

    assert isinstance(count, int)
    assert elapsed < 5.0, f"_tail took {elapsed:.1f}s — should have exited early via live detection"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_watcher.py::test_find_active_session_prefers_live_session tests/test_watcher.py::test_find_active_session_falls_back_to_mtime_when_no_live tests/test_watcher.py::test_tail_exits_early_when_session_leaves_live_list -v
```

Expected: all three fail (ImportError or assertion error — `_find_active_session` doesn't call `live_sessions` yet).

- [ ] **Step 3: Update `_find_active_session` in `cctx/watcher.py`**

Replace the existing `_find_active_session` function (currently lines 36–45):

```python
def _find_active_session(project_dir: Path) -> Path | None:
    """Return the JSONL for the active session in project_dir.

    Prefers the live session from `claude agents --json` when available;
    falls back to most-recently-modified JSONL.
    """
    from cctx.agents import live_sessions

    encoded_name = project_dir.name
    for live in live_sessions():
        if live.cwd:
            live_encoded = Path(live.cwd).resolve().as_posix().replace("/", "-")
            if live_encoded == encoded_name:
                candidate = project_dir / f"{live.session_id}.jsonl"
                if candidate.exists():
                    return candidate

    candidates = list(project_dir.glob("*.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)
```

- [ ] **Step 4: Update `_tail` in `cctx/watcher.py`**

Replace the existing `_tail` function. The full new version (changes are in the `else` branch of the size check):

```python
def _tail(session_path: Path) -> int:
    """Tail session_path, re-running classifiers on each growth event.

    Returns the number of unique findings detected.
    """
    from cctx.agents import live_sessions

    seen_keys: set[tuple[FindingKind, int]] = set()
    last_size = 0
    idle_since: float | None = None
    session_id = session_path.stem
    session_seen_live = False  # True once we've confirmed claude is available

    print(f"Watching {session_path.name} …  Ctrl+C to stop.", flush=True)

    while True:
        try:
            current_size = session_path.stat().st_size
        except OSError:
            time.sleep(_POLL_INTERVAL)
            continue

        if current_size > last_size:
            last_size = current_size
            idle_since = None

            try:
                trace = _parse_trace(session_path)
                diagnosis = diagnostician.run(trace)
            except Exception:
                time.sleep(_POLL_INTERVAL)
                continue

            for finding in diagnosis.findings:
                key = _finding_key(finding)
                if key not in seen_keys:
                    seen_keys.add(key)
                    print(_format_finding(finding), flush=True)
        else:
            now = time.monotonic()
            if idle_since is None:
                idle_since = now
            else:
                live = live_sessions()
                live_ids = {s.session_id for s in live}
                if live:
                    session_seen_live = True
                if session_seen_live and session_id not in live_ids:
                    print(
                        f"\nSession ended — analysis complete. "
                        f"Findings detected: {len(seen_keys)}",
                        flush=True,
                    )
                    return len(seen_keys)
                if now - idle_since >= _IDLE_TIMEOUT:
                    print(
                        f"\nSession idle for {_IDLE_TIMEOUT:.0f}s — analysis complete. "
                        f"Findings detected: {len(seen_keys)}",
                        flush=True,
                    )
                    return len(seen_keys)

        time.sleep(_POLL_INTERVAL)
```

- [ ] **Step 5: Run all watcher tests to verify they pass**

```bash
uv run pytest tests/test_watcher.py -v
```

Expected: all tests pass, including the 3 new ones.

- [ ] **Step 6: Commit**

```bash
git add cctx/watcher.py tests/test_watcher.py
git commit -m "feat: watcher — live session detection + early idle exit via claude agents --json"
```

---

## Task 3: Add live badges to `renderers/terminal.py`

**Files:**
- Modify: `cctx/renderers/terminal.py`
- Modify: `tests/test_terminal_renderer.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_terminal_renderer.py`:

```python
def test_render_sessions_shows_live_badge(tmp_path: Path) -> None:
    """A session whose ID is in live_statuses gets a ● badge in the output."""
    from io import StringIO

    from rich.console import Console

    from cctx.discovery import ProjectInfo, SessionMeta
    from cctx.renderers.terminal import render_sessions

    from datetime import datetime, timezone

    session = SessionMeta(
        path=tmp_path / "abc12345.jsonl",
        session_id="abc12345-0000-0000-0000-000000000000",
        start_time=datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc),
        cwd="/some/path",
        git_branch="main",
    )
    project = ProjectInfo(
        project_dir=tmp_path,
        display_name="~/some/path",
        sessions=[session],
    )

    buf = StringIO()
    con = Console(file=buf, highlight=False, markup=False)
    render_sessions(
        project,
        live_statuses={"abc12345-0000-0000-0000-000000000000": "busy"},
        console=con,
    )
    output = buf.getvalue()

    assert "●" in output
    assert "busy" in output


def test_render_sessions_no_badge_when_not_live(tmp_path: Path) -> None:
    """Sessions not in live_statuses get no badge — output matches prior behavior."""
    from io import StringIO

    from rich.console import Console

    from cctx.discovery import ProjectInfo, SessionMeta
    from cctx.renderers.terminal import render_sessions

    from datetime import datetime, timezone

    session = SessionMeta(
        path=tmp_path / "abc12345.jsonl",
        session_id="abc12345-0000-0000-0000-000000000000",
        start_time=datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc),
        cwd="/some/path",
        git_branch="main",
    )
    project = ProjectInfo(
        project_dir=tmp_path,
        display_name="~/some/path",
        sessions=[session],
    )

    buf = StringIO()
    con = Console(file=buf, highlight=False, markup=False)
    render_sessions(project, live_statuses={}, console=con)
    output = buf.getvalue()

    assert "●" not in output


def test_render_projects_shows_live_badge(tmp_path: Path) -> None:
    """A project with a live session shows a ● badge in the project listing."""
    from io import StringIO

    from rich.console import Console

    from cctx.discovery import ProjectInfo, SessionMeta
    from cctx.renderers.terminal import render_projects

    from datetime import datetime, timezone

    session = SessionMeta(
        path=tmp_path / "abc12345.jsonl",
        session_id="abc12345-0000-0000-0000-000000000000",
        start_time=datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc),
        cwd="/some/path",
        git_branch="main",
    )
    project = ProjectInfo(
        project_dir=tmp_path,
        display_name="~/some/path",
        sessions=[session],
    )

    buf = StringIO()
    con = Console(file=buf, highlight=False, markup=False)
    render_projects(
        [project],
        live_statuses={"abc12345-0000-0000-0000-000000000000": "busy"},
        console=con,
    )
    output = buf.getvalue()

    assert "●" in output
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_terminal_renderer.py::test_render_sessions_shows_live_badge tests/test_terminal_renderer.py::test_render_sessions_no_badge_when_not_live tests/test_terminal_renderer.py::test_render_projects_shows_live_badge -v
```

Expected: all three fail — `render_sessions` and `render_projects` don't accept `live_statuses` yet.

- [ ] **Step 3: Update `render_sessions` in `cctx/renderers/terminal.py`**

Change the signature and table rendering. Locate the existing `render_sessions` function (around line 329) and replace it:

```python
def render_sessions(
    project: ProjectInfo,
    *,
    live_statuses: dict[str, str] | None = None,
    console: Console | None = None,
) -> None:
    con = console or _default_console()
    _live = live_statuses or {}

    con.print(Rule(f"cctx — {project.display_name}"))
    if not project.sessions:
        con.print("No sessions found.")
        return

    table = Table(show_header=True, box=None, pad_edge=False, show_edge=False)
    table.add_column("Session", style="bold")
    table.add_column("Date", style="dim")
    table.add_column("Branch", style="dim")
    table.add_column("Path", style="dim")
    table.add_column("Status")

    for s in project.sessions:
        date_str = s.start_time.strftime("%Y-%m-%d %H:%M") if s.start_time else "—"
        if s.session_id in _live:
            status_cell = Text(f"● {_live[s.session_id]}", style="green bold")
        else:
            status_cell = Text("")
        table.add_row(
            s.session_id[:8],
            date_str,
            s.git_branch or "—",
            str(s.path),
            status_cell,
        )
    con.print(table)
    con.print()
    con.print(
        Text("cctx autopsy <path>", style="bold") +
        Text("  to diagnose a session", style="dim")
    )
```

- [ ] **Step 4: Update `render_projects` in `cctx/renderers/terminal.py`**

Locate the existing `render_projects` function (around line 297) and replace it:

```python
def render_projects(
    projects: list[ProjectInfo],
    *,
    live_statuses: dict[str, str] | None = None,
    console: Console | None = None,
) -> None:
    con = console or _default_console()
    _live = live_statuses or {}
    live_project_ids: set[str] = {
        proj.project_dir.name
        for proj in projects
        for s in proj.sessions
        if s.session_id in _live
    }

    if not projects:
        con.print("No projects found in ~/.claude/projects/.")
        return

    con.print(Rule("cctx — projects"))
    table = Table(show_header=True, box=None, pad_edge=False, show_edge=False)
    table.add_column("Project", style="bold")
    table.add_column("Sessions", justify="right", style="dim")
    table.add_column("Last session", style="dim")
    table.add_column("Status")

    for proj in projects:
        last = proj.latest_time.strftime("%Y-%m-%d") if proj.latest_time else "—"
        if proj.project_dir.name in live_project_ids:
            status_cell = Text("● live", style="green bold")
        else:
            status_cell = Text("")
        table.add_row(
            proj.display_name,
            str(proj.session_count),
            last,
            status_cell,
        )
    con.print(table)
    con.print()
    con.print(
        Text("cctx ls <project-path>", style="bold") +
        Text("  to list sessions in a project", style="dim")
    )
    con.print(
        Text("cctx autopsy --latest <project-path>", style="bold") +
        Text("  to diagnose the most recent session", style="dim")
    )
```

- [ ] **Step 5: Verify the imports at the top of `renderers/terminal.py` include `Text`**

`Text` is already imported (it's used in the existing `render_projects`). Confirm with:

```bash
grep "from rich" cctx/renderers/terminal.py | head -10
```

If `Text` is not imported, add it to the existing `from rich.text import Text` line.

- [ ] **Step 6: Run all renderer tests to verify they pass**

```bash
uv run pytest tests/test_terminal_renderer.py -v
```

Expected: all tests pass, including the 3 new ones.

- [ ] **Step 7: Commit**

```bash
git add cctx/renderers/terminal.py tests/test_terminal_renderer.py
git commit -m "feat: render_sessions/render_projects — live status badges via live_statuses param"
```

---

## Task 4: Wire `cctx ls` in `cli.py`

**Files:**
- Modify: `cctx/cli.py`

No new tests needed — the existing CLI smoke tests in `tests/test_cli.py` already exercise `cctx ls`. The new code path (live_statuses) is covered by the renderer tests in Task 3 and falls back gracefully to `{}` if `claude` isn't on PATH.

- [ ] **Step 1: Add `live_sessions` import and update the `ls` command**

In `cctx/cli.py`, add the import near the top (after the existing `from cctx.discovery import ...` import):

```python
from cctx.agents import live_sessions as _live_sessions
```

Then update the `ls` command body. Find the current `ls` function (around line 190) and replace the body:

```python
@cli.command("ls")
@click.argument(
    "project",
    required=False,
    type=click.Path(exists=True, path_type=Path),
    shell_complete=lambda c, p, i: _complete_project(c, p, i),
)
def ls(project: Path | None) -> None:
    """List Claude Code projects and sessions.

    With no arguments, lists all projects in ~/.claude/projects/.

    With PROJECT (a local project directory), lists sessions for that project.
    """
    from cctx.discovery import ProjectInfo, find_project_dir, list_projects, list_sessions

    live_statuses = {s.session_id: s.status for s in _live_sessions()}

    if project is None:
        projects = list_projects()
        render_projects(projects, live_statuses=live_statuses)
    else:
        cwd = project if project.is_dir() else project.parent
        project_dir = find_project_dir(cwd)
        if project_dir is None:
            raise click.UsageError(
                f"No Claude Code sessions found for {cwd}.\n"
                "Check that ~/.claude/projects/ contains a matching directory."
            )
        sessions = list_sessions(project_dir)
        info = ProjectInfo(
            project_dir=project_dir,
            display_name=str(cwd).replace(str(Path.home()), "~"),
            sessions=sessions,
        )
        render_sessions(info, live_statuses=live_statuses)
```

- [ ] **Step 2: Run the full test suite**

```bash
uv run pytest -x -q
```

Expected: all tests pass. If `render_projects` or `render_sessions` calls in other tests fail because they don't pass `live_statuses`, confirm the parameter has a default of `None` (it does — `live_statuses: dict[str, str] | None = None`).

- [ ] **Step 3: Smoke-test `cctx ls` manually**

```bash
uv run cctx ls
```

Expected: project list appears. If you have an active Claude session open, it should show a green `● busy` badge next to that project.

```bash
uv run cctx ls .
```

Expected: session list for the current project. Any currently-running session shows `● busy` or `● idle`.

- [ ] **Step 4: Commit**

```bash
git add cctx/cli.py
git commit -m "feat: cctx ls — pass live_statuses to renderer for live session badges"
```

---

## Self-review

**Spec coverage:**
- ✅ `cctx/agents.py` with `LiveSession` and `live_sessions()` → Task 1
- ✅ All failure modes swallowed, return `[]` → Task 1
- ✅ `_find_active_session()` tries live first, falls back to mtime → Task 2
- ✅ `_tail()` short-circuits when session disappears from live list → Task 2
- ✅ `session_seen_live` guard: only short-circuit if we've seen claude was available → Task 2
- ✅ `render_sessions()` and `render_projects()` gain `live_statuses` param → Task 3
- ✅ `live_statuses={}` → no visual change (backward-compat) → Task 3
- ✅ `cli.py` `ls` command wires it all up → Task 4
- ✅ `discovery.py` untouched → spec

**Type consistency:**
- `live_statuses: dict[str, str] | None = None` used consistently in renderer signatures and cli.py calls ✅
- `live_sessions() -> list[LiveSession]` used in watcher and cli.py ✅
- `session_id` (snake_case) on `LiveSession` matches `sessionId` mapping in `agents.py` ✅
