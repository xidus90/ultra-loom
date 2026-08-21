"""Tests for node types, graph construction and validation."""

from dataclasses import dataclass

import pytest

from ultraloom.graph import END, AgentNode, CodeNode, GateNode, Graph, GraphError, node_kind


@dataclass(frozen=True, slots=True)
class Data:
    green: bool = False


def code(name: str, max_visits: int = 1) -> CodeNode[Data]:
    return CodeNode(name, lambda _data: {}, max_visits=max_visits)


def test_node_kind_names_the_three_sorts() -> None:
    assert node_kind(code("a")) == "code"
    assert node_kind(AgentNode("b", lambda _d: "ask", schema=Data)) == "agent"
    assert node_kind(GateNode("c", lambda _d: "ok?", lambda _d, _a: {})) == "gate"


def test_an_agent_node_defaults_to_the_reading_profile() -> None:
    node: AgentNode[Data] = AgentNode("review", lambda _d: "ask", schema=Data)

    assert node.tools == "read_only", "writing must be asked for, never inherited"
    assert node.effort == "high"


def test_a_linear_graph_validates() -> None:
    graph: Graph[Data] = Graph("linear", start="first")
    graph.add(code("first"))
    graph.add(code("second"))
    graph.edge("first", "second")
    graph.edge("second", END)

    graph.validate()


def test_adding_the_same_node_name_twice_is_refused() -> None:
    graph: Graph[Data] = Graph("dup", start="first")
    graph.add(code("first"))

    with pytest.raises(GraphError, match="already"):
        graph.add(code("first"))


def test_an_edge_to_an_unknown_node_is_refused_at_validation() -> None:
    graph: Graph[Data] = Graph("dangling", start="first")
    graph.add(code("first"))
    graph.edge("first", "nowhere")

    with pytest.raises(GraphError, match="nowhere"):
        graph.validate()


def test_an_edge_from_an_unknown_node_is_refused_at_validation() -> None:
    graph: Graph[Data] = Graph("ghost", start="first")
    graph.add(code("first"))
    graph.edge("first", END)
    graph.edge("ghost", END)

    with pytest.raises(GraphError, match="edge from unknown node 'ghost'"):
        graph.validate()


def test_a_missing_start_node_is_refused() -> None:
    graph: Graph[Data] = Graph("nostart", start="first")
    graph.add(code("other"))
    graph.edge("other", END)

    with pytest.raises(GraphError, match="start"):
        graph.validate()


def test_an_unreachable_node_is_refused() -> None:
    graph: Graph[Data] = Graph("island", start="first")
    graph.add(code("first"))
    graph.add(code("island"))
    graph.edge("first", END)
    graph.edge("island", END)

    with pytest.raises(GraphError, match="island"):
        graph.validate()


def test_a_node_without_an_outgoing_edge_is_refused() -> None:
    graph: Graph[Data] = Graph("deadend", start="first")
    graph.add(code("first"))

    with pytest.raises(GraphError, match="no outgoing edge"):
        graph.validate()


def test_a_cycle_whose_nodes_allow_only_one_visit_is_refused() -> None:
    graph: Graph[Data] = Graph("loop", start="check")
    graph.add(code("check"))
    graph.add(code("repair"))
    graph.edge("check", END, when=lambda d: d.green)
    graph.edge("check", "repair", when=lambda d: not d.green)
    graph.edge("repair", "check")

    with pytest.raises(GraphError, match="max_visits"):
        graph.validate()


def test_a_cycle_validates_once_its_nodes_allow_repeat_visits() -> None:
    graph: Graph[Data] = Graph("loop", start="check")
    graph.add(code("check", max_visits=5))
    graph.add(code("repair", max_visits=5))
    graph.edge("check", END, when=lambda d: d.green)
    graph.edge("check", "repair", when=lambda d: not d.green)
    graph.edge("repair", "check")

    graph.validate()


def test_next_name_takes_the_first_edge_whose_condition_holds() -> None:
    graph: Graph[Data] = Graph("branch", start="check")
    graph.add(code("check"))
    graph.add(code("repair"))
    graph.edge("check", END, when=lambda d: d.green)
    graph.edge("check", "repair", when=lambda d: not d.green)
    graph.edge("repair", END)

    assert graph.next_name("check", Data(green=True)) == END
    assert graph.next_name("check", Data(green=False)) == "repair"


def test_an_unconditional_edge_always_holds() -> None:
    graph: Graph[Data] = Graph("plain", start="first")
    graph.add(code("first"))
    graph.edge("first", END)

    assert graph.next_name("first", Data()) == END


def test_next_name_raises_when_no_condition_holds() -> None:
    graph: Graph[Data] = Graph("stuck", start="check")
    graph.add(code("check"))
    graph.edge("check", END, when=lambda d: d.green)

    with pytest.raises(GraphError, match="no edge"):
        graph.next_name("check", Data(green=False))


def test_node_looks_up_by_name() -> None:
    graph: Graph[Data] = Graph("one", start="first")
    first = code("first")
    graph.add(first)

    assert graph.node("first") is first

    with pytest.raises(GraphError, match="unknown"):
        graph.node("missing")


def test_an_error_edge_alone_does_not_count_as_an_outgoing_edge() -> None:
    graph: Graph[Data] = Graph("onlyerror", start="first")
    graph.add(code("first"))
    graph.add(code("fallback"))
    graph.edge("first", "fallback", on_error=True)
    graph.edge("fallback", END)

    with pytest.raises(GraphError, match="no outgoing edge"):
        graph.validate()


def test_next_name_ignores_error_edges_and_error_name_finds_them() -> None:
    graph: Graph[Data] = Graph("both", start="first")
    graph.add(code("first"))
    graph.add(code("fallback"))
    # The error edge comes first, so next_name has to skip past it rather than
    # merely stop before reaching it.
    graph.edge("first", "fallback", on_error=True)
    graph.edge("first", END)
    graph.edge("fallback", END)

    assert graph.next_name("first", Data()) == END
    assert graph.error_name("first") == "fallback"
    assert graph.error_name("fallback") is None


def test_an_agent_node_defaults_to_a_delta_free_apply() -> None:
    node: AgentNode[Data] = AgentNode("review", lambda _d: "ask", schema=Data)

    assert node.apply(Data(), object()) == {}
