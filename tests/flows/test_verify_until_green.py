"""Tests for the verify-until-green flow's state and its check, repair and guard nodes."""

import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from ultraloom.checks import CheckResult
from ultraloom.config import Config
from ultraloom.flows.verify_until_green import (
    CheckRunner,
    RepairResult,
    VerifyState,
    changed_files,
    make_check,
    make_guard,
    make_repair,
)
from ultraloom.runner import FlowExit


def _config() -> Config:
    return Config(root=Path("."), test_paths=("tests/",))


def _runner(outcomes: Mapping[str, bool]) -> CheckRunner:
    def run(kind: str, _config: Config) -> CheckResult:
        ok = outcomes[kind]
        return CheckResult(kind, ok, "" if ok else f"{kind} is unhappy", "test")

    return run


def test_all_green_leaves_nothing_failing() -> None:
    step = make_check(_config(), _runner({"lint": True, "types": True}))

    delta = step(VerifyState(kinds=("lint", "types")))

    assert delta["failing"] == ()
    assert delta["unfixable"] == ()
    assert delta["rounds"] == 1


def test_a_red_check_is_named_and_rendered() -> None:
    step = make_check(_config(), _runner({"lint": False, "types": True}))

    delta = step(VerifyState(kinds=("lint", "types")))

    assert delta["failing"] == ("lint",)
    assert "lint" in str(delta["report"])
    assert "types" not in str(delta["report"])  # a green check is not worth a model's tokens


def test_coverage_is_red_but_out_of_the_repairers_reach() -> None:
    step = make_check(_config(), _runner({"coverage": False}))

    delta = step(VerifyState(kinds=("coverage",)))

    assert delta["failing"] == ("coverage",)
    assert delta["unfixable"] == ("coverage",)


def test_a_check_that_never_resolved_is_out_of_reach_too() -> None:
    """A missing tool is red with source "unavailable"; nobody can repair it."""

    def runner(kind: str, _config: Config) -> CheckResult:
        return CheckResult(kind, False, "no gdlint here", "unavailable")

    delta = make_check(_config(), runner)(VerifyState(kinds=("types",)))

    assert delta["failing"] == ("types",)
    assert delta["unfixable"] == ("types",)


def test_every_kind_the_state_names_is_run() -> None:
    seen: list[str] = []

    def runner(kind: str, _config: Config) -> CheckResult:
        seen.append(kind)
        return CheckResult(kind, True, "", "test")

    make_check(_config(), runner)(VerifyState(kinds=("types", "lint")))

    assert sorted(seen) == ["lint", "types"]  # concurrent, so only the set is fixed


def test_the_failing_kinds_keep_the_order_the_state_named() -> None:
    """Not the order the checks finished in — a prompt is built from this list."""
    step = make_check(_config(), _runner({"types": False, "lint": False}))

    assert step(VerifyState(kinds=("types", "lint")))["failing"] == ("types", "lint")


def test_rounds_counts_up_from_where_the_state_stood() -> None:
    step = make_check(_config(), _runner({"lint": True}))

    assert step(VerifyState(kinds=("lint",), rounds=2))["rounds"] == 3


def test_the_prompt_carries_the_report_and_the_forbidden_paths() -> None:
    node = make_repair(test_paths=("tests/", "conftest.py"))
    state = VerifyState(kinds=("lint",), failing=("lint",), report="## lint\nE501 too long")

    prompt = node.prompt(state)

    assert "E501 too long" in prompt
    assert "tests/" in prompt
    assert "conftest.py" in prompt


def test_the_node_may_edit_and_gets_more_than_one_attempt() -> None:
    node = make_repair(test_paths=("tests/",))

    assert node.tools == "edit"
    assert node.schema is RepairResult
    assert node.max_visits == 5


def test_the_prompt_forbids_suppressing_a_check_instead_of_fixing_it() -> None:
    prompt = make_repair(test_paths=("tests/",)).prompt(VerifyState())

    assert "# noqa" in prompt
    assert "# type: ignore" in prompt
    assert "# pragma: no cover" in prompt
    assert "pyproject.toml" in prompt


def test_a_flow_without_test_paths_is_refused() -> None:
    with pytest.raises(ValueError, match="test_paths"):
        make_repair(test_paths=())


def test_the_reply_becomes_the_summary_of_the_pass() -> None:
    node = make_repair(test_paths=("tests/",))

    delta = node.apply(VerifyState(), RepairResult(summary="shortened the line", changed=True))

    assert delta == {"report": "shortened the line"}


def test_a_reply_of_the_wrong_type_is_refused() -> None:
    node = make_repair(test_paths=("tests/",))

    with pytest.raises(TypeError, match="RepairResult"):
        node.apply(VerifyState(), "I fixed it")


