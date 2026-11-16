"""Task failure types with stable process exit codes.

Tasks signal failure to the dispatcher through the process exit code. Giving each
failure class its own code lets the dispatcher tell "bad configuration" from "the
work itself failed" without parsing stderr.
"""

from __future__ import annotations


class TaskError(SystemExit):
    """Base error for a task that cannot continue.

    `exit_code` is what the process returns. 1 is the generic failure; the
    subclasses below use distinct codes so callers can react differently.

    Derives from SystemExit, not Exception, for two reasons:

    - An uncaught one exits with its own code instead of a traceback and exit 1,
      so a task that forgets `run_task()` still reports the right code.
    - The helpers these errors replaced (`die`, `require_env`) raised SystemExit,
      and existing task tests assert on that. Keeping the base class means those
      tests stay meaningful instead of being rewritten to match the new library.

    The consequence worth knowing: a bare `except Exception` will NOT catch
    these. That is the intended behaviour — a task failing configuration should
    stop, not be swallowed by a defensive handler.
    """

    exit_code = 1

    def __init__(self, message: str) -> None:
        # SystemExit's first arg becomes .code, which is what the interpreter
        # uses when the exception propagates uncaught.
        super().__init__(self.exit_code)
        self.message = message

    def __str__(self) -> str:
        return self.message


class ConfigError(TaskError):
    """Missing or malformed environment configuration. The task never started."""

    exit_code = 2


class PathEscapeError(TaskError):
    """A path resolved outside its allowed root.

    Raised before any I/O happens. Treat it as a security event, not a typo:
    with multi-tenancy, a path escaping its root can reach another tenant's data.
    """

    exit_code = 3


class InputNotFoundError(TaskError):
    """An input path is valid and contained, but does not exist."""

    exit_code = 4


class OutputExistsError(TaskError):
    """The requested output already exists and overwriting was not requested.

    Its own code because it is the one failure here the user can act on directly:
    pick another name, or tick overwrite. The dispatcher can surface it as a
    prompt rather than as a generic task failure.
    """

    exit_code = 5
