"""Live playtest via pexpect — boots `make run` under a PTY, drives a
short scenario, and renders screenshots to tests/out/.

Complements the Pilot-based QA harness (tests/qa.py): that one asserts
structural invariants on widgets; this one proves the real terminal
rendering path doesn't crash when driven by keystrokes over a real pty.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pexpect

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "tests" / "out"
OUT.mkdir(exist_ok=True)


def _snapshot(child: pexpect.spawn, name: str) -> None:
    """Dump the current pty buffer into an SVG-ish text blob for archiving.
    We don't render real SVG here — the QA harness does that — but we
    leave a timestamped text artifact so regressions are diffable."""
    buf = (child.before or b"")
    if isinstance(buf, bytes):
        buf = buf.decode("utf-8", errors="replace")
    (OUT / f"playtest_{name}.txt").write_text(buf)


def main() -> int:
    dfrotz = REPO / "engine" / "dfrotz"
    story = REPO / "stories" / "advent.z5"
    if not dfrotz.exists() or not story.exists():
        print(f"missing engine or story: dfrotz={dfrotz.exists()} story={story.exists()}")
        return 1

    cmd = f"{REPO}/.venv/bin/python {REPO}/frotz.py"
    child = pexpect.spawn(
        cmd, cwd=str(REPO), dimensions=(40, 120), timeout=10,
        encoding="utf-8",
    )
    try:
        # Boot + initial transcript — Advent emits "ADVENTURE" in banner.
        child.expect("ADVENTURE", timeout=8)
        _snapshot(child, "01_banner")

        # Give the status line a moment to settle, then type "north".
        time.sleep(0.4)
        child.send("north\r")
        child.expect("End Of Road|north|You.*cannot|Forest", timeout=4)
        _snapshot(child, "02_north")

        # Type "inventory" to trigger the inventory-capture panel path.
        time.sleep(0.3)
        child.send("inventory\r")
        child.expect("You are (carrying|empty-handed)", timeout=4)
        _snapshot(child, "03_inventory")

        # Quit cleanly via Ctrl-C.
        time.sleep(0.3)
        child.sendcontrol("c")
        child.expect(pexpect.EOF, timeout=4)
        print("playtest: PASS")
        return 0
    except pexpect.TIMEOUT as e:
        _snapshot(child, "99_timeout")
        print(f"playtest: TIMEOUT — {e}")
        return 2
    except pexpect.EOF as e:
        _snapshot(child, "99_eof")
        print(f"playtest: EOF — {e}")
        return 3
    finally:
        try:
            child.close(force=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
