"""Tests for resume from the journal, replay without a model, and reproducibility."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import count
from pathlib import Path

from ultraloom.graph import END, AgentNode, CodeNode, GateNode, Graph
from ultraloom.journal import Entry, Journal
from ultraloom.model.fake import FakeModel
from ultraloom.model.port import Reply
from ultraloom.runner import Runner


@dataclass(frozen=True, slots=True)
class Data:
    steps: str = ""


@dataclass(frozen=True, slots=True)
class Verdict:
    fix: str = ""


def ticking_clock() -> Callable[[], float]:
    ticks = count()
    return lambda: float(next(ticks))


def counting_flow(log: list[str]) -> Graph[Data]:
    """Two code nodes that record every real execution."""

    def first(data: Data) -> dict[str, object]:
        log.append("first")
        return {"steps": data.steps + "1"}

    def second(data: Data) -> dict[str, object]:
        log.append("second")
        return {"steps": data.steps + "2"}

    graph: Graph[Data] = Graph("counting", start="first")
    graph.add(CodeNode("first", first))
    graph.add(CodeNode("second", second))
    graph.edge("first", "second")
    graph.edge("second", END)
    return graph


def looping_flow(log: list[str]) -> Graph[Data]:
    """A cycle whose nodes leave `data` alone, so every visit shares one hash.

    That is what makes the visit-limit entry a decoy: it lands on the same
    `(node, input_hash)` key as the successful entry written one visit earlier.
    """

    def note(name: str) -> Callable[[Data], dict[str, object]]:
        def run(_data: Data) -> dict[str, object]:
            log.append(name)
            return {}

        return run

    graph: Graph[Data] = Graph("looping", start="a")
    # A cycle must raise its own ceiling; two visits is the smallest that lets
    # the third visit of "a" hit the limit and write the decoy entry.
    graph.add(CodeNode("a", note("a"), max_visits=2))
    graph.add(CodeNode("b", note("b"), max_visits=2))
    graph.edge("a", "b")
    graph.edge("b", "a")
    return graph


def test_a_resume_over_a_finished_journal_executes_nothing(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    log: list[str] = []
    Runner(counting_flow(log), journal, clock=ticking_clock()).run(Data())
    assert log == ["first", "second"]

    log.clear()
    result = Runner(counting_flow(log), journal, clock=ticking_clock()).resume(Data())

    assert log == [], "unchanged inputs must come from the journal, not from a rerun"
    assert result.state.data.steps == "12"


def test_a_second_run_over_the_same_journal_executes_everything_again(tmp_path: Path) -> None:
    """A fresh `run` is not a retrace, so the journal must not stand in for it."""
    journal = Journal(tmp_path / "r.jsonl")
    log: list[str] = []
    Runner(counting_flow(log), journal, clock=ticking_clock()).run(Data())

    log.clear()
    Runner(counting_flow(log), journal, clock=ticking_clock()).run(Data())

    assert log == ["first", "second"]


def test_a_truncated_journal_reruns_only_what_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    journal = Journal(path)
    log: list[str] = []
    Runner(counting_flow(log), journal, clock=ticking_clock()).run(Data())

    kept = path.read_text(encoding="utf-8").splitlines()[:1]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    log.clear()
    result = Runner(counting_flow(log), journal, clock=ticking_clock()).resume(Data())

    assert log == ["second"], "the first node is retraced, the second is not"
    assert result.state.data.steps == "12", "a resumed run must reach the same state"


def test_a_changed_input_reruns_and_so_does_everything_after_it(tmp_path: Path) -> None:
    """The cache key is the node name plus the data it saw, and nothing else.

    So a different starting payload invalidates the whole chain. A rewritten
    node *body* under the same name does not — see the report; `input_hash`
    hashes data, and a run of the same flow over the same input is the case
    resume exists for.
    """
    journal = Journal(tmp_path / "r.jsonl")
    log: list[str] = []
    Runner(counting_flow(log), journal, clock=ticking_clock()).run(Data())

    log.clear()
    result = Runner(counting_flow(log), journal, clock=ticking_clock()).resume(Data(steps="seed"))

    assert log == ["first", "second"]
    assert result.state.data.steps == "seed12"


def test_a_journalled_error_is_not_replayed_as_success(tmp_path: Path) -> None:
    """Only an `ok` entry may stand in for a real run."""
    journal = Journal(tmp_path / "r.jsonl")
    attempts: list[str] = []

    def flaky(_data: Data) -> dict[str, object]:
        attempts.append("try")
        if len(attempts) == 1:
            raise RuntimeError("first attempt failed")
        return {"steps": "recovered"}

    graph: Graph[Data] = Graph("flaky", start="try")
    graph.add(CodeNode("try", flaky))
    graph.edge("try", END)

    first = Runner(graph, journal, clock=ticking_clock()).run(Data())
    assert first.status == "error"

    second = Runner(graph, journal, clock=ticking_clock()).resume(Data())
    assert second.status == "done"
    assert second.state.data.steps == "recovered"


def test_a_later_non_ok_entry_does_not_hide_an_earlier_success(tmp_path: Path) -> None:
    """Obligation (a): the search finds the most recent `ok`, not the most recent.

    The visit-limit entry for `a` is written after `a` already succeeded under
    the very same key. A lookup that took the latest entry and then tested its
    outcome would re-execute a node that is done.
    """
    journal = Journal(tmp_path / "r.jsonl")
    log: list[str] = []
    first = Runner(looping_flow(log), journal, clock=ticking_clock()).run(Data())
    assert first.status == "error"
    assert log == ["a", "b", "a", "b"], "every pass of the cycle executes"

    outcomes = [(entry.node, entry.outcome) for entry in journal.entries()]
    assert outcomes == [
        ("a", "ok"),
        ("b", "ok"),
        ("a", "ok"),
        ("b", "ok"),
        ("a", "error"),
    ], "the decoy must be in place"
    keys = {entry.input_hash for entry in journal.entries() if entry.node == "a"}
    assert len(keys) == 1, "both entries for 'a' must share one key, or there is no decoy"

    log.clear()
    second = Runner(looping_flow(log), journal, clock=ticking_clock()).resume(Data())

    assert log == [], "a node with a successful entry must not run again"
    assert second.status == "error", "the visit limit still stops the cycle"


def test_a_node_before_a_gate_runs_once_across_a_pause_and_a_resume(tmp_path: Path) -> None:
    """Obligation (b): resuming from the start must not pay for finished work."""
    journal = Journal(tmp_path / "r.jsonl")
    log: list[str] = []

    def prepare(data: Data) -> dict[str, object]:
        log.append("prepare")
        return {"steps": data.steps + "p"}

    graph: Graph[Data] = Graph("approve", start="prepare")
    graph.add(CodeNode("prepare", prepare))
    graph.add(
        GateNode(
            "gate",
            question=lambda _d: "ok to proceed?",
            apply=lambda d, answer: {"steps": d.steps + answer},
        )
    )
    graph.edge("prepare", "gate")
    graph.edge("gate", END)

    paused = Runner(graph, journal, clock=ticking_clock()).run(Data())
    assert paused.status == "paused"
    assert log == ["prepare"]

    again = Runner(graph, journal, clock=ticking_clock()).resume(Data())

    assert again.status == "paused", "without an answer the gate pauses again"
    assert log == ["prepare"], "the node before the gate must not run a second time"


def test_replay_mode_refuses_to_execute_a_node_that_is_not_in_the_journal(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    log: list[str] = []

    result = Runner(counting_flow(log), journal, clock=ticking_clock(), replay=True).run(Data())

    assert result.status == "error"
    assert result.detail is not None
    assert "not in the journal" in result.detail
    assert log == [], "replay must never run a node for real"


def test_replay_mode_reproduces_a_finished_run(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    log: list[str] = []
    expected = Runner(counting_flow(log), journal, clock=ticking_clock()).run(Data())

    log.clear()
    replayed = Runner(counting_flow(log), journal, clock=ticking_clock(), replay=True).run(Data())

    assert log == []
    assert replayed.state.data == expected.state.data
    assert replayed.status == "done"


def test_replay_writes_no_new_journal_lines(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    journal = Journal(path)
    Runner(counting_flow([]), journal, clock=ticking_clock()).run(Data())
    before = path.read_text(encoding="utf-8")

    Runner(counting_flow([]), journal, clock=ticking_clock(), replay=True).run(Data())

    assert path.read_text(encoding="utf-8") == before


def test_replay_writes_nothing_even_on_the_visit_limit_path(tmp_path: Path) -> None:
    """The visit-limit entry is written outside `_step`, so it needs its own proof."""
    path = tmp_path / "r.jsonl"
    journal = Journal(path)
    Runner(looping_flow([]), journal, clock=ticking_clock()).run(Data())
    before = path.read_text(encoding="utf-8")

    log: list[str] = []
    result = Runner(looping_flow(log), journal, clock=ticking_clock(), replay=True).run(Data())

    assert result.status == "error"
    assert log == []
    assert path.read_text(encoding="utf-8") == before


def test_an_agent_node_is_replayed_without_asking_the_model(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    graph = _asking_flow()

    Runner(
        graph,
        journal,
        model=FakeModel([Reply(Verdict(fix="patched"), tokens=5)]),
        clock=ticking_clock(),
    ).run(Data())

    empty = FakeModel([])
    result = Runner(graph, journal, model=empty, clock=ticking_clock(), replay=True).run(Data())

    assert empty.seen == (), "a replayed agent node must cost nothing"
    assert result.state.data.steps == "patched"


class _WatchingJournal(Journal):
    """A journal that records every lookup a walk was served from.

    A replay writes nothing by construction, so comparing the file before and
    after says only that the replay ran. What has to be measured is which
    entries it walked: this records node, key and delta in the order the walk
    asked for them.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.served: list[tuple[str, str, Mapping[str, object]]] = []

    def lookup(self, node: str, node_input_hash: str, outcome: str | None = None) -> Entry | None:
        entry = super().lookup(node, node_input_hash, outcome)
        if entry is not None:
            self.served.append((entry.node, entry.input_hash, entry.delta))
        return entry


