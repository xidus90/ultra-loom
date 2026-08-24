"""Tests for the verify-until-green flow's state and its check, repair and guard nodes."""

import subprocess
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from ultraloom.checks import (
    BLOCKED,
    KINDS,
    UNREADY,
    CheckResult,
    CheckRunner,
    CheckUnavailableError,
    run_check,
)
from ultraloom.config import Config
from ultraloom.discovery import Baseline, FlowContext
from ultraloom.flows.verify_until_green import (
    _EXIT_STILL_RED,
    MODEL_OUTPUT_LINES,
    Differ,
    RepairResult,
    VerifyState,
    _out_of_reach,
    _render,
    assemble,
    build,
    clip,
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
from ultraloom.worktree import WorktreeError, changed_files, head_commit

# A marker file is all `checks` needs to know the language -- and with it, that
# `coverage` waits for `test`. The order under test lives in the preset table,
# so a project this thin is enough to reach it.
_PYPROJECT = '[project]\nname = "x"\n'


def _config() -> Config:
    return Config(root=Path("."), test_paths=("tests/",))


def test_build_declares_that_it_measures_against_a_commit(tmp_path: Path) -> None:
    """The declaration is what lets the CLI refuse a doomed start early."""
    context = FlowContext(
        root=tmp_path,
        config=Config(root=tmp_path, test_paths=("tests/",)),
        baseline=Baseline("abc", frozenset()),
    )

    loaded = build(context)

    assert loaded.needs_baseline is True


def test_assemble_leaves_the_baseline_unset_when_git_gives_no_commit(tmp_path: Path) -> None:
    """No baseline handed in and git gives none: assembled, but never guarded.

    Not refused here: the refusal that matters is the command line's, before
    anything of the run exists, and it only gets its turn if `build` returns.
    """
    outside = tmp_path / "plain"
    outside.mkdir()

    graph = assemble(
        _config(),
        outside,
        max_rounds=1,
        check_runner=_runner({"lint": False}),
        head=lambda _root: _fail(outside),
    )
    model = FakeModel([Reply(RepairResult("had a go", changed=True), tokens=0)])
    result = Runner(graph, Journal(tmp_path / "run.jsonl"), model=model).run(
        VerifyState(kinds=("lint",))
    )

    assert result.exit_code == 4
    assert "baseline" in (result.detail or "")


def _fail(root: Path) -> str:
    raise WorktreeError(f"git gives nothing for {root}")


def _runner(outcomes: Mapping[str, bool]) -> CheckRunner:
    def run(kind: str, _config: Config, _alongside: frozenset[str] = frozenset()) -> CheckResult:
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

    def runner(kind: str, _config: Config, _alongside: frozenset[str] = frozenset()) -> CheckResult:
        return CheckResult(kind, False, "no gdlint here", "unavailable")

    delta = make_check(_config(), runner)(VerifyState(kinds=("types",)))

    assert delta["failing"] == ("types",)
    assert delta["unfixable"] == ("types",)


def test_every_kind_the_state_names_is_run() -> None:
    seen: list[str] = []

    def runner(kind: str, _config: Config, _alongside: frozenset[str] = frozenset()) -> CheckResult:
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


def test_the_prompt_carries_the_brief_and_the_forbidden_paths() -> None:
    """The brief and not the report: the long one is what the journal keeps."""
    node = make_repair(test_paths=("tests/", "conftest.py"))
    state = VerifyState(
        kinds=("lint",),
        failing=("lint",),
        report="## lint\nE501 too long\nand a thousand more lines",
        brief="## lint\nE501 too long",
    )

    prompt = node.prompt(state)

    assert "E501 too long" in prompt
    assert "a thousand more lines" not in prompt
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

    assert delta == {"report": "shortened the line", "brief": "shortened the line"}


def test_a_reply_of_the_wrong_type_is_refused() -> None:
    node = make_repair(test_paths=("tests/",))

    with pytest.raises(TypeError, match="RepairResult"):
        node.apply(VerifyState(), "I fixed it")


def test_a_source_only_change_passes_and_is_recorded() -> None:
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root, _base: ("src/ultraloom/cli.py",),
        baseline=Baseline("abc", frozenset()),
    )

    delta = guard(VerifyState())

    assert delta["touched"] == ("src/ultraloom/cli.py",)


def test_a_touched_test_file_stops_the_run_with_code_4() -> None:
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root, _base: ("tests/test_cli.py",),
        baseline=Baseline("abc", frozenset()),
    )

    with pytest.raises(FlowExit) as raised:
        guard(VerifyState())

    assert raised.value.code == 4
    assert "tests/test_cli.py" in str(raised.value)


