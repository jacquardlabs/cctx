# Trace TUI — design

**Status:** draft — awaiting review before implementation
**Date:** 2026-05-14
**Module:** `cctx/renderers/trace_tui.py`
**Pipeline position:** `(SessionTrace, Diagnosis) → [TraceTUI renderer] → terminal`

## 1. Goal

`cctx trace <session>` opens an interactive TUI that lets a developer navigate a Claude Code session turn by turn with the autopsy diagnosis overlaid. Turns that participate in a detected pattern glow with the finding's severity color. Pressing Enter on a flagged turn reveals the diagnosis snippet. A persistent status bar shows the session-level verdict and total waste cost. The goal is forensic navigation — "what happened at turn 14, and why does cctx flag it?" — not transcript browsing, not editing, and not replay. The TUI is a renderer: it consumes a pre-computed `(SessionTrace, Diagnosis)` pair and presents it; it never runs classifiers, never re-derives costs, and never calls `anthropic`.

## 2. Design decisions

These are recorded so implementors don't re-litigate them.

### 2.1 The TUI is a renderer

`trace_tui.py` lives in `cctx/renderers/`. It imports from `cctx.models` and uses Textual. It does not import `click`, `rich_click`, `anthropic`, or anything from `cctx.diagnostician` or `cctx.recommender`. Analysis is complete before the TUI opens.

### 2.2 Diagnosis input is orchestrator output (no patches)

The CLI passes the `Diagnosis` returned by `diagnostician.run(trace)` — `patches=[]`. The TUI does not display patches; that's the terminal renderer's and harvest's job. The CLI does not call `recommender.generate()` before opening the TUI.

```python
# cli.py wiring
trace     = parse_session(session_path)
diagnosis = diagnostician.run(trace)
# NOTE: recommender.generate() is NOT called here — patches not shown in TUI
app = TraceTUI(trace=trace, diagnosis=diagnosis)
app.run()
```

### 2.3 Affected-turn resolution via per-kind extraction

`Finding` has no `affected_turns: list[int]` field. The TUI resolves which turns glow via a helper `affected_turns(finding) -> frozenset[int]` defined in `trace_tui.py`. Per-kind extraction rules:

| Kind | Extraction |
|---|---|
| `retry_loop` | `{occ["turn"] for occ in finding.evidence["occurrences"]}` |
| `scope_creep` | `{ph["turn"] for ph in finding.evidence["phrases"]}` |
| `stale_context` | `range(item["last_referenced_turn"], trace_last_turn + 1)` for each stale item (compaction-truncated) |

For `stale_context`, the "glowing" range is from the point each item goes stale to the end of the session (or next compaction event). The helper receives the `SessionTrace` so it can look up the last turn number and compaction events.

```python
def affected_turns(finding: Finding, trace: SessionTrace) -> frozenset[int]:
    kind = finding.kind
    if kind is FindingKind.RETRY_LOOP:
        return frozenset(occ["turn"] for occ in finding.evidence["occurrences"])
    if kind is FindingKind.SCOPE_CREEP:
        return frozenset(ph["turn"] for ph in finding.evidence["phrases"])
    if kind is FindingKind.STALE_CONTEXT:
        last = trace.turns[-1].turn_number if trace.turns else 0
        turns: set[int] = set()
        for item in finding.evidence["stale_items"]:
            start = item["last_referenced_turn"] + 1
            turns.update(range(start, last + 1))
        return frozenset(turns)
    return frozenset()
```

The helper is called once at TUI startup; results are stored in a `dict[int, list[Finding]]` mapping each flagged turn number to its findings. This avoids recomputing on every render.

### 2.4 Verdict string

`Diagnosis` has no `verdict: str` field. The TUI derives one via a presentation helper:

```python
def verdict(diagnosis: Diagnosis) -> str:
    if not diagnosis.findings:
        return "clean"
    parts = [f.kind.value.replace("_", " ") for f in diagnosis.findings]
    return " + ".join(parts)
```

