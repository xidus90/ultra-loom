"""Tests for running one child process without ever waiting on a dead pipe."""

from __future__ import annotations

import io
import subprocess
import sys
import threading
import time
from pathlib import Path

from ultraloom.process import (
    Completed,
    _drain,
    _release_job,
    _terminate_posix,
    _terminate_windows,
    run,
    spawn_kwargs,
    terminator,
)

# subprocess.CREATE_SUSPENDED exists only on Windows, but its value is a Win32
# constant out of winbase.h and does not depend on where the test runs. Naming
# it here keeps the switch checkable on both platforms rather than skipping half
# of the decision on the half of the machines that cannot execute it.
_CREATE_SUSPENDED = getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)


def _leftover_drain_threads() -> list[str]:
    """Drain threads still alive. Daemons, so they are invisible until counted."""
    return [
        t.name for t in threading.enumerate() if t.name.startswith("ultraloom-") and t.is_alive()
    ]


# A grandchild that outlives its parent and keeps the inherited pipe open. This
# is the shape subprocess.run hangs on: the parent dies, the pipe does not
# close, and communicate() waits for an EOF that never comes.
_ORPHAN = (
    "import subprocess, sys; "
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
    "import time; time.sleep(30)"
)

# The same shape, but with output written before the orphan is left behind.
# This is what a real check looks like when it hangs: pytest has already
# printed its failures, and then something below it refuses to die.
_ORPHAN_AFTER_OUTPUT = "print('before the orphan', flush=True); " + _ORPHAN


def _python(code: str) -> tuple[str, ...]:
    return (sys.executable, "-c", code)


def test_it_reports_what_the_command_said(tmp_path: Path) -> None:
    completed = run(
        _python("import sys; print('out'); print('err', file=sys.stderr)"),
        cwd=tmp_path,
        timeout=30,
    )
    assert completed == Completed(returncode=0, stdout="out\n", stderr="err\n")


def test_it_reports_a_nonzero_exit(tmp_path: Path) -> None:
    completed = run(_python("raise SystemExit(3)"), cwd=tmp_path, timeout=30)
    assert completed.returncode == 3
    assert not completed.timed_out


def test_a_timeout_returns_instead_of_waiting_on_the_orphans_pipe(tmp_path: Path) -> None:
    """The whole point of the module: a hung tool must cost the timeout, not the run."""
    started = time.monotonic()
    completed = run(_python(_ORPHAN), cwd=tmp_path, timeout=1)
    elapsed = time.monotonic() - started

    assert completed.timed_out
    # Generous on purpose -- this is a wall-clock test, and a loaded machine is
    # allowed to be slow. It still fails hard against the old behaviour, which
    # would sit here for the full 30 seconds.
    assert elapsed < 20, f"run() waited {elapsed:.1f}s; a timed-out command must not block the run"
    # Since Task 2 the orphan dies with the tree, so the pipe closes and no
    # reader has to be given up on. Asserted rather than left open: a capture
    # that is silently short is the failure this module was written against.
    assert not completed.output_abandoned


def test_it_keeps_the_output_of_a_command_whose_reader_had_to_be_abandoned(tmp_path: Path) -> None:
    """The regression this module exists for: abandoned must mean cut off, not lost.

    Reading to EOF would hold every byte inside read() until the pipe closes --
    and here it never does, because the orphan keeps its end open. The output
    would be thrown away in exactly the case the user most needs to see it.
    """
    completed = run(_python(_ORPHAN_AFTER_OUTPUT), cwd=tmp_path, timeout=1)

    assert completed.timed_out
    assert not completed.output_abandoned
    assert "before the orphan" in completed.stdout


def test_a_reader_that_dies_is_reported_and_not_read_as_silence() -> None:
    """A dead pump must never look like a tool that exited cleanly saying nothing."""

    class Exploding(io.BufferedReader):
        def __init__(self) -> None:
            super().__init__(io.BytesIO(b""))

        def read1(self, size: int = -1, /) -> bytes:
            raise OSError("the pipe went away")

    drain = _drain(Exploding(), "stdout")
    drain.thread.join(5)

    assert not drain.thread.is_alive()
    assert drain.abandoned
    assert drain.text() == ""


