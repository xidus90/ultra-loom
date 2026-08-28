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

The other half is that a timeout must reach the whole tree, not just the direct
child: a killed parent whose grandchild lives on is a check that reports a
timeout and leaves a process behind holding the pipe. POSIX gets a session of
its own and one killpg; Windows gets a job object, plus a sweep of the
descendants for the processes Windows refuses to put in it. Both are chosen by
`terminator`, which is a plain function so the choice can be tested on a machine
that can only execute one of the two.

Every path out of `run` -- a clean exit that left a descendant holding the pipe,
a timeout, an exception on the way to the wait -- goes through a kill and a
*bounded* reap; only a clean exit with nothing left behind needs none, because
there is nothing left to kill. A process this module started suspended and then
walked away from would sit there until the machine is rebooted, holding two
pipes, one such process per check command.

The intent is that nothing in here leaves a process running, but on Windows that
is not absolute, and the limit belongs where it can be found. The sweep beside
the job walks the (pid, parent pid) table, so it only reaches what is still
joined to the root by a chain of *living* processes. Windows keeps no
grandparent link: when an intermediate process exits, its children's recorded
parent pid points at a pid that is gone, and the walk stops there. That shape is
not exotic -- the `python.exe` of a uv-managed virtual environment is a
trampoline that re-executes the real interpreter as a child of its own, and a
command that ends cleanly takes that link with it. On a machine where the job
does not hold the grandchild either (IsProcessInJob measures which ones those
are), a broken chain means the descendant survives both mechanisms. See
`_descendants`.
"""

from __future__ import annotations

import contextlib
import ctypes
import functools
import io
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TypeGuard, cast

# The whole budget for everything that happens after the command's own time is
# up: killing the tree, reaping the child, and letting the readers finish. One
# deadline shared by all of them, not one grace period each -- what a caller is
# promised is how long run() may take, and grace periods laid end to end would
# quietly turn that promise into timeout + a multiple of this. Whatever is still
# blocked when the deadline passes is given up on; the run gives up on the rest
# of the output rather than on itself.
DRAIN_GRACE = 5.0

# The same budget for a kill that has no deadline to share -- the failure path,
# where there is no output left to wait for. Bounded for the same reason
# everything else here is: an unbounded wait after a kill that did not take is
# the very hang this module exists to prevent, only moved one line down.
KILL_GRACE = 5.0

# Reported when the kill did not take and the process has no exit code yet.
# Negative, like the signal-derived codes on POSIX, so it cannot be confused
# with a status a tool chose to exit with.
NO_EXIT_CODE = -1

# Win32 constants, spelled out because the standard library exposes none of
# them. From winbase.h, winnt.h and tlhelp32.h.
_CREATE_SUSPENDED = 0x00000004
_TH32CS_SNAPPROCESS = 0x00000002
_TH32CS_SNAPTHREAD = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_MAX_PATH = 260
# What ResumeThread returns when it could not do it: (DWORD) -1.
_RESUME_FAILED = 0xFFFFFFFF

# ctypes.wintypes is deliberately not imported: importing it *fails* on POSIX,
# which would make this whole module -- and with it the POSIX branch it
# promises -- unimportable on Linux and macOS. Every Win32 type this module
# needs is a plain C type underneath, so they are spelled out instead.
_HANDLE = ctypes.c_void_p
_BOOL = ctypes.c_int
_DWORD = ctypes.c_uint
_UINT = ctypes.c_uint
_LPCWSTR = ctypes.c_wchar_p
# INVALID_HANDLE_VALUE is (HANDLE) -1, and a c_void_p restype comes back from
# ctypes *unsigned*. Comparing against a plain -1 would therefore never match,
# and a failed snapshot would be walked as if it were an empty machine.
_INVALID_HANDLE = ctypes.c_void_p(-1).value

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
    # The overloads cannot express "which kwargs these are depends on the
    # platform"; spawn_kwargs is where that decision is made, and tested.
    # Annotated because the ignore below would otherwise make `process` Any and
    # let every later mistake through unseen.
    process: subprocess.Popen[bytes] = subprocess.Popen(  # type: ignore[call-overload]  # see above
        tuple(argv),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=child_env(os.environ),
        **spawn_kwargs(sys.platform),
    )
    try:
        if sys.platform == "win32":  # pragma: no cover  # one platform per machine
            _adopt_into_job(process)
        out = _drain(process.stdout, "stdout")
        err = _drain(process.stderr, "stderr")

        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True

        # Started before the kill, on purpose: the reap and the readers share it.
        deadline = time.monotonic() + DRAIN_GRACE
        if timed_out:
            _kill_tree(process, deadline=deadline)

        for drain in (out, err):
            drain.thread.join(max(0.0, deadline - time.monotonic()))

        abandoned = out.abandoned or err.abandoned
        if abandoned and not timed_out:
            # The command exited inside its limit and a reader did not come
            # back. Two ways to get here, and the kill answers the first: a
            # reader still stuck in read1() means a descendant inherited the
            # pipe and outlived the command, nothing else will ever close that
            # write end, and the two daemon readers would sit there for the life
            # of this process holding both pipe ends while the descendant runs
            # on. The second is a reader that died of an exception (`failed`);
            # then there may be nothing left to kill at all, and this costs a
            # kill on an empty tree rather than being wrong.
            #
            # Asked only after the join, because before it a live reader means
            # nothing: a thread that has not yet noticed EOF is not stuck.
            #
            # The deadline is passed on although the join above has just spent
            # it, so the reap inside is bounded at roughly zero. That is fine
            # here and only here: the direct child has already exited, so there
            # is nothing to reap -- what this call is for is the tree behind it.
            _kill_tree(process, deadline=deadline)

        return Completed(
            returncode=NO_EXIT_CODE if process.returncode is None else process.returncode,
            stdout=out.text(),
            stderr=err.text(),
            timed_out=timed_out,
            # The state from before that kill, deliberately: whatever the tree
            # would still have written died with it, so a capture that was
            # short at that moment stays reported as short.
            output_abandoned=abandoned,
        )
    except BaseException:
        # On Windows the process is at this point possibly still *suspended*:
        # adoption or the resume may be what failed. Raising and walking away
        # would leave it standing until the machine reboots, holding both
        # pipes. Loud and left behind is worse than loud.
        _kill_tree(process)
        raise
    finally:
        _release_job(process)


def _kill_tree(process: subprocess.Popen[bytes], *, deadline: float | None = None) -> None:
    """Kill the whole tree and reap the direct child, on a deadline.

    Neither half may raise. A terminator that throws would otherwise be called a
    second time by the handler in `run` -- same cause, same exception, and a
    process that on Windows may still be suspended left standing, which is
    precisely the case that handler exists to prevent. So a tree-wide kill that
    fails falls back to the ordinary kill of the direct child, and the reap is
    bounded because no kill is guaranteed to take.

    Without a deadline the kill gets KILL_GRACE of its own; with one it takes
    what is left of a budget it shares with the readers.
    """
    try:
        terminator(sys.platform)(process)
    except Exception:
        # Whatever the tree-wide kill was, it did not happen. The direct child
        # is still reachable the ordinary way, and the caller learns of the rest
        # through NO_EXIT_CODE and output_abandoned.
        with contextlib.suppress(Exception):
            process.kill()
    remaining = KILL_GRACE if deadline is None else max(0.0, deadline - time.monotonic())
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(remaining)


@dataclass(frozen=True, slots=True)
class _Drain:
    """One pipe, the thread emptying it, and what that thread has read so far.

    The chunks live here rather than inside a `read()` call precisely so the
    main thread can still get at them when the reader has to be abandoned.
    A list of chunks, not a growing buffer: `list.append` is one bytecode, so
    a snapshot taken while the reader is still running is always a prefix of
    the output -- a prefix on the byte level, note, not on the line level:
    `read1` regularly stops in the middle of a line.
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


