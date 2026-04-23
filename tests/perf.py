"""Hot-path benchmarks for frotz-tui.

Run:
    .venv/bin/python -m tests.perf

Frotz-tui's hot paths are tiny compared to SimCity — no zero-copy FFI,
just subprocess I/O and line parsing. We benchmark:

1. `parse_status_line` throughput
2. `classify_line` on a mixed corpus
3. `Mapper.note_room` scaling (1k rooms)
4. `Mapper.render` at realistic size
5. End-to-end: spawn dfrotz, pipe 50 commands, teardown
"""

from __future__ import annotations

import time
from pathlib import Path

from frotz_tui.engine import (
    FrotzEngine,
    classify_line,
    parse_status_line,
)
from frotz_tui.mapper import Mapper


REPO = Path(__file__).resolve().parent.parent
DFROTZ = REPO / "engine" / "dfrotz"
STORY = REPO / "stories" / "advent.z5"


def _time(label: str, fn, iterations: int = 1) -> float:
    t0 = time.perf_counter()
    for _ in range(iterations):
        fn()
    dt = (time.perf_counter() - t0) / iterations
    print(f"  {label:<50} {dt*1000:8.3f} ms / call  "
          f"({1/dt if dt > 0 else float('inf'):.0f} /s)")
    return dt


def bench_status_parser() -> None:
    print("== status line parser ==")
    good = " At End Of Road                              Score: 36    Moves: 12"
    junk = "You are carrying nothing."
    mixed = [good, junk, good, junk, " Dark Room   Score: -1  Moves: 99"]

    def hit():
        for _ in range(1000):
            parse_status_line(good)

    def miss():
        for _ in range(1000):
            parse_status_line(junk)

    def batch():
        for _ in range(1000):
            for ln in mixed:
                classify_line(ln)

    _time("parse_status_line hit   × 1000", hit)
    _time("parse_status_line miss  × 1000", miss)
    _time("classify_line batch(5)  × 1000", batch)


def bench_mapper() -> None:
    print("\n== mapper ==")

    def note_many():
        m = Mapper()
        m.note_room("Room 0")
        for i in range(1, 200):
            m.note_command("e" if i & 1 else "n")
            m.note_room(f"Room {i}")

    def render_200():
        m = Mapper()
        m.note_room("Room 0")
        for i in range(1, 200):
            m.note_command("e" if i & 1 else "n")
            m.note_room(f"Room {i}")
        m.render(viewport_w=40, viewport_h=30)

    _time("note_room × 200 (with edges)", note_many)
    _time("render 40×30 viewport, 200 rooms", render_200)


def bench_end_to_end() -> None:
    print("\n== end-to-end: dfrotz subprocess, 50 commands ==")
    if not DFROTZ.exists():
        print(f"  skipped: {DFROTZ} not built")
        return

    engine = FrotzEngine(str(DFROTZ), str(STORY))

    t0 = time.perf_counter()
    engine.start()
    # Drain startup output.
    deadline = time.perf_counter() + 2.0
    total_lines = 0
    while time.perf_counter() < deadline:
        lines = engine.read_available()
        total_lines += len(lines)
        if lines and any("End Of Road" in ln for ln in lines):
            break
        time.sleep(0.02)
    start_dt = time.perf_counter() - t0
    print(f"  boot + drain startup ({total_lines} lines): {start_dt*1000:.1f} ms")

    commands = ["look", "east", "west", "east", "take lamp", "inventory",
                "west", "south", "north"] * 5 + ["look"] * 5
    cmd_start = time.perf_counter()
    cmd_lines = 0
    for cmd in commands:
        engine.send(cmd)
        # Wait briefly for response.
        burst_start = time.perf_counter()
        while time.perf_counter() - burst_start < 0.15:
            lines = engine.read_available()
            cmd_lines += len(lines)
            if lines:
                # Keep reading for another short window to drain.
                while True:
                    time.sleep(0.005)
                    more = engine.read_available()
                    if not more:
                        break
                    cmd_lines += len(more)
                break
            time.sleep(0.005)
    cmd_dt = time.perf_counter() - cmd_start
    print(f"  {len(commands)} commands, {cmd_lines} response lines: "
          f"{cmd_dt*1000:.1f} ms  ({cmd_dt/len(commands)*1000:.2f} ms/cmd)")

    stop0 = time.perf_counter()
    engine.stop()
    print(f"  shutdown: {(time.perf_counter() - stop0)*1000:.1f} ms")


def main() -> None:
    bench_status_parser()
    bench_mapper()
    bench_end_to_end()


if __name__ == "__main__":
    main()