def test_it_keeps_what_a_timed_out_command_managed_to_write(tmp_path: Path) -> None:
    completed = run(
        _python("print('before the hang', flush=True); import time; time.sleep(30)"),
        cwd=tmp_path,
        timeout=1,
    )
    assert "before the hang" in completed.stdout


def test_a_large_output_does_not_deadlock_the_pipe(tmp_path: Path) -> None:
    """Without draining threads a chatty tool fills the pipe buffer and stops."""
    completed = run(
        _python("print('x' * 200_000)"),
        cwd=tmp_path,
        timeout=60,
    )
    assert completed.returncode == 0
    assert len(completed.stdout) > 200_000


def test_it_runs_in_the_directory_it_was_given(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("here", encoding="utf-8")
    completed = run(
        _python("print(open('marker.txt').read())"),
        cwd=tmp_path,
        timeout=30,
    )
    assert "here" in completed.stdout


# The grandchild itself: it writes to the file it was given, forever.
_TICKER = "import time\nwhile True:\n    open('tick.txt', 'a').write('.')\n    time.sleep(0.1)"

# A parent that spawns that grandchild and then hangs. If the grandchild
# survives the timeout, the file keeps growing after run() returned -- which is
# exactly the bug being fixed.
_TICKING_GRANDCHILD = (
    "import subprocess, sys, time; "
    f"subprocess.Popen([sys.executable, '-c', {_TICKER!r}]); "
    "time.sleep(30)"
)


def test_the_switch_answers_for_both_platforms() -> None:
    """Selectable on any machine: the choice is testable, only the syscall is not."""
    assert terminator("win32") is _terminate_windows
    assert terminator("linux") is _terminate_posix
    assert terminator("darwin") is _terminate_posix


def test_posix_asks_for_its_own_session() -> None:
    assert spawn_kwargs("linux") == {"start_new_session": True}


def test_windows_starts_suspended() -> None:
    """Suspended, so no fast child can spawn a grandchild before the job exists."""
    flags = spawn_kwargs("win32")["creationflags"]
    assert isinstance(flags, int)
    assert flags & _CREATE_SUSPENDED


def test_a_timeout_kills_the_grandchild_too(tmp_path: Path) -> None:
    # Generous on purpose: two interpreter startups have to fit inside the
    # timeout, or the grandchild is not yet there to survive anything.
    completed = run(_python(_TICKING_GRANDCHILD), cwd=tmp_path, timeout=5)

    tick = tmp_path / "tick.txt"
    assert tick.exists(), f"the grandchild never started: {completed}"
    before = tick.stat().st_size
    time.sleep(1.5)
    assert tick.stat().st_size == before, "the grandchild outlived the timeout"
    # Finding 2 from the Task 1 review: with the whole tree gone, nobody holds
    # the pipe any more, so no reader has to be abandoned and none piles up.
    assert not completed.output_abandoned
    assert not _leftover_drain_threads()


def test_a_timed_out_run_leaves_no_reader_behind(tmp_path: Path) -> None:
    """Abandoned readers used to accumulate over a run; a working tree kill ends that."""
    run(_python(_ORPHAN), cwd=tmp_path, timeout=1)
    assert not _leftover_drain_threads()


def test_a_process_without_a_job_is_still_killed(tmp_path: Path) -> None:
    """Adoption can fail, and on POSIX there is no job at all: kill the child anyway."""
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=tmp_path)
    try:
        _terminate_windows(process)
        assert process.wait(10) != 0
    finally:
        process.kill()


def test_releasing_a_job_that_was_never_created_is_harmless(tmp_path: Path) -> None:
    process = subprocess.Popen([sys.executable, "-c", ""], cwd=tmp_path)
    process.wait(10)
    _release_job(process)
