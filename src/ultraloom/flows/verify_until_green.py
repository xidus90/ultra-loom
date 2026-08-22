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

from ultraloom.checks import CheckResult, run_check
from ultraloom.config import Config
from ultraloom.graph import AgentNode
from ultraloom.runner import FlowExit
from ultraloom.state import Delta

type CheckRunner = Callable[[str, Config], CheckResult]
type Differ = Callable[[Path], tuple[str, ...]]

_EXIT_TOUCHED_A_TEST = 4

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
    # Each entry is "XY path"; a rename adds its original path as its own entry.
    return tuple(entry[3:] for entry in result.stdout.split("\0") if len(entry) > 3)


def _is_protected(path: str, test_paths: tuple[str, ...]) -> bool:
    """Whether one reported path is the protected path itself or lies below it.

    PurePosixPath and not Path: git reports forward slashes on every platform,
    so the comparison is a POSIX one even where the flow runs on Windows.
    Comparing whole segments is the point -- a plain prefix test would let
    "tests/" catch "testsuite/thing.py".
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
