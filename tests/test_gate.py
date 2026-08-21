"""Tests for approval points: stopping, and carrying on with an answer."""

from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path

from ultraloom.gate import pending_gate
from ultraloom.graph import END, CodeNode, GateNode, Graph
from ultraloom.journal import Entry, Journal, input_hash
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


def test_the_answers_effect_reaches_the_journal(tmp_path: Path) -> None:
    """A replay has only the file; an entry without the delta destroys the answer."""
    journal = Journal(tmp_path / "r.jsonl")
    graph = approval_flow()
    Runner(graph, journal, clock=ticking_clock()).run(Data())

    Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="yes")

    answered = journal.entries()[1]
    assert answered.delta == {"approved": "yes"}
    assert answered.seconds == 0.0, "an answer from outside the process has no measured duration"


def test_the_answered_entry_keys_on_the_data_the_gate_saw(tmp_path: Path) -> None:
    """Both of the gate's entries must share the key a replay looks it up by."""
    journal = Journal(tmp_path / "r.jsonl")
    graph = approval_flow()
    Runner(graph, journal, clock=ticking_clock()).run(Data())

    Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="yes")

    paused, answered = journal.entries()[0], journal.entries()[1]
    assert answered.input_hash == paused.input_hash == input_hash("ask", Data())


def test_an_answer_for_a_run_that_is_not_paused_fails_visibly(tmp_path: Path) -> None:
    """A user's answer must never evaporate into a full re-run of the flow."""
    ran: list[str] = []
    graph: Graph[Data] = Graph("plain", start="write")

    def write(_d: Data) -> dict[str, str]:
        ran.append("write")
        return {"note": "done"}

    graph.add(CodeNode("write", write))
    graph.edge("write", END)

    result = Runner(graph, Journal(tmp_path / "r.jsonl"), clock=ticking_clock()).resume(
        Data(), answer="yes"
    )

    assert result.status == "error"
    assert result.detail == "no gate is waiting for an answer"
    assert ran == [], "an answer for an unpaused run must not re-execute the flow"


def staged_approval_flow() -> Graph[Data]:
    """A gate with a state-changing node in front of it.

    The branch's other gate fixtures put the gate at `graph.start`, where the
    initial payload and the payload the gate sees coincide — and where a resume
    that ignores the earlier nodes' deltas cannot be told from one that honours
    them.
    """
    graph: Graph[Data] = Graph("staged", start="prepare")
    graph.add(CodeNode("prepare", lambda d: {"note": d.note + "p"}))
    graph.add(
        GateNode(
            "ask",
            question=lambda _d: "May I write the wiki entry?",
            apply=lambda d, answer: {"note": d.note + answer},
        )
    )
    graph.add(CodeNode("write", lambda d: {"note": d.note + "!"}))
    graph.edge("prepare", "ask")
    graph.edge("ask", "write")
    graph.edge("write", END)
    return graph


def test_a_gate_behind_another_node_applies_the_answer_to_the_state_it_saw(
    tmp_path: Path,
) -> None:
    """The gate's `apply` must see the prepared payload, not the initial one."""
    journal = Journal(tmp_path / "r.jsonl")
    graph = staged_approval_flow()
    assert Runner(graph, journal, clock=ticking_clock()).run(Data()).status == "paused"

    result = Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="Y")

    assert result.status == "done"
    assert result.state.data.note == "pY!"


def test_a_gate_behind_another_node_keys_both_entries_on_the_gates_own_input(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    graph = staged_approval_flow()
    Runner(graph, journal, clock=ticking_clock()).run(Data())

    Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="Y")

    gate_entries = [entry for entry in journal.entries() if entry.node == "ask"]
    assert [entry.outcome for entry in gate_entries] == ["paused", "ok"]
    assert {entry.input_hash for entry in gate_entries} == {input_hash("ask", Data(note="p"))}


def test_a_resumed_run_behind_another_node_replays_cleanly(tmp_path: Path) -> None:
    """A resume that keys the answer wrongly leaves a journal no replay can walk."""
    journal = Journal(tmp_path / "r.jsonl")
    graph = staged_approval_flow()
    Runner(graph, journal, clock=ticking_clock()).run(Data())
    Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="Y")

    replayed = Runner(graph, journal, clock=ticking_clock(), replay=True).run(Data())

    assert replayed.status == "done"
    assert replayed.state.data.note == "pY!"


def test_replay_mode_refuses_an_answer_in_the_runner(tmp_path: Path) -> None:
    """`Runner` is published, so the CLI's refusal cannot be the only one."""
    journal = Journal(tmp_path / "r.jsonl")
    graph = approval_flow()
    Runner(graph, journal, clock=ticking_clock()).run(Data())
    before = (tmp_path / "r.jsonl").read_text(encoding="utf-8")

    result = Runner(graph, journal, clock=ticking_clock(), replay=True).resume(Data(), answer="yes")

    assert result.status == "error"
    assert result.detail == "a replay cannot take an answer; resume the run instead"
    assert (tmp_path / "r.jsonl").read_text(encoding="utf-8") == before


def looping_gate_flow() -> Graph[Data]:
    """A gate on a cycle, so the same node pauses once per pass."""
    graph: Graph[Data] = Graph("looping", start="ask")
    graph.add(
        GateNode(
            "ask",
            question=lambda d: f"again? {d.note}",
            apply=lambda d, answer: {"note": d.note + answer},
            max_visits=3,
        )
    )
    graph.add(CodeNode("step", lambda d: {"note": d.note + "."}, max_visits=3))
    graph.edge("ask", "step")
    graph.edge("step", "ask")
    return graph


def test_a_gate_visited_twice_can_be_answered_twice(tmp_path: Path) -> None:
    """The answer belongs to the pause that is open, not to the node's name.

    Keyed on the name, the second answer was spent on the first pass -- already
    answered, so the journal cache short-circuited before the answer was read --
    and vanished: the same question came back with nothing journalled.
    """
    journal = Journal(tmp_path / "r.jsonl")
    graph = looping_gate_flow()
    Runner(graph, journal, clock=ticking_clock()).run(Data())
    Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="y")

    result = Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="z")

    assert result.status == "paused"
    assert result.state.data.note == "y.z.", "the second answer must reach the open pause"
    assert result.question == "again? y.z."


def test_a_second_answer_is_journalled_under_the_second_pause(tmp_path: Path) -> None:
    """A dropped answer left two identical pause entries and no record of it."""
    journal = Journal(tmp_path / "r.jsonl")
    graph = looping_gate_flow()
    Runner(graph, journal, clock=ticking_clock()).run(Data())
    Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="y")

    Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="z")

    answered = [entry for entry in journal.entries() if entry.detail == "answered: z"]
    assert len(answered) == 1
    assert answered[0].delta == {"note": "y.z"}
    assert answered[0].input_hash == input_hash("ask", Data(note="y."))


def test_an_answer_is_applied_to_exactly_one_pass(tmp_path: Path) -> None:
    """One answer must not carry the loop further than the pause it belongs to."""
    journal = Journal(tmp_path / "r.jsonl")
    graph = looping_gate_flow()
    Runner(graph, journal, clock=ticking_clock()).run(Data())

    result = Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="y")

    assert result.status == "paused"
    assert result.state.data.note == "y."
    assert [entry.detail for entry in journal.entries()].count("answered: y") == 1
