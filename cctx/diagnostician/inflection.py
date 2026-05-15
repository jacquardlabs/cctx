"""Inflection-turn detection.

The inflection turn is the earliest turn in the session where a classifier
found a problem. Future versions may detect inflection from turn-level signals
that precede any classifier finding (rising error rate, apology language, etc.).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cctx.models import Finding


def detect(findings: list[Finding]) -> int | None:
    """Return the earliest first_turn across all findings, or None."""
    if not findings:
        return None
    return min(f.first_turn for f in findings)
