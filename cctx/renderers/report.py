"""HTML report renderer for autopsy Diagnosis output.

render_html(diag, trace) -> str
  Returns a fully self-contained HTML string with inlined CSS.
  No external resources; no JavaScript.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, select_autoescape

if TYPE_CHECKING:
    from cctx.models import Diagnosis, Finding, SessionTrace

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _flagged_index(findings: list[Finding]) -> dict[int, list[Finding]]:
    index: dict[int, list[Finding]] = {}
    for f in findings:
        last = f.last_turn if f.last_turn is not None else f.first_turn
        for tn in range(f.first_turn, last + 1):
            index.setdefault(tn, []).append(f)
    return index


def render_html(diag: Diagnosis, trace: SessionTrace) -> str:
    """Render a Diagnosis as a self-contained HTML report string."""
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["to_json"] = lambda v: json.dumps(v, indent=2, default=str)

    def _diff_highlight(diff_text: str) -> str:
        lines = []
        for line in diff_text.splitlines():
            from markupsafe import Markup, escape
            escaped = escape(line)
            if line.startswith("+") and not line.startswith("+++"):
                lines.append(Markup(f'<span class="add">{escaped}</span>'))
            elif line.startswith("-") and not line.startswith("---"):
                lines.append(Markup(f'<span class="del">{escaped}</span>'))
            else:
                lines.append(escaped)
        return Markup("\n".join(lines))

    env.filters["diff_highlight"] = _diff_highlight

    from cctx.pricing import PRICING_LAST_VERIFIED

    sub_labels = {a.session_id: a.label for a in diag.subagent_costs}

    tmpl = env.get_template("autopsy.html.j2")
    return tmpl.render(
        diag=diag,
        trace=trace,
        flagged=_flagged_index(diag.findings),
        pricing_as_of=PRICING_LAST_VERIFIED,
        sub_labels=sub_labels,
    )
