"""Headless QA for frotz-tui.

    python -m tests.qa          # run all
    python -m tests.qa status   # run scenarios whose name matches 'status'

Each scenario gets a fresh `FrotzApp` via `App.run_test()`, runs to
completion (or assertion), and saves an SVG screenshot to `tests/out/`.
Exit code is the number of failures.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from frotz_tui.app import FrotzApp
from frotz_tui.engine import parse_status_line
from frotz_tui.mapper import Mapper, canonical_direction


REPO = Path(__file__).resolve().parent.parent
DFROTZ = REPO / "engine" / "dfrotz"
STORY = REPO / "stories" / "advent.z5"
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)


@dataclass
class Scenario:
    name: str
    fn: Callable[[FrotzApp, "object"], Awaitable[None]]


# ---------- helper: wait for engine quiet ----------

async def _wait_for_text(app: FrotzApp, pilot, needle: str, *,
                         timeout: float = 4.0) -> bool:
    """Poll the transcript's rendered lines until `needle` appears or
    timeout elapses."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await pilot.pause(0.05)
        if app.transcript is None:
            continue
        # RichLog exposes `.lines` (list of Strip) and we can stringify.
        try:
            joined = "\n".join(
                "".join(seg.text for seg in list(line))
                for line in app.transcript.lines
            )
        except Exception:
            joined = ""
        if needle.lower() in joined.lower():
            return True
    return False


# ---------- scenarios ----------

async def s_mount_clean(app, pilot):
    assert app.transcript is not None
    assert app.input_bar is not None
    assert app.status_bar is not None
    assert app.map_panel is not None
    assert app.inv_panel is not None


async def s_engine_boots(app, pilot):
    # Wait for the game's title text.
    ok = await _wait_for_text(app, pilot, "ADVENTURE", timeout=4.0)
    assert ok, "Advent banner never arrived in transcript"
    assert app.engine.is_alive(), "engine died immediately"


async def s_status_line_populates(app, pilot):
    # Let the intro flow in and the status line update.
    ok = await _wait_for_text(app, pilot, "End Of Road", timeout=4.0)
    assert ok, "room text did not appear"
    # Now press a command so the status line refreshes.
    assert app.input_bar is not None
    app.input_bar.focus()
    await pilot.press(*"look")
    await pilot.press("enter")
    # Give dfrotz a moment to respond.
    for _ in range(40):
        if app.status_bar.status is not None:
            break
        await pilot.pause(0.05)
    st = app.status_bar.status
    assert st is not None, "status bar never populated"
    assert "End Of Road" in st.room, f"room={st.room!r}"
    assert st.moves >= 0


async def s_typing_command_echoes(app, pilot):
    await _wait_for_text(app, pilot, "End Of Road", timeout=4.0)
    assert app.input_bar is not None
    app.input_bar.focus()
    await pilot.press(*"look")
    await pilot.press("enter")
    # The echo line is "> look"
    ok = await _wait_for_text(app, pilot, "> look", timeout=2.0)
    assert ok, "user command was not echoed into transcript"


async def s_movement_updates_room(app, pilot):
    await _wait_for_text(app, pilot, "End Of Road", timeout=4.0)
    assert app.input_bar is not None
    app.input_bar.focus()
    await pilot.press(*"east")
    await pilot.press("enter")
    # Advent: "east" at End Of Road → "Inside Building".
    ok = await _wait_for_text(app, pilot, "Inside Building", timeout=3.0)
    assert ok, "moving east did not bring us Inside Building"


async def s_inventory_populates_panel(app, pilot):
    await _wait_for_text(app, pilot, "End Of Road", timeout=4.0)
    assert app.input_bar is not None
    app.input_bar.focus()
    # First grab some items — go east, then inventory.
    await pilot.press(*"east")
    await pilot.press("enter")
    await _wait_for_text(app, pilot, "Inside Building", timeout=3.0)
    await pilot.press(*"take all")
    await pilot.press("enter")
    await pilot.pause(0.3)
    await pilot.press(*"inventory")
    await pilot.press("enter")
    # Wait for the inventory capture to flush (one quiet tick after
    # the listing arrives).
    ok = await _wait_for_text(app, pilot, "You are carrying", timeout=3.0)
    assert ok, "inventory response not seen in transcript"
    # Now give the pump a moment to flush into the panel.
    for _ in range(40):
        if app.inv_panel.items:
            break
        await pilot.pause(0.05)
    assert app.inv_panel.items, "inventory panel is still empty after `inventory`"


