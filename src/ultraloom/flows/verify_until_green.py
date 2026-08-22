"""Check, repair, check again — until it is green or honestly red.

The first flow ultraloom ships. It knows nothing about any one project: which
tools check it and where its tests live both arrive through Config, which is
what lets the same flow run in a Python package and in a Godot game.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from ultraloom.checks import BLOCKED, KINDS, UNREADY, CheckResult, CheckRunner, run_kinds
from ultraloom.config import Config, ConfigError
from ultraloom.discovery import FlowContext, LoadedFlow
from ultraloom.graph import END, AgentNode, CodeNode, Graph
from ultraloom.runner import FlowExit
from ultraloom.state import Delta
from ultraloom.worktree import WorktreeError, changed_files

type Differ = Callable[[Path], tuple[str, ...]]

_EXIT_TOUCHED_A_TEST = 4
_EXIT_STILL_RED = 1

# Red checks the repairer is not allowed to close. Closing a coverage gap means
# writing tests, and writing tests is exactly what the guard forbids -- so a
# repair pass for it would be an agent looking for a way around a rule.
UNFIXABLE: tuple[str, ...] = ("coverage",)

# A check that could not be resolved at all reports itself this way
# (checks._run_or_report). It is red, but no edit to the project fixes it --
# space has no GDScript typechecker, and asking an agent to repair a tool that
# is not installed is asking it to invent one.
UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class VerifyState:
    """What one verification run knows about itself."""

    kinds: tuple[str, ...] = ()
    report: str = ""
    failing: tuple[str, ...] = ()
    unfixable: tuple[str, ...] = ()
    touched: tuple[str, ...] = ()
    rounds: int = 0
    previous_failing: tuple[str, ...] = ()


def make_check(config: Config, runner: CheckRunner | None = None) -> Callable[[VerifyState], Delta]:
    """The `check` node, bound to one project's configuration.

    The runner is a parameter so the flow's own tests never start a real tool:
    a test that shells out to ruff measures ruff. It stays None by default and
    is passed on as None, because `run_kinds` builds the run's one process cap
    around its own default runner -- naming `run_check` here would hand every
    check a cap of its own.
    """

    def check(state: VerifyState) -> Delta:
        if not state.kinds:
            # Kept here although `run_kinds` also refuses an empty list: its
            # ValueError speaks about a scheduler call, and this is a statement
            # about the state -- it names no check, so nothing was verified. A
            # green answer nobody checked for is the one failure this flow must
            # never produce, so it is refused here as well as in `_kinds_from`:
            # `assemble` is callable without going through `build`.
            raise FlowExit(
                _EXIT_STILL_RED,
                "no checks to run: the state names none, so nothing was verified",
            )

        # checks.run_kinds and not a pool of our own: the ordering between
        # checks lives there, and a second scheduler here would run this flow --
        # the one the ordering was written for -- unordered. The translation of
        # CheckUnavailableError travels with it; it stood here as well only
        # because there were two pools.
        try:
            results = run_kinds(state.kinds, config, runner)
        except ConfigError as error:
            # Not a red check but the end of the run: a cycle in the check order
            # is a statement the configuration makes about itself, and no repair
            # pass the flow could start would close it. Rounds of an agent
            # editing source against it would all be wasted.
            raise FlowExit(_EXIT_STILL_RED, str(error)) from error

        red = tuple(result for result in results if not result.ok)
        return {
            "failing": tuple(result.kind for result in red),
            "unfixable": tuple(result.kind for result in red if _out_of_reach(result)),
            "report": _render(red),
            "rounds": state.rounds + 1,
            # What the previous pass found, saved before `failing` is
            # overwritten: an edge condition sees one state, so "the same
            # checks failed again" is only answerable if the state carries it.
            "previous_failing": state.failing,
        }

    return check


def _out_of_reach(result: CheckResult) -> bool:
    """Whether a red check is one no repair pass could close.

    UNREADY (checks._unready) joins UNAVAILABLE here: a Godot project that was
    never imported is red for a reason no edit to the source removes, and the
    handle is an editor run -- which an agent must not start.

    BLOCKED deliberately does not: a check that did not run because its
    predecessor was red closes itself the moment that predecessor goes green,
    and calling it out of reach would end the flow at every ordinary red test.
    Asked first, and before UNFIXABLE at that: a blocked `coverage` is not a
    coverage gap that would have to be written away, it is a check that never
    ran, and the kind alone cannot tell the two apart.
    """
    if result.source == BLOCKED:
        return False
    return result.kind in UNFIXABLE or result.source in (UNAVAILABLE, UNREADY)


def _render(red: tuple[CheckResult, ...]) -> str:
    """The failing checks, for a human and for a model.

    Only the failing ones: a green check's output is noise in a terminal and
    paid-for noise in a prompt.

    A blocked check is named below the findings and never among them: it is
    nothing the repairer can touch, and a defect list holding it would spend a
    round on a check that has no defect. Named all the same, so a report with a
    green lint, a green types and a red test does not read as though coverage
    had been checked.
    """
    blocked = tuple(result.kind for result in red if result.source == BLOCKED)
    findings = tuple(result for result in red if result.source != BLOCKED)
    rendered = "\n\n".join(
        f"## {result.kind} ({result.source})\n{result.output}" for result in findings
    )
    if not blocked:
        return rendered
    line = f"Nicht gelaufen, weil ein Vorgänger rot war: {', '.join(blocked)}"
    # Concatenated conditionally rather than always: a blocked check whose own
    # blocker was blocked leaves no findings at all, and a report opening on two
    # blank lines would read as a lost heading.
    return f"{rendered}\n\n{line}" if rendered else line


@dataclass(frozen=True, slots=True)
class RepairResult:
    """What the repairer says it did.

    Scalars only, because that is what a model adapter can describe as a JSON
    schema. `changed` is the model's own claim and is never trusted on its own:
    the guard node reads the working tree.
    """

    summary: str
    changed: bool = False


REPAIR_PROMPT = """The project's checks are failing. Fix the source so they pass.