def _golden_flow() -> Graph[Data]:
    """Three nodes, so the entry-by-entry comparison has an order to get wrong."""
    graph: Graph[Data] = Graph("golden", start="first")
    graph.add(CodeNode("first", lambda d: {"steps": d.steps + "1"}))
    graph.add(
        AgentNode(
            "review",
            prompt=lambda _d: "ask",
            schema=Verdict,
            apply=lambda d, reply: {"steps": d.steps + getattr(reply, "fix", "")},
        )
    )
    graph.add(CodeNode("last", lambda d: {"steps": d.steps + "z"}))
    graph.edge("first", "review")
    graph.edge("review", "last")
    graph.edge("last", END)
    return graph


def _golden_run(path: Path, journal: Journal | None = None) -> Journal:
    """One recorded run of the golden flow, with a fixed clock and a fixed reply."""
    written = journal if journal is not None else Journal(path)
    Runner(
        _golden_flow(),
        written,
        model=FakeModel([Reply(Verdict(fix="patched"), tokens=5)]),
        clock=ticking_clock(),
    ).run(Data())
    return written


def test_a_replay_walks_the_recorded_entries_in_order(tmp_path: Path) -> None:
    """The golden-journal test: the replay is compared entry by entry.

    Not "the replay changed nothing" — that is true of any replay by
    construction. What is asserted is that the walk was served exactly the
    recorded entries, in the recorded order, with the recorded keys and deltas,
    and arrived at the same end state.
    """
    path = tmp_path / "r.jsonl"
    watching = _WatchingJournal(path)
    _golden_run(path, watching)
    recorded = [(e.node, e.input_hash, e.delta) for e in watching.entries() if e.outcome == "ok"]
    assert [node for node, _key, _delta in recorded] == ["first", "review", "last"]

    watching.served.clear()
    replayed = Runner(
        _golden_flow(),
        watching,
        model=FakeModel([]),
        clock=ticking_clock(),
        replay=True,
    ).run(Data())

    assert replayed.status == "done"
    assert watching.served == recorded, "the replay must walk the recorded entries, in order"
    assert replayed.state.data.steps == "1patchedz", "and arrive where the recorded run arrived"