Example: `"retry loop + scope creep"`. This matches the brief's example output.

### 2.5 Severity → CSS color classes

| Severity | Textual CSS class | Approximate color |
|---|---|---|
| `HIGH` | `.finding-high` | red (`$error`) |
| `MEDIUM` | `.finding-medium` | yellow (`$warning`) |
| `LOW` | `.finding-low` | blue (`$accent`) |

The default Textual theme variables map `$error` to red and `$warning` to yellow. The TUI's `DEFAULT_CSS` defines these classes so they are self-contained.

```css
.finding-high   { background: $error 30%;   color: $text; }
.finding-medium { background: $warning 30%; color: $text; }
.finding-low    { background: $accent 30%;  color: $text; }
```

A turn card that is flagged by multiple findings takes the highest severity class.

### 2.6 Context-decomposition mini-panel is presentation arithmetic only

The `c` key toggles a mini-panel that decomposes the session's token usage. This is pure arithmetic over fields already on `SessionTrace` and `Turn` — no new analysis module. The panel shows:

- Initial context tokens: `trace.initial_context_tokens`
- User inputs total: sum of `turn.usage.input_tokens` across assistant turns (this reflects the full API input at each call — as close as we can get without the internal framing)
- Tool result tokens: sum of `result.token_count for turn in trace.turns for result in turn.tool_results`
- Waste estimate: `diagnosis.waste_cost_usd` and `diagnosis.total_cost_usd`
- Unattributed remainder: labelled "system internals (not in logs)" — the honest gap

This is a presentation helper in `trace_tui.py`, not a new analyzer.

### 2.7 Subagent turns render without finding glow

`ToolUse.subagent_session_id` links to a child `SessionTrace` in `trace.subagents`. The TUI renders subagent turns as collapsible nodes within the parent turn card. Because autopsy v0 diagnoses the main trace only, subagent child turns carry no severity glow. The collapsible node header shows: subagent session ID (truncated), turn count, and model if known. v1 will add `sub_diagnoses` to `Diagnosis` and the TUI will then be able to glow subagent turns.

### 2.8 Tool result expansion is a modal

Large tool result content is not rendered inline — it opens a `ToolResultModal`. The card shows a one-line preview (first 80 chars of `tool_result.content`). Pressing Enter on a card with a tool result, or pressing `r`, opens the modal.

### 2.9 Finding detail is a second modal

Pressing Enter on a flagged turn opens a `FindingModal`, not the tool result modal. If the turn is both flagged and has a tool result, Enter opens `FindingModal` and `r` opens `ToolResultModal`.

## 3. Data model interface

The TUI reads only the fields listed here. Everything else on `SessionTrace` and `Diagnosis` is ignored.

### From `SessionTrace`

```python
trace.session_id            # str — displayed in header
trace.source_path           # Path — displayed in header subtitle
trace.primary_model         # str | None — status bar
trace.turns                 # list[Turn] — one card per turn
trace.subagents             # list[SessionTrace] — for collapsible subagent nodes
trace.start_time            # datetime | None — header
trace.end_time              # datetime | None — header
```

### From `Turn`

```python
turn.turn_number            # int — card label
turn.role                   # str — "user" | "assistant" | "system"
turn.text                   # str — card body preview (first 120 chars)
turn.model                  # str | None — shown on assistant turns
turn.tool_uses              # list[ToolUse] — tool name badges on card
turn.tool_results           # list[ToolResult] — expandable via modal
turn.usage                  # Usage | None — token detail (t toggle)
turn.timestamp              # datetime — shown in card footer
```

### From `ToolUse`

```python
tool_use.tool_name           # str
tool_use.subagent_session_id # str | None — triggers subagent node
```

### From `ToolResult`

