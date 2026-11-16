"""Containment tests for PathTranslator.

These are the tests that matter most in this package. Each one pins a way a path
could escape its allowed root — and with multi-tenancy, escaping the root means
reaching another tenant's data. `task-lidar-dsm` shipped without any of these
checks because they were lost in a copy-paste; that is what this file prevents
from recurring.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from task_runtime_base.errors import InputNotFoundError, PathEscapeError
from task_runtime_base.paths import PathTranslator


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.translator = PathTranslator(
            host_prefix="/data", container_root="/host-data", extra_roots=("/out", "/tmp")
        )

    def test_host_path_is_translated(self):
        self.assertEqual(
            self.translator.translate("/data/lidar/gra/vuelo_2024"),
            Path("/host-data/lidar/gra/vuelo_2024"),
        )

    def test_host_prefix_itself_translates_to_the_root(self):
        self.assertEqual(self.translator.translate("/data"), Path("/host-data"))

    def test_container_path_passes_through(self):
        self.assertEqual(self.translator.translate("/out/result.tif"), Path("/out/result.tif"))

    def test_empty_path_is_rejected(self):
        with self.assertRaises(PathEscapeError):
            self.translator.translate("")

    def test_sibling_prefix_is_not_translated(self):
        """`/database` starts with the string `/data` but is not inside it."""
        self.assertEqual(self.translator.translate("/database/x"), Path("/database/x"))


class ContainmentTests(unittest.TestCase):
    """Every way a path could leave its root."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.container_root = self.root / "host-data"
        self.container_root.mkdir()
        self.outside = self.root / "outside"
        self.outside.mkdir()
        self.translator = PathTranslator(
            host_prefix="/data",
            container_root=str(self.container_root),
            extra_roots=(),
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_path_inside_root_is_accepted(self):
        target = self.container_root / "a" / "b.txt"
        self.assertEqual(self.translator.validate(target), target.resolve())

    def test_root_itself_is_accepted(self):
        self.assertEqual(
            self.translator.validate(self.container_root), self.container_root.resolve()
        )

    def test_parent_traversal_is_rejected(self):
        with self.assertRaises(PathEscapeError):
            self.translator.validate(self.container_root / ".." / "outside" / "x")

    def test_absolute_path_outside_root_is_rejected(self):
        with self.assertRaises(PathEscapeError):
            self.translator.validate(Path("/etc/passwd"))

    def test_sibling_directory_sharing_a_prefix_is_rejected(self):
        """The bug a `str.startswith` check would let through.

        `<root>2` shares the root's textual prefix but is a different directory.
        Containment must compare path components, not strings.
        """
        sibling = Path(str(self.container_root) + "2")
        sibling.mkdir()
        with self.assertRaises(PathEscapeError):
            self.translator.validate(sibling / "stolen.txt")

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_symlink_pointing_outside_is_rejected(self):
        """A link inside the mount that points out of it.

        Only caught because `validate` resolves before comparing; comparing the
        unresolved path would accept this.
        """
        secret = self.outside / "secret.txt"
        secret.write_text("other tenant's data", encoding="utf-8")
        link = self.container_root / "innocent.txt"
        link.symlink_to(secret)
        with self.assertRaises(PathEscapeError):
            self.translator.validate(link)

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_symlink_pointing_inside_is_accepted(self):
        real = self.container_root / "real.txt"
        real.write_text("mine", encoding="utf-8")
        link = self.container_root / "alias.txt"
        link.symlink_to(real)
        self.assertEqual(self.translator.validate(link), real.resolve())

    def test_extra_roots_are_allowed(self):
        scratch = self.root / "scratch"
        scratch.mkdir()
        translator = PathTranslator(
            host_prefix="/data",
            container_root=str(self.container_root),
            extra_roots=(str(scratch),),
        )
        self.assertEqual(
            translator.validate(scratch / "tmp.tif"), (scratch / "tmp.tif").resolve()
        )


class MountedPathTests(unittest.TestCase):
    """Storage attached inside a root that resolves elsewhere on the host.

    The tenant tree carries mounts like geoserver/mapdata pointing at GeoServer's
    own directory. Following those is legitimate; following an undeclared link
    out of the tree is not, and that distinction has to survive.
    """

    def setUp(self):
        if os.name == "nt":
            self.skipTest("creating symlinks requires optional Windows privileges")
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "root"
        self.root.mkdir()
        self.mounted = self.tmp / "elsewhere"
        (self.mounted / "data").mkdir(parents=True)
        (self.root / "mount").symlink_to(self.mounted)
        self.forbidden = self.tmp / "forbidden"
        self.forbidden.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_undeclared_mount_is_rejected(self):
        translator = PathTranslator("/data", str(self.root), extra_roots=())
        with self.assertRaises(PathEscapeError):
            translator.validate(self.root / "mount" / "data")

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_declared_mount_is_accepted(self):
        translator = PathTranslator(
            "/data", str(self.root), extra_roots=(), mounted_paths=[str(self.mounted)]
        )
        self.assertEqual(
            translator.validate(self.root / "mount" / "data"),
            (self.mounted / "data").resolve(),
        )

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_declaring_one_mount_does_not_open_another(self):
        (self.root / "sneaky").symlink_to(self.forbidden)
        translator = PathTranslator(
            "/data", str(self.root), extra_roots=(), mounted_paths=[str(self.mounted)]
        )
        with self.assertRaises(PathEscapeError):
            translator.validate(self.root / "sneaky")

    def test_traversal_is_still_rejected_with_mounts_declared(self):
        translator = PathTranslator(
            "/data", str(self.root), extra_roots=(), mounted_paths=[str(self.mounted)]
        )
        with self.assertRaises(PathEscapeError):
            translator.validate(self.root / ".." / "forbidden")


class ToContainerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.container_root = self.root / "host-data"
        (self.container_root / "lidar").mkdir(parents=True)
        self.translator = PathTranslator(
            host_prefix="/data", container_root=str(self.container_root), extra_roots=()
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_translate_and_validate_together(self):
        self.assertEqual(
            self.translator.to_container("/data/lidar"), (self.container_root / "lidar").resolve()
        )

    def test_traversal_in_host_path_is_rejected(self):
        with self.assertRaises(PathEscapeError):
            self.translator.to_container("/data/../../etc/passwd")

    def test_existing_check_distinguishes_missing_from_escaping(self):
        """Two different problems must not produce the same error."""
        with self.assertRaises(InputNotFoundError):
            self.translator.to_container_existing("/data/nope")
        with self.assertRaises(PathEscapeError):
            self.translator.to_container_existing("/etc/passwd")


class DisplayTests(unittest.TestCase):
    """Task logs are shown verbatim in the UI, so paths in them are public.

    A message quoting `/data/tenants/acme/out/x.json` tells any user where every
    tenant's data lives on the server and what the other tenants are called.
    None of that helps the person reading the log: the part they typed, and the
    only part they can fix, is `out/x.json`.
    """

    def setUp(self):
        self.translator = PathTranslator(
            host_prefix="/data/tenants/acme",
            container_root="/host-data",
            extra_roots=("/out", "/tmp"),
        )

    def test_container_path_is_shown_relative_to_the_mount(self):
        self.assertEqual(
            self.translator.display("/host-data/out/model.city.json"),
            "out/model.city.json",
        )

    def test_host_path_is_shown_without_the_tenant_root(self):
        self.assertEqual(
            self.translator.display("/data/tenants/acme/out/model.city.json"),
            "out/model.city.json",
        )

    def test_output_root_is_stripped_too(self):
        self.assertEqual(self.translator.display("/out/run-id/model.glb"), "run-id/model.glb")

    def test_unattributable_path_is_shown_whole(self):
        """A path matching no known root is the one worth seeing in full."""
        self.assertEqual(self.translator.display("/etc/passwd"), "/etc/passwd")

    def test_the_root_itself_is_not_shown_as_a_dot(self):
        self.assertEqual(self.translator.display("/host-data"), "")

    def test_missing_input_message_does_not_leak_the_tenant_root(self):
        with self.assertRaises(InputNotFoundError) as caught:
            self.translator.to_container_existing("/data/tenants/acme/out/nope.json")
        message = str(caught.exception)
        self.assertIn("out/nope.json", message)
        self.assertNotIn("/data/tenants", message)
        self.assertNotIn("acme", message)

    def test_escape_message_does_not_disclose_the_real_roots(self):
        """An escape attempt is exactly when not to hand back the map."""
        with self.assertRaises(PathEscapeError) as caught:
            self.translator.to_container("/etc/passwd")
        message = str(caught.exception)
        self.assertNotIn("/host-data", message)
        self.assertNotIn("/data/tenants", message)


class CollectFilesTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.translator = PathTranslator(
            host_prefix="/data", container_root=str(self.root), extra_roots=()
        )
        for name in ("a.laz", "b.LAZ", "c.txt"):
            (self.root / name).write_text("x", encoding="utf-8")
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "d.laz").write_text("x", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_suffix_match_is_case_insensitive(self):
        found = self.translator.collect_files(self.root, suffixes=(".laz",))
        self.assertEqual([p.name for p in found], ["a.laz", "b.LAZ"])

    def test_recursive_includes_nested(self):
        found = self.translator.collect_files(self.root, suffixes=(".laz",), recursive=True)
        self.assertEqual(len(found), 3)

    def test_single_file_is_returned_as_one_item(self):
        found = self.translator.collect_files(self.root / "a.laz", suffixes=(".laz",))
        self.assertEqual(len(found), 1)

    def test_single_file_with_wrong_suffix_is_rejected(self):
        with self.assertRaises(InputNotFoundError):
            self.translator.collect_files(self.root / "c.txt", suffixes=(".laz",))

    def test_no_matches_is_an_error(self):
        with self.assertRaises(InputNotFoundError):
            self.translator.collect_files(self.root, suffixes=(".tif",))


class SafeJoinTests(unittest.TestCase):
    """Archive entries are untrusted content — `../../etc/passwd` is a real attack."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.base = self.root / "out"
        self.base.mkdir()
        self.translator = PathTranslator(
            host_prefix="/data", container_root=str(self.root), extra_roots=()
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_normal_member_is_joined(self):
        self.assertEqual(
            self.translator.safe_join(self.base, "dir/file.txt"),
            (self.base / "dir" / "file.txt").resolve(),
        )

    def test_traversing_member_is_rejected(self):
        with self.assertRaises(PathEscapeError):
            self.translator.safe_join(self.base, "../../etc/passwd")

    def test_absolute_member_is_rejected(self):
        with self.assertRaises(PathEscapeError):
            self.translator.safe_join(self.base, "/etc/passwd")


if __name__ == "__main__":
    unittest.main()
