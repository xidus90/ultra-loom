"""Tests for running one child process without ever waiting on a dead pipe."""

from __future__ import annotations

import ctypes
import io
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ultraloom import process as process_module
from ultraloom.process import (
    NO_EXIT_CODE,
    Completed,
    _could_be_a_descendant,
    _descendants,
    _drain,
    _kill_job_then_strays,
    _release_job,
    _resumed_enough,
    _sweep_or_nothing,
    _terminate_posix,
    _terminate_windows,
    _usable_handle,
    run,
    spawn_kwargs,
    terminator,
)

# INVALID_HANDLE_VALUE as ctypes hands it back from a c_void_p restype: (HANDLE)
# -1, unsigned. Computed the same way the module does, because the width of a
# pointer is the whole point of the value.
_INVALID_HANDLE = ctypes.c_void_p(-1).value

# ResumeThread's answer for "could not": (DWORD) -1.
_RESUME_FAILED = 0xFFFFFFFF

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


def test_it_keeps_what_a_killed_tree_had_already_written(tmp_path: Path) -> None:
    """Reading to EOF would hold every byte inside read() until the pipe closes.

    Here it closes only because the whole tree is killed. What the command
    managed to say before that must survive: it is the case the user most needs
    to see. That the same output survives when the reader has to be *given up
    on* is a separate promise, tested in
    `test_a_reader_that_never_returns_still_hands_over_what_it_read`.
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


def test_a_reader_that_never_returns_still_hands_over_what_it_read() -> None:
    """The promise the chunk list exists for: abandoned must mean cut off, not lost.

    The pipe here never closes, exactly like one an escaped descendant still
    holds. `run` gives such a reader up after DRAIN_GRACE, and everything read
    before that has to be readable from the main thread anyway.
    """
    released = threading.Event()

    class Blocking(io.BufferedReader):
        def __init__(self) -> None:
            super().__init__(io.BytesIO(b""))
            self.handed_over = False

        def read1(self, size: int = -1, /) -> bytes:
            if not self.handed_over:
                self.handed_over = True
                return b"said this much"
            released.wait(30)
            return b""

    drain = _drain(Blocking(), "stdout")
    try:
        drain.thread.join(0.5)
        assert drain.abandoned, "a reader still inside read1 counts as abandoned"
        assert drain.text() == "said this much"
    finally:
        released.set()
        drain.thread.join(5)


def test_a_failure_on_the_way_to_the_wait_leaves_no_process_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C1: on Windows the process is suspended at that point and would never run out.

    Adoption or the resume can fail. A raise that walks away from a suspended
    process leaves it standing until the machine reboots, holding both pipes --
    one such process per check command.
    """

    def exploding(stream: object, name: str) -> None:
        raise RuntimeError("adoption failed")

    spawned = _remember_spawned(monkeypatch)
    monkeypatch.setattr(process_module, "_drain", exploding)

    with pytest.raises(RuntimeError, match="adoption failed"):
        run(_python("import time; time.sleep(30)"), cwd=tmp_path, timeout=30)

    assert spawned[0].poll() is not None, "the child outlived the failure that started it"


def test_a_kill_that_does_not_take_is_reported_rather_than_waited_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C2: an unbounded wait after a failed kill is the hang, one line further down."""
    spawned = _remember_spawned(monkeypatch)
    monkeypatch.setattr(process_module, "DRAIN_GRACE", 0.5)
    monkeypatch.setattr(process_module, "terminator", lambda platform: lambda process: None)

    try:
        started = time.monotonic()
        completed = run(_python("import time; time.sleep(30)"), cwd=tmp_path, timeout=1)
        elapsed = time.monotonic() - started

        assert completed.timed_out
        assert completed.returncode == NO_EXIT_CODE
        assert elapsed < 20, f"run() waited {elapsed:.1f}s on a kill that never took"
    finally:
        # The terminator was a no-op, so nobody else is going to do this.
        _reap(spawned)


def test_a_terminator_that_raises_does_not_leave_the_child_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N2: a throwing terminator used to be called twice and then give up.

    The second call had the same cause as the first, so the exception left
    run() -- with a process behind it that on Windows may never even have been
    resumed.
    """
    spawned = _remember_spawned(monkeypatch)

    def refusing(platform: str) -> object:
        def terminate(process: subprocess.Popen[bytes]) -> None:
            raise OSError("the kill did not go through")

        return terminate

    monkeypatch.setattr(process_module, "terminator", refusing)

    try:
        completed = run(_python("import time; time.sleep(30)"), cwd=tmp_path, timeout=1)
        assert completed.timed_out
        assert spawned[0].poll() is not None, "the child outlived a terminator that threw"
    finally:
        _reap(spawned)


