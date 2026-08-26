"""What a threshold would cost, measured against real messages."""

from __future__ import annotations

import io
import re
import subprocess
from pathlib import Path

import pytest

from ultraloom.commit.calibrate import HistoryError, calibrate, read_messages, render
from ultraloom.process import Completed

_MESSAGES = (
    "Let the gate run one profile",                      # 0: English
    "Rename the page to der-alte-fall.md",               # 1: one hit, a path
    'The page says "der Bericht und das Ergebnis"',      # 2: quoted
    "Das Ergebnis und der Bericht fehlen vollstaendig",  # 3: German prose
)


def test_a_higher_threshold_refuses_fewer() -> None:
    result = calibrate(_MESSAGES, "en", (1, 2, 3))
    assert 3 in result[2]
    # Sets, not tuples: comparing tuples with <= is lexicographic and would
    # pass on orderings that have nothing to do with "refuses a subset".
    assert set(result[3]) <= set(result[2])
    assert set(result[2]) <= set(result[1])


def test_the_calibrated_default_refuses_only_the_prose() -> None:
    """Two is the line between the false-positive shapes and real prose."""
    assert calibrate(_MESSAGES, "en", (2,))[2] == (3,)


def test_an_allow_pattern_takes_a_message_out_of_every_count() -> None:
    """The measurement must answer for the project's own exemptions.

    Calibrating without them would report a cost the configured gate never
    charges, and the number is read as advice about that gate.
    """
    messages = ("Das Ergebnis und der Bericht fehlen", "Ein Bericht fehlt")
    allow = (re.compile(r"^Das Ergebnis"),)
    assert calibrate(messages, "en", (1, 2)) == {1: (0, 1), 2: (0,)}
    assert calibrate(messages, "en", (1, 2), allow) == {1: (1,), 2: ()}


def _repository(root: Path, *messages: str) -> Path:
    subprocess.run(("git", "init", "-q"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.email", "t@example.com"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.name", "Test"), cwd=root, check=True)
    for index, message in enumerate(messages):
        (root / f"file{index}.txt").write_text(str(index), encoding="utf-8")
        subprocess.run(("git", "add", "-A"), cwd=root, check=True)
        subprocess.run(("git", "commit", "-q", "-m", message), cwd=root, check=True)
    return root


def test_the_history_comes_back_newest_first_and_keeps_blank_lines(tmp_path: Path) -> None:
    """The separator is the NUL, not the blank line a body is allowed to have."""
    root = _repository(tmp_path, "First one", "Second one\n\nWith a body")
    assert read_messages(root, 2) == ("Second one\n\nWith a body\n", "First one\n")


def test_fewer_commits_than_asked_for_is_not_an_error(tmp_path: Path) -> None:
    root = _repository(tmp_path, "Only one")
    assert len(read_messages(root, 100)) == 1


def test_a_directory_without_a_repository_is_a_history_error(tmp_path: Path) -> None:
    with pytest.raises(HistoryError, match="cannot read the history"):
        read_messages(tmp_path, 5)


def test_a_git_that_hangs_is_a_history_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout carries returncode 0 on some platforms, so it is asked first."""
    monkeypatch.setattr(
        "ultraloom.process.run",
        lambda *_args, **_kwargs: Completed(returncode=0, stdout="", stderr="", timed_out=True),
    )
    with pytest.raises(HistoryError, match="took longer than"):
        read_messages(tmp_path, 5)


def test_the_table_names_the_first_line_of_every_refused_message() -> None:
    out = io.StringIO()
    render((*_MESSAGES, "Ein Bericht fehlt"), "en", (1, 2), out)
    said = out.getvalue()
    assert "5 messages" in said
    assert "threshold 1: 2 refused" in said
    assert "threshold 2: 1 refused" in said
    assert "#4  Das Ergebnis und der Bericht fehlen vollstaendig" in said
    assert "#5  Ein Bericht fehlt" in said


def test_a_threshold_that_refuses_nothing_lists_nothing() -> None:
    out = io.StringIO()
    render(("Let the gate run one profile",), "en", (2,), out)
    assert out.getvalue().splitlines()[-1].strip() == "threshold 2: 0 refused"


def test_a_long_message_is_shown_by_its_subject_alone() -> None:
    out = io.StringIO()
    render(("Das Ergebnis und der Bericht fehlen\n\nUnd noch ein Absatz",), "en", (2,), out)
    said = out.getvalue()
    assert "Und noch ein Absatz" not in said
