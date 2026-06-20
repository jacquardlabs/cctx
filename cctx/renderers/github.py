"""GitHub Actions job summary renderer.

render_github_summary(diagnosis) -> str
    Returns a markdown string suitable for appending to $GITHUB_STEP_SUMMARY.

write_github_summary(diagnosis) -> None
    Appends the markdown to $GITHUB_STEP_SUMMARY. Falls back to stderr warning
    when $GITHUB_STEP_SUMMARY is not set (e.g. local invocations).
"""
from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from cctx.models import KIND_LABEL
from cctx.pricing import PRICING_LAST_VERIFIED

if TYPE_CHECKING:
    from cctx.models import Diagnosis

_SEVERITY_EMOJI = {
    "high":   "🔴",
    "medium": "🟡",
    "low":    "🟢",
}


def render_github_summary(diagnosis: Diagnosis) -> str:
    lines: list[str] = []

    lines.append(f"## cctx autopsy — session `{diagnosis.session_id}`\n")
    lines.append(
        f"**Session cost:** ~${diagnosis.total_cost_usd:.2f} "
        f"*(~85–95% of actual billing; prices as of {PRICING_LAST_VERIFIED})*\n"
    )
    if diagnosis.unknown_models:
        models = ", ".join(f"`{m}`" for m in diagnosis.unknown_models)
        lines.append(
            f"> ⚠️ Unrecognized model(s) priced at the default rate: {models} — "
            f"add to `cctx/pricing.py` for accurate cost.\n"
        )

    if not diagnosis.findings:
        lines.append("**Result:** ✅ Clean session — no findings.\n")
        return "\n".join(lines)

    pct = (
        diagnosis.waste_cost_usd / diagnosis.total_cost_usd * 100
        if diagnosis.total_cost_usd
        else 0
    )
    lines.append(
        f"**Result:** {len(diagnosis.findings)} finding(s) — "
        f"~${diagnosis.waste_cost_usd:.2f} attributed waste ({pct:.0f}%)\n"
    )

    # Findings table
    lines.append("| Severity | Pattern | Summary |")
    lines.append("|---|---|---|")
    for f in diagnosis.findings:
        sev_icon = _SEVERITY_EMOJI.get(f.severity.value, "")
        kind_label = KIND_LABEL.get(f.kind, f.kind.value.upper())
        summary = f.summary.replace("|", "\\|")
        lines.append(f"| {sev_icon} {f.severity.value} | {kind_label} | {summary} |")

    # Patch diffs
    if diagnosis.patches:
        lines.append("\n### Recommended CLAUDE.md patches\n")
        for patch in diagnosis.patches:
            lines.append(f"**{patch.description}**\n")
            lines.append(f"```diff\n{patch.unified_diff}\n```\n")

    return "\n".join(lines)


def write_github_summary(diagnosis: Diagnosis) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        print(
            "Warning: $GITHUB_STEP_SUMMARY not set; --github-summary has no effect.",
            file=sys.stderr,
        )
        return
    md = render_github_summary(diagnosis)
    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write(md + "\n")
