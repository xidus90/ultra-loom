"""Tells a fresh session which runs are still waiting for an answer.

A paused run has an address but no voice: nothing surfaces it in a new
session, and `resume` needs an id somebody has to know. This hook is where
that id comes from.

It also writes down the commit the session starts on, which the stop gate
later measures against. Here and nowhere else: by the time the first Stop
fires, the turn has already run, and anything it committed would sit inside
the baseline that is supposed to expose it.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TextIO

from ultraloom.gate import pending_gate
from ultraloom.hooks.payload import EXIT_INTERNAL, EXIT_OK, PayloadError
from ultraloom.hooks.payload import read as read_payload
from ultraloom.hooks.state import read as read_state
from ultraloom.hooks.state import write as write_state
from ultraloom.journal import Journal, JournalError
from ultraloom.worktree import RUN_DIR, WorktreeError, head_commit


def run(stdin: TextIO, root: Path, stdout: TextIO, stderr: TextIO) -> int:
    """Report every paused run. Never blocks -- this is an announcement."""
    try:
        payload = read_payload(stdin)
    except PayloadError as error:
        print(f"ultraloom hook session-start: {error}", file=stderr)
        return EXIT_INTERNAL

    _record_base(payload.get("session_id"), root)

    for line in waiting(root, stderr):
        print(line, file=stdout)
    return EXIT_OK


def _record_base(session_id: object, root: Path) -> None:
    """Keep the commit this session starts on, if there is one to keep.

    Silent in both failure cases on purpose. Without a session id there is
    nowhere to file it, and outside a repository there is nothing to file --
    neither is a defect of the project, and neither is worth a line in every
    session of every checkout that is not a git repository. The stop gate is
    where the absence matters, and that is where it is said out loud.
    """
    if not isinstance(session_id, str):
        return
    try:
        commit = head_commit(root)
    except WorktreeError:
        return
    state = read_state(root, session_id)
    write_state(root, session_id, replace(state, base=commit))


def waiting(root: Path, stderr: TextIO) -> tuple[str, ...]:
    """One line per paused run, in run order."""
    directory = root / RUN_DIR
    if not directory.is_dir():
        return ()

    lines: list[str] = []
    for path in sorted(directory.glob("*.jsonl")):
        run_id = path.stem
        try:
            gate = pending_gate(Journal(path))
        except JournalError as error:
            # Named, not swallowed, and not fatal either: one damaged file is
            # a finding of its own, and hiding the other runs behind it would
            # turn a small defect into a silent one.
            print(f"ultraloom hook session-start: {error}", file=stderr)
            continue
        if gate is None:
            continue
        # ASCII on purpose, down to the placeholder: this line is printed to
        # whatever console the harness happens to hand over, and on Windows
        # that is cp1252 by default. A single "…" there does not merely show
        # up wrong -- print raises UnicodeEncodeError, and the hook dies with
        # a code the exit protocol does not describe.
        lines.append(
            f"run {run_id} is waiting at {gate.node}: {gate.question}\n"
            f'  answer it with: ultraloom resume {run_id} --answer "your answer"'
        )
    return tuple(lines)
