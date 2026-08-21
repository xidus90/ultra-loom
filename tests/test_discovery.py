"""Tests for finding a project's flows."""

import sys
from pathlib import Path

import pytest

from ultraloom.discovery import FlowLoadError, FlowNotFoundError, find_flow, list_flows

A_FLOW = '''
"""A minimal flow for tests."""

from dataclasses import dataclass

from ultraloom.graph import END, CodeNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    done: bool = False


flow: Graph[Data] = Graph("smoke", start="mark")
flow.add(CodeNode("mark", lambda _d: {"done": True}))
flow.edge("mark", END)

initial = Data()
'''


def write_flow(root: Path, name: str, body: str = A_FLOW) -> None:
    target = root / ".ultraloom" / "flows" / f"{name}.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_a_flow_is_found_by_file_name(tmp_path: Path) -> None:
    write_flow(tmp_path, "smoke")

    assert find_flow("smoke", tmp_path).graph.name == "smoke"


def test_flows_are_listed_alphabetically(tmp_path: Path) -> None:
    write_flow(tmp_path, "second")
    write_flow(tmp_path, "first")

    assert list_flows(tmp_path) == ("first", "second")


def test_a_package_marker_is_not_a_flow(tmp_path: Path) -> None:
    write_flow(tmp_path, "smoke")
    write_flow(tmp_path, "__init__", "")

    assert list_flows(tmp_path) == ("smoke",)


def test_a_project_without_a_flow_directory_lists_nothing(tmp_path: Path) -> None:
    assert list_flows(tmp_path) == ()


def test_an_absent_flow_names_what_is_available(tmp_path: Path) -> None:
    write_flow(tmp_path, "smoke")

    with pytest.raises(FlowNotFoundError, match="smoke"):
        find_flow("nonexistent", tmp_path)


def test_an_empty_project_offers_no_alternative(tmp_path: Path) -> None:
    with pytest.raises(FlowNotFoundError, match="none"):
        find_flow("nonexistent", tmp_path)


def test_a_module_without_a_flow_attribute_is_refused(tmp_path: Path) -> None:
    write_flow(tmp_path, "empty", "x = 1\n")

    with pytest.raises(FlowLoadError, match="flow"):
        find_flow("empty", tmp_path)


def test_a_flow_attribute_that_is_not_a_graph_is_refused(tmp_path: Path) -> None:
    write_flow(tmp_path, "wrong", "flow = 'not a graph'\n")

    with pytest.raises(FlowLoadError, match="Graph"):
        find_flow("wrong", tmp_path)


def test_a_module_that_raises_on_import_reports_the_file(tmp_path: Path) -> None:
    write_flow(tmp_path, "broken", "raise ValueError('the flow is broken')\n")

    with pytest.raises(FlowLoadError, match=r"broken\.py"):
        find_flow("broken", tmp_path)


def test_two_flows_with_the_same_module_name_do_not_collide(tmp_path: Path) -> None:
    """Flows from different projects must not shadow each other in sys.modules."""
    other = tmp_path / "other"
    other.mkdir()
    write_flow(tmp_path, "smoke")
    write_flow(other, "smoke", A_FLOW.replace('Graph("smoke"', 'Graph("other-smoke"'))

    assert find_flow("smoke", tmp_path).graph.name == "smoke"
    assert find_flow("smoke", other).graph.name == "other-smoke"


def test_a_loaded_flow_leaves_no_module_behind(tmp_path: Path) -> None:
    """A loaded flow must not outlive its call in the interpreter's module table."""
    before = set(sys.modules)
    write_flow(tmp_path, "smoke")

    find_flow("smoke", tmp_path)

    assert set(sys.modules) - before == set()


def test_the_initial_state_comes_back_with_the_graph(tmp_path: Path) -> None:
    write_flow(tmp_path, "smoke")

    loaded = find_flow("smoke", tmp_path)

    assert loaded.initial.__class__.__name__ == "Data"


def test_a_module_without_an_initial_state_is_refused(tmp_path: Path) -> None:
    body = A_FLOW.replace("initial = Data()", "")
    write_flow(tmp_path, "noinit", body)

    with pytest.raises(FlowLoadError, match="initial"):
        find_flow("noinit", tmp_path)
