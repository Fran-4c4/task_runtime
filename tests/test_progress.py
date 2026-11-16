"""Progress formatting tests.

The dispatcher parses `NN% message` from stdout. A wrong format means the UI
shows a task stuck at 0% while it runs fine, so the format is pinned here.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from task_runtime_base.errors import ConfigError, PathEscapeError, TaskError
import json

from task_runtime_base.progress import (
    RECORD_ROOT,
    log_info,
    log_step,
    message,
    run_task,
    summary,
)


def _captured(fn):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        fn()
    return buffer.getvalue()


class StructuredRecordTests(unittest.TestCase):
    """The dispatcher recognises the documented structured-record root key."""

    def test_message_is_one_json_line(self):
        output = _captured(lambda: message("3 edificios sin altura", level="warning"))
        self.assertEqual(output.count("\n"), 1)
        self.assertEqual(
            json.loads(output),
            {RECORD_ROOT: {"type": "message", "level": "warning", "text": "3 edificios sin altura"}},
        )

    def test_unknown_level_becomes_info(self):
        output = _captured(lambda: message("x", level="loud"))
        self.assertEqual(json.loads(output)[RECORD_ROOT]["level"], "info")

    def test_summary_carries_its_data(self):
        output = _captured(lambda: summary({"updated": 1234, "without_height": 3}))
        self.assertEqual(
            json.loads(output),
            {RECORD_ROOT: {"type": "summary", "data": {"updated": 1234, "without_height": 3}}},
        )

    def test_text_with_newlines_stays_on_one_line(self):
        output = _captured(lambda: message("line one\nline two"))
        self.assertEqual(output.count("\n"), 1)
        self.assertEqual(json.loads(output)[RECORD_ROOT]["text"], "line one\nline two")


class LogStepTests(unittest.TestCase):
    def test_dispatcher_format(self):
        self.assertEqual(_captured(lambda: log_step(42, "working")), "42% working\n")

    def test_percent_is_clamped(self):
        self.assertEqual(_captured(lambda: log_step(-5, "x")), "0% x\n")
        self.assertEqual(_captured(lambda: log_step(150, "x")), "100% x\n")

    def test_info_lines_cannot_be_mistaken_for_progress(self):
        """An info line must not start with digits followed by '%'."""
        output = _captured(lambda: log_info("detail"))
        self.assertFalse(output.lstrip().startswith(("0", "1", "2", "3", "4",
                                                     "5", "6", "7", "8", "9")))


class ExitCodeTests(unittest.TestCase):
    """Each failure class keeps a distinct exit code the dispatcher can act on."""

    def test_task_errors_are_system_exit(self):
        """Uncaught, a TaskError must exit with its own code, not a traceback.

        Also keeps faith with the helpers it replaced: `die` and `require_env`
        raised SystemExit, and existing task test suites assert on that.
        """
        self.assertTrue(issubclass(TaskError, SystemExit))
        self.assertEqual(PathEscapeError("x").code, 3)
        self.assertEqual(str(ConfigError("missing FOO")), "missing FOO")

    def test_task_error_is_not_caught_by_except_exception(self):
        """A defensive `except Exception` must not swallow a failed task."""
        try:
            raise ConfigError("boom")
        except Exception:  # noqa: BLE001 - deliberately broad, asserting it misses
            self.fail("ConfigError was caught by except Exception")
        except SystemExit as error:
            self.assertEqual(error.code, 2)

    def test_task_error_exit_codes_are_distinct(self):
        self.assertEqual(TaskError("x").exit_code, 1)
        self.assertEqual(ConfigError("x").exit_code, 2)
        self.assertEqual(PathEscapeError("x").exit_code, 3)

    def test_run_task_exits_zero_on_success(self):
        with self.assertRaises(SystemExit) as ctx:
            run_task(lambda: None)
        self.assertEqual(ctx.exception.code, 0)

    def test_run_task_maps_task_error_to_its_exit_code(self):
        def failing():
            raise PathEscapeError("escaped")

        with self.assertRaises(SystemExit) as ctx:
            run_task(failing)
        self.assertEqual(ctx.exception.code, 3)

    def test_unexpected_errors_still_propagate(self):
        """A genuine bug should surface as a traceback, not a tidy exit."""
        def buggy():
            raise ValueError("bug")

        with self.assertRaises(ValueError):
            run_task(buggy)


if __name__ == "__main__":
    unittest.main()