async def s_mapper_records_edge(app, pilot):
    await _wait_for_text(app, pilot, "End Of Road", timeout=4.0)
    assert app.map_panel is not None
    assert app.input_bar is not None
    app.input_bar.focus()
    await pilot.press(*"east")
    await pilot.press("enter")
    await _wait_for_text(app, pilot, "Inside Building", timeout=3.0)
    # Give the status pump a moment.
    await pilot.pause(0.3)
    rooms = app.map_panel.mapper.rooms
    names = set(rooms.keys())
    assert any("End Of Road" in n for n in names), f"rooms={names}"
    assert any("Inside Building" in n for n in names), f"rooms={names}"
    # Edge from End Of Road --east--> Inside Building should exist.
    eor = next(r for r in rooms.values() if "End Of Road" in r.name)
    assert eor.exits.get("e", "").startswith("Inside"), eor.exits


async def s_engine_dies_gracefully(app, pilot):
    """Killing the engine subprocess out from under the app should not
    crash the TUI — the pump tick must handle `is_alive() == False` and
    the next input submission should display a clear error."""
    await _wait_for_text(app, pilot, "End Of Road", timeout=4.0)
    # Hard-kill the subprocess.
    assert app.engine._proc is not None
    app.engine._proc.kill()
    # Let the pump notice.
    await pilot.pause(0.3)
    assert not app.engine.is_alive()
    # App still standing — widgets intact?
    assert app.transcript is not None
    assert app.map_panel is not None
    # Submitting a command now should produce an error, not a crash.
    assert app.input_bar is not None
    app.input_bar.focus()
    await pilot.press(*"look")
    await pilot.press("enter")
    ok = await _wait_for_text(app, pilot, "engine not running", timeout=1.0)
    assert ok, "expected graceful 'engine not running' message"


async def s_empty_command_ignored(app, pilot):
    """Hitting Enter with no input shouldn't send anything to dfrotz."""
    await _wait_for_text(app, pilot, "End Of Road", timeout=4.0)
    assert app.input_bar is not None
    app.input_bar.focus()
    # Just Enter — no text.
    await pilot.press("enter")
    await pilot.pause(0.2)
    # No "> " prompt with empty text should have been echoed.
    # (If the empty-command guard failed, we'd see the echo.)
    txt = "\n".join(
        "".join(seg.text for seg in list(line))
        for line in app.transcript.lines
    )
    # There should be no "> \n" or "> " at the end as a single line.
    assert "> \n" not in txt, "empty command was echoed"


async def s_mapper_handles_unknown_direction(app, pilot):
    """Mapper.note_command with a non-direction should not add bogus edges."""
    m = Mapper()
    m.note_room("A")
    m.note_command("xyzzy")   # not a direction
    m.note_room("B")
    # B should be placed, but there should be no edge labelled "xyzzy"
    # on A.
    assert "B" in m.rooms
    assert "xyzzy" not in m.rooms["A"].exits


async def s_help_modal_opens_and_closes(app, pilot):
    await _wait_for_text(app, pilot, "End Of Road", timeout=4.0)
    # Focus the app (not the input) so the ? binding fires at the App level.
    # Input has its own keystroke handling; we trigger the action directly.
    app.action_help()
    await pilot.pause(0.1)
    assert app.screen.__class__.__name__ == "HelpScreen", (
        f"after help action, top screen is {app.screen.__class__.__name__}"
    )
    await pilot.press("escape")
    await pilot.pause(0.1)
    assert app.screen.__class__.__name__ != "HelpScreen"


async def s_command_history_recall(app, pilot):
    """Up arrow in the input bar should recall the last command."""
    await _wait_for_text(app, pilot, "End Of Road", timeout=4.0)
    assert app.input_bar is not None
    app.input_bar.focus()
    # Submit a command to populate history.
    await pilot.press(*"look")
    await pilot.press("enter")
    await pilot.pause(0.2)
    # Now press up-arrow.
    await pilot.press("up")
    await pilot.pause(0.05)
    assert app.input_bar.value == "look", f"history recall: {app.input_bar.value!r}"
    # Down clears back to live entry.
    await pilot.press("down")
    await pilot.pause(0.05)
    assert app.input_bar.value == "", f"down should clear, got {app.input_bar.value!r}"


async def s_clear_transcript_binding(app, pilot):
    await _wait_for_text(app, pilot, "End Of Road", timeout=4.0)
    assert app.transcript is not None
    # We can't easily check line-count on RichLog, but we can fire the
    # action and trust the widget.
    before = len(app.transcript.lines)
    app.action_clear_transcript()
    await pilot.pause(0.05)
    after = len(app.transcript.lines)
    assert after < before, f"clear didn't shrink log: {before} → {after}"


# ---------- pure-function unit scenarios (no Pilot) ----------