# Standard toolchain directories on Windows that subshells (e.g. IDE hooks, minimal environments)
# might omit from PATH.
_WINDOWS_TOOLCHAIN_PATHS: tuple[Path, ...] = (Path(r"C:\Program Files\Go\bin"),)


def child_env(
    parent: Mapping[str, str],
    *,
    platform: str = sys.platform,
    known_toolchain_paths: tuple[Path, ...] = _WINDOWS_TOOLCHAIN_PATHS,
) -> dict[str, str]:
    """The environment a check command runs in: the parent's, plus utf-8 and toolchain PATHs.

    `_decode` reads every pipe as utf-8, and a child left to the machine's
    locale does not merely answer in another one. On Windows it writes through
    a console codec of cp1252 and raises at the first character outside it --
    inside the child, before a byte reaches the pipe, where no decoding on this
    side can still recover it. Measured on `ruff`, whose finding carried an
    umlaut: the check reported a crash instead of the finding.

    So an inherited value is overwritten rather than respected. This is not a
    preference a machine may hold against us; it is the other half of a
    decoding that is already fixed.

    On Windows, known toolchain install directories (like Go) are appended to
    PATH if present on disk and not already in PATH, so that gates running in
    subshells with minimal PATH can still reach installed compilers.
    """
    env = {**parent, "PYTHONIOENCODING": "utf-8"}
    if platform == "win32":
        path_var = env.get("PATH", "")
        existing = {os.path.normcase(p.strip()) for p in path_var.split(os.pathsep) if p.strip()}
        additions = [
            str(candidate)
            for candidate in known_toolchain_paths
            if candidate.is_dir() and os.path.normcase(str(candidate)) not in existing
        ]
        if additions:
            env["PATH"] = (
                os.pathsep.join([path_var, *additions]) if path_var else os.pathsep.join(additions)
            )
    return env



