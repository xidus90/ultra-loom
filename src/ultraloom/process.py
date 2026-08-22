"""Running one child process so that a hung tool costs its timeout and no more.

subprocess.run cannot do this. On a timeout it kills the direct child and then
calls communicate(), which waits for the pipes to close -- and a surviving
grandchild holds those same pipe ends open. The run then hangs at exactly the
point the timeout existed to prevent. Every check command in this project has
that shape: `uv run pytest` is a chain of at least two processes, and so is a
Godot launcher, and so is anything behind an [exec].prefix.

The answer is to never wait on a pipe: two threads drain stdout and stderr as
the process writes them, so the output is already collected before anything is
killed.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

# How long the draining threads get after the tree has been killed. They are
# reading from pipes nobody should be holding any more; if they are still
# blocked after this, something out there survived and the run gives up on the
# rest of the output rather than on itself.
DRAIN_GRACE = 5.0

type TerminateTree = Callable[[subprocess.Popen[bytes]], None]


@dataclass(frozen=True, slots=True)
class Completed:
    """What the process said, and whether it was allowed to finish saying it."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    # A draining thread that never came back: some descendant still holds the
    # pipe. Named in the result so a truncated capture does not read as a
    # command that simply said little.
    output_abandoned: bool = False


def run(argv: Sequence[str], *, cwd: Path, timeout: float) -> Completed:
    """Run one command to completion, or kill it when the timeout runs out."""
    process = subprocess.Popen(
        tuple(argv),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    captured: dict[str, bytes] = {}
    drains = tuple(
        _drain(stream, name, captured)
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))
    )

    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_tree(process)
        process.wait()

    abandoned = False
    for thread in drains:
        thread.join(DRAIN_GRACE)
        if thread.is_alive():
            abandoned = True

    return Completed(
        returncode=process.returncode,
        stdout=_text(captured.get("stdout", b"")),
        stderr=_text(captured.get("stderr", b"")),
        timed_out=timed_out,
        output_abandoned=abandoned,
    )


def _drain(
    stream: IO[bytes] | None,
    name: str,
    captured: dict[str, bytes],
) -> threading.Thread:
    """One daemon thread emptying one pipe into `captured`.

    Daemon, because an abandoned thread must not keep the interpreter alive:
    the whole point of this module is that one stuck descendant cannot hold the
    run hostage.
    """
    # Popen types both pipes as optional; they were just requested, so this is
    # a shape check, not a case that can happen.
    assert stream is not None

    def pump() -> None:
        with stream:
            captured[name] = stream.read()

    thread = threading.Thread(target=pump, daemon=True, name=f"ultraloom-{name}")
    thread.start()
    return thread


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    """Kill the process. Task 2 replaces this with a kill of the whole tree."""
    process.kill()


def _text(raw: bytes) -> str:
    """Whatever the tool wrote, never an exception about how it wrote it.

    Newlines are translated the way `text=True` would have done it, because the
    callers this module replaces read line-oriented tool output and must not
    start seeing a stray \\r at the end of every line on Windows.
    """
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
