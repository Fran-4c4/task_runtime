"""Output directory and task log tests."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from task_runtime_base.errors import ConfigError, OutputExistsError
from task_runtime_base.outputs import (
    reserve_output_file,
    setup_out_dir,
    task_id,
    write_run_manifest,
)


class TaskIdTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(os.environ)
        os.environ.pop("TASK_RUN_ID", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def test_canonical_variable(self):
        os.environ["TASK_RUN_ID"] = "abc"
        self.assertEqual(task_id(), "abc")

    def test_unrelated_id_variable_is_not_an_alias(self):
        os.environ["CUSTOM_TASK_ID"] = "other"
        with self.assertRaises(ConfigError):
            task_id()

    def test_missing_task_id_is_an_error(self):
        with self.assertRaises(ConfigError):
            task_id()

    def test_task_id_must_be_one_path_component(self):
        for invalid in (".", "..", "../escape", "nested/run", "nested\\run"):
            with self.subTest(value=invalid):
                os.environ["TASK_RUN_ID"] = invalid
                with self.assertRaises(ConfigError):
                    task_id()


class OutDirTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(os.environ)
        self.root = Path(tempfile.mkdtemp())
        os.environ["TASK_RUN_ID"] = "run-1"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)
        shutil.rmtree(self.root, ignore_errors=True)

    def test_creates_per_run_subdirectory(self):
        """`/out/<task_id>/` is the layout the backend resolves for downloads."""
        directory = setup_out_dir(root=str(self.root))
        self.assertTrue(directory.is_dir())
        self.assertEqual(directory.name, "run-1")

    def test_is_idempotent(self):
        first = setup_out_dir(root=str(self.root))
        second = setup_out_dir(root=str(self.root))
        self.assertEqual(first, second)


class RunManifestTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_records_inputs_and_outputs(self):
        path = write_run_manifest(
            self.root, "export_footprints",
            inputs={"table": "inspire.buildings", "crs": "4326"},
            outputs={"feature_count": 538},
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("Run manifest — export_footprints", content)
        self.assertIn("table: inspire.buildings", content)
        self.assertIn("feature_count: 538", content)

    def test_blank_input_is_shown_as_none(self):
        """An empty filter should read as "(none)", not as a blank line."""
        path = write_run_manifest(self.root, "op", inputs={"where": ""}, outputs={})
        self.assertIn("where: (none)", path.read_text(encoding="utf-8"))

    def test_notes_are_appended(self):
        path = write_run_manifest(self.root, "op", inputs={}, outputs={}, notes="dry run")
        self.assertIn("dry run", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class ReserveOutputFileTests(unittest.TestCase):
    """Claiming an output name, and what happens when two runs want the same one.

    This is the case the run-id folder used to make impossible: with the folder
    named after the run, two concurrent runs could not meet. Once the user
    chooses the folder and the file name, they can — and the history already
    holds six pairs of overlapping runs of the same task.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_the_file_and_returns_it(self):
        path = reserve_output_file(self.tmp, "result.tif")
        self.assertEqual(path, self.tmp / "result.tif")
        self.assertTrue(path.exists())

    def test_creates_missing_parent_directories(self):
        path = reserve_output_file(self.tmp / "deep" / "nested", "result.tif")
        self.assertTrue(path.exists())

    def test_second_claim_is_refused(self):
        reserve_output_file(self.tmp, "result.tif")
        with self.assertRaises(OutputExistsError):
            reserve_output_file(self.tmp, "result.tif")

    def test_refusal_does_not_touch_the_existing_file(self):
        """The whole point: the loser must not destroy the winner's output."""
        first = reserve_output_file(self.tmp, "result.tif")
        first.write_text("the first run's results", encoding="utf-8")
        with self.assertRaises(OutputExistsError):
            reserve_output_file(self.tmp, "result.tif")
        self.assertEqual(first.read_text(encoding="utf-8"), "the first run's results")

    def test_overwrite_replaces_it(self):
        first = reserve_output_file(self.tmp, "result.tif")
        first.write_text("stale", encoding="utf-8")
        again = reserve_output_file(self.tmp, "result.tif", overwrite=True)
        self.assertEqual(again.read_text(encoding="utf-8"), "")

    def test_overwrite_on_a_free_name_is_fine(self):
        path = reserve_output_file(self.tmp, "fresh.tif", overwrite=True)
        self.assertTrue(path.exists())

    def test_exit_code_is_distinct(self):
        """The dispatcher tells this apart from a generic failure."""
        self.assertEqual(OutputExistsError.exit_code, 5)

    def test_only_one_of_many_concurrent_claims_wins(self):
        """The property a check-then-write guard cannot provide.

        Threads rather than processes, which is enough: `os.open` with O_EXCL
        releases the GIL, so without the kernel's atomicity several would succeed.
        """
        import threading

        winners = []
        losers = []
        barrier = threading.Barrier(8)

        def claim():
            barrier.wait()
            try:
                reserve_output_file(self.tmp, "contended.tif")
                winners.append(1)
            except OutputExistsError:
                losers.append(1)

        threads = [threading.Thread(target=claim) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(winners), 1, "exactly one run may claim the name")
        self.assertEqual(len(losers), 7)
