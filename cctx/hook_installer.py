"""Settings-merge hook installer — install/remove the cctx SessionEnd hook.

Reads, merges, and writes ~/.claude/settings.json or .claude/settings.json
without touching any other keys. Idempotent: fingerprinted by the hook's
description field so a double-install is a no-op.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HOOK_DESCRIPTION = "cctx SessionEnd hook (diagnostics on session exit)"
HOOK_COMMAND = "cctx autopsy --latest --quiet"


def settings_path(global_: bool) -> Path:
    if global_:
        return Path.home() / ".claude" / "settings.json"
    return Path(".claude") / "settings.json"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def _save(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _find_hook(session_end: list[dict[str, Any]]) -> int | None:
    """Return the index of the cctx hook group in the SessionEnd array, or None."""
    for i, group in enumerate(session_end):
        for h in group.get("hooks", []):
            desc = h.get("description", "")
            if isinstance(desc, str) and "cctx SessionEnd" in desc:
                return i
    return None


def _hook_entry() -> dict[str, Any]:
    return {
        "hooks": [
            {
                "type": "command",
                "command": HOOK_COMMAND,
                "async": True,
                "description": HOOK_DESCRIPTION,
            }
        ]
    }


def is_installed(global_: bool = False) -> bool:
    path = settings_path(global_)
    settings = _load(path)
    session_end = settings.get("hooks", {}).get("SessionEnd", [])
    return _find_hook(session_end) is not None


def install(global_: bool = False, force: bool = False) -> str:
    """Install the hook. Returns "already_installed" or the path written."""
    path = settings_path(global_)
    settings = _load(path)
    hooks = settings.setdefault("hooks", {})
    session_end = hooks.setdefault("SessionEnd", [])
    idx = _find_hook(session_end)
    if idx is not None and not force:
        return "already_installed"
    if idx is not None:
        session_end[idx] = _hook_entry()
    else:
        session_end.append(_hook_entry())
    _save(path, settings)
    return str(path)


def remove(global_: bool = False) -> str | None:
    """Remove the hook. Returns the path written, or None if not found."""
    path = settings_path(global_)
    settings = _load(path)
    hooks = settings.get("hooks", {})
    session_end = hooks.get("SessionEnd", [])
    idx = _find_hook(session_end)
    if idx is None:
        return None
    session_end.pop(idx)
    if not session_end:
        del hooks["SessionEnd"]
    if not hooks:
        del settings["hooks"]
    _save(path, settings)
    return str(path)
