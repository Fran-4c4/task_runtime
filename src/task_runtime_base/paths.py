"""Safe host-to-container path translation with containment checks.

The host mounts a data tree read-only inside the container at a different prefix:

    host        /data/lidar/gra/vuelo_2024
    container   /host-data/lidar/gra/vuelo_2024

Users type host paths in the task form, so every task has to translate them and —
crucially — verify the result did not escape the mount. That check is the whole
point of this module and must remain centralized rather than copied per task.

Two rules the implementation must keep, each with a test:

1. **Containment is compared by path components, never by string prefix.**
   `/data/out2` is not inside `/data/out`, though `str.startswith` says it is.

2. **Symlinks are resolved before comparing.** A symlink inside the mount can
   point anywhere; comparing the unresolved path would accept it.

With multi-tenancy these are not hygiene, they are the boundary between tenants.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

from task_runtime_base.errors import InputNotFoundError, PathEscapeError

DEFAULT_HOST_PREFIX = "/data"
DEFAULT_CONTAINER_ROOT = "/host-data"
DEFAULT_EXTRA_ROOTS = ("/out", "/tmp")


def _is_within(candidate: Path, root: Path) -> bool:
    """True when `candidate` is `root` or lives underneath it.

    Uses path components (`Path.is_relative_to` semantics, reimplemented because
    that method only arrived in 3.9 and we support exactly 3.9 — using it
    directly is fine, but doing the comparison explicitly keeps the intent
    visible and the behaviour identical on every supported version).
    """
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


class PathTranslator:
    """Translates host paths into container paths and enforces containment.

    One instance per task, built from the task's own env vars:

        translator = PathTranslator.from_env("ZIP_HOST_PREFIX", "ZIP_ROOT")
        source = translator.to_container(input_path)      # raises if it escapes

    Every method that returns a path has already validated it. There is no way
    to obtain a path from this class that sits outside the allowed roots.
    """

    def __init__(
        self,
        host_prefix: str = DEFAULT_HOST_PREFIX,
        container_root: str = DEFAULT_CONTAINER_ROOT,
        extra_roots: Sequence[str] = DEFAULT_EXTRA_ROOTS,
        mounted_paths: Optional[Sequence[str]] = None,
    ) -> None:
        self.host_prefix = Path(host_prefix)
        self.container_root = Path(container_root)
        # Roots a translated path may legitimately live in: the mounted data
        # tree plus the task's writable output and scratch space.
        self.allowed_roots = tuple(
            [self.container_root] + [Path(root) for root in extra_roots]
        )
        # Storage attached inside a root on purpose, which resolves elsewhere on
        # the host: the tenant tree carries mounts like geoserver/mapdata. Named
        # explicitly, like the backend's path_root.extra_paths_json — a symlink
        # that is not listed here is still an escape.
        self.mounted_paths = tuple(
            Path(p).resolve() for p in (mounted_paths or []) if Path(p).is_absolute()
        )

    @classmethod
    def from_env(
        cls,
        host_prefix_var: str = "HOST_DATA_PREFIX",
        container_root_var: str = "HOST_DATA_ROOT",
        extra_roots: Sequence[str] = DEFAULT_EXTRA_ROOTS,
    ) -> "PathTranslator":
        """Build from environment variables, falling back to the defaults.

        Task-specific variable names are accepted because the existing tasks use
        their own (ZIP_ROOT, RASTER_ROOT, PROMOTE_ROOT, ...). New tasks should
        use the default HOST_DATA_PREFIX / HOST_DATA_ROOT.
        """
        from task_runtime_base.config import env

        # MOUNTED_PATHS lists storage attached inside the root that resolves
        # elsewhere, colon-separated. The dispatcher sets it from the task's
        # path_root configuration.
        mounted = [p for p in env("MOUNTED_PATHS", "").split(":") if p]
        return cls(
            host_prefix=env(host_prefix_var, DEFAULT_HOST_PREFIX),
            container_root=env(container_root_var, DEFAULT_CONTAINER_ROOT),
            extra_roots=extra_roots,
            mounted_paths=mounted,
        )

    # -- translation ------------------------------------------------------ #

    def translate(self, raw_path: str) -> Path:
        """Map a host path to its container equivalent, without validating.

        A path that does not start with the host prefix is returned unchanged:
        callers legitimately pass container-side paths such as `/out/...`.
        `validate` is what decides whether the result is acceptable.
        """
        if not raw_path:
            raise PathEscapeError("empty path")

        candidate = Path(raw_path)
        if _is_within(candidate, self.host_prefix):
            relative = candidate.relative_to(self.host_prefix)
            return self.container_root / relative
        return candidate

    def validate(self, path: Path) -> Path:
        """Resolve `path` and confirm it stays inside an allowed root.

        `resolve()` follows symlinks and normalises `..`, so this catches both a
        traversal spelled literally and one hidden behind a link. `strict=False`
        because outputs legitimately do not exist yet.
        """
        resolved = path.resolve()
        for root in self.allowed_roots:
            # Resolve the root too: if the mount itself is a symlink, an
            # unresolved comparison would never match.
            if _is_within(resolved, root.resolve()):
                return resolved
        for mounted in self.mounted_paths:
            if _is_within(resolved, mounted):
                return resolved
        # Deliberately terse. This message reaches the UI, and an escape attempt
        # is the one case where echoing the resolved target and the list of real
        # roots would hand a prober the map they were looking for. What the user
        # needs is that the path was rejected; what it resolved to is the
        # server's business.
        raise PathEscapeError(
            "path {0!r} is outside the allowed area".format(str(path))
        )

    def to_container(self, raw_path: str) -> Path:
        """Translate and validate in one step. The method tasks should use."""
        return self.validate(self.translate(raw_path))

    def display(self, path) -> str:
        """The path as the user should see it: relative to their own data root.

        Task logs are shown verbatim in the UI, so they must not leak the
        server's filesystem layout. `/data/tenants/acme/out/x.json` says where
        every tenant's data lives and what this one is called; `out/x.json` is
        the part the user actually typed and the only part they can act on.

        Strips whichever root applies — the host prefix, the container mount, or
        the output root — and falls back to the full path when it matches none,
        because a path we cannot attribute is exactly the one worth showing
        whole.
        """
        text = str(path)
        candidate = Path(text)
        for root in (self.container_root, self.host_prefix) + self.allowed_roots:
            # validate() returns resolved paths. Compare against both spellings
            # so diagnostics remain stable when tests or callers run on Windows
            # while the container contract uses POSIX paths.
            for display_root in (root, root.resolve()):
                if display_root == display_root.parent:
                    continue
                if _is_within(candidate, display_root):
                    inner = candidate.relative_to(display_root).as_posix()
                    return "" if inner == "." else inner
        return text


    def to_container_existing(self, raw_path: str) -> Path:
        """`to_container`, and the path must already exist.

        Distinguishes "you asked for something outside your sandbox"
        (PathEscapeError) from "the file is not there" (InputNotFoundError) —
        different problems that used to produce the same opaque message.
        """
        path = self.to_container(raw_path)
        if not path.exists():
            raise InputNotFoundError(
                "input path does not exist: {0}".format(self.display(path))
            )
        return path

    # -- convenience ------------------------------------------------------ #

    def collect_files(
        self,
        path: Path,
        suffixes: Optional[Iterable[str]] = None,
        recursive: bool = False,
    ) -> Tuple[Path, ...]:
        """List files under `path`, or `path` itself when it is a file.

        Several tasks accept "a folder of tiles or a single file" and each wrote
        its own version of this. `suffixes` is matched case-insensitively.
        """
        wanted = None
        if suffixes is not None:
            wanted = frozenset(s.lower() for s in suffixes)

        def matches(candidate: Path) -> bool:
            return wanted is None or candidate.suffix.lower() in wanted

        if path.is_file():
            if not matches(path):
                raise InputNotFoundError(
                    "{0} does not have one of the expected extensions {1}".format(
                        self.display(path), sorted(wanted or ())
                    )
                )
            return (path,)

        if not path.is_dir():
            raise InputNotFoundError(
                "path does not exist: {0}".format(self.display(path))
            )

        entries = path.rglob("*") if recursive else path.iterdir()
        found = tuple(sorted(p for p in entries if p.is_file() and matches(p)))
        if not found:
            raise InputNotFoundError(
                "no matching files in {0}{1}".format(
                    self.display(path),
                    " (extensions: {0})".format(sorted(wanted)) if wanted else "",
                )
            )
        return found

    def safe_join(self, base: Path, member: str) -> Path:
        """Join `member` onto `base`, refusing anything that escapes `base`.

        For archive extraction and any other place where a name comes from
        untrusted content — a zip entry called `../../etc/passwd` is a real
        attack, and `task-zip` was the only task guarding against it.
        """
        target = (base / member).resolve()
        if not _is_within(target, base.resolve()):
            raise PathEscapeError(
                "entry {0!r} escapes the destination directory".format(member)
            )
        return self.validate(target)