def spawn_kwargs(platform: str) -> dict[str, object]:
    """How to start a process so that its descendants can be reached later.

    POSIX gets a session of its own, so one killpg reaches every descendant.
    Windows is started *suspended*: the job is created and the process assigned
    to it before it runs a single instruction. Started first and assigned after,
    a fast child could already have spawned a grandchild that never belongs to
    the job -- and that grandchild is the one this whole module is about.
    """
    if platform == "win32":
        return {"creationflags": _CREATE_SUSPENDED}
    return {"start_new_session": True}


def terminator(platform: str) -> TerminateTree:
    """The kill that reaches the whole tree on this platform."""
    if platform == "win32":
        return _terminate_windows
    return _terminate_posix


def _terminate_posix(process: subprocess.Popen[bytes]) -> None:  # pragma: no cover  # POSIX-only
    """One signal to the session started for this process reaches every descendant.

    The platform guard is for the type checker, not for the logic: mypy resolves
    sys.platform at the platform it runs on, and only behind that check does it
    stop insisting that os.killpg does not exist. The project is checked on
    Windows, which is also why this whole function is excluded from coverage.
    """
    if sys.platform == "win32":
        process.kill()
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        # Already gone, or in a session this process may not signal. Either way
        # there is nothing left to kill here; the bounded reap in _kill_tree is
        # what keeps a failure from turning into a hang.
        process.kill()


def _terminate_windows(process: subprocess.Popen[bytes]) -> None:
    """Terminate the job, then whatever managed to be born outside it.

    The job is the mechanism; the sweep is the admission that it has a hole.
    Processes started by a packaged application -- the Microsoft Store build of
    Python is one, and it is what a bare `python` resolves to on a stock
    Windows -- are created through the app-model activation path and never join
    the job of the process that asked for them. Measured with IsProcessInJob:
    cmd.exe and a uv-managed CPython pass their job on to their children, the
    Store build does not, and terminating the job then leaves the grandchild
    running with the pipe still in its hand.

    That is the hole the sweep was written for, not the only one there is: the
    sweep can follow only a chain of living processes (see `_descendants`). On a
    machine where the job does not hold a grandchild *and* the chain to it is
    broken, neither half reaches it.
    """
    handle = getattr(process, "_ultraloom_job", None)
    if handle is None:
        # No job: a POSIX machine came through the switch, or adoption failed.
        # Killing the direct child is then all that is left to do.
        process.kill()
        return
    _terminate_job_and_strays(process, handle)  # pragma: no cover  # Windows-only syscalls


