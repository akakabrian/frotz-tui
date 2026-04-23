"""FrotzApp — 5-panel Textual TUI around dfrotz.

Layout:

    +-----------+-------------------------------------------+
    |           |   status bar (room / score / moves)       |
    |  MAP      +-------------------------------------------+
    |           |                                           |
    +-----------+   TRANSCRIPT (scrollable)                 |
    |           |                                           |
    | INVENTORY |                                           |
    |           +-------------------------------------------+
    |           |   > input bar                             |
    +-----------+-------------------------------------------+
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from .engine import FrotzEngine, StatusLine, classify_line
from .mapper import Mapper
from .screens import HelpScreen


INVENTORY_COMMANDS = {"i", "inv", "inventory"}

# Rough heuristic: lines that end with punctuation and start with a
# capital letter and don't contain ">" are likely narrative prose —
# rendered in the default color. Room headers (short title-cased lines)
# get styled yellow so they stand out in the transcript.
def _looks_like_room_header(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 50:
        return False
    # No trailing punctuation, Title Case.
    if s[-1] in ".!?,;:":
        return False
    words = s.split()
    if len(words) < 1 or len(words) > 6:
        return False
    # All words start with caps (allowing articles).
    caps = sum(1 for w in words if w and w[0].isupper())
    return caps >= max(1, len(words) - 1)


@dataclass
class _InvCapture:
    """State machine for capturing the output of an `inventory` command
    so we can stream it into the inventory panel rather than (or in
    addition to) the transcript."""
    active: bool = False
    lines: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.lines is None:
            self.lines = []


class StatusBar(Static):
    """Top bar: shows room name, score, and moves from the z-machine
    status line. Reactive-ish — we just update the renderable directly."""

    def __init__(self) -> None:
        super().__init__("", id="status_bar")
        self.status: StatusLine | None = None

    def apply(self, st: StatusLine) -> None:
        self.status = st
        text = Text.assemble(
            ("  ", ""),
            (f"{st.room}", "bold #ffd866"),
            ("    ", ""),
            (f"Score: {st.score}", "#8ec9ff"),
            ("    ", ""),
            (f"Moves: {st.moves}", "#cfe08a"),
        )
        self.update(text)


class MapPanel(Static):
    """Left pane: shows the auto-mapper's current view."""

    def __init__(self) -> None:
        super().__init__("(map)", id="map_panel")
        self.mapper = Mapper()

    def refresh_map(self) -> None:
        try:
            w = max(10, self.size.width - 2)
            h = max(6, self.size.height - 2)
        except Exception:
            w, h = 26, 18
        lines = self.mapper.render(viewport_w=w, viewport_h=h)
        text = Text()
        text.append("— MAP —\n", style="bold #8ec9ff")
        for ln in lines:
            text.append(ln + "\n")
        self.update(text)


class InventoryPanel(Static):
    """Left-bottom pane: last-known inventory. Updated lazily whenever the
    player types an `inventory` command and the output settles."""

    def __init__(self) -> None:
        super().__init__("(inventory)", id="inventory_panel")
        self.items: list[str] = []

    def set_items(self, items: list[str]) -> None:
        self.items = items
        text = Text()
        text.append("— INVENTORY —\n", style="bold #cfe08a")
        if not items:
            text.append("(nothing)\n", style="dim")
        else:
            for it in items:
                text.append("• " + it.strip() + "\n")
        self.update(text)


