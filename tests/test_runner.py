"""Tests for the execution loop over code and agent nodes."""

from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path

import pytest

from ultraloom.graph import END, AgentNode, CodeNode, GateNode, Graph
from ultraloom.journal import Journal
from ultraloom.model.fake import FakeModel
from ultraloom.model.port import ModelError, Reply
from ultraloom.runner import Result, Runner, VisitLimitError, _guard_visits, _monotonic
from ultraloom.state import State


@dataclass(frozen=True, slots=True)
class Data:
    green: bool = False
    attempts: int = 0
    note: str = ""


@dataclass(frozen=True, slots=True)
class Verdict:
    fix: str = ""


def ticking_clock() -> Callable[[], float]:
    """A clock that advances one second per call, so durations are deterministic."""
    ticks = count()
    return lambda: float(next(ticks))


def a_journal(tmp_path: Path) -> Journal:
    return Journal(tmp_path / "run.jsonl")


def test_a_single_code_node_runs_and_the_run_ends_done(tmp_path: Path) -> None:
    graph: Graph[Data] = Graph("one", start="mark")
    graph.add(CodeNode("mark", lambda _d: {"green": True}))
    graph.edge("mark", END)

    result = Runner(graph, a_journal(tmp_path), clock=ticking_clock()).run(Data())

    assert result.status == "done"
    assert result.state.data == Data(green=True)


def test_two_code_nodes_run_in_edge_order(tmp_path: Path) -> None:
    graph: Graph[Data] = Graph("two", start="first")
    graph.add(CodeNode("first", lambda _d: {"note": "a"}))
    graph.add(CodeNode("second", lambda d: {"note": d.note + "b"}))
    graph.edge("first", "second")
    graph.edge("second", END)

    result = Runner(graph, a_journal(tmp_path), clock=ticking_clock()).run(Data())

    assert result.state.data.note == "ab"


def test_a_condition_picks_the_branch(tmp_path: Path) -> None:
    graph: Graph[Data] = Graph("branch", start="check")
    graph.add(CodeNode("check", lambda _d: {"green": True}))
    graph.add(CodeNode("repair", lambda _d: {"note": "repaired"}))
    graph.edge("check", END, when=lambda d: d.green)
    graph.edge("check", "repair", when=lambda d: not d.green)
    graph.edge("repair", END)

    result = Runner(graph, a_journal(tmp_path), clock=ticking_clock()).run(Data())

    assert result.state.data.note == "", "the green branch must skip the repair node"


def test_a_back_edge_loops_until_the_condition_flips(tmp_path: Path) -> None:
    graph: Graph[Data] = Graph("loop", start="check")
    graph.add(CodeNode("check", lambda d: {"green": d.attempts >= 2}, max_visits=5))
    graph.add(CodeNode("bump", lambda d: {"attempts": d.attempts + 1}, max_visits=5))
    graph.edge("check", END, when=lambda d: d.green)
    graph.edge("check", "bump", when=lambda d: not d.green)
    graph.edge("bump", "check")

    result = Runner(graph, a_journal(tmp_path), clock=ticking_clock()).run(Data())

    assert result.status == "done"
    assert result.state.data.attempts == 2


def test_exceeding_max_visits_ends_the_run_as_an_error(tmp_path: Path) -> None:
    """The guard must stop the loop, not spin forever."""
    graph: Graph[Data] = Graph("runaway", start="check")
    graph.add(CodeNode("check", lambda _d: {}, max_visits=2))
    graph.add(CodeNode("bump", lambda d: {"attempts": d.attempts + 1}, max_visits=2))
    graph.edge("check", "bump")
    graph.edge("bump", "check")

    result = Runner(graph, a_journal(tmp_path), clock=ticking_clock()).run(Data())

    assert result.status == "error"
    assert result.detail is not None
    assert "max_visits" in result.detail
    assert "check" in result.detail, "the detail must name the node that hit its ceiling"
    assert result.node == "check"


def test_the_visit_limit_is_journalled_at_the_node_that_hit_it(tmp_path: Path) -> None:
    journal = a_journal(tmp_path)
    graph: Graph[Data] = Graph("runaway", start="check")
    graph.add(CodeNode("check", lambda _d: {}, max_visits=2))
    graph.add(CodeNode("bump", lambda d: {"attempts": d.attempts + 1}, max_visits=2))
    graph.edge("check", "bump")
    graph.edge("bump", "check")

    Runner(graph, journal, clock=ticking_clock()).run(Data())

    last = journal.entries()[-1]
    assert (last.node, last.outcome) == ("check", "error")
    assert last.detail is not None
    assert "max_visits" in last.detail