def _descendants(root: int, parents: Iterable[tuple[int, int]]) -> list[int]:
    """Every pid below `root`, transitively, given the (pid, parent pid) pairs.

    Pure on purpose: the walk is the part that can be wrong, and taking the
    enumeration as an argument is what makes it testable on a machine that
    cannot run a toolhelp snapshot.

    The `seen` set is not tidiness. Windows keeps a parent pid on record after
    the parent has died and hands the pid out again, so the table can contain a
    cycle -- A recorded as B's child while B is recorded as A's. Without it the
    walk would never end, and `run` would never return.

    The known limit of this walk: it needs the chain to be *alive*. Windows
    records only a parent pid, never a grandparent, so a process whose parent has
    already exited is no longer reachable from the root -- the pair (its pid, a
    dead pid) joins nothing. A venv trampoline that hands off to the real
    interpreter and then dies leaves exactly that gap, and there is nothing here
    that can bridge it. Handles held from the moment of spawn would, which is
    what the backlog's pid-reuse entry already asks for; until then the sweep is
    a good mechanism with a hole in it rather than a guarantee.
    """
    children: dict[int, list[int]] = {}
    for child, parent in parents:
        children.setdefault(parent, []).append(child)

    found: list[int] = []
    seen = {root}
    pending = list(children.get(root, ()))
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        found.append(current)
        pending.extend(children.get(current, ()))
    return found


def _resumed_enough(previous_counts: Iterable[int]) -> bool:
    """Did resuming those threads actually start something that was standing still?

    Pure so the decision can be tested; `_resume` supplies the numbers.

    ResumeThread returns the *previous* suspend count. Three answers must not
    be mistaken for success: no threads at all, `_RESUME_FAILED`, and a plain
    zero -- zero means the thread was already running, which for a process
    started suspended means we did not find the one that mattered.
    """
    return any(count != _RESUME_FAILED and count > 0 for count in previous_counts)


def _kill_job_then_strays(
    *,
    sweep: Callable[[], list[int]],
    job_kill: Callable[[], bool],
    direct_kill: Callable[[], None],
    stray_kill: Callable[[int], None],
    release: Callable[[int], None],
) -> None:
    """Order and failure policy for the Windows kill, with the syscalls handed in.

    The syscalls are parameters so that the part that can be wrong -- the order,
    and what happens when a step fails -- can be tested on any machine.

    The sweep runs first even though the job kill matters more, because opening
    the descendants before anything dies is what keeps their pids reserved; done
    afterwards, the parents would be gone and the pids free to be handed out
    again. That order is only safe as long as the sweep cannot stop the kill,
    which is what `_sweep_or_nothing` is for: a sweep that fails costs strays,
    never the job.

    A job kill that reports failure falls back to the direct child, which is
    reachable without any of this.
    """
    strays: list[int] = []
    try:
        strays = _sweep_or_nothing(sweep)
    finally:
        # A `finally`, because `_sweep_or_nothing` only swallows Exception. A
        # KeyboardInterrupt travels on -- it is allowed to end the run -- but it
        # may not take the kill with it and leave the tree standing.
        try:
            if not job_kill():
                direct_kill()
            for stray in strays:
                stray_kill(stray)
        finally:
            for stray in strays:
                release(stray)


def _sweep_or_nothing(sweep: Callable[[], list[int]]) -> list[int]:
    """The strays, or none of them -- but never an exception.

    Collecting the strays needs a process snapshot and a creation time per
    candidate, and every one of those can fail. None of it may prevent the kill
    it is a supplement to: no strays is a partial kill, no kill at all is the
    bug this module was written against.

    Exception, not BaseException: a KeyboardInterrupt is meant to end the run,
    and swallowing it here would only delay that. The kill happens anyway --
    `_kill_job_then_strays` puts it in a `finally` for exactly this case.
    """
    try:
        return sweep()
    except Exception:
        return []


def _usable_handle(value: int | None) -> TypeGuard[int]:
    """Whether a Win32 call handed back a handle or a way of saying "no".

    Two ways of saying no, which is the point of having this in one place:
    OpenProcess and friends return NULL, which ctypes hands over as None or 0,
    while CreateToolhelp32Snapshot returns INVALID_HANDLE_VALUE. That one is
    (HANDLE) -1, and a c_void_p restype comes back *unsigned* -- comparing it
    against a plain -1 never matches, and a failed snapshot would then be walked
    as if the machine had no processes on it.
    """
    return value is not None and value != 0 and value != _INVALID_HANDLE