def test_a_prefix_match_is_not_a_path_match() -> None:
    # "tests/" must not forgive "tests_helper.py" and must not catch "testsuite/".
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root, _base: ("testsuite/thing.py",),
        baseline=Baseline("abc", frozenset()),
    )

    assert guard(VerifyState())["touched"] == ("testsuite/thing.py",)


def test_a_single_file_may_be_protected() -> None:
    guard = make_guard(
        Path("."),
        ("conftest.py",),
        differ=lambda _root, _base: ("conftest.py",),
        baseline=Baseline("abc", frozenset()),
    )

    with pytest.raises(FlowExit):
        guard(VerifyState())


def test_a_file_next_to_a_protected_one_is_not_protected() -> None:
    guard = make_guard(
        Path("."),
        ("conftest.py",),
        differ=lambda _root, _base: ("conftest_helper.py",),
        baseline=Baseline("abc", frozenset()),
    )

    assert guard(VerifyState())["touched"] == ("conftest_helper.py",)


def test_nothing_changed_is_an_empty_record_not_a_failure() -> None:
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root, _base: (),
        baseline=Baseline("abc", frozenset()),
    )

    assert guard(VerifyState())["touched"] == ()


def test_a_guard_without_test_paths_is_refused() -> None:
    with pytest.raises(ValueError, match="test_paths"):
        make_guard(Path("."), ())


def test_a_committed_test_file_still_stops_the_run() -> None:
    """The blind spot: the guard must not depend on the tree staying dirty."""
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root, _base: ("tests/test_cli.py",),
        baseline=Baseline("abc", frozenset()),
    )

    with pytest.raises(FlowExit) as raised:
        guard(VerifyState())

    assert raised.value.code == 4
    assert "tests/test_cli.py" in str(raised.value)


def test_the_guard_measures_against_the_recorded_commit() -> None:
    """Not against HEAD, which the repairer may have moved."""
    seen: list[str] = []

    def differ(_root: Path, base: str) -> tuple[str, ...]:
        seen.append(base)
        return ()

    guard = make_guard(Path("."), ("tests/",), differ=differ, baseline=Baseline("abc", frozenset()))
    guard(VerifyState())

    assert seen == ["abc"]


def test_a_guard_without_a_baseline_is_refused_when_it_runs() -> None:
    """A guard with no reference point cannot tell a repair from a starting state.

    Refused on the visit and not at construction, so the graph still assembles
    and the command line keeps its own, earlier refusal.
    """
    guard = make_guard(Path("."), ("tests/",), differ=lambda _root, _base: ())

    with pytest.raises(FlowExit) as raised:
        guard(VerifyState(kinds=("lint",)))

    assert raised.value.code == 4
    assert "baseline" in str(raised.value)


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
    guard = make_guard(repo, ("tests/",), baseline=Baseline(head_commit(repo), frozenset()))

    with pytest.raises(FlowExit) as raised:
        guard(VerifyState())

    assert "tests/test_cli.py" in str(raised.value)


def test_a_committed_test_file_with_an_umlaut_does_not_escape_the_guard(tmp_path: Path) -> None:
    """A quoted path is a path no protected entry matches.

    Without -z on the diff, git answers '"tests/test_gr\\303\\274n.py"', whose
    first segment is '"tests' rather than 'tests' -- and the guard waves it
    through. `docs/abläufe/` is in this project's own tree, so non-ASCII in a
    path is nothing exotic.
    """
    repo = _repo(tmp_path)
    base = head_commit(repo)
    (repo / "tests" / "test_grün.py").write_text("assert False\n", encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=repo, check=True)
    subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "umlaut"),
        cwd=repo,
        check=True,
    )
    guard = make_guard(repo, ("tests/",), baseline=Baseline(base, frozenset()))

    with pytest.raises(FlowExit) as raised:
        guard(VerifyState())

    assert raised.value.code == 4
    assert "tests/test_grün.py" in str(raised.value)


