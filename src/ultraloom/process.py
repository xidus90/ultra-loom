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
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import functools
import io
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
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

# Win32 constants, spelled out because the standard library exposes none of
# them. From winbase.h and tlhelp32.h.
_CREATE_SUSPENDED = 0x00000004
_TH32CS_SNAPPROCESS = 0x00000002
_TH32CS_SNAPTHREAD = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002
_PROCESS_TERMINATE = 0x0001
_MAX_PATH = 260
_INVALID_HANDLE_VALUE = -1
# What ResumeThread returns when it could not do it: (DWORD) -1.
_RESUME_FAILED = 0xFFFFFFFF

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
            terminator(sys.platform)(process)
            process.wait()

        deadline = time.monotonic() + DRAIN_GRACE
        for drain in (out, err):
            drain.thread.join(max(0.0, deadline - time.monotonic()))

        return Completed(
            returncode=process.returncode,
            stdout=out.text(),
            stderr=err.text(),
            timed_out=timed_out,
            output_abandoned=out.abandoned or err.abandoned,
        )
    finally:
        _release_job(process)


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
        # there is nothing left to kill and nothing worth raising over.
        process.kill()


class _ProcessEntry32(ctypes.Structure):
    """PROCESSENTRY32W from tlhelp32.h, in full: the walk hands it to Windows."""

    _fields_ = (
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_wchar * _MAX_PATH),
    )


class _ThreadEntry32(ctypes.Structure):
    """THREADENTRY32 from tlhelp32.h; the walk needs it up to the owning pid."""

    _fields_ = (
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ThreadID", ctypes.c_ulong),
        ("th32OwnerProcessID", ctypes.c_ulong),
        ("tpBasePri", ctypes.c_long),
        ("tpDeltaPri", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
    )


def _terminate_windows(process: subprocess.Popen[bytes]) -> None:
    """Terminate the job, then whatever managed to be born outside it.

    The job is the mechanism; the sweep is the admission that it has a hole.
    Processes started by a packaged application -- the Microsoft Store build of
    Python is one, and it is what a stock Windows `python` resolves to -- are
    created through the app-model activation path and never join the job of the
    process that asked for them. Measured on this machine: with a Store Python
    as the direct child, its own child sits in no job at all, and terminating
    the job leaves it running with the pipe still in its hand.

    So the descendants are opened *before* the job dies. A held handle keeps the
    pid reserved, which is what makes killing by pid safe here: the alternative,
    listing pids after the parents are gone, races against pid reuse.
    """
    handle = getattr(process, "_ultraloom_job", None)
    if handle is None:
        # No job: a POSIX machine came through the switch, or adoption failed.
        # Killing the direct child is then all that is left to do.
        process.kill()
        return
    _terminate_job_and_strays(process, handle)  # pragma: no cover  # Windows-only


def _terminate_job_and_strays(
    process: subprocess.Popen[bytes], job: int
) -> None:  # pragma: no cover  # Windows-only syscalls
    """The job first, then everything the job never got hold of."""
    kernel32 = _kernel32()
    strays = _open_descendants(process.pid)
    try:
        kernel32.TerminateJobObject(job, 1)
        for stray in strays:
            kernel32.TerminateProcess(stray, 1)
    finally:
        for stray in strays:
            kernel32.CloseHandle(stray)


def _open_descendants(pid: int) -> list[int]:  # pragma: no cover  # Windows-only toolhelp walk
    """Handles to everything below one process, transitively.

    Handles rather than pids on purpose: see `_terminate_windows`. Processes
    that cannot be opened are skipped -- one unreachable descendant is not a
    reason to leave the reachable ones running.

    Windows keeps a parent pid on record after the parent is gone, so a stray
    whose parent pid was reused could in principle join the list. The root of
    the walk is safe -- its pid is held by the Popen handle -- and everything
    below it belongs to a tree that is being killed anyway.
    """
    children: dict[int, list[int]] = {}
    for child, parent in _process_parents():
        children.setdefault(parent, []).append(child)

    handles: list[int] = []
    pending = list(children.get(pid, ()))
    while pending:
        current = pending.pop()
        pending.extend(children.get(current, ()))
        handle = _kernel32().OpenProcess(_PROCESS_TERMINATE, False, current)
        if handle:
            handles.append(handle)
    return handles


def _process_parents() -> list[tuple[int, int]]:  # pragma: no cover  # Windows-only toolhelp walk
    """Every running process as (pid, parent pid)."""
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot == _INVALID_HANDLE_VALUE:
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


@functools.cache
def _kernel32() -> ctypes.WinDLL:  # pragma: no cover  # Windows-only
    """kernel32 with the prototypes spelled out.

    Not optional tidiness: without argtypes ctypes passes and returns C ints,
    and a 64-bit HANDLE truncated to 32 bits turns every call into a silent
    no-op. The symptom is a job that exists and contains nothing -- which looks
    exactly like the bug this module is here to fix.
    """
    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    dll.CreateJobObjectW.restype = wintypes.HANDLE
    dll.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    dll.AssignProcessToJobObject.restype = wintypes.BOOL
    dll.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    dll.TerminateJobObject.restype = wintypes.BOOL
    dll.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    dll.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    dll.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    dll.Process32FirstW.restype = wintypes.BOOL
    dll.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32))
    dll.Process32NextW.restype = wintypes.BOOL
    dll.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32))
    dll.OpenProcess.restype = wintypes.HANDLE
    dll.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    dll.TerminateProcess.restype = wintypes.BOOL
    dll.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    dll.Thread32First.restype = wintypes.BOOL
    dll.Thread32First.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32))
    dll.Thread32Next.restype = wintypes.BOOL
    dll.Thread32Next.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32))
    dll.OpenThread.restype = wintypes.HANDLE
    dll.OpenThread.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    dll.ResumeThread.restype = wintypes.DWORD
    dll.ResumeThread.argtypes = (wintypes.HANDLE,)
    dll.CloseHandle.restype = wintypes.BOOL
    dll.CloseHandle.argtypes = (wintypes.HANDLE,)
    return dll