def test_the_graph_is_validated_before_the_first_node_runs(tmp_path: Path) -> None:
    ran: list[str] = []

    def record(_data: Data) -> dict[str, object]:
        ran.append("first")
        return {}

    graph: Graph[Data] = Graph("bad", start="first")
    graph.add(CodeNode("first", record))
    graph.edge("first", "nowhere")

    result = Runner(graph, a_journal(tmp_path), clock=ticking_clock()).run(Data())

    assert result.status == "error"
    assert ran == [], "validation must run before any node does"


def test_a_state_no_edge_applies_to_ends_the_run_as_an_error(tmp_path: Path) -> None:
    """A gap in the conditions is a flow bug, and must be reported as one."""
    graph: Graph[Data] = Graph("gap", start="check")
    graph.add(CodeNode("check", lambda _d: {}))
    graph.edge("check", END, when=lambda d: d.green)

    result = Runner(graph, a_journal(tmp_path), clock=ticking_clock()).run(Data())

    assert result.status == "error"
    assert result.node == "check"
    assert result.detail is not None
    assert "no edge out of" in result.detail


def test_an_agent_node_asks_the_model_and_applies_its_answer(tmp_path: Path) -> None:
    graph: Graph[Data] = Graph("ask", start="review")
    graph.add(
        AgentNode(
            "review",
            prompt=lambda d: f"attempts so far: {d.attempts}",
            schema=Verdict,
            apply=lambda _d, reply: {"note": getattr(reply, "fix", "")},
            tools="read_only",
            effort="low",
        )
    )
    graph.edge("review", END)
    model = FakeModel([Reply(Verdict(fix="raise the ceiling"), tokens=42)])

    result = Runner(graph, a_journal(tmp_path), model=model, clock=ticking_clock()).run(Data())

    assert result.state.data.note == "raise the ceiling"
    assert model.seen[0].prompt == "attempts so far: 0"
    assert model.seen[0].tools == ("Glob", "Grep", "Read")
    assert model.seen[0].effort == "low"


def test_mcp_servers_reach_the_request_of_an_mcp_node(tmp_path: Path) -> None:
    graph: Graph[Data] = Graph("ask", start="review")
    graph.add(AgentNode("review", lambda _d: "ask", schema=Verdict, tools="mcp"))
    graph.edge("review", END)
    model = FakeModel([Reply(Verdict(), tokens=0)])

    Runner(
        graph,
        a_journal(tmp_path),
        model=model,
        clock=ticking_clock(),
        mcp_servers=("sentry",),
    ).run(Data())

    assert model.seen[0].tools == ("Glob", "Grep", "Read", "mcp__sentry")


def test_the_journal_records_tokens_and_the_tool_profile(tmp_path: Path) -> None:
    journal = a_journal(tmp_path)
    graph: Graph[Data] = Graph("ask", start="review")
    graph.add(
        AgentNode(
            "review",
            prompt=lambda _d: "ask",
            schema=Verdict,
            apply=lambda _d, _r: {},
            tools="edit",
        )
    )
    graph.edge("review", END)

    Runner(
        graph, journal, model=FakeModel([Reply(Verdict(), tokens=42)]), clock=ticking_clock()
    ).run(Data())

    entry = journal.entries()[0]
    assert entry.kind == "agent"
    assert entry.tokens == 42
    assert entry.tools == "edit"
    assert entry.effort == "high"
    assert entry.seconds == 1.0


def test_a_code_node_journals_no_tokens_and_no_profile(tmp_path: Path) -> None:
    journal = a_journal(tmp_path)
    graph: Graph[Data] = Graph("one", start="mark")
    graph.add(CodeNode("mark", lambda _d: {"green": True}))
    graph.edge("mark", END)

    Runner(graph, journal, clock=ticking_clock()).run(Data())

    entry = journal.entries()[0]
    assert (entry.kind, entry.tokens, entry.tools, entry.effort) == ("code", 0, None, None)


def test_an_agent_node_without_a_model_is_an_error_not_a_crash(tmp_path: Path) -> None:
    graph: Graph[Data] = Graph("ask", start="review")
    graph.add(AgentNode("review", lambda _d: "ask", schema=Verdict, apply=lambda _d, _r: {}))
    graph.edge("review", END)

    result = Runner(graph, a_journal(tmp_path), clock=ticking_clock()).run(Data())

    assert result.status == "error"
    assert result.detail is not None
    assert "needs a model" in result.detail


