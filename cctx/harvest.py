"""Harvest — apply Patch objects to CLAUDE.md on disk.

Public API:
    apply_patch(patch, target_dir) -> ApplyResult
    preview_patches(patches, target_dir) -> list[ApplyResult]
    apply_patches(patches, target_dir) -> list[ApplyResult]
    check_claude_md(target_dir) -> list[CheckFinding]

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


# ---------------------------------------------------------------------------
# harvest --check types
# ---------------------------------------------------------------------------


class CheckIssue(str, Enum):
    DEAD_FILE_REF = "dead_file_ref"   # backtick-quoted path that doesn't exist on disk
    DEAD_SKILL_REF = "dead_skill_ref" # .claude/skills/ reference that doesn't exist
    EMPTY_SECTION = "empty_section"   # ## heading with no content


@dataclass
class CheckFinding:
    heading: str          # ## section where this was found ("(preamble)" if before first heading)
    issue: CheckIssue
    detail: str           # human-readable description


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
    """Any .md file under target_dir is a valid target."""
    return patch.target_file.endswith(".md")


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
                message=f"target not supported (must be a .md file): {patch.target_file}",
            )

        # Create parent directories (e.g. .claude/rules/, .claude/skills/)
        target_path.parent.mkdir(parents=True, exist_ok=True)
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
                message=f"target not supported (must be a .md file): {patch.target_file}",
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


# ---------------------------------------------------------------------------
# harvest --check
# ---------------------------------------------------------------------------

# Matches backtick-quoted tokens that look like file paths with an extension.
# We anchor on a leading backtick-word-backtick pattern to avoid false
# positives on URLs, option names, etc.
_FILE_REF_RE = re.compile(r"`([^`\s]+\.[a-z]{1,6}[^`]*)`")

# Matches .claude/skills/ paths (with or without backticks)
_SKILL_REF_RE = re.compile(r"[`']?([./]*\.claude/skills/[^\s`'\"]+)[`']?")

_KNOWN_EXTENSIONS = {
    ".py", ".ts", ".js", ".tsx", ".jsx", ".toml", ".yaml", ".yml",
    ".json", ".md", ".sh", ".bash", ".fish", ".zsh",
}


def _parse_sections(content: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) pairs.

    The text before the first ## heading is yielded as ("(preamble)", text).
    """
    sections: list[tuple[str, str]] = []
    current_heading = "(preamble)"
    current_lines: list[str] = []

    for line in content.splitlines():
        if line.startswith("## "):
            sections.append((current_heading, "\n".join(current_lines)))
            current_heading = line.rstrip()
            current_lines = []
        else:
            current_lines.append(line)
    sections.append((current_heading, "\n".join(current_lines)))
    return sections


def check_claude_md(target_dir: Path) -> list[CheckFinding]:
    """Audit CLAUDE.md in target_dir for deterministically detectable issues.

    Checks:
      - Dead file references: backtick-quoted paths that don't exist on disk
      - Dead skill references: .claude/skills/ paths that don't exist
      - Empty sections: ## headings with no content

    Returns an empty list if CLAUDE.md doesn't exist (not an error).
    """
    claude_md = target_dir / "CLAUDE.md"
    if not claude_md.exists():
        return []

    content = claude_md.read_text(encoding="utf-8")
    sections = _parse_sections(content)
    findings: list[CheckFinding] = []

    for heading, body in sections:
        body_stripped = body.strip()

        # Empty section (skip preamble — it's often intentionally sparse)
        if heading != "(preamble)" and not body_stripped:
            findings.append(CheckFinding(
                heading=heading,
                issue=CheckIssue.EMPTY_SECTION,
                detail=f"{heading!r} has no content",
            ))
            continue

        # Dead skill references
        for match in _SKILL_REF_RE.finditer(body):
            skill_path_str = match.group(1).lstrip("./")
            # Try resolving from target_dir and from home
            candidates = [
                target_dir / skill_path_str,
                Path.home() / skill_path_str,
            ]
            if not any(c.exists() for c in candidates):
                findings.append(CheckFinding(
                    heading=heading,
                    issue=CheckIssue.DEAD_SKILL_REF,
                    detail=f"skill not found: {match.group(1)!r}",
                ))

        # Dead file references (backtick-quoted paths with known extensions)
        for match in _FILE_REF_RE.finditer(body):
            token = match.group(1)
            p = Path(token)
            if p.suffix not in _KNOWN_EXTENSIONS:
                continue
            # Skip if it looks like a URL or template variable
            if token.startswith("http") or "{" in token or "<" in token:
                continue
            candidate = target_dir / token
            if not candidate.exists() and not Path(token).exists():
                findings.append(CheckFinding(
                    heading=heading,
                    issue=CheckIssue.DEAD_FILE_REF,
                    detail=f"file not found: {token!r}",
                ))

    return findings
