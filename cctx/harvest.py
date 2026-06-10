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

import dataclasses
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from cctx.models import MANAGED_HEADING_PREFIX, MANAGED_HEADINGS

if TYPE_CHECKING:
    from cctx.models import Patch


# ---------------------------------------------------------------------------
# harvest --check types
# ---------------------------------------------------------------------------


class CheckSeverity(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class CheckIssue(str, Enum):
    DEAD_FILE_REF    = "dead_file_ref"
    DEAD_SKILL_REF   = "dead_skill_ref"
    EMPTY_SECTION    = "empty_section"
    CONTRADICTION    = "contradiction"
    REDUNDANCY       = "redundancy"
    STALE_IDENTIFIER = "stale_identifier"


@dataclass
class CheckFinding:
    heading:  str
    issue:    CheckIssue
    severity: CheckSeverity
    detail:   str


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

# Maps an --emit target name to the destination filename. Single place to add
# future targets (Cursor, Windsurf, Copilot) when demand exists.
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
    from cctx.models import FindingKind, Patch  # runtime use; Patch is TYPE_CHECKING-only at module scope

    claude_md = target_dir / "CLAUDE.md"
    if not claude_md.exists():
        return []

    dest = EMIT_TARGETS[emit_target]
    content = claude_md.read_text(encoding="utf-8")
    patches: list[Patch] = []

    for heading, body in _parse_sections(content):
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
    # Track (target_path, fingerprint) pairs already "seen" within this preview
    # run (idempotency). Keyed by file so the same heading in two different
    # target files is correctly treated as two independent patches.
    seen_fingerprints: set[tuple[Path, str]] = set()

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

        already_seen = fp is not None and (target_path, fp) in seen_fingerprints
        if fp is not None and (_already_present(content, fp) or already_seen):
            results.append(ApplyResult(
                patch=patch,
                status=ApplyStatus.SKIPPED,
                target_path=target_path,
                message=f"already present: {fp}",
            ))
        else:
            if fp is not None:
                seen_fingerprints.add((target_path, fp))
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

_STOPWORDS = {
    "a", "an", "the", "to", "be", "is", "are", "was", "were",
    "in", "on", "at", "of", "for", "with", "and", "or", "not",
    "it", "this", "that", "you", "your", "use", "do",
}

_ALWAYS_NEVER_RE = re.compile(
    r"\b(always|never)\b(.+?)(?:[.!?\n]|$)", re.IGNORECASE
)

_STALENESS_EXCLUDED = {".git", ".venv", "node_modules", "__pycache__"}

_FUNC_REF_RE = re.compile(r"`([^`/.\s]{8,})\(\)`")


def _words(text: str) -> set[str]:
    tokens = re.findall(r"\b[a-zA-Z_]\w*\b", text.lower())
    return {t for t in tokens if t not in _STOPWORDS}


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


def check_contradictions(
    sections: list[tuple[str, str]],
) -> list[CheckFinding]:
    """Detect contradictions across sections using always/never polarity heuristic.

    Looks for "always" and "never" clauses in section bodies, extracts the
    subject words, and flags cases where the same word has conflicting polarities.

    Returns findings for each contradiction found (severity: HIGH).
    """
    subject_map: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for heading, body in sections:
        for match in _ALWAYS_NEVER_RE.finditer(body):
            polarity = match.group(1).lower()
            clause = match.group(2)
            for word in _words(clause):
                subject_map[word].append((polarity, heading))

    findings: list[CheckFinding] = []
    seen: set[tuple[str, str]] = set()
    for word, occurrences in subject_map.items():
        always_headings = [h for p, h in occurrences if p == "always"]
        never_headings = [h for p, h in occurrences if p == "never"]
        if always_headings and never_headings:
            key = (always_headings[0], never_headings[0])
            if key not in seen:
                seen.add(key)
                findings.append(CheckFinding(
                    heading=always_headings[0],
                    issue=CheckIssue.CONTRADICTION,
                    severity=CheckSeverity.HIGH,
                    detail=(
                        f"'{word}' is 'always' in {always_headings[0]!r}"
                        f" but 'never' in {never_headings[0]!r}"
                    ),
                ))
    return findings


def check_redundancy(
    sections: list[tuple[str, str]],
) -> list[CheckFinding]:
    """Detect redundancy across sections using Jaccard similarity.

    Builds a word set (stopwords removed) for each section. Sections with
    fewer than 5 words are ineligible. For all pairs of eligible sections,
    computes Jaccard similarity of their word sets. Flags pairs with
    similarity >= 0.8.

    Returns findings for each redundancy found (severity: MEDIUM).
    """
    eligible = []
    for heading, body in sections:
        ws = _words(body)
        if len(ws) >= 5:
            eligible.append((heading, body, ws))

    findings: list[CheckFinding] = []
    for i in range(len(eligible)):
        for j in range(i + 1, len(eligible)):
            h1, _, w1 = eligible[i]
            h2, _, w2 = eligible[j]
            union = w1 | w2
            jaccard = len(w1 & w2) / len(union)
            if jaccard >= 0.8:
                findings.append(CheckFinding(
                    heading=h1,
                    issue=CheckIssue.REDUNDANCY,
                    severity=CheckSeverity.MEDIUM,
                    detail=f"{h1!r} and {h2!r} are {jaccard:.0%} similar",
                ))
    return findings


def check_staleness(
    sections: list[tuple[str, str]],
    project_dir: Path,
) -> list[CheckFinding]:
    """Detect stale function references in CLAUDE.md.

    Scans all .py, .ts, and .js source files in the project directory and
    searches for backtick-quoted function references (e.g., `my_function()`)
    that are 8+ characters long. Flags references not found in the source.

    Returns findings for each stale identifier found (severity: LOW).
    """
    source_files = [
        f
        for f in (
            list(project_dir.rglob("*.py"))
            + list(project_dir.rglob("*.ts"))
            + list(project_dir.rglob("*.js"))
        )
        if not any(part in _STALENESS_EXCLUDED for part in f.parts)
    ]
    if not source_files:
        return []

    findings: list[CheckFinding] = []
    for heading, body in sections:
        for match in _FUNC_REF_RE.finditer(body):
            name = match.group(1)
            found = any(
                name in f.read_text(encoding="utf-8", errors="ignore")
                for f in source_files
            )
            if not found:
                findings.append(CheckFinding(
                    heading=heading,
                    issue=CheckIssue.STALE_IDENTIFIER,
                    severity=CheckSeverity.LOW,
                    detail=f"'{name}()' not found in project source files",
                ))
    return findings


def _check_structure(
    sections: list[tuple[str, str]],
    target_dir: Path,
) -> list[CheckFinding]:
    """Check structure issues: empty sections, dead file/skill references.

    Returns findings for:
      - Empty sections: ## headings with no content (MEDIUM)
      - Dead file references: backtick-quoted paths that don't exist (MEDIUM)
      - Dead skill references: .claude/skills/ paths that don't exist (MEDIUM)
    """
    findings: list[CheckFinding] = []

    for heading, body in sections:
        body_stripped = body.strip()

        # Empty section (skip preamble — it's often intentionally sparse)
        if heading != "(preamble)" and not body_stripped:
            findings.append(CheckFinding(
                heading=heading,
                issue=CheckIssue.EMPTY_SECTION,
                severity=CheckSeverity.MEDIUM,
                detail=f"{heading!r} has no content",
            ))
            continue

        # Dead skill references
        for match in _SKILL_REF_RE.finditer(body):
            skill_path_str = match.group(1).removeprefix("./")
            # Try resolving from target_dir and from home
            candidates = [
                target_dir / skill_path_str,
                Path.home() / skill_path_str,
            ]
            if not any(c.exists() for c in candidates):
                findings.append(CheckFinding(
                    heading=heading,
                    issue=CheckIssue.DEAD_SKILL_REF,
                    severity=CheckSeverity.MEDIUM,
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
                    severity=CheckSeverity.MEDIUM,
                    detail=f"file not found: {token!r}",
                ))

    return findings


def check_claude_md(target_dir: Path) -> list[CheckFinding]:
    """Audit CLAUDE.md in target_dir for deterministically detectable issues.

    Checks:
      - Dead file/skill references and empty sections (MEDIUM)
      - Contradictory always/never rules (HIGH)
      - Redundant sections with Jaccard >= 0.8 (MEDIUM)
      - Stale backtick-quoted function identifiers >= 8 chars (LOW)

    Returns an empty list if CLAUDE.md doesn't exist (not an error).
    """
    claude_md = target_dir / "CLAUDE.md"
    if not claude_md.exists():
        return []

    content = claude_md.read_text(encoding="utf-8")
    sections = _parse_sections(content)
    return (
        _check_structure(sections, target_dir)
        + check_contradictions(sections)
        + check_redundancy(sections)
        + check_staleness(sections, target_dir)
    )
