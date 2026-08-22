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

Nothing in here may leave a process running. Every path out of `run` -- a clean
exit, a timeout, an exception on the way to the wait -- goes through a kill and
a *bounded* reap. A process this module started suspended and then walked away
from would sit there until the machine is rebooted, holding two pipes, one such
process per check command.
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
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, cast

# How long the draining threads get *together* after the tree has been killed.
# One shared deadline, not one per reader: what a caller is promised is how long
# run() may take, and two sequential grace periods would quietly turn that into
# timeout + 2 x DRAIN_GRACE. If a reader is still blocked when the deadline has
# passed, something out there survived and the run gives up on the rest of the
# output rather than on itself.
DRAIN_GRACE = 5.0

# How long a killed process gets to actually die. Bounded for the same reason
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
    process: subprocess.Popen[bytes] = subprocess.Popen(  # type: ignore[call-overload]
        tuple(argv),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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
            _kill_tree(process)

        deadline = time.monotonic() + DRAIN_GRACE
        for drain in (out, err):
            drain.thread.join(max(0.0, deadline - time.monotonic()))

        return Completed(
            returncode=NO_EXIT_CODE if process.returncode is None else process.returncode,
            stdout=out.text(),
            stderr=err.text(),
            timed_out=timed_out,
            output_abandoned=out.abandoned or err.abandoned,
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


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    """Kill the whole tree and reap the direct child, on a deadline.

    The reap is bounded because the kill is not guaranteed: TerminateJobObject
    can fail, killpg can land in a session this process may not signal. An
    unbounded wait() there would hand the run exactly the hang the timeout was
    meant to buy it out of.
    """
    terminator(sys.platform)(process)
    # Suppressed, not handled: there is nothing further to try. The caller
    # learns of it through NO_EXIT_CODE and through output_abandoned.
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(KILL_GRACE)


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


def _terminate_job_and_strays(  # pragma: no cover  # Windows-only syscalls
    process: subprocess.Popen[bytes], job: int
) -> None:
    """The job first, then everything the job never got hold of."""
    kernel32 = _kernel32()
    strays = _open_strays(process)
    try:
        if not kernel32.TerminateJobObject(job, 1):
            # The job failed us; the direct child is still reachable directly.
            process.kill()
        for stray in strays:
            kernel32.TerminateProcess(stray, 1)
    finally:
        for stray in strays:
            kernel32.CloseHandle(stray)


def _open_strays(process: subprocess.Popen[bytes]) -> list[int]:  # pragma: no cover  # Windows-only
    """Handles to the descendants, opened before anything is killed.

    Handles rather than pids: a held handle keeps the pid reserved, so the pid
    cannot be recycled between this walk and the kill that follows it.

    The window *before* the walk is closed by the creation times. A stray whose
    recorded parent pid was reused would otherwise be opened and killed although
    it belongs to somebody else; a real descendant cannot have started before
    the process it descends from.
    """
    kernel32 = _kernel32()
    root_started = _started_at(_process_handle(process))
    handles: list[int] = []
    try:
        for pid in _descendants(process.pid, _process_parents()):
            handle = kernel32.OpenProcess(
                _PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not handle:
                # Unreachable is not a reason to leave the reachable ones alive.
                continue
            if _started_at(handle) < root_started:
                kernel32.CloseHandle(handle)
                continue
            handles.append(handle)
    except BaseException:
        for handle in handles:
            kernel32.CloseHandle(handle)
        raise
    return handles


def _process_parents() -> list[tuple[int, int]]:  # pragma: no cover  # Windows-only syscalls
    """Every running process as (pid, parent pid)."""
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot in (None, _INVALID_HANDLE):
        raise ctypes.WinError(ctypes.get_last_error())
    entry = _ProcessEntry32()
    entry.dwSize = ctypes.sizeof(_ProcessEntry32)
    pairs: list[tuple[int, int]] = []
    try:
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            pairs.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return pairs


def _thread_ids(pid: int) -> list[int]:  # pragma: no cover  # Windows-only syscalls
    """Every thread currently belonging to one process."""
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if snapshot in (None, _INVALID_HANDLE):
        raise ctypes.WinError(ctypes.get_last_error())
    entry = _ThreadEntry32()
    entry.dwSize = ctypes.sizeof(_ThreadEntry32)
    found: list[int] = []
    try:
        more = kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID == pid:
                found.append(int(entry.th32ThreadID))
            more = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def _started_at(handle: int) -> int:  # pragma: no cover  # Windows-only syscall
    """When that process was created, as a raw FILETIME."""
    created, exited, kernel, user = (_FileTime() for _ in range(4))
    if not _kernel32().GetProcessTimes(
        handle,
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
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
