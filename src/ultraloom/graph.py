"""Node types, edges, and the validation that runs before the first node."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, assert_never

from ultraloom.state import Delta

END = "__end__"

type Effort = Literal["low", "medium", "high", "xhigh", "max"]


class GraphError(ValueError):
    """Raised for a graph that cannot run: dangling edge, island, open cycle."""


@dataclass(frozen=True, slots=True)
class CodeNode[T]:
    """A plain function. Costs no tokens and is reproducible byte for byte.

    `max_visits` raises the ceiling so this node may sit on a cycle. It does
    not make a cycle work on its own: the runner serves any node whose name and
    input already have a successful journal entry from that entry instead of
    executing it. A loop whose passes leave the payload unchanged therefore
    runs **once** and then spins on the cache until the ceiling stops it. Every
    pass of a bounded cycle has to advance the payload.
    """

    name: str
    run: Callable[[T], Delta]
    max_visits: int = 1


@dataclass(frozen=True, slots=True)
class AgentNode[T]:
    """A model call with its own prompt, tool profile, effort and output schema.

    `schema` must be a frozen dataclass whose fields are all `str`, `int`,
    `float` or `bool`. That is what a model adapter can describe as a JSON
    schema, and a dataclass checks no field types when it is built from the
    reply — so anything wider would let a wrong-typed value into the state and
    the journal unnoticed. A field without a default is asked of the model as
    required.
    """

    name: str
    prompt: Callable[[T], str]
    schema: type
    # The reply is typed only by `schema`, which the type system cannot tie to
    # this callable's parameter; the flow narrows it where it knows the type.
    apply: Callable[[T, object], Delta] = lambda _data, _reply: {}
    tools: str = "read_only"
    effort: Effort = "high"
    max_visits: int = 1


@dataclass(frozen=True, slots=True)
class GateNode[T]:
    """Stops and puts a question. The run ends resumable."""

    name: str
    question: Callable[[T], str]
    apply: Callable[[T, str], Delta]
    max_visits: int = 1


type Node[T] = CodeNode[T] | AgentNode[T] | GateNode[T]


def node_kind[T](node: Node[T]) -> str:
    """The node's sort, as written into the journal."""
    match node:
        case CodeNode():
            return "code"
        case AgentNode():
            return "agent"
        case GateNode():
            return "gate"
        case _:  # pragma: no cover  # the Node union is exhaustive; mypy proves it here
            assert_never(node)


@dataclass(frozen=True, slots=True)
class _Edge[T]:
    dst: str
    when: Callable[[T], bool] | None
    on_error: bool = False


@dataclass(slots=True)
class Graph[T]:
    """A flow: named nodes joined by edges that carry conditions."""

    name: str
    start: str
    _nodes: dict[str, Node[T]] = field(default_factory=dict)
    _edges: dict[str, list[_Edge[T]]] = field(default_factory=dict)

    def add(self, node: Node[T]) -> None:
        """Register a node. Its name is its address."""
        if node.name in self._nodes:
            raise GraphError(f"node {node.name!r} was already added")
        self._nodes[node.name] = node

    def edge(
        self,
        src: str,
        dst: str,
        when: Callable[[T], bool] | None = None,
        on_error: bool = False,
    ) -> None:
        """Join two nodes. Without a condition the edge always holds.

        An on_error edge is taken only when the source node raised; it is
        invisible to the normal path, so a fallback is a visible edge in the
        flow rather than hidden retry logic in the runner.

        Raises:
            GraphError: if a condition is put on an error edge. `error_name`
                does not evaluate one, so accepting it would let an author's
                condition be ignored with nothing to reveal it.
        """
        if when is not None and on_error:
            raise GraphError(
                f"the error edge from {src!r} to {dst!r} cannot carry a condition; "
                f"an error edge is unconditional"
            )
        self._edges.setdefault(src, []).append(_Edge(dst, when, on_error))

    def node(self, name: str) -> Node[T]:
        """Look a node up by name."""
        try:
            return self._nodes[name]
        except KeyError:
            raise GraphError(f"unknown node {name!r}") from None

    def next_name(self, current: str, data: T) -> str:
        """The name of the node after `current`, or END."""
        for candidate in self._edges.get(current, []):
            if candidate.on_error:
                continue
            if candidate.when is None or candidate.when(data):
                return candidate.dst
        raise GraphError(f"no edge out of {current!r} applies to the current state")

    def error_name(self, current: str) -> str | None:
        """Where to go when `current` raised, or None to end the run."""
        for candidate in self._edges.get(current, []):
            if candidate.on_error:
                return candidate.dst
        return None

    def validate(self) -> None:
        """Refuse a graph that cannot run, before the first node runs."""
        if self.start not in self._nodes:
            raise GraphError(f"start node {self.start!r} was never added")

        for src, edges in self._edges.items():
            if src not in self._nodes:
                raise GraphError(f"edge from unknown node {src!r}")
            for candidate in edges:
                if candidate.dst != END and candidate.dst not in self._nodes:
                    raise GraphError(f"edge from {src!r} to unknown node {candidate.dst!r}")

        # Reachability first: an island with no edges at all is unreachable
        # *and* has no way out, and "no outgoing edge" would send its author
        # looking for a missing edge instead of a missing path to the node.
        unreachable = sorted(set(self._nodes) - self._reachable())
        if unreachable:
            raise GraphError(f"unreachable node(s): {', '.join(unreachable)}")

        # An error edge alone is not an exit: a node whose only way out is the
        # fallback would run once and then have nowhere to go on success.
        for name in self._nodes:
            if not [edge for edge in self._edges.get(name, []) if not edge.on_error]:
                raise GraphError(f"node {name!r} has no outgoing edge")

        self._check_cycles_are_bounded()

    def _reachable(self) -> set[str]:
        seen: set[str] = set()
        pending = [self.start]
        while pending:
            name = pending.pop()
            if name in seen or name == END:
                continue
            seen.add(name)
            pending.extend(edge.dst for edge in self._edges.get(name, []))
        return seen

    def _check_cycles_are_bounded(self) -> None:
        """A back edge is allowed; an unbounded loop is not.

        Every node that sits on a cycle must raise its own ceiling above the
        default of one visit. That makes the loop guard visible in the flow
        instead of hidden in the runner.
        """
        for name in sorted(self._nodes):
            if self._on_a_cycle(name) and self._nodes[name].max_visits <= 1:
                raise GraphError(
                    f"node {name!r} sits on a cycle but allows one visit; raise its max_visits"
                )

    def _on_a_cycle(self, start: str) -> bool:
        pending = [edge.dst for edge in self._edges.get(start, [])]
        seen: set[str] = set()
        while pending:
            name = pending.pop()
            if name == start:
                return True
            if name in seen or name == END:
                continue
            seen.add(name)
            pending.extend(edge.dst for edge in self._edges.get(name, []))
        return False
