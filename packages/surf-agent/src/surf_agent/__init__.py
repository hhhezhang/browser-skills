"""Agent-scoped surf wrapper."""

__all__ = ["__version__", "Browser", "ErrorCode", "Snapshot", "Thread", "SurfAgentError"]
__version__ = "0.1.0"

from .errors import install_brief_surf_tracebacks

# A script run by the launcher reports uncaught errors through this hook; a session
# cell formats them itself.
install_brief_surf_tracebacks()


def __getattr__(name: str):
    if name == "Browser":
        from .browser import Browser
        return Browser
    if name in {"ErrorCode", "SurfAgentError"}:
        from . import errors

        return getattr(errors, name)
    if name in {"Snapshot", "Thread"}:
        from .thread import Snapshot, Thread

        return {"Snapshot": Snapshot, "Thread": Thread}[name]
    raise AttributeError(name)
