"""File in, exit code out. The heuristic is test_language's business."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from ultraloom.commit.cli import calibrate_run, run


def _project(tmp_path: Path, config: str) -> Path:
    (tmp_path / ".ultraloom").mkdir()
    (tmp_path / ".ultraloom" / "config.toml").write_text(config, encoding="utf-8")
    return tmp_path


def _message(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text(text, encoding="utf-8")
    return path


def test_without_a_commit_section_everything_passes(tmp_path: Path) -> None:
    root = _project(tmp_path, '[verify]\nlint = "ruff check ."\n')
    path = _message(tmp_path, "Das Gate laeuft jetzt mit dem Profil und nicht anders")
    errors = io.StringIO()
    assert run(path, root, errors) == 0
    assert errors.getvalue() == ""


def test_an_english_message_passes(tmp_path: Path) -> None:
    root = _project(tmp_path, '[commit]\nlanguage = "en"\n')
    path = _message(tmp_path, "Let the gate run one profile")
    errors = io.StringIO()
    assert run(path, root, errors) == 0


def test_a_german_message_is_refused_with_its_lines(tmp_path: Path) -> None:
    root = _project(tmp_path, '[commit]\nlanguage = "en"\n')
    path = _message(tmp_path, "Add a thing\n\nDas Ergebnis und der Bericht fehlen")
    errors = io.StringIO()
    assert run(path, root, errors) == 2
    said = errors.getvalue()
    assert "line 3" in said
    # Not `"und" in said`: that word is inside the echoed line as well, so the
    # loose form passes even when the hits are never printed at all.
    assert "hits: das, und, der" in said
    assert "--no-verify" in said


def test_a_missing_file_is_an_internal_error(tmp_path: Path) -> None:
    root = _project(tmp_path, '[commit]\nlanguage = "en"\n')
    errors = io.StringIO()
    assert run(tmp_path / "nope", root, errors) == 1


def test_a_broken_config_is_an_internal_error_not_a_refusal(tmp_path: Path) -> None:
    """A typo in the config must not block every commit in the repository.

    The opposite of the policy's rule, and deliberately: a policy that passes
    silently gives away a file, while a language gate that passes costs a
    message in the wrong language. Blocking every commit is the larger harm
    here, and the mistake surfaces at the next `ultraloom check` anyway.
    """
    root = _project(tmp_path, '[commit]\nlanguage = "klingon"\n')
    path = _message(tmp_path, "Add a thing")
    errors = io.StringIO()
    assert run(path, root, errors) == 1
    assert "klingon" in errors.getvalue()


def test_every_refused_line_is_named(tmp_path: Path) -> None:
    """One line reported and the rest hidden would send the author back twice."""
    root = _project(tmp_path, '[commit]\nlanguage = "en"\n')
    path = _message(
        tmp_path,
        "Das Ergebnis und der Bericht fehlen\n\nDie Kette wird nach dem Lauf nicht gruen",
    )
    errors = io.StringIO()
    assert run(path, root, errors) == 2
    said = errors.getvalue()
    assert "line 1" in said
    assert "line 3" in said
    assert "hits: das, und, der" in said


def test_a_message_that_is_not_utf8_is_an_internal_error(tmp_path: Path) -> None:
    """A decode failure is ours to report, not a verdict on the author's text.

    UnicodeDecodeError is a ValueError, so an `except OSError` around the read
    never sees it, and the hook would die in a traceback naming pathlib rather
    than the file git wrote a moment ago.
    """
    root = _project(tmp_path, '[commit]\nlanguage = "en"\n')
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_bytes(b"F\xfcr den Bericht und den Lauf\n")
    errors = io.StringIO()
    assert run(path, root, errors) == 1
    assert "ultraloom commit-msg:" in errors.getvalue()


def test_a_config_that_is_not_utf8_is_an_internal_error(tmp_path: Path) -> None:
    """The same hole one module over: config.py reads its file the same way."""
    (tmp_path / ".ultraloom").mkdir()
    (tmp_path / ".ultraloom" / "config.toml").write_bytes(
        b'[commit]\nlanguage = "en"\n# f\xfcr den Bericht\n'
    )
    path = _message(tmp_path, "Add a thing")
    errors = io.StringIO()
    assert run(path, tmp_path, errors) == 1
    assert "ultraloom commit-msg:" in errors.getvalue()


def test_the_configured_threshold_reaches_the_scan(tmp_path: Path) -> None:
    """One hit is below the default, so only a passed-through 1 refuses this."""
    root = _project(tmp_path, '[commit]\nlanguage = "en"\nthreshold = 1\n')
    path = _message(tmp_path, "Add a thing und nothing else")
    errors = io.StringIO()
    assert run(path, root, errors) == 2
    assert "hits: und" in errors.getvalue()


def test_the_configured_allow_rules_reach_the_scan(tmp_path: Path) -> None:
    """The only offending line is exempt, so a dropped allow list refuses it."""
    root = _project(
        tmp_path,
        '[commit]\nlanguage = "en"\n\n'
        '[[commit.allow]]\nregex = "^Revert "\nreason = "the reverted subject is quoted"\n',
    )
    path = _message(tmp_path, "Revert Das Ergebnis und der Bericht fehlen")
    errors = io.StringIO()
    assert run(path, root, errors) == 0
    assert errors.getvalue() == ""


def test_an_english_message_is_refused_where_commits_are_german(tmp_path: Path) -> None:
    """The other direction of the opening line, which nothing else takes."""
    root = _project(tmp_path, '[commit]\nlanguage = "de"\n')
    path = _message(tmp_path, "Add a thing\n\nThe report and the run are missing")
    errors = io.StringIO()
    assert run(path, root, errors) == 2
    assert "reads as English, and commits here are German." in errors.getvalue()


def test_the_hits_line_aligns_under_a_two_digit_line_number(tmp_path: Path) -> None:
    """A hardcoded indent only lines up while the message stays short."""
    root = _project(tmp_path, '[commit]\nlanguage = "en"\n')
    path = _message(tmp_path, "Add a thing\n" * 10 + "Das Ergebnis und der Bericht fehlen")
    errors = io.StringIO()
    assert run(path, root, errors) == 2
    lines = errors.getvalue().splitlines()
    assert lines[1].index("Das") == lines[2].index("hits:")


def test_calibrate_needs_a_language_from_somewhere(tmp_path: Path) -> None:
    """No guessed default, for the same reason [commit] has none."""
    root = _project(tmp_path, '[verify]\nlint = "ruff check ."\n')
    errors = io.StringIO()
    assert calibrate_run(root, 5, None, io.StringIO(), errors) == 1
    assert "--language" in errors.getvalue()


def test_calibrate_takes_the_language_from_the_flag_without_a_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ultraloom.commit.calibrate.read_messages",
        lambda _root, _count: ("Das Ergebnis und der Bericht fehlen",),
    )
    out = io.StringIO()
    assert calibrate_run(tmp_path, 5, "en", out, io.StringIO()) == 0
    assert "threshold 2: 1 refused" in out.getvalue()


def test_calibrate_measures_with_the_project_exemptions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A table ignoring `allow` reports a cost the configured gate never charges."""
    root = _project(
        tmp_path,
        '[commit]\nlanguage = "en"\n\n[[commit.allow]]\n'
        'regex = "^Das Ergebnis"\nreason = "a fixed heading"\n',
    )
    monkeypatch.setattr(
        "ultraloom.commit.calibrate.read_messages",
        lambda _root, _count: ("Das Ergebnis und der Bericht fehlen",),
    )
    out = io.StringIO()
    assert calibrate_run(root, 5, None, out, io.StringIO()) == 0
    assert "threshold 1: 0 refused" in out.getvalue()