def test_the_walk_finds_every_generation() -> None:
    assert sorted(_descendants(1, [(2, 1), (3, 2), (4, 3)])) == [2, 3, 4]


def test_the_walk_leaves_other_peoples_processes_alone() -> None:
    assert _descendants(1, [(2, 99), (3, 98)]) == []


def test_the_walk_survives_a_cycle_in_the_parent_table() -> None:
    """C3: Windows reuses pids, so a pid can end up recorded as its own ancestor."""
    assert sorted(_descendants(1, [(2, 1), (3, 2), (2, 3)])) == [2, 3]


def test_the_walk_never_returns_its_own_root() -> None:
    """The root is killed through its handle; listing it again would be a second kill."""
    assert _descendants(1, [(1, 1), (2, 1)]) == [2]


def test_a_thread_that_was_standing_still_counts_as_resumed() -> None:
    assert _resumed_enough([1])


def test_no_threads_at_all_is_not_a_resume() -> None:
    assert not _resumed_enough([])


def test_a_failed_resume_is_not_a_resume() -> None:
    assert not _resumed_enough([_RESUME_FAILED])


def test_a_thread_that_was_already_running_is_not_a_resume() -> None:
    """I4: ResumeThread answers 0 there, and 0 would otherwise pass for success."""
    assert not _resumed_enough([0])


