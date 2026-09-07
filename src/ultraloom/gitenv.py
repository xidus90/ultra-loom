"""Git's own environment, kept out of ultraloom's git calls.

Its own module, and a leaf one: `process` needs it for every child it starts,
`worktree` for every question it asks git, and `import ultraloom.cli` may not
pay for `ctypes` on the way (tests/test_cli_imports.py). So the list does not
live in `process`, whose Windows machinery brings ctypes with it.

The mirror image on the Go side is `internal/gitenv`. Two languages, two
copies -- unavoidable, and the reason both carry the same reasoning in full.
"""

from __future__ import annotations

from collections.abc import Mapping

# What git exports to every hook it runs, and what has to be taken back out
# before a child of ours starts.
#
# Each of these names a repository, an index or an object store, and each of
# them *outranks* the directory a call is given to work in: a git call with
# `cwd` set to one repository still answers about the one these point at.
# Measured on 2026-09-07 out of a worktree, where GIT_DIR is absolute -- in the
# main checkout it is the relative `.git`, which resolves inside a scratch
# repository by luck and hides the whole effect: `.githooks/pre-commit` handed
# `go test` a pointer to the repository being committed, three tests in
# cmd/init read that one instead of their own, and `git rev-parse
# --absurd-flag` came back a success.
#
# A named list rather than a GIT_ prefix cut: GIT_AUTHOR_NAME, GIT_EDITOR and
# GIT_TERMINAL_PROMPT are the user's settings and none of our business.
GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_PREFIX",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def without_location(parent: Mapping[str, str]) -> dict[str, str]:
    """`parent` without the variables in `GIT_LOCATION_VARS`.

    Takes the environment rather than reading it, so the decision is testable
    without a process to inherit from.
    """
    return {key: value for key, value in parent.items() if key not in GIT_LOCATION_VARS}
