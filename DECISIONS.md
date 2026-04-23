# frotz-tui — design decisions

## Engine choice: dfrotz (dumb frontend)

Frotz's `dumb` interface builds to a standalone binary `dfrotz` that reads
commands on stdin and writes the game transcript to stdout. This is ideal
for a subprocess pipe-based integration — no SWIG / ctypes / FFI headaches.

Alternatives considered:
- **SWIG-binding Frotz core directly.** Frotz's `common/` layer has C
  entry points but expects a display driver (dumb/curses/SDL). Wrapping
  the core would mean reimplementing a display driver in Python that
  calls back into our TUI — doable but 10× the effort. dfrotz already
  IS the display driver we want.
- **Pure-Python Z-machine.** `python-zmachine`, `bitch-zmachine` exist
  but are incomplete or unmaintained. Frotz is the reference
  implementation with 30 years of bug-fixes.

## Subprocess I/O protocol

- Launch: `dfrotz -p -m -w <width> -h <height> <story.z*>`
  - `-p` plain ASCII only (we don't need IRC/ANSI codes — Textual renders
    styles directly)
  - `-m` disables MORE prompts (otherwise dfrotz pauses on full screens
    waiting for keyboard input; breaks pipe model)
  - `-w`/`-h` set the virtual screen dimensions
- Read stdout line-by-line. Z-machine status lines intersperse with game
  text — we detect them (column-aligned "Location ... Score: N Moves: N")
  and route them to the status panel rather than the transcript.
- Write commands to stdin, terminated by `\n`. dfrotz echoes nothing back;
  we render the user's typed command into the transcript on our side.

## Story bundled: Advent (Colossal Cave), Graham Nelson's Inform port

Release 9 / Serial 060321 — bundled under `stories/advent.z5` (138 KB).
This port is freely redistributable: the Inform library samples are in
the public distribution at <https://www.ifarchive.org/if-archive/games/zcode/>
and there are no license restrictions on redistributing the z5. Crowther
& Woods' original 1976/1977 Adventure code itself is in the public domain;
Nelson's Inform 6 reconstruction follows that same tradition.

Avoided bundling:
- Zork I/II/III — Infocom; Activision owns the copyright, free download
  from Infocom's site was never a redistribution license.
- Anchorhead — freely playable but the author (Michael S. Gentry) has not
  issued an explicit redistribution license, so erring on safe side.
- Curses! — Graham Nelson; Nelson has made Advent freely redistributable
  but Curses! is shareware.

## Architecture

```
frotz-tui/
├── frotz.py                  # entry: argparse → run(...)
├── pyproject.toml            # textual + aiohttp deps
├── Makefile                  # engine build, venv, run, clean, test
├── DECISIONS.md              # this file
├── stories/advent.z5         # bundled test story
├── engine/                   # vendored frotz source + built dfrotz binary
├── frotz_tui/
│   ├── engine.py             # FrotzEngine: subprocess wrapper, parse_output()
│   ├── app.py                # FrotzApp, TranscriptPane, InputBar, panels
│   ├── screens.py            # HelpScreen, LoadScreen, SaveScreen, MapScreen
│   ├── mapper.py             # auto-map: tracks room transitions → graph
│   └── tui.tcss              # Textual stylesheet
└── tests/
    ├── qa.py                 # TUI scenarios via Pilot
    ├── perf.py               # hot-path benchmarks
    └── out/                  # screenshots
```

## Panels

- **Transcript** (main, center) — scrollable log of game output + player
  commands. RichLog with max_lines=2000.
- **Input bar** (bottom) — single-line Input widget; Enter submits.
- **Status** (top-right) — room name, score, moves. Parsed from the
  z-machine status line.
- **Inventory** (right) — periodically issues `inventory` (via a
  side-channel save/restore trick, or just polls on natural pauses).
  Cached between polls.
- **Map** (left) — auto-built graph of visited rooms and transitions.
  Uses the status line's room-name changes + the direction the player
  last typed to build edges.

## Status line parsing

Advent's status format (v3 Z-machine): one line, location left-aligned,
"Score: N    Moves: N" right-aligned. Regex:
`r'^\s*(.+?)\s+Score:\s*(-?\d+)\s+Moves:\s*(\d+)\s*$'`. V4+ games use a
2-line split window we'll ignore for now (render into transcript).

## Map auto-build strategy

Track `(prev_room, direction_typed, new_room)` triples. When the
player's typed command is a known direction (n/s/e/w/ne/nw/se/sw/u/d/in/
out and their long forms), and the post-command status line reports a
different room name, add an edge. Render as a rough graph in an ASCII
grid — place the current room at center, siblings at compass offsets,
reuse positions for known rooms. Good enough to be useful even without
a proper force-directed layout.

## Inventory refresh

Strategy: intercept the transcript stream for `inventory`-like outputs
(when the player types `i` / `inv` / `inventory`). After the response
settles (idle for ~300 ms), re-parse lines between the typed command
and the next status line as the inventory contents.

Background polling is rejected — it mutates the turn counter, and many
games count an inventory command as a turn (food rots, batteries drain,
etc.). We stay passive.