def test_two_runs_of_the_same_flow_write_the_same_bytes(tmp_path: Path) -> None:
    """The other half of the golden test: the write path itself is deterministic.

    Separate journal paths, because a second run over the same file appends to
    it. Byte equality covers what an entry-by-entry comparison does not — field
    order, serialisation, and the durations the injected clock fixes.
    """
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"

    _golden_run(first)
    _golden_run(second)

    assert first.read_bytes() == second.read_bytes()


def test_a_replay_gap_names_the_missing_node(tmp_path: Path) -> None:
    """The gap must say *which* node is missing, on the Result the runner built."""
    path = tmp_path / "r.jsonl"
    journal = Journal(path)
    log: list[str] = []
    Runner(counting_flow(log), journal, clock=ticking_clock()).run(Data())

    kept = path.read_text(encoding="utf-8").splitlines()[:1]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    log.clear()
    result = Runner(counting_flow(log), journal, clock=ticking_clock(), replay=True).run(Data())

    assert result.status == "error"
    assert result.node == "second", "the run stops at the node the journal lacks"
    assert result.detail == "node 'second' is not in the journal"
    assert log == [], "the cached node must not rerun, the missing one must not run at all"


def _asking_flow() -> Graph[Data]:
    graph: Graph[Data] = Graph("ask", start="review")
    graph.add(
        AgentNode(
            "review",
            prompt=lambda _d: "ask",
            schema=Verdict,
            apply=lambda _d, reply: {"steps": getattr(reply, "fix", "")},
        )
    )
    graph.edge("review", END)
    return graph


