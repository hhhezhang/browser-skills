"""Storage layout under ~/.agents and the explicit move from the old platformdirs layout.

Written from the requirements: Surf keeps config in ~/.agents/config/surf-agent and
everything it writes (profile included) in ~/.agents/state/surf-agent on every OS;
it refuses to start while files remain at the old locations, and an explicit,
re-runnable command moves them.
"""

from __future__ import annotations

import errno
import os
import socket
from pathlib import Path

import platformdirs.macos
import pytest

import surf_agent.backends.patchright.bridge as bridge
import surf_agent.legacy_storage as legacy_storage
from surf_agent import Browser, SurfAgentError, Thread
from surf_agent.legacy_storage import check_legacy_storage, migrate_legacy_storage
from surf_agent.runtime import (
    SurfAgent,
    default_patchright_profile_dir,
    surf_agent_config_dir,
    surf_agent_state_dir,
)

# conftest replaces runtime.config_file per test; this import runs at collection
# time, so it holds the real function.
from surf_agent.runtime import config_file

PROFILE_MARKER = Path("chrome") / "Default" / "Cookies"


@pytest.fixture(autouse=True)
def unused_bridge_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """The migration asks a legacy bridge to stop; never reach a real one."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setenv("SURF_AGENT_PORT", str(port))
    for variable in ("SURF_AGENT_HOME", "SURF_AGENT_PROFILE_DIR", "SURF_AGENT_CHROME_BIN"):
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture(autouse=True)
def no_running_chrome(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real process list could hold the user's Chrome; tests opt into fakes."""
    monkeypatch.setattr("surf_agent.chrome_lifecycle.iter_process_args", lambda: [])


def home() -> Path:
    return Path(os.environ["HOME"])


def new_config_dir() -> Path:
    return home() / ".agents" / "config" / "surf-agent"


def new_state_dir() -> Path:
    return home() / ".agents" / "state" / "surf-agent"


def linux_legacy() -> dict[str, Path]:
    return {
        "config": home() / ".config" / "surf-agent" / "config.json",
        "cookie_import": home() / ".local" / "state" / "surf-agent" / "cookie-import.json",
        "profiles": home() / ".local" / "share" / "surf-agent" / "profiles",
    }


def macos_legacy() -> dict[str, Path]:
    root = home() / "Library" / "Application Support" / "surf-agent"
    return {
        "config": root / "config.json",
        "cookie_import": root / "cookie-import.json",
        "profiles": root / "profiles",
    }


def new_targets() -> dict[str, Path]:
    return {
        "config": new_config_dir() / "config.json",
        "cookie_import": new_state_dir() / "cookie-import.json",
        "profiles": new_state_dir() / "profiles",
    }


def plant(paths: dict[str, Path], kinds=("config", "cookie_import", "profiles")) -> None:
    for kind in kinds:
        path = paths[kind]
        if kind == "profiles":
            marker = path / PROFILE_MARKER
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(f"legacy {kind}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'{{"legacy": "{kind}"}}')


def content(kind: str, path: Path) -> str:
    return (path / PROFILE_MARKER).read_text() if kind == "profiles" else path.read_text()


@pytest.fixture
def simulate_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Have the old-layout lookup decide as platformdirs does on macOS.

    Patches the legacy PlatformDirs instance only; the new layout must not
    depend on the platform at all.
    """
    monkeypatch.setattr(
        legacy_storage, "LEGACY_DIRS", platformdirs.macos.MacOS("surf-agent", appauthor=False)
    )


@pytest.fixture
def bridge_profiles(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Run bridge.main without Chrome or a socket; record the profile it would open."""
    constructed: list[Path] = []

    class FakeRuntime:
        def __init__(self, *, profile_dir, **_kwargs):
            constructed.append(profile_dir)

        def stop(self):
            return ""

    class FakeServer:
        def __init__(self, *_args, **_kwargs):
            pass

        def serve_forever(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(bridge, "PatchrightRuntime", FakeRuntime)
    monkeypatch.setattr(bridge, "PatchrightHTTPServer", FakeServer)
    return constructed


# --- layout -----------------------------------------------------------------


def test_default_layout_is_under_agents_root_and_ignores_xdg(monkeypatch, tmp_path):
    # Same paths on every OS: XDG variables (honoured by platformdirs) must not move them.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    assert surf_agent_config_dir() == new_config_dir()
    assert surf_agent_state_dir() == new_state_dir()
    assert config_file() == new_config_dir() / "config.json"
    assert default_patchright_profile_dir() == new_state_dir() / "profiles" / "chrome"


def test_profile_dir_override_moves_only_the_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("SURF_AGENT_PROFILE_DIR", str(tmp_path / "elsewhere"))
    assert default_patchright_profile_dir() == tmp_path / "elsewhere"
    assert surf_agent_config_dir() == new_config_dir()
    assert surf_agent_state_dir() == new_state_dir()


def test_bridge_defaults_to_profile_under_agents_state(bridge_profiles):
    bridge.main([])
    assert bridge_profiles == [new_state_dir() / "profiles" / "chrome"]


# --- refusing to start ------------------------------------------------------


@pytest.mark.parametrize("kind", ["config", "cookie_import", "profiles"])
def test_any_single_legacy_item_blocks_startup_with_migration_command(kind):
    plant(linux_legacy(), kinds=[kind])
    with pytest.raises(SurfAgentError) as raised:
        SurfAgent(chrome_bin="chrome")
    message = str(raised.value)
    assert str(linux_legacy()[kind]) in message
    assert "migrate_legacy_storage" in message
    assert not new_targets()["profiles"].exists()


def test_macos_legacy_folder_blocks_startup(simulate_macos):
    plant(macos_legacy(), kinds=["profiles"])
    with pytest.raises(SurfAgentError, match="migrate_legacy_storage"):
        SurfAgent(chrome_bin="chrome")


def _set_cookie_source(tmp_path: Path) -> None:
    source = tmp_path / "google-chrome"
    (source / "Default").mkdir(parents=True)
    Browser().set_cookie_source(str(source), "Default", domains=["example.com"])


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(lambda _tmp: Thread("t"), id="Thread"),
        pytest.param(lambda _tmp: Browser().profile(), id="Browser.profile"),
        pytest.param(lambda _tmp: Browser().cookie_source(), id="Browser.cookie_source"),
        pytest.param(_set_cookie_source, id="Browser.set_cookie_source"),
        pytest.param(lambda _tmp: Browser().reset_cookie_source(), id="Browser.reset_cookie_source"),
    ],
)
def test_public_entry_points_refuse_while_legacy_files_remain(entry, tmp_path, monkeypatch):
    monkeypatch.setenv("SURF_AGENT_CHROME_BIN", "chrome")
    plant(linux_legacy())
    with pytest.raises(SurfAgentError, match="old location"):
        entry(tmp_path)
    # Nothing written that would hide the legacy config (conftest's config path).
    assert not (tmp_path / "config.json").exists()


