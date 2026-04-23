"""Modal screens — help, save/restore, quit confirm."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


HELP_TEXT = """\
[bold #ffd866]frotz-tui — quick reference[/]

[bold]Moving[/]                       [bold]Interacting[/]
  north / n   south / s        look  (l)      examine X  (x X)
  east  / e   west  / w        take X         drop X
  ne nw se sw                  inventory (i)  wear X
  up / u   down / d            open X         close X
  enter / in   exit / out      read X         push X

[bold]Meta commands (parser)[/]
  save / restore               oops / undo / again (g)
  verbose / brief              score
  quit        (leaves the game; ctrl-c exits the app)

[bold]App bindings[/]
  Enter      submit the typed command
  Up / Down  recall previous / next command
  Ctrl-L     clear the transcript (sim state unaffected)
  Ctrl-C     quit the app
  ?          open this help
  Esc        close modal

[dim]The map and inventory panels update automatically as you play —
the map grows whenever you enter a new room, and the inventory
refreshes whenever you type an [bold]inventory[/] command.[/]
"""


class HelpScreen(ModalScreen[None]):
    """Modal help overlay. Dismissed with Escape / Enter / q / ?."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > Vertical {
        width: 72;
        height: auto;
        max-height: 90%;
        background: #1a2236;
        border: round #ffd866;
        padding: 1 2;
    }
    HelpScreen Static#help_body {
        height: auto;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "close", priority=True),
        Binding("enter", "dismiss", "close", priority=True),
        Binding("q", "dismiss", "close", priority=True),
        Binding("question_mark", "dismiss", "close", priority=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(HELP_TEXT, id="help_body", markup=True)

    def action_dismiss(self) -> None:
        self.app.pop_screen()