def test_calibrate_reports_a_broken_config_rather_than_a_table(tmp_path: Path) -> None:
    root = _project(tmp_path, "[commit]\nthreshold = 2\n")
    errors = io.StringIO()
    assert calibrate_run(root, 5, None, io.StringIO(), errors) == 1
    assert "needs a `language`" in errors.getvalue()


def test_calibrate_reports_an_unreadable_history(tmp_path: Path) -> None:
    """tmp_path is no repository, so git log has nothing to answer with."""
    root = _project(tmp_path, '[commit]\nlanguage = "en"\n')
    errors = io.StringIO()
    assert calibrate_run(root, 5, None, io.StringIO(), errors) == 1
    assert "cannot read the history" in errors.getvalue()


def test_the_table_carries_exactly_the_four_thresholds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which thresholds are shown is the command's answer, not a detail.

    A zero among them would refuse every non-blank line and report a hundred
    per cent, and a table nobody pins says nothing when that happens.
    """
    root = _project(tmp_path, '[commit]\nlanguage = "en"\n')
    monkeypatch.setattr(
        "ultraloom.commit.calibrate.read_messages",
        lambda _root, _count: ("Das Ergebnis und der Bericht fehlen",),
    )
    out = io.StringIO()
    assert calibrate_run(root, 5, None, out, io.StringIO()) == 0
    shown = [line.strip() for line in out.getvalue().splitlines() if "threshold" in line]
    assert [line.split(":")[0] for line in shown] == [
        "threshold 1",
        "threshold 2",
        "threshold 3",
        "threshold 4",
    ]


def test_a_count_below_one_is_refused_rather_than_handed_to_git(tmp_path: Path) -> None:
    """`git log -n -1` means unlimited, and zero means an empty table.

    Both are somebody's typo answered with a plausible-looking result, which
    is the one failure this whole tool argues against.
    """
    root = _project(tmp_path, '[commit]\nlanguage = "en"\n')
    for count in (0, -1):
        errors = io.StringIO()
        assert calibrate_run(root, count, None, io.StringIO(), errors) == 1
        assert "--calibrate needs a count of at least 1" in errors.getvalue()
