"""Progress, log lines, and structured messages emitted by task containers.

The dispatcher reads container stdout. A line beginning with `NN% ` is a
progress update, stored on the task request with its message. A line that is a
JSON object with the root key "task_runtime" is a structured record: a message for the
user, or the run's summary. The task screen lists those apart from the log.
Anything else is plain log output, kept in full in the log store.

Getting a format wrong is a silent failure (a task stuck at 0%, a warning
nobody sees), so the formats live here and nowhere else.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, NoReturn

from task_runtime_base.errors import TaskError


def log_step(percent: int, message: str) -> None:
    """Report progress. `percent` is clamped to 0-100 and printed as `NN% msg`."""
    bounded = max(0, min(100, int(percent)))
    print("{0}% {1}".format(bounded, message), flush=True)


def log_info(message: str) -> None:
    """Log a detail line. Indented so it cannot be mistaken for a progress line."""
    print("   {0}".format(message), flush=True)


def log_warning(message: str) -> None:
    """Log something the operator should notice that is not fatal."""
    print("   WARNING: {0}".format(message), file=sys.stderr, flush=True)


MESSAGE_LEVELS = ("info", "notice", "warning", "error")

# External protocol contract: every structured stdout record has exactly this
# root key. Dispatchers consume it line by line; changing it requires coordinated
# updates to every producer, parser, stored event schema, and regression test.
RECORD_ROOT = "task_runtime"


def _emit_record(record: Dict[str, Any]) -> None:
    # One line, always: the dispatcher reads records line by line.
    print(json.dumps({RECORD_ROOT: record}, ensure_ascii=False, default=str), flush=True)


def message(text: str, level: str = "info") -> None:
    """Tell the user something, apart from the log: it is listed on the task screen.

    For what the user should read even if they never open the log: a result
    ("1234 buildings updated"), a warning about the data ("3 buildings have no
    LiDAR height; the cadastral one is used"), an error they can act on. Detail
    for whoever debugs the task goes to log_info instead.

    `level` is one of info, notice, warning, error; anything else is info.
    """
    if level not in MESSAGE_LEVELS:
        level = "info"
    _emit_record({"type": "message", "level": level, "text": str(text)})


def summary(data: Dict[str, Any]) -> None:
    """Report the run's result as figures the task screen can show.

    Call it once, near the end. A later call replaces an earlier one. Keep it
    small: a few counts or names, not the output itself.
    """
    _emit_record({"type": "summary", "data": data})


def die(message: str, exit_code: int = 1) -> NoReturn:
    """Print an error to stderr and exit.

    Prefer raising a `TaskError` from library code — it carries a meaningful exit
    code and can be caught. This is for the top level of a script.
    """
    print("ERROR: {0}".format(message), file=sys.stderr, flush=True)
    raise SystemExit(exit_code)


def run_task(main_function) -> NoReturn:
    """Run a task's `main()` and turn a TaskError into a clean exit.

    Wrapping the entrypoint means a configuration mistake prints one clear line
    and returns a meaningful exit code, instead of a traceback the operator has
    to read through:

        if __name__ == "__main__":
            run_task(main)
    """
    try:
        main_function()
    except TaskError as error:
        print("ERROR: {0}".format(error.message), file=sys.stderr, flush=True)
        raise SystemExit(error.exit_code)
    raise SystemExit(0)