```python
tool_result.tool_name        # str
tool_result.content          # str — preview + modal body
tool_result.is_error         # bool — error styling on card
tool_result.token_count      # int — shown in modal header
```

### From `Diagnosis`

```python
diagnosis.findings           # list[Finding] — for affected_turns() mapping
diagnosis.inflection_turn    # int | None — highlighted in turn list
diagnosis.total_cost_usd     # float — status bar
diagnosis.waste_cost_usd     # float — status bar
```

### From `Finding`

```python
finding.kind                 # FindingKind — modal title
finding.severity             # Severity — CSS class selection
finding.first_turn           # int
finding.last_turn            # int | None
finding.evidence             # dict — per-kind extraction for affected_turns()
finding.summary              # str — one-line badge on the card
```

## 4. Screen layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ cctx trace — abc123 | /Users/bryan/projects/myapp  | claude-sonnet-4-6      │
│ 2026-05-14 09:14–09:26 (12m 18s) | 38 turns                                 │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│ ▶  T01 [user]       "Fix the auth bug in the login flow"           09:14:01  │
│    T02 [assistant]  "I'll start by reading the auth module..."     09:14:08  │
│    T03 [user]       [tool_result: Read(src/auth.py) 1,240 tok]    09:14:08  │
│    T04 [assistant]  "I see the issue. Let me fix it..."            09:14:15  │
│    T05 [user]       [tool_result: Edit(src/auth.py) ok]            09:14:15  │
│ ░░ T06 [assistant]  "Let me run the tests to confirm..."           09:14:22  │  <- flagged (inflection)
│░░░ T07 [user]       [tool_result: Bash(npm test) ERROR 3 fails]   09:14:23  │  <- HIGH (retry_loop)
│░░░ T08 [assistant]  "while I'm here, I'll also fix the user..."   09:14:30  │  <- MEDIUM (scope_creep)
│    ...                                                                       │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│ Verdict: retry loop + scope creep | Waste: $0.83 / $1.42 total              │
│ ↑↓ / jk navigate  enter expand  t tokens  f filter  c context  q quit       │
└──────────────────────────────────────────────────────────────────────────────┘
```

Cards with no finding have no background tint. The inflection turn is marked with `▶` in the gutter even when it isn't the highest-severity flagged turn. The status bar is always visible.

When the context-decomposition panel is open (`c`):

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ [header as above]                                                            │
├──────────────────────────────────┬───────────────────────────────────────────┤
│ [turn list, scrollable]          │ Context decomposition                     │
│                                  │ ─────────────────────────────────────     │
│                                  │ Initial context       42,140 tok          │
│                                  │ User inputs total    318,220 tok          │
│                                  │ Tool results          89,400 tok          │
│                                  │ System internals       ~8,000 tok (est.)  │
│                                  │ ─────────────────────────────────────     │
│                                  │ Total cost            $1.42               │
│                                  │ Waste (stale ctx)     $0.92               │
├──────────────────────────────────┴───────────────────────────────────────────┤
│ [status bar as above]                                                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 5. Turn card design

Each turn is rendered as a single `ListItem` in a `ListView`. The card layout (left-to-right within one line for the compact default; expandable for long text):

```
[gutter] Tnn [role]   [text preview — 80 chars]    [tool badges]  [timestamp]
```

Fields:
- **Gutter** (4 chars): `▶` if inflection turn, `░░░` shading with severity color if flagged. An inflection turn that is also flagged shows `▶` over the severity background.
- **Turn number**: `T01`–`T99` (zero-padded to match session length). Sessions > 99 turns use `T001` etc.
- **Role badge**: `[user]`, `[assistant]`, `[system]` — styled with dim color to not compete with severity.
- **Text preview**: first 80 characters of `turn.text`. Truncated with `…`. If `turn.text` is empty and the turn has tool_results, shows `[tool_result: {tool_name}({key_preview})]`.
- **Tool badges**: for each `ToolUse` in `turn.tool_uses`, a pill: `Bash` / `Read` / `Edit` / etc. Error tool results add `✗` suffix: `Bash✗`.
- **Severity badge**: if flagged, a small inline badge after the text: `⚠ retry loop` (HIGH) or `↕ scope creep` (MEDIUM). Uses the finding's `summary` field. Multiple findings on one turn show the highest-severity badge plus a `+N` indicator.
- **Timestamp**: right-aligned, `HH:MM:SS` format.

When `t` (token detail) is active, each card adds a second line:
```
     input: 18,240 tok  output: 842 tok  cache_read: 12,100 tok
