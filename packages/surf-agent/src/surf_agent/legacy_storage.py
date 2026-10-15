"""Find and move files left at the pre-``~/.agents`` platformdirs locations.

Temporary: delete this module, its callers and the platformdirs dependency once
existing installs have migrated. Runtime code only detects legacy files and
fails fast; moving them is an explicit command so logins never move silently.
"""

from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs

from .backends import PatchrightBridgeClient
from .chrome_lifecycle import find_active_chrome_roots
from .constants import DEFAULT_PATCHRIGHT_PORT
from .errors import SurfAgentError
from .session import kill_sessions_in, session_socket_dir
from .runtime import (
    APP_NAME,
    parse_port_env,
    surf_agent_config_dir,
    surf_agent_home,
    surf_agent_state_dir,
)

# Where releases before the ~/.agents root could have written. platformdirs
# honors XDG_* on macOS too, so the same install used the XDG folders or
# Application Support depending on the environment Surf ran in; check both,
# and let the path active in the current environment win.
LEGACY_DIRS = PlatformDirs(APP_NAME, appauthor=False)
XDG_DEFAULT_ROOTS = {"config": ".config", "state": ".local/state", "data": ".local/share"}
MACOS_APP_SUPPORT = "Library/Application Support"
LEGACY_PROFILES = "profiles"
STOP_BRIDGE_TIMEOUT_S = 30.0

MIGRATION_COMMAND = """python3 "$BROWSER_SKILL/scripts/run.py" - <<'PY'
from surf_agent.legacy_storage import migrate_legacy_storage
migrate_legacy_storage()
PY"""


class LegacyStorageError(SurfAgentError):
    """Surf files remain at their pre-``~/.agents`` locations."""


@dataclass(frozen=True)
class LegacyItem:
    candidates: tuple[Path, ...]
    target: Path

    @property
    def found(self) -> list[Path]:
        return [path for path in self.candidates if path.exists()]

    @property
    def active(self) -> Path | None:
        """The copy to move: the active path wins, so other copies are stale.

        An existing target is already active. Otherwise the first candidate is
        what platformdirs resolves in this environment; fall back to whichever
        copy exists.
        """
        if self.target.exists():
            return None
        return next(iter(self.found), None)


def _legacy_roots(kind: str) -> list[Path]:
    resolved = {
        "config": LEGACY_DIRS.user_config_dir,
        "state": LEGACY_DIRS.user_state_dir,
        "data": LEGACY_DIRS.user_data_dir,
    }[kind]
    home = Path.home()
    candidates = [
        Path(resolved),
        home / XDG_DEFAULT_ROOTS[kind] / APP_NAME,
        home / MACOS_APP_SUPPORT / APP_NAME,
    ]
    return list(dict.fromkeys(candidates))


def _candidates(kind: str, name: str) -> tuple[Path, ...]:
    return tuple(root / name for root in _legacy_roots(kind))


def legacy_items() -> list[LegacyItem]:
    """The files worth keeping that the current overrides still default, paired with their new location."""
    if surf_agent_home():
        # An explicit home never used the platformdirs layout.
        return []
    items = [
        LegacyItem(_candidates("config", "config.json"), surf_agent_config_dir() / "config.json"),
        LegacyItem(_candidates("state", "cookie-import.json"), surf_agent_state_dir() / "cookie-import.json"),
    ]
    if not os.environ.get("SURF_AGENT_PROFILE_DIR"):
        items.append(LegacyItem(_candidates("data", LEGACY_PROFILES), surf_agent_state_dir() / LEGACY_PROFILES))
    return items


def pending_legacy_items() -> list[LegacyItem]:
    return [item for item in legacy_items() if item.active is not None]


def check_legacy_storage() -> None:
    """Fail fast instead of silently starting a fresh, logged-out profile."""
    listing = "\n".join(f"  {item.active} -> {item.target}" for item in pending_legacy_items())
    if not listing:
        return
    raise LegacyStorageError(
        "Surf files are still at their old location:\n"
        f"{listing}\n"
        "Move them with the command below. It ends running Surf sessions and closes "
        "a Surf browser left by the previous version.\n"
        f"{MIGRATION_COMMAND}"
    )


def migrate_legacy_storage() -> None:
    """Move legacy config, cookie-import state and profiles into the ~/.agents root.

    Safe to re-run: each item moves only while its target is absent, so an
    interrupted run finishes on the next one and nothing is nested or replaced.
    Copies that lose to the active path stay where they are, unmentioned.
    """
    if surf_agent_home():
        raise SurfAgentError("SURF_AGENT_HOME is set; the migration only moves the default layout")
    pending = pending_legacy_items()
    if not pending:
        print("Nothing to migrate.")
    else:
        _end_sessions()
    for item in pending:
        legacy = item.active
        if legacy.name == LEGACY_PROFILES:
            _stop_legacy_browser(legacy / "chrome")
        item.target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(legacy, item.target)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            # Copying a multi-gigabyte profile is not this command's job.
            raise SurfAgentError(
                f"{legacy} is on a different filesystem from {item.target}; "
                "move it manually, then re-run the migration"
            ) from exc
        print(f"Moved {legacy} -> {item.target}")
    # Unpicked copies and items an override leaves behind stay untouched, and
    # so does any folder holding one.
    kept = [
        path
        for kind, name in (("config", "config.json"), ("state", "cookie-import.json"), ("data", LEGACY_PROFILES))
        for path in _candidates(kind, name)
        if path.exists()
    ]
    leftovers = sorted(
        {
            root
            for kind in XDG_DEFAULT_ROOTS
            for root in _legacy_roots(kind)
            if root.exists() and not any(path.is_relative_to(root) for path in kept)
        }
    )
    if leftovers:
        print("Once Surf works from the new location, trash the old folders:")
        for root in leftovers:
            print(f"  {root}")


def _end_sessions() -> None:
    """End sessions that could still run the previous version against legacy paths.

    Without XDG_RUNTIME_DIR, the previous version kept its sockets under the
    legacy state folder, where the current launcher cannot list them.
    """
    legacy_socket_dirs = {root / APP_NAME for root in _legacy_roots("state")}
    for directory in {session_socket_dir(), *legacy_socket_dirs}:
        kill_sessions_in(directory)


def _stop_legacy_browser(profile_dir: Path) -> None:
    """Stop a bridge left on the legacy profile; refuse if Chrome still uses it."""
    if not profile_dir.exists():
        return
    client = PatchrightBridgeClient(
        timeout_s=STOP_BRIDGE_TIMEOUT_S,
        port=parse_port_env("SURF_AGENT_PORT", DEFAULT_PATCHRIGHT_PORT),
        profile_dir=profile_dir,
    )
    client.stop()
    active = find_active_chrome_roots(profile_dir)
    if active:
        raise SurfAgentError(
            f"Chrome is still using {profile_dir} (pids {', '.join(map(str, active))}); "
            "close it, then re-run the migration"
        )