class FrotzApp(App):
    """Main Textual app."""

    CSS_PATH = "tui.tcss"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True, show=True),
        Binding("ctrl+l", "clear_transcript", "Clear", show=True),
        Binding("ctrl+r", "refresh_all", "Refresh", show=False),
        Binding("question_mark", "help", "Help", show=True),
    ]

    def __init__(self, story_path: str, dfrotz_path: str) -> None:
        super().__init__()
        self.story_path = story_path
        self.dfrotz_path = dfrotz_path
        # Use a small virtual screen (80×24); real rendering happens in
        # our Textual widgets, not in dfrotz's "screen".
        self.engine = FrotzEngine(dfrotz_path, story_path, width=80, height=24)
        self.transcript: RichLog | None = None
        self.input_bar: Input | None = None
        self.status_bar: StatusBar | None = None
        self.map_panel: MapPanel | None = None
        self.inv_panel: InventoryPanel | None = None
        self._inv_capture = _InvCapture()
        # Pending command — filled when user hits Enter, echoed into the
        # transcript, and used by the mapper to interpret status changes.
        self._last_command: str | None = None
        # Command history (most-recent last). Arrow keys in the input bar
        # walk the history like a shell.
        self._history: list[str] = []
        self._history_pos: int | None = None   # None = live entry; int = index
        # Timer handle (so we can cancel on shutdown).
        self._pump_timer = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main"):
            with Vertical(id="left"):
                self.map_panel = MapPanel()
                self.inv_panel = InventoryPanel()
                yield self.map_panel
                yield self.inv_panel
            with Vertical(id="center"):
                self.status_bar = StatusBar()
                self.transcript = RichLog(
                    id="transcript",
                    highlight=False,
                    wrap=True,
                    max_lines=2000,
                )
                self.input_bar = Input(
                    placeholder="Type a command (look, inventory, north)… and Enter",
                    id="input_bar",
                )
                yield self.status_bar
                yield self.transcript
                yield self.input_bar
        yield Footer()

    async def on_mount(self) -> None:
        self.title = f"frotz-tui — {Path(self.story_path).name}"
        assert self.input_bar is not None
        self.input_bar.focus()
        try:
            self.engine.start()
        except FileNotFoundError as e:
            self._write_transcript(f"[error] {e}", style="bold red")
            return
        # Poll the engine at 20 Hz. Line batches arrive in ~instantaneous
        # bursts after each player command, so this feels real-time.
        self._pump_timer = self.set_interval(0.05, self._pump_engine)
        # Refresh the map pane at 2 Hz — cheap.
        self.set_interval(0.5, self._refresh_panels)

    def on_unmount(self) -> None:
        if self._pump_timer is not None:
            self._pump_timer.stop()
        self.engine.stop()

    # ---------- engine pump ----------

    def _pump_engine(self) -> None:
        if not self.engine.is_alive():
            return
        lines = self.engine.read_available()
        if not lines:
            # If we're capturing inventory and the stream has gone quiet,
            # flush the buffered lines to the inventory panel.
            if self._inv_capture.active and self._inv_capture.lines:
                self._flush_inventory()
            return
        for raw in lines:
            if raw == "__EOF__":
                self._write_transcript("[game ended]", style="bold yellow")
                continue
            kind, val = classify_line(raw)
            if kind == "status":
                assert isinstance(val, StatusLine)
                self._on_status(val)
            else:
                assert isinstance(val, str)
                self._on_text(val)

    def _on_status(self, st: StatusLine) -> None:
        assert self.status_bar is not None and self.map_panel is not None
        self.status_bar.apply(st)
        self.map_panel.mapper.note_room(st.room)

    def _on_text(self, line: str) -> None:
        # Skip dfrotz's startup chatter — doesn't belong in the transcript.
        if line.startswith(("Using normal formatting", "Loading ")):
            return
        # If we're capturing inventory, tee the line into the buffer and
        # also let it flow to the transcript (so the player sees it).
        if self._inv_capture.active:
            # Empty line after the first content line marks end of
            # inventory block for most games. We'll flush on the next
            # quiet tick if this is empty AND we already have items.
            self._inv_capture.lines.append(line)
        if _looks_like_room_header(line):
            self._write_transcript(line, style="bold #ffd866")
        else:
            self._write_transcript(line)

    def _flush_inventory(self) -> None:
        assert self.inv_panel is not None
        lines = list(self._inv_capture.lines)
        self._inv_capture.active = False
        self._inv_capture.lines = []
        # Extract bullet-style lines. Typical Inform output:
        #   You are carrying:
        #     a brass lantern
        #     the keys
        items: list[str] = []
        found_header = False
        for ln in lines:
            s = ln.strip()
            if not s:
                if found_header and items:
                    break   # blank line after items — done
                continue
            if s.lower().startswith(("you are carrying", "you have")):
                found_header = True
                continue
            if s.lower() == "you are carrying nothing.":
                items = []
                found_header = True
                break
            if found_header:
                # Strip leading articles / indentation.
                cleaned = s.lstrip("-• ").strip()
                if cleaned:
                    items.append(cleaned)
        self.inv_panel.set_items(items)

    # ---------- UI helpers ----------

    def _write_transcript(self, text: str, style: str | None = None) -> None:
        assert self.transcript is not None
        if style:
            self.transcript.write(Text(text, style=style))
        else:
            self.transcript.write(text)

    def _refresh_panels(self) -> None:
        if self.map_panel is not None:
            self.map_panel.refresh_map()

    # ---------- event handlers ----------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Player hit Enter in the input bar."""
        cmd = event.value.strip()
        assert self.input_bar is not None
        self.input_bar.value = ""
        self._history_pos = None
        if not cmd:
            return
        if not self.engine.is_alive():
            self._write_transcript("[engine not running]", style="bold red")
            return
        # Record history (dedupe consecutive duplicates).
        if not self._history or self._history[-1] != cmd:
            self._history.append(cmd)
        # Echo the command into the transcript so it reads like a play log.
        self._write_transcript(f"> {cmd}", style="bold #8ec9ff")
        # Tell the mapper what direction (if any) we're about to take.
        if self.map_panel is not None:
            self.map_panel.mapper.note_command(cmd)
        # Kick off inventory capture.
        if cmd.lower() in INVENTORY_COMMANDS:
            self._inv_capture.active = True
            self._inv_capture.lines = []
        try:
            self.engine.send(cmd)
        except RuntimeError as e:
            self._write_transcript(f"[engine error] {e}", style="bold red")
        self._last_command = cmd

    async def on_key(self, event) -> None:
        """Up/Down in the input bar walks command history."""
        # Only react if the input is focused and not a modal screen.
        if self.input_bar is None or not self.input_bar.has_focus:
            return
        if self.screen is not self.screen_stack[0]:
            # A modal is on top.
            return
        if event.key == "up" and self._history:
            if self._history_pos is None:
                self._history_pos = len(self._history) - 1
            else:
                self._history_pos = max(0, self._history_pos - 1)
            self.input_bar.value = self._history[self._history_pos]
            event.stop()
        elif event.key == "down" and self._history:
            if self._history_pos is None:
                return
            self._history_pos += 1
            if self._history_pos >= len(self._history):
                self._history_pos = None
                self.input_bar.value = ""
            else:
                self.input_bar.value = self._history[self._history_pos]
            event.stop()

    # ---------- actions ----------

    def action_clear_transcript(self) -> None:
        if self.transcript is not None:
            self.transcript.clear()

    def action_refresh_all(self) -> None:
        self._refresh_panels()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())


def run(*, story_path: str, dfrotz_path: str) -> None:
    app = FrotzApp(story_path=story_path, dfrotz_path=dfrotz_path)
    app.run()
