"""File in, exit code out. The heuristic is test_language's business."""

from __future__ import annotations

import io
from pathlib import Path

from ultraloom.commit.cli import run


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
    assert "und" in said
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