def test_a_resume_without_an_answer_does_not_grow_the_journal(tmp_path: Path) -> None:
    """Looking at what a gate asks must not change what the journal says.

    The pause is already recorded under the gate's input hash. A second entry
    with the same key records nothing new, and it makes the journal grow once
    per look — a run that was checked on ten times would read as ten pauses.
    """
    journal = Journal(tmp_path / "r.jsonl")

    graph: Graph[Data] = Graph("approve", start="gate")
    graph.add(
        GateNode(
            "gate",
            question=lambda _d: "ok to proceed?",
            apply=lambda d, answer: {"steps": d.steps + answer},
        )
    )
    graph.edge("gate", END)

    Runner(graph, journal, clock=ticking_clock()).run(Data())
    after_pause = journal.entries()

    Runner(graph, journal, clock=ticking_clock()).resume(Data())
    Runner(graph, journal, clock=ticking_clock()).resume(Data())

    assert journal.entries() == after_pause, "a look at the open question writes nothing"


def test_a_gate_on_a_cycle_still_records_each_pass_it_pauses_on(tmp_path: Path) -> None:
    """The pause is keyed by the visit, so a second pass is a second entry."""
    journal = Journal(tmp_path / "r.jsonl")

    graph: Graph[Data] = Graph("approve", start="gate")
    graph.add(
        GateNode(
            "gate",
            question=lambda d: f"proceed from {d.steps!r}?",
            apply=lambda d, answer: {"steps": d.steps + answer},
            max_visits=3,
        )
    )
    # A back edge, so the gate is asked once per pass.
    graph.edge("gate", "gate", when=lambda d: len(d.steps) < 2)
    graph.edge("gate", END)

    Runner(graph, journal, clock=ticking_clock()).run(Data())
    # The answer advances the payload, so the next pass hashes to a new key.
    Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="a")

    paused = [entry for entry in journal.entries() if entry.outcome == "paused"]
    assert len({entry.input_hash for entry in paused}) == len(paused) > 1