@pytest.mark.parametrize(
    "env,legacy_kinds,refuses",
    [
        pytest.param({"SURF_AGENT_HOME": "{tmp}/surf-home"}, ["config", "cookie_import", "profiles"], False, id="home-ignores-legacy"),
        pytest.param({"SURF_AGENT_PROFILE_DIR": "{tmp}/profile"}, ["profiles"], False, id="profile-override-ignores-legacy-profile"),
        pytest.param({"SURF_AGENT_PROFILE_DIR": "{tmp}/profile"}, ["config"], True, id="profile-override-still-checks-config"),
    ],
)
def test_overrides_decide_which_legacy_files_matter(env, legacy_kinds, refuses, tmp_path, monkeypatch):
    for name, value in env.items():
        monkeypatch.setenv(name, value.format(tmp=tmp_path))
    plant(linux_legacy(), kinds=legacy_kinds)
    if refuses:
        with pytest.raises(SurfAgentError, match="migrate_legacy_storage"):
            SurfAgent(chrome_bin="chrome")
    else:
        SurfAgent(chrome_bin="chrome")


# --- migration --------------------------------------------------------------


@pytest.mark.parametrize(
    "platform_paths,expected_old_roots",
    [
        pytest.param(
            linux_legacy,
            lambda: [
                home() / ".config" / "surf-agent",
                home() / ".local" / "state" / "surf-agent",
                home() / ".local" / "share" / "surf-agent",
            ],
            id="linux",
        ),
        pytest.param(
            macos_legacy,
            lambda: [home() / "Library" / "Application Support" / "surf-agent"],
            id="macos",
        ),
    ],
)
def test_migration_moves_everything_and_reports(platform_paths, expected_old_roots, request, capsys):
    if platform_paths is macos_legacy:
        request.getfixturevalue("simulate_macos")
    legacy = platform_paths()
    plant(legacy)

    migrate_legacy_storage()

    out = capsys.readouterr().out
    for kind, target in new_targets().items():
        assert content(kind, target) == (
            f"legacy {kind}" if kind == "profiles" else f'{{"legacy": "{kind}"}}'
        )
        assert not legacy[kind].exists()
        assert str(legacy[kind]) in out and str(target) in out
    for root in expected_old_roots():
        assert out.count(str(root) + "\n") == 1, f"old folder {root} reported once"
    # Surf now starts and uses the moved profile.
    agent = SurfAgent(chrome_bin="chrome")
    assert (agent.patchright_profile_dir / "Default" / "Cookies").read_text() == "legacy profiles"


def test_interrupted_migration_finishes_on_rerun():
    # State an interrupted run leaves: config already moved, the rest still old.
    plant(linux_legacy())
    targets = new_targets()
    targets["config"].parent.mkdir(parents=True)
    linux_legacy()["config"].rename(targets["config"])

    migrate_legacy_storage()

    assert content("profiles", targets["profiles"]) == "legacy profiles"
    assert content("cookie_import", targets["cookie_import"]) == '{"legacy": "cookie_import"}'
    assert content("config", targets["config"]) == '{"legacy": "config"}'
    check_legacy_storage()


def test_rerun_after_complete_migration_changes_nothing():
    plant(linux_legacy())
    migrate_legacy_storage()
    migrate_legacy_storage()
    assert content("profiles", new_targets()["profiles"]) == "legacy profiles"
    assert not (new_targets()["profiles"] / "profiles").exists()


