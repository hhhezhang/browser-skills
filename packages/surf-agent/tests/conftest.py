from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep pytest runs independent of user surf-agent config."""
    import surf_agent.runtime as runtime

    monkeypatch.setattr(runtime, "config_file", lambda: tmp_path / "config.json")


@pytest.fixture(autouse=True)
def isolate_storage_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep default and legacy storage paths away from the user's real files."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for variable in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture(autouse=True)
def isolate_emission_baselines(monkeypatch: pytest.MonkeyPatch) -> None:
    """Baselines live for the whole process; tests reuse thread names."""
    import surf_agent.thread as thread

    monkeypatch.setattr(thread, "_baselines", {})