def test_a_test_file_dirty_before_the_run_stays_excused_once_it_is_committed(
    tmp_path: Path,
) -> None:
    """Spec case 3, with a real repository rather than an injected differ.

    The baseline's dirty half comes from `status` and the accusation from
    `diff`; only if both spell the path the same way does the subtraction still
    hold after the repairer commits it.
    """
    repo = _repo(tmp_path)
    (repo / "tests" / "test_cli.py").write_text("x = 2\n", encoding="utf-8")
    baseline = Baseline(head_commit(repo), frozenset(changed_files(repo)))
    subprocess.run(("git", "add", "-A"), cwd=repo, check=True)
    subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "swept up"),
        cwd=repo,
        check=True,
    )
    guard = make_guard(repo, ("tests/",), baseline=baseline)

    assert guard(VerifyState()) == {"touched": ()}


def test_the_run_journal_is_not_charged_to_the_repairer(tmp_path: Path) -> None:
    """The case from space's first run, with the real differ rather than a fake.

    A project that lists `.ultraloom/` among its protected paths is the normal
    thing to do -- that is where its thresholds live. Every run writes its
    journal and its marker below it while the repair agent works, so before
    those were dropped this guard took exit 4 on every run, naming files
    ultraloom had written itself.
    """
    repo = _repo(tmp_path)
    runs = repo / ".ultraloom" / "runs"
    runs.mkdir(parents=True)
    (runs / "0001.jsonl").write_text("{}\n", encoding="utf-8")
    (runs / "0001.flow").write_text("verify_until_green\n", encoding="utf-8")
    guard = make_guard(
        repo,
        ("tests/", ".ultraloom/"),
        baseline=Baseline(head_commit(repo), frozenset()),
        run_files=frozenset({".ultraloom/runs/0001.jsonl", ".ultraloom/runs/0001.flow"}),
    )

    assert guard(VerifyState()) == {"touched": ()}


def test_a_marker_this_run_did_not_write_reaches_the_guard(tmp_path: Path) -> None:
    """The hole that subtracting by name replaces, against real git.

    The whole run directory used to be invisible, so a repairer rewriting some
    other run's marker -- which the `edit` profile can do without a shell --
    was seen by nobody. Under a project that protects `.ultraloom/` it is exit
    4 now, and under one that does not it is at least reported.
    """
    repo = _repo(tmp_path)
    runs = repo / ".ultraloom" / "runs"
    runs.mkdir(parents=True)
    (runs / "0001.jsonl").write_text("{}\n", encoding="utf-8")
    (runs / "0002.flow").write_text("verify_until_green\n", encoding="utf-8")
    guard = make_guard(
        repo,
        ("tests/", ".ultraloom/"),
        baseline=Baseline(head_commit(repo), frozenset()),
        run_files=frozenset({".ultraloom/runs/0001.jsonl", ".ultraloom/runs/0001.flow"}),
    )

    with pytest.raises(FlowExit) as raised:
        guard(VerifyState())

    assert raised.value.code == 4
    assert ".ultraloom/runs/0002.flow" in str(raised.value)
    # And not the one this run wrote itself: naming it would be the accusation
    # the subtraction exists to prevent.
    assert "0001.jsonl" not in str(raised.value)


def test_a_test_deep_below_a_protected_directory_is_protected() -> None:
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root, _base: ("tests/flows/sub/test_x.py",),
        baseline=Baseline("abc", frozenset()),
    )

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

    def runner(kind: str, _config: Config, _alongside: frozenset[str] = frozenset()) -> CheckResult:
        ok = passes.outcome(kind)
        return CheckResult(kind, ok, "" if ok else f"{kind} is unhappy", "test")

    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=runner,
        differ=lambda _root, _base: next(diffs, ()),
        max_rounds=max_rounds,
        # Explicit, so the scripted tree does not lose its first answer to the
        # baseline reading. What `assemble` does without one has its own test.
        baseline=Baseline("abc", frozenset()),
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
    context = FlowContext(
        root=tmp_path,
        config=config,
        options={"checks": "edit"},
        baseline=Baseline("abc", frozenset()),
    )

    assert _built_kinds(context) == ("lint", "types")