def _could_be_a_descendant(root_started: int | None, candidate_started: int | None) -> bool:
    """Whether a process found by parent pid can really descend from the root.

    Windows keeps a parent pid on record after the parent has died and hands the
    pid out again, so the table can name a stranger as our child. A stranger
    that started *before* the root cannot be its descendant, and that is cheap
    to check -- this is what keeps the sweep from killing somebody else's work.

    Unreadable times are not treated alike, and deliberately so. A candidate
    whose time cannot be read is dropped: it may be a stranger, and being unsure
    is not a licence to kill. A root whose time cannot be read drops the filter
    instead of the sweep: the tree is being killed either way, and a sweep
    without the filter is still better than a grandchild left running.
    """
    if root_started is None:
        return True
    if candidate_started is None:
        return False
    return candidate_started >= root_started


def _terminate_job_and_strays(  # pragma: no cover  # Windows-only syscalls
    process: subprocess.Popen[bytes], job: int
) -> None:
    """Hand the Win32 calls to the policy in `_kill_job_then_strays`."""
    kernel32 = _kernel32()
    _kill_job_then_strays(
        sweep=lambda: _open_strays(process),
        job_kill=lambda: bool(kernel32.TerminateJobObject(job, 1)),
        direct_kill=process.kill,
        stray_kill=lambda stray: kernel32.TerminateProcess(stray, 1),
        release=lambda stray: kernel32.CloseHandle(stray),
    )


def _collect_strays(
    *,
    pids: Iterable[int],
    root_started: int | None,
    open_process: Callable[[int], int | None],
    started_at: Callable[[int], int | None],
    close: Callable[[int], None],
) -> list[int]:
    """Which candidates get a handle held on them, with the syscalls handed in.

    Handles rather than pids: a held handle keeps the pid reserved, so the pid
    cannot be recycled between this walk and the kill that follows it. Which is
    also why every handle taken has to be given back on the way out -- an
    exception here would otherwise leak one per candidate, and each leaked
    handle pins a pid nobody is watching any more.
    """
    handles: list[int] = []
    try:
        for pid in pids:
            handle = open_process(pid)
            if not _usable_handle(handle):
                # Unreachable is not a reason to leave the reachable ones alive.
                continue
            if not _could_be_a_descendant(root_started, started_at(handle)):
                close(handle)
                continue
            handles.append(handle)
    except BaseException:
        for handle in handles:
            close(handle)
        raise
    return handles


def _threads_of(pid: int, owners: Iterable[tuple[int, int]]) -> list[int]:
    """The thread ids belonging to one process, out of (thread id, owner) pairs."""
    return [thread for thread, owner in owners if owner == pid]


def _walk_snapshot[T](
    *, begin: Callable[[], bool], advance: Callable[[], bool], read: Callable[[], T]
) -> list[T]:
    """The toolhelp iteration shape: First, then Next until it says no.

    Windows fills the same struct over and over, so `read` is called between the
    steps rather than the entries being collected and read afterwards.
    """
    entries: list[T] = []
    more = begin()
    while more:
        entries.append(read())
        more = advance()
    return entries


def _open_strays(process: subprocess.Popen[bytes]) -> list[int]:  # pragma: no cover  # Windows-only
    """Hand the Win32 calls to `_collect_strays`."""
    kernel32 = _kernel32()
    return _collect_strays(
        pids=_descendants(process.pid, _process_parents()),
        root_started=_started_at(_process_handle(process)),
        open_process=lambda pid: kernel32.OpenProcess(
            _PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        ),
        started_at=_started_at,
        close=lambda handle: kernel32.CloseHandle(handle),
    )


def _process_parents() -> list[tuple[int, int]]:  # pragma: no cover  # Windows-only syscalls
    """Every running process as (pid, parent pid)."""
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not _usable_handle(snapshot):
        raise ctypes.WinError(ctypes.get_last_error())
    entry = _ProcessEntry32()
    entry.dwSize = ctypes.sizeof(_ProcessEntry32)
    try:
        return _walk_snapshot(
            begin=lambda: bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry))),
            advance=lambda: bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry))),
            read=lambda: (int(entry.th32ProcessID), int(entry.th32ParentProcessID)),
        )
    finally:
        kernel32.CloseHandle(snapshot)


