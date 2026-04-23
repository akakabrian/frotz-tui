"""FrotzEngine — subprocess wrapper around dfrotz.

dfrotz is Frotz's "dumb" frontend: a plain stdin/stdout Z-machine
interpreter. We spawn it once, pump lines of game output out on a reader
thread into an async queue, and write the player's commands to stdin.

The engine is completely decoupled from Textual — unit-testable in
isolation, and the app only calls a narrow surface: `start()`, `send()`,
`read_available()`, `stop()`.

Key parsing responsibilities live here so the UI layer stays thin:

- `parse_status_line(line)` detects the z-machine status line
  (`<Room>   Score: N   Moves: N`) and returns a StatusLine dataclass
  when it matches, None otherwise.
- `classify_line(line)` is the top-level dispatcher: given a raw line
  from dfrotz, returns either (`"status", StatusLine`) or
  (`"text", line)`. The app uses this to route text to the transcript
  and status updates to the status panel.
"""

from __future__ import annotations

import os
import queue
import re
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class StatusLine:
    """Parsed z-machine status bar."""
    room: str
    score: int
    moves: int


# Z-machine status line: <Location>  Score: N   Moves: N
# The location is left-justified, the score+moves right-justified; dfrotz
# pads with spaces. Accept at least one whitespace between fields, optional
# leading/trailing whitespace, and score may be negative (some games
# deduct points).
_STATUS_RE = re.compile(
    r"^\s*(\S.*?\S|\S)\s{2,}Score:\s*(-?\d+)\s+Moves:\s*(\d+)\s*$"
)

# v4+ games use a "Time: HH:MM" status instead of score — support both.
_STATUS_TIME_RE = re.compile(
    r"^\s*(\S.*?\S|\S)\s{2,}Time:\s*(\d+:\d+)\s*$"
)


def _strip_prompt(s: str) -> str:
    """dfrotz prefixes the status line with the last-prompt character
    (usually '>') because of the way the interleaved split window flushes.
    Strip a leading '>' plus trailing whitespace from the room name."""
    s = s.strip()
    if s.startswith(">"):
        s = s[1:].lstrip()
    return s


def parse_status_line(line: str) -> StatusLine | None:
    """If `line` looks like a z-machine status bar, return a StatusLine.
    Otherwise return None. Accepts both Score/Moves and Time variants."""
    m = _STATUS_RE.match(line)
    if m:
        room = _strip_prompt(m.group(1))
        if not room:
            return None
        try:
            return StatusLine(room=room, score=int(m.group(2)),
                              moves=int(m.group(3)))
        except ValueError:
            return None
    m = _STATUS_TIME_RE.match(line)
    if m:
        room = _strip_prompt(m.group(1))
        if not room:
            return None
        # For v4 games we show the time tacked on the room; score/moves 0.
        return StatusLine(room=f"{room} [{m.group(2)}]",
                          score=0, moves=0)
    return None


def classify_line(line: str) -> tuple[str, object]:
    """Classify a line as a status update or plain transcript text."""
    st = parse_status_line(line)
    if st is not None:
        return ("status", st)
    return ("text", line)


class FrotzEngine:
    """Spawns and talks to a single dfrotz subprocess.

    Threading model: dfrotz's stdout is blocking, so we pump it on a
    background daemon thread into a thread-safe queue. The TUI main loop
    polls `read_available()` (non-blocking) on each tick. Writes on the
    main thread flush stdin and are seen by dfrotz promptly (dfrotz uses
    line-buffered stdin).
    """

    def __init__(self, dfrotz_path: str | os.PathLike,
                 story_path: str | os.PathLike,
                 width: int = 80, height: int = 24) -> None:
        self.dfrotz_path = Path(dfrotz_path)
        self.story_path = Path(story_path)
        self.width = width
        self.height = height
        self._proc: subprocess.Popen[str] | None = None
        self._out_q: queue.Queue[str] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._stopping = False

    # ---------- lifecycle ----------

    def start(self) -> None:
        if not self.dfrotz_path.exists():
            raise FileNotFoundError(
                f"dfrotz not found at {self.dfrotz_path} — run `make engine`"
            )
        if not self.story_path.exists():
            raise FileNotFoundError(f"story file not found: {self.story_path}")

        cmd = [
            str(self.dfrotz_path),
            "-p",                    # plain ASCII, no format codes
            "-m",                    # suppress MORE prompts
            "-w", str(self.width),
            "-h", str(self.height),
            str(self.story_path),
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,               # line-buffered on our side
            # Detach from the controlling terminal so Ctrl-C to our TUI
            # doesn't deliver SIGINT to dfrotz (which would kill it).
            start_new_session=True,
        )
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="frotz-reader", daemon=True
        )
        self._reader_thread.start()

    def _reader_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            for line in self._proc.stdout:
                if self._stopping:
                    break
                # Strip trailing newline only; keep leading whitespace
                # (z-machine status bar is padded with leading spaces).
                self._out_q.put(line.rstrip("\n"))
        except Exception as e:
            self._out_q.put(f"[engine error] {e!r}")
        finally:
            self._out_q.put("__EOF__")

    def stop(self) -> None:
        self._stopping = True
        p = self._proc
        if p is None:
            return
        try:
            if p.poll() is None:
                # Skip the graceful-quit wait: dfrotz doesn't always honour
                # `\q` while mid-prompt, and we don't need its bookkeeping.
                # Straight to SIGTERM, then SIGKILL.
                p.terminate()
                try:
                    p.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    p.kill()
                    try:
                        p.wait(timeout=0.2)
                    except subprocess.TimeoutExpired:
                        pass
        finally:
            if p.stdin:
                try:
                    p.stdin.close()
                except Exception:
                    pass
            self._proc = None

    # ---------- I/O ----------

    def send(self, command: str) -> None:
        """Send a single player command. Adds newline; caller should not."""
        p = self._proc
        if p is None or p.stdin is None or p.stdin.closed:
            raise RuntimeError("engine is not running")
        try:
            p.stdin.write(command.rstrip("\n") + "\n")
            p.stdin.flush()
        except BrokenPipeError:
            raise RuntimeError("dfrotz has exited") from None

    def read_available(self) -> list[str]:
        """Drain the output queue without blocking. Returns a list (possibly
        empty) of raw lines produced by dfrotz since the last call."""
        out: list[str] = []
        while True:
            try:
                line = self._out_q.get_nowait()
            except queue.Empty:
                break
            out.append(line)
        return out

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ---------- helpers ----------

    def classify_batch(self, lines: Iterable[str]) -> list[tuple[str, object]]:
        return [classify_line(ln) for ln in lines]
