"""The execution loop: pick the next node, run it, journal it, carry on."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import assert_never

from ultraloom.gate import pending_gate
from ultraloom.graph import END, AgentNode, CodeNode, GateNode, Graph, GraphError, Node, node_kind
from ultraloom.journal import Entry, Journal, input_hash
from ultraloom.model.port import Model, Request
from ultraloom.state import Delta, State
from ultraloom.tools import resolve_tools

type Clock = Callable[[], float]


class VisitLimitError(RuntimeError):
    """Raised when a node ran more often than its max_visits allows."""


class ReplayGapError(RuntimeError):
    """Raised in replay mode for a node the journal does not cover."""


@dataclass(frozen=True, slots=True)
class Result[T]:
    """How a run ended, and where."""

    status: str
    state: State[T]
    node: str | None
    question: str | None
    detail: str | None


class Runner[T]:
    """Walks a graph, journalling every step.

    Every method reads the journal first. A node whose name and input already
    have a successful entry is *not* executed: its recorded delta is returned.
    That is what makes a resume cheap, and it applies to `run` exactly as much
    as to `resume` — a `run` over a journal that already covers the flow
    executes nothing at all.

    So a node is recognised by its name and the input it saw, never by its
    implementation. Editing a node's body and running again over the same
    journal replays the old result for the new code. That is the price of the
    alternative: hashing a function body would throw a journal away on a
    cosmetic edit. Start a fresh run when a node changes.
    """

    def __init__(
        self,
        graph: Graph[T],
        journal: Journal,
        model: Model | None = None,
        clock: Clock | None = None,
        mcp_servers: Sequence[str] = (),
        replay: bool = False,
    ) -> None:
        self._graph = graph
        self._journal = journal
        self._model = model
        # An injected clock keeps durations deterministic, which is what makes
        # the golden-journal test in task 8 a real test.
        self._clock = clock if clock is not None else _monotonic
        self._mcp_servers = tuple(mcp_servers)
        self._replay = replay

    def run(self, data: T) -> Result[T]:
        """Run the flow from its start node.

        Subject to the journal cache described on the class: this is not a
        guarantee that anything executes.
        """
        try:
            self._graph.validate()
        except GraphError as error:
            return Result("error", State(data), None, None, str(error))
        return self._walk(State(data), self._graph.start)

    def resume(self, data: T, answer: str | None = None) -> Result[T]:
        """Carry a paused run onward, applying the answer to its open gate.

        Without an answer the gate pauses again: treating a missing answer as
        consent would make the approval point decorative.

        The journal cache described on the class governs here too: nothing
        before the gate is executed a second time.

        With an answer the walk still starts at `graph.start`, so every node
        before the gate is reconstructed from the journal and the gate's `apply`
        sees the payload the gate actually saw. Jumping straight to the gate
        with the caller's initial payload would hand `apply` a state that never
        existed, and would key the answer under a hash no replay can find.

        """
        if self._replay and answer is not None:
            # Refused here and not only at the CLI: `Runner` is published, so an
            # invariant enforced by another module is not an invariant. Applying
            # an answer calls the gate's `apply` live, which is precisely the
            # promise a replay makes it will not do.
            return Result(
                "error",
                State(data),
                None,
                None,
                "a replay cannot take an answer; resume the run instead",
            )

        try:
            self._graph.validate()
        except GraphError as error:
            return Result("error", State(data), None, None, str(error))

        gate = pending_gate(self._journal)
        if answer is None:
            return self._walk(State(data), self._graph.start)
        if gate is None:
            # An answer with nothing to answer is a mistake worth reporting: a
            # silent re-run from the start would discard the answer and charge
            # for every node again, which is the worst reading of a user's "yes".
            return Result("error", State(data), None, None, "no gate is waiting for an answer")

        node = self._graph.node(gate.node)
        if not isinstance(node, GateNode):
            return Result("error", State(data), gate.node, None, f"{gate.node!r} is not a gate")

        return self._walk(State(data), self._graph.start, _Answer(gate.input_hash, answer))

    def _walk(self, state: State[T], name: str, answer: _Answer | None = None) -> Result[T]:
        while name != END:
            node = self._graph.node(name)
            state = state.with_visit(name)
            try:
                _guard_visits(node, state)
            except VisitLimitError as error:
                # The guard raises, so a runaway loop has its own type and can
                # be told from a node failure. It is converted here, where the
                # state still exists: exceeding max_visits is an outcome of the
                # flow, not a crash of the harness, so nothing leaves `run`.
                detail = str(error) + self._why_it_looped(node, state)
                self._write(node, state, {}, "error", 0, 0.0, detail)
                return Result("error", state, name, None, detail)

            # Matched on the pause's own key, not on the node's name: a gate on
            # a cycle pauses once per pass, and an earlier pass is already
            # answered in the journal. Keying on the name would spend the answer
            # there -- where the cache short-circuits before it is even read --
            # and the open pause would be asked again with nothing recorded.
            pending = (
                answer.text
                if answer is not None and answer.key == input_hash(name, state.data)
                else None
            )
            if pending is not None:
                answer = None

            try:
                outcome = self._step(node, state, pending)
            except ReplayGapError as error:
                return Result("error", state, name, None, str(error))
            if outcome.paused:
                return Result("paused", outcome.state, name, outcome.question, None)
            if outcome.failed:
                fallback = self._graph.error_name(name)
                if fallback is None:
                    return Result("error", outcome.state, name, None, outcome.detail)
                state, name = outcome.state, fallback
                continue

            state = outcome.state
            try:
                name = self._graph.next_name(name, state.data)
            except GraphError as error:
                return Result("error", state, name, None, str(error))
        return Result("done", state, None, None, None)

    def _why_it_looped(self, node: Node[T], state: State[T]) -> str:
        """The half of a visit-limit report the bare count does not carry.

        A cycle whose passes leave the payload alone hits the same
        `(node, input_hash)` key every time, so the journal serves the first
        pass's delta and the node never runs again. Without this the author
        reads "exceeded max_visits" and looks for a loop that ran too often,
        when in fact it ran once and spun.
        """
        served = self._journal.lookup(node.name, input_hash(node.name, state.data), outcome="ok")
        if served is None:
            return ""
        return (
            "; every visit saw the same payload, so the journal served the first pass "
            "and the node never ran again — a bounded cycle has to advance its payload"
        )

    def _step(self, node: Node[T], state: State[T], answer: str | None = None) -> _Step[T]:
        # The most recent *successful* entry, not the most recent one: both the
        # visit-limit path and a gate's pause write a non-ok entry under the key
        # of an entry that succeeded, and taking the latest match would re-run a
        # node that is already done — for an agent node, a real model call.
        # This holds outside replay mode too: without it, resuming a paused run
        # from the start would pay again for every node before the gate.
        cached = self._journal.lookup(node.name, input_hash(node.name, state.data), outcome="ok")
        if cached is not None:
            return _Step(state.merged(cached.delta))
        if self._replay:
            # Not an error outcome: an error outcome would be offered the node's
            # on_error edge, and taking a fallback the original run never took
            # would make a broken replay look like a run that handled a failure.
            raise ReplayGapError(f"node {node.name!r} is not in the journal")

        if answer is not None and isinstance(node, GateNode):
            return self._answered(node, state, answer)

        started = self._clock()
        try:
            delta, tokens = self._invoke(node, state)
        # A node runs arbitrary project code, so anything may come out of it.
        # A crash here would lose the journal entry that explains the failure.
        # It is turned into an error outcome here, never swallowed.
        except Exception as error:
            seconds = self._clock() - started
            self._write(node, state, {}, "error", 0, seconds, str(error))
            return _Step(state, failed=True, detail=str(error))

        seconds = self._clock() - started
        if isinstance(node, GateNode):
            question = node.question(state.data)
            self._write(node, state, {}, "paused", 0, seconds, question)
            return _Step(state, paused=True, question=question)

        self._write(node, state, delta, "ok", tokens, seconds, None)
        return _Step(state.merged(delta))

    def _answered(self, node: GateNode[T], state: State[T], answer: str) -> _Step[T]:
        """Apply a gate's answer against the state the gate paused on."""
        delta = node.apply(state.data, answer)
        # The delta goes into the entry, not an empty one: the journal is the
        # only source a replay has, so an entry without the answer's effect
        # would not postpone that information but destroy it.
        # `seconds=0.0` because this entry records an answer that arrived from
        # outside the process, not a step this run executed and timed; an entry
        # that represents no measured execution carries no measured duration.
        # The hash is taken over the data the gate saw, so this entry shares the
        # key of the pause entry that a replay looks the gate up by.
        self._write(node, state, delta, "ok", 0, 0.0, f"answered: {answer}")
        return _Step(state.merged(delta))

    def _invoke(self, node: Node[T], state: State[T]) -> tuple[Delta, int]:
        match node:
            case CodeNode():
                return node.run(state.data), 0
            case AgentNode():
                if self._model is None:
                    # The message names the install, because "no model" leaves
                    # the reader to guess that a model is something you add.
                    raise RuntimeError(
                        f"node {node.name!r} needs a model; install it with "
                        'uv add "ultraloom[agent]"'
                    )
                reply = self._model.ask(
                    Request(
                        prompt=node.prompt(state.data),
                        tools=resolve_tools(node.tools, self._mcp_servers),
                        effort=node.effort,
                        schema=node.schema,
                    )
                )
                return node.apply(state.data, reply.value), reply.tokens
            case GateNode():
                # A gate contributes no delta of its own; the answer that
                # resumes it does, once there is one.
                return {}, 0
            case _:  # pragma: no cover  # the Node union is exhaustive; mypy proves it here
                assert_never(node)

    def _write(
        self,
        node: Node[T],
        state: State[T],
        delta: Delta,
        outcome: str,
        tokens: int,
        seconds: float,
        detail: str | None,
    ) -> None:
        # A replay reproduces a run; one that appended to the journal it is
        # reading would not be reproducing it. The guard sits here rather than
        # at each call site so no path — visit limit, pause, error — escapes it.
        if self._replay:
            return
        agent = node if isinstance(node, AgentNode) else None
        self._journal.append(
            Entry(
                node=node.name,
                kind=node_kind(node),
                input_hash=input_hash(node.name, state.data),
                delta=dict(delta),
                outcome=outcome,
                # The profile name, not the resolved list: the list is derived
                # from it plus the mcp servers, and the name is what a resume
                # needs to recognise the node it is looking at.
                tools=agent.tools if agent else None,
                effort=agent.effort if agent else None,
                tokens=tokens,
                seconds=seconds,
                detail=detail,
            )
        )


@dataclass(frozen=True, slots=True)
class _Answer:
    """An answer waiting for the pause it belongs to, carried through the walk.

    `key` is the paused entry's `input_hash`, which names one visit of one node.
    """

    key: str
    text: str


@dataclass(frozen=True, slots=True)
class _Step[T]:
    state: State[T]
    paused: bool = False
    failed: bool = False
    question: str | None = None
    detail: str | None = None


def _guard_visits[T](node: Node[T], state: State[T]) -> None:
    """Raise when a node has run more often than its ceiling allows."""
    if state.visit_count(node.name) > node.max_visits:
        raise VisitLimitError(f"node {node.name!r} exceeded max_visits={node.max_visits}")


def _monotonic() -> float:
    """The default clock. Monotonic, so a clock adjustment cannot shorten a step."""
    return time.monotonic()
