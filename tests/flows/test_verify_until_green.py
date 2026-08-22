"""Tests for the verify-until-green flow's state and its check and repair nodes."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from ultraloom.checks import CheckResult
from ultraloom.config import Config
from ultraloom.flows.verify_until_green import (
    CheckRunner,
    RepairResult,
    VerifyState,
    make_check,
    make_repair,
)


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