def _thread_ids(pid: int) -> list[int]:  # pragma: no cover  # Windows-only syscalls
    """Every thread currently belonging to one process."""
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not _usable_handle(snapshot):
        raise ctypes.WinError(ctypes.get_last_error())
    entry = _ThreadEntry32()
    entry.dwSize = ctypes.sizeof(_ThreadEntry32)
    try:
        owners = _walk_snapshot(
            begin=lambda: bool(kernel32.Thread32First(snapshot, ctypes.byref(entry))),
            advance=lambda: bool(kernel32.Thread32Next(snapshot, ctypes.byref(entry))),
            read=lambda: (int(entry.th32ThreadID), int(entry.th32OwnerProcessID)),
        )
    finally:
        kernel32.CloseHandle(snapshot)
    return _threads_of(pid, owners)


def _started_at(handle: int) -> int | None:  # pragma: no cover  # Windows-only syscall
    """When that process was created as a raw FILETIME, or None if unreadable.

    None rather than an exception: this runs on the path to a kill, and what to
    make of an unreadable time is `_could_be_a_descendant`'s decision, not a
    reason to abandon the kill.
    """
    created, exited, kernel, user = (_FileTime() for _ in range(4))
    if not _kernel32().GetProcessTimes(
        handle,
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        return None
    # The fields are c_uint, which ctypes hands back as a plain int; mypy only
    # sees Structure.__getattr__.
    return (int(created.high) << 32) | int(created.low)


def _process_handle(process: subprocess.Popen[bytes]) -> int:  # pragma: no cover  # Windows-only
    """The process handle subprocess keeps to itself; there is no public way to it."""
    # The attribute exists only in the Windows implementation of Popen, which is
    # why the type checker has never heard of it.
    return int(process._handle)  # type: ignore[attr-defined]  # see above


def _adopt_into_job(process: subprocess.Popen[bytes]) -> None:  # pragma: no cover  # Windows-only
    """Create a job, put the suspended process in it, then let it run.

    The handle rides on the Popen object because that is what `_terminate_windows`
    is handed. A private attribute on a foreign object is not pretty; the
    alternative is a second mapping keyed by pid, and a pid can be reused.

    A failure here is raised, not swallowed: a run that quietly loses its job is
    a run whose timeout no longer reaches the grandchild, and that is the whole
    reason this module exists. `run` catches it and kills the process, which at
    this point may still be suspended.
    """
    kernel32 = _kernel32()
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel32.AssignProcessToJobObject(job, _process_handle(process)):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise ctypes.WinError(error)
    # Same story as _process_handle: a private attribute on a foreign object.
    process._ultraloom_job = job  # type: ignore[attr-defined]  # see the docstring
    _resume(process.pid)


def _resume(pid: int) -> None:  # pragma: no cover  # Windows-only syscalls
    """Let a CREATE_SUSPENDED process run.

    subprocess keeps the main thread's handle to itself, so the thread has to be
    found again through a toolhelp snapshot. Whether the numbers that come back
    mean success is decided by `_resumed_enough`, which is where that judgement
    can be tested.
    """
    kernel32 = _kernel32()
    previous_counts: list[int] = []
    for thread_id in _thread_ids(pid):
        handle = kernel32.OpenThread(_THREAD_SUSPEND_RESUME, False, thread_id)
        if not handle:
            continue
        previous_counts.append(int(kernel32.ResumeThread(handle)))
        kernel32.CloseHandle(handle)
    if not _resumed_enough(previous_counts):
        raise RuntimeError(f"could not resume suspended process {pid}")


def _release_job(process: subprocess.Popen[bytes]) -> None:
    """Give the job handle back once the run is over, however it ended.

    Closing it kills nothing -- the job carries no KILL_ON_JOB_CLOSE limit -- so
    this is purely about not leaking one handle per check.
    """
    handle = getattr(process, "_ultraloom_job", None)
    if handle is None:
        return
    _kernel32().CloseHandle(handle)  # pragma: no cover  # Windows-only syscall
    process._ultraloom_job = None  # type: ignore[attr-defined]  # see _adopt_into_job


class _ProcessEntry32(ctypes.Structure):
    """PROCESSENTRY32W from tlhelp32.h, in full: the walk hands it to Windows."""

    _fields_ = (
        ("dwSize", _DWORD),
        ("cntUsage", _DWORD),
        ("th32ProcessID", _DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", _DWORD),
        ("cntThreads", _DWORD),
        ("th32ParentProcessID", _DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", _DWORD),
        ("szExeFile", ctypes.c_wchar * _MAX_PATH),
    )


class _ThreadEntry32(ctypes.Structure):
    """THREADENTRY32 from tlhelp32.h; the walk needs it up to the owning pid."""

    _fields_ = (
        ("dwSize", _DWORD),
        ("cntUsage", _DWORD),
        ("th32ThreadID", _DWORD),
        ("th32OwnerProcessID", _DWORD),
        ("tpBasePri", ctypes.c_long),
        ("tpDeltaPri", ctypes.c_long),
        ("dwFlags", _DWORD),
    )


class _FileTime(ctypes.Structure):
    """FILETIME from minwinbase.h: one 64-bit count in two halves."""

    _fields_ = (("low", _DWORD), ("high", _DWORD))


@functools.cache
def _kernel32() -> ctypes.CDLL:  # pragma: no cover  # Windows-only
    """kernel32 with the prototypes spelled out.

    Not optional tidiness: without argtypes ctypes passes and returns C ints,
    and a 64-bit HANDLE truncated to 32 bits turns every call into a silent
    no-op. The symptom is a job that exists and contains nothing -- which looks
    exactly like the bug this module is here to fix.
    """
    process_entry = ctypes.POINTER(_ProcessEntry32)
    thread_entry = ctypes.POINTER(_ThreadEntry32)
    file_time = ctypes.POINTER(_FileTime)

    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    dll.CreateJobObjectW.restype = _HANDLE
    dll.CreateJobObjectW.argtypes = (ctypes.c_void_p, _LPCWSTR)
    dll.AssignProcessToJobObject.restype = _BOOL
    dll.AssignProcessToJobObject.argtypes = (_HANDLE, _HANDLE)
    dll.TerminateJobObject.restype = _BOOL
    dll.TerminateJobObject.argtypes = (_HANDLE, _UINT)
    dll.CreateToolhelp32Snapshot.restype = _HANDLE
    dll.CreateToolhelp32Snapshot.argtypes = (_DWORD, _DWORD)
    dll.Process32FirstW.restype = _BOOL
    dll.Process32FirstW.argtypes = (_HANDLE, process_entry)
    dll.Process32NextW.restype = _BOOL
    dll.Process32NextW.argtypes = (_HANDLE, process_entry)
    dll.OpenProcess.restype = _HANDLE
    dll.OpenProcess.argtypes = (_DWORD, _BOOL, _DWORD)
    dll.TerminateProcess.restype = _BOOL
    dll.TerminateProcess.argtypes = (_HANDLE, _UINT)
    dll.GetProcessTimes.restype = _BOOL
    dll.GetProcessTimes.argtypes = (_HANDLE, file_time, file_time, file_time, file_time)
    dll.Thread32First.restype = _BOOL
    dll.Thread32First.argtypes = (_HANDLE, thread_entry)
    dll.Thread32Next.restype = _BOOL
    dll.Thread32Next.argtypes = (_HANDLE, thread_entry)
    dll.OpenThread.restype = _HANDLE
    dll.OpenThread.argtypes = (_DWORD, _BOOL, _DWORD)
    dll.ResumeThread.restype = _DWORD
    dll.ResumeThread.argtypes = (_HANDLE,)
    dll.CloseHandle.restype = _BOOL
    dll.CloseHandle.argtypes = (_HANDLE,)
    return dll


def _text(raw: bytes) -> str:
    """Whatever the tool wrote, never an exception about how it wrote it.

    Newlines are translated the way `text=True` would have done it, because the
    callers this module replaces read line-oriented tool output and must not
    start seeing a stray \\r at the end of every line on Windows.
    """
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
