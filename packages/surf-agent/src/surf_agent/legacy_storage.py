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


def legacy_items() -> list[LegacyItem]:
    """The files worth keeping, paired with their new location."""
    if surf_agent_home():
        # An explicit home never used the platformdirs layout.
        return []
    items = [
        LegacyItem(
            Path(LEGACY_DIRS.user_config_dir) / "config.json",
            surf_agent_config_dir() / "config.json",
        ),
        LegacyItem(
            Path(LEGACY_DIRS.user_state_dir) / "cookie-import.json",
            surf_agent_state_dir() / "cookie-import.json",
        ),
    ]
    if not os.environ.get("SURF_AGENT_PROFILE_DIR"):
        items.append(
            LegacyItem(
                Path(LEGACY_DIRS.user_data_dir) / LEGACY_PROFILES,
                surf_agent_state_dir() / LEGACY_PROFILES,
            )
        )
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
    raise SurfAgentError(
        "Surf files are still at their old location:\n"
        f"{listing}\n"
        "Kill sessions started by the previous Surf version, then move them with:\n"
        f"{MIGRATION_COMMAND}"
    )


def migrate_legacy_storage() -> None:
    """Move legacy config, cookie-import state and profiles into the ~/.agents root.

    Safe to re-run: each item moves only while its target is absent, so an
    interrupted run finishes on the next one and nothing is nested or replaced.
    """
    conflicts = [item for item in legacy_items() if item.conflicting]
    if conflicts:
        listing = "\n".join(f"  {item.legacy}\n  {item.target}" for item in conflicts)
        raise SurfAgentError(
            "These exist at both the old and the new location:\n"
            f"{listing}\n"
            "Keep one of each pair, trash the other, then re-run the migration"
        )
    pending = pending_legacy_items()
    if not pending:
        print("Nothing to migrate.")
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
    leftovers = sorted(
        {
            Path(root)
            for root in (
                LEGACY_DIRS.user_config_dir,
                LEGACY_DIRS.user_state_dir,
                LEGACY_DIRS.user_data_dir,
            )
            if Path(root).exists()
        }
    )
    if leftovers:
        print("Once Surf works from the new location, trash the old folders:")
        for root in leftovers:
            print(f"  {root}")


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
