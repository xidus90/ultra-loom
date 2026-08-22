"""Tests for the verify-until-green flow's state and its check, repair and guard nodes."""

import subprocess
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from ultraloom.checks import KINDS, CheckResult, CheckUnavailableError
from ultraloom.config import Config
from ultraloom.discovery import FlowContext
from ultraloom.flows.verify_until_green import (
    _EXIT_STILL_RED,
    CheckRunner,
    Differ,
    RepairResult,
    VerifyState,
    assemble,
    build,
    make_check,
    make_guard,
    make_repair,
)
from ultraloom.graph import CodeNode, Graph
from ultraloom.journal import Journal
from ultraloom.model.fake import FakeModel
from ultraloom.model.port import Reply
from ultraloom.runner import FlowExit, Result, Runner
from ultraloom.state import Delta
from ultraloom.worktree import WorktreeError


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


class _Passes:
    """One outcome mapping per round, handed to every kind in that round.

    The check node runs its kinds concurrently, so a plain iterator would give
    the two kinds of one round two different rounds' answers.
    """

    def __init__(self, outcomes: list[Mapping[str, bool]]) -> None:
        self._outcomes = outcomes
        self._round = -1
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def outcome(self, kind: str) -> bool:
        with self._lock:
            if kind in self._seen or self._round < 0:
                self._round += 1
                self._seen = set()
            self._seen.add(kind)
            current = self._outcomes[min(self._round, len(self._outcomes) - 1)]
        return current.get(kind, True)


def _run_flow(
    tmp_path: Path,
    outcomes: list[Mapping[str, bool]],
    repairs: list[RepairResult] | None = None,
    touched: list[tuple[str, ...]] | None = None,
    kinds: tuple[str, ...] = ("lint",),
    max_rounds: int = 5,
    initial: VerifyState | None = None,
    model: FakeModel | None = None,
) -> Result[VerifyState]:
    """Run the real graph against a scripted checker and a scripted working tree.

    The whole flow, not one node: the edges are where this task's decisions
    live, and a node-by-node test would not touch a single one of them.
    """
    passes = _Passes(outcomes)
    diffs = iter(touched or [])

    def runner(kind: str, _config: Config) -> CheckResult:
        ok = passes.outcome(kind)
        return CheckResult(kind, ok, "" if ok else f"{kind} is unhappy", "test")

    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=runner,
        differ=lambda _root: next(diffs, ()),
        max_rounds=max_rounds,
        # Explicit, so the scripted tree does not lose its first answer to the
        # baseline reading. What `assemble` does without one has its own test.
        baseline=frozenset(),
    )
    if model is None:
        model = FakeModel([Reply(repair, tokens=0) for repair in repairs or []])
    state = initial if initial is not None else VerifyState(kinds=kinds)
    return Runner(graph, Journal(tmp_path / "run.jsonl"), model=model).run(state)


def test_a_green_first_pass_ends_the_run(tmp_path: Path) -> None:
    result = _run_flow(tmp_path, outcomes=[{"lint": True}])

    assert result.status == "done"
    assert result.state.data.rounds == 1


def test_red_then_repaired_then_green(tmp_path: Path) -> None:
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": False}, {"lint": True}],
        repairs=[RepairResult("fixed the line", changed=True)],
        touched=[("src/thing.py",)],
    )

    assert result.status == "done"
    assert result.state.data.rounds == 2


def test_a_repair_that_only_helps_on_the_second_try_still_ends_green(tmp_path: Path) -> None:
    """Not every fixture may succeed on its first repair, or the loop goes untested."""
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": False}, {"lint": False}, {"lint": True}],
        repairs=[
            RepairResult("moved the import", changed=True),
            RepairResult("that was the real cause", changed=True),
        ],
        touched=[("src/thing.py",), ("src/other.py",)],
    )

    assert result.status == "done"
    assert result.state.data.rounds == 3


def test_one_kind_going_green_while_another_stays_red_keeps_repairing(tmp_path: Path) -> None:
    result = _run_flow(
        tmp_path,
        outcomes=[
            {"lint": False, "types": False},
            {"lint": True, "types": False},
            {"lint": True, "types": True},
        ],
        kinds=("lint", "types"),
        repairs=[
            RepairResult("lint first", changed=True),
            RepairResult("types next", changed=True),
        ],
        touched=[("src/a.py",), ("src/b.py",)],
    )

    assert result.status == "done"
    assert result.state.data.rounds == 3


