"""Textual TUI for trace visualization with autopsy overlay.

Public API:
    affected_turns(finding, trace) -> frozenset[int]
    verdict(diagnosis) -> str
    finding_modal_text(findings) -> str
    flags_label(findings) -> str
    build_app(trace, diagnosis) -> App   # for tests (Pilot); not run
    launch(trace, diagnosis) -> None

Internal:
    _build_flagged_index(findings, trace) -> dict[int, list[Finding]]

Textual is only imported inside launch() so that the pure helpers remain
importable without the textual package (e.g. during testing).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cctx.models import KIND_LABEL, FindingKind

if TYPE_CHECKING:
    from cctx.models import Diagnosis, Finding, SessionTrace, Turn


# ---------------------------------------------------------------------------
# Pure helpers — no Textual dependency
# ---------------------------------------------------------------------------


def affected_turns(finding: Finding, trace: SessionTrace) -> frozenset[int]:
    """Return turn numbers covered by a finding using per-kind evidence extraction."""
    ev = finding.evidence or {}
    kind = finding.kind

    if kind is FindingKind.RETRY_LOOP:
        turns: set[int] = {occ["turn"] for occ in ev.get("occurrences", []) if "turn" in occ}
    elif kind is FindingKind.SCOPE_CREEP:
        turns = {ph["turn"] for ph in ev.get("phrases", []) if "turn" in ph}
    elif kind is FindingKind.STALE_CONTEXT:
        last = finding.last_turn if finding.last_turn is not None else finding.first_turn
        turns = set()
        for item in ev.get("stale_items", []):
            if "last_referenced_turn" in item:
                turns.update(range(item["last_referenced_turn"] + 1, last + 1))
    else:
        last = finding.last_turn if finding.last_turn is not None else finding.first_turn
        turns = set(range(finding.first_turn, last + 1))

    return frozenset(turns) if turns else frozenset({finding.first_turn})


def verdict(diagnosis: Diagnosis) -> str:
    """Canonical one-line headline. Delegates to Diagnosis.verdict (single source)."""
    return diagnosis.verdict


def finding_modal_text(
    findings: list[Finding], sub_labels: dict[str, str] | None = None
) -> str:
    """Body text for the FindingModal — one block per finding, KIND_LABEL headed.
    Subagent findings (session_id set) are prefixed with their [label]."""
    sub_labels = sub_labels or {}
    lines: list[str] = []
    for f in findings:
        label = KIND_LABEL.get(f.kind, f.kind.value.upper())
        if f.session_id is not None:
            tag = sub_labels.get(f.session_id, f.session_id[:8])
            label = f"[{tag}] {label}"
        lines.append(
            f"[bold]{label}[/]  severity={f.severity.value}  confidence={f.confidence.value}"
        )
        lines.append(f"  {f.summary}")
        if f.cost_usd is not None:
            lines.append(f"  cost: ${f.cost_usd:.4f}")
        lines.append("")
    return "\n".join(lines).rstrip() or "No findings."


def flags_label(findings: list[Finding]) -> str:
    """Comma-joined KIND_LABELs for the trace table Flags column."""
    return ", ".join(KIND_LABEL.get(f.kind, f.kind.value.upper()) for f in findings)


def _build_flagged_index(findings: list[Finding], trace: SessionTrace) -> dict[int, list[Finding]]:
    """Map turn_number -> list of findings that affect that turn."""
    index: dict[int, list[Finding]] = {}
    for finding in findings:
        for tn in affected_turns(finding, trace):
            index.setdefault(tn, []).append(finding)
    return index


# ---------------------------------------------------------------------------
# Entry point — Textual imports deferred here
# ---------------------------------------------------------------------------


def build_app(trace: SessionTrace, diagnosis: Diagnosis):  # noqa: C901
    """Build the Textual app and return it (does NOT run it). Imports textual on call.

    Returned rather than run so tests can drive it via App.run_test() (Textual
    Pilot). launch() wraps this with .run() for the blocking CLI path.
    """
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import ScrollableContainer
    from textual.screen import ModalScreen
    from textual.widgets import DataTable, Footer, Header, Label, Static

    flagged = _build_flagged_index(diagnosis.findings, trace)
    session_verdict = verdict(diagnosis)
    sub_labels = {a.session_id: a.label for a in diagnosis.subagent_costs}

    class FindingModal(ModalScreen):  # type: ignore[type-arg]
        """Finding details for the selected turn."""

        DEFAULT_CSS = """
        FindingModal {
            align: center middle;
            width: 80%;
            height: 80%;
        }
        FindingModal > ScrollableContainer {
            background: $surface;
            border: solid $accent;
            padding: 1 2;
        }
        """

        BINDINGS = [
            Binding("escape", "dismiss", "Close"),
            Binding("q", "dismiss", "Close"),
        ]

        def __init__(self, findings: list[Finding]) -> None:
            super().__init__()
            self._findings = findings

        def compose(self) -> ComposeResult:
            text = finding_modal_text(self._findings, sub_labels)
            with ScrollableContainer():
                yield Label(text, markup=True)

    class ToolResultModal(ModalScreen):  # type: ignore[type-arg]
        """Turn content and tool results for the selected turn."""

        DEFAULT_CSS = """
        ToolResultModal {
            align: center middle;
            width: 80%;
            height: 80%;
        }
        ToolResultModal > ScrollableContainer {
            background: $surface;
            border: solid $accent;
            padding: 1 2;
        }
        """

        BINDINGS = [
            Binding("escape", "dismiss", "Close"),
            Binding("q", "dismiss", "Close"),
        ]

        def __init__(self, selected_turn: Turn) -> None:
            super().__init__()
            self._turn = selected_turn

        def compose(self) -> ComposeResult:
            t = self._turn
            lines: list[str] = [f"[bold]Turn {t.turn_number}[/] — {t.role}", ""]
            if t.text:
                preview = t.text[:2000]
                if len(t.text) > 2000:
                    preview += "\n[dim]…truncated[/]"
                lines.append(preview)
                lines.append("")
            for tr in t.tool_results:
                lines.append(f"[bold]{tr.tool_name}[/] ({tr.tool_use_id})")
                content_preview = tr.content[:1000]
                if len(tr.content) > 1000:
                    content_preview += "\n[dim]…truncated[/]"
                lines.append(content_preview)
                lines.append("")
            if not t.text and not t.tool_results:
                lines.append("[dim](no content)[/]")
            with ScrollableContainer():
                yield Label("\n".join(lines), markup=True)

    class HelpScreen(ModalScreen):  # type: ignore[type-arg]
        """Keyboard shortcut reference."""

        DEFAULT_CSS = """
        HelpScreen {
            align: center middle;
            width: 60%;
            height: 60%;
        }
        HelpScreen > ScrollableContainer {
            background: $surface;
            border: solid $accent;
            padding: 1 2;
        }
        """

        BINDINGS = [
            Binding("escape", "dismiss", "Close"),
            Binding("q", "dismiss", "Close"),
            Binding("question_mark", "dismiss", "Close"),
        ]

        def compose(self) -> ComposeResult:
            help_text = (
                "[bold]cctx trace — keyboard shortcuts[/]\n\n"
                "  [bold]↑ / ↓[/]    Navigate turns\n"
                "  [bold]Enter[/]    Show turn content / tool results\n"
                "  [bold]f[/]        Show finding details (flagged turns only)\n"
                "  [bold]?[/]        Toggle this help screen\n"
                "  [bold]q[/]        Quit\n"
            )
            with ScrollableContainer():
                yield Label(help_text, markup=True)

    class TraceTUI(App):  # type: ignore[type-arg]
        """Interactive turn-by-turn trace viewer with autopsy overlay."""

        DEFAULT_CSS = """
        DataTable { height: 1fr; }
        #verdict { height: 1; background: $accent; color: $text; padding: 0 1; }
        """

        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("f", "show_finding", "Finding"),
            Binding("question_mark", "show_help", "Help"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self._turn_numbers: list[int] = []

        def compose(self) -> ComposeResult:
            yield Header()
            yield DataTable(id="turns", cursor_type="row")
            yield Static(session_verdict, id="verdict")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#turns", DataTable)
            table.add_column("#", width=6)
            table.add_column("Role", width=14)
            table.add_column("Model", width=22)
            table.add_column("Tokens", width=10)
            table.add_column("Flags", width=22)

            for t in trace.turns:
                is_flagged = t.turn_number in flagged
                findings = flagged.get(t.turn_number, [])
                if t.usage:
                    total = (
                        t.usage.input_tokens
                        + t.usage.cache_creation_5m
                        + t.usage.cache_creation_1h
                        + t.usage.cache_read
                    )
                    tokens = f"{total:,}"
                else:
                    tokens = ""
                model = t.model or ""
                flags = flags_label(findings)

                if is_flagged:
                    cells = [
                        f"[bold red]{t.turn_number}[/]",
                        f"[bold red]{t.role}[/]",
                        f"[red]{model}[/]",
                        f"[red]{tokens}[/]",
                        f"[bold red]{flags}[/]",
                    ]
                else:
                    cells = [str(t.turn_number), t.role, model, tokens, flags]

                table.add_row(*cells)
                self._turn_numbers.append(t.turn_number)

        def _current_turn_number(self) -> int | None:
            table = self.query_one("#turns", DataTable)
            idx = table.cursor_row
            if idx < 0 or idx >= len(self._turn_numbers):
                return None
            return self._turn_numbers[idx]

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            idx = event.cursor_row
            if idx < 0 or idx >= len(self._turn_numbers):
                return
            turn_number = self._turn_numbers[idx]
            selected = next((t for t in trace.turns if t.turn_number == turn_number), None)
            if selected is not None:
                self.push_screen(ToolResultModal(selected))

        def action_show_finding(self) -> None:
            tn = self._current_turn_number()
            if tn is None:
                return
            findings = flagged.get(tn)
            if not findings:
                return
            self.push_screen(FindingModal(findings))

        def action_show_help(self) -> None:
            self.push_screen(HelpScreen())

    return TraceTUI()


def launch(trace: SessionTrace, diagnosis: Diagnosis) -> None:
    """Build and run the Textual app (blocking). Imports textual on first call."""
    build_app(trace, diagnosis).run()