## Report

```
{report}
```

Rules:
- Do NOT edit, weaken, skip or delete any of these paths, or anything below a
  directory among them: {forbidden}
  A failing test is a finding about the source, not a problem with the test.
- Do NOT silence a check instead of fixing it: no new `# noqa`,
  `# type: ignore`, `# pragma: no cover` or any other suppression, and no
  change to a configuration file that sets a threshold or a rule set
  (`pyproject.toml`,
  `setup.cfg`, `.ruff.toml`, `mypy.ini` and their like). Suppressions that are
  already there with a stated reason may stay. If a check would only go green
  by silencing it, say that in the summary and leave the code alone.
- Change as little as possible. A narrow fix beats a rewrite.
- If a check fails for a reason you cannot fix in the source, say so in the
  summary and change nothing.

Answer with a summary of what you changed and whether you changed anything.
"""


def make_repair(test_paths: tuple[str, ...]) -> AgentNode[VerifyState]:
    """The `repair` node, told which paths it must keep its hands off.

    Refuses an empty `test_paths`: the rule would then name nothing and read as
    a licence to touch the tests. The flow already declines to start without
    `[verify].tests`; this is the second line of the same rule.
    """
    if not test_paths:
        raise ValueError("repair needs test_paths to protect; configure [verify].tests")

    forbidden = ", ".join(test_paths)

    def apply(_state: VerifyState, reply: object) -> Delta:
        if not isinstance(reply, RepairResult):
            # The adapter validates the reply too; this is the second line,
            # catching a wrong shape before it reaches state and journal.
            raise TypeError(f"expected a RepairResult, got {type(reply).__name__}")
        # `changed` deliberately does not enter the state: the guard reads the
        # truth out of the working tree, and the model's own word about it is
        # worth nothing next to that -- carrying it along would only invite
        # someone to believe it later.
        #
        # The summary replaces the report on purpose: the next `check` pass
        # overwrites it anyway, and carrying the old failures forward would let
        # a stale report reach the next prompt if that pass ever fails to run.
        # Between `repair` and that pass the state therefore reads mixed --
        # `failing` and `unfixable` still hold the old round's values while
        # `report` already holds the summary -- and the guard is the node that
        # sees it that way.
        return {"report": reply.summary}

    return AgentNode(
        "repair",
        prompt=lambda state: REPAIR_PROMPT.format(report=state.report, forbidden=forbidden),
        schema=RepairResult,
        apply=apply,
        tools="edit",
        effort="high",
        max_visits=5,
    )


def _is_protected(path: str, test_paths: tuple[str, ...]) -> bool:
    """Whether one reported path is the protected path itself or lies below it.

    PurePosixPath and not Path: git reports forward slashes on every platform,
    so the comparison is a POSIX one even where the flow runs on Windows.
    Comparing whole segments is the point -- a plain prefix test would let
    "tests/" catch "testsuite/thing.py".

    Case is compared exactly, deliberately, even on Windows: git reports the
    path as its index spells it, so the spelling matches what the project
    configured rather than what a case-insensitive filesystem accepted.
    """
    candidate = PurePosixPath(path)
    for protected in test_paths:
        target = PurePosixPath(protected)
        if candidate == target or target in candidate.parents:
            return True
    return False


def make_guard(
    root: Path,
    test_paths: tuple[str, ...],
    differ: Differ = changed_files,
    baseline: frozenset[str] = frozenset(),
) -> Callable[[VerifyState], Delta]:
    """The `guard` node: what the repairer did, measured against what it may do.

    In a node and not in the tool profile: a profile is a coarse permission and
    knows no paths, and which paths hold tests is something only the project
    knows. Reading the working tree afterwards also catches a change made by a
    detour the profile never named.

    `baseline` is what the working tree already looked like when the run
    started. Everything in it is subtracted before a path is judged, because
    this node answers "what did the repair agent do", not "what is dirty in
    this tree" -- and without the baseline it answers the second question and
    hands that answer over as if it were the first. The first real run ended on
    exactly that: exit 4 naming a test file the agent had never opened.

    The price runs the other way: a file that was already dirty and that the
    agent then edits as well stays invisible here. That is the right way round.
    A missed catch costs one repair the guard did not stop; a false accusation
    costs every run on a working tree that is not pristine, which is most of
    them.

    Refuses an empty `test_paths` for the same reason `make_repair` does: a
    guard that protects nothing is a guard that always says yes.
    """
    if not test_paths:
        raise ValueError("guard needs test_paths to protect; configure [verify].tests")

    def guard(_state: VerifyState) -> Delta:
        try:
            reported = differ(root)
        except WorktreeError as error:
            # A guard that cannot see the working tree must stop the run.
            raise FlowExit(_EXIT_TOUCHED_A_TEST, str(error)) from error
        # Subtracted before anything else, so `touched` -- which feeds the
        # stagnation check -- also counts only what this run produced.
        touched = tuple(path for path in reported if path not in baseline)
        forbidden = tuple(path for path in touched if _is_protected(path, test_paths))
        if forbidden:
            raise FlowExit(
                _EXIT_TOUCHED_A_TEST,
                "the repairer changed protected files: " + ", ".join(forbidden),
            )
        return {"touched": touched}

    return guard


def _out_of_reach_only(state: VerifyState) -> bool:
    """Whether nothing repairable is left -- the one case that ends the run early.

    A subset test and not `bool(state.unfixable)`: one unrepairable check
    standing beside repairable ones used to end the whole run, so a project
    whose coverage check measures by running the tests never reached a repair
    pass at all once a single test was red.

    An *unavailable* check -- one that could not be resolved to a tool at all --
    is unrepairable for the same purposes and now takes the same road: it no
    longer ends the run on the spot, so the repairable checks beside it get
    their rounds and the model is asked up to `max_rounds` times where a single
    exit 1 used to come back immediately. That is the intended trade and it is
    the normal case, not the exception, in a project that permanently lacks a
    tool -- space has no GDScript typechecker, so `types` is unavailable there
    on every single run.
    """
    return bool(state.failing) and set(state.failing) <= set(state.unfixable)


def _why_red(state: VerifyState, max_rounds: int) -> str:
    """Why the run is ending red, in the order the reasons rule each other out."""
    failing = ", ".join(state.failing)
    if _out_of_reach_only(state):
        return (
            f"still red and out of reach: {failing}. "
            f"Closing these means writing tests, which the repairer must not do."
        )
    reason = (
        f"still red after {max_rounds} repair rounds: {failing}"
        if state.rounds > max_rounds
        else f"stagnated: {failing} failed twice over and the last repair pass changed nothing"
    )
    if not state.unfixable:
        return reason
    # Named separately rather than left out: a reader who sees only the
    # unrepairable half goes looking at the coverage threshold instead of at
    # the test that is actually broken.
    return (
        f"{reason}. Of these, out of reach: {', '.join(state.unfixable)} -- "
        f"closing them means writing tests, which the repairer must not do"
    )


def _stagnated(state: VerifyState) -> bool:
    """The same checks failed again and the repair pass in between changed no file."""
    return bool(state.failing) and state.failing == state.previous_failing and not state.touched


def assemble(
    config: Config,
    root: Path,
    check_runner: CheckRunner | None = None,
    differ: Differ = changed_files,
    max_rounds: int = 5,
    baseline: frozenset[str] | None = None,
) -> Graph[VerifyState]:
    """The graph, with everything it talks to passed in.

    Separate from `build` so the flow's tests can put a scripted checker and a
    scripted working tree in front of a real Runner: a flow is worth testing as
    a flow, not as four functions that were each fine on their own.

    `baseline` is what the working tree looked like when the *run* started, and
    it is what `guard` measures against. It is passed in rather than taken here
    whenever the caller knows it: `build` reads it out of the run's recorded
    options, so a resumed run keeps the baseline of its first start. Taking a
    fresh one on resume would hand the repairer an alibi -- everything it had
    already changed before the pause would be in the new baseline, including a
    test file.

    Reading it here is the fallback for a caller that has none, which is
    `assemble` used directly and `build` on a run that recorded nothing.
    """
    if baseline is None:
        try:
            baseline = frozenset(differ(root))
        except WorktreeError:
            # Only this error, not every FlowExit an injected differ might
            # raise: an unreadable tree is the guard's finding to report, at its
            # own turn and with its own message, while anything else a differ
            # raises is a real failure and must not be swallowed here. Dying of
            # it here would also kill the green case, which never reaches the
            # guard at all -- and refusing to check a project because it is not
            # under version control is not this flow's call to make.
            baseline = frozenset()

    def report_red(state: VerifyState) -> Delta:
        raise FlowExit(_EXIT_STILL_RED, _why_red(state, max_rounds))

    def out_of_rounds(state: VerifyState) -> bool:
        return state.rounds > max_rounds

    graph: Graph[VerifyState] = Graph("verify-until-green", start="check")
    graph.add(CodeNode("check", make_check(config, check_runner), max_visits=max_rounds + 1))
    # Every ceiling is max_rounds + 1, check's included. A visit limit is the
    # runner's last resort against a runaway loop; the round counter is the gate
    # this flow actually closes with. The last resort has to sit *above* the
    # gate, never on it: level with it, `--max-rounds 1` would make repair and
    # guard single-visit nodes on a cycle -- which the graph refuses outright --
    # and any run reaching its ceiling would end on the runner's guard, without
    # an exit code and with a message about max_visits instead of the reason it
    # is red.
    graph.add(dataclasses.replace(make_repair(config.test_paths), max_visits=max_rounds + 1))
    graph.add(
        CodeNode(
            "guard",
            make_guard(root, config.test_paths, differ, baseline),
            max_visits=max_rounds + 1,
        )
    )
    graph.add(CodeNode("report_red", report_red))

    # Order matters: next_name takes the first edge whose condition holds, and
    # an edge without one always holds. The unconditional edge goes last.
    graph.edge("check", END, when=lambda state: not state.failing)
    graph.edge(
        "check",
        "report_red",
        when=lambda state: _out_of_reach_only(state) or _stagnated(state) or out_of_rounds(state),
    )
    graph.edge("check", "repair")
    graph.edge("repair", "guard")
    graph.edge("guard", "check")
    # Never taken -- report_red always raises. It is here because validate()
    # refuses a node with no way out, and a dead end is not a way out.
    graph.edge("report_red", END)
    return graph


def build(context: FlowContext) -> LoadedFlow:
    """Assemble the flow for one project and one command line."""
    config = context.config
    if not config.test_paths:
        raise ValueError(
            "verify-until-green needs [verify].tests in .ultraloom/config.toml: "
            "the paths the repairer must not touch. Without it there is nothing "
            "stopping a failing test from being edited away."
        )
    kinds = _kinds_from(context.options.get("checks"), config)
    max_rounds = _max_rounds_from(context.options.get("max_rounds"))
    graph = assemble(
        config,
        context.root,
        max_rounds=max_rounds,
        baseline=context.baseline,
    )
    # LoadedFlow holds any flow's graph and therefore types it over `object`,
    # which Graph -- being mutable -- is invariant in. The cast is the erasure
    # discovery performs on every flow it loads; every node in this graph still
    # only ever sees a VerifyState.
    return LoadedFlow(cast(Graph[object], graph), VerifyState(kinds=kinds))


def _kinds_from(requested: str | None, config: Config) -> tuple[str, ...]:
    """What `--checks` asked for: a profile name, a list, or everything."""
    if requested is None:
        return KINDS
    # The profile's kinds go through the emptiness check below like any other
    # answer: returning them here would leave a profile configured as an empty
    # list the one way to start a run that checks nothing.
    kinds = (
        config.profiles[requested]
        if requested in config.profiles
        else tuple(part.strip() for part in requested.split(",") if part.strip())
    )
    unknown = [kind for kind in kinds if kind not in KINDS]
    if unknown:
        known = ", ".join(KINDS)
        profiles = ", ".join(sorted(config.profiles)) or "none"
        raise ValueError(
            f"unknown check {unknown[0]!r}; known checks: {known}; profiles: {profiles}"
        )
    if not kinds:
        # An empty answer passes the name check above -- there is no name to
        # object to -- and would start a run that verifies nothing and reports
        # success. "" and "," take this path, and so does a profile configured
        # as an empty list: config.py validates the names in a profile, not
        # that it holds any.
        raise ValueError(
            f"--checks {requested!r} names no check to run; known checks: {', '.join(KINDS)}"
        )
    return kinds


def _max_rounds_from(requested: str | None) -> int:
    """How many repair rounds the caller allows.

    The CLI declares `--max-rounds` as `type=int`, so a word never gets this
    far from there: argparse refuses it first, with exit 2. The parse survives
    because the CLI is not the only way in. A hand-written `.flow` marker and a
    direct `build()` call both reach here with whatever string they hold, and
    for those `int()` alone would raise a message about literals that never
    mentions the option. The lower bound has no argparse equivalent at all: a
    ceiling of zero or less reaches the graph as an unbounded cycle and is
    reported as a GraphError about a node's max_visits, which is true and tells
    the caller nothing.
    """
    if requested is None:
        return 5
    try:
        rounds = int(requested)
    except ValueError:
        raise ValueError(f"max_rounds must be a whole number, got {requested!r}") from None
    if rounds < 1:
        raise ValueError(f"max_rounds must be at least 1, got {rounds}")
    return rounds