def test_two_identical_red_passes_without_a_change_stop_the_run(tmp_path: Path) -> None:
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": False}, {"lint": False}],
        repairs=[RepairResult("I could not fix it", changed=False)],
        touched=[()],
    )

    assert result.status == "error"
    assert result.exit_code == 1
    assert "stagnated" in (result.detail or "")


def test_only_coverage_red_never_calls_the_model(tmp_path: Path) -> None:
    model = FakeModel([])
    result = _run_flow(tmp_path, outcomes=[{"coverage": False}], kinds=("coverage",), model=model)

    assert result.exit_code == 1
    assert "coverage" in (result.detail or "")
    assert model.seen == ()


def test_a_touched_test_file_ends_the_run_with_four(tmp_path: Path) -> None:
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": False}],
        repairs=[RepairResult("rewrote the test", changed=True)],
        touched=[("tests/test_thing.py",)],
    )

    assert result.exit_code == 4


def test_the_round_ceiling_ends_the_run(tmp_path: Path) -> None:
    # Five repairs that each change something and never help.
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": False}] * 7,
        repairs=[RepairResult(f"attempt {n}", changed=True) for n in range(6)],
        touched=[(f"src/attempt_{n}.py",) for n in range(6)],
        max_rounds=5,
    )

    assert result.exit_code == 1
    assert result.state.data.rounds == 6  # five repairs, six checks
    assert "5 repair rounds" in (result.detail or "")


def test_a_state_that_starts_mid_run_is_not_a_special_case(tmp_path: Path) -> None:
    # Deliberately not the shape every other fixture here has: the plan's own
    # fixtures are suggestions, and a run that starts at rounds=2 is the case a
    # resume produces.
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": True}],
        initial=VerifyState(kinds=("lint",), rounds=2, previous_failing=("lint",)),
    )

    assert result.status == "done"
    assert result.state.data.rounds == 3


def test_a_resumed_state_that_is_still_red_repairs_rather_than_stagnating(tmp_path: Path) -> None:
    """A remembered failure alone is not stagnation: the last pass did change something."""
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": False}, {"lint": True}],
        initial=VerifyState(
            kinds=("lint",),
            rounds=3,
            # `failing` too, and not only `previous_failing`: the first check
            # pass overwrites `previous_failing` with whatever `failing` held,
            # so a state that names only the older half makes the condition
            # compare ("lint",) against () and the fixture would pass with
            # `touched` empty -- proving nothing about the rule it is named for.
            failing=("lint",),
            previous_failing=("lint",),
            touched=("src/thing.py",),
        ),
        repairs=[RepairResult("second look", changed=True)],
        touched=[("src/thing.py",)],
    )

    assert result.status == "done"
    assert result.state.data.rounds == 5


def test_a_missing_test_paths_setting_refuses_to_start(tmp_path: Path) -> None:
    context = FlowContext(root=tmp_path, config=Config(root=tmp_path), options={})

    with pytest.raises(ValueError, match=r"\[verify\].tests"):
        build(context)


def _built_kinds(context: FlowContext) -> tuple[str, ...]:
    """The kinds `build` starts from, narrowed: a LoadedFlow types its state as `object`."""
    initial = build(context).initial
    assert isinstance(initial, VerifyState)
    return initial.kinds


