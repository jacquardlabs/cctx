"""Patch generator — turns Findings into copy-pasteable CLAUDE.md diffs.

generate(diagnosis) -> Diagnosis   (single-session path)
generate_from_evidence(evidence) -> list[Patch]   (cross-session path, generic findings)
generate_from_patterns(patterns) -> list[Patch]   (cross-session path, project patterns)
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from cctx.models import FindingKind, Patch

if TYPE_CHECKING:
    from cctx.models import Diagnosis, Finding, KindEvidence, ProjectPattern

# ---------------------------------------------------------------------------
# Patch templates (append-style unified diffs, v0)
# ---------------------------------------------------------------------------

_RETRY_LOOP_DIFF = """\
+## Retry discipline
+
+If the same command or file operation fails twice with the same error, stop and
+diagnose before retrying. Read the relevant file, check the full error message,
+confirm paths exist. Try a meaningfully different approach — never repeat the
+exact failing call a third time."""

_SCOPE_CREEP_DIFF = """\
+## Scope discipline
+
+Finish the stated task before picking up anything else. If you notice an adjacent
+issue while working, note it as a TODO comment but do not fix it unless explicitly
+asked. One task at a time."""

_STALE_CONTEXT_DIFF = """\
+## Context hygiene
+
+Large tool outputs (grep results, file reads over ~2K tokens) go stale quickly.
+After a result has served its purpose, do not carry it through 5+ additional turns
+without re-referencing it. Prefer re-running the tool over dragging stale context
+forward — the compaction system handles removal."""

_TOOL_THRASH_DIFF = """\
+## Tool-call discipline
+
+Before reaching for a tool, decide what specific information the call must return
+and how it changes the next step. Don't fan out near-identical searches or re-read
+the same file from different angles hoping something turns up. If two or three calls
+haven't moved you forward, stop and form a hypothesis before the next one."""

_DEAD_END_DIFF = """\
+## Exploration discipline
+
+When an approach stops making progress, name the dead end explicitly and back out
+rather than pushing deeper on a path that isn't working. Re-read the goal, list the
+approaches already ruled out, and pick a meaningfully different one. Sunk effort on a
+failing approach is not a reason to continue it."""

_FANOUT_WASTE_DIFF = """\
+## Fan-out discipline
+
+Before spawning multiple subagents in parallel, state what each one will return
+and verify the tasks don't overlap. After each subagent completes, confirm its
+result is actually consumed by the parent before spawning retries. Retry only
+after changing something meaningful about the task — identical re-spawns waste
+the full subagent cost with no new information."""

_CACHE_HYGIENE_DIFF = """\
+## Cache hygiene
+
+Keep the prompt prefix stable across turns so Claude's KV-cache can be reused.
+Avoid changing tool definitions mid-session, keep system prompt content
+consistent, and prefer append-only context updates over rewrites. If context
+compaction fires frequently, consider splitting long sessions into shorter ones
+with a stable, cacheable preamble. A 10× cost difference separates a warm
+cache hit from a cold input read."""

_COMPACTION_DIFF = """\
+## Compaction hygiene
+
+If context-window compaction occurs mid-session, assume all previously read files
+are gone from context. Re-read only files you actively need for the next step —
+don't reflexively reload everything. Better: compact earlier by summarizing large
+tool outputs once you've extracted what you need, so compaction doesn't erase
+work-in-progress state."""

_EXPLORATION_THRASH_DIFF = """\
+## Exploration thrash
+
+Before opening another file or running another search, state the specific
+question this call must answer and how the answer changes the next step. If
+you have read 6+ files without writing anything, stop and synthesise what
+you know. Never call the same read or grep more than twice with identical
+arguments — if the first two didn't help, a third won't either."""

_UNUSED_CONTEXT_DIFF = """\
+## Context overhead
+
+Review your MCP server list in `.claude/settings.json`. Servers loaded in
+every session but never called add token overhead to each request. Disable
+servers you don't actively use in this project."""

