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
    """A plain function. Costs no tokens and is reproducible byte for byte."""

    name: str
    run: Callable[[T], Delta]
    max_visits: int = 1


@dataclass(frozen=True, slots=True)
class AgentNode[T]:
    """A model call with its own prompt, tool profile, effort and output schema."""

    name: str
    prompt: Callable[[T], str]
    schema: type
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

    def edge(self, src: str, dst: str, when: Callable[[T], bool] | None = None) -> None:
        """Join two nodes. Without a condition the edge always holds."""
        self._edges.setdefault(src, []).append(_Edge(dst, when))

    def node(self, name: str) -> Node[T]:
        """Look a node up by name."""
        try:
            return self._nodes[name]
        except KeyError:
            raise GraphError(f"unknown node {name!r}") from None

    def next_name(self, current: str, data: T) -> str:
        """The name of the node after `current`, or END."""
        for candidate in self._edges.get(current, []):
            if candidate.when is None or candidate.when(data):
                return candidate.dst
        raise GraphError(f"no edge out of {current!r} applies to the current state")

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

        for name in self._nodes:
            if not self._edges.get(name):
                raise GraphError(f"node {name!r} has no outgoing edge")

        unreachable = sorted(set(self._nodes) - self._reachable())
        if unreachable:
            raise GraphError(f"unreachable node(s): {', '.join(unreachable)}")

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