def test_the_checks_option_may_name_a_profile(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",), profiles={"edit": ("lint", "types")})
    context = FlowContext(root=tmp_path, config=config, options={"checks": "edit"})

    assert _built_kinds(context) == ("lint", "types")


def test_the_checks_option_may_be_a_list(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",))
    context = FlowContext(root=tmp_path, config=config, options={"checks": "lint,types"})

    assert _built_kinds(context) == ("lint", "types")


def test_without_a_checks_option_every_known_kind_runs(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",))

    assert _built_kinds(FlowContext(root=tmp_path, config=config)) == KINDS


def test_an_unknown_check_name_is_refused_before_the_run(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",))
    context = FlowContext(root=tmp_path, config=config, options={"checks": "spelling"})

    with pytest.raises(ValueError, match="unknown check 'spelling'"):
        build(context)


def test_the_round_ceiling_may_be_raised_from_the_command_line(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",))
    context = FlowContext(root=tmp_path, config=config, options={"max_rounds": "9"})

    graph = build(context).graph
    graph.validate()

    # The repair node's ceiling moves with the option, and sits one above it.
    # Fixed at five it would not show here -- validate() only asks whether a
    # cycle is bounded at all -- but a run of more than five rounds would end on
    # the runner's visit guard instead of the flow's own red exit.
    assert graph.node("repair").max_visits == 10


def test_an_empty_checks_option_is_refused(tmp_path: Path) -> None:
    """A run with nothing to check would report success without checking anything."""
    config = Config(root=tmp_path, test_paths=("tests/",))
    context = FlowContext(root=tmp_path, config=config, options={"checks": ""})

    with pytest.raises(ValueError, match="names no check"):
        build(context)


def test_a_checks_option_of_only_separators_is_refused(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",))
    context = FlowContext(root=tmp_path, config=config, options={"checks": ","})

    with pytest.raises(ValueError, match="names no check"):
        build(context)


def test_a_profile_that_names_no_check_is_refused(tmp_path: Path) -> None:
    """config.py validates the names in a profile, not that there are any."""
    config = Config(root=tmp_path, test_paths=("tests/",), profiles={"nothing": ()})
    context = FlowContext(root=tmp_path, config=config, options={"checks": "nothing"})

    with pytest.raises(ValueError, match="names no check"):
        build(context)


def test_a_run_without_kinds_ends_red_rather_than_reporting_success(tmp_path: Path) -> None:
    """`assemble` is callable directly, so the door `build` closes must be shut here too.

    Without this the check node maps over nothing, `failing` is empty, the first
    edge holds and the run reports done with exit 0 -- having started no checker.
    """
    result = _run_flow(tmp_path, outcomes=[{}], initial=VerifyState(kinds=()))

    assert result.status == "error"
    assert result.exit_code == _EXIT_STILL_RED
    assert "no checks" in (result.detail or "")


def test_a_raised_round_ceiling_reaches_the_red_exit_and_not_a_visit_limit(
    tmp_path: Path,
) -> None:
    """Above five rounds the repair node's own ceiling used to be hit first.

    That ends the run through the runner's visit guard: no exit code and a
    detail about max_visits, instead of exit 1 and the reason the run is red.
    """
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": False}] * 9,
        repairs=[RepairResult(f"attempt {n}", changed=True) for n in range(7)],
        touched=[(f"src/attempt_{n}.py",) for n in range(7)],
        max_rounds=6,
    )

    assert result.exit_code == _EXIT_STILL_RED
    assert result.state.data.rounds == 7
    assert "6 repair rounds" in (result.detail or "")


def test_a_round_ceiling_that_is_not_a_number_says_so(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",))
    context = FlowContext(root=tmp_path, config=config, options={"max_rounds": "abc"})

    with pytest.raises(ValueError, match="max_rounds must be a whole number"):
        build(context)


def test_a_round_ceiling_below_one_says_so(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",))
    context = FlowContext(root=tmp_path, config=config, options={"max_rounds": "0"})

    with pytest.raises(ValueError, match="max_rounds must be at least 1"):
        build(context)


def test_a_single_round_allows_one_repair_and_then_ends_red(tmp_path: Path) -> None:
    """`--max-rounds 1` is a valid wish: check, one repair attempt, check, red.

    The visit ceilings must sit above the round counter, not on it: equal to it
    they make `repair` and `guard` single-visit nodes on a cycle, which the
    graph refuses before the first node runs.
    """
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": False}] * 3,
        repairs=[RepairResult("one attempt", changed=True)],
        touched=[("src/thing.py",)],
        max_rounds=1,
    )

    assert result.exit_code == _EXIT_STILL_RED
    assert result.state.data.rounds == 2  # one repair, two checks
    assert "1 repair rounds" in (result.detail or "")


def test_a_path_dirty_before_the_run_is_not_the_repairers_doing() -> None:
    """The whole point of the baseline: exit 4 must accuse only the repairer."""
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root: ("tests/test_cli.py",),
        baseline=frozenset({"tests/test_cli.py"}),
    )

    assert guard(VerifyState())["touched"] == ()


def test_a_protected_path_outside_the_baseline_still_stops_the_run() -> None:
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root: ("tests/test_cli.py", "tests/test_new.py"),
        baseline=frozenset({"tests/test_cli.py"}),
    )

    with pytest.raises(FlowExit) as raised:
        guard(VerifyState())

    assert raised.value.code == 4
    assert "tests/test_new.py" in str(raised.value)
    # Only the new one: naming the pre-existing change would be the accusation
    # the baseline exists to prevent.
    assert "tests/test_cli.py" not in str(raised.value)


def test_a_source_file_dirty_before_the_run_does_not_count_as_touched() -> None:
    """`touched` feeds the stagnation check, so the baseline must leave it out."""
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root: ("src/a.py", "src/b.py"),
        baseline=frozenset({"src/a.py"}),
    )

    assert guard(VerifyState())["touched"] == ("src/b.py",)


def test_assemble_takes_the_baseline_once_when_it_builds_the_graph(tmp_path: Path) -> None:
    """Once, at build time: asked again per round it would absolve the repairer."""
    calls: list[int] = []

    def differ(_root: Path) -> tuple[str, ...]:
        calls.append(1)
        return ("tests/test_cli.py",)

    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=_runner({"lint": False}),
        differ=differ,
    )
    model = FakeModel([Reply(RepairResult("looked around", changed=False), tokens=0)])
    result = Runner(graph, Journal(tmp_path / "run.jsonl"), model=model).run(
        VerifyState(kinds=("lint",))
    )

    # The dirty test file was there before the run, so the guard lets it pass
    # and the run ends on stagnation rather than on a false accusation.
    assert result.exit_code == 1
    assert "stagnated" in (result.detail or "")
    assert len(calls) == 2  # once for the baseline, once in the guard


def test_a_repairable_red_next_to_an_unrepairable_one_is_still_repaired(tmp_path: Path) -> None:
    """A failing test makes coverage red too; ending there would never repair it."""
    model = FakeModel([Reply(RepairResult("fixed the source", changed=True), tokens=7)])
    result = _run_flow(
        tmp_path,
        outcomes=[{"test": False, "coverage": False}, {"test": True, "coverage": True}],
        kinds=("test", "coverage"),
        touched=[("src/thing.py",)],
        model=model,
    )

    assert result.status == "done"
    assert result.state.data.rounds == 2
    assert len(model.seen) == 1


def test_only_unrepairable_red_left_ends_the_run(tmp_path: Path) -> None:
    result = _run_flow(
        tmp_path,
        outcomes=[{"test": False, "coverage": False}, {"test": True, "coverage": False}],
        repairs=[RepairResult("fixed the source", changed=True)],
        kinds=("test", "coverage"),
        touched=[("src/thing.py",)],
    )

    assert result.exit_code == 1
    assert "out of reach: coverage" in (result.detail or "")


def test_a_red_exit_names_every_failing_check_not_only_the_unreachable_ones(
    tmp_path: Path,
) -> None:
    """The finding from the first real run: naming only `coverage` sent the
    reader to the threshold instead of to the test that was actually broken."""
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": False, "coverage": False}] * 2,
        repairs=[RepairResult("I could not fix it", changed=False)],
        kinds=("lint", "coverage"),
        touched=[()],
    )

    assert result.exit_code == 1
    detail = result.detail or ""
    assert "lint" in detail
    assert "out of reach: coverage" in detail


def _guard_of(graph: Graph[object]) -> Callable[[object], Delta]:
    """The guard node's function out of a built graph, narrowed for the typechecker."""
    node = graph.node("guard")
    assert isinstance(node, CodeNode)
    return node.run


def _raises(error: Exception) -> Differ:
    def differ(_root: Path) -> tuple[str, ...]:
        raise error

    return differ


def test_an_unreadable_tree_does_not_stop_the_graph_from_being_built(tmp_path: Path) -> None:
    """The green case never reaches the guard, so it must not die of its baseline.

    The differ raises rather than the directory being chosen to be outside a
    repository: on a machine whose temp directory happens to sit inside a git
    tree, that arrangement passes without touching the branch it is named for.
    """
    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=_runner({"lint": True}),
        differ=_raises(WorktreeError("no git here")),
    )
    result = Runner(graph, Journal(tmp_path / "run.jsonl"), model=FakeModel([])).run(
        VerifyState(kinds=("lint",))
    )

    assert result.status == "done"


