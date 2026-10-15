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

# The layout every release before the ~/.agents root used. On macOS all three
# roots are the same Application Support folder.
LEGACY_DIRS = PlatformDirs(APP_NAME, appauthor=False)
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
    legacy: Path
    target: Path

    @property
    def pending(self) -> bool:
        return self.legacy.exists() and not self.target.exists()

    @property
    def conflicting(self) -> bool:
        return self.legacy.exists() and self.target.exists()


def _legacy_config() -> Path:
    return Path(LEGACY_DIRS.user_config_dir) / "config.json"


def _legacy_cookie_import() -> Path:
    return Path(LEGACY_DIRS.user_state_dir) / "cookie-import.json"


def _legacy_profiles() -> Path:
    return Path(LEGACY_DIRS.user_data_dir) / LEGACY_PROFILES


def legacy_items() -> list[LegacyItem]:
    """The files worth keeping that the current overrides still default, paired with their new location."""
    if surf_agent_home():
        # An explicit home never used the platformdirs layout.
        return []
    items = [
        LegacyItem(_legacy_config(), surf_agent_config_dir() / "config.json"),
        LegacyItem(_legacy_cookie_import(), surf_agent_state_dir() / "cookie-import.json"),
    ]
    if not os.environ.get("SURF_AGENT_PROFILE_DIR"):
        items.append(LegacyItem(_legacy_profiles(), surf_agent_state_dir() / LEGACY_PROFILES))
    return items


def pending_legacy_items() -> list[LegacyItem]:
    return [item for item in legacy_items() if item.pending]


def check_legacy_storage() -> None:
    """Fail fast instead of silently starting a fresh, logged-out profile.

    Refuses while any legacy item exists, even when its target exists too:
    two profiles mean one would be ignored, and only the user knows which.
    """
    remaining = [item for item in legacy_items() if item.legacy.exists()]
    if not remaining:
        return
    listing = "\n".join(f"  {item.legacy} -> {item.target}" for item in remaining)
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
    """
    if surf_agent_home():
        raise SurfAgentError("SURF_AGENT_HOME is set; the migration only moves the default layout")
    conflicts = [item for item in legacy_items() if item.conflicting]
    if conflicts:
        listing = "\n".join(f"  old: {item.legacy}\n  new: {item.target}" for item in conflicts)
        raise SurfAgentError(
            "These exist at both the old and the new location:\n"
            f"{listing}\n"
            "Keep the one holding your data (for a profile, the one you are logged in with), "
            "trash the other, then re-run the migration"
        )
    pending = pending_legacy_items()
    if not pending:
        print("Nothing to migrate.")
    else:
        _end_sessions()
    for item in pending:
        if item.legacy.name == LEGACY_PROFILES:
            _stop_legacy_browser(item.legacy / "chrome")
        item.target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(item.legacy, item.target)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            # Copying a multi-gigabyte profile is not this command's job.
            raise SurfAgentError(
                f"{item.legacy} is on a different filesystem from {item.target}; "
                "move it manually, then re-run the migration"
            ) from exc
        print(f"Moved {item.legacy} -> {item.target}")
    # Checked without overrides: SURF_AGENT_PROFILE_DIR leaves the legacy profile
    # in place, and its folder must not be offered for trashing.
    kept = [path for path in (_legacy_config(), _legacy_cookie_import(), _legacy_profiles()) if path.exists()]
    leftovers = sorted(
        {
            Path(root)
            for root in (
                LEGACY_DIRS.user_config_dir,
                LEGACY_DIRS.user_state_dir,
                LEGACY_DIRS.user_data_dir,
            )
            if Path(root).exists() and not any(path.is_relative_to(root) for path in kept)
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
    legacy_socket_dir = Path(LEGACY_DIRS.user_state_dir) / APP_NAME
    for directory in {session_socket_dir(), legacy_socket_dir}:
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