```
(From `turn.usage`; shown only on assistant turns with non-None usage. User/tool_result turns show nothing on the second line.)

## 6. Keyboard map

| Key | Action |
|---|---|
| `↑` / `k` | Move selection up one turn |
| `↓` / `j` | Move selection down one turn |
| `Enter` | On flagged turn: open `FindingModal`. On unflagged turn with tool results: open `ToolResultModal`. On unflagged turn without tool results: no-op. |
| `r` | Open `ToolResultModal` for selected turn's first tool result (if any). |
| `t` | Toggle token detail line on all cards. |
| `f` | Open filter dialog: filter visible turns by tool name. Cycle through tools with `↑`/`↓`, confirm with `Enter`, clear with `Escape`. |
| `c` | Toggle context-decomposition mini-panel (right sidebar). |
| `g` | Jump to inflection turn (if any). |
| `q` / `Ctrl+C` | Quit. |
| `Escape` | Close open modal or filter dialog. |
| `?` | Toggle keybinding help overlay. |

## 7. Finding overlay (FindingModal)

When Enter is pressed on a flagged turn, a `FindingModal` (a Textual `ModalScreen`) opens. It shows all findings that flag the selected turn, one panel per finding.

Layout:

```
┌──────────────────────────────────────────────────────┐
│  ⚠ Retry loop — HIGH confidence                      │
│  Turns 14–22                                         │
│  ──────────────────────────────────────────────────  │
│  Edit(src/auth.py) failed 3× between turns 12–16     │
│                                                      │
│  Evidence:                                           │
│    Turn 14: Edit(src/auth.py) → Error: permission    │
│    Turn 16: Edit(src/auth.py) → Error: permission    │
│    Turn 18: Edit(src/auth.py) → Error: permission    │
│                                                      │
│  [No patch shown — use cctx autopsy for full report] │
│                                                      │
│  Press Escape to close                               │
└──────────────────────────────────────────────────────┘
```

Content per finding:
- **Title**: finding kind (human-readable) + severity badge.
- **Span**: `Turns {first_turn}–{last_turn}` (or just `Turn {first_turn}` if `last_turn is None`).
- **Summary line**: `finding.summary` verbatim.
- **Evidence**: per-kind rendering —
  - `retry_loop`: table of `evidence["occurrences"]` rows: turn, key, error preview (40 chars).
  - `scope_creep`: each entry in `evidence["phrases"]`: turn + 80-char snippet with the phrase highlighted.
  - `stale_context`: table of `evidence["stale_items"]`: tool_name, content_tokens, turns_stale, token_turns.
- **Footer note**: `[No patch shown — use cctx autopsy for full report]`. The TUI deliberately omits patches to keep focus on navigation.

When multiple findings flag the same turn, each is rendered as a separate panel in the modal, separated by a horizontal rule. The highest-severity finding is shown first.

## 8. Tool result modal (ToolResultModal)

A `ModalScreen` that shows the full content of one tool result. Triggered by `r` on any turn with tool results, or by Enter on an unflagged turn that has tool results.

Layout:

```
┌──────────────────────────────────────────────────────┐
│  Tool result: Bash  |  Turn 7  |  token_count: 4,820 │
│  is_error: False                                     │
│  ──────────────────────────────────────────────────  │
│  $ npm test                                          │
│                                                      │
│  > myapp@1.0.0 test                                  │
│  > jest                                              │
│                                                      │
│  PASS src/auth.test.js                               │
│  FAIL src/user.test.js                               │
│    ● should validate email format                    │
│      Expected: true  Received: false                 │
│  ...                                                 │
│  ──────────────────────────────────────────────────  │
│  [↑↓ scroll]  [Escape close]                         │
└──────────────────────────────────────────────────────┘
```

Content:
- **Header**: tool name, turn number, `token_count` (0 shown as "not counted" — offline mode).
- **`is_error`** displayed as `is_error: True` with error styling when true.
- **Body**: `tool_result.content` rendered as a scrollable `TextLog` or `RichLog` widget, monospace.
- If a turn has multiple tool results, a tab bar or `[1/N] → next` footer cycles between them.
- No syntax highlighting in v0 (avoids the dependency on `pygments` or similar).

## 9. Textual architecture

### 9.1 Widget tree

```
TraceTUI (App)
├── Header
│   ├── session_id + source_path
│   └── model + time range + turn count
├── Horizontal (main body)
│   ├── TurnListView (ListView, id="turn-list")
│   │   └── TurnListItem (ListItem) × N turns
│   │       └── TurnCard (Static or Horizontal)
│   └── ContextPanel (Static, id="context-panel")  ← hidden unless c toggled
└── StatusBar (Footer-like Static, id="status-bar")
    ├── verdict string
    ├── waste / total cost
    └── key hint strip