def test_an_unreadable_tree_still_stops_the_run_at_the_guard(tmp_path: Path) -> None:
    """Swallowed while the baseline is taken, reported where it actually matters."""
    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=_runner({"lint": False}),
        differ=_raises(WorktreeError("no git here")),
    )
    model = FakeModel([Reply(RepairResult("had a go", changed=True), tokens=0)])
    result = Runner(graph, Journal(tmp_path / "run.jsonl"), model=model).run(
        VerifyState(kinds=("lint",))
    )

    assert result.exit_code == 4
    assert "no git here" in (result.detail or "")


def test_a_differ_that_fails_for_another_reason_is_not_swallowed(tmp_path: Path) -> None:
    """`except WorktreeError` and not `except FlowExit`: only unreadability is expected."""
    with pytest.raises(FlowExit) as raised:
        assemble(
            config=Config(root=tmp_path, test_paths=("tests/",)),
            root=tmp_path,
            check_runner=_runner({"lint": True}),
            differ=_raises(FlowExit(7, "something else entirely")),
        )

    assert raised.value.code == 7


def test_build_takes_the_baseline_the_run_recorded(tmp_path: Path) -> None:
    """The resume case: the tree is not read again, or the repairer gets an alibi.

    A real repository with a real dirty test file, so the guard's own reading
    does find it and the baseline is what decides.
    """
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_cli.py").write_text("x = 1\n", encoding="utf-8")
    context = FlowContext(
        root=tmp_path,
        config=Config(root=tmp_path, test_paths=("tests/",)),
        options={"checks": "lint"},
        baseline=frozenset({"tests/test_cli.py"}),
    )

    # Covered by the recorded baseline, so not the repairer's doing -- even
    # though it is a protected path and the tree really is dirty there.
    assert _guard_of(build(context).graph)(VerifyState())["touched"] == ()


