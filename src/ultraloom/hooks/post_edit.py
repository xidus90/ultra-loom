"""Formats the file that was just written and reports what is left over.

Exit 2 blocks nothing here -- the tool has already run. It is how the finding
reaches the file that caused it, instead of surfacing forty seconds later in
the stop gate with nothing to connect it to.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, TextIO

from ultraloom import process
from ultraloom.checks import UNAVAILABLE, run_kinds
from ultraloom.config import Config, ConfigError, kinds_for, load_config
from ultraloom.hooks.payload import EXIT_BLOCKED, EXIT_INTERNAL, EXIT_OK, PayloadError
from ultraloom.hooks.payload import read as read_payload

# The profile this hook runs. Named here and not spelled out as kinds: a
# project that wants something else from an edit says so in its config.
PROFILE = "edit"

# What `ruff format` understands. A notebook is JSON, and a formatter that
# does not understand a file does not tidy it -- it breaks it.
_FORMATTED = (".py", ".pyi")

# `uvx`, the same way the Python lint preset reaches for ruff: the hook then
# needs nothing of the project but the file itself, and works in a checkout
# that has no environment built yet. A project that pins its own ruff pins it
# for `lint` too, and the two are one tool -- a version difference shows up as
# a lint finding in this very run, never as a file quietly reformatted twice.
_FORMATTER = ("uvx", "ruff", "format")


def formats(path: Path) -> bool:
    """Whether the formatter may touch this file."""
    return path.suffix in _FORMATTED


def run(stdin: TextIO, root: Path, stderr: TextIO) -> int:
    """Format, then check. Findings go to stderr for the agent to read."""
    try:
        payload = read_payload(stdin)
    except PayloadError as error:
        print(f"ultraloom hook post-edit: {error}", file=stderr)
        return EXIT_INTERNAL

    written = _written_path(payload.get("tool_input"), root)
    if written is None:
        return EXIT_OK

    try:
        config = load_config(root)
    except ConfigError as error:
        # Exit 1, not 2: a broken [verify] table is not this file's fault, and
        # a finding the agent cannot act on is noise at the wrong moment.
        print(f"ultraloom hook post-edit: {error}", file=stderr)
        return EXIT_INTERNAL

    return _check(written, config, stderr)


def _written_path(tool_input: Any, root: Path) -> Path | None:
    """The file this call wrote, if it wrote one inside the project."""
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "notebook_path"):
        raw = tool_input.get(key)
        if isinstance(raw, str):
            path = Path(raw)
            try:
                path.resolve().relative_to(root.resolve())
            except ValueError:
                return None
            return path
    return None


def _check(written: Path, config: Config, stderr: TextIO) -> int:
    """Format the file, run the profile over the project, report what is red."""
    if formats(written):
        complaint = _format(written, config)
        if complaint is not None:
            # A formatter that cannot run says nothing about the file, so it is
            # exit 1. It stops the hook all the same: checking source the
            # formatter did not get to would report findings about a shape
            # nobody chose.
            print(f"ultraloom hook post-edit: {complaint}", file=stderr)
            return EXIT_INTERNAL

    try:
        kinds = kinds_for(config, PROFILE)
    except ConfigError as error:
        # A project without an `edit` profile is told so, and the hook ends at
        # 1. Exit 0 would be the worst of the three: it would report "nothing
        # wrong" about a file that nothing looked at, which is the one failure
        # this chain exists to rule out. Exit 2 would be wrong the other way --
        # a missing profile is not a finding about the file.
        print(f"ultraloom hook post-edit: {error}", file=stderr)
        return EXIT_INTERNAL

    try:
        results = run_kinds(kinds, config)
    except ConfigError as error:
        # The scheduler is the first reader of the *effective* check order, so
        # a ring between the project's edges and the preset's shows up here,
        # long after load_config was happy.
        print(f"ultraloom hook post-edit: {error}", file=stderr)
        return EXIT_INTERNAL

    red = tuple(result for result in results if not result.ok)
    if not red:
        return EXIT_OK
    for result in red:
        print(f"{result.kind}: {result.output}", file=stderr)
    if all(result.source == UNAVAILABLE for result in red):
        # `all`, not `any`: only a chain that said nothing usable at all is no
        # verdict about the file. One unavailable check beside a real finding
        # must not swallow it -- a project that legitimately has no such check
        # (GDScript has no typechecker, so `types` resolves to nothing on every
        # single run) would otherwise never be able to block. Reported with the
        # rest above either way, because the agent still has to see which check
        # is missing -- but not as a finding it could repair.
        return EXIT_INTERNAL
    return EXIT_BLOCKED


def _format(written: Path, config: Config) -> str | None:
    """Run the formatter over one file; the message if it refused, else None.

    Through `process.run` and the project's [exec].prefix like every check
    command, and not a subprocess call of its own: a project that checks across
    a container boundary must format on the same side of it, or the formatter
    reaches a file the checks never see.
    """
    argv = (*config.exec_prefix, *_FORMATTER, str(written))
    try:
        completed = process.run(argv, cwd=config.root, timeout=config.timeout)
    except OSError as error:
        return f"could not run {shlex.join(argv)!r}: {error}"
    if completed.timed_out:
        return f"{shlex.join(argv)!r} timed out after {config.timeout}s"
    if completed.returncode != 0:
        return f"{shlex.join(argv)!r} exited {completed.returncode}\n{completed.stderr}"
    return None
