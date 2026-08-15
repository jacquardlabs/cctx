"""WCAG AA contrast enforcement for the HTML report's badges.

`.badge` renders at `.7rem` (11.2px against the 16px root) and
`font-weight: 700` — below the 18.66px bold threshold for WCAG's large-text
exemption, so the 4.5:1 normal-text floor applies to every badge.

These tests parse the shipped CSS out of the rendered HTML rather than
duplicating a colour table, so a badge rule added later is covered
automatically.
"""
from __future__ import annotations

import re

import pytest

from cctx.models import FindingKind, Severity
from tests.renderers.test_report import _make_diagnosis, _render

# ---------------------------------------------------------------------------
# WCAG 2.x relative luminance / contrast
# ---------------------------------------------------------------------------


def _srgb_lum(hex_color: str) -> float:
    """WCAG 2.x relative luminance of an sRGB hex colour."""
    h = hex_color.lstrip("#")
    if len(h) == 3:  # expand shorthand so #fff parses
        h = "".join(c * 2 for c in h)
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    r, g, b = linear
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _srgb_lum(a), _srgb_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


_RULE_RE = re.compile(r"\.badge\.([\w-]+)\s*\{([^}]*)\}")
_BG_RE = re.compile(r"background:\s*(#[0-9a-fA-F]{3,6})")
# Negative lookbehind keeps `border: 1px solid #x` and any future
# `background-color:` out of the foreground slot.
_FG_RE = re.compile(r"(?<![-\w])color:\s*(#[0-9a-fA-F]{3,6})")


def _badge_rules(html: str) -> dict[str, tuple[str, str]]:
    """Map badge class suffix -> (background, foreground) for every .badge.* rule."""
    rules: dict[str, tuple[str, str]] = {}
    for cls, body in _RULE_RE.findall(html):
        bg = _BG_RE.search(body)
        fg = _FG_RE.search(body)
        if bg and fg:
            rules[cls] = (bg.group(1), fg.group(1))
    return rules


@pytest.fixture(scope="module")
def badge_rules() -> dict[str, tuple[str, str]]:
    return _badge_rules(_render(_make_diagnosis()))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_contrast_helper_matches_wcag_reference() -> None:
    """Pin the helper against two published reference ratios."""
    assert _contrast("#000", "#fff") == pytest.approx(21.0, abs=0.01)
    # #767676 on white is the canonical "exactly passes AA" grey.
    assert _contrast("#767676", "#fff") == pytest.approx(4.54, abs=0.01)


def test_badge_rules_cover_every_kind_and_severity(badge_rules) -> None:
    """A missing rule renders an invisible badge, so absence must fail loudly."""
    for kind in FindingKind:
        assert f"kind-{kind.value}" in badge_rules, f"no badge rule for {kind.value}"
    for sev in Severity:
        assert f"sev-{sev.value}" in badge_rules, f"no badge rule for severity {sev.value}"


@pytest.mark.parametrize("kind", list(FindingKind), ids=lambda k: f"kind-{k.value}")
def test_kind_badge_meets_wcag_aa(kind: FindingKind, badge_rules) -> None:
    bg, fg = badge_rules[f"kind-{kind.value}"]
    ratio = _contrast(bg, fg)
    assert ratio >= 4.5, f"kind-{kind.value}: {fg} on {bg} is {ratio:.2f}:1, needs 4.5:1"


@pytest.mark.parametrize("sev", list(Severity), ids=lambda s: f"sev-{s.value}")
def test_severity_badge_meets_wcag_aa(sev: Severity, badge_rules) -> None:
    bg, fg = badge_rules[f"sev-{sev.value}"]
    ratio = _contrast(bg, fg)
    assert ratio >= 4.5, f"sev-{sev.value}: {fg} on {bg} is {ratio:.2f}:1, needs 4.5:1"


def test_every_badge_rule_meets_wcag_aa(badge_rules) -> None:
    """Sweeps all parsed rules, so a badge class beyond kind-/sev- is covered too."""
    failures = {
        cls: round(_contrast(bg, fg), 2)
        for cls, (bg, fg) in badge_rules.items()
        if _contrast(bg, fg) < 4.5
    }
    assert not failures, f"badges below WCAG AA 4.5:1: {failures}"


def test_badge_font_size_is_not_large_text() -> None:
    """The 4.5:1 floor applies only because badges are below the large-text threshold.

    If either declaration changes, the floor these tests enforce needs rechecking.
    """
    html = _render(_make_diagnosis())
    base = re.search(r"\.badge\s*\{([^}]*)\}", html)
    assert base is not None, ".badge base rule not found"
    body = base.group(1)
    assert "font-size: .7rem" in body
    assert "font-weight: 700" in body
