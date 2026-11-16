"""Output directory and task log.

Every task writes to `/out/<task_id>/`, a per-run directory inside the writable
bind mount. The backend resolves that same path to list and serve the results, so
the convention has to match exactly.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Mapping, Optional

from task_runtime_base.config import require_env
from task_runtime_base.errors import ConfigError, OutputExistsError, TaskError

# External contract: TASK_RUN_ID is the sole authoritative identifier for one
# execution. It must be present, non-blank, and a single path component: `.`,
# `..`, `/`, and `\` are rejected. setup_out_dir() consumes it beneath
# OUTPUT_ROOT; changing this name or domain affects every task launcher and
# container using this runtime.
TASK_ID_VARIABLE = "TASK_RUN_ID"

OUTPUT_ROOT = "/out"


def task_id() -> str:
    """Return the validated identifier for the current task execution."""
    value = require_env(TASK_ID_VARIABLE)
    if value in (".", "..") or "/" in value or "\\" in value:
        raise ConfigError(
            "{0} must be a single path component".format(TASK_ID_VARIABLE)
        )
    return value


def setup_out_dir(root: str = OUTPUT_ROOT) -> Path:
    """Create and return `/out/<task_id>/`.

    The dispatcher mounts `<host output base>` at `/out`; this subdirectory is
    what the backend later resolves for downloads.
    """
    directory = Path(root) / task_id()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def reserve_output_file(
    directory: Path,
    name: str,
    *,
    overwrite: bool = False,
) -> Path:
    """Claim `directory/name` for this run, atomically.

    Why atomically, and not "check then write"
    ------------------------------------------
    Two people can launch the same task at the same time — it has already
    happened here — and if both name the same output file, a plain
    `if path.exists()` guard does not help: between the check and the write sits
    the other run. Whoever finishes second wins, the first result is gone, and
    nothing reports an error. Worse, a reader can catch the file mid-rewrite and
    take away something truncated.

    `O_CREAT | O_EXCL` asks the kernel to create the file *only if it does not
    exist*, in one operation. There is no window. The loser gets an error instead
    of silently destroying the winner's output.

    The file is created empty and returned as a path: callers hand it to PDAL,
    GDAL or a writer that expects to open it itself, which is fine — the point is
    that the *name* is now taken.

    `overwrite=True` is the deliberate escape hatch, for re-running a task over
    its own previous result. It removes the existing file first, so the race is
    reopened on purpose and by request.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name

    if overwrite:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise TaskError(
                "cannot replace {0}: {1}".format(target, error)
            )

    try:
        handle = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise OutputExistsError(
            "{0} already exists. Choose another name, or enable overwriting to "
            "replace it.".format(target)
        )
    except OSError as error:
        raise TaskError("cannot create {0}: {1}".format(target, error))
    os.close(handle)
    return target


def write_run_manifest(
    out_dir: Path,
    operation: str,
    inputs: Mapping[str, object],
    outputs: Mapping[str, object],
    notes: Optional[str] = None,
) -> Path:
    """Write `run_manifest.txt`: what the task was asked to do and what it produced.

    It travels with the outputs, so whoever receives the folder knows how it
    was made. It is not the run's log: that is everything the task wrote to
    stdout, kept in the log store. Kept deliberately plain and stable.
    """
    generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "Run manifest — {0}".format(operation),
        "Generated: {0}".format(generated),
        "",
        "Inputs:",
    ]
    for key, value in inputs.items():
        lines.append("  {0}: {1}".format(key, value if value != "" else "(none)"))
    lines.append("")
    lines.append("Outputs:")
    for key, value in outputs.items():
        lines.append("  {0}: {1}".format(key, value))
    if notes:
        lines.extend(["", "Notes:", "  {0}".format(notes)])
    lines.append("")

    path = out_dir / "run_manifest.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
