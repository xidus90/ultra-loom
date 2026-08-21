"""Tests for the immutable flow state."""

from dataclasses import dataclass

import pytest

from ultraloom.state import NotADataclassError, State


@dataclass(frozen=True, slots=True)
class Data:
    green: bool = False
    attempts: int = 0


@dataclass
class MutableData:
    green: bool = False


def test_merged_returns_a_new_state_and_leaves_the_old_one_alone() -> None:
    first = State(Data())
    second = first.merged({"green": True})

    assert second.data == Data(green=True)
    assert first.data == Data(), "merging must not mutate the state it was called on"


def test_merged_keeps_fields_the_delta_does_not_mention() -> None:
    state = State(Data(green=True, attempts=2))

    assert state.merged({"attempts": 3}).data == Data(green=True, attempts=3)


def test_merged_rejects_a_field_the_data_type_does_not_have() -> None:
    with pytest.raises(TypeError):
        State(Data()).merged({"nonexistent": 1})


def test_visits_start_at_zero_and_count_up() -> None:
    state = State(Data())

    assert state.visit_count("run_tests") == 0
    assert state.with_visit("run_tests").visit_count("run_tests") == 1
    assert state.with_visit("run_tests").with_visit("run_tests").visit_count("run_tests") == 2


def test_with_visit_leaves_other_nodes_at_zero() -> None:
    state = State(Data()).with_visit("repair")

    assert state.visit_count("run_tests") == 0


def test_with_visit_returns_a_new_state() -> None:
    first = State(Data())
    second = first.with_visit("repair")

    assert first.visit_count("repair") == 0
    assert second.visit_count("repair") == 1


def test_a_non_dataclass_payload_is_refused_at_construction() -> None:
    with pytest.raises(NotADataclassError):
        # A dict binds T just fine for the type checker; the refusal is a
        # runtime guarantee, which is exactly why it needs a test.
        State({"green": True})


def test_a_mutable_dataclass_payload_is_refused_at_construction() -> None:
    # A payload a node could write into in place would make the journal's
    # record of the input stop describing what the node actually saw.
    with pytest.raises(NotADataclassError):
        State(MutableData())


def test_the_data_class_itself_is_not_a_payload() -> None:
    # The guard inspects the payload's type, so passing the class instead of
    # an instance has to be refused rather than mistaken for a dataclass.
    with pytest.raises(NotADataclassError):
        State(Data)
