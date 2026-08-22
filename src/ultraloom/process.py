"""Running one child process so that a hung tool costs its timeout and no more.

subprocess.run cannot do this. On a timeout it kills the direct child and then
calls communicate(), which waits for the pipes to close -- and a surviving
grandchild holds those same pipe ends open. The run then hangs at exactly the
point the timeout existed to prevent. Every check command in this project has
that shape: `uv run pytest` is a chain of at least two processes, and so is a
Godot launcher, and so is anything behind an [exec].prefix.

The answer is to never wait on a pipe: two threads drain stdout and stderr
chunk by chunk as the process writes them, into buffers the main thread can
read. So the output is already in hand before anything is killed -- and still
in hand when a reader has to be given up on, which is the case this module was
written for.
"""

from __future__ import annotations

import io
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, cast

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
    # A reader that never came back -- some descendant still holds the pipe --
    # or one that died on the way. Named in the result so a truncated capture
    # does not read as a command that simply said little.
    output_abandoned: bool = False


def run(argv: Sequence[str], *, cwd: Path, timeout: float) -> Completed:
    """Run one command to completion, or kill it when the timeout runs out."""
    process = subprocess.Popen(
        tuple(argv),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out = _drain(process.stdout, "stdout")
    err = _drain(process.stderr, "stderr")

    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_tree(process)
        process.wait()

    for drain in (out, err):
        drain.thread.join(DRAIN_GRACE)

    return Completed(
        returncode=process.returncode,
        stdout=out.text(),
        stderr=err.text(),
        timed_out=timed_out,
        output_abandoned=out.abandoned or err.abandoned,
    )


@dataclass(frozen=True, slots=True)
class _Drain:
    """One pipe, the thread emptying it, and what that thread has read so far.

    The chunks live here rather than inside a `read()` call precisely so the
    main thread can still get at them when the reader has to be abandoned.
    A list of chunks, not a growing buffer: `list.append` is one bytecode, so
    a snapshot taken while the reader is still running is a prefix of the
    output and never a half-written line.
    """

    thread: threading.Thread
    chunks: list[bytes]
    failed: threading.Event

    @property
    def abandoned(self) -> bool:
        """True when the capture may be short: the reader is stuck, or it died."""
        return self.thread.is_alive() or self.failed.is_set()

    def text(self) -> str:
        return _text(b"".join(self.chunks[:]))


def _drain(stream: IO[bytes] | None, name: str) -> _Drain:
    """Start one daemon thread emptying one pipe, chunk by chunk.

    Daemon, because an abandoned thread must not keep the interpreter alive:
    the whole point of this module is that one stuck descendant cannot hold the
    run hostage.
    """
    # pragma: both pipes were just requested, so None would mean a broken Popen.
    if stream is None:  # pragma: no cover  # see above
        raise RuntimeError(f"{name} was not piped")

    # Popen types the pipe as IO[bytes], but at the default bufsize it really is
    # a BufferedReader -- and only that offers read1(), which returns what has
    # arrived instead of waiting for EOF. Reading in chunks is the whole point:
    # read() would keep every byte inside the call until the pipe closes, and in
    # the case this module exists for it never does.
    reader = cast("io.BufferedReader", stream)
    chunks: list[bytes] = []
    failed = threading.Event()

    def pump() -> None:
        # Anything at all, because a reader that dies quietly is the one failure
        # this module must never have: an empty capture next to a zero exit code
        # reads as a tool that passed and said nothing.
        try:
            with reader:
                while chunk := reader.read1():
                    chunks.append(chunk)
        except Exception:
            failed.set()

    thread = threading.Thread(target=pump, daemon=True, name=f"ultraloom-{name}")
    thread.start()
    return _Drain(thread=thread, chunks=chunks, failed=failed)


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
