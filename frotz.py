"""Entry point — `python frotz.py [story-file]`."""

from __future__ import annotations

import argparse
from pathlib import Path

from frotz_tui.app import run


REPO = Path(__file__).resolve().parent
DEFAULT_STORY = REPO / "stories" / "advent.z5"


def main() -> None:
    p = argparse.ArgumentParser(prog="frotz-tui")
    p.add_argument(
        "story",
        nargs="?",
        default=str(DEFAULT_STORY),
        help=f"path to a .z3/.z5/.z8 story file (default: {DEFAULT_STORY.name})",
    )
    p.add_argument(
        "--dfrotz",
        default=str(REPO / "engine" / "dfrotz"),
        help="path to the dfrotz binary",
    )
    args = p.parse_args()
    run(story_path=args.story, dfrotz_path=args.dfrotz)


if __name__ == "__main__":
    main()
