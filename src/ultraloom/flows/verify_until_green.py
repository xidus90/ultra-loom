"""Check, repair, check again — until it is green or honestly red.

The first flow ultraloom ships. It knows nothing about any one project: which
tools check it and where its tests live both arrive through Config, which is
what lets the same flow run in a Python package and in a Godot game.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from ultraloom.checks import KINDS, CheckResult, run_check
from ultraloom.config import Config
from ultraloom.discovery import FlowContext, LoadedFlow
from ultraloom.graph import END, AgentNode, CodeNode, Graph
from ultraloom.runner import FlowExit
from ultraloom.state import Delta

type CheckRunner = Callable[[str, Config], CheckResult]
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


def make_check(config: Config, runner: CheckRunner = run_check) -> Callable[[VerifyState], Delta]:
    """The `check` node, bound to one project's configuration.

    The runner is a parameter so the flow's own tests never start a real tool:
    a test that shells out to ruff measures ruff.
    """

    def check(state: VerifyState) -> Delta:
        # Concurrent for the same reason checks.run_all is: subprocess.run
        # releases the GIL while it waits. Not run_all itself, because that one
        # runs every kind and this node runs the kinds the caller asked for.
        with ThreadPoolExecutor(max_workers=max(1, len(state.kinds))) as pool:
            results = tuple(pool.map(lambda kind: runner(kind, config), state.kinds))

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
    """Whether a red check is one no repair pass could close."""
    return result.kind in UNFIXABLE or result.source == UNAVAILABLE


def _render(red: tuple[CheckResult, ...]) -> str:
    """The failing checks, for a human and for a model.

    Only the failing ones: a green check's output is noise in a terminal and
    paid-for noise in a prompt.
    """
    return "\n\n".join(f"## {result.kind} ({result.source})\n{result.output}" for result in red)


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


def changed_files(root: Path) -> tuple[str, ...]:
    """Every path git reports as changed, added or untracked below `root`.

    `status` and not `diff`, because a repairer may add a file, and an
    untracked file is invisible to `diff`. `-z` because a path holding
    non-ASCII comes back quoted otherwise, and `-uall` because the default
    collapses a whole untracked directory into one entry that is not a path to
    any file.
    """
    try:
        result = subprocess.run(
            ("git", "status", "--porcelain", "-z", "-uall"),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as error:
        # A directory that is not there never reaches a return code: the spawn
        # itself fails. Same answer as a non-zero one -- see below.
        raise FlowExit(
            _EXIT_TOUCHED_A_TEST, f"cannot inspect the working tree in {root}: {error}"
        ) from error
    if result.returncode != 0:
        # A guard that cannot see the working tree must stop the run. Reading
        # an unanswerable question as "nothing changed" would disable exactly
        # the rule this node exists for.
        raise FlowExit(
            _EXIT_TOUCHED_A_TEST,
            f"cannot inspect the working tree in {root}: {result.stderr.strip()}",
        )
    return _parse_status(result.stdout)


def _parse_status(output: str) -> tuple[str, ...]:
    """The paths out of a `--porcelain -z` answer, read field by field.

    Most fields are "XY path". A rename or a copy is the exception: git emits
    *two* fields for it, and only the first carries the three-character prefix
    -- the second is the original path, bare. Cutting three characters off that
    one too would turn "tests/test_cli.py" into "s/test_cli.py", and a test
    renamed out of the way would walk straight past the guard.
    """
    fields = [field for field in output.split("\0") if field]
    paths: list[str] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        paths.append(field[3:])
        index += 1
        if field[:1] in ("R", "C") and index < len(fields):
            paths.append(fields[index])
            index += 1
    return tuple(paths)


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
    root: Path, test_paths: tuple[str, ...], differ: Differ = changed_files
) -> Callable[[VerifyState], Delta]:
    """The `guard` node: what the repairer did, measured against what it may do.

    In a node and not in the tool profile: a profile is a coarse permission and
    knows no paths, and which paths hold tests is something only the project
    knows. Reading the working tree afterwards also catches a change made by a
    detour the profile never named.

    Refuses an empty `test_paths` for the same reason `make_repair` does: a
    guard that protects nothing is a guard that always says yes.
    """
    if not test_paths:
        raise ValueError("guard needs test_paths to protect; configure [verify].tests")

    def guard(_state: VerifyState) -> Delta:
        touched = differ(root)
        forbidden = tuple(path for path in touched if _is_protected(path, test_paths))
        if forbidden:
            raise FlowExit(
                _EXIT_TOUCHED_A_TEST,
                "the repairer changed protected files: " + ", ".join(forbidden),
            )
        return {"touched": touched}

    return guard


def _why_red(state: VerifyState, max_rounds: int) -> str:
    """Why the run is ending red, in the order the reasons rule each other out."""
    if state.unfixable:
        return (
            f"still red and out of reach: {', '.join(state.unfixable)}. "
            f"Closing these means writing tests, which the repairer must not do."
        )
    if state.rounds > max_rounds:
        return f"still red after {max_rounds} repair rounds: {', '.join(state.failing)}"
    return (
        f"stagnated: {', '.join(state.failing)} failed twice over and the last "
        f"repair pass changed nothing"
    )


def _stagnated(state: VerifyState) -> bool:
    """The same checks failed again and the repair pass in between changed no file."""
    return bool(state.failing) and state.failing == state.previous_failing and not state.touched


def assemble(
    config: Config,
    root: Path,
    check_runner: CheckRunner = run_check,
    differ: Differ = changed_files,
    max_rounds: int = 5,
) -> Graph[VerifyState]:
    """The graph, with everything it talks to passed in.

    Separate from `build` so the flow's tests can put a scripted checker and a
    scripted working tree in front of a real Runner: a flow is worth testing as
    a flow, not as four functions that were each fine on their own.
    """

    def report_red(state: VerifyState) -> Delta:
        raise FlowExit(_EXIT_STILL_RED, _why_red(state, max_rounds))

    def out_of_rounds(state: VerifyState) -> bool:
        return state.rounds > max_rounds

    graph: Graph[VerifyState] = Graph("verify-until-green", start="check")
    # One more than repair: the last check grades the last repair pass.
    graph.add(CodeNode("check", make_check(config, check_runner), max_visits=max_rounds + 1))
    graph.add(make_repair(config.test_paths))
    graph.add(CodeNode("guard", make_guard(root, config.test_paths, differ), max_visits=max_rounds))
    graph.add(CodeNode("report_red", report_red))

    # Order matters: next_name takes the first edge whose condition holds, and
    # an edge without one always holds. The unconditional edge goes last.
    graph.edge("check", END, when=lambda state: not state.failing)
    graph.edge(
        "check",
        "report_red",
        when=lambda state: bool(state.unfixable) or _stagnated(state) or out_of_rounds(state),
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
    max_rounds = int(context.options.get("max_rounds", 5))
    graph = assemble(config, context.root, max_rounds=max_rounds)
    # LoadedFlow holds any flow's graph and therefore types it over `object`,
    # which Graph -- being mutable -- is invariant in. The cast is the erasure
    # discovery performs on every flow it loads; every node in this graph still
    # only ever sees a VerifyState.
    return LoadedFlow(cast(Graph[object], graph), VerifyState(kinds=kinds))


def _kinds_from(requested: str | None, config: Config) -> tuple[str, ...]:
    """What `--checks` asked for: a profile name, a list, or everything."""
    if requested is None:
        return KINDS
    if requested in config.profiles:
        return config.profiles[requested]
    kinds = tuple(part.strip() for part in requested.split(",") if part.strip())
    unknown = [kind for kind in kinds if kind not in KINDS]
    if unknown:
        known = ", ".join(KINDS)
        profiles = ", ".join(sorted(config.profiles)) or "none"
        raise ValueError(
            f"unknown check {unknown[0]!r}; known checks: {known}; profiles: {profiles}"
        )
    return kinds
