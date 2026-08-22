"""Check, repair, check again — until it is green or honestly red.

The first flow ultraloom ships. It knows nothing about any one project: which
tools check it and where its tests live both arrive through Config, which is
what lets the same flow run in a Python package and in a Godot game.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from ultraloom.checks import CheckResult, run_check
from ultraloom.config import Config
from ultraloom.graph import AgentNode
from ultraloom.state import Delta

type CheckRunner = Callable[[str, Config], CheckResult]

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

{report}

Rules:
- Do NOT edit, weaken, skip or delete anything under: {forbidden}
  A failing test is a finding about the source, not a problem with the test.
- Change as little as possible. A narrow fix beats a rewrite.
- If a check fails for a reason you cannot fix in the source, say so in the
  summary and change nothing.

Answer with a summary of what you changed and whether you changed anything.
"""


def make_repair(test_paths: tuple[str, ...]) -> AgentNode[VerifyState]:
    """The `repair` node, told which paths it must keep its hands off."""
    forbidden = ", ".join(test_paths)

    def apply(_state: VerifyState, reply: object) -> Delta:
        if not isinstance(reply, RepairResult):
            # The runner types the reply as `object`, so this is the one place
            # a wrong shape can still be caught before it reaches the journal.
            raise TypeError(f"expected a RepairResult, got {type(reply).__name__}")
        # The summary replaces the report on purpose: the next `check` pass
        # overwrites it anyway, and carrying the old failures forward would let
        # a stale report reach the next prompt if that pass ever fails to run.
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