_TEMPLATES: dict[FindingKind, tuple[str, str, str]] = {
    # kind → (description, diff_body, target_file)
    FindingKind.RETRY_LOOP: ("Add retry discipline rule", _RETRY_LOOP_DIFF, "CLAUDE.md"),
    FindingKind.SCOPE_CREEP: ("Add scope discipline rule", _SCOPE_CREEP_DIFF, "CLAUDE.md"),
    FindingKind.STALE_CONTEXT: ("Add context hygiene rule", _STALE_CONTEXT_DIFF, "CLAUDE.md"),
    FindingKind.TOOL_THRASH: ("Add tool-call discipline rule", _TOOL_THRASH_DIFF, "CLAUDE.md"),
    FindingKind.DEAD_END: ("Add exploration discipline rule", _DEAD_END_DIFF, "CLAUDE.md"),
    FindingKind.FANOUT_WASTE: ("Add fan-out discipline rule", _FANOUT_WASTE_DIFF, "CLAUDE.md"),
    FindingKind.CACHE_HYGIENE: ("Add cache hygiene rule", _CACHE_HYGIENE_DIFF, "CLAUDE.md"),
    FindingKind.COMPACTION: ("Add compaction hygiene rule", _COMPACTION_DIFF, "CLAUDE.md"),
    FindingKind.EXPLORATION_THRASH: (
        "Add exploration thrash rule", _EXPLORATION_THRASH_DIFF, "CLAUDE.md"
    ),
    FindingKind.UNUSED_CONTEXT: (
        "Add context overhead note", _UNUSED_CONTEXT_DIFF, "CLAUDE.md"
    ),
}


def summarize(finding: Finding) -> str:
    ev = finding.evidence
    match finding.kind:
        case FindingKind.RETRY_LOOP:
            occs = ev.get("occurrences", [])
            if occs:
                first = occs[0]
                loop_len = ev.get("loop_length", "?")
                return (
                    f"{first['call']}({first['key'][:40]}) failed {loop_len}×"
                    f" between turns {first['turn']}–{occs[-1]['turn']}"
                )
            return finding.summary
        case FindingKind.SCOPE_CREEP:
            phrases = ev.get("phrases", [])
            if phrases:
                return f"'{phrases[0]['phrase']}' at turn {phrases[0]['turn']}"
            return finding.summary
        case FindingKind.STALE_CONTEXT:
            items = ev.get("stale_items", [])
            if items:
                worst = max(items, key=lambda i: i["token_turns"])
                tokens_k = worst["content_tokens"] // 1000
                cost_str = f", ~${finding.cost_usd:.2f}" if finding.cost_usd else ""
                return (
                    f"{tokens_k}K-token {worst['tool_name']} result stale "
                    f"{worst['turns_stale']} turns "
                    f"(~{ev.get('total_token_turns', 0):,} token-turns{cost_str})"
                )
            return finding.summary
        case _:
            return finding.summary


def _make_patch(finding: Finding) -> Patch:
    description, diff_body, target_file = _TEMPLATES[finding.kind]
    return Patch(
        target_file=target_file,
        description=description,
        unified_diff=diff_body,
        finding_kind=finding.kind,
        evidence_summary=summarize(finding),
    )


def generate(diagnosis: Diagnosis) -> Diagnosis:
    """Populate patches on a Diagnosis. Returns a new Diagnosis; original unchanged."""
    patches = [_make_patch(f) for f in diagnosis.findings]
    return dataclasses.replace(diagnosis, patches=patches)


def generate_from_evidence(
    evidence: dict[FindingKind, KindEvidence],
) -> list[Patch]:
    """Cross-session patch generation.

    Like generate(), but appends an Evidence line when session_count >= 2:
        Evidence: appeared in N of M sessions in the past window (~$X.XX wasted).
    """
    patches = []
    for kind, ev in evidence.items():
        if kind not in _TEMPLATES:
            continue
        description, diff_body, target_file = _TEMPLATES[kind]

        if ev.session_count >= 2:
            evidence_line = (
                f"\n+\n+Evidence: appeared in {ev.session_count} sessions "
                f"(~${ev.total_waste_usd:.2f} wasted)."
            )
            diff_body = diff_body + evidence_line

        example = ev.example_summaries[0] if ev.example_summaries else ""
        patches.append(Patch(
            target_file=target_file,
            description=description,
            unified_diff=diff_body,
            finding_kind=kind,
            evidence_summary=example,
        ))
    return patches


def generate_from_patterns(patterns: list[ProjectPattern]) -> list[Patch]:
    """Generate CLAUDE.md patches from cross-session ProjectPatterns."""
    patches = []
    for p in patterns:
        diff = (
            f"+## Project-specific: {p.tool_name}({p.failure_key})\n"
            f"+When `{p.failure_key}` fails, use `{p.fix_key}` instead.\n"
            f"+Re-discovered in {p.session_count} sessions "
            f"(~${p.total_waste_usd:.2f} wasted)."
        )
        patches.append(Patch(
            target_file="CLAUDE.md",
            description=f"Project-specific: {p.failure_key} → {p.fix_key}",
            unified_diff=diff,
            finding_kind=FindingKind.PROJECT_PATTERN,
            evidence_summary=(
                f"Seen in {p.session_count} sessions, ~${p.total_waste_usd:.2f} wasted"
            ),
        ))
    return patches
