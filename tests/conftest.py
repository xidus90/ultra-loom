"""What every test in this suite may take for granted.

The one thing here is git's environment. The suite builds scratch
repositories all over the place -- `git init` in a `tmp_path`, then a commit,
then a question -- and every one of those calls inherits this process's
environment. Git exports GIT_DIR and its relatives to every hook it runs, and
they outrank the working directory a call is given: a fixture would then write
its configuration into the repository whose hook is running and measure against
a scratch repository nothing ever reached.

Measured on 2026-09-07: with an absolute GIT_DIR in the environment, 60 tests
across eight files failed, and `git rev-parse --absurd-flag` reported success.
The production code strips the same variables (`ultraloom.gitenv`), so the
suite is not what protects the gate -- but a suite whose answer depends on
where it was started measures the wrong thing, and here it did so silently.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from ultraloom.gitenv import GIT_LOCATION_VARS


@pytest.fixture(autouse=True, scope="session")
def _without_gits_repository_pointers() -> Iterator[None]:
    """Take git's own pointers out of the environment for the whole session."""
    removed = {name: os.environ.pop(name) for name in GIT_LOCATION_VARS if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(removed)
