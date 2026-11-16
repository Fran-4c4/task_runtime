"""Subprocess wrapper for external command-line tools driven by tasks."""

from __future__ import annotations

import subprocess
from typing import Optional, Sequence

from task_runtime_base.errors import TaskError


class RunResult(object):
    """Outcome of a subprocess call."""

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run(
    cmd: Sequence[str],
    check: bool = True,
    capture: bool = False,
    env: Optional[dict] = None,
    cwd: Optional[str] = None,
) -> RunResult:
    """Run a command.

    By default output streams straight through to the container log, so progress
    from the underlying tool reaches the UI. `capture=True` collects it instead,
    for when the task needs to parse it.

    With `check=True` a non-zero exit raises TaskError including stderr — the
    failure mode that used to produce a bare "command failed" with no detail.
    """
    completed = subprocess.run(
        list(cmd),
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        universal_newlines=True,
        env=env,
        cwd=cwd,
    )
    result = RunResult(
        completed.returncode,
        completed.stdout or "",
        completed.stderr or "",
    )
    if check and not result.ok:
        detail = result.stderr.strip()
        raise TaskError(
            "command failed (exit {0}): {1}{2}".format(
                result.returncode,
                " ".join(cmd),
                "\n{0}".format(detail) if detail else "",
            )
        )
    return result
