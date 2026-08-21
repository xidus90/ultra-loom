"""Tests for approval points: stopping, and carrying on with an answer."""

from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path

from ultraloom.gate import pending_gate
from ultraloom.graph import END, CodeNode, GateNode, Graph
from ultraloom.journal import Entry, Journal
from ultraloom.runner import Runner


@dataclass(frozen=True, slots=True)
class Data:
    approved: str = ""
    note: str = ""


def ticking_clock() -> Callable[[], float]:
    ticks = count()
    return lambda: float(next(ticks))


def approval_flow() -> Graph[Data]:
    graph: Graph[Data] = Graph("approve", start="ask")
    graph.add(
        GateNode(
            "ask",
            question=lambda _d: "May I write the wiki entry?",
            apply=lambda _d, answer: {"approved": answer},
        )
    )
    graph.add(CodeNode("write", lambda d: {"note": f"wrote it: {d.approved}"}))
    graph.edge("ask", "write")
    graph.edge("write", END)
    return graph


def paused_entry(node: str, detail: str | None) -> Entry:
    """A pause entry written by hand, to reach states no flow produces."""
    return Entry(
        node=node,
        kind="gate",
        input_hash="0" * 64,
        delta={},
        outcome="paused",
        tools=None,
        effort=None,
        tokens=0,
        seconds=0.0,
        detail=detail,
    )


def test_a_gate_pauses_the_run_and_puts_its_question(tmp_path: Path) -> None:
    result = Runner(approval_flow(), Journal(tmp_path / "r.jsonl"), clock=ticking_clock()).run(
        Data()
    )

    assert result.status == "paused"
    assert result.node == "ask"
    assert result.question == "May I write the wiki entry?"


def test_the_node_after_the_gate_did_not_run(tmp_path: Path) -> None:
    result = Runner(approval_flow(), Journal(tmp_path / "r.jsonl"), clock=ticking_clock()).run(
        Data()
    )

    assert result.state.data.note == "", "a pause must stop before the next node, not after it"


def test_the_pause_is_journalled_with_the_question(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    Runner(approval_flow(), journal, clock=ticking_clock()).run(Data())

    entry = journal.entries()[0]
    assert (entry.kind, entry.outcome) == ("gate", "paused")
    assert entry.detail == "May I write the wiki entry?"


def test_pending_gate_reads_the_open_question_from_the_journal(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    Runner(approval_flow(), journal, clock=ticking_clock()).run(Data())

    gate = pending_gate(journal)
    assert gate is not None
    assert (gate.node, gate.question) == ("ask", "May I write the wiki entry?")


def test_pending_gate_is_none_on_a_finished_run(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    graph: Graph[Data] = Graph("plain", start="write")
    graph.add(CodeNode("write", lambda _d: {"note": "done"}))
    graph.edge("write", END)
    Runner(graph, journal, clock=ticking_clock()).run(Data())

    assert pending_gate(journal) is None


def test_pending_gate_is_none_on_an_empty_journal(tmp_path: Path) -> None:
    assert pending_gate(Journal(tmp_path / "absent.jsonl")) is None


def test_pending_gate_is_none_when_the_pause_carries_no_question(tmp_path: Path) -> None:
    """A pause without a question has nothing to answer, so it is not pending."""
    journal = Journal(tmp_path / "r.jsonl")
    journal.append(paused_entry("ask", None))

    assert pending_gate(journal) is None


def test_resume_applies_the_answer_and_finishes_the_run(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    graph = approval_flow()
    Runner(graph, journal, clock=ticking_clock()).run(Data())

    result = Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="yes")

    assert result.status == "done"
    assert result.state.data.note == "wrote it: yes"


def test_resume_journals_the_answer_without_rewriting_the_pause(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    graph = approval_flow()
    Runner(graph, journal, clock=ticking_clock()).run(Data())

    Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="yes")

    entries = journal.entries()
    assert [(e.node, e.outcome, e.detail) for e in entries] == [
        ("ask", "paused", "May I write the wiki entry?"),
        ("ask", "ok", "answered: yes"),
        ("write", "ok", None),
    ]


def test_resume_without_an_open_gate_just_runs_the_flow(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    graph: Graph[Data] = Graph("plain", start="write")
    graph.add(CodeNode("write", lambda _d: {"note": "done"}))
    graph.edge("write", END)

    result = Runner(graph, journal, clock=ticking_clock()).resume(Data())

    assert result.status == "done"
    assert result.state.data.note == "done"


def test_resuming_an_open_gate_without_an_answer_pauses_again(tmp_path: Path) -> None:
    """Silently treating a missing answer as consent would defeat the gate."""
    journal = Journal(tmp_path / "r.jsonl")
    graph = approval_flow()
    Runner(graph, journal, clock=ticking_clock()).run(Data())

    result = Runner(graph, journal, clock=ticking_clock()).resume(Data())

    assert result.status == "paused"
    assert result.node == "ask"


def test_resume_refuses_a_graph_that_cannot_run(tmp_path: Path) -> None:
    graph: Graph[Data] = Graph("broken", start="absent")

    result = Runner(graph, Journal(tmp_path / "r.jsonl"), clock=ticking_clock()).resume(Data())

    assert result.status == "error"
    assert result.detail is not None
    assert "absent" in result.detail


def test_resume_refuses_an_answer_for_a_node_that_is_not_a_gate(tmp_path: Path) -> None:
    """The journal is data on disk; a pause naming a code node must not be applied."""
    journal = Journal(tmp_path / "r.jsonl")
    journal.append(paused_entry("write", "who paused me?"))
    graph: Graph[Data] = Graph("plain", start="write")
    graph.add(CodeNode("write", lambda _d: {"note": "done"}))
    graph.edge("write", END)

    result = Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="yes")

    assert result.status == "error"
    assert result.node == "write"
    assert result.detail == "'write' is not a gate"


def test_resume_reports_a_gate_with_no_applicable_edge(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    graph: Graph[Data] = Graph("approve", start="ask")
    graph.add(
        GateNode(
            "ask",
            question=lambda _d: "May I?",
            apply=lambda _d, answer: {"approved": answer},
        )
    )
    graph.add(CodeNode("write", lambda _d: {"note": "done"}))
    graph.edge("ask", "write", when=lambda d: d.approved == "yes")
    graph.edge("write", END)
    Runner(graph, journal, clock=ticking_clock()).run(Data())

    result = Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="no")

    assert result.status == "error"
    assert result.node == "ask"
    assert result.detail is not None
    assert "no edge out of 'ask'" in result.detail
