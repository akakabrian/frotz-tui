# frotz-tui

Terminal Z-machine interpreter — [Frotz](https://gitlab.com/DavidGriffith/frotz)
(the canonical Infocom-compatible interpreter) wrapped in a
[Textual](https://github.com/Textualize/textual) TUI with transcript,
status, inventory, and auto-mapper panels.

```
+-------------+---------------------------------------------+
| MAP         | Room / Score / Moves                         |
|             +---------------------------------------------+
|  [*EOR*]—   |                                             |
|   |         |   (game transcript — scrollable, wrapped)   |
|   |         |                                             |
+-------------+                                             |
| INVENTORY   |                                             |
|             +---------------------------------------------+
|  • lamp     | > _                                         |
|  • keys     |                                             |
+-------------+---------------------------------------------+
```

## Install / run (Linux)

```bash
git clone <this-repo> frotz-tui
cd frotz-tui
make all      # clone + build dfrotz + make venv
make run      # launches with the bundled Adventure story
```

`make all` does:
1. `git clone` [DavidGriffith/frotz](https://gitlab.com/DavidGriffith/frotz)
   into `engine/`
2. `make dumb` inside that tree → produces `engine/dfrotz`
3. `python3 -m venv .venv && pip install -e .`

## Playing

- Type commands at the bottom prompt, hit Enter.
- Arrow keys / Page Up/Down scroll the transcript.
- Ctrl-L clears the transcript.
- Ctrl-C quits.

The map auto-builds as you walk. The inventory panel updates whenever
you type `i` / `inv` / `inventory`.

## Custom stories

```
python frotz.py path/to/my-game.z5
```

Any `.z3`–`.z8` story file works. Frotz's dumb frontend reads anything
the reference interpreter accepts.

## Bundled story

- `stories/advent.z5` — *Adventure* (Colossal Cave), Graham Nelson's
  Inform 6 reconstruction, Release 9 / serial 060321, freely
  redistributable.

Other free IF:
- [Curses!](https://www.ifarchive.org/if-archive/games/zcode/curses.z5) — Graham Nelson, shareware (playable, not redistributable).
- [Anchorhead](https://www.ifarchive.org/if-archive/games/zcode/Anchorhead.z8) — Michael S. Gentry.
- Full catalogue: <https://www.ifarchive.org/if-archive/games/zcode/>.

## Tests

```bash
make test                         # all scenarios
make test-only PAT=status         # scenarios matching 'status'
```

## License

GPL-3.0 — Frotz is GPLv2-or-later; our wrapper follows through. See
`engine/COPYING` for the Frotz license.
