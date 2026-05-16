"""Session and project discovery for ~/.claude/projects/.

Public API:
    claude_projects_dir() -> Path
    find_project_dir(cwd) -> Path | None
    list_projects(base) -> list[ProjectInfo]
    list_sessions(project_dir) -> list[SessionMeta]
    latest_session(project_dir) -> Path | None
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SessionMeta:
    path: Path
    session_id: str
    start_time: datetime | None
    cwd: str | None
    git_branch: str | None


@dataclass
class ProjectInfo:
    project_dir: Path          # ~/.claude/projects/-Users-...
    display_name: str          # ~/Projects/cctx  (from cwd in first session)
    sessions: list[SessionMeta] = field(default_factory=list)

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    @property
    def latest_time(self) -> datetime | None:
        times = [s.start_time for s in self.sessions if s.start_time]
        return max(times) if times else None


def claude_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _encode_path(path: Path) -> str:
    return path.resolve().as_posix().replace("/", "-")


def find_project_dir(cwd: Path, *, base: Path | None = None) -> Path | None:
    """Return the ~/.claude/projects/<encoded> dir that corresponds to cwd."""
    base = base or claude_projects_dir()
    encoded = _encode_path(cwd)
    candidate = base / encoded
    return candidate if candidate.is_dir() else None


def _read_session_meta(path: Path) -> SessionMeta:
    """Quick scan: read enough lines to get session metadata without full parse."""
    session_id = path.stem
    start_time: datetime | None = None
    cwd: str | None = None
    git_branch: str | None = None

    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for _ in range(50):  # cap at 50 lines — metadata is always early
                line = fh.readline()
                if not line:
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "sessionId" in obj:
                    session_id = obj["sessionId"]
                if "timestamp" in obj and start_time is None:
                    try:
                        raw = obj["timestamp"].replace("Z", "+00:00")
                        start_time = datetime.fromisoformat(raw)
                    except (ValueError, AttributeError):
                        pass
                if "cwd" in obj and cwd is None:
                    cwd = obj["cwd"]
                if "gitBranch" in obj and git_branch is None:
                    git_branch = obj["gitBranch"]
                if start_time and cwd:
                    break
    except OSError:
        pass

    return SessionMeta(
        path=path,
        session_id=session_id,
        start_time=start_time,
        cwd=cwd,
        git_branch=git_branch,
    )


def list_sessions(project_dir: Path) -> list[SessionMeta]:
    """List sessions in a project directory, newest first."""
    sessions = [
        _read_session_meta(p)
        for p in project_dir.glob("*.jsonl")
    ]
    _epoch = datetime.min.replace(tzinfo=timezone.utc)
    sessions.sort(key=lambda s: s.start_time or _epoch, reverse=True)
    return sessions


def _project_display_name(project_dir: Path) -> str:
    """Derive a human-readable name from cwd in session files, or decode best-effort."""
    for path in sorted(project_dir.glob("*.jsonl"))[:3]:
        meta = _read_session_meta(path)
        if meta.cwd:
            home = str(Path.home())
            if meta.cwd.startswith(home):
                return "~" + meta.cwd[len(home):]
            return meta.cwd

    # Fallback: decode -Users-bryan-Projects-cctx → ~/Projects/cctx
    encoded = project_dir.name
    home_prefix = _encode_path(Path.home())  # -Users-bryan
    if encoded.startswith(home_prefix):
        tail = encoded[len(home_prefix):]  # -Projects-cctx
        return "~" + tail.replace("-", "/")
    return encoded


def list_projects(base: Path | None = None) -> list[ProjectInfo]:
    """List all projects in the claude projects directory, newest-activity first."""
    base = base or claude_projects_dir()
    if not base.is_dir():
        return []

    projects: list[ProjectInfo] = []
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        if not any(entry.glob("*.jsonl")):
            continue
        sessions = list_sessions(entry)
        projects.append(ProjectInfo(
            project_dir=entry,
            display_name=_project_display_name(entry),
            sessions=sessions,
        ))

    projects.sort(
        key=lambda p: p.latest_time or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return projects


def latest_session(project_dir: Path) -> Path | None:
    """Return the path of the most recent session JSONL in a project dir."""
    sessions = list_sessions(project_dir)
    return sessions[0].path if sessions else None
