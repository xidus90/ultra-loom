"""Tells a fresh session which runs are still waiting for an answer.

A paused run has an address but no voice: nothing surfaces it in a new
session, and `resume` needs an id somebody has to know. This hook is where
that id comes from.
"""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from ultraloom.gate import pending_gate
from ultraloom.hooks.payload import EXIT_INTERNAL, EXIT_OK, PayloadError
from ultraloom.hooks.payload import read as read_payload
from ultraloom.journal import Journal, JournalError
from ultraloom.worktree import RUN_DIR


def run(stdin: TextIO, root: Path, stdout: TextIO, stderr: TextIO) -> int:
    """Report every paused run. Never blocks -- this is an announcement."""
    try:
        read_payload(stdin)
    except PayloadError as error:
        print(f"ultraloom hook session-start: {error}", file=stderr)
        return EXIT_INTERNAL

    for line in waiting(root, stderr):
        print(line, file=stdout)
    return EXIT_OK


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
        lines.append(
            f"run {run_id} is waiting at {gate.node}: {gate.question}\n"
            f'  answer it with: ultraloom resume {run_id} --answer "…"'
        )
    return tuple(lines)
