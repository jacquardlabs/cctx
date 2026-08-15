"""Textual TUI for trace visualization with autopsy overlay.

Public API:
    affected_turns(finding, trace) -> frozenset[int]
    verdict(diagnosis) -> str
    finding_modal_text(findings) -> str
    flags_label(findings) -> str
    build_app(trace, diagnosis) -> App   # for tests (Pilot); not run
    launch(trace, diagnosis) -> None

    tool_result_modal_text(turn) -> str
    turn_row_cells(turn, findings) -> list[str]

Internal:
    _build_flagged_index(findings, trace) -> dict[int, list[Finding]]
    _build_finding_modal_cls() -> type
    _build_tool_result_modal_cls() -> type
    _build_help_screen_cls() -> type
    _build_app_cls(trace, flagged, verdict_line, sub_labels) -> type

Textual is imported lazily inside the _build_*_cls factories and build_app, so
the pure helpers above stay importable without the textual package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cctx.models import KIND_LABEL, FindingKind

if TYPE_CHECKING:
    from cctx.models import Diagnosis, Finding, SessionTrace, Turn

_TEXT_PREVIEW_LIMIT = 2000
_TOOL_RESULT_PREVIEW_LIMIT = 1000

_TURN_TABLE_COLUMNS = (
    ("#", 6),
    ("Role", 14),
    ("Model", 22),
    ("Tokens", 10),
    ("Flags", 22),
)

HELP_TEXT = (
    "[bold]cctx trace — keyboard shortcuts[/]\n\n"
    "  [bold]↑ / ↓[/]    Navigate turns\n"
    "  [bold]Enter[/]    Show turn content / tool results\n"
    "  [bold]f[/]        Show finding details (flagged turns only)\n"
    "  [bold]?[/]        Toggle this help screen\n"
    "  [bold]q[/]        Quit\n"
)


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


def tool_result_modal_text(turn: Turn) -> str:
    """Body of the turn-content modal: turn text plus each tool result."""
    lines: list[str] = [f"[bold]Turn {turn.turn_number}[/] — {turn.role}", ""]
    if turn.text:
        preview = turn.text[:_TEXT_PREVIEW_LIMIT]
        if len(turn.text) > _TEXT_PREVIEW_LIMIT:
            preview += "\n[dim]…truncated[/]"
        lines.append(preview)
        lines.append("")
    for tr in turn.tool_results:
        lines.append(f"[bold]{tr.tool_name}[/] ({tr.tool_use_id})")
        content_preview = tr.content[:_TOOL_RESULT_PREVIEW_LIMIT]
        if len(tr.content) > _TOOL_RESULT_PREVIEW_LIMIT:
            content_preview += "\n[dim]…truncated[/]"
        lines.append(content_preview)
        lines.append("")
    if not turn.text and not turn.tool_results:
        lines.append("[dim](no content)[/]")
    return "\n".join(lines)


def turn_row_cells(turn: Turn, findings: list[Finding]) -> list[str]:
    """One trace-table row. Flagged rows carry red markup.

    Tokens is input + cache creation + cache read; output_tokens is
    deliberately excluded (pinned by test_turn_row_tokens_sum_excludes_output_tokens).

    A turn is flagged iff it has findings. That is equivalent to the old
    `turn_number in flagged` check only because _build_flagged_index
    setdefault-appends and so never stores an empty list — an invariant this
    signature now depends on.
    """
    if turn.usage:
        total = (
            turn.usage.input_tokens
            + turn.usage.cache_creation_5m
            + turn.usage.cache_creation_1h
            + turn.usage.cache_read
        )
        tokens = f"{total:,}"
    else:
        tokens = ""
    model = turn.model or ""
    flags = flags_label(findings)

    if findings:
        return [
            f"[bold red]{turn.turn_number}[/]",
            f"[bold red]{turn.role}[/]",
            f"[red]{model}[/]",
            f"[red]{tokens}[/]",
            f"[bold red]{flags}[/]",
        ]
    return [str(turn.turn_number), turn.role, model, tokens, flags]


def _build_flagged_index(findings: list[Finding], trace: SessionTrace) -> dict[int, list[Finding]]:
    """Map turn_number -> list of findings that affect that turn."""
    index: dict[int, list[Finding]] = {}
    for finding in findings:
        for tn in affected_turns(finding, trace):
            index.setdefault(tn, []).append(finding)
    return index


# ---------------------------------------------------------------------------
# Textual class factories — each defers its own textual import
# ---------------------------------------------------------------------------


def _build_finding_modal_cls() -> type:
    """FindingModal: finding details for the selected turn."""
    from textual.app import ComposeResult
    from textual.binding import Binding
    from textual.containers import ScrollableContainer
    from textual.screen import ModalScreen
    from textual.widgets import Label

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

        def __init__(self, findings: list[Finding], sub_labels: dict[str, str]) -> None:
            super().__init__()
            self._findings = findings
            self._sub_labels = sub_labels

        def compose(self) -> ComposeResult:
            text = finding_modal_text(self._findings, self._sub_labels)
            with ScrollableContainer():
                yield Label(text, markup=True)

    return FindingModal


def _build_tool_result_modal_cls() -> type:
    """ToolResultModal: turn content and tool results for the selected turn."""
    from textual.app import ComposeResult
    from textual.binding import Binding
    from textual.containers import ScrollableContainer
    from textual.screen import ModalScreen
    from textual.widgets import Label

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
            with ScrollableContainer():
                yield Label(tool_result_modal_text(self._turn), markup=True)

    return ToolResultModal


def _build_help_screen_cls() -> type:
    """HelpScreen: keyboard shortcut reference."""
    from textual.app import ComposeResult
    from textual.binding import Binding
    from textual.containers import ScrollableContainer
    from textual.screen import ModalScreen
    from textual.widgets import Label

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
            with ScrollableContainer():
                yield Label(HELP_TEXT, markup=True)

    return HelpScreen


def _build_app_cls(
    trace: SessionTrace,
    flagged: dict[int, list[Finding]],
    verdict_line: str,
    sub_labels: dict[str, str],
) -> type:
    """TraceTUI: the trace table plus its three modal screens."""
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.widgets import DataTable, Footer, Header, Static

    FindingModal = _build_finding_modal_cls()
    ToolResultModal = _build_tool_result_modal_cls()
    HelpScreen = _build_help_screen_cls()

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
            yield Static(verdict_line, id="verdict")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#turns", DataTable)
            for name, width in _TURN_TABLE_COLUMNS:
                table.add_column(name, width=width)

            for t in trace.turns:
                table.add_row(*turn_row_cells(t, flagged.get(t.turn_number, [])))
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
            self.push_screen(FindingModal(findings, sub_labels))

        def action_show_help(self) -> None:
            self.push_screen(HelpScreen())

    return TraceTUI


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def build_app(trace: SessionTrace, diagnosis: Diagnosis):
    """Build the Textual app and return it (does NOT run it). Imports textual on call.

    Returned rather than run so tests can drive it via App.run_test() (Textual
    Pilot). launch() wraps this with .run() for the blocking CLI path.
    """
    cls = _build_app_cls(
        trace,
        _build_flagged_index(diagnosis.findings, trace),
        verdict(diagnosis),
        {a.session_id: a.label for a in diagnosis.subagent_costs},
    )
    return cls()


def launch(trace: SessionTrace, diagnosis: Diagnosis) -> None:
    """Build and run the Textual app (blocking). Imports textual on first call."""
    build_app(trace, diagnosis).run()
