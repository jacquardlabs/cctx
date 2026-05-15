"""Harvest — apply Patch objects to CLAUDE.md on disk.

Public API:
    apply_patch(patch, target_dir) -> ApplyResult
    preview_patches(patches, target_dir) -> list[ApplyResult]
    apply_patches(patches, target_dir) -> list[ApplyResult]

Layering rules (MUST respect):
- Does NOT import click, rich_click, or anthropic.
- Does NOT import from diagnostician or recommender.
- Receives list[Patch] from the caller (cli.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cctx.models import Patch


class ApplyStatus(str, Enum):
    APPLIED = "applied"
    SKIPPED = "skipped"
    ERROR   = "error"


@dataclass
class ApplyResult:
    patch:       Patch
    status:      ApplyStatus
    target_path: Path
    message:     str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_body(unified_diff: str) -> str:
    """Strip leading '+' from each line. A lone '+' becomes a blank line."""
    lines = []
    for line in unified_diff.splitlines():
        if line.startswith("+"):
            lines.append(line[1:])
        else:
            lines.append(line)
    return "\n".join(lines)


def _fingerprint(body: str) -> str | None:
    """Return the first '## ...' heading in body, or None."""
    for line in body.splitlines():
        if line.startswith("## "):
            return line.rstrip()
    return None


def _already_present(content: str, fingerprint: str) -> bool:
    """Case-sensitive line-anchored match for the heading."""
    pattern = re.compile(rf"^{re.escape(fingerprint)}\s*$", re.MULTILINE)
    return bool(pattern.search(content))


def _is_supported_target(patch: Patch) -> bool:
    return patch.target_file == "CLAUDE.md"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_patch(patch: Patch, target_dir: Path) -> ApplyResult:
    """Apply one patch. Never raises — errors go into ApplyResult(status=ERROR)."""
    target_path = target_dir / patch.target_file
    try:
        body = _extract_body(patch.unified_diff)
        fp = _fingerprint(body)

        if not _is_supported_target(patch):
            return ApplyResult(
                patch=patch,
                status=ApplyStatus.SKIPPED,
                target_path=target_path,
                message=f"target not supported in v0: {patch.target_file}",
            )

        if not target_path.exists():
            target_path.touch()

        content = target_path.read_text(encoding="utf-8")

        if fp is not None and _already_present(content, fp):
            return ApplyResult(
                patch=patch,
                status=ApplyStatus.SKIPPED,
                target_path=target_path,
                message=f"already present: {fp}",
            )

        with target_path.open("a", encoding="utf-8") as fh:
            if content and not content.endswith("\n\n"):
                fh.write("\n" if content.endswith("\n") else "\n\n")
            fh.write(body)
            fh.write("\n")

        return ApplyResult(
            patch=patch,
            status=ApplyStatus.APPLIED,
            target_path=target_path,
            message=f"appended: {fp or patch.description}",
        )

    except Exception as exc:  # noqa: BLE001
        return ApplyResult(
            patch=patch,
            status=ApplyStatus.ERROR,
            target_path=target_path,
            message=str(exc),
        )


def preview_patches(patches: list[Patch], target_dir: Path) -> list[ApplyResult]:
    """Compute what would happen without writing. Returns APPLIED or SKIPPED."""
    results = []
    # Track fingerprints already "seen" within this preview run (idempotency)
    seen_fingerprints: set[str] = set()

    for patch in patches:
        target_path = target_dir / patch.target_file

        if not _is_supported_target(patch):
            results.append(ApplyResult(
                patch=patch,
                status=ApplyStatus.SKIPPED,
                target_path=target_path,
                message=f"target not supported in v0: {patch.target_file}",
            ))
            continue

        body = _extract_body(patch.unified_diff)
        fp = _fingerprint(body)

        content = target_path.read_text(encoding="utf-8") if target_path.exists() else ""

        if fp is not None and (_already_present(content, fp) or fp in seen_fingerprints):
            results.append(ApplyResult(
                patch=patch,
                status=ApplyStatus.SKIPPED,
                target_path=target_path,
                message=f"already present: {fp}",
            ))
        else:
            if fp is not None:
                seen_fingerprints.add(fp)
            results.append(ApplyResult(
                patch=patch,
                status=ApplyStatus.APPLIED,
                target_path=target_path,
                message=f"would append: {fp or patch.description}",
            ))

    return results


def apply_patches(patches: list[Patch], target_dir: Path) -> list[ApplyResult]:
    """Apply all applicable patches in sequence."""
    return [apply_patch(patch, target_dir) for patch in patches]
