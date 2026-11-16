"""Environment configuration tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from task_runtime_base.config import (
    env,
    env_bool,
    env_float,
    env_int,
    require_env,
    require_env_any,
)
from task_runtime_base.errors import ConfigError


class EnvTestCase(unittest.TestCase):
    """Sets variables and restores the previous environment afterwards."""

    def setUp(self):
        self._saved = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def set(self, **values):
        for key, value in values.items():
            os.environ[key] = value


class EnvReadingTests(EnvTestCase):
    def test_value_is_stripped(self):
        self.set(X="  spaced  ")
        self.assertEqual(env("X"), "spaced")

    def test_blank_falls_back_to_default(self):
        """A variable set to whitespace is as good as unset."""
        self.set(X="   ")
        self.assertEqual(env("X", "fallback"), "fallback")

    def test_missing_returns_default(self):
        self.assertEqual(env("DEFINITELY_UNSET", "d"), "d")

    def test_require_env_raises_when_missing(self):
        with self.assertRaises(ConfigError):
            require_env("DEFINITELY_UNSET")

    def test_require_env_raises_when_blank(self):
        self.set(X="  ")
        with self.assertRaises(ConfigError):
            require_env("X")


class RequireEnvAnyTests(EnvTestCase):
    """Backs the task-id migration: six legacy names, one canonical."""

    def test_first_set_variable_wins(self):
        self.set(SECOND="b", THIRD="c")
        self.assertEqual(require_env_any("FIRST", "SECOND", "THIRD"), "b")

    def test_canonical_name_takes_precedence(self):
        self.set(PRIMARY_ID="new", LEGACY_ID="old")
        self.assertEqual(require_env_any("PRIMARY_ID", "LEGACY_ID"), "new")

    def test_none_set_raises_and_names_them(self):
        with self.assertRaises(ConfigError) as ctx:
            require_env_any("NOPE_A", "NOPE_B")
        self.assertIn("NOPE_A", str(ctx.exception))

    def test_no_names_is_an_error(self):
        with self.assertRaises(ConfigError):
            require_env_any()


class BoolTests(EnvTestCase):
    def test_accepts_the_spellings_tasks_already_use(self):
        for value in ("1", "true", "TRUE", "yes", "y", "on"):
            self.set(FLAG=value)
            self.assertTrue(env_bool("FLAG"), value)
        for value in ("0", "false", "no", "n", "off"):
            self.set(FLAG=value)
            self.assertFalse(env_bool("FLAG"), value)

    def test_unset_uses_default(self):
        self.assertTrue(env_bool("UNSET_FLAG", True))
        self.assertFalse(env_bool("UNSET_FLAG", False))

    def test_unrecognised_value_is_an_error(self):
        """`OVERWRITE=maybe` must not quietly mean "no"."""
        self.set(FLAG="maybe")
        with self.assertRaises(ConfigError):
            env_bool("FLAG")


class NumberTests(EnvTestCase):
    def test_int_parsing(self):
        self.set(N="42")
        self.assertEqual(env_int("N"), 42)

    def test_int_default_when_unset(self):
        self.assertEqual(env_int("UNSET_N", 7), 7)

    def test_int_required_when_no_default(self):
        with self.assertRaises(ConfigError):
            env_int("UNSET_N")

    def test_int_rejects_non_numeric_and_reports_the_value(self):
        self.set(N="abc")
        with self.assertRaises(ConfigError) as ctx:
            env_int("N")
        self.assertIn("abc", str(ctx.exception))

    def test_float_parsing(self):
        self.set(F="0.5")
        self.assertEqual(env_float("F"), 0.5)

    def test_float_rejects_non_numeric(self):
        self.set(F="x")
        with self.assertRaises(ConfigError):
            env_float("F")


if __name__ == "__main__":
    unittest.main()