def test_a_raising_node_ends_the_run_at_that_node(tmp_path: Path) -> None:
    def boom(_data: Data) -> dict[str, object]:
        raise RuntimeError("the report is unreadable")

    graph: Graph[Data] = Graph("boom", start="read")
    graph.add(CodeNode("read", boom))
    graph.edge("read", END)

    result = Runner(graph, a_journal(tmp_path), clock=ticking_clock()).run(Data())

    assert result.status == "error"
    assert result.node == "read"
    assert result.detail is not None
    assert "unreadable" in result.detail


def test_a_node_error_is_journalled_before_the_run_ends(tmp_path: Path) -> None:
    """An error that leaves no trace cannot be diagnosed later."""
    journal = a_journal(tmp_path)
    graph: Graph[Data] = Graph("ask", start="review")
    graph.add(AgentNode("review", lambda _d: "ask", schema=Verdict, apply=lambda _d, _r: {}))
    graph.edge("review", END)

    Runner(graph, journal, model=FakeModel([ModelError("unreachable")]), clock=ticking_clock()).run(
        Data()
    )

    entry = journal.entries()[0]
    assert entry.outcome == "error"
    assert entry.detail is not None
    assert "unreachable" in entry.detail


def test_an_on_error_edge_carries_the_run_onward(tmp_path: Path) -> None:
    def boom(_data: Data) -> dict[str, object]:
        raise RuntimeError("first attempt failed")

    graph: Graph[Data] = Graph("recover", start="try")
    graph.add(CodeNode("try", boom))
    graph.add(CodeNode("fallback", lambda _d: {"note": "took the fallback"}))
    # A normal exit is required of every node; the error edge overrides it only
    # for the run in which the node actually raised.
    graph.edge("try", END)
    graph.edge("try", "fallback", on_error=True)
    graph.edge("fallback", END)

    result = Runner(graph, a_journal(tmp_path), clock=ticking_clock()).run(Data())

    assert result.status == "done"
    assert result.state.data.note == "took the fallback"


def test_a_gate_node_pauses_the_run_with_its_question(tmp_path: Path) -> None:
    """A gate must stop the run, never guess the answer for the human."""
    journal = a_journal(tmp_path)
    graph: Graph[Data] = Graph("gated", start="confirm")
    graph.add(
        GateNode(
            "confirm",
            question=lambda d: f"ship with {d.attempts} attempts?",
            apply=lambda _d, answer: {"note": answer},
        )
    )
    graph.add(CodeNode("ship", lambda _d: {"note": "shipped"}))
    graph.edge("confirm", "ship")
    graph.edge("ship", END)

    result = Runner(graph, journal, clock=ticking_clock()).run(Data())

    assert result.status == "paused"
    assert result.node == "confirm"
    assert result.question == "ship with 0 attempts?"
    assert result.state.data.note == "", "the node after the gate must not have run"

    entry = journal.entries()[0]
    assert (entry.kind, entry.outcome, entry.detail) == (
        "gate",
        "paused",
        "ship with 0 attempts?",
    )
    assert journal.entries()[1:] == ()


def test_result_is_immutable() -> None:
    result = Result("done", State(Data()), None, None, None)
    with pytest.raises(AttributeError):
        result.status = "error"  # type: ignore[misc]  # immutability is the point


def test_an_unknown_tool_profile_ends_the_run_as_an_error(tmp_path: Path) -> None:
    """A typo in a profile name must surface as a failed run, not a crash."""
    graph: Graph[Data] = Graph("ask", start="review")
    graph.add(AgentNode("review", lambda _d: "ask", schema=Verdict, tools="read-only"))
    graph.edge("review", END)

    result = Runner(
        graph,
        a_journal(tmp_path),
        model=FakeModel([Reply(Verdict(), tokens=0)]),
        clock=ticking_clock(),
    ).run(Data())

    assert result.status == "error"
    assert result.node == "review"
    assert result.detail is not None
    assert "read-only" in result.detail


def test_the_visit_guard_raises_the_error_named_in_the_contract() -> None:
    node: CodeNode[Data] = CodeNode("check", lambda _d: {}, max_visits=1)
    state = State(Data(), {"check": 2})

    with pytest.raises(VisitLimitError, match="check"):
        _guard_visits(node, state)


def test_the_default_clock_is_the_monotonic_clock() -> None:
    """The clock that ships to a caller who injects none must actually work."""
    first = _monotonic()
    second = _monotonic()

    assert isinstance(first, float)
    assert second >= first, "a monotonic clock never runs backwards"
