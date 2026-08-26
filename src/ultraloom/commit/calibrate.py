"""What a threshold would have refused, measured against real commits.

The built-in two is calibrated against one project's history, and no number
carries from one repository to the next: a project whose commits quote paths,
package names or foreign titles reaches any threshold sooner than one whose
commits are plain prose. So the number is not defended here -- it is measured,
against the messages a project actually wrote, before anyone turns the gate on.

Reading the history is deliberately not `git log | grep`: the same `scan` the
hook runs answers here, exemptions and all, or the table would report a cost
the configured gate never charges.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from re import Pattern
from typing import TextIO

from ultraloom.commit.language import Language, scan

# The thresholds worth looking at. One is every message with a single hit --
# the false-positive floor -- and above four a message would have to be prose
# in the other language and nothing else, which no threshold can miss.
THRESHOLDS: tuple[int, ...] = (1, 2, 3, 4)

# Generous for `git log` over a few hundred commits, and short enough that a
# repository whose objects live behind a dead network share says so rather
# than hanging at a terminal.
GIT_TIMEOUT = 60.0


class HistoryError(Exception):
    """The commits could not be read, so there is nothing to measure against."""


def calibrate(
    messages: Sequence[str],
    language: Language,
    thresholds: Sequence[int],
    allow: tuple[Pattern[str], ...] = (),
) -> Mapping[int, tuple[int, ...]]:
    """Per threshold, the indices of the messages that would be refused."""
    return {
        threshold: tuple(
            index
            for index, message in enumerate(messages)
            if scan(message, language, threshold, allow)
        )
        for threshold in thresholds
    }


def read_messages(root: Path, count: int) -> tuple[str, ...]:
    """The last `count` commit messages, newest first.

    Split on NUL and not on the blank line: a commit body may hold blank lines
    of its own, and `-z` is what makes the boundary unambiguous.
    """
    # Imported here: the hook path runs on every commit and must not pay for
    # the process machinery, which only this one command needs.
    from ultraloom.process import run

    try:
        completed = run(
            ("git", "log", "-z", "--format=%B", "-n", str(count)),
            cwd=root,
            timeout=GIT_TIMEOUT,
        )
    except OSError as error:  # pragma: no cover  # git missing from PATH
        raise HistoryError(f"cannot read the history in {root}: {error}") from error

    # Asked before the return code: a killed process has whatever code the kill
    # left behind, and on some platforms that is zero.
    if completed.timed_out:
        raise HistoryError(f"reading the history in {root} took longer than {GIT_TIMEOUT:.0f}s")
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"git exited {completed.returncode}"
        raise HistoryError(f"cannot read the history in {root}: {detail}")

    return tuple(chunk for chunk in completed.stdout.split("\0") if chunk.strip())


def render(
    messages: Sequence[str],
    language: Language,
    thresholds: Sequence[int],
    stream: TextIO,
    allow: tuple[Pattern[str], ...] = (),
) -> None:
    """Print one row per threshold, with the subject of everything it refuses.

    The subject and not the whole message: the table is read to decide a
    number, and a screen of bodies buries the count it exists to show.
    """
    result = calibrate(messages, language, thresholds, allow)
    print(f"{len(messages)} messages, checked as {language}", file=stream)
    for threshold in thresholds:
        refused = result[threshold]
        print(f"  threshold {threshold}: {len(refused)} refused", file=stream)
        for index in refused:
            # One-based, so the number matches what a person counting the list
            # above would say.
            print(f"    #{index + 1}  {_subject(messages[index])}", file=stream)


def _subject(message: str) -> str:
    """The first line carrying text, empty for a message that has none.

    A message without one is never refused -- `scan` finds nothing in blank
    lines -- so this stays a single expression rather than a special case with
    a placeholder nobody would ever read.
    """
    return next((line.strip() for line in message.splitlines() if line.strip()), "")
