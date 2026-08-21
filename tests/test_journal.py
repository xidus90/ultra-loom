"""Tests for the run journal: the log and the only source of a resume."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from ultraloom.journal import Entry, Journal, JournalError, input_hash

# Fixtures write the same LF bytes the journal writes; text mode on Windows
# would turn them into CRLF and test something the journal never produces.
LF = chr(10)


@dataclass(frozen=True, slots=True)
class Data:
    green: bool = False
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class Opaque:
    """A payload holding something JSON has no representation for."""

    thing: object = object()


def an_entry(node: str = "run_tests", outcome: str = "ok", **kw: object) -> Entry:
    fields: dict[str, object] = {
        "node": node,
        "kind": "code",
        "input_hash": "abc123",
        "delta": {"green": True},
        "outcome": outcome,
        "tools": None,
        "effort": None,
        "tokens": 0,
        "seconds": 0.0,
        "detail": None,
    }
    fields.update(kw)
    return Entry(**fields)  # type: ignore[arg-type]  # the helper's job is to spell the fields once


def test_the_same_data_hashes_the_same_way() -> None:
    assert input_hash("node", Data(green=True)) == input_hash("node", Data(green=True))


def test_different_data_hashes_differently() -> None:
    assert input_hash("node", Data(green=True)) != input_hash("node", Data(green=False))


def test_the_node_name_is_part_of_the_hash() -> None:
    assert input_hash("first", Data()) != input_hash("second", Data())


def test_field_order_does_not_change_the_hash() -> None:
    """A hash that depends on dict ordering would break resume silently."""
    assert input_hash("n", Data(green=True, attempts=1)) == input_hash(
        "n", Data(attempts=1, green=True)
    )


def test_a_plain_payload_hashes_too() -> None:
    """Not every input a node sees is a dataclass instance."""
    assert input_hash("n", {"green": True}) == input_hash("n", {"green": True})


def test_an_unserializable_payload_is_refused() -> None:
    """Hashing an address would make the same payload hash differently twice."""
    with pytest.raises(JournalError, match="object"):
        input_hash("n", Opaque())


def test_a_payload_that_is_a_class_is_refused() -> None:
    """A class object is not an instance, so it is not unpacked, and JSON balks."""
    with pytest.raises(JournalError, match="type"):
        input_hash("n", Data)


def test_an_appended_entry_reads_back(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "run.jsonl")
    journal.append(an_entry())

    assert journal.entries() == (an_entry(),)


def test_append_creates_missing_parents(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "deep" / "down" / "run.jsonl")
    journal.append(an_entry())

    assert journal.entries() == (an_entry(),)


def test_entries_keep_their_order(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "run.jsonl")
    journal.append(an_entry(node="first"))
    journal.append(an_entry(node="second"))

    assert [entry.node for entry in journal.entries()] == ["first", "second"]


def test_an_absent_file_reads_as_empty(tmp_path: Path) -> None:
    assert Journal(tmp_path / "absent.jsonl").entries() == ()


def test_lookup_finds_an_entry_by_node_and_hash(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "run.jsonl")
    journal.append(an_entry(node="first", input_hash="aaa"))

    found = journal.lookup("first", "aaa")
    assert found is not None
    assert found.delta == {"green": True}


def test_lookup_misses_when_the_hash_changed(tmp_path: Path) -> None:
    """A changed input means the node must run for real, not replay."""
    journal = Journal(tmp_path / "run.jsonl")
    journal.append(an_entry(node="first", input_hash="aaa"))

    assert journal.lookup("first", "bbb") is None


def test_lookup_misses_when_the_node_differs(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "run.jsonl")
    journal.append(an_entry(node="first", input_hash="aaa"))

    assert journal.lookup("second", "aaa") is None


def test_lookup_returns_the_last_entry_for_a_repeated_node(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "run.jsonl")
    journal.append(an_entry(node="check", input_hash="aaa", delta={"attempts": 1}))
    journal.append(an_entry(node="check", input_hash="aaa", delta={"attempts": 2}))

    found = journal.lookup("check", "aaa")
    assert found is not None
    assert found.delta == {"attempts": 2}


def test_a_corrupt_line_is_reported_with_its_number(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    Journal(path).append(an_entry())
    with path.open("a", encoding="utf-8", newline=LF) as handle:
        handle.write("not json\n")

    with pytest.raises(JournalError, match="line 2"):
        Journal(path).entries()


def test_a_line_with_the_wrong_fields_is_reported(tmp_path: Path) -> None:
    """Valid JSON is not yet an entry; a partial record must not read as one."""
    path = tmp_path / "run.jsonl"
    path.write_text('{"node": "first"}\n', encoding="utf-8")

    with pytest.raises(JournalError, match="line 1"):
        Journal(path).entries()


def test_an_entry_with_an_unserializable_delta_is_refused(tmp_path: Path) -> None:
    """A delta the journal cannot express must not reach the file either."""
    path = tmp_path / "run.jsonl"

    with pytest.raises(JournalError, match="object"):
        Journal(path).append(an_entry(delta={"thing": object()}))

    assert not path.exists()


def test_lines_end_with_lf_on_every_platform(tmp_path: Path) -> None:
    """Read as bytes on purpose: text mode would hide a CRLF and pass anyway."""
    journal = Journal(tmp_path / "run.jsonl")
    journal.append(an_entry())

    raw = journal.path.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "run.jsonl")
    journal.append(an_entry())
    journal.path.write_text(journal.path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert len(journal.entries()) == 1


def test_a_line_is_written_with_sorted_fields(tmp_path: Path) -> None:
    """The bytes are the contract: a resume and the golden journal read them."""
    journal = Journal(tmp_path / "run.jsonl")
    journal.append(an_entry())

    line = journal.path.read_text(encoding="utf-8", newline=LF).splitlines()[0]
    assert list(json.loads(line)) == sorted(json.loads(line))