def test_the_checks_option_may_be_a_list(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",))
    context = FlowContext(
        root=tmp_path,
        config=config,
        options={"checks": "lint,types"},
        baseline=Baseline("abc", frozenset()),
    )

    assert _built_kinds(context) == ("lint", "types")


def test_without_a_checks_option_every_known_kind_runs(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",))

    context = FlowContext(root=tmp_path, config=config, baseline=Baseline("abc", frozenset()))

    assert _built_kinds(context) == KINDS


def test_an_unknown_check_name_is_refused_before_the_run(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",))
    context = FlowContext(root=tmp_path, config=config, options={"checks": "spelling"})

    with pytest.raises(ValueError, match="unknown check 'spelling'"):
        build(context)


def test_the_round_ceiling_may_be_raised_from_the_command_line(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",))
    context = FlowContext(
        root=tmp_path,
        config=config,
        options={"max_rounds": "9"},
        baseline=Baseline("abc", frozenset()),
    )

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


def test_the_runs_own_journal_and_marker_are_not_the_repairers_doing() -> None:
    """The two files this run writes itself, and only those two.

    They come into being while the repair agent works, so counted as its doing
    a project that protects `.ultraloom/` would take exit 4 on every run, named
    after files ultraloom wrote.
    """
    own = frozenset({".ultraloom/runs/0001.jsonl", ".ultraloom/runs/0001.flow"})
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root, _base: tuple(sorted(own)),
        baseline=Baseline("abc", frozenset()),
        run_files=own,
    )

    assert guard(VerifyState())["touched"] == ()


def test_another_runs_marker_is_the_repairers_doing() -> None:
    """The hole this replaces: the whole run directory used to be invisible.

    A marker this run did not write is nobody's business but the repairer's --
    and the `edit` profile can write one without ever reaching for a shell.
    """
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root, _base: (".ultraloom/runs/0002.flow",),
        baseline=Baseline("abc", frozenset()),
        run_files=frozenset({".ultraloom/runs/0001.jsonl", ".ultraloom/runs/0001.flow"}),
    )

    assert guard(VerifyState())["touched"] == (".ultraloom/runs/0002.flow",)


def test_a_run_that_names_no_files_of_its_own_subtracts_nothing() -> None:
    """`assemble` called directly has no run id, so it knows no own files.

    Nothing is hidden then, which is the safe direction: a report naming a
    journal beats a guard that quietly drops a whole directory.
    """
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root, _base: (".ultraloom/runs/0001.jsonl",),
        baseline=Baseline("abc", frozenset()),
    )

    assert guard(VerifyState())["touched"] == (".ultraloom/runs/0001.jsonl",)


def test_a_path_dirty_before_the_run_is_not_the_repairers_doing() -> None:
    """The whole point of the baseline: exit 4 must accuse only the repairer."""
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root, _base: ("tests/test_cli.py",),
        baseline=Baseline("abc", frozenset({"tests/test_cli.py"})),
    )

    assert guard(VerifyState())["touched"] == ()


def test_a_protected_path_outside_the_baseline_still_stops_the_run() -> None:
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root, _base: ("tests/test_cli.py", "tests/test_new.py"),
        baseline=Baseline("abc", frozenset({"tests/test_cli.py"})),
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
        differ=lambda _root, _base: ("src/a.py", "src/b.py"),
        baseline=Baseline("abc", frozenset({"src/a.py"})),
    )

    assert guard(VerifyState())["touched"] == ("src/b.py",)


def test_assemble_takes_the_baseline_once_when_it_builds_the_graph(tmp_path: Path) -> None:
    """Once, at build time: asked again per round it would absolve the repairer.

    Counted on `head` and not on the differ. The baseline is a commit now, and
    the commit is what a second reading would move: a run taking a fresh HEAD
    each round would measure the repairer against its own last commit and find
    nothing. The differ is asked once per round by design, so counting it would
    say nothing about this rule at all.

    A real repository, because the baseline's dirty half is `changed_files` on
    the actual tree; the dirty test file is what proves the baseline was taken
    at all.
    """
    repo = _repo(tmp_path)
    (repo / "tests" / "test_cli.py").write_text("x = 2\n", encoding="utf-8")
    heads: list[Path] = []

    def head(root: Path) -> str:
        heads.append(root)
        return "abc"

    graph = assemble(
        config=Config(root=repo, test_paths=("tests/",)),
        root=repo,
        check_runner=_runner({"lint": False}),
        differ=lambda _root, _base: ("tests/test_cli.py",),
        head=head,
    )
    # Taken while the graph was built, before any node has run.
    assert heads == [repo]

    model = FakeModel([Reply(RepairResult("looked around", changed=False), tokens=0)])
    result = Runner(graph, Journal(tmp_path / "run.jsonl"), model=model).run(
        VerifyState(kinds=("lint",))
    )

    # The dirty test file was there before the run, so the guard lets it pass
    # and the run ends on stagnation rather than on a false accusation.
    assert result.exit_code == 1
    assert "stagnated" in (result.detail or "")
    # Still once, after a full repair round with a guard visit in it.
    assert heads == [repo]


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
    def differ(_root: Path, _base: str) -> tuple[str, ...]:
        raise error

    return differ


