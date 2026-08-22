"""What git says has changed below a directory.

Its own module because two callers need the *same* answer: the CLI takes a
run's baseline when the run starts, and the verify flow's guard reads the tree
again after a repair pass. A second implementation of the same git call would
drift in exactly the parsing details this file exists for, and the two answers
would then be compared against each other.

Below the harness on purpose: it raises its own error and knows nothing about
flows, exit codes or runs, so `ultraloom check` may import it (spec 15.2).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class WorktreeError(RuntimeError):
    """Raised when git cannot answer what changed. Never read as "nothing"."""


def changed_files(root: Path) -> tuple[str, ...]:
    """Every path git reports as changed, added or untracked below `root`.

    `status` and not `diff`, because a repairer may add a file, and an
    untracked file is invisible to `diff`. `-z` because a path holding
    non-ASCII comes back quoted otherwise, and `-uall` because the default
    collapses a whole untracked directory into one entry that is not a path to
    any file.
    """
    try:
        result = subprocess.run(
            ("git", "status", "--porcelain", "-z", "-uall"),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as error:
        # A directory that is not there never reaches a return code: the spawn
        # itself fails. Same answer as a non-zero one -- see below.
        raise WorktreeError(f"cannot inspect the working tree in {root}: {error}") from error
    if result.returncode != 0:
        # A caller that cannot see the working tree must not carry on as if it
        # had seen an empty one. Reading an unanswerable question as "nothing
        # changed" would disable exactly the rules this answer feeds.
        raise WorktreeError(f"cannot inspect the working tree in {root}: {result.stderr.strip()}")
    return _parse_status(result.stdout)


def _parse_status(output: str) -> tuple[str, ...]:
    """The paths out of a `--porcelain -z` answer, read field by field.

    Most fields are "XY path". A rename or a copy is the exception: git emits
    *two* fields for it, and only the first carries the three-character prefix
    -- the second is the original path, bare. Cutting three characters off that
    one too would turn "tests/test_cli.py" into "s/test_cli.py", and a test
    renamed out of the way would walk straight past the guard.
    """
    fields = [field for field in output.split("\0") if field]
    paths: list[str] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        paths.append(field[3:])
        index += 1
        if field[:1] in ("R", "C") and index < len(fields):
            paths.append(fields[index])
            index += 1
    return tuple(paths)
