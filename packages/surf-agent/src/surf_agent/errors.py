from __future__ import annotations

from enum import StrEnum
import itertools
import os
import sys
import traceback
from types import TracebackType

PACKAGE_DIRECTORY = os.path.dirname(os.path.abspath(__file__)) + os.sep


class ErrorCode(StrEnum):
    """Stable failure categories; callers branch on these, never on message text."""

    STALE_REF = "stale_ref"
    NOT_FOUND = "not_found"
    NOT_VISIBLE = "not_visible"
    NOT_ENABLED = "not_enabled"
    NOT_EDITABLE = "not_editable"
    INTERCEPTED = "intercepted"
    ACTION_TIMEOUT = "action_timeout"
    WAIT_TIMEOUT = "wait_timeout"
    PAGE_CLOSED = "page_closed"
    BRIDGE_UNAVAILABLE = "bridge_unavailable"
    OUTCOME_UNKNOWN = "outcome_unknown"


class SurfAgentError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1, *, code: ErrorCode | None = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.code = code


class BridgeUnavailable(SurfAgentError):
    def __init__(self, message: str, *, code: ErrorCode = ErrorCode.BRIDGE_UNAVAILABLE) -> None:
        super().__init__(message, code=code)


class BridgeIdentityUnproven(SurfAgentError):
    pass


class BridgeToolError(SurfAgentError):
    def __init__(self, *, backend_label: str, tool_name: str, detail: str, code: ErrorCode | None = None) -> None:
        self.detail = detail
        super().__init__(f"{backend_label} bridge tool {tool_name} failed: {detail}", code=code)


def _is_surf_frame(frame: traceback.FrameSummary) -> bool:
    return os.path.abspath(frame.filename).startswith(PACKAGE_DIRECTORY)


def format_surf_error(error: SurfAgentError, trace: TracebackType | None) -> str:
    """The caller's frames and an `ExceptionName [code]: message` line.

    Surf's own frames are the same on every failure, so they only cost the caller
    tokens. The caller's frames are the run outside this package that ends at the
    first call into it; leading Surf frames are the session runner executing a cell.
    """
    frames = traceback.extract_tb(trace)
    caller_frames = itertools.takewhile(
        lambda frame: not _is_surf_frame(frame),
        itertools.dropwhile(_is_surf_frame, frames),
    )
    code = f" [{error.code}]" if error.code else ""
    summary = f"{type(error).__name__}{code}: {error}\n"
    return "".join(traceback.format_list(list(caller_frames))) + summary


def install_brief_surf_tracebacks() -> None:
    """Print uncaught Surf errors briefly in a script; other errors keep the full traceback."""
    previous_hook = sys.excepthook

    def excepthook(
        error_type: type[BaseException], error: BaseException, trace: TracebackType | None
    ) -> None:
        if isinstance(error, SurfAgentError):
            sys.stderr.write(format_surf_error(error, trace))
        else:
            previous_hook(error_type, error, trace)

    sys.excepthook = excepthook
