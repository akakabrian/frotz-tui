"""Auto-mapper — build a graph of visited rooms from status-line changes.

We observe: every turn, dfrotz prints a status line with the current room
name. When the player's typed command is a known movement direction and
the post-command room name differs from the previous one, we add a
directed edge. We keep a small grid layout for rendering.

No layout is optimal without solving a force-directed layout problem; we
just grid-place by first-seen offset and hope the game's geography lines
up. Adventure games are rough graphs anyway; perfect layout isn't the
goal — reminding the player which exits they've already taken is.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Canonical direction names → (dx, dy) grid offset.
# y grows downward (typical terminal orientation).
DIRECTIONS: dict[str, tuple[int, int]] = {
    "n":  (0, -1), "north":      (0, -1),
    "s":  (0,  1), "south":      (0,  1),
    "e":  (1,  0), "east":       (1,  0),
    "w": (-1,  0), "west":      (-1,  0),
    "ne": (1, -1), "northeast":  (1, -1),
    "nw": (-1, -1), "northwest": (-1, -1),
    "se": (1,  1), "southeast":  (1,  1),
    "sw": (-1,  1), "southwest": (-1,  1),
    "u":  (0, -2), "up":         (0, -2),
    "d":  (0,  2), "down":       (0,  2),
    "in":  (0, 0), "out":        (0, 0),   # no grid offset; we just record the edge
    "enter": (0, 0), "exit":     (0, 0),
}

REVERSE: dict[str, str] = {
    "n": "s", "s": "n", "e": "w", "w": "e",
    "ne": "sw", "sw": "ne", "nw": "se", "se": "nw",
    "u": "d", "d": "u", "in": "out", "out": "in",
}


def canonical_direction(cmd: str) -> str | None:
    """If `cmd` is a movement command, return its canonical short form
    (n/s/e/w/ne/.../u/d/in/out). Otherwise return None."""
    c = cmd.strip().lower()
    # Strip leading articles / "go".
    for prefix in ("go ", "walk ", "run "):
        if c.startswith(prefix):
            c = c[len(prefix):].strip()
    if c in DIRECTIONS:
        # Normalize to short form for consistency in the graph.
        short = {
            "north": "n", "south": "s", "east": "e", "west": "w",
            "northeast": "ne", "northwest": "nw",
            "southeast": "se", "southwest": "sw",
            "up": "u", "down": "d",
            "enter": "in", "exit": "out",
        }.get(c, c)
        return short
    return None


@dataclass
class Room:
    name: str
    x: int
    y: int
    exits: dict[str, str] = field(default_factory=dict)  # dir -> neighbor room name


@dataclass
class Mapper:
    rooms: dict[str, Room] = field(default_factory=dict)
    current: str | None = None
    _pending_direction: str | None = None

    def note_command(self, cmd: str) -> None:
        """Called before each player command is sent. Records whether it's
        a movement, so the next status-line change can be linked to it."""
        self._pending_direction = canonical_direction(cmd)

    def note_room(self, room_name: str) -> None:
        """Called each time a status-line update arrives with a room name.
        Creates the room on first sight, and if we had a pending direction
        from a movement command, wires up an edge."""
        if not room_name:
            return
        if room_name not in self.rooms:
            # Place relative to current room if we have one + a direction.
            if (
                self.current is not None
                and self._pending_direction is not None
                and self._pending_direction in DIRECTIONS
            ):
                base = self.rooms[self.current]
                dx, dy = DIRECTIONS[self._pending_direction]
                # If target cell is occupied, shift by (1, 1) until free.
                # This is dumb but keeps rooms visually separated.
                nx, ny = base.x + dx, base.y + dy
                occupied = {(r.x, r.y) for r in self.rooms.values()}
                shift = 0
                while (nx, ny) in occupied and shift < 10:
                    shift += 1
                    nx += 1
                    ny += 1
                self.rooms[room_name] = Room(name=room_name, x=nx, y=ny)
            else:
                # First room or non-movement arrival — put at origin if free.
                origin_free = not any(
                    r.x == 0 and r.y == 0 for r in self.rooms.values()
                )
                if origin_free:
                    self.rooms[room_name] = Room(name=room_name, x=0, y=0)
                else:
                    # Place just below the lowest known room.
                    max_y = max(r.y for r in self.rooms.values())
                    self.rooms[room_name] = Room(
                        name=room_name, x=0, y=max_y + 1
                    )
        # Wire edge if direction known and room transitioned.
        if (
            self.current is not None
            and self._pending_direction is not None
            and room_name != self.current
            and self._pending_direction in DIRECTIONS
        ):
            prev = self.rooms[self.current]
            prev.exits[self._pending_direction] = room_name
            # Add reverse edge if not already known — games are usually
            # symmetric, and this helps when the player backs up.
            if self._pending_direction in REVERSE:
                rev = REVERSE[self._pending_direction]
                cur = self.rooms[room_name]
                cur.exits.setdefault(rev, self.current)
        self.current = room_name
        self._pending_direction = None

    # ---------- rendering ----------

    def render(self, viewport_w: int = 26, viewport_h: int = 18) -> list[str]:
        """Produce a list of text lines showing the map around the current
        room. Uses tiny abbreviations (first letter of each word, up to 3
        chars) for room labels, with `*` marking the current location."""
        if not self.rooms:
            return ["(no rooms visited yet)"]

        cx, cy = (0, 0)
        if self.current and self.current in self.rooms:
            cur = self.rooms[self.current]
            cx, cy = cur.x, cur.y

        # Build a dense grid then slice a viewport centered on current.
        # Use half-width so two chars fit per tile (" AB ").
        cell_w = 5    # " XYZ "
        cell_h = 2    # room row + connector row

        # Each grid cell (x, y) → abbrev string (≤3 chars) + is_current flag.
        placed: dict[tuple[int, int], tuple[str, bool]] = {}
        for r in self.rooms.values():
            abbrev = _abbrev(r.name)
            placed[(r.x, r.y)] = (abbrev, r.name == self.current)

        # Compute which cells are visible given viewport center.
        half_w = (viewport_w // cell_w) // 2
        half_h = (viewport_h // cell_h) // 2
        x_min, x_max = cx - half_w, cx + half_w
        y_min, y_max = cy - half_h, cy + half_h

        lines: list[str] = []
        for gy in range(y_min, y_max + 1):
            # Row 1: rooms.
            row = ""
            for gx in range(x_min, x_max + 1):
                if (gx, gy) in placed:
                    abbrev, is_current = placed[(gx, gy)]
                    if is_current:
                        row += f"[{abbrev:^3}]"
                    else:
                        row += f" {abbrev:^3} "
                else:
                    row += " " * cell_w
            lines.append(row[:viewport_w])
            # Row 2: n/s connectors.
            conn = ""
            for gx in range(x_min, x_max + 1):
                room_here = _find_room_at(self.rooms, gx, gy)
                has_s = bool(room_here and "s" in room_here.exits)
                has_e = bool(room_here and "e" in room_here.exits)
                # east connector between this cell and next
                conn += "  " + ("|" if has_s else " ") + "  "
                # overwrite last char with east link if we need one
                if has_e:
                    conn = conn[:-1] + "-"
            lines.append(conn[:viewport_w])
        return lines


def _abbrev(name: str) -> str:
    """Compact a room name into <=3 letters by taking initial letters of
    each word, or the first 3 chars of a single word."""
    words = [w for w in name.replace("-", " ").split() if w]
    if not words:
        return "???"
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words[:3]).upper()


def _find_room_at(rooms: dict[str, Room], x: int, y: int) -> Room | None:
    for r in rooms.values():
        if r.x == x and r.y == y:
            return r
    return None
