"""Tests for running one child process without ever waiting on a dead pipe."""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

from ultraloom.process import Completed, _drain, run

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
    # The grandchild still holds the pipe, so the reader had to be given up on.
    # Asserted, not merely reached: this flag is what tells a caller that an
    # empty capture means "cut off" rather than "the tool said nothing".
    assert completed.output_abandoned


def test_it_keeps_the_output_of_a_command_whose_reader_had_to_be_abandoned(tmp_path: Path) -> None:
    """The regression this module exists for: abandoned must mean cut off, not lost.

    Reading to EOF would hold every byte inside read() until the pipe closes --
    and here it never does, because the orphan keeps its end open. The output
    would be thrown away in exactly the case the user most needs to see it.
    """
    completed = run(_python(_ORPHAN_AFTER_OUTPUT), cwd=tmp_path, timeout=1)

    assert completed.timed_out
    assert completed.output_abandoned
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