def test_a_source_only_change_passes_and_is_recorded() -> None:
    guard = make_guard(Path("."), ("tests/",), differ=lambda _root: ("src/ultraloom/cli.py",))

    delta = guard(VerifyState())

    assert delta["touched"] == ("src/ultraloom/cli.py",)


def test_a_touched_test_file_stops_the_run_with_code_4() -> None:
    guard = make_guard(Path("."), ("tests/",), differ=lambda _root: ("tests/test_cli.py",))

    with pytest.raises(FlowExit) as raised:
        guard(VerifyState())

    assert raised.value.code == 4
    assert "tests/test_cli.py" in str(raised.value)


def test_a_prefix_match_is_not_a_path_match() -> None:
    # "tests/" must not forgive "tests_helper.py" and must not catch "testsuite/".
    guard = make_guard(Path("."), ("tests/",), differ=lambda _root: ("testsuite/thing.py",))

    assert guard(VerifyState())["touched"] == ("testsuite/thing.py",)


def test_a_single_file_may_be_protected() -> None:
    guard = make_guard(Path("."), ("conftest.py",), differ=lambda _root: ("conftest.py",))

    with pytest.raises(FlowExit):
        guard(VerifyState())


def test_a_file_next_to_a_protected_one_is_not_protected() -> None:
    guard = make_guard(Path("."), ("conftest.py",), differ=lambda _root: ("conftest_helper.py",))

    assert guard(VerifyState())["touched"] == ("conftest_helper.py",)


def test_nothing_changed_is_an_empty_record_not_a_failure() -> None:
    guard = make_guard(Path("."), ("tests/",), differ=lambda _root: ())

    assert guard(VerifyState())["touched"] == ()


def test_a_guard_without_test_paths_is_refused() -> None:
    with pytest.raises(ValueError, match="test_paths"):
        make_guard(Path("."), ())


def test_changed_files_reads_git(tmp_path: Path) -> None:
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")

    assert changed_files(tmp_path) == ("a.py",)


def test_changed_files_survives_a_directory_that_is_no_repository(tmp_path: Path) -> None:
    # Not a crash and not silence: an empty answer here would let the guard
    # wave through a repair pass it could not see.
    with pytest.raises(FlowExit) as raised:
        changed_files(tmp_path / "nowhere")

    assert raised.value.code == 4


def test_changed_files_survives_a_directory_outside_any_repository(tmp_path: Path) -> None:
    """The other unanswerable case: the directory is there, but git refuses it."""
    outside = tmp_path / "plain"
    outside.mkdir()

    with pytest.raises(FlowExit) as raised:
        changed_files(outside)

    assert raised.value.code == 4


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


def test_changed_files_reports_every_kind_of_change(tmp_path: Path) -> None:
    """A rename, a deletion, a short path and a non-ASCII one, in one answer.

    This is what -z and the paired reading of a rename are for: git reports a
    rename as two NUL fields, and only the first carries the "XY " prefix.
    """
    repo = _repo(tmp_path)
    subprocess.run(("git", "mv", "tests/test_cli.py", "moved.py"), cwd=repo, check=True)
    subprocess.run(("git", "mv", "a.c", "b.c"), cwd=repo, check=True)
    (repo / "gone.py").unlink()
    (repo / "gr\u00fc\u00dfe.py").write_text("z = 3\n", encoding="utf-8")

    reported = changed_files(repo)

    assert set(reported) == {
        "moved.py",
        "tests/test_cli.py",  # the rename's original path, prefix-free
        "b.c",
        "a.c",  # three characters, and still a path
        "gone.py",
        "gr\u00fc\u00dfe.py",  # quoted without -z, and unreadable then
    }


def test_a_test_file_renamed_away_does_not_escape_the_guard(tmp_path: Path) -> None:
    """Moving a test out of tests/ is deleting it by another name."""
    repo = _repo(tmp_path)
    subprocess.run(("git", "mv", "tests/test_cli.py", "moved.py"), cwd=repo, check=True)
    guard = make_guard(repo, ("tests/",))

    with pytest.raises(FlowExit) as raised:
        guard(VerifyState())

    assert "tests/test_cli.py" in str(raised.value)


def test_a_test_deep_below_a_protected_directory_is_protected() -> None:
    guard = make_guard(Path("."), ("tests/",), differ=lambda _root: ("tests/flows/sub/test_x.py",))

    with pytest.raises(FlowExit):
        guard(VerifyState())


def test_an_untracked_directory_is_reported_file_by_file(tmp_path: Path) -> None:
    """Without -uall git collapses this to "new/", which is no path to any file."""
    repo = _repo(tmp_path)
    (repo / "new").mkdir()
    (repo / "new" / "one.py").write_text("a = 1\n", encoding="utf-8")
    (repo / "new" / "two.py").write_text("b = 2\n", encoding="utf-8")

    assert set(changed_files(repo)) == {"new/one.py", "new/two.py"}
