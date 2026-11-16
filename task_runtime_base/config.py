"""Environment configuration helpers.

Task containers are configured entirely through environment variables, injected
by the dispatcher from `container_env_json`. These helpers make reading them
uniform: every value is stripped, every missing required value fails the same
way, and every type conversion reports the offending value.
"""

from __future__ import annotations

import os
from typing import Optional

from task_runtime_base.errors import ConfigError


def env(name: str, default: str = "") -> str:
    """Read an environment variable, stripped. Missing or blank yields `default`."""
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def require_env(name: str) -> str:
    """Read a variable that must be present and non-blank."""
    value = env(name)
    if not value:
        raise ConfigError("{0} is required but not set".format(name))
    return value


def require_env_any(*names: str) -> str:
    """Return the first variable that is set among `names`.

    This is useful when an external protocol explicitly defines ordered aliases.
    The caller owns that ordering; this helper does not define compatibility
    names or defaults itself.
    """
    if not names:
        raise ConfigError("require_env_any needs at least one variable name")
    for name in names:
        value = env(name)
        if value:
            return value
    raise ConfigError(
        "none of these environment variables is set: {0}".format(", ".join(names))
    )


_TRUE_VALUES = frozenset(("1", "true", "yes", "y", "on"))
_FALSE_VALUES = frozenset(("0", "false", "no", "n", "off"))


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean flag.

    Accepts the spellings the existing tasks already use. An unrecognised value
    is an error rather than silently false: `OVERWRITE=maybe` should not quietly
    mean "do not overwrite".
    """
    value = env(name).lower()
    if not value:
        return default
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ConfigError(
        "{0} must be a boolean (got {1!r}); use one of {2}".format(
            name, value, sorted(_TRUE_VALUES | _FALSE_VALUES)
        )
    )


def env_int(name: str, default: Optional[int] = None) -> int:
    """Read an integer. Without a default, the variable is required."""
    value = env(name)
    if not value:
        if default is None:
            raise ConfigError("{0} is required but not set".format(name))
        return default
    try:
        return int(value)
    except ValueError:
        raise ConfigError("{0} must be an integer, got {1!r}".format(name, value))


def env_float(name: str, default: Optional[float] = None) -> float:
    """Read a float. Without a default, the variable is required."""
    value = env(name)
    if not value:
        if default is None:
            raise ConfigError("{0} is required but not set".format(name))
        return default
    try:
        return float(value)
    except ValueError:
        raise ConfigError("{0} must be a number, got {1!r}".format(name, value))


def require_pg_env() -> None:
    """Validate the PostgreSQL variables and default PGPORT.

    GDAL tools and psycopg both read these from the environment, so tasks only
    need them to be present and correct.
    """
    for name in ("PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD"):
        require_env(name)
    os.environ.setdefault("PGPORT", "5432")