def _head_raises(error: Exception) -> Callable[[Path], str]:
    def head(_root: Path) -> str:
        raise error

    return head


def test_a_project_with_no_commit_to_measure_against_stops_at_the_guard(tmp_path: Path) -> None:
    """Only a `WorktreeError` is absorbed, and it costs the guard its answer."""
    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=_runner({"lint": False}),
        differ=lambda _root, _base: (),
        head=_head_raises(WorktreeError("no HEAD here")),
    )
    model = FakeModel([Reply(RepairResult("had a go", changed=True), tokens=0)])
    result = Runner(graph, Journal(tmp_path / "run.jsonl"), model=model).run(
        VerifyState(kinds=("lint",))
    )

    assert result.exit_code == 4
    assert "baseline" in (result.detail or "")


def test_an_unreadable_tree_still_stops_the_run_at_the_guard(tmp_path: Path) -> None:
    """Read when the graph is built, reported where it actually matters."""
    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=_runner({"lint": False}),
        differ=_raises(WorktreeError("no git here")),
        baseline=Baseline("abc", frozenset()),
    )
    model = FakeModel([Reply(RepairResult("had a go", changed=True), tokens=0)])
    result = Runner(graph, Journal(tmp_path / "run.jsonl"), model=model).run(
        VerifyState(kinds=("lint",))
    )

    assert result.exit_code == 4
    assert "no git here" in (result.detail or "")


def test_a_baseline_reading_that_fails_for_another_reason_is_not_swallowed(
    tmp_path: Path,
) -> None:
    """`except WorktreeError` and not `except Exception`: only a missing commit is expected."""
    with pytest.raises(FlowExit) as raised:
        assemble(
            config=Config(root=tmp_path, test_paths=("tests/",)),
            root=tmp_path,
            check_runner=_runner({"lint": True}),
            differ=lambda _root, _base: (),
            head=_head_raises(FlowExit(7, "something else entirely")),
        )

    assert raised.value.code == 7


def _empty_repo(tmp_path: Path) -> Path:
    """A repository with one commit and nothing in it.

    A commit and not just `git init`: the guard measures against one, and a
    repository that has none is refused before the first repair round.
    """
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "first",
        ),
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def test_build_takes_the_baseline_the_run_recorded(tmp_path: Path) -> None:
    """The resume case: the tree is not read again, or the repairer gets an alibi.

    A real repository with a real dirty test file, so the guard's own reading
    does find it and the baseline is what decides.
    """
    repo = _empty_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_cli.py").write_text("x = 1\n", encoding="utf-8")
    context = FlowContext(
        root=repo,
        config=Config(root=repo, test_paths=("tests/",)),
        options={"checks": "lint"},
        baseline=Baseline(head_commit(repo), frozenset({"tests/test_cli.py"})),
    )

    # Covered by the recorded baseline, so not the repairer's doing -- even
    # though it is a protected path and the tree really is dirty there.
    assert _guard_of(build(context).graph)(VerifyState())["touched"] == ()


def test_build_without_a_recorded_baseline_reads_the_tree(tmp_path: Path) -> None:
    """A flow built by hand, or a run from before the baseline was recorded."""
    repo = _empty_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    config = Config(root=repo, test_paths=("tests/",))
    context = FlowContext(root=repo, config=config, options={"checks": "lint"})

    assert _guard_of(build(context).graph)(VerifyState())["touched"] == ()


def test_build_still_returns_for_a_project_with_no_commit(tmp_path: Path) -> None:
    """The road a real run takes, and the reason `needs_baseline` can be read.

    `build` is where the CLI learns that this flow measures against a commit.
    Refusing here would refuse before it ever learns it, and the run would be
    turned away as an unloadable flow instead of an unguardable start.
    """
    context = FlowContext(root=tmp_path, config=Config(root=tmp_path, test_paths=("tests/",)))

    loaded = build(context)

    assert loaded.needs_baseline is True


