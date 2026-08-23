"""Tests for reading what git says has changed below a directory."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ultraloom.worktree import WorktreeError, changed_files


def _repo(tmp_path: Path) -> Path:
    """A repository with one committed file per case the -z parsing must handle."""
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_cli.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "gone.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "a.c").write_text("int main;\n", encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=tmp_path, check=True)
    subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first"),
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def test_changed_files_reads_git(tmp_path: Path) -> None:
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")

    assert changed_files(tmp_path) == ("a.py",)


def test_a_directory_that_is_not_there_is_an_error_not_an_empty_answer(tmp_path: Path) -> None:
    # Not a crash and not silence: an empty answer here would let a caller
    # believe it had seen a working tree it never reached.
    with pytest.raises(WorktreeError):
        changed_files(tmp_path / "nowhere")


def test_a_directory_outside_any_repository_is_an_error(tmp_path: Path) -> None:
    """The other unanswerable case: the directory is there, but git refuses it."""
    outside = tmp_path / "plain"
    outside.mkdir()

    with pytest.raises(WorktreeError):
        changed_files(outside)


def test_changed_files_reports_every_kind_of_change(tmp_path: Path) -> None:
    """A rename, a deletion, a short path and a non-ASCII one, in one answer.

    This is what -z and the paired reading of a rename are for: git reports a
    rename as two NUL fields, and only the first carries the "XY " prefix.
    """
    repo = _repo(tmp_path)
    subprocess.run(("git", "mv", "tests/test_cli.py", "moved.py"), cwd=repo, check=True)
    subprocess.run(("git", "mv", "a.c", "b.c"), cwd=repo, check=True)
    (repo / "gone.py").unlink()
    (repo / "grüße.py").write_text("z = 3\n", encoding="utf-8")

    reported = changed_files(repo)

    assert set(reported) == {
        "moved.py",
        "tests/test_cli.py",  # the rename's original path, prefix-free
        "b.c",
        "a.c",  # three characters, and still a path
        "gone.py",
        "grüße.py",  # quoted without -z, and unreadable then
    }


def test_an_untracked_directory_is_reported_file_by_file(tmp_path: Path) -> None:
    """Without -uall git collapses this to "new/", which is no path to any file."""
    repo = _repo(tmp_path)
    (repo / "new").mkdir()
    (repo / "new" / "one.py").write_text("a = 1\n", encoding="utf-8")
    (repo / "new" / "two.py").write_text("b = 2\n", encoding="utf-8")

    assert set(changed_files(repo)) == {"new/one.py", "new/two.py"}


def test_paths_are_reported_relative_to_the_given_root(tmp_path: Path) -> None:
    """git answers relative to the repository root; the caller asked about `root`.

    A monorepo whose ultraloom project sits in a subdirectory is the case: git
    says "package/tests/test_x.py" where the project's own `[verify].tests`
    says "tests/". Left uncorrected, no configured path ever matches and the
    guard that protects the tests is silently off.
    """
    repo = _repo(tmp_path)
    package = repo / "package"
    (package / "tests").mkdir(parents=True)
    (package / "tests" / "test_x.py").write_text("x = 1\n", encoding="utf-8")

    assert changed_files(package) == ("tests/test_x.py",)


def test_a_change_outside_the_root_is_not_reported(tmp_path: Path) -> None:
    """ "Below root" means below root: a sibling's change is not this project's."""
    repo = _repo(tmp_path)
    package = repo / "package"
    package.mkdir()
    (package / "own.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "sibling.py").write_text("y = 2\n", encoding="utf-8")

    assert changed_files(package) == ("own.py",)


def test_a_clean_repository_answers_with_nothing(tmp_path: Path) -> None:
    """And without asking git a second question: there is no path to relocate."""
    assert changed_files(_repo(tmp_path)) == ()


def test_the_run_directory_is_not_part_of_the_answer(tmp_path: Path) -> None:
    """ultraloom's own journals are not a change to the project.

    The guard reads this answer to say what the repair agent did, and every run
    writes its journal and its marker while that agent works. Left in, they are
    the agent's doing according to every caller -- and a project that lists
    `.ultraloom/` among its protected paths gets exit 4 on every single run,
    naming files ultraloom wrote itself.
    """
    repo = _repo(tmp_path)
    runs = repo / ".ultraloom" / "runs"
    runs.mkdir(parents=True)
    (runs / "0001.jsonl").write_text("{}\n", encoding="utf-8")
    (runs / "0001.flow").write_text("verify_until_green\n", encoding="utf-8")
    (repo / "own.py").write_text("x = 1\n", encoding="utf-8")

    assert changed_files(repo) == ("own.py",)


def test_the_rest_of_the_ultraloom_directory_stays_visible(tmp_path: Path) -> None:
    """Only the journals are ours. The configuration is the project's own file.

    It holds the thresholds a check is measured against, so an agent editing it
    is exactly the kind of change the guard exists to see.
    """
    repo = _repo(tmp_path)
    (repo / ".ultraloom").mkdir()
    (repo / ".ultraloom" / "config.toml").write_text("[verify]\n", encoding="utf-8")

    assert changed_files(repo) == (".ultraloom/config.toml",)


def test_the_run_directory_is_only_dropped_below_the_given_root(tmp_path: Path) -> None:
    """A sibling project's `.ultraloom/runs` is not below `root` anyway.

    But `root`'s own is, however deep `root` sits below the repository root --
    the filter runs after the paths have been made relative to `root`, which is
    the only spelling that matches.
    """
    repo = _repo(tmp_path)
    package = repo / "package"
    (package / ".ultraloom" / "runs").mkdir(parents=True)
    (package / ".ultraloom" / "runs" / "0001.jsonl").write_text("{}\n", encoding="utf-8")
    (package / "own.py").write_text("x = 1\n", encoding="utf-8")

    assert changed_files(package) == ("own.py",)