def _adopt_into_job(process: subprocess.Popen[bytes]) -> None:  # pragma: no cover  # Windows-only
    """Create a job, put the suspended process in it, then let it run.

    The handle rides on the Popen object because that is what `_terminate_windows`
    is handed. A private attribute on a foreign object is not pretty; the
    alternative is a second mapping keyed by pid, and a pid can be reused.

    A failure here is raised, not swallowed: a run that quietly loses its job is
    a run whose timeout no longer reaches the grandchild, and that is the whole
    reason this module exists.
    """
    kernel32 = _kernel32()
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    # The process handle subprocess keeps; there is no public way to it.
    handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
    if not kernel32.AssignProcessToJobObject(job, handle):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise ctypes.WinError(error)
    process._ultraloom_job = job  # type: ignore[attr-defined]  # see the docstring
    _resume(process.pid)


def _resume(pid: int) -> None:  # pragma: no cover  # Windows-only
    """Let a CREATE_SUSPENDED process run.

    subprocess keeps the main thread's handle to itself, so the thread has to be
    found again through a toolhelp snapshot. Raising when nothing was resumed is
    deliberate: a process left suspended does not fail, it sits there until the
    timeout and reports nothing -- the worst outcome this module could produce,
    and the one risk the CREATE_SUSPENDED trick buys its guarantee with.
    """
    kernel32 = _kernel32()
    resumed = 0
    for thread_id in _thread_ids(pid):
        handle = kernel32.OpenThread(_THREAD_SUSPEND_RESUME, False, thread_id)
        if not handle:
            continue
        if kernel32.ResumeThread(handle) != _RESUME_FAILED:
            resumed += 1
        kernel32.CloseHandle(handle)
    if not resumed:
        raise RuntimeError(f"could not resume suspended process {pid}")


def _thread_ids(pid: int) -> list[int]:  # pragma: no cover  # Windows-only toolhelp walk
    """Every thread currently belonging to one process."""
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if snapshot == _INVALID_HANDLE_VALUE:
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


def _text(raw: bytes) -> str:
    """Whatever the tool wrote, never an exception about how it wrote it.

    Newlines are translated the way `text=True` would have done it, because the
    callers this module replaces read line-oriented tool output and must not
    start seeing a stray \\r at the end of every line on Windows.
    """
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
