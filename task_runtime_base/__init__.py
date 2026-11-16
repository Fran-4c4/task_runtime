"""Shared runtime helpers for containerized tasks.

Every task container repeats the same five things: read configuration from the
environment, translate host paths to container paths, keep those paths inside
their allowed roots, report progress, and write an output log. Before this
package each task had its own copy, and the copies had already diverged — one of
them silently lost its path-containment check.

Import what you need:

    from task_runtime_base import (
        env, env_bool, env_int, env_float, require_env, require_env_any,
        PathTranslator, PathEscapeError,
        log_step, log_info, die, TaskError,
        task_id, setup_out_dir, write_run_manifest,
        run,
    )

Python support
--------------
**Python 3.9 is the floor and it is a hard constraint, not an aspiration.**
Task images are often built on different Python versions, so this code must not
use anything newer than 3.9:

  - `from __future__ import annotations` in every module, so `str | None` in a
    signature is a string at runtime and never evaluated.
  - No `match` statements, no `tomllib`, no PEP 604 unions outside annotations,
    no `dict | dict` merge operator on 3.8 (fine on 3.9), no `Self`.
  - Only the standard library. A task needing numpy or GDAL brings it itself.

Images without a compatible Python runtime cannot use these helpers directly.
"""

from __future__ import annotations

from task_runtime_base.config import (
    env,
    env_bool,
    env_float,
    env_int,
    require_env,
    require_env_any,
)
from task_runtime_base.errors import OutputExistsError, PathEscapeError, TaskError
from task_runtime_base.outputs import (
    reserve_output_file,
    setup_out_dir,
    task_id,
    write_run_manifest,
)
from task_runtime_base.paths import PathTranslator
from task_runtime_base.process import RunResult, run
from task_runtime_base.progress import die, log_info, log_step, message, summary

__version__ = "0.1.0"

__all__ = [
    "env",
    "env_bool",
    "env_float",
    "env_int",
    "require_env",
    "require_env_any",
    "TaskError",
    "PathEscapeError",
    "OutputExistsError",
    "PathTranslator",
    "log_step",
    "log_info",
    "message",
    "summary",
    "die",
    "task_id",
    "setup_out_dir",
    "reserve_output_file",
    "write_run_manifest",
    "run",
    "RunResult",
    "__version__",
]