def test_an_unavailable_check_beside_a_repairable_one_still_gets_its_rounds(
    tmp_path: Path,
) -> None:
    """A missing tool is unrepairable, but it must not cancel the repairable half.

    The normal case in a project that permanently lacks a tool: space has no
    GDScript typechecker, so `types` is unavailable there on every run.
    """
    passes = _Passes([{"lint": False}, {"lint": True}])

    def runner(kind: str, _config: Config, _alongside: frozenset[str] = frozenset()) -> CheckResult:
        if kind == "types":
            return CheckResult(kind, False, "no typechecker here", "unavailable")
        ok = passes.outcome(kind)
        return CheckResult(kind, ok, "" if ok else "lint is unhappy", "test")

    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=runner,
        differ=lambda _root, _base: ("src/thing.py",),
        baseline=Baseline("abc", frozenset()),
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

    def run(kind: str, _config: Config, _alongside: frozenset[str] = frozenset()) -> CheckResult:
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
    repo = _empty_repo(tmp_path)
    package = repo / "package"
    (package / "tests").mkdir(parents=True)
    (package / "tests" / "test_x.py").write_text("x = 1\n", encoding="utf-8")
    guard = make_guard(package, ("tests/",), baseline=Baseline(head_commit(package), frozenset()))

    with pytest.raises(FlowExit) as raised:
        guard(VerifyState())

    assert raised.value.code == 4
    assert "tests/test_x.py" in str(raised.value)


def test_an_unready_project_is_out_of_the_repairers_reach() -> None:
    """No agent should run a Godot import; the project, not the code, is unready."""

    def runner(kind: str, _config: Config, _alongside: frozenset[str] = frozenset()) -> CheckResult:
        return CheckResult(kind, False, "never been imported", "unready")

    delta = make_check(_config(), runner)(VerifyState(kinds=("test",)))

    assert delta["failing"] == ("test",)
    assert delta["unfixable"] == ("test",)


def test_a_blocked_check_is_not_out_of_reach() -> None:
    """It closes itself the moment `test` goes green -- giving up on it would end
    the flow at every ordinary red test."""
    assert not _out_of_reach(CheckResult("coverage", False, "", BLOCKED))


def test_the_node_runs_checks_in_dependency_order(tmp_path: Path) -> None:
    record: list[str] = []

    def runner(kind: str, _config: Config, _alongside: frozenset[str]) -> CheckResult:
        record.append(kind)
        return CheckResult(kind, True, "", "fake")

    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    check = make_check(Config(root=tmp_path, test_paths=("tests/",)), runner)
    check(VerifyState(kinds=("test", "coverage")))

    assert record.index("coverage") > record.index("test")


def test_the_report_names_what_did_not_run(tmp_path: Path) -> None:
    def runner(kind: str, _config: Config, _alongside: frozenset[str]) -> CheckResult:
        return CheckResult(kind, kind != "test", "suite is red", "fake")

    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    check = make_check(Config(root=tmp_path, test_paths=("tests/",)), runner)
    delta = check(VerifyState(kinds=("test", "coverage")))

    assert "Nicht gelaufen, weil ein Vorgänger rot war: coverage" in str(delta["report"])
    # A check that did not run is never a passed check -- and never a defect
    # the repairer is asked to close either.
    assert delta["failing"] == ("test", "coverage")
    assert delta["unfixable"] == ()


def test_a_blocked_check_is_named_below_the_findings_not_among_them(tmp_path: Path) -> None:
    """The repairer's list of defects must hold only what it can touch."""

    def runner(kind: str, _config: Config, _alongside: frozenset[str]) -> CheckResult:
        return CheckResult(kind, kind != "test", "suite is red", "fake")

    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    check = make_check(Config(root=tmp_path, test_paths=("tests/",)), runner)
    report = str(check(VerifyState(kinds=("test", "coverage")))["report"])

    assert report.index("## test") < report.index("Nicht gelaufen")
    assert "## coverage" not in report


def test_a_ring_in_the_configured_order_ends_the_run(tmp_path: Path) -> None:
    """Not a red check: no repair pass closes a cycle in the configuration."""

    def runner(kind: str, _config: Config, _alongside: frozenset[str]) -> CheckResult:
        return CheckResult(kind, True, "", "fake")  # pragma: no cover  # never reached

    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    config = Config(root=tmp_path, test_paths=("tests/",), after={"test": "coverage"})
    check = make_check(config, runner)

    with pytest.raises(FlowExit) as raised:
        check(VerifyState(kinds=("test", "coverage")))

    assert raised.value.code == _EXIT_STILL_RED
    assert "cycle" in str(raised.value)


def test_a_report_of_nothing_but_blocked_checks_does_not_open_on_blank_lines() -> None:
    """`_render` takes any tuple of red results, and the flow is not its only caller."""
    rendered = _render((CheckResult("coverage", False, "did not run", BLOCKED),))

    assert rendered == "Nicht gelaufen, weil ein Vorgänger rot war: coverage"


def test_the_real_runner_may_not_be_handed_in_directly() -> None:
    """It typechecks and it works -- and spends max_parallel per check, not per run."""
    with pytest.raises(ValueError, match="process cap"):
        make_check(_config(), run_check)


