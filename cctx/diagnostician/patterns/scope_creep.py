"""Scope-creep classifier.

Fires only on explicit re-scoping phrases in assistant turn text (conservative
v0). No structural heuristics. One Finding per session; all phrase matches
bundled into evidence.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cctx.models import Confidence, Finding, FindingKind, Severity

if TYPE_CHECKING:
    from cctx.models import SessionTrace

# Case-insensitive phrase list. "i noticed that" requires a following action verb.
_PLAIN_PHRASES = [
    "i'll also fix",
    "while i'm here",
    "let me also",
    "i also noticed",
    "while we're at it",
    "i should also",
    "additionally, i'll",
]

_ACTION_VERBS = r"(?:fix|add|update|change|remove|clean|refactor|improve|address)"
_NOTICED_THAT = re.compile(
    r"i noticed that.{0,20}" + _ACTION_VERBS,
    re.IGNORECASE,
)


def _matches(text: str) -> list[str]:
    """Return all matched phrases found in text."""
    low = text.lower()
    found = [p for p in _PLAIN_PHRASES if p in low]
    if _NOTICED_THAT.search(text):
        found.append("i noticed that")
    return found




def classify(trace: SessionTrace) -> list[Finding]:
    phrases_found: list[dict] = []

    for turn in trace.turns:
        if turn.role != "assistant" or not turn.text:
            continue
        matched = _matches(turn.text)
        for phrase in matched:
            low = turn.text.lower()
            idx = low.find(phrase)
            start = max(0, idx - 20)
            snippet = turn.text[start : start + 80]
            phrases_found.append({
                "turn": turn.turn_number,
                "phrase": phrase,
                "snippet": snippet,
            })

    if not phrases_found:
        return []

    first_turn = min(p["turn"] for p in phrases_found)
    count = len(phrases_found)
    first_phrase = phrases_found[0]["phrase"]
    plural = "s" if count > 1 else ""
    summary = f"'{first_phrase}' at turn {first_turn} ({count} scope expansion{plural} total)"

    return [Finding(
        kind=FindingKind.SCOPE_CREEP,
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        first_turn=first_turn,
        last_turn=phrases_found[-1]["turn"] if len(phrases_found) > 1 else None,
        evidence={"phrases": phrases_found},
        cost_usd=None,
        summary=summary,
    )]