def test_build_without_a_recorded_baseline_reads_the_tree(tmp_path: Path) -> None:
    """A flow built by hand, or a run from before the baseline was recorded."""
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    config = Config(root=tmp_path, test_paths=("tests/",))
    context = FlowContext(root=tmp_path, config=config, options={"checks": "lint"})

    assert _guard_of(build(context).graph)(VerifyState())["touched"] == ()


def test_an_unavailable_check_beside_a_repairable_one_still_gets_its_rounds(
    tmp_path: Path,
) -> None:
    """A missing tool is unrepairable, but it must not cancel the repairable half.

    The normal case in a project that permanently lacks a tool: space has no
    GDScript typechecker, so `types` is unavailable there on every run.
    """
    passes = _Passes([{"lint": False}, {"lint": True}])

    def runner(kind: str, _config: Config) -> CheckResult:
        if kind == "types":
            return CheckResult(kind, False, "no typechecker here", "unavailable")
        ok = passes.outcome(kind)
        return CheckResult(kind, ok, "" if ok else "lint is unhappy", "test")

    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=runner,
        differ=lambda _root: ("src/thing.py",),
        baseline=frozenset(),
    )
    model = FakeModel([Reply(RepairResult("fixed the lint", changed=True), tokens=0)])
    result = Runner(graph, Journal(tmp_path / "run.jsonl"), model=model).run(
        VerifyState(kinds=("lint", "types"))
    )

    assert len(model.seen) == 1  # the repairable half was tried
    assert result.exit_code == 1
    assert "out of reach: types" in (result.detail or "")


def test_an_unresolvable_check_is_red_and_out_of_reach_not_an_exception() -> None:
    """Found in space: a Godot project has no coverage preset.

    `run_check` raises for a check it cannot resolve, and the node used to let
    that escape -- the whole run died with a traceback-shaped error before any
    other check was even reported. The documented behaviour is a red result
    with source "unavailable", which is what makes it out of reach.
    """

    def run(kind: str, _config: Config) -> CheckResult:
        if kind == "coverage":
            raise CheckUnavailableError("GDScript has no coverage tool")
        return CheckResult(kind, True, "", "preset")

    delta = make_check(_config(), run)(VerifyState(kinds=("lint", "coverage")))

    assert delta["failing"] == ("coverage",)
    assert delta["unfixable"] == ("coverage",)
    assert "unavailable" in str(delta["report"])


def test_the_guard_holds_when_the_project_root_is_below_the_repository_root(
    tmp_path: Path,
) -> None:
    """A monorepo: `[verify].tests` says "tests/", git says "package/tests/...".

    The real `changed_files`, not a scripted differ -- the mismatch this test
    is about lives in the answer git gives, so a scripted one cannot show it.
    """
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    package = tmp_path / "package"
    (package / "tests").mkdir(parents=True)
    (package / "tests" / "test_x.py").write_text("x = 1\n", encoding="utf-8")
    guard = make_guard(package, ("tests/",), baseline=frozenset())

    with pytest.raises(FlowExit) as raised:
        guard(VerifyState())

    assert raised.value.code == 4
    assert "tests/test_x.py" in str(raised.value)


def test_an_unready_project_is_out_of_the_repairers_reach() -> None:
    """No agent should run a Godot import; the project, not the code, is unready."""

    def runner(kind: str, _config: Config) -> CheckResult:
        return CheckResult(kind, False, "never been imported", "unready")

    delta = make_check(_config(), runner)(VerifyState(kinds=("test",)))

    assert delta["failing"] == ("test",)
    assert delta["unfixable"] == ("test",)
