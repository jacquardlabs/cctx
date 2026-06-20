"""Fan-out waste classifier.

classify(trace) -> list[Finding]

Signal A — OVERLAP: Two Agent calls with Jaccard >= 0.65 on word 3-grams,
    both prompts >= 50 words.
Signal B — RETRY: Agent ToolResult is_error=True followed by the next Agent
    call with Jaccard >= 0.50 on word 3-grams, both prompts >= 30 words.

Signal C (unused-result) is deferred — the 6-gram approach fires false
positives on paraphrased references and is not ship-ready.

cost_usd is set to None here; _patch_fanout_costs() in diagnostician/__init__.py
fills it in from SubagentAttribution data after run() collects attributions.

Evidence (Finding.evidence, kind=FANOUT_WASTE):
    signal
    overlap_pair
    jaccard
    prompt_a
    prompt_b
    subagent_session_ids
    retry_prompt
    failed_prompt
    failed_session_id
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from cctx.models import Confidence, Finding, FindingKind, Severity

if TYPE_CHECKING:
    from cctx.models import SessionTrace, ToolUse

# ---------------------------------------------------------------------------
# Thresholds — documented here, not tuned at runtime
# ---------------------------------------------------------------------------

OVERLAP_JACCARD: float = 0.65   # minimum Jaccard on word 3-grams for overlap
OVERLAP_MIN_WORDS: int = 50     # both prompts must be this long

RETRY_JACCARD: float = 0.50     # minimum Jaccard for failed-retry detection
RETRY_MIN_WORDS: int = 30       # both prompts must be this long


# ---------------------------------------------------------------------------
# N-gram helpers
# ---------------------------------------------------------------------------

def _word_ngrams(text: str, n: int) -> set[tuple[str, ...]]:
    words = text.lower().split()
    if len(words) < n:
        return set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _get_prompt(tu: ToolUse) -> str:
    return tu.tool_input.get("prompt") or tu.tool_input.get("description") or ""


# ---------------------------------------------------------------------------
# Signal A — Overlapping subagent prompts
# ---------------------------------------------------------------------------

def _signal_overlap(agent_calls: list[tuple[int, ToolUse]]) -> list[Finding]:
    findings: list[Finding] = []
    for i in range(len(agent_calls)):
        turn_i, tu_i = agent_calls[i]
        p_i = _get_prompt(tu_i)
        words_i = p_i.split()
        if len(words_i) < OVERLAP_MIN_WORDS:
            continue
        ng_i = _word_ngrams(p_i, 3)
        for j in range(i + 1, len(agent_calls)):
            turn_j, tu_j = agent_calls[j]
            p_j = _get_prompt(tu_j)
            words_j = p_j.split()
            if len(words_j) < OVERLAP_MIN_WORDS:
                continue
            ng_j = _word_ngrams(p_j, 3)
            score = _jaccard(ng_i, ng_j)
            if score < OVERLAP_JACCARD:
                continue
            findings.append(Finding(
                kind=FindingKind.FANOUT_WASTE,
                severity=Severity.MEDIUM,
                confidence=Confidence.MEDIUM,
                first_turn=min(turn_i, turn_j),
                last_turn=max(turn_i, turn_j),
                evidence={
                    "signal": "overlap",
                    "overlap_pair": [tu_i.subagent_session_id, tu_j.subagent_session_id],
                    "jaccard": round(score, 3),
                    "prompt_a": p_i[:80],
                    "prompt_b": p_j[:80],
                    "subagent_session_ids": [],  # filled by _patch_fanout_costs
                },
                cost_usd=None,
                summary=f"Overlapping subagent prompts (Jaccard {score:.2f})",
            ))
    return findings


# ---------------------------------------------------------------------------
# Signal B — Failed subagent re-spawned with similar prompt
# ---------------------------------------------------------------------------

def _signal_retry(
    agent_calls: list[tuple[int, ToolUse]],
    result_map: dict[str, tuple[bool, str]],  # tool_use_id -> (is_error, content)
) -> list[Finding]:
    findings: list[Finding] = []
    for k, (turn_k, tu_k) in enumerate(agent_calls):
        is_error, _content = result_map.get(tu_k.tool_use_id, (False, ""))
        if not is_error:
            continue
        # Only check the immediate next Agent call (by list order = turn order)
        if k + 1 >= len(agent_calls):
            continue
        turn_next, tu_next = agent_calls[k + 1]
        p_failed = _get_prompt(tu_k)
        p_retry = _get_prompt(tu_next)
        if len(p_failed.split()) < RETRY_MIN_WORDS or len(p_retry.split()) < RETRY_MIN_WORDS:
            continue
        score = _jaccard(_word_ngrams(p_failed, 3), _word_ngrams(p_retry, 3))
        if score < RETRY_JACCARD:
            continue
        findings.append(Finding(
            kind=FindingKind.FANOUT_WASTE,
            severity=Severity.HIGH,
            confidence=Confidence.HIGH,
            first_turn=turn_k,
            last_turn=turn_next,
            evidence={
                "signal": "retry",
                "failed_session_id": tu_k.subagent_session_id,
                "jaccard": round(score, 3),
                "failed_prompt": p_failed[:80],
                "retry_prompt": p_retry[:80],
                "subagent_session_ids": [],  # filled by _patch_fanout_costs
            },
            cost_usd=None,
            summary=f"Failed subagent re-spawned with similar prompt (Jaccard {score:.2f})",
        ))
    return findings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def classify(trace: SessionTrace) -> list[Finding]:
    # Collect Agent ToolUse in turn order
    agent_calls: list[tuple[int, ToolUse]] = []
    result_map: dict[str, tuple[bool, str]] = {}

    for turn in trace.turns:
        for tu in turn.tool_uses:
            if tu.tool_name == "Agent":
                agent_calls.append((turn.turn_number, tu))
        for tr in turn.tool_results:
            if tr.tool_name == "Agent":
                result_map[tr.tool_use_id] = (tr.is_error, tr.content)

    if len(agent_calls) < 2:
        return []

    findings: list[Finding] = [
        *_signal_overlap(agent_calls),
        *_signal_retry(agent_calls, result_map),
    ]
    return findings


