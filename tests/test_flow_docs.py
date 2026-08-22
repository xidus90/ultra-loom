"""The documentation pages of the bundled flows, checked against the real graphs.

A drawing nobody checks is a lie six months later. These tests hold every
bundled flow's page against the graph its module actually builds, in both
directions: no node or edge may be missing from the page, and the page may draw
nothing the graph does not have.
"""

from __future__ import annotations

import re
from pathlib import Path

from ultraloom.config import Config
from ultraloom.discovery import FlowContext, find_flow, list_flows
from ultraloom.graph import END, Graph

ROOT = Path(__file__).resolve().parents[1]
DOC_DIR = ROOT / "docs" / "abläufe"

# The pages document the graph, not one project's configuration. These values
# only have to be good enough for `build` to assemble a graph at all.
_CONTEXT = FlowContext(root=ROOT, config=Config(root=ROOT, test_paths=("tests/",)))


def _bundled_names() -> tuple[str, ...]:
    return tuple(entry.name for entry in list_flows(ROOT) if entry.origin == "bundled")


def _page_for(name: str) -> Path:
    """The page belonging to a flow module: `verify_until_green` -> `verify-until-green.md`."""
    return DOC_DIR / f"{name.replace('_', '-')}.md"


def _graph_for(name: str) -> Graph[object]:
    return find_flow(name, ROOT, _CONTEXT).graph


def _mermaid_block(page: Path) -> str:
    """The page's mermaid diagram, without its fences."""
    match = re.search(r"```mermaid\n(.*?)```", page.read_text(encoding="utf-8"), re.DOTALL)
    assert match is not None, f"{page} holds no mermaid block"
    return match.group(1)


# One drawn edge: a source identifier, an arrow with an optional `|label|`, a
# target identifier. The lines of a mermaid block are indented, so the source is
# anchored against the stripped line -- anchoring against the raw one would see
# every node only as a target, and an invented node that merely points somewhere
# would walk past the check.
_EDGE = re.compile(r"^([A-Za-z_]\w*)\s*-->\s*(?:\|[^|]*\|\s*)?([A-Za-z_]\w*)")


def _edges_drawn(diagram: str) -> set[tuple[str, str]]:
    """Every edge the diagram draws, as (source, target)."""
    found = (_EDGE.match(line.strip()) for line in diagram.splitlines())
    return {(match.group(1), match.group(2)) for match in found if match is not None}


def _nodes_drawn(diagram: str) -> set[str]:
    """Every identifier the diagram uses as a node, on either end of an arrow."""
    return {name for edge in _edges_drawn(diagram) for name in edge}


def _edge_drawn(diagram: str, source: str, target: str) -> bool:
    """Whether the diagram draws `source --> target`."""
    return (source, target) in _edges_drawn(diagram)


def test_every_bundled_flow_has_a_documentation_page() -> None:
    for name in _bundled_names():
        assert _page_for(name).is_file(), f"{name} has no page under docs/abläufe/"


def test_there_is_at_least_one_bundled_flow_to_check() -> None:
    """Otherwise every test here would pass over an empty loop."""
    assert _bundled_names()


def test_every_page_names_every_node_and_every_edge() -> None:
    for name in _bundled_names():
        graph = _graph_for(name)
        diagram = _mermaid_block(_page_for(name))

        for node in graph.node_names():
            assert node in diagram, f"{name}: node {node!r} is missing from the diagram"
        for source, target in graph.edges():
            drawn = target if target != END else "END"
            assert _edge_drawn(diagram, source, drawn), (
                f"{name}: edge {source} -> {drawn} is missing"
            )


def test_no_page_draws_an_edge_the_graph_does_not_have() -> None:
    """A deleted edge that stayed in the drawing is exactly the drift to catch."""
    for name in _bundled_names():
        graph = _graph_for(name)
        real = {(source, target if target != END else "END") for source, target in graph.edges()}

        for edge in _edges_drawn(_mermaid_block(_page_for(name))):
            assert edge in real, f"{name}: the diagram draws edge {edge[0]} -> {edge[1]}"


def test_no_page_draws_a_node_the_graph_does_not_have() -> None:
    for name in _bundled_names():
        graph = _graph_for(name)
        drawn = _nodes_drawn(_mermaid_block(_page_for(name)))

        assert drawn <= set(graph.node_names()) | {"END", "flowchart", "graph"}, (
            f"{name}: the diagram draws nodes the graph does not have"
        )


def test_a_page_that_lost_an_edge_fails_the_check() -> None:
    """The check has to be able to fail, or it is decoration.

    Indented, like every line inside a real mermaid block: an example without
    the indentation would exercise a shape no page actually has.
    """
    diagram = "    check --> repair\n    repair --> guard\n"

    assert not _edge_drawn(diagram, "guard", "check")


def test_a_page_that_lost_a_node_fails_the_check() -> None:
    """The same, for the node direction of the comparison."""
    diagram = "    check --> repair\n"

    assert "guard" not in _nodes_drawn(diagram)


def test_a_node_drawn_only_as_a_source_is_still_seen() -> None:
    """An invented node points somewhere; it need never be pointed at."""
    diagram = "    bogus --> check\n"

    assert _nodes_drawn(diagram) == {"bogus", "check"}


def test_an_edge_the_graph_does_not_have_is_seen() -> None:
    """The direction that catches a deleted edge left standing in the drawing."""
    diagram = "    check -->|kein Fehler| END\n    guard --> report_red\n"

    assert _edges_drawn(diagram) == {("check", "END"), ("guard", "report_red")}