def test_the_module_imports_where_ctypes_has_no_windows_half() -> None:
    """S1: on POSIX `import ctypes.wintypes` raises, and so would this module.

    Simulated rather than skipped, because the machine this is measured on is
    the one that cannot notice the mistake: ctypes.wintypes is made
    unimportable and the Windows-only ctypes names are removed, which is the
    shape ctypes has on Linux and macOS. If the module can still be imported
    and still answers for the POSIX branch, the branch is alive.
    """
    # Every name ctypes and subprocess only have on Windows, not merely the
    # ones the module happens to use today: a relapse to ctypes.windll or to
    # subprocess.CREATE_SUSPENDED would otherwise sail straight through here.
    probe = (
        "import ctypes, subprocess, sys;"
        "sys.modules['ctypes.wintypes'] = None;"
        "[delattr(ctypes, n) for n in ("
        "'WinDLL', 'OleDLL', 'WinError', 'windll', 'oledll', 'GetLastError',"
        "'get_last_error', 'set_last_error', 'FormatError', 'WINFUNCTYPE', 'HRESULT')"
        " if hasattr(ctypes, n)];"
        "[delattr(subprocess, n) for n in dir(subprocess)"
        " if n.startswith(('CREATE_', 'DETACHED_', 'ABOVE_', 'BELOW_', 'HIGH_',"
        " 'IDLE_', 'NORMAL_', 'REALTIME_', 'STARTF_', 'STD_', 'SW_'))];"
        "import ultraloom.process as p;"
        "print(p.spawn_kwargs('linux'), p.terminator('linux').__name__)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "{'start_new_session': True} _terminate_posix"


def _remember_spawned(monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen[bytes]]:
    """Hold on to every process run() starts, so a test can clean up after itself."""
    spawned: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def remembering(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        # A pass-through wrapper: the overloads cannot describe *args, and the
        # bytes-mode Popen is the only one run() ever asks for.
        process: subprocess.Popen[bytes] = real_popen(*args, **kwargs)  # type: ignore[call-overload]
        spawned.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", remembering)
    return spawned


def _reap(spawned: list[subprocess.Popen[bytes]]) -> None:
    for process in spawned:
        process.kill()
        process.wait(10)


class _Recorder:
    """Notes what the kill policy did, in the order it did it."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def note(self, event: str) -> None:
        self.events.append(event)


def test_the_sweep_runs_before_the_job_is_killed() -> None:
    """N1: the descendants have to be opened while their parents are still alive.

    A handle held on a process keeps its pid reserved. Collected after the job
    dies, the pids would be free to be handed out again between the walk and
    the kill -- and the sweep would be killing whoever got them.
    """
    recorder = _Recorder()

    def sweep() -> list[int]:
        recorder.note("sweep")
        return [7]

    def job_kill() -> bool:
        recorder.note("job")
        return True

    _kill_job_then_strays(
        sweep=sweep,
        job_kill=job_kill,
        direct_kill=lambda: recorder.note("direct"),
        stray_kill=lambda stray: recorder.note(f"stray {stray}"),
        release=lambda stray: recorder.note(f"release {stray}"),
    )

    assert recorder.events == ["sweep", "job", "stray 7", "release 7"]


def test_a_sweep_that_fails_costs_strays_and_not_the_job() -> None:
    """N1: three syscalls on the way to the strays can fail, none may stop the kill.

    Before this, one unreadable process time meant the job was never terminated
    at all and the whole tree survived.
    """
    recorder = _Recorder()

    def exploding() -> list[int]:
        raise OSError("the snapshot failed")

    def job_kill() -> bool:
        recorder.note("job")
        return True

    _kill_job_then_strays(
        sweep=exploding,
        job_kill=job_kill,
        direct_kill=lambda: recorder.note("direct"),
        stray_kill=lambda stray: recorder.note(f"stray {stray}"),
        release=lambda stray: recorder.note(f"release {stray}"),
    )

    assert recorder.events == ["job"]


def test_a_job_that_refuses_to_die_falls_back_to_the_direct_child() -> None:
    recorder = _Recorder()

    _kill_job_then_strays(
        sweep=lambda: [],
        job_kill=lambda: False,
        direct_kill=lambda: recorder.note("direct"),
        stray_kill=lambda stray: recorder.note(f"stray {stray}"),
        release=lambda stray: recorder.note(f"release {stray}"),
    )

    assert recorder.events == ["direct"]


def test_every_stray_handle_is_given_back_even_when_a_kill_throws() -> None:
    released: list[int] = []

    with pytest.raises(OSError, match="no"):
        _kill_job_then_strays(
            sweep=lambda: [1, 2],
            job_kill=lambda: True,
            direct_kill=lambda: None,
            stray_kill=_raising_stray_kill,
            release=released.append,
        )

    assert released == [1, 2]


def _raising_stray_kill(stray: int) -> None:
    raise OSError("no")


def test_a_failing_sweep_hands_back_no_strays() -> None:
    def exploding() -> list[int]:
        raise OSError("the snapshot failed")

    assert _sweep_or_nothing(exploding) == []


def test_a_working_sweep_is_handed_through() -> None:
    assert _sweep_or_nothing(lambda: [4, 5]) == [4, 5]


def test_a_null_handle_is_not_a_handle() -> None:
    assert not _usable_handle(None)
    assert not _usable_handle(0)


def test_the_invalid_handle_value_is_not_a_handle() -> None:
    """I2: it comes back unsigned, so comparing it against -1 never matched."""
    assert not _usable_handle(_INVALID_HANDLE)
    assert _INVALID_HANDLE != -1, "the whole point: ctypes hands it over unsigned"


def test_a_real_handle_is_a_handle() -> None:
    assert _usable_handle(1136)


def test_a_process_older_than_the_root_cannot_descend_from_it() -> None:
    """I1: a stranger whose dead parent once held a pid from our tree."""
    assert not _could_be_a_descendant(1000, 999)


def test_a_process_younger_than_the_root_may_descend_from_it() -> None:
    assert _could_be_a_descendant(1000, 1001)
    assert _could_be_a_descendant(1000, 1000)


def test_a_candidate_whose_time_cannot_be_read_is_dropped() -> None:
    """Being unsure about a stranger is not a licence to kill it."""
    assert not _could_be_a_descendant(1000, None)


def test_an_unreadable_root_time_drops_the_filter_and_not_the_sweep() -> None:
    """The tree is being killed either way; no filter beats no sweep."""
    assert _could_be_a_descendant(None, 999)
    assert _could_be_a_descendant(None, None)
