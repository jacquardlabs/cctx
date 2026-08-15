"""Cross-agent emit — mirror cctx-managed CLAUDE.md sections to other agents.

Public API:
    EMIT_TARGETS: dict[str, str]                       # emit name -> destination file
    retarget_patches(patches, emit_target) -> list[Patch]
    sync_managed_sections(target_dir, emit_target) -> list[Patch]
    managed_heading_dates(target_dir) -> dict[str, datetime | None]

This module owns the "cctx-managed sections" concept: which CLAUDE.md headings
cctx writes, how to mirror them into another agent's config file, and when each
was introduced (git provenance, used by patch-efficacy). The CLI routes the
resulting patches through harvest.preview_patches / apply_patches, so
idempotency and dry-run come for free from the existing machinery.

Layering rules (MUST respect):
- Does NOT import click, rich_click, or anthropic.
- Does NOT import from diagnostician or recommender.
- May import harvest (the patch-application core) — never the reverse.
"""
from __future__ import annotations

import dataclasses
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from cctx.harvest import parse_sections
from cctx.models import MANAGED_HEADING_PREFIX, MANAGED_HEADINGS

if TYPE_CHECKING:
    from cctx.models import Patch

EMIT_TARGETS: dict[str, str] = {
    "agents": "AGENTS.md",
}


def retarget_patches(patches: list[Patch], emit_target: str) -> list[Patch]:
    """Clone CLAUDE.md-targeted patches to the emit target's file.

    Only patches whose target_file is exactly "CLAUDE.md" are emitted —
    .claude/rules/ and .claude/skills/ patches are Claude Code-specific and do
    not translate to other agents. Returns clones; inputs are unmodified.
    """
    dest = EMIT_TARGETS[emit_target]
    return [
        dataclasses.replace(p, target_file=dest)
        for p in patches
        if p.target_file == "CLAUDE.md"
    ]


# Reverse map: exact managed heading -> the FindingKind that owns it.
_HEADING_TO_KIND = {heading: kind for kind, heading in MANAGED_HEADINGS.items()}


def sync_managed_sections(target_dir: Path, emit_target: str) -> list[Patch]:
    """Build synthetic patches mirroring CLAUDE.md's cctx-managed sections.

    Reads CLAUDE.md in target_dir, keeps sections whose heading is an exact
    MANAGED_HEADINGS value or starts with MANAGED_HEADING_PREFIX, and returns
    one Patch per kept section targeting the emit file. Returns [] if CLAUDE.md
    is absent. The CLI routes these through preview_patches / apply_patches, so
    idempotency and dry-run come for free from the existing machinery.
    """
    from cctx.models import FindingKind, Patch  # runtime use (Patch is TYPE_CHECKING-only above)

    claude_md = target_dir / "CLAUDE.md"
    if not claude_md.exists():
        return []

    dest = EMIT_TARGETS[emit_target]
    content = claude_md.read_text(encoding="utf-8")
    patches: list[Patch] = []

    for heading, body in parse_sections(content):
        is_fixed = heading in _HEADING_TO_KIND
        is_prefixed = heading.startswith(MANAGED_HEADING_PREFIX)
        if not (is_fixed or is_prefixed):
            continue

        kind = _HEADING_TO_KIND[heading] if is_fixed else FindingKind.PROJECT_PATTERN
        diff_lines = [heading] + body.splitlines()
        unified_diff = "\n".join(f"+{line}" for line in diff_lines)
        patches.append(Patch(
            target_file=dest,
            description=heading,
            unified_diff=unified_diff,
            finding_kind=kind,
            evidence_summary="synced from CLAUDE.md",
        ))

    return patches


def managed_heading_dates(target_dir: Path) -> dict[str, datetime | None]:
    """Return the git introduction date for each MANAGED_HEADINGS heading.

    For each heading, runs:
        git log --reverse --format="%aI" -S"<heading>" -- CLAUDE.md

    --reverse gives oldest-first; the first line is the introduction commit.
    -S (pickaxe) fires when the occurrence count of the literal string changes.
    Returns None for any heading not found in git history, or if git fails.
    Never raises.
    """
    result: dict[str, datetime | None] = {}
    for heading in MANAGED_HEADINGS.values():
        try:
            proc = subprocess.run(
                ["git", "log", "--reverse", "--format=%aI", f"-S{heading}", "--", "CLAUDE.md"],
                cwd=target_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = proc.stdout.strip().splitlines()
            if lines:
                date_str = lines[0].replace("Z", "+00:00")
                result[heading] = datetime.fromisoformat(date_str)
            else:
                result[heading] = None
        except Exception:  # noqa: BLE001
            result[heading] = None
    return result