async def s_parse_status_variants(app, pilot):
    # Standard score/moves line.
    st = parse_status_line(
        " At End Of Road                                      Score: 36    Moves: 0"
    )
    assert st and st.room == "At End Of Road" and st.score == 36 and st.moves == 0
    # Negative score.
    st = parse_status_line(" Dark Cave                      Score: -5    Moves: 120")
    assert st and st.score == -5 and st.moves == 120
    # Prompt-prefixed (dfrotz flush artifact).
    st = parse_status_line("> Inside Building   Score: 36    Moves: 2")
    assert st and st.room == "Inside Building"
    # Junk: should not match.
    assert parse_status_line("You are carrying nothing.") is None
    assert parse_status_line("") is None
    assert parse_status_line(">") is None
    # Time-based status (v4).
    st = parse_status_line(" Library        Time: 14:30")
    assert st and "14:30" in st.room


async def s_canonical_direction(app, pilot):
    assert canonical_direction("n") == "n"
    assert canonical_direction("NORTH") == "n"
    assert canonical_direction("go east") == "e"
    assert canonical_direction("walk up") == "u"
    assert canonical_direction("take lamp") is None
    assert canonical_direction("") is None


async def s_mapper_basic(app, pilot):
    m = Mapper()
    m.note_room("Entrance")
    assert m.current == "Entrance"
    assert "Entrance" in m.rooms
    m.note_command("east")
    m.note_room("Hallway")
    assert m.current == "Hallway"
    assert m.rooms["Entrance"].exits.get("e") == "Hallway"
    assert m.rooms["Hallway"].exits.get("w") == "Entrance"  # auto-reverse
    # Non-movement command → no new edge on the next room change.
    m.note_command("look")
    m.note_room("Secret Room")
    assert "Secret Room" in m.rooms
    assert "look" not in m.rooms["Hallway"].exits  # no bogus direction


# ---------- harness ----------

SCENARIOS: list[Scenario] = [
    Scenario("parse_status_variants",      s_parse_status_variants),
    Scenario("canonical_direction",        s_canonical_direction),
    Scenario("mapper_basic",               s_mapper_basic),
    Scenario("mount_clean",                s_mount_clean),
    Scenario("engine_boots",               s_engine_boots),
    Scenario("status_line_populates",      s_status_line_populates),
    Scenario("typing_command_echoes",      s_typing_command_echoes),
    Scenario("movement_updates_room",      s_movement_updates_room),
    Scenario("inventory_populates_panel",  s_inventory_populates_panel),
    Scenario("mapper_records_edge",        s_mapper_records_edge),
    Scenario("mapper_unknown_direction",   s_mapper_handles_unknown_direction),
    Scenario("empty_command_ignored",      s_empty_command_ignored),
    Scenario("engine_dies_gracefully",     s_engine_dies_gracefully),
    Scenario("help_modal",                 s_help_modal_opens_and_closes),
    Scenario("command_history_recall",     s_command_history_recall),
    Scenario("clear_transcript_binding",   s_clear_transcript_binding),
]


async def run_scenario(scn: Scenario) -> tuple[str, bool, str]:
    app = FrotzApp(story_path=str(STORY), dfrotz_path=str(DFROTZ))
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            # Let on_mount run + initial engine output flow in.
            await pilot.pause(0.1)
            try:
                await scn.fn(app, pilot)
                try:
                    app.save_screenshot(
                        str(OUT / f"{scn.name}.PASS.svg")
                    )
                except Exception:
                    pass
                return (scn.name, True, "")
            except AssertionError as e:
                try:
                    app.save_screenshot(
                        str(OUT / f"{scn.name}.FAIL.svg")
                    )
                except Exception:
                    pass
                return (scn.name, False, f"AssertionError: {e}")
            except Exception:
                try:
                    app.save_screenshot(
                        str(OUT / f"{scn.name}.ERROR.svg")
                    )
                except Exception:
                    pass
                return (scn.name, False, traceback.format_exc())
    finally:
        # Belt-and-braces: make sure the dfrotz subprocess is torn down.
        try:
            app.engine.stop()
        except Exception:
            pass


def main(argv: list[str]) -> int:
    pattern = argv[1] if len(argv) > 1 else None
    scns = [s for s in SCENARIOS if pattern is None or pattern in s.name]
    if not scns:
        print(f"no scenarios match {pattern!r}")
        return 1
    failures: list[tuple[str, str]] = []
    for scn in scns:
        name, ok, detail = asyncio.run(run_scenario(scn))
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {name}")
        if not ok:
            # Print the first 5 lines of the failure detail for quick eyeballing.
            for ln in detail.splitlines()[:10]:
                print(f"        {ln}")
            failures.append((name, detail))
    print()
    print(f"{len(scns) - len(failures)}/{len(scns)} passed")
    return len(failures)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
