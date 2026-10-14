"""Browser zoom saved in the Surf profile, cleared before Chrome starts.

Under any zoom but 100%, Patchright's CSS-scale screenshots show only the top-left
part of the viewport, and nothing once the page is scrolled (#31). CDP has no
command to change browser zoom, and synthetic Ctrl+0 never reaches Chrome's
shortcuts, so Surf resets it in the profile file before launch.
"""

from __future__ import annotations

import json
from pathlib import Path

from ...config import write_config
from ...constants import CHROME_PROFILE_DIRECTORY

# Chrome keeps both under `partition`, each keyed by storage partition:
# default_zoom_level.<partition> and per_host_zoom_levels.<partition>.<host>.
SAVED_ZOOM_PREFERENCES = ("default_zoom_level", "per_host_zoom_levels")


def clear_saved_zoom(profile_dir: Path) -> None:
    """Drop the profile's default and per-site zoom so pages open at 100%.

    Call only while Chrome is not running on the profile: a running Chrome keeps
    its zoom in memory and writes it back.
    """
    preferences_path = profile_dir / CHROME_PROFILE_DIRECTORY / "Preferences"
    if not preferences_path.exists():
        return
    try:
        preferences = json.loads(preferences_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Chrome sets an unreadable Preferences file aside and starts from defaults,
        # so there is no saved zoom left to clear.
        return
    partition = preferences.get("partition", {})
    saved = [key for key in SAVED_ZOOM_PREFERENCES if key in partition]
    if not saved:
        return
    for key in saved:
        del partition[key]
    write_config(preferences_path, preferences)