def test_existing_target_is_neither_overwritten_nor_nested_into():
    plant(linux_legacy(), kinds=["profiles"])
    target = new_targets()["profiles"]
    (target / PROFILE_MARKER).parent.mkdir(parents=True)
    (target / PROFILE_MARKER).write_text("new profile")

    try:
        migrate_legacy_storage()
    except SurfAgentError:
        pass  # Refusing is acceptable; damaging either side is not.

    assert content("profiles", target) == "new profile"
    assert content("profiles", linux_legacy()["profiles"]) == "legacy profiles"
    assert not (target / "profiles").exists()


@pytest.mark.parametrize(
    ("resolver", "winner", "loser"),
    [
        (None, linux_legacy, macos_legacy),
        ("simulate_macos", macos_legacy, linux_legacy),
    ],
)
def test_path_active_in_this_environment_wins_over_other_copies(resolver, winner, loser, request):
    # One Mac can hold copies in both the XDG folders and Application Support,
    # depending on whether XDG_* was set when the old version ran.
    if resolver:
        request.getfixturevalue(resolver)
    plant(linux_legacy(), kinds=["profiles"])
    (macos_legacy()["profiles"] / PROFILE_MARKER).parent.mkdir(parents=True)
    (macos_legacy()["profiles"] / PROFILE_MARKER).write_text("other profile")
    winner_text = content("profiles", winner()["profiles"])

    migrate_legacy_storage()

    assert content("profiles", new_targets()["profiles"]) == winner_text
    assert loser()["profiles"].exists()
    check_legacy_storage()


def test_existing_target_wins_and_startup_proceeds():
    plant(linux_legacy(), kinds=["profiles"])
    target = new_targets()["profiles"]
    (target / PROFILE_MARKER).parent.mkdir(parents=True)
    (target / PROFILE_MARKER).write_text("new profile")

    check_legacy_storage()


def test_migration_refuses_while_chrome_uses_old_profile(monkeypatch):
    plant(linux_legacy(), kinds=["profiles"])
    old_profile = linux_legacy()["profiles"] / "chrome"
    # Narrowest seam: the process lister that Chrome detection reads.
    monkeypatch.setattr(
        "surf_agent.chrome_lifecycle.iter_process_args",
        lambda: [(os.getpid() + 100_000, ["/opt/google/chrome/chrome", f"--user-data-dir={old_profile}"])],
    )
    with pytest.raises(SurfAgentError, match="Chrome"):
        migrate_legacy_storage()
    assert content("profiles", linux_legacy()["profiles"]) == "legacy profiles"
    assert not new_targets()["profiles"].exists()


def test_cross_filesystem_move_stops_without_copying(monkeypatch):
    plant(linux_legacy(), kinds=["profiles"])
    real_rename = os.rename

    def rename_across_devices(source, destination, *args, **kwargs):
        if Path(source) == linux_legacy()["profiles"]:
            raise OSError(errno.EXDEV, os.strerror(errno.EXDEV), str(source), None, str(destination))
        return real_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", rename_across_devices)
    with pytest.raises(SurfAgentError, match="different filesystem"):
        migrate_legacy_storage()
    assert content("profiles", linux_legacy()["profiles"]) == "legacy profiles"
    assert not new_targets()["profiles"].exists()


def test_nothing_to_migrate_is_harmless(capsys):
    migrate_legacy_storage()
    assert not any(target.exists() for target in new_targets().values())
    assert capsys.readouterr().out.strip()


def test_bridge_refuses_default_profile_while_legacy_profile_remains(bridge_profiles):
    # Started without --profile-dir, the bridge would otherwise create a fresh,
    # logged-out profile at the new path; that target then hides the old profile
    # from every later startup check.
    plant(linux_legacy(), kinds=["profiles"])
    with pytest.raises(SurfAgentError, match="migrate_legacy_storage"):
        bridge.main([])
    assert bridge_profiles == []


def test_migration_refuses_when_surf_agent_home_is_set(monkeypatch, tmp_path, capsys):
    # The old roots are not Surf's files under an explicit home; offering them
    # for trashing would be wrong.
    monkeypatch.setenv("SURF_AGENT_HOME", str(tmp_path / "surf-home"))
    plant(linux_legacy())
    with pytest.raises(SurfAgentError):
        migrate_legacy_storage()
    assert "trash" not in capsys.readouterr().out
    for kind, path in linux_legacy().items():
        assert path.exists(), kind


def test_profile_override_never_offers_the_folder_holding_the_legacy_profile(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SURF_AGENT_PROFILE_DIR", str(tmp_path / "profile"))
    plant(linux_legacy())

    migrate_legacy_storage()

    out = capsys.readouterr().out
    assert content("config", new_targets()["config"]) == '{"legacy": "config"}'
    assert content("profiles", linux_legacy()["profiles"]) == "legacy profiles"
    profile_root = str(home() / ".local" / "share" / "surf-agent")
    assert not any(line.strip() == profile_root for line in out.splitlines()), out