```

`FindingModal` and `ToolResultModal` are `ModalScreen` subclasses pushed onto the screen stack with `app.push_screen()`.

`FilterDialog` is a lightweight `ModalScreen` with a `ListView` of tool names.

### 9.2 App entry point

```python
class TraceTUI(App):
    """Textual application for cctx trace."""

    CSS_PATH = None  # inline DEFAULT_CSS
    BINDINGS = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("q", "quit", "Quit"),
        ("t", "toggle_tokens", "Tokens"),
        ("f", "open_filter", "Filter"),
        ("c", "toggle_context", "Context"),
        ("g", "jump_inflection", "Inflection"),
        ("?", "toggle_help", "Help"),
    ]

    def __init__(
        self,
        trace: SessionTrace,
        diagnosis: Diagnosis,
    ) -> None:
        super().__init__()
        self._trace = trace
        self._diagnosis = diagnosis
        # Pre-compute once: {turn_number: [Finding, ...]}
        self._flagged: dict[int, list[Finding]] = _build_flagged_index(
            diagnosis.findings, trace
        )

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield TurnListView(
                self._trace.turns,
                flagged=self._flagged,
                inflection_turn=self._diagnosis.inflection_turn,
                id="turn-list",
            )
            yield ContextPanel(self._trace, self._diagnosis, id="context-panel")
        yield StatusBar(self._trace, self._diagnosis, id="status-bar")
```

### 9.3 Key widget classes

```python
class TurnListView(ListView):
    """ListView populated with one TurnListItem per turn."""

    def __init__(
        self,
        turns: list[Turn],
        flagged: dict[int, list[Finding]],
        inflection_turn: int | None,
        **kwargs,
    ) -> None: ...

    def action_cursor_down(self) -> None:
        self.index = min(self.index + 1, len(self._children) - 1)

    def action_cursor_up(self) -> None:
        self.index = max(self.index - 1, 0)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        # Called on Enter key; delegate to the item.
        item: TurnListItem = event.item
        item.activate(self.app)


