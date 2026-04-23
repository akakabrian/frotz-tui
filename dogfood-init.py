"""dogfood-init.py — App factory for tui-dogfood.

The tui-dogfood framework looks for this file at <game>/dogfood-init.py.
If it defines ``make_app() -> App``, that factory is used instead of the
default zero-arg ``App()`` construction (which fails for FrotzApp because
it requires story_path and dfrotz_path).
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Resolve paths relative to this file so the factory works regardless of
# the working directory the runner is launched from.
_HERE = Path(__file__).resolve().parent
_STORIES_DIR = _HERE / "stories"
_ENGINE_DIR = _HERE / "engine"

_DEFAULT_STORY = _STORIES_DIR / "advent.z5"
_BUNDLED_DFROTZ = _ENGINE_DIR / "dfrotz"


def _find_dfrotz() -> str:
    """Return an absolute path to dfrotz.

    Preference order:
    1. Bundled binary at <game>/engine/dfrotz
    2. dfrotz on $PATH
    """
    if _BUNDLED_DFROTZ.exists():
        return str(_BUNDLED_DFROTZ)
    found = shutil.which("dfrotz")
    if found:
        return found
    raise FileNotFoundError(
        "dfrotz not found: expected at "
        f"{_BUNDLED_DFROTZ} or on $PATH"
    )


def make_app():
    """Return a FrotzApp instance loaded with the bundled Advent.z5 story."""
    # Import lazily so the module can be loaded even before the game's
    # package is on sys.path; the framework inserts the game root before
    # calling make_app().
    from frotz_tui.app import FrotzApp  # noqa: PLC0415

    return FrotzApp(
        story_path=str(_DEFAULT_STORY),
        dfrotz_path=_find_dfrotz(),
    )