def test_a_blocked_check_does_not_buy_an_unrepairable_project_five_rounds(
    tmp_path: Path,
) -> None:
    """A Godot project that was never imported: `test` unready, `coverage` blocked.

    The whole flow and not `_out_of_reach_only` alone, because the change this
    guards against moves the path *through* that predicate: counting the blocked
    check as repairable makes `failing` a superset of `unfixable`, the run takes
    the repair edge, and a model is paid five times over a project no edit turns
    green.
    """
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")

    def runner(kind: str, _config: Config, _alongside: frozenset[str]) -> CheckResult:
        return CheckResult(kind, False, "never been imported", UNREADY)

    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=runner,
        differ=lambda _root, _base: (),
        baseline=Baseline("abc", frozenset()),
    )
    model = FakeModel([])
    result = Runner(graph, Journal(tmp_path / "run.jsonl"), model=model).run(
        VerifyState(kinds=("test", "coverage"))
    )

    assert not model.seen  # not one paid repair round
    assert result.state.data.rounds == 1
    assert result.exit_code == 1
    assert "out of reach" in (result.detail or "")


def test_a_blocked_check_beside_a_repairable_one_still_gets_its_rounds(
    tmp_path: Path,
) -> None:
    """The other direction: an ordinary red `test` blocks `coverage` and is repaired."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    passes = _Passes([{"test": False}, {"test": True}])

    def runner(kind: str, _config: Config, _alongside: frozenset[str]) -> CheckResult:
        ok = passes.outcome(kind)
        return CheckResult(kind, ok, "" if ok else "suite is red", "test")

    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=runner,
        differ=lambda _root, _base: ("src/thing.py",),
        baseline=Baseline("abc", frozenset()),
    )
    model = FakeModel([Reply(RepairResult("fixed the suite", changed=True), tokens=0)])
    result = Runner(graph, Journal(tmp_path / "run.jsonl"), model=model).run(
        VerifyState(kinds=("test", "coverage"))
    )

    assert len(model.seen) == 1  # the blocked check did not end the run early
    assert result.status == "done"


def test_short_output_is_untouched() -> None:
    assert clip("one\ntwo\n") == "one\ntwo\n"


def test_output_without_any_line_break_survives() -> None:
    assert clip("x" * 10_000) == "x" * 10_000


def test_empty_output_stays_empty() -> None:
    assert clip("") == ""


def test_long_output_keeps_both_ends() -> None:
    lines = "\n".join(str(number) for number in range(1000))

    clipped = clip(lines)

    assert clipped.splitlines()[0] == "0"
    assert clipped.splitlines()[-1] == "999"
    assert len(clipped.splitlines()) == MODEL_OUTPUT_LINES  # marker included


def test_the_clip_says_how_much_it_dropped() -> None:
    clipped = clip("\n".join(str(number) for number in range(1000)))

    assert "Zeilen ausgelassen" in clipped


def test_the_gap_is_named_with_the_exact_number_of_dropped_lines() -> None:
    """A literal budget, so the arithmetic is checked and not merely restated."""
    clipped = clip("\n".join(str(number) for number in range(90)), limit=30)

    assert "61 Zeilen ausgelassen" in clipped
    assert len(clipped.splitlines()) == 30  # the marker is paid for out of the budget


def test_two_thirds_of_the_budget_go_to_the_tail() -> None:
    """pytest writes its summary last, and the summary is the part worth keeping."""
    clipped = clip("\n".join(str(number) for number in range(90)), limit=30)
    body = clipped.splitlines()
    marker = next(index for index, line in enumerate(body) if "ausgelassen" in line)

    assert marker == 9  # nine lines of head, twenty of tail
    assert body[:marker] == [str(number) for number in range(9)]
    assert body[marker + 1 :] == [str(number) for number in range(70, 90)]


def test_a_clipped_output_keeps_a_trailing_newline_like_an_unclipped_one() -> None:
    clipped = clip("\n".join(str(number) for number in range(90)) + "\n", limit=30)

    assert clipped.endswith("89\n")


def test_a_report_exactly_at_the_budget_is_not_clipped() -> None:
    lines = "\n".join(str(number) for number in range(30))

    assert clip(lines, limit=30) == lines


def test_the_render_leaves_everything_alone_without_a_limit() -> None:
    """The default is the uncut report: this is the copy the journal keeps."""
    long_output = "\n".join(str(number) for number in range(1000))

    rendered = _render((CheckResult("test", False, long_output, "pytest"),))

    assert rendered == f"## test (pytest)\n{long_output}"


def test_the_render_clips_each_check_but_not_the_blocked_line() -> None:
    long_output = "\n".join(str(number) for number in range(1000))

    rendered = _render(
        (
            CheckResult("test", False, long_output, "pytest"),
            CheckResult("coverage", False, "did not run", BLOCKED),
        ),
        limit=MODEL_OUTPUT_LINES,
    )

    assert "Zeilen ausgelassen" in rendered
    assert rendered.endswith("Nicht gelaufen, weil ein Vorgänger rot war: coverage")
    assert "500" not in rendered


def test_the_journal_keeps_the_full_output_while_the_repairer_sees_the_clip(
    tmp_path: Path,
) -> None:
    """Clipped towards the model, complete in the journal -- or a run stops being auditable.

    The whole flow with a real Runner and a real Journal, because that is where
    the property lives: `make_check` throws the CheckResults away, so whatever
    the delta does not carry is gone for good.
    """
    long_output = "\n".join(f"line {number}" for number in range(1000))
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")

    def runner(kind: str, _config: Config, _alongside: frozenset[str]) -> CheckResult:
        return CheckResult(kind, False, long_output, "pytest")

    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=runner,
        differ=lambda _root, _base: (),
        baseline=Baseline("abc", frozenset()),
        max_rounds=1,
    )
    journal = Journal(tmp_path / "run.jsonl")
    model = FakeModel([Reply(RepairResult("gave up", changed=False), tokens=0)])
    Runner(graph, journal, model=model).run(VerifyState(kinds=("test",)))

    checks = [entry for entry in journal.entries() if entry.node == "check"]
    assert checks
    assert checks[0].delta["report"] == f"## test (pytest)\n{long_output}"
    assert "ausgelassen" in str(checks[0].delta["brief"])
    prompt = model.seen[0].prompt
    assert "ausgelassen" in prompt  # the repairer got the short one
    assert "line 500" not in prompt


def test_the_repairers_prompt_never_carries_the_full_report(tmp_path: Path) -> None:
    """The one thing the clip is for: the long report must not reach the model."""
    long_output = "\n".join(f"line {number}" for number in range(1000))
    step = make_check(
        Config(root=tmp_path, test_paths=("tests/",)),
        lambda kind, _config, _alongside: CheckResult(kind, False, long_output, "pytest"),
    )

    delta = step(VerifyState(kinds=("test",)))
    state = VerifyState(report=str(delta["report"]), brief=str(delta["brief"]))
    prompt = make_repair(("tests/",)).prompt(state)

    assert len(prompt.splitlines()) < 250
    assert "ausgelassen" in prompt


class _ModelThatActs:
    """A model that does something to the tree before it answers.

    The repairer is a black box to the flow, so the only way to test a repairer
    that commits is to let the model's turn have the same side effect a real
    agent's tool calls would have.
    """

    def __init__(self, reply: Reply, act: Callable[[], None]) -> None:
        self._reply = reply
        self._act = act
        self.seen: list[object] = []

    def ask(self, request: object) -> Reply:
        """Act on the tree, then hand back the prepared reply."""
        self.seen.append(request)
        self._act()
        return self._reply


def test_a_repairer_that_commits_a_test_file_does_not_get_past_the_real_guard(
    tmp_path: Path,
) -> None:
    """No injected differ: the wiring between the flow and git is the point."""
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("assert False\n", encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=tmp_path, check=True)
    subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first"),
        cwd=tmp_path,
        check=True,
    )

    def runner(kind: str, _config: Config, _alongside: frozenset[str] = frozenset()) -> CheckResult:
        return CheckResult(kind, False, f"{kind} is unhappy", "test")

    def repair_then_commit() -> None:
        (tmp_path / "tests" / "test_a.py").write_text("assert True\n", encoding="utf-8")
        subprocess.run(("git", "add", "-A"), cwd=tmp_path, check=True)
        subprocess.run(
            ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "sneaky"),
            cwd=tmp_path,
            check=True,
        )

    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=runner,
        max_rounds=2,
    )
    model = _ModelThatActs(Reply(RepairResult("done", changed=True), tokens=0), repair_then_commit)
    result = Runner(graph, Journal(tmp_path / "run.jsonl"), model=model).run(
        VerifyState(kinds=("test",))
    )

    assert result.exit_code == 4
    assert "tests/test_a.py" in (result.detail or "")