class TurnListItem(ListItem):
    """One turn card in the list."""

    def __init__(
        self,
        turn: Turn,
        findings: list[Finding],  # [] if not flagged
        is_inflection: bool,
        show_tokens: bool = False,
    ) -> None: ...

    def severity_class(self) -> str:
        """Return CSS class for highest-severity finding, or ''."""
        if not self.findings:
            return ""
        sev = max(
            (f.severity for f in self.findings),
            key=lambda s: {"high": 2, "medium": 1, "low": 0}[s.value],
        )
        return f"finding-{sev.value}"

    def activate(self, app: TraceTUI) -> None:
        """Push the appropriate modal."""
        if self.findings:
            app.push_screen(FindingModal(self.turn, self.findings))
        elif self.turn.tool_results:
            app.push_screen(ToolResultModal(self.turn))


class FindingModal(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, turn: Turn, findings: list[Finding]) -> None: ...


class ToolResultModal(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close"), ("r", "next_result", "Next")]

    def __init__(self, turn: Turn, result_index: int = 0) -> None: ...


class ContextPanel(Widget):
    """Right sidebar: context decomposition. Hidden by default."""

    def __init__(self, trace: SessionTrace, diagnosis: Diagnosis, **kwargs) -> None: ...

    def compute_breakdown(self) -> dict[str, int | float]:
        """Pure arithmetic; no analysis."""
        tool_result_tokens = sum(
            r.token_count for t in self._trace.turns for r in t.tool_results
        )
        user_input_tokens = sum(
            t.usage.input_tokens for t in self._trace.turns
            if t.usage is not None
        )
        return {
            "initial_context": self._trace.initial_context_tokens,
            "user_inputs_total": user_input_tokens,
            "tool_result_tokens": tool_result_tokens,
            "total_cost_usd": self._diagnosis.total_cost_usd,
            "waste_cost_usd": self._diagnosis.waste_cost_usd,
        }


class StatusBar(Static):
    """Fixed bottom bar: verdict + cost + key hints."""

    def __init__(self, trace: SessionTrace, diagnosis: Diagnosis, **kwargs) -> None: ...

    def render(self) -> str:
        v = verdict(self._diagnosis)
        return (
            f"Verdict: {v}  |  "
            f"Waste: ${self._diagnosis.waste_cost_usd:.2f} / "
            f"${self._diagnosis.total_cost_usd:.2f} total  |  "
            f"↑↓/jk navigate  enter expand  t tokens  f filter  c context  q quit"
        )
```

### 9.4 Pre-computation helpers

```python
def _build_flagged_index(
    findings: list[Finding],
    trace: SessionTrace,
) -> dict[int, list[Finding]]:
    """Return {turn_number: [finding, ...]} for all flagged turns."""
    index: dict[int, list[Finding]] = {}
    for f in findings:
        for turn_num in affected_turns(f, trace):
            index.setdefault(turn_num, []).append(f)
    # Sort each list by severity (highest first) for consistent rendering.
    sev_rank = {"high": 2, "medium": 1, "low": 0}
    for lst in index.values():
        lst.sort(key=lambda f: sev_rank[f.severity.value], reverse=True)
    return index
```

### 9.5 Subagent rendering

When a `TurnListItem` renders a turn whose `tool_uses` includes an entry with `subagent_session_id` set, it renders a collapsible `Collapsible` widget inside the card. The collapsible header shows the subagent session ID (first 12 chars) and turn count. Its body contains a nested `TurnListView`-like widget (read-only, non-interactive in v0) showing the subagent's turns in the same card format, with no severity glow (v0: no sub-diagnoses).

The subagent trace is retrieved from `trace.subagents` by matching `subagent_session_id`.

```python
def _find_subagent(trace: SessionTrace, session_id: str) -> SessionTrace | None:
    return next(
        (s for s in trace.subagents if s.session_id == session_id), None
    )
```

## 10. CLI integration

The `cctx trace` subcommand is added to `cli.py`:

```python
@cli.command("trace")
@click.argument("session", type=click.Path(exists=True, path_type=Path))
def trace_cmd(session: Path) -> None:
    """Navigate a session turn-by-turn with autopsy findings overlaid."""
    from cctx.parsers.claude_code import parse_session
    from cctx.diagnostician import run as diagnose
    from cctx.renderers.trace_tui import TraceTUI

    trace     = parse_session(session)
    diagnosis = diagnose(trace)
    app       = TraceTUI(trace=trace, diagnosis=diagnosis)
    app.run()
```

No `--json`, `--html`, or other output flags. The TUI is the only mode for `cctx trace`.

## 11. Testing approach

Tests live in `tests/test_trace_tui.py`. All use Textual's `Pilot` context manager for key simulation. Fixtures are reused from the existing `tests/fixtures/claude_code/` corpus — no new JSONL fixtures needed for basic navigation tests (the existing clean, retry-loop, and scope-creep fixtures cover the cases).

### 11.1 Navigation

```python
@pytest.mark.asyncio
async def test_navigation_j_k(trace_with_retry_loop, diagnosis_with_retry_loop):
    app = TraceTUI(trace=trace_with_retry_loop, diagnosis=diagnosis_with_retry_loop)
    async with app.run_test() as pilot:
        turn_list = app.query_one("#turn-list", TurnListView)
        assert turn_list.index == 0
        await pilot.press("j")
        assert turn_list.index == 1
        await pilot.press("k")
        assert turn_list.index == 0
```

### 11.2 Finding modal opens on flagged turn

```python
@pytest.mark.asyncio
async def test_enter_on_flagged_turn_opens_finding_modal(
    trace_with_retry_loop, diagnosis_with_retry_loop
):
    app = TraceTUI(trace=trace_with_retry_loop, diagnosis=diagnosis_with_retry_loop)
    async with app.run_test() as pilot:
        # Navigate to the first flagged turn.
        first_flagged = min(
            t for t in app._flagged
        )
        turn_list = app.query_one("#turn-list", TurnListView)
        # Jump to the flagged turn index (turn_number - 1 because 1-based).
        turn_list.index = first_flagged - 1
        await pilot.press("enter")
        assert len(app.query(FindingModal)) == 1
        await pilot.press("escape")
        assert len(app.query(FindingModal)) == 0
```

### 11.3 Tool result modal

```python
@pytest.mark.asyncio
async def test_r_opens_tool_result_modal(trace_clean, diagnosis_clean):
    # Navigate to a turn with tool results and press r.
    app = TraceTUI(trace=trace_clean, diagnosis=diagnosis_clean)
    async with app.run_test() as pilot:
        # Find a turn with tool_results by index.
        tool_result_turns = [
            t for t in trace_clean.turns if t.tool_results
        ]
        if not tool_result_turns:
            pytest.skip("fixture has no tool results")
        idx = tool_result_turns[0].turn_number - 1
        app.query_one("#turn-list", TurnListView).index = idx
        await pilot.press("r")
        assert len(app.query(ToolResultModal)) == 1
```

### 11.4 Token toggle

```python
@pytest.mark.asyncio
async def test_token_toggle(trace_clean, diagnosis_clean):
    app = TraceTUI(trace=trace_clean, diagnosis=diagnosis_clean)
    async with app.run_test() as pilot:
        await pilot.press("t")
        # After toggle, at least one TurnListItem should have a CSS class
        # or reactive indicating tokens are shown. Implementation-defined;
        # assert app._show_tokens is True as a proxy.
        assert app._show_tokens is True
        await pilot.press("t")
        assert app._show_tokens is False
```

### 11.5 Context panel toggle

```python
@pytest.mark.asyncio
async def test_context_panel_toggle(trace_clean, diagnosis_clean):
    app = TraceTUI(trace=trace_clean, diagnosis=diagnosis_clean)
    async with app.run_test() as pilot:
        panel = app.query_one("#context-panel", ContextPanel)
        assert not panel.display  # hidden by default
        await pilot.press("c")
        assert panel.display
        await pilot.press("c")
        assert not panel.display
```

### 11.6 Quit

```python
@pytest.mark.asyncio
async def test_q_quits(trace_clean, diagnosis_clean):
    app = TraceTUI(trace=trace_clean, diagnosis=diagnosis_clean)
    async with app.run_test() as pilot:
        await pilot.press("q")
    # app.run_test() context manager exits cleanly — no exception.
```

### 11.7 Affected-turns helper unit tests

```python
def test_affected_turns_retry_loop():
    finding = Finding(
        kind=FindingKind.RETRY_LOOP,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=14,
        last_turn=18,
        evidence={"occurrences": [{"turn": 14}, {"turn": 16}, {"turn": 18}], "loop_length": 3},
        cost_usd=None,
        summary="...",
    )
    result = affected_turns(finding, stub_trace(last_turn=20))
    assert result == frozenset({14, 16, 18})


def test_affected_turns_stale_context():
    finding = Finding(
        kind=FindingKind.STALE_CONTEXT,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        first_turn=11,
        last_turn=None,
        evidence={
            "stale_items": [{"last_referenced_turn": 11, "token_turns": 300_000, ...}],
            "total_token_turns": 300_000,
        },
        cost_usd=0.90,
        summary="...",
    )
    result = affected_turns(finding, stub_trace(last_turn=15))
    assert result == frozenset({12, 13, 14, 15})
```

### 11.8 What to assert vs. not

**Assert:** widget identity (modal mounted/unmounted), `ListView.index` position, reactive attribute values (`_show_tokens`, `_show_context`), panel display state.

**Do not assert:** exact rendered text (Textual snapshots are fragile to minor string changes). Use `assert panel.display` over `assert "initial_context_tokens" in panel.render()` for toggle tests; use the data-layer helpers for correctness of the underlying logic.

## 12. Out of scope for v0

- **Patch/diff display.** Patches live in the autopsy terminal renderer and harvest — not in the TUI.
- **Write capability.** The TUI is read-only. No applying patches, editing CLAUDE.md, or modifying sessions.
- **Cross-session navigation.** One session per `cctx trace` invocation.
- **Fork-and-replay.** No re-running tool calls.
- **Live filesystem watching.** Static snapshot only. `cctx watch` is a future feature.
- **Per-subagent finding overlay.** Subagent turns render but carry no severity glow until v1 adds `sub_diagnoses` to `Diagnosis`.
- **`--html` or `--json` flags on `cctx trace`.** Export is `cctx export`.
- **Syntax highlighting** in the tool result modal. Adds a dependency; defer to v1.
- **Session search.** No text search within the TUI in v0.
- **Mouse support.** Keyboard only in v0.

## 13. Open questions deferred to implementation

1. **Textual version pinning.** Textual's API has shifted across versions; pin to a specific Textual release in `pyproject.toml` and document it here when implementation begins. The widget names (`ListView`, `ListItem`, `ModalScreen`) match the Textual 0.x public API — verify against the pinned version.

2. **`TurnListView` scroll-to-inflection on startup.** Should the TUI scroll to `inflection_turn` on first open? Probably yes — it's the most useful default. Implement as `call_after_refresh(self._scroll_to_inflection)` in `on_mount`. Leave the decision to the implementor to confirm with the user.

3. **Filter dialog implementation.** The `f` key opens a filter dialog. The dialog needs a list of distinct tool names from `trace.turns`. Filtering should hide non-matching turns in the `ListView` (using Textual's display toggling). Decide during implementation whether to filter by removing `ListItem` children or using a `display=False` toggle (the latter avoids re-composing the list on filter clear).

4. **`?` help overlay.** The full keybinding table from §6 rendered as a modal. Textual's built-in `HelpPanel` may serve this; evaluate during implementation.

5. **Subagent collapsible depth limit.** Sessions with deeply nested subagents could create N levels of collapsible nesting. Cap at 2 levels in v0 (the same as `max_subagent_depth=4` in the parser doesn't mean the TUI must show all 4). Decide during implementation.
