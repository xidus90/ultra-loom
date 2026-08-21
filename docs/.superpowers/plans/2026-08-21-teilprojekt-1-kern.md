# ultraloom Teilprojekt 1: Kern — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein Graph-Ausführer mit Zustand, Journal, Freigabepunkten und Wiederaufnahme, dazu eine Prüfkette, die ohne das Claude Agent SDK läuft.

**Architecture:** Drei Knotenarten (`CodeNode`, `AgentNode`, `GateNode`) werden von einem Ausführer über bedingte Kanten abgearbeitet. Jeder Schritt wird als JSONL-Zeile journalisiert; dasselbe Journal ist Protokoll und einzige Quelle der Wiederaufnahme. Der Modellzugang liegt hinter einem Port mit Attrappe, die Prüfkette ist ein eigener Ast ohne Import in den Harness-Teil.

**Tech Stack:** Python ≥ 3.13, `uv`, `hatchling`, `pytest`, `ruff`, `mypy --strict`, `coverage` (Schwelle 100), `claude-agent-sdk` als optionales Extra.

**Spec:** `docs/.superpowers/specs/2026-08-21-ultraloom-kern-design.md`

## Global Constraints

- **Python ≥ 3.13.** `requires-python = ">=3.13"`, `target-version = "py313"` für ruff, `python_version = "3.13"` für mypy. Bewusst nicht 3.14 wie ultra-brain: ultraloom ist ein öffentliches Paket, und die Untergrenze ist seine Nutzbarkeit.
- **Immer `uv`, niemals `pip`.** `uv add`, `uv sync`, `uv run`, `uvx`. Kein `pip install`, keine `requirements.txt`.
- **TDD.** Erst der fehlschlagende Test, dann die Implementierung. Jede Aufgabe endet mit grünen Tests und einem Commit.
- **100 % Coverage, gemessen.** `fail_under = 100`. Jeder Ausschluss braucht `# pragma: no cover  # <Grund>`, niemals nackt.
- **`ruff` und `mypy --strict` laufen sauber durch.** Kein `Any`, kein `# type: ignore` ohne begründenden Kommentar.
- **Sprachen:** Quellcode, Identifier, Code-Kommentare, Commit-Nachrichten, Log- und Fehlermeldungen auf **Englisch**. Dieser Plan und die Spec auf **Deutsch**.
- **Imports stehen oben.** Ein lokaler Import nur mit begründendem Kommentar — im Kern betrifft das genau eine Stelle: das Agent SDK in `model/agent_sdk.py`.
- **Modulgrenze (Spec 15.2):** `checks.py`, `config.py` und der `check`-Zweig von `cli.py` importieren nichts aus `graph.py`, `state.py`, `runner.py`, `journal.py`, `gate.py` oder `model/`. Aufgabe 12 sichert das mit einem Test.
- **Determinismus:** Kein `time.time()`, `datetime.now()` oder `random` im Kern. Uhren und Zufall werden injiziert, damit der Golden-Journal-Test aus Aufgabe 8 echt ist.
- **Kein `flows/`-Inhalt in diesem Teilprojekt.** Das Verzeichnis entsteht leer (nur `__init__.py`); mitgelieferte Abläufe sind Teilprojekt 2.

---

## Dateistruktur

| Datei | Verantwortung |
|---|---|
| `pyproject.toml` | Paket, Extras, Werkzeugkonfiguration |
| `src/ultraloom/state.py` | Unveränderlicher Zustand, Delta-Zusammenführung, Besuchszähler |
| `src/ultraloom/graph.py` | Knotenarten, Kanten, Graphbau, Validierung, Kantenwahl |
| `src/ultraloom/journal.py` | JSONL schreiben und lesen, Eingabe-Hash |
| `src/ultraloom/model/port.py` | Modellschnittstelle und Anfrage-/Antworttypen |
| `src/ultraloom/model/fake.py` | Attrappe mit vorgegebenen Antworten |
| `src/ultraloom/model/agent_sdk.py` | Übersetzung Port → Claude Agent SDK |
| `src/ultraloom/tools.py` | Werkzeugprofile |
| `src/ultraloom/runner.py` | Ausführungsschleife, Ergebnisobjekt |
| `src/ultraloom/gate.py` | Freigabepunkt: Frage stellen, Antwort einsetzen |
| `src/ultraloom/config.py` | `.ultraloom/config.toml` lesen |
| `src/ultraloom/checks.py` | Prüfwerkzeuge auflösen und ausführen |
| `src/ultraloom/discovery.py` | Abläufe im Projekt finden |
| `src/ultraloom/cli.py` | `run`, `show`, `resume`, `replay`, `check` |
| `src/ultraloom/flows/__init__.py` | Leeres Paket für Teilprojekt 2 |

Testdateien spiegeln das eins zu eins: `tests/test_state.py`, `tests/test_graph.py` und so weiter.

---

## Task 1: Gerüst und Zustand

**Files:**
- Create: `pyproject.toml`, `README.md`, `src/ultraloom/__init__.py`, `src/ultraloom/state.py`, `src/ultraloom/flows/__init__.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: nichts
- Produces:
  - `type Delta = Mapping[str, object]`
  - `class State[T]` mit `data: T`, `visits: Mapping[str, int]`
  - `State.merged(delta: Delta) -> State[T]`
  - `State.with_visit(node: str) -> State[T]`
  - `State.visit_count(node: str) -> int`
  - `class NotADataclassError(TypeError)`

- [ ] **Step 1: Projekt anlegen**

```bash
cd /c/Users/micro/Documents/#GIT/ultraloom
mkdir -p src/ultraloom/model src/ultraloom/flows tests
```

Schreibe `pyproject.toml`:

```toml
[project]
name = "ultraloom"
version = "0.1.0"
description = "A check chain for linters and tests, and an optional graph harness for agent flows"
requires-python = ">=3.13"
license = "AGPL-3.0-or-later"
license-files = ["LICENSE"]
dependencies = []

[project.optional-dependencies]
# The harness needs the Claude Agent SDK; the check chain must not.
agent = ["claude-agent-sdk>=0.1"]

[project.scripts]
ultraloom = "ultraloom.cli:main"

[dependency-groups]
dev = [
    "pytest>=8",
    "ruff>=0.6",
    "mypy>=1.11",
    "coverage[toml]>=7",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ultraloom"]

[tool.ruff]
target-version = "py313"
line-length = 100
src = ["src", "tests"]
# Plan documents carry Python fragments that are deliberately not valid
# modules: indented insert pieces and bare comma lists. Formatting them
# destroys the very information they carry.
extend-exclude = ["*.md"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF"]

[tool.mypy]
python_version = "3.13"
strict = true
files = ["src", "tests"]

[tool.pytest.ini_options]
# The contract test talks to the real Claude Agent SDK over the network. It
# stays out of the default run and is asked for explicitly with `-m contract`.
markers = ["contract: runs against the real Claude Agent SDK; excluded from the default run"]
addopts = "-m 'not contract'"

[tool.coverage.run]
branch = true
source = ["src/ultraloom"]

[tool.coverage.report]
fail_under = 100
show_missing = true
```

Schreibe `README.md`:

```markdown
# ultraloom

A check chain that puts one interface in front of ruff, eslint, gdlint, mypy,
tsc, pytest, vitest and coverage — and an optional graph harness for agent
flows.

## The check chain

    uvx ultraloom check lint
    uvx ultraloom check types
    uvx ultraloom check test
    uvx ultraloom check coverage --threshold 100

No installation in your project, no LLM dependency, no API key. The tool for
each check comes from a language preset; the place it runs comes from your
project's `.ultraloom/config.toml`.

## The harness (optional)

    uv add "ultraloom[agent]"

Runs a flow as a graph: nodes are steps, edges are transitions with
conditions. It journals every step, stops at approval points, and resumes an
aborted run from where it stopped.

## Licence

AGPL-3.0-or-later. See `LICENSE`.
```

Leere Paketdateien:

```bash
printf '' > src/ultraloom/__init__.py
printf '' > src/ultraloom/flows/__init__.py
printf '' > src/ultraloom/model/__init__.py
printf '' > tests/__init__.py
uv sync
```

- [ ] **Step 2: Den fehlschlagenden Test schreiben**

`tests/test_state.py`:

```python
"""Tests for the immutable flow state."""

from dataclasses import dataclass

import pytest

from ultraloom.state import NotADataclassError, State


@dataclass(frozen=True, slots=True)
class Data:
    green: bool = False
    attempts: int = 0


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
        State({"green": True})  # type: ignore[type-var]  # the refusal is what we test
```

- [ ] **Step 3: Test laufen lassen und Fehlschlag bestätigen**

Run: `uv run pytest tests/test_state.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.state'`

- [ ] **Step 4: Minimale Implementierung**

`src/ultraloom/state.py`:

```python
"""The immutable state that travels through a flow."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

type Delta = Mapping[str, object]


class NotADataclassError(TypeError):
    """Raised when a flow's payload is not a frozen dataclass."""


@dataclass(frozen=True, slots=True)
class State[T]:
    """A flow's payload plus how often each node has run.

    Nodes never write into a state; they return a delta and the runner builds
    the next state from it. Without that rule a resume could not reconstruct
    the state a node saw before it ran.
    """

    data: T
    visits: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # T cannot be bound to "is a dataclass" in the type system, so the
        # guarantee `merged` relies on is checked once, here, at the door.
        if not dataclasses.is_dataclass(self.data) or isinstance(self.data, type):
            raise NotADataclassError(
                f"a flow's payload must be a frozen dataclass instance, got {type(self.data).__name__}"
            )

    def merged(self, delta: Delta) -> State[T]:
        """Return a new state with the delta's fields replaced."""
        # dataclasses.replace needs a dataclass instance. __post_init__ has
        # already established that, which the type system cannot express.
        payload = cast(object, self.data)
        return State(cast(T, dataclasses.replace(payload, **delta)), self.visits)  # type: ignore[type-var]  # payload is a dataclass, checked in __post_init__

    def with_visit(self, node: str) -> State[T]:
        """Return a new state with one more recorded visit to `node`."""
        return State(self.data, {**self.visits, node: self.visit_count(node) + 1})

    def visit_count(self, node: str) -> int:
        """How often `node` has run in this state's history."""
        return self.visits.get(node, 0)
```

- [ ] **Step 5: Tests, Linter und Typen laufen lassen**

```bash
uv run pytest tests/test_state.py -v
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Expected: alle Tests PASS, ruff und mypy ohne Befund.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml README.md uv.lock src/ultraloom tests
git commit -m "Carry a flow's payload in a state that nodes cannot write into"
```

---

## Task 2: Knotenarten, Graph und Validierung

**Files:**
- Create: `src/ultraloom/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: `Delta` aus `state.py`
- Produces:
  - `END: str` (Wert `"__end__"`)
  - `type Effort = Literal["low", "medium", "high", "xhigh", "max"]`
  - `class CodeNode[T]` mit `name`, `run: Callable[[T], Delta]`, `max_visits: int = 1`
  - `class AgentNode[T]` mit `name`, `prompt: Callable[[T], str]`, `schema: type`, `tools: str = "read_only"`, `effort: Effort = "high"`, `max_visits: int = 1`
  - `class GateNode[T]` mit `name`, `question: Callable[[T], str]`, `apply: Callable[[T, str], Delta]`, `max_visits: int = 1`
  - `type Node[T] = CodeNode[T] | AgentNode[T] | GateNode[T]`
  - `node_kind(node: Node[T]) -> str` → `"code"` | `"agent"` | `"gate"`
  - `class GraphError(ValueError)`
  - `class Graph[T]` mit `__init__(name: str, start: str)`, `add(node)`, `edge(src, dst, when=None)`, `validate()`, `node(name) -> Node[T]`, `next_name(current, data) -> str`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`tests/test_graph.py`:

```python
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
    node = AgentNode("review", lambda _d: "ask", schema=Data)

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
```

- [ ] **Step 2: Test laufen lassen und Fehlschlag bestätigen**

Run: `uv run pytest tests/test_graph.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.graph'`

- [ ] **Step 3: Minimale Implementierung**

`src/ultraloom/graph.py`:

```python
"""Node types, edges, and the validation that runs before the first node."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

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


def node_kind(node: Node[T]) -> str:
    """The node's sort, as written into the journal."""
    match node:
        case CodeNode():
            return "code"
        case AgentNode():
            return "agent"
        case GateNode():
            return "gate"


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
```

- [ ] **Step 4: Tests, Linter und Typen laufen lassen**

```bash
uv run pytest tests/test_graph.py -v
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Expected: alle Tests PASS.

- [ ] **Step 5: Coverage der beiden Module prüfen**

```bash
uv run coverage run -m pytest tests/test_state.py tests/test_graph.py
uv run coverage report --include="src/ultraloom/state.py,src/ultraloom/graph.py"
```

Expected: 100 % für beide Dateien. Fehlt eine Zeile, fehlt ein Test — schreibe ihn, statt die Schwelle zu senken.

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/graph.py tests/test_graph.py
git commit -m "Refuse a graph that cannot run before its first node runs"
```

---

## Task 3: Journal

**Files:**
- Create: `src/ultraloom/journal.py`
- Test: `tests/test_journal.py`

**Interfaces:**
- Consumes: nichts aus früheren Aufgaben
- Produces:
  - `class Entry` (frozen) mit `node: str`, `kind: str`, `input_hash: str`, `delta: Mapping[str, object]`, `outcome: str`, `tools: str | None`, `effort: str | None`, `tokens: int`, `seconds: float`, `detail: str | None`
  - `input_hash(node: str, data: object) -> str`
  - `class Journal` mit `__init__(path: Path)`, `append(entry: Entry) -> None`, `entries() -> tuple[Entry, ...]`, `lookup(node: str, input_hash: str) -> Entry | None`
  - `class JournalError(ValueError)`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`tests/test_journal.py`:

```python
"""Tests for the run journal: the log and the only source of a resume."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from ultraloom.journal import Entry, Journal, JournalError, input_hash


@dataclass(frozen=True, slots=True)
class Data:
    green: bool = False
    attempts: int = 0


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


def test_the_same_data_hashes_the_same_way(tmp_path: Path) -> None:
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


def test_an_appended_entry_reads_back(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "run.jsonl")
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


def test_lookup_returns_the_last_entry_for_a_repeated_node(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "run.jsonl")
    journal.append(an_entry(node="check", input_hash="aaa", delta={"attempts": 1}))
    journal.append(an_entry(node="check", input_hash="aaa", delta={"attempts": 2}))

    found = journal.lookup("check", "aaa")
    assert found is not None
    assert found.delta == {"attempts": 2}


def test_a_corrupt_line_is_reported_with_its_number(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    path.write_text('{"node": "first"}\nnot json\n', encoding="utf-8")

    with pytest.raises(JournalError, match="line 2"):
        Journal(path).entries()


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "run.jsonl")
    journal.append(an_entry())
    journal.path.write_text(journal.path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert len(journal.entries()) == 1
```

- [ ] **Step 2: Test laufen lassen und Fehlschlag bestätigen**

Run: `uv run pytest tests/test_journal.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.journal'`

- [ ] **Step 3: Minimale Implementierung**

`src/ultraloom/journal.py`:

```python
"""The run journal: one JSONL line per node.

Deliberately one thing instead of two — the same file is the log you read to
evaluate a run and the only source a resume reads from.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class JournalError(ValueError):
    """Raised for a journal file that cannot be read."""


@dataclass(frozen=True, slots=True)
class Entry:
    """What one node did."""

    node: str
    kind: str
    input_hash: str
    delta: Mapping[str, object]
    outcome: str
    tools: str | None
    effort: str | None
    tokens: int
    seconds: float
    detail: str | None


def input_hash(node: str, data: object) -> str:
    """A stable fingerprint of the input a node saw.

    Keys are sorted, so a hash never depends on field ordering — a resume that
    turned on dict order would replay the wrong node without saying so.
    """
    payload = dataclasses.asdict(data) if dataclasses.is_dataclass(data) and not isinstance(data, type) else data
    blob = json.dumps({"node": node, "data": payload}, sort_keys=True, default=repr)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Journal:
    """Append-only JSONL, read back whole."""

    path: Path

    def append(self, entry: Entry) -> None:
        """Add one line. Creates the file and its parents on first write."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(dataclasses.asdict(entry), sort_keys=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def entries(self) -> tuple[Entry, ...]:
        """Every line, in order. An absent file reads as empty."""
        if not self.path.exists():
            return ()
        found: list[Entry] = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                found.append(Entry(**json.loads(line)))
            except (json.JSONDecodeError, TypeError) as error:
                raise JournalError(f"{self.path}: line {number} is not a journal entry") from error
        return tuple(found)

    def lookup(self, node: str, node_input_hash: str) -> Entry | None:
        """The most recent entry for this node and this input, if any."""
        for entry in reversed(self.entries()):
            if entry.node == node and entry.input_hash == node_input_hash:
                return entry
        return None
```

- [ ] **Step 4: Tests, Linter und Typen laufen lassen**

```bash
uv run pytest tests/test_journal.py -v
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/journal.py tests/test_journal.py
git commit -m "Journal every node so a run can be read back and resumed"
```

---

## Task 4: Modell-Port und Attrappe

**Files:**
- Create: `src/ultraloom/model/port.py`, `src/ultraloom/model/fake.py`
- Test: `tests/test_model_fake.py`

**Interfaces:**
- Consumes: `Effort` aus `graph.py`
- Produces:
  - `class Request` (frozen) mit `prompt: str`, `tools: tuple[str, ...]`, `effort: str`, `schema: type`
  - `class Reply` (frozen) mit `value: object`, `tokens: int`
  - `class Model(Protocol)` mit `ask(request: Request) -> Reply`
  - `class ModelError(RuntimeError)`
  - `class FakeModel` mit `__init__(replies: Sequence[Reply | ModelError])`, `ask(...)`, `seen: tuple[Request, ...]`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`tests/test_model_fake.py`:

```python
"""Tests for the model port's stand-in."""

from dataclasses import dataclass

import pytest

from ultraloom.model.fake import FakeModel
from ultraloom.model.port import ModelError, Reply, Request


@dataclass(frozen=True, slots=True)
class Answer:
    ok: bool = True


def a_request(prompt: str = "ask") -> Request:
    return Request(prompt=prompt, tools=("Read",), effort="low", schema=Answer)


def test_replies_come_back_in_the_order_they_were_given() -> None:
    model = FakeModel([Reply(Answer(ok=True), tokens=7), Reply(Answer(ok=False), tokens=9)])

    assert model.ask(a_request()).value == Answer(ok=True)
    assert model.ask(a_request()).value == Answer(ok=False)


def test_the_fake_records_what_it_was_asked() -> None:
    model = FakeModel([Reply(Answer(), tokens=1)])
    model.ask(a_request("check the report"))

    assert [request.prompt for request in model.seen] == ["check the report"]
    assert model.seen[0].tools == ("Read",)


def test_a_queued_error_is_raised_instead_of_returned() -> None:
    model = FakeModel([ModelError("the model is unreachable")])

    with pytest.raises(ModelError, match="unreachable"):
        model.ask(a_request())


def test_running_out_of_replies_is_an_error_not_a_silent_none() -> None:
    model = FakeModel([])

    with pytest.raises(ModelError, match="no reply left"):
        model.ask(a_request())
```

- [ ] **Step 2: Test laufen lassen und Fehlschlag bestätigen**

Run: `uv run pytest tests/test_model_fake.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.model.fake'`

- [ ] **Step 3: Minimale Implementierung**

`src/ultraloom/model/port.py`:

```python
"""The model interface every AgentNode goes through.

Keeping the model behind a port is what makes the whole core testable without
the network — and it leaves the door open for a node to reach the model a
different way than its neighbours do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ModelError(RuntimeError):
    """Raised when a model cannot answer: unreachable, refused, schema broken."""


@dataclass(frozen=True, slots=True)
class Request:
    """One model call, fully described."""

    prompt: str
    tools: tuple[str, ...]
    effort: str
    schema: type


@dataclass(frozen=True, slots=True)
class Reply:
    """A schema-validated answer and what it cost."""

    value: object
    tokens: int


class Model(Protocol):
    """What the runner needs from a model."""

    def ask(self, request: Request) -> Reply:
        """Answer one request, or raise ModelError."""
        ...
```

`src/ultraloom/model/fake.py`:

```python
"""A model that answers from a queue, for tests."""

from __future__ import annotations

from collections.abc import Sequence

from ultraloom.model.port import ModelError, Reply, Request


class FakeModel:
    """Hands out prepared replies and records what it was asked.

    A queued ModelError is raised rather than returned, so error paths are as
    testable as happy ones.
    """

    def __init__(self, replies: Sequence[Reply | ModelError]) -> None:
        self._pending = list(replies)
        self._seen: list[Request] = []

    @property
    def seen(self) -> tuple[Request, ...]:
        """Every request this model was handed, in order."""
        return tuple(self._seen)

    def ask(self, request: Request) -> Reply:
        """Return the next prepared reply."""
        self._seen.append(request)
        if not self._pending:
            raise ModelError(f"no reply left for {request.prompt!r}")
        nxt = self._pending.pop(0)
        if isinstance(nxt, ModelError):
            raise nxt
        return nxt
```

- [ ] **Step 4: Tests, Linter und Typen laufen lassen**

```bash
uv run pytest tests/test_model_fake.py -v
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/model tests/test_model_fake.py
git commit -m "Put the model behind a port so the core is testable without a network"
```

---

## Task 5: Werkzeugprofile

**Files:**
- Create: `src/ultraloom/tools.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: nichts
- Produces:
  - `PROFILES: Mapping[str, tuple[str, ...]]`
  - `resolve_tools(profile: str, mcp_servers: Sequence[str] = ()) -> tuple[str, ...]`
  - `class UnknownProfileError(ValueError)`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`tests/test_tools.py`:

```python
"""Tests for the tool profiles that bound what an AgentNode can touch."""

import pytest

from ultraloom.tools import PROFILES, UnknownProfileError, resolve_tools


def test_the_default_profile_cannot_write() -> None:
    """A node that only reads must be unable to write, not merely willing."""
    assert resolve_tools("read_only") == ("Glob", "Grep", "Read")
    assert "Edit" not in resolve_tools("read_only")
    assert "Write" not in resolve_tools("read_only")
    assert "Bash" not in resolve_tools("read_only")


def test_the_edit_profile_adds_writing_to_reading() -> None:
    assert resolve_tools("edit") == ("Edit", "Glob", "Grep", "Read", "Write")


def test_the_shell_profile_adds_bash_but_not_writing() -> None:
    tools = resolve_tools("shell")

    assert "Bash" in tools
    assert "Edit" not in tools, "a shell profile must not smuggle in an edit tool"


def test_the_mcp_profile_adds_the_configured_servers() -> None:
    assert resolve_tools("mcp", ["ultra-brain"]) == ("Glob", "Grep", "Read", "mcp__ultra-brain")


def test_the_mcp_profile_without_servers_is_just_reading() -> None:
    assert resolve_tools("mcp") == ("Glob", "Grep", "Read")


def test_servers_are_ignored_by_profiles_that_do_not_ask_for_them() -> None:
    assert resolve_tools("read_only", ["ultra-brain"]) == ("Glob", "Grep", "Read")


def test_an_unknown_profile_is_refused_with_the_known_ones_named() -> None:
    with pytest.raises(UnknownProfileError, match="read_only"):
        resolve_tools("everything")


def test_every_profile_is_sorted_and_free_of_duplicates() -> None:
    """The tool list feeds a prompt cache prefix; unstable order would break it."""
    for name, tools in PROFILES.items():
        assert list(tools) == sorted(set(tools)), f"profile {name} is unsorted or repeats a tool"
```

- [ ] **Step 2: Test laufen lassen und Fehlschlag bestätigen**

Run: `uv run pytest tests/test_tools.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.tools'`

- [ ] **Step 3: Minimale Implementierung**

`src/ultraloom/tools.py`:

```python
"""Tool profiles: the ceiling on what an AgentNode can reach.

Reading is the default. Writing and shell access have to be asked for, so a
node that should only interpret a report cannot touch a source file — because
the tool is absent, not because the node is well behaved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

_READ = ("Glob", "Grep", "Read")

PROFILES: Mapping[str, tuple[str, ...]] = {
    "read_only": _READ,
    "edit": tuple(sorted({*_READ, "Edit", "Write"})),
    "shell": tuple(sorted({*_READ, "Bash"})),
    "mcp": _READ,
}

_TAKES_SERVERS = frozenset({"mcp"})


class UnknownProfileError(ValueError):
    """Raised for a profile name that is not defined."""


def resolve_tools(profile: str, mcp_servers: Sequence[str] = ()) -> tuple[str, ...]:
    """The tools a node with this profile may use."""
    try:
        base = PROFILES[profile]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        raise UnknownProfileError(f"unknown tool profile {profile!r}; known: {known}") from None
    if profile not in _TAKES_SERVERS:
        return base
    return tuple(sorted({*base, *(f"mcp__{server}" for server in mcp_servers)}))
```

- [ ] **Step 4: Tests, Linter und Typen laufen lassen**

```bash
uv run pytest tests/test_tools.py -v
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/tools.py tests/test_tools.py
git commit -m "Bound what a node can touch by the tools it is given"
```

---
## Task 6: Ausführer für Code- und Agent-Knoten

**Files:**
- Create: `src/ultraloom/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `State`, `Delta`; `Graph`, `END`, `node_kind`, `CodeNode`, `AgentNode`, `GateNode`, `GraphError`; `Journal`, `Entry`, `input_hash`; `Model`, `Request`, `ModelError`; `resolve_tools`
- Produces:
  - `type Clock = Callable[[], float]`
  - `class Result[T]` (frozen) mit `status: str` (`"done"` | `"paused"` | `"error"`), `state: State[T]`, `node: str | None`, `question: str | None`, `detail: str | None`
  - `class VisitLimitError(RuntimeError)`
  - `class Runner[T]` mit `__init__(graph, journal, model=None, clock=None, mcp_servers=())`, `run(data: T) -> Result[T]`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`tests/test_runner.py`:

```python
"""Tests for the execution loop over code and agent nodes."""

from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path

import pytest

from ultraloom.graph import END, AgentNode, CodeNode, Graph
from ultraloom.journal import Journal
from ultraloom.model.fake import FakeModel
from ultraloom.model.port import ModelError, Reply
from ultraloom.runner import Result, Runner, VisitLimitError


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


def test_the_graph_is_validated_before_the_first_node_runs(tmp_path: Path) -> None:
    ran: list[str] = []
    graph: Graph[Data] = Graph("bad", start="first")
    graph.add(CodeNode("first", lambda _d: ran.append("first") or {}))
    graph.edge("first", "nowhere")

    result = Runner(graph, a_journal(tmp_path), clock=ticking_clock()).run(Data())

    assert result.status == "error"
    assert ran == [], "validation must run before any node does"


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

    Runner(graph, journal, model=FakeModel([Reply(Verdict(), tokens=42)]), clock=ticking_clock()).run(
        Data()
    )

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
    assert "no model" in result.detail


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

    Runner(
        graph, journal, model=FakeModel([ModelError("unreachable")]), clock=ticking_clock()
    ).run(Data())

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
    graph.edge("try", "fallback", on_error=True)
    graph.edge("fallback", END)

    result = Runner(graph, a_journal(tmp_path), clock=ticking_clock()).run(Data())

    assert result.status == "done"
    assert result.state.data.note == "took the fallback"


def test_visit_limit_error_carries_the_node_name() -> None:
    assert "check" in str(VisitLimitError("node 'check' exceeded max_visits"))


def test_result_is_immutable() -> None:
    from ultraloom.state import State

    result = Result("done", State(Data()), None, None, None)
    with pytest.raises(AttributeError):
        result.status = "error"  # type: ignore[misc]  # immutability is the point
```

- [ ] **Step 2: Test laufen lassen und Fehlschlag bestätigen**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL — `ultraloom.runner` fehlt, und `AgentNode` kennt noch kein `apply`, `Graph.edge` kein `on_error`.

- [ ] **Step 3: `AgentNode` um `apply` und `Graph.edge` um `on_error` erweitern**

In `src/ultraloom/graph.py`: `AgentNode` bekommt das Feld, das die Antwort in ein Delta übersetzt. Ohne es müsste der Ausführer raten, welches Feld welchen Zustandsteil trifft.

```python
@dataclass(frozen=True, slots=True)
class AgentNode[T]:
    """A model call with its own prompt, tool profile, effort and output schema."""

    name: str
    prompt: Callable[[T], str]
    schema: type
    # The reply is typed only by `schema`, which the type system cannot tie to
    # this callable's parameter; the flow narrows it where it knows the type.
    apply: Callable[[T, object], Delta] = lambda _data, _reply: {}
    tools: str = "read_only"
    effort: Effort = "high"
    max_visits: int = 1
```

`_Edge` und `edge()` bekommen die Fehlerkante:

```python
@dataclass(frozen=True, slots=True)
class _Edge[T]:
    dst: str
    when: Callable[[T], bool] | None
    on_error: bool = False
```

```python
    def edge(
        self,
        src: str,
        dst: str,
        when: Callable[[T], bool] | None = None,
        on_error: bool = False,
    ) -> None:
        """Join two nodes. Without a condition the edge always holds.

        An on_error edge is taken only when the source node raised; it is
        invisible to the normal path, so a fallback is a visible edge in the
        flow rather than hidden retry logic in the runner.
        """
        self._edges.setdefault(src, []).append(_Edge(dst, when, on_error))
```

`next_name` überspringt Fehlerkanten, und eine neue Methode findet sie:

```python
    def next_name(self, current: str, data: T) -> str:
        """The name of the node after `current`, or END."""
        for candidate in self._edges.get(current, []):
            if candidate.on_error:
                continue
            if candidate.when is None or candidate.when(data):
                return candidate.dst
        raise GraphError(f"no edge out of {current!r} applies to the current state")

    def error_name(self, current: str) -> str | None:
        """Where to go when `current` raised, or None to end the run."""
        for candidate in self._edges.get(current, []):
            if candidate.on_error:
                return candidate.dst
        return None
```

In `validate` darf ein Knoten mit ausschließlich einer Fehlerkante nicht als „hat eine Kante" gelten — sonst könnte ein Knoten ohne normalen Ausgang durchrutschen:

```python
        for name in self._nodes:
            if not [edge for edge in self._edges.get(name, []) if not edge.on_error]:
                raise GraphError(f"node {name!r} has no outgoing edge")
```

Ergänze in `tests/test_graph.py` zwei Tests für die neuen Zusagen:

```python
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
    graph.edge("first", END)
    graph.edge("first", "fallback", on_error=True)
    graph.edge("fallback", END)

    assert graph.next_name("first", Data()) == END
    assert graph.error_name("first") == "fallback"
    assert graph.error_name("fallback") is None


def test_an_agent_node_defaults_to_a_delta_free_apply() -> None:
    node = AgentNode("review", lambda _d: "ask", schema=Data)

    assert node.apply(Data(), object()) == {}
```

- [ ] **Step 4: Ausführer implementieren**

`src/ultraloom/runner.py`:

```python
"""The execution loop: pick the next node, run it, journal it, carry on."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ultraloom.graph import END, AgentNode, CodeNode, GateNode, Graph, GraphError, Node, node_kind
from ultraloom.journal import Entry, Journal, input_hash
from ultraloom.model.port import Model, ModelError, Request
from ultraloom.state import Delta, State
from ultraloom.tools import UnknownProfileError, resolve_tools

type Clock = Callable[[], float]


class VisitLimitError(RuntimeError):
    """Raised when a node ran more often than its max_visits allows."""


@dataclass(frozen=True, slots=True)
class Result[T]:
    """How a run ended, and where."""

    status: str
    state: State[T]
    node: str | None
    question: str | None
    detail: str | None


class Runner[T]:
    """Walks a graph, journalling every step."""

    def __init__(
        self,
        graph: Graph[T],
        journal: Journal,
        model: Model | None = None,
        clock: Clock | None = None,
        mcp_servers: Sequence[str] = (),
    ) -> None:
        self._graph = graph
        self._journal = journal
        self._model = model
        # An injected clock keeps durations deterministic, which is what makes
        # the golden-journal test in task 8 a real test.
        self._clock = clock if clock is not None else _monotonic
        self._mcp_servers = tuple(mcp_servers)

    def run(self, data: T) -> Result[T]:
        """Run the flow from its start node."""
        try:
            self._graph.validate()
        except GraphError as error:
            return Result("error", State(data), None, None, str(error))
        return self._walk(State(data), self._graph.start)

    def _walk(self, state: State[T], name: str) -> Result[T]:
        while name != END:
            node = self._graph.node(name)
            state = state.with_visit(name)
            if state.visit_count(name) > node.max_visits:
                detail = f"node {name!r} exceeded max_visits={node.max_visits}"
                self._write(node, state, {}, "error", 0, 0.0, detail)
                return Result("error", state, name, None, detail)

            outcome = self._step(node, state)
            if outcome.paused:
                return Result("paused", outcome.state, name, outcome.question, None)
            if outcome.failed:
                fallback = self._graph.error_name(name)
                if fallback is None:
                    return Result("error", outcome.state, name, None, outcome.detail)
                state, name = outcome.state, fallback
                continue

            state = outcome.state
            try:
                name = self._graph.next_name(name, state.data)
            except GraphError as error:
                return Result("error", state, name, None, str(error))
        return Result("done", state, None, None, None)

    def _step(self, node: Node[T], state: State[T]) -> _Step[T]:
        started = self._clock()
        try:
            delta, tokens = self._invoke(node, state)
        # A node runs arbitrary project code, so anything may come out of it.
        # A crash here would lose the journal entry that explains the failure.
        except Exception as error:  # noqa: BLE001  # turned into an error outcome, never swallowed
            seconds = self._clock() - started
            self._write(node, state, {}, "error", 0, seconds, str(error))
            return _Step(state, failed=True, detail=str(error))

        seconds = self._clock() - started
        if isinstance(node, GateNode):
            question = node.question(state.data)
            self._write(node, state, {}, "paused", 0, seconds, question)
            return _Step(state, paused=True, question=question)

        self._write(node, state, delta, "ok", tokens, seconds, None)
        return _Step(state.merged(delta))

    def _invoke(self, node: Node[T], state: State[T]) -> tuple[Delta, int]:
        match node:
            case CodeNode():
                return node.run(state.data), 0
            case AgentNode():
                if self._model is None:
                    raise RuntimeError(f"node {node.name!r} needs a model but no model was given")
                reply = self._model.ask(
                    Request(
                        prompt=node.prompt(state.data),
                        tools=resolve_tools(node.tools, self._mcp_servers),
                        effort=node.effort,
                        schema=node.schema,
                    )
                )
                return node.apply(state.data, reply.value), reply.tokens
            case GateNode():
                return {}, 0

    def _write(
        self,
        node: Node[T],
        state: State[T],
        delta: Delta,
        outcome: str,
        tokens: int,
        seconds: float,
        detail: str | None,
    ) -> None:
        agent = node if isinstance(node, AgentNode) else None
        self._journal.append(
            Entry(
                node=node.name,
                kind=node_kind(node),
                input_hash=input_hash(node.name, state.data),
                delta=dict(delta),
                outcome=outcome,
                tools=agent.tools if agent else None,
                effort=agent.effort if agent else None,
                tokens=tokens,
                seconds=seconds,
                detail=detail,
            )
        )


@dataclass(frozen=True, slots=True)
class _Step[T]:
    state: State[T]
    paused: bool = False
    failed: bool = False
    question: str | None = None
    detail: str | None = None


def _monotonic() -> float:  # pragma: no cover  # the default clock; tests inject their own
    import time

    return time.monotonic()
```

- [ ] **Step 5: Tests, Linter und Typen laufen lassen**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Expected: alle Tests PASS, auch die beiden neuen in `test_graph.py`.

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/graph.py src/ultraloom/runner.py tests/test_graph.py tests/test_runner.py
git commit -m "Walk a graph and journal every step, with fallbacks as visible edges"
```

---

## Task 7: Freigabepunkte

**Files:**
- Create: `src/ultraloom/gate.py`
- Modify: `src/ultraloom/runner.py` (Methode `resume` ergänzen)
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes: `GateNode`, `Graph`, `Journal`, `Runner`, `State`
- Produces:
  - `class PendingGate` (frozen) mit `node: str`, `question: str`
  - `pending_gate(journal: Journal) -> PendingGate | None`
  - `Runner.resume(data: T, answer: str | None = None) -> Result[T]`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`tests/test_gate.py`:

```python
"""Tests for approval points: stopping, and carrying on with an answer."""

from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path

from ultraloom.gate import pending_gate
from ultraloom.graph import END, CodeNode, GateNode, Graph
from ultraloom.journal import Journal
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


def test_a_gate_pauses_the_run_and_puts_its_question(tmp_path: Path) -> None:
    result = Runner(approval_flow(), Journal(tmp_path / "r.jsonl"), clock=ticking_clock()).run(Data())

    assert result.status == "paused"
    assert result.node == "ask"
    assert result.question == "May I write the wiki entry?"


def test_the_node_after_the_gate_did_not_run(tmp_path: Path) -> None:
    result = Runner(approval_flow(), Journal(tmp_path / "r.jsonl"), clock=ticking_clock()).run(Data())

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


def test_resume_applies_the_answer_and_finishes_the_run(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    graph = approval_flow()
    Runner(graph, journal, clock=ticking_clock()).run(Data())

    result = Runner(graph, journal, clock=ticking_clock()).resume(Data(), answer="yes")

    assert result.status == "done"
    assert result.state.data.note == "wrote it: yes"


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
```

- [ ] **Step 2: Test laufen lassen und Fehlschlag bestätigen**

Run: `uv run pytest tests/test_gate.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.gate'`

- [ ] **Step 3: Implementieren**

`src/ultraloom/gate.py`:

```python
"""Approval points, read back from the journal.

A paused run has an address: the journal's last entry names the gate and the
question it asked, so `resume` needs nothing but the journal.
"""

from __future__ import annotations

from dataclasses import dataclass

from ultraloom.journal import Journal


@dataclass(frozen=True, slots=True)
class PendingGate:
    """A gate that stopped a run and is waiting for an answer."""

    node: str
    question: str


def pending_gate(journal: Journal) -> PendingGate | None:
    """The open question of this run, or None if nothing is waiting."""
    entries = journal.entries()
    if not entries:
        return None
    last = entries[-1]
    if last.outcome != "paused" or last.detail is None:
        return None
    return PendingGate(last.node, last.detail)
```

In `src/ultraloom/runner.py` die Wiederaufnahme nach einem Gate ergänzen — Import oben, Methode nach `run`:

```python
from ultraloom.gate import pending_gate
```

```python
    def resume(self, data: T, answer: str | None = None) -> Result[T]:
        """Carry a paused run onward, applying the answer to its open gate.

        Without an answer the gate pauses again: treating a missing answer as
        consent would make the approval point decorative.
        """
        try:
            self._graph.validate()
        except GraphError as error:
            return Result("error", State(data), None, None, str(error))

        gate = pending_gate(self._journal)
        if gate is None or answer is None:
            return self._walk(State(data), self._graph.start)

        node = self._graph.node(gate.node)
        if not isinstance(node, GateNode):
            return Result("error", State(data), gate.node, None, f"{gate.node!r} is not a gate")

        state = State(data).merged(node.apply(data, answer))
        self._write(node, state, {}, "ok", 0, 0.0, f"answered: {answer}")
        try:
            name = self._graph.next_name(gate.node, state.data)
        except GraphError as error:
            return Result("error", state, gate.node, None, str(error))
        return self._walk(state, name)
```

- [ ] **Step 4: Tests, Linter und Typen laufen lassen**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/gate.py src/ultraloom/runner.py tests/test_gate.py
git commit -m "Stop at an approval point and carry on only with an answer"
```

---

## Task 8: Wiederaufnahme, Wiedergabe und der Golden-Journal-Test

**Files:**
- Modify: `src/ultraloom/runner.py`
- Test: `tests/test_resume.py`

**Interfaces:**
- Consumes: alles aus Aufgaben 1–7
- Produces:
  - `Runner.__init__(..., replay: bool = False)`
  - `class ReplayGapError(RuntimeError)`
  - Verhalten: ein Knoten, dessen `input_hash` im Journal mit Ausgang `"ok"` steht, liefert sein Delta aus dem Journal statt zu laufen

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`tests/test_resume.py`:

```python
"""Tests for resume from the journal, replay without a model, and reproducibility."""

from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path

import pytest

from ultraloom.graph import END, AgentNode, CodeNode, Graph
from ultraloom.journal import Journal
from ultraloom.model.fake import FakeModel
from ultraloom.model.port import Reply
from ultraloom.runner import ReplayGapError, Runner


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


def test_a_second_run_over_the_same_journal_executes_nothing(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    log: list[str] = []
    Runner(counting_flow(log), journal, clock=ticking_clock()).run(Data())
    assert log == ["first", "second"]

    log.clear()
    result = Runner(counting_flow(log), journal, clock=ticking_clock()).run(Data())

    assert log == [], "unchanged inputs must come from the journal, not from a rerun"
    assert result.state.data.steps == "12"


def test_a_truncated_journal_reruns_only_what_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    journal = Journal(path)
    log: list[str] = []
    Runner(counting_flow(log), journal, clock=ticking_clock()).run(Data())

    kept = path.read_text(encoding="utf-8").splitlines()[:1]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    log.clear()
    result = Runner(counting_flow(log), journal, clock=ticking_clock()).run(Data())

    assert log == ["second"], "the first node is cached, the second is not"
    assert result.state.data.steps == "12", "a resumed run must reach the same state"


def test_a_changed_node_reruns_and_so_does_everything_after_it(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
    log: list[str] = []
    Runner(counting_flow(log), journal, clock=ticking_clock()).run(Data())

    changed: list[str] = []

    def first(data: Data) -> dict[str, object]:
        changed.append("first")
        return {"steps": data.steps + "X"}

    graph: Graph[Data] = Graph("counting", start="first")
    graph.add(CodeNode("first", first))
    graph.add(CodeNode("second", lambda d: changed.append("second") or {"steps": d.steps + "2"}))
    graph.edge("first", "second")
    graph.edge("second", END)

    result = Runner(graph, journal, clock=ticking_clock()).run(Data())

    assert changed == ["first", "second"]
    assert result.state.data.steps == "X2"


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

    second = Runner(graph, journal, clock=ticking_clock()).run(Data())
    assert second.status == "done"
    assert second.state.data.steps == "recovered"


def test_an_agent_node_is_replayed_without_asking_the_model(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "r.jsonl")
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

    Runner(
        graph, journal, model=FakeModel([Reply(Verdict(fix="patched"), tokens=5)]), clock=ticking_clock()
    ).run(Data())

    empty = FakeModel([])
    result = Runner(graph, journal, model=empty, clock=ticking_clock()).run(Data())

    assert empty.seen == (), "a replayed agent node must cost nothing"
    assert result.state.data.steps == "patched"


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


def test_the_same_flow_and_the_same_fake_produce_the_same_journal(tmp_path: Path) -> None:
    """The golden-journal test: reproducibility is measured, not assumed."""

    def one_run(name: str) -> str:
        path = tmp_path / f"{name}.jsonl"
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
        Runner(
            graph,
            Journal(path),
            model=FakeModel([Reply(Verdict(fix="patched"), tokens=5)]),
            clock=ticking_clock(),
        ).run(Data())
        return path.read_text(encoding="utf-8")

    assert one_run("a") == one_run("b")


def test_replay_gap_error_names_the_node() -> None:
    assert "second" in str(ReplayGapError("node 'second' is not in the journal"))
```

- [ ] **Step 2: Test laufen lassen und Fehlschlag bestätigen**

Run: `uv run pytest tests/test_resume.py -v`
Expected: FAIL mit `ImportError: cannot import name 'ReplayGapError'`

- [ ] **Step 3: Implementieren**

In `src/ultraloom/runner.py`:

```python
class ReplayGapError(RuntimeError):
    """Raised in replay mode for a node the journal does not cover."""
```

`__init__` bekommt den Schalter:

```python
        replay: bool = False,
```

```python
        self._replay = replay
```

`_step` fragt zuerst das Journal. Nur ein Eintrag mit Ausgang `"ok"` darf einen echten Lauf ersetzen — ein journalisierter Fehler ist kein Ergebnis:

```python
    def _step(self, node: Node[T], state: State[T]) -> _Step[T]:
        cached = self._journal.lookup(node.name, input_hash(node.name, state.data))
        if cached is not None and cached.outcome == "ok":
            return _Step(state.merged(cached.delta))
        if self._replay:
            detail = f"node {node.name!r} is not in the journal"
            return _Step(state, failed=True, detail=detail)

        started = self._clock()
        ...
```

Im Wiedergabemodus schreibt `_write` nichts:

```python
    def _write(self, ...) -> None:
        if self._replay:
            return
        ...
```

- [ ] **Step 4: Tests, Linter und Typen laufen lassen**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run coverage run -m pytest && uv run coverage report
```

Expected: alle Tests PASS, Coverage 100 % für alle bisher geschriebenen Module.

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/runner.py tests/test_resume.py
git commit -m "Resume from the journal, and replay a run without spending a token"
```

---

## Task 9: Projektkonfiguration

**Files:**
- Create: `src/ultraloom/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nichts (Modulgrenze: kein Import aus dem Harness-Ast)
- Produces:
  - `class Config` (frozen) mit `root: Path`, `commands: Mapping[str, str]`, `exec_prefix: tuple[str, ...]`, `coverage_report: str | None`, `coverage_threshold: int`, `mcp_servers: tuple[str, ...]`
  - `load_config(root: Path) -> Config`
  - `class ConfigError(ValueError)`
  - `CONFIG_NAME = ".ultraloom/config.toml"`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`tests/test_config.py`:

```python
"""Tests for reading .ultraloom/config.toml."""

from pathlib import Path

import pytest

from ultraloom.config import ConfigError, load_config


def write_config(root: Path, body: str) -> None:
    target = root / ".ultraloom" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_a_project_without_a_config_gets_empty_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config.commands == {}
    assert config.exec_prefix == ()
    assert config.coverage_threshold == 100


def test_check_commands_are_read(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify]\nlint = "uvx gdlint ."\ntest = "godot --headless"\n')

    config = load_config(tmp_path)

    assert config.commands["lint"] == "uvx gdlint ."
    assert config.commands["test"] == "godot --headless"


def test_the_exec_prefix_is_split_into_argv(tmp_path: Path) -> None:
    write_config(tmp_path, '[exec]\nprefix = "docker compose exec -T frontend"\n')

    assert load_config(tmp_path).exec_prefix == ("docker", "compose", "exec", "-T", "frontend")


def test_coverage_report_and_threshold_are_read(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        '[verify]\n[verify.coverage]\nreport = "coverage-report/lcov.info"\nthreshold = 90\n',
    )

    config = load_config(tmp_path)

    assert config.coverage_report == "coverage-report/lcov.info"
    assert config.coverage_threshold == 90


def test_mcp_servers_are_read(tmp_path: Path) -> None:
    write_config(tmp_path, '[agent]\nmcp_servers = ["ultra-brain"]\n')

    assert load_config(tmp_path).mcp_servers == ("ultra-brain",)


def test_broken_toml_is_reported_with_the_path(tmp_path: Path) -> None:
    write_config(tmp_path, "this is not toml =\n")

    with pytest.raises(ConfigError, match="config.toml"):
        load_config(tmp_path)


def test_a_non_string_command_is_refused(tmp_path: Path) -> None:
    write_config(tmp_path, "[verify]\nlint = 7\n")

    with pytest.raises(ConfigError, match="lint"):
        load_config(tmp_path)


def test_a_non_integer_threshold_is_refused(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify]\n[verify.coverage]\nthreshold = "all of it"\n')

    with pytest.raises(ConfigError, match="threshold"):
        load_config(tmp_path)


def test_the_config_module_does_not_import_the_harness() -> None:
    """Spec 15.2: the check side must stay installable without the agent extra."""
    import ultraloom.config as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("from ultraloom.graph", "from ultraloom.runner", "from ultraloom.model"):
        assert forbidden not in source
```

- [ ] **Step 2: Test laufen lassen und Fehlschlag bestätigen**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.config'`

- [ ] **Step 3: Implementieren**

`src/ultraloom/config.py`:

```python
"""Reading a project's .ultraloom/config.toml.

Configuration says two independent things: which tool runs a check, and where
it runs. Splitting those is what lets a project that checks through a container
boundary still profit from the language presets.
"""

from __future__ import annotations

import shlex
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_NAME = ".ultraloom/config.toml"

_KINDS = ("lint", "types", "test", "coverage")


class ConfigError(ValueError):
    """Raised for a config file that cannot be read or means two things."""


@dataclass(frozen=True, slots=True)
class Config:
    """What a project says about how it is checked."""

    root: Path
    commands: Mapping[str, str] = field(default_factory=dict)
    exec_prefix: tuple[str, ...] = ()
    coverage_report: str | None = None
    coverage_threshold: int = 100
    mcp_servers: tuple[str, ...] = ()


def load_config(root: Path) -> Config:
    """Read the project's configuration, or return empty defaults."""
    path = root / CONFIG_NAME
    if not path.exists():
        return Config(root)

    try:
        # tomllib returns nested dicts of unknown shape; every field below is
        # narrowed explicitly, which is why the raw mapping is typed loosely.
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error

    verify = _table(raw, "verify", path)
    coverage = _table(verify, "coverage", path)
    agent = _table(raw, "agent", path)

    commands: dict[str, str] = {}
    for kind in _KINDS:
        if kind not in verify or kind == "coverage":
            continue
        value = verify[kind]
        if not isinstance(value, str):
            raise ConfigError(f"{path}: [verify].{kind} must be a string, got {type(value).__name__}")
        commands[kind] = value

    threshold = coverage.get("threshold", 100)
    if not isinstance(threshold, int) or isinstance(threshold, bool):
        raise ConfigError(f"{path}: [verify.coverage].threshold must be an integer")

    report = coverage.get("report")
    if report is not None and not isinstance(report, str):
        raise ConfigError(f"{path}: [verify.coverage].report must be a string")

    prefix = _table(raw, "exec", path).get("prefix", "")
    if not isinstance(prefix, str):
        raise ConfigError(f"{path}: [exec].prefix must be a string")

    servers = agent.get("mcp_servers", [])
    if not isinstance(servers, list) or not all(isinstance(name, str) for name in servers):
        raise ConfigError(f"{path}: [agent].mcp_servers must be a list of strings")

    return Config(
        root=root,
        commands=commands,
        exec_prefix=tuple(shlex.split(prefix)),
        coverage_report=report,
        coverage_threshold=threshold,
        mcp_servers=tuple(servers),
    )


def _table(raw: Mapping[str, Any], name: str, path: Path) -> Mapping[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: [{name}] must be a table")
    return value
```

- [ ] **Step 4: Tests, Linter und Typen laufen lassen**

```bash
uv run pytest tests/test_config.py -v
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/config.py tests/test_config.py
git commit -m "Read a project's checks and its execution prefix as separate things"
```

---

## Task 10: Prüfkette

**Files:**
- Create: `src/ultraloom/checks.py`
- Test: `tests/test_checks.py`

**Interfaces:**
- Consumes: `Config`, `load_config` aus `config.py`
- Produces:
  - `class Command` (frozen) mit `kind: str`, `argv: tuple[str, ...]`, `source: str` (`"config"` | `"script"` | `"preset"`)
  - `class CheckResult` (frozen) mit `kind: str`, `ok: bool`, `output: str`, `source: str`
  - `resolve_check(kind: str, config: Config) -> Command`
  - `run_check(kind: str, config: Config) -> CheckResult`
  - `class CheckUnavailableError(RuntimeError)`
  - `PRESETS: Mapping[str, Mapping[str, tuple[str, ...]]]`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`tests/test_checks.py`:

```python
"""Tests for resolving and running the check chain."""

import sys
from pathlib import Path

import pytest

from ultraloom.checks import CheckUnavailableError, resolve_check, run_check
from ultraloom.config import load_config


def python_project(root: Path) -> Path:
    (root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    return root


def node_project(root: Path) -> Path:
    (root / "package.json").write_text('{"name": "x"}\n', encoding="utf-8")
    return root


def godot_project(root: Path) -> Path:
    (root / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return root


def write_config(root: Path, body: str) -> None:
    target = root / ".ultraloom" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_config_beats_everything(tmp_path: Path) -> None:
    python_project(tmp_path)
    write_config(tmp_path, '[verify]\nlint = "my-own-linter --strict"\n')

    command = resolve_check("lint", load_config(tmp_path))

    assert command.argv == ("my-own-linter", "--strict")
    assert command.source == "config"


def test_a_convention_script_beats_the_preset(tmp_path: Path) -> None:
    python_project(tmp_path)
    script = tmp_path / ".ultraloom" / "checks" / "lint.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('linted')\n", encoding="utf-8")

    command = resolve_check("lint", load_config(tmp_path))

    assert command.source == "script"
    assert str(script) in " ".join(command.argv)


def test_the_python_preset_is_found_from_pyproject(tmp_path: Path) -> None:
    python_project(tmp_path)

    command = resolve_check("types", load_config(tmp_path))

    assert command.source == "preset"
    assert command.argv[:2] == ("uvx", "mypy")


def test_the_node_preset_is_found_from_package_json(tmp_path: Path) -> None:
    node_project(tmp_path)

    assert resolve_check("types", load_config(tmp_path)).argv == ("tsc", "--noEmit")
    assert resolve_check("lint", load_config(tmp_path)).argv == ("eslint", ".")


def test_the_godot_preset_is_found_from_project_godot(tmp_path: Path) -> None:
    godot_project(tmp_path)

    assert resolve_check("lint", load_config(tmp_path)).argv == ("uvx", "gdlint", ".")


def test_gdscript_has_no_typechecker_and_says_so(tmp_path: Path) -> None:
    """A missing capability must be reported, never counted as passed."""
    godot_project(tmp_path)

    with pytest.raises(CheckUnavailableError, match="known limitation"):
        resolve_check("types", load_config(tmp_path))


def test_an_unrecognised_project_refuses_to_guess(tmp_path: Path) -> None:
    with pytest.raises(CheckUnavailableError, match="could not tell"):
        resolve_check("lint", load_config(tmp_path))


def test_an_unknown_check_kind_is_refused(tmp_path: Path) -> None:
    python_project(tmp_path)

    with pytest.raises(CheckUnavailableError, match="unknown check"):
        resolve_check("vibes", load_config(tmp_path))


def test_the_exec_prefix_is_put_in_front_of_a_preset(tmp_path: Path) -> None:
    node_project(tmp_path)
    write_config(tmp_path, '[exec]\nprefix = "docker compose exec -T frontend"\n')

    command = resolve_check("lint", load_config(tmp_path))

    assert command.argv == ("docker", "compose", "exec", "-T", "frontend", "eslint", ".")


def test_the_exec_prefix_is_put_in_front_of_a_configured_command(tmp_path: Path) -> None:
    node_project(tmp_path)
    write_config(tmp_path, '[exec]\nprefix = "docker compose exec -T web"\n[verify]\nlint = "biome check"\n')

    assert resolve_check("lint", load_config(tmp_path)).argv == (
        "docker",
        "compose",
        "exec",
        "-T",
        "web",
        "biome",
        "check",
    )


def test_a_passing_command_reports_ok(tmp_path: Path) -> None:
    write_config(tmp_path, f'[verify]\nlint = "{sys.executable} -c pass"\n')

    result = run_check("lint", load_config(tmp_path))

    assert result.ok is True
    assert result.kind == "lint"


def test_a_failing_command_reports_not_ok_and_keeps_its_output(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        f"[verify]\nlint = \"{sys.executable} -c 'import sys; print(\\\"three problems\\\"); sys.exit(1)'\"\n",
    )

    result = run_check("lint", load_config(tmp_path))

    assert result.ok is False
    assert "three problems" in result.output


def test_a_missing_executable_reports_not_ok_rather_than_crashing(tmp_path: Path) -> None:
    """A tool that is not installed is a failure, never a skipped check."""
    write_config(tmp_path, '[verify]\nlint = "definitely-not-installed-anywhere"\n')

    result = run_check("lint", load_config(tmp_path))

    assert result.ok is False
    assert "definitely-not-installed-anywhere" in result.output


def test_the_checks_module_does_not_import_the_harness() -> None:
    """Spec 15.2: the check side must stay installable without the agent extra."""
    import ultraloom.checks as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("from ultraloom.graph", "from ultraloom.runner", "from ultraloom.model"):
        assert forbidden not in source
```

- [ ] **Step 2: Test laufen lassen und Fehlschlag bestätigen**

Run: `uv run pytest tests/test_checks.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.checks'`

- [ ] **Step 3: Implementieren**

`src/ultraloom/checks.py`:

```python
"""Resolving and running a project's checks.

Four stages, first hit wins: explicit configuration, a script at a named path,
the language preset, then refusal. Detection saves work; guessing would cost
reliability — and a missing tool is a failure, never a skipped check.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ultraloom.config import Config

KINDS = ("lint", "types", "test", "coverage")

# marker file -> check kind -> the tool's argv
PRESETS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "pyproject.toml": {
        "lint": ("uvx", "ruff", "check", "."),
        "types": ("uvx", "mypy"),
        "test": ("uv", "run", "pytest"),
        "coverage": ("uv", "run", "coverage", "report"),
    },
    "package.json": {
        "lint": ("eslint", "."),
        "types": ("tsc", "--noEmit"),
        "test": ("vitest", "run"),
        "coverage": ("vitest", "run", "--coverage"),
    },
    "project.godot": {
        "lint": ("uvx", "gdlint", "."),
        "test": ("godot", "--headless", "--quit"),
    },
}

_LANGUAGE_NAMES: Mapping[str, str] = {
    "pyproject.toml": "Python",
    "package.json": "Node",
    "project.godot": "GDScript",
}


class CheckUnavailableError(RuntimeError):
    """Raised when a check cannot be resolved. Never a reason to skip it."""


@dataclass(frozen=True, slots=True)
class Command:
    """A resolved check: what to run, and where the decision came from."""

    kind: str
    argv: tuple[str, ...]
    source: str


@dataclass(frozen=True, slots=True)
class CheckResult:
    """What a check said."""

    kind: str
    ok: bool
    output: str
    source: str


def resolve_check(kind: str, config: Config) -> Command:
    """Find the command for this check, or refuse to guess."""
    if kind not in KINDS:
        raise CheckUnavailableError(f"unknown check {kind!r}; known: {', '.join(KINDS)}")

    if kind in config.commands:
        return Command(kind, config.exec_prefix + tuple(shlex.split(config.commands[kind])), "config")

    script = _script_for(kind, config.root)
    if script is not None:
        return Command(kind, config.exec_prefix + script, "script")

    marker = _marker(config.root)
    if marker is None:
        raise CheckUnavailableError(
            f"could not tell what kind of project {config.root} is; "
            f"set [verify].{kind} in {config.root / '.ultraloom' / 'config.toml'}"
        )

    preset = PRESETS[marker]
    if kind not in preset:
        raise CheckUnavailableError(
            f"{_LANGUAGE_NAMES[marker]} has no {kind} tool — a known limitation, not a passed check"
        )
    return Command(kind, config.exec_prefix + preset[kind], "preset")


def run_check(kind: str, config: Config) -> CheckResult:
    """Run the check and report what it said."""
    command = resolve_check(kind, config)
    try:
        completed = subprocess.run(  # noqa: S603  # the argv comes from the project's own config
            command.argv,
            cwd=config.root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return CheckResult(kind, False, f"could not run {command.argv[0]!r}: {error}", command.source)
    output = completed.stdout + completed.stderr
    return CheckResult(kind, completed.returncode == 0, output, command.source)


def _script_for(kind: str, root: Path) -> tuple[str, ...] | None:
    """A check script at the conventional path, if the project put one there.

    A named path, deliberately not a search for anything that looks like a
    check script — that would be guessing.
    """
    directory = root / ".ultraloom" / "checks"
    if not directory.is_dir():
        return None
    for candidate in sorted(directory.glob(f"{kind}.*")):
        if candidate.suffix == ".py":
            return (sys.executable, str(candidate))
        return (str(candidate),)
    return None


def _marker(root: Path) -> str | None:
    for name in PRESETS:
        if (root / name).exists():
            return name
    return None
```

- [ ] **Step 4: Tests, Linter und Typen laufen lassen**

```bash
uv run pytest tests/test_checks.py -v
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/checks.py tests/test_checks.py
git commit -m "Resolve a check in four stages and refuse to guess at the last one"
```

---

## Task 11: Abläufe finden

**Files:**
- Create: `src/ultraloom/discovery.py`
- Test: `tests/test_discovery.py`

**Interfaces:**
- Consumes: `Graph` aus `graph.py`
- Produces:
  - `find_flow(name: str, root: Path) -> Graph[object]`
  - `list_flows(root: Path) -> tuple[str, ...]`
  - `class FlowNotFoundError(LookupError)`
  - `class FlowLoadError(RuntimeError)`
  - `FLOW_DIR = ".ultraloom/flows"`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`tests/test_discovery.py`:

```python
"""Tests for finding a project's flows."""

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
'''


def write_flow(root: Path, name: str, body: str = A_FLOW) -> None:
    target = root / ".ultraloom" / "flows" / f"{name}.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_a_flow_is_found_by_file_name(tmp_path: Path) -> None:
    write_flow(tmp_path, "smoke")

    assert find_flow("smoke", tmp_path).name == "smoke"


def test_flows_are_listed_alphabetically(tmp_path: Path) -> None:
    write_flow(tmp_path, "second")
    write_flow(tmp_path, "first")

    assert list_flows(tmp_path) == ("first", "second")


def test_a_project_without_a_flow_directory_lists_nothing(tmp_path: Path) -> None:
    assert list_flows(tmp_path) == ()


def test_an_absent_flow_names_what_is_available(tmp_path: Path) -> None:
    write_flow(tmp_path, "smoke")

    with pytest.raises(FlowNotFoundError, match="smoke"):
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

    with pytest.raises(FlowLoadError, match="broken.py"):
        find_flow("broken", tmp_path)


def test_two_flows_with_the_same_module_name_do_not_collide(tmp_path: Path) -> None:
    """Flows from different projects must not shadow each other in sys.modules."""
    other = tmp_path / "other"
    other.mkdir()
    write_flow(tmp_path, "smoke")
    write_flow(other, "smoke", A_FLOW.replace('Graph("smoke"', 'Graph("other-smoke"'))

    assert find_flow("smoke", tmp_path).name == "smoke"
    assert find_flow("smoke", other).name == "other-smoke"
```

- [ ] **Step 2: Test laufen lassen und Fehlschlag bestätigen**

Run: `uv run pytest tests/test_discovery.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.discovery'`

- [ ] **Step 3: Implementieren**

`src/ultraloom/discovery.py`:

```python
"""Finding the flows a project keeps beside its own code.

ultraloom loads them and knows nothing else about them: a project's flows carry
that project's world, and the core must not.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from ultraloom.graph import Graph

FLOW_DIR = ".ultraloom/flows"


class FlowNotFoundError(LookupError):
    """Raised when no flow of that name exists in the project."""


class FlowLoadError(RuntimeError):
    """Raised when a flow module cannot be imported or holds no graph."""


def list_flows(root: Path) -> tuple[str, ...]:
    """The names of the project's flows, sorted."""
    directory = root / FLOW_DIR
    if not directory.is_dir():
        return ()
    return tuple(sorted(path.stem for path in directory.glob("*.py") if path.stem != "__init__"))


def find_flow(name: str, root: Path) -> Graph[object]:
    """Load one flow by name."""
    path = root / FLOW_DIR / f"{name}.py"
    if not path.is_file():
        available = ", ".join(list_flows(root)) or "none"
        raise FlowNotFoundError(f"no flow {name!r} in {root / FLOW_DIR}; available: {available}")

    # The module name carries the project path so two projects can each have a
    # flow called "verify" without one shadowing the other in sys.modules.
    unique = f"ultraloom_flow_{abs(hash(str(path)))}_{name}"
    spec = importlib.util.spec_from_file_location(unique, path)
    if spec is None or spec.loader is None:  # pragma: no cover  # a .py file always yields a loader
        raise FlowLoadError(f"{path}: cannot be loaded as a module")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise FlowLoadError(f"{path}: {error}") from error

    flow = getattr(module, "flow", None)
    if flow is None:
        raise FlowLoadError(f"{path}: defines no module-level `flow`")
    if not isinstance(flow, Graph):
        raise FlowLoadError(f"{path}: `flow` must be a Graph, got {type(flow).__name__}")
    return flow
```

- [ ] **Step 4: Tests, Linter und Typen laufen lassen**

```bash
uv run pytest tests/test_discovery.py -v
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/discovery.py tests/test_discovery.py
git commit -m "Load a project's flows without knowing anything else about it"
```

---
## Task 12: Kommandozeile

**Files:**
- Create: `src/ultraloom/cli.py`
- Modify: `src/ultraloom/discovery.py` (Anfangszustand mitladen)
- Test: `tests/test_cli.py`, `tests/test_discovery.py` (zwei Tests ergänzen)

**Interfaces:**
- Consumes: `load_config`, `run_check`, `resolve_check`, `CheckUnavailableError`, `find_flow`, `list_flows`, `Journal`, `Runner`, `pending_gate`
- Produces:
  - `class LoadedFlow` (frozen) mit `graph: Graph[object]`, `initial: object`
  - `find_flow(name: str, root: Path) -> LoadedFlow` (geänderte Rückgabe)
  - `main(argv: Sequence[str] | None = None) -> int`
  - `next_run_id(root: Path) -> str`
  - `RUN_DIR = ".ultraloom/runs"`

- [ ] **Step 1: `discovery.py` um den Anfangszustand erweitern**

Ein Ausführer braucht zwei Dinge vom Ablauf: den Graphen und den Zustand, mit dem er beginnt. Bisher liefert `find_flow` nur den Graphen, also könnte die CLI keinen Lauf starten.

Ergänze in `src/ultraloom/discovery.py` — Import und Rückgabetyp:

```python
from dataclasses import dataclass
```

```python
@dataclass(frozen=True, slots=True)
class LoadedFlow:
    """A flow's graph together with the state it starts from."""

    graph: Graph[object]
    initial: object
```

Und am Ende von `find_flow`, anstelle des bisherigen `return flow`:

```python
    initial = getattr(module, "initial", None)
    if initial is None:
        raise FlowLoadError(f"{path}: defines no module-level `initial` state")
    return LoadedFlow(flow, initial)
```

Passe in `tests/test_discovery.py` die Ablaufvorlage und die betroffenen Zusagen an:

```python
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
```

In `test_a_flow_is_found_by_file_name` und `test_two_flows_with_the_same_module_name_do_not_collide` wird `find_flow(...).name` zu `find_flow(...).graph.name`. Dazu zwei neue Tests:

```python
def test_the_initial_state_comes_back_with_the_graph(tmp_path: Path) -> None:
    write_flow(tmp_path, "smoke")

    loaded = find_flow("smoke", tmp_path)

    assert loaded.initial.__class__.__name__ == "Data"


def test_a_module_without_an_initial_state_is_refused(tmp_path: Path) -> None:
    body = A_FLOW.replace("initial = Data()", "")
    write_flow(tmp_path, "noinit", body)

    with pytest.raises(FlowLoadError, match="initial"):
        find_flow("noinit", tmp_path)
```

- [ ] **Step 2: Den fehlschlagenden Test für die CLI schreiben**

`tests/test_cli.py`:

```python
"""Tests for the command line."""

import sys
from pathlib import Path

from ultraloom.cli import main, next_run_id

A_FLOW = '''
"""A flow that finishes on its own."""

from dataclasses import dataclass

from ultraloom.graph import END, CodeNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    note: str = ""


flow: Graph[Data] = Graph("smoke", start="mark")
flow.add(CodeNode("mark", lambda _d: {"note": "marked"}))
flow.edge("mark", END)

initial = Data()
'''

A_GATED_FLOW = '''
"""A flow that stops for an answer."""

from dataclasses import dataclass

from ultraloom.graph import END, CodeNode, GateNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    answer: str = ""


flow: Graph[Data] = Graph("gated", start="ask")
flow.add(GateNode("ask", lambda _d: "Proceed?", lambda _d, a: {"answer": a}))
flow.add(CodeNode("act", lambda d: {"answer": d.answer + "!"}))
flow.edge("ask", "act")
flow.edge("act", END)

initial = Data()
'''


def write_flow(root: Path, name: str, body: str) -> None:
    target = root / ".ultraloom" / "flows" / f"{name}.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def write_config(root: Path, body: str) -> None:
    target = root / ".ultraloom" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_run_ids_count_up_and_are_zero_padded(tmp_path: Path) -> None:
    """Run ids come from the directory, not a clock — so tests stay deterministic."""
    assert next_run_id(tmp_path) == "0001"
    runs = tmp_path / ".ultraloom" / "runs"
    runs.mkdir(parents=True)
    (runs / "0001.jsonl").touch()

    assert next_run_id(tmp_path) == "0002"


def test_run_finishes_a_flow_and_reports_the_run_id(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]  # pytest's capsys fixture is untyped
    write_flow(tmp_path, "smoke", A_FLOW)

    code = main(["run", "smoke", "--root", str(tmp_path)])

    assert code == 0
    out = capsys.readouterr().out
    assert "done" in out
    assert "0001" in out
    assert (tmp_path / ".ultraloom" / "runs" / "0001.jsonl").exists()


def test_run_names_the_available_flows_when_the_name_is_wrong(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    write_flow(tmp_path, "smoke", A_FLOW)

    code = main(["run", "nope", "--root", str(tmp_path)])

    assert code == 1
    assert "smoke" in capsys.readouterr().err


def test_run_reports_a_pause_and_the_question(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    write_flow(tmp_path, "gated", A_GATED_FLOW)

    code = main(["run", "gated", "--root", str(tmp_path)])

    assert code == 2, "a pause is neither success nor failure"
    assert "Proceed?" in capsys.readouterr().out


def test_resume_with_an_answer_finishes_the_run(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    write_flow(tmp_path, "gated", A_GATED_FLOW)
    main(["run", "gated", "--root", str(tmp_path)])
    capsys.readouterr()

    code = main(["resume", "0001", "--answer", "yes", "--root", str(tmp_path)])

    assert code == 0
    assert "done" in capsys.readouterr().out


def test_resume_of_an_unknown_run_id_fails(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    write_flow(tmp_path, "gated", A_GATED_FLOW)

    code = main(["resume", "9999", "--answer", "yes", "--root", str(tmp_path)])

    assert code == 1
    assert "9999" in capsys.readouterr().err


def test_show_prints_a_line_per_node_with_tokens_and_seconds(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    write_flow(tmp_path, "smoke", A_FLOW)
    main(["run", "smoke", "--root", str(tmp_path)])
    capsys.readouterr()

    code = main(["show", "0001", "--root", str(tmp_path)])

    assert code == 0
    out = capsys.readouterr().out
    assert "mark" in out
    assert "code" in out
    assert "ok" in out


def test_replay_reaches_the_same_end_without_running_a_node(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    write_flow(tmp_path, "smoke", A_FLOW)
    main(["run", "smoke", "--root", str(tmp_path)])
    before = (tmp_path / ".ultraloom" / "runs" / "0001.jsonl").read_text(encoding="utf-8")
    capsys.readouterr()

    code = main(["replay", "0001", "--root", str(tmp_path)])

    assert code == 0
    assert "done" in capsys.readouterr().out
    after = (tmp_path / ".ultraloom" / "runs" / "0001.jsonl").read_text(encoding="utf-8")
    assert after == before, "replay must not append to the journal it reads"


def test_check_reports_zero_when_the_command_passes(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    write_config(tmp_path, f'[verify]\nlint = "{sys.executable} -c pass"\n')

    code = main(["check", "lint", "--root", str(tmp_path)])

    assert code == 0
    assert "lint" in capsys.readouterr().out


def test_check_reports_one_and_the_output_when_the_command_fails(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    write_config(
        tmp_path,
        f"[verify]\nlint = \"{sys.executable} -c 'import sys; print(\\\"bad\\\"); sys.exit(1)'\"\n",
    )

    code = main(["check", "lint", "--root", str(tmp_path)])

    assert code == 1
    assert "bad" in capsys.readouterr().out


def test_check_reports_an_unresolvable_check_as_a_failure(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """An unresolvable check must never look like a passed one."""
    code = main(["check", "lint", "--root", str(tmp_path)])

    assert code == 1
    assert "could not tell" in capsys.readouterr().err


def test_check_honours_the_coverage_threshold_flag(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    write_config(tmp_path, f'[verify]\ncoverage = "{sys.executable} -c pass"\n')

    code = main(["check", "coverage", "--threshold", "90", "--root", str(tmp_path)])

    assert code == 0
    assert "90" in capsys.readouterr().out


def test_no_subcommand_prints_usage_and_fails(capsys) -> None:  # type: ignore[no-untyped-def]
    code = main([])

    assert code == 1
    assert "usage" in capsys.readouterr().err.lower()


def test_run_of_a_flow_that_needs_a_model_says_so(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """Without the agent extra the message must name the install, not raise ImportError."""
    body = '''
from dataclasses import dataclass

from ultraloom.graph import END, AgentNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    note: str = ""


flow: Graph[Data] = Graph("needs-model", start="ask")
flow.add(AgentNode("ask", lambda _d: "question", schema=Data, apply=lambda _d, _r: {}))
flow.edge("ask", END)

initial = Data()
'''
    write_flow(tmp_path, "needs_model", body)

    code = main(["run", "needs_model", "--root", str(tmp_path), "--no-model"])

    assert code == 1
    assert "ultraloom[agent]" in capsys.readouterr().out
```

- [ ] **Step 3: Test laufen lassen und Fehlschlag bestätigen**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.cli'`

- [ ] **Step 4: Implementieren**

`src/ultraloom/cli.py`:

```python
"""The command line. A paused run needs an address, and a check needs a caller."""

from __future__ import annotations

import argparse
import dataclasses
import sys
from collections.abc import Sequence
from pathlib import Path

from ultraloom.checks import CheckUnavailableError, run_check
from ultraloom.config import load_config

RUN_DIR = ".ultraloom/runs"

_EXIT_OK = 0
_EXIT_FAIL = 1
_EXIT_PAUSED = 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run one subcommand. Returns the process exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_usage(sys.stderr)
        return _EXIT_FAIL

    root = Path(args.root).resolve()
    if args.command == "check":
        return _check(args.kind, root, args.threshold)
    return _flow_command(args, root)


def next_run_id(root: Path) -> str:
    """The next run's id: a counter over the run directory, never a clock."""
    directory = root / RUN_DIR
    existing = sorted(path.stem for path in directory.glob("*.jsonl")) if directory.is_dir() else []
    highest = max((int(stem) for stem in existing if stem.isdigit()), default=0)
    return f"{highest + 1:04d}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ultraloom", description="Run checks and agent flows.")
    parser.add_argument("--root", default=".", help="project root (default: the current directory)")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="run a flow from its start")
    run.add_argument("flow")
    run.add_argument("--no-model", action="store_true", help="run without a model, for diagnosis")

    for name, help_text in (
        ("show", "print a run's journal"),
        ("replay", "re-derive a run from its journal, without a model call"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("run_id")

    resume = subparsers.add_parser("resume", help="carry a paused or aborted run onward")
    resume.add_argument("run_id")
    resume.add_argument("--answer", default=None, help="the answer to the run's open gate")

    check = subparsers.add_parser("check", help="run one of the project's checks")
    check.add_argument("kind", choices=("lint", "types", "test", "coverage"))
    check.add_argument("--threshold", type=int, default=None, help="coverage threshold in percent")

    return parser


def _check(kind: str, root: Path, threshold: int | None) -> int:
    config = load_config(root)
    if threshold is not None:
        config = dataclasses.replace(config, coverage_threshold=threshold)
    try:
        result = run_check(kind, config)
    except CheckUnavailableError as error:
        print(str(error), file=sys.stderr)
        return _EXIT_FAIL

    verdict = "ok" if result.ok else "failed"
    detail = f" (threshold {config.coverage_threshold}%)" if kind == "coverage" else ""
    print(f"{result.kind}: {verdict} [{result.source}]{detail}")
    if result.output:
        print(result.output, end="" if result.output.endswith("\n") else "\n")
    return _EXIT_OK if result.ok else _EXIT_FAIL


def _flow_command(args: argparse.Namespace, root: Path) -> int:
    # Imported here so `ultraloom check` never touches the harness side, which
    # would drag in the optional agent extra (spec 15.2).
    from ultraloom.discovery import FlowLoadError, FlowNotFoundError, find_flow
    from ultraloom.journal import Journal
    from ultraloom.runner import Runner

    if args.command == "show":
        return _show(root, args.run_id)

    if args.command == "run":
        run_id = next_run_id(root)
        flow_name = args.flow
    else:
        run_id = args.run_id
        journal_path = root / RUN_DIR / f"{run_id}.jsonl"
        if not journal_path.exists():
            print(f"no run {run_id!r} under {root / RUN_DIR}", file=sys.stderr)
            return _EXIT_FAIL
        flow_name = _flow_of(root, run_id)

    try:
        loaded = find_flow(flow_name, root)
    except (FlowNotFoundError, FlowLoadError) as error:
        print(str(error), file=sys.stderr)
        return _EXIT_FAIL

    journal = Journal(root / RUN_DIR / f"{run_id}.jsonl")
    _remember_flow(root, run_id, flow_name)
    model = None if getattr(args, "no_model", False) else _model(root)
    runner = Runner(
        loaded.graph,
        journal,
        model=model,
        mcp_servers=load_config(root).mcp_servers,
        replay=args.command == "replay",
    )

    result = (
        runner.resume(loaded.initial, answer=args.answer)
        if args.command == "resume"
        else runner.run(loaded.initial)
    )

    print(f"run {run_id}: {result.status}")
    if result.question is not None:
        print(result.question)
    if result.detail is not None:
        print(result.detail)
    if result.status == "paused":
        return _EXIT_PAUSED
    return _EXIT_OK if result.status == "done" else _EXIT_FAIL


def _show(root: Path, run_id: str) -> int:
    from ultraloom.journal import Journal

    path = root / RUN_DIR / f"{run_id}.jsonl"
    if not path.exists():
        print(f"no run {run_id!r} under {root / RUN_DIR}", file=sys.stderr)
        return _EXIT_FAIL
    for entry in Journal(path).entries():
        profile = entry.tools or "-"
        print(
            f"{entry.node:<24} {entry.kind:<6} {entry.outcome:<7} "
            f"{entry.tokens:>7} tok {entry.seconds:>7.2f}s {profile}"
        )
    return _EXIT_OK


def _flow_of(root: Path, run_id: str) -> str:
    """Which flow a run belongs to, remembered beside its journal."""
    marker = root / RUN_DIR / f"{run_id}.flow"
    return marker.read_text(encoding="utf-8").strip() if marker.exists() else run_id


def _remember_flow(root: Path, run_id: str, flow_name: str) -> None:
    marker = root / RUN_DIR / f"{run_id}.flow"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(flow_name + "\n", encoding="utf-8")


def _model(root: Path) -> object | None:
    """The real model, if the agent extra is installed."""
    # Local import: the agent extra is optional, and `ultraloom check` must work
    # without it (spec 15.2).
    try:
        from ultraloom.model.agent_sdk import AgentSdkModel
    except ImportError:
        return None
    return AgentSdkModel(cwd=root)
```

Der Ausführer muss die Meldung über das fehlende Modell verbessern, damit sie zur Installation führt. In `src/ultraloom/runner.py`, in `_invoke`:

```python
            case AgentNode():
                if self._model is None:
                    raise RuntimeError(
                        f"node {node.name!r} needs a model; install it with "
                        'uv add "ultraloom[agent]"'
                    )
```

Passe die Zusage in `tests/test_runner.py` an — `assert "no model" in result.detail` wird zu:

```python
    assert "needs a model" in result.detail
```

- [ ] **Step 5: Tests, Linter und Typen laufen lassen**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Expected: alle Tests PASS. `test_cli.py::test_run_of_a_flow_that_needs_a_model_says_so` beweist, dass die Meldung zur Installation führt statt einen `ImportError` zu zeigen.

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/cli.py src/ultraloom/discovery.py src/ultraloom/runner.py tests/test_cli.py tests/test_discovery.py tests/test_runner.py
git commit -m "Give every run an address on the command line"
```

---

## Task 13: Anbindung an das Claude Agent SDK und die Modulgrenze

**Files:**
- Create: `src/ultraloom/model/agent_sdk.py`
- Test: `tests/test_agent_sdk.py`, `tests/test_module_boundary.py`

**Interfaces:**
- Consumes: `Model`, `Request`, `Reply`, `ModelError` aus `model/port.py`
- Produces:
  - `class AgentSdkModel` mit `__init__(cwd: Path)`, `ask(request: Request) -> Reply`

- [ ] **Step 1: Die aktuelle Oberfläche des Agent SDK nachlesen**

Der `claude-api`-Skill deckt Messages API und Managed Agents ab, **nicht** das Agent SDK — das ist ein eigenes Paket mit eigener Dokumentation. Signaturen dürfen nicht geraten werden.

```bash
uv add "ultraloom[agent]"
uv run python -c "import claude_agent_sdk; print(claude_agent_sdk.__version__); print(sorted(n for n in dir(claude_agent_sdk) if not n.startswith('_')))"
```

Lies zusätzlich `code.claude.com/docs/en/agent-sdk`. Notiere vor dem Weiterarbeiten drei Dinge:

1. Der Name der Einstiegsfunktion und ihre Parameter (Prompt, Optionen).
2. Wie die erlaubten Werkzeuge übergeben werden (Feldname im Optionsobjekt).
3. Wie eine schemavalidierte Ausgabe und der Tokenverbrauch aus dem Ergebnis gelesen werden.

Die Struktur unten steht fest — sie ist Übersetzung und nichts weiter. Nur die drei Namen kommen aus der Dokumentation. Weicht die Oberfläche ab, passe `_call` an und lasse den Rest, wie er ist.

- [ ] **Step 2: Den fehlschlagenden Test schreiben**

`tests/test_agent_sdk.py`:

```python
"""Tests for the translation from the model port to the Claude Agent SDK.

The SDK itself is replaced by a stub module, so these tests cover the
translation completely without a network call. A single contract test talks to
the real SDK and stays out of the default run.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ultraloom.model.port import ModelError, Request


@dataclass(frozen=True, slots=True)
class Verdict:
    fix: str = ""


@pytest.fixture
def stub_sdk(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Put a recording stand-in for the SDK into sys.modules."""
    module = ModuleType("claude_agent_sdk")
    module.calls = []  # type: ignore[attr-defined]  # a stub records what it was handed

    def query(prompt: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        module.calls.append((prompt, options))  # type: ignore[attr-defined]
        return {"result": {"fix": "patched"}, "usage": {"output_tokens": 11}}

    module.query = query  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", module)
    return module


def a_request() -> Request:
    return Request(prompt="read the report", tools=("Read", "Grep"), effort="low", schema=Verdict)


def test_the_prompt_and_the_tools_reach_the_sdk(stub_sdk: ModuleType, tmp_path: Path) -> None:
    from ultraloom.model.agent_sdk import AgentSdkModel

    AgentSdkModel(cwd=tmp_path).ask(a_request())

    prompt, options = stub_sdk.calls[0]  # type: ignore[attr-defined]
    assert prompt == "read the report"
    assert options is not None
    assert list(options["allowed_tools"]) == ["Read", "Grep"]


def test_the_effort_and_the_working_directory_reach_the_sdk(
    stub_sdk: ModuleType, tmp_path: Path
) -> None:
    from ultraloom.model.agent_sdk import AgentSdkModel

    AgentSdkModel(cwd=tmp_path).ask(a_request())

    _prompt, options = stub_sdk.calls[0]  # type: ignore[attr-defined]
    assert options["effort"] == "low"
    assert str(tmp_path) == str(options["cwd"])


def test_the_reply_is_built_into_the_schema_and_carries_its_tokens(
    stub_sdk: ModuleType, tmp_path: Path
) -> None:
    from ultraloom.model.agent_sdk import AgentSdkModel

    reply = AgentSdkModel(cwd=tmp_path).ask(a_request())

    assert reply.value == Verdict(fix="patched")
    assert reply.tokens == 11


def test_a_reply_that_does_not_fit_the_schema_is_a_model_error(
    stub_sdk: ModuleType, tmp_path: Path
) -> None:
    """A wrong shape must fail loudly here, not corrupt a later node's state."""
    stub_sdk.query = lambda _p, _o=None: {"result": {"unexpected": 1}, "usage": {}}  # type: ignore[attr-defined]
    from ultraloom.model.agent_sdk import AgentSdkModel

    with pytest.raises(ModelError, match="does not fit"):
        AgentSdkModel(cwd=tmp_path).ask(a_request())


def test_an_sdk_exception_becomes_a_model_error(stub_sdk: ModuleType, tmp_path: Path) -> None:
    def boom(_prompt: str, _options: dict[str, Any] | None = None) -> dict[str, Any]:
        raise RuntimeError("the service is unreachable")

    stub_sdk.query = boom  # type: ignore[attr-defined]
    from ultraloom.model.agent_sdk import AgentSdkModel

    with pytest.raises(ModelError, match="unreachable"):
        AgentSdkModel(cwd=tmp_path).ask(a_request())


def test_a_missing_sdk_is_reported_with_the_install_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    from ultraloom.model.agent_sdk import AgentSdkModel

    with pytest.raises(ModelError, match=r"ultraloom\[agent\]"):
        AgentSdkModel(cwd=tmp_path).ask(a_request())


@pytest.mark.contract
def test_the_real_sdk_answers_a_trivial_question(tmp_path: Path) -> None:
    """Runs only with `-m contract`: needs the SDK, the network and credentials."""
    from ultraloom.model.agent_sdk import AgentSdkModel

    @dataclass(frozen=True, slots=True)
    class Answer:
        capital: str = ""

    reply = AgentSdkModel(cwd=tmp_path).ask(
        Request(
            prompt="What is the capital of France? Answer with the city name only.",
            tools=(),
            effort="low",
            schema=Answer,
        )
    )

    assert isinstance(reply.value, Answer)
    assert reply.tokens > 0
```

- [ ] **Step 3: Implementieren**

`src/ultraloom/model/agent_sdk.py`:

```python
"""Translating the model port into a Claude Agent SDK call.

Deliberately thin: everything the harness needs is decided in `runner.py`, so
this file only renames fields and turns SDK failures into ModelError.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from ultraloom.model.port import ModelError, Reply, Request


class AgentSdkModel:
    """Reaches the model through Claude Code's own harness."""

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    def ask(self, request: Request) -> Reply:
        """Answer one request, or raise ModelError."""
        raw = self._call(request)
        payload = raw.get("result", {})
        tokens = int(raw.get("usage", {}).get("output_tokens", 0))
        try:
            value = request.schema(**payload)
        except TypeError as error:
            raise ModelError(
                f"the reply does not fit {request.schema.__name__}: {payload!r}"
            ) from error
        return Reply(value, tokens)

    def _call(self, request: Request) -> dict[str, Any]:
        # Local import: the Claude Agent SDK is an optional extra, and the check
        # chain must stay usable without it (spec 15.2).
        try:
            import claude_agent_sdk
        except ImportError as error:  # pragma: no cover  # covered via a None entry in sys.modules
            raise ModelError('the agent extra is missing; install it with uv add "ultraloom[agent]"') from error

        if claude_agent_sdk is None:
            raise ModelError('the agent extra is missing; install it with uv add "ultraloom[agent]"')

        options: dict[str, Any] = {
            "allowed_tools": list(request.tools),
            "effort": request.effort,
            "cwd": str(self._cwd),
            "output_schema": _schema_of(request.schema),
        }
        try:
            result = claude_agent_sdk.query(request.prompt, options)
        except Exception as error:
            raise ModelError(f"the agent SDK failed: {error}") from error
        return dict(result)


def _schema_of(schema: type) -> dict[str, Any]:
    """A JSON-schema-shaped description of a frozen dataclass."""
    properties = {
        field.name: {"type": _json_type(field.type)} for field in dataclasses.fields(schema)
    }
    return {"type": "object", "properties": properties, "additionalProperties": False}


def _json_type(annotation: object) -> str:
    text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "str")
    return {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}.get(
        text, "string"
    )
```

- [ ] **Step 4: Den Modulgrenzen-Test schreiben**

`tests/test_module_boundary.py`:

```python
"""The test that keeps the promise "the harness is optional" honest.

A promise without a test decays. This one runs the check chain in a child
process where the Claude Agent SDK cannot be imported at all.
"""

import subprocess
import sys
from pathlib import Path

BLOCK_AND_CHECK = '''
import sys


class Blocker:
    """Makes claude_agent_sdk unimportable, whatever is installed."""

    def find_spec(self, name, path=None, target=None):
        if name == "claude_agent_sdk" or name.startswith("claude_agent_sdk."):
            raise ImportError("blocked for this test")
        return None


sys.meta_path.insert(0, Blocker())

from ultraloom.cli import main

sys.exit(main(["check", "lint", "--root", sys.argv[1]]))
'''

IMPORT_CHECK_SIDE = '''
import sys


class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name == "claude_agent_sdk" or name.startswith("claude_agent_sdk."):
            raise ImportError("blocked for this test")
        return None


sys.meta_path.insert(0, Blocker())

import ultraloom.checks
import ultraloom.cli
import ultraloom.config

for forbidden in ("ultraloom.graph", "ultraloom.runner", "ultraloom.model.agent_sdk"):
    assert forbidden not in sys.modules, f"{forbidden} was pulled in by the check side"
print("clean")
'''


def test_the_check_chain_runs_without_the_agent_sdk(tmp_path: Path) -> None:
    config = tmp_path / ".ultraloom" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f'[verify]\nlint = "{sys.executable} -c pass"\n', encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-c", BLOCK_AND_CHECK, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, (
        f"the check chain must not need the agent SDK\n"
        f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
    )


def test_importing_the_check_side_pulls_in_no_harness_module() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", IMPORT_CHECK_SIDE],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "clean" in completed.stdout
```

- [ ] **Step 5: Alles laufen lassen**

```bash
uv run pytest -v
uv run pytest -m contract -v   # nur wenn Zugangsdaten vorliegen; sonst überspringen
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Expected: die Vorgaberunde PASS. Schlägt `test_importing_the_check_side_pulls_in_no_harness_module` fehl, steht ein Import in `cli.py` oben, der nach unten in die Funktion gehört.

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/model/agent_sdk.py tests/test_agent_sdk.py tests/test_module_boundary.py
git commit -m "Reach the model through the agent SDK, and prove the check side does not need it"
```

---

## Task 14: Abnahme

**Files:**
- Create: `.ultraloom/config.toml`, `.ultraloom/flows/smoke.py` (ultraloom prüft sich mit seinem eigenen Werkzeug)
- Test: keine neuen; diese Aufgabe misst

**Interfaces:**
- Consumes: alles
- Produces: nichts Neues

- [ ] **Step 1: Coverage über das ganze Paket messen**

```bash
uv run coverage run -m pytest
uv run coverage report
```

Expected: `TOTAL ... 100%`. Fehlt eine Zeile, schreibe den fehlenden Test. Ein `# pragma: no cover` ist nur mit begründendem Kommentar erlaubt; in diesem Plan sind genau drei vorgesehen (die Standarduhr in `runner.py`, der Lader-Zweig in `discovery.py`, der `ImportError`-Zweig in `agent_sdk.py`). Kommt ein vierter dazu, prüfe zuerst, ob ein Test einfacher wäre.

- [ ] **Step 2: Prüfen, dass zu jedem Modul ein Testmodul existiert**

```bash
for module in src/ultraloom/*.py src/ultraloom/model/*.py; do
  name=$(basename "$module" .py)
  [ "$name" = "__init__" ] && continue
  ls tests/ | grep -q "$name" || echo "MISSING TEST MODULE: $module"
done
```

Expected: keine Ausgabe. `port.py` wird über `test_model_fake.py` und `test_agent_sdk.py` abgedeckt — trägt der Bericht aus Schritt 1 dafür 100 %, ist die Zusage erfüllt.

- [ ] **Step 3: ultraloom auf sich selbst anwenden**

`.ultraloom/config.toml`:

```toml
# ultraloom checks itself with its own tool. The Python preset would find these
# commands anyway; spelling them out makes the dogfooding visible.
[verify]
lint  = "uv run ruff check ."
types = "uv run mypy"
test  = "uv run pytest"

[verify.coverage]
threshold = 100
```

`.ultraloom/flows/smoke.py`:

```python
"""The smallest real flow: check this project until everything is green.

Deliberately code-only — no AgentNode. It proves the runner, the journal and
the check chain work together before any model is involved. The flows that need
a model come with subproject 2.
"""

from dataclasses import dataclass
from pathlib import Path

from ultraloom.checks import run_check
from ultraloom.config import load_config
from ultraloom.graph import END, CodeNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    lint_ok: bool = False
    types_ok: bool = False
    report: str = ""


def _check(kind: str, data: Data) -> dict[str, object]:
    result = run_check(kind, load_config(Path.cwd()))
    return {f"{kind}_ok": result.ok, "report": data.report + f"{kind}={result.ok} "}


flow: Graph[Data] = Graph("smoke", start="lint")
flow.add(CodeNode("lint", lambda data: _check("lint", data)))
flow.add(CodeNode("types", lambda data: _check("types", data)))
flow.edge("lint", "types")
flow.edge("types", END)

initial = Data()
```

- [ ] **Step 4: Rauchtest fahren**

```bash
uv run ultraloom check lint
uv run ultraloom check types
uv run ultraloom run smoke
uv run ultraloom show 0001
uv run ultraloom replay 0001
```

Expected:
- `check lint` und `check types` melden `ok [config]` und geben 0 zurück.
- `run smoke` meldet `run 0001: done`.
- `show 0001` zeigt zwei Zeilen, `lint` und `types`, beide `code` und `ok`.
- `replay 0001` meldet erneut `done` und verändert `.ultraloom/runs/0001.jsonl` nicht.

Vergleiche die Journaldatei vor und nach dem `replay`:

```bash
cp .ultraloom/runs/0001.jsonl /tmp/before.jsonl
uv run ultraloom replay 0001
diff /tmp/before.jsonl .ultraloom/runs/0001.jsonl && echo "replay wrote nothing"
```

- [ ] **Step 5: Die Läufe aus der Versionsverwaltung heraushalten**

`.gitignore` ergänzen:

```
# Run journals are traces of single runs, not source.
.ultraloom/runs/
```

- [ ] **Step 6: Commit**

```bash
git add .gitignore .ultraloom/config.toml .ultraloom/flows/smoke.py
git commit -m "Check ultraloom with ultraloom"
```

---

## Nicht in diesem Teilprojekt

Damit beim Ausführen nichts hineinwächst, was nicht hierher gehört:

- **`flows/` im Paket bleibt leer.** Mitgelieferte allgemeine Abläufe — allen voran „Prüfschleife bis grün" — sind Teilprojekt 2. Der Rauchtest-Ablauf in Schritt 3 von Aufgabe 14 liegt in `.ultraloom/flows/` des Repos selbst, nicht in `src/ultraloom/flows/`.
- **Effort-Eskalation** (Spec 10) ist ein Muster für einen Ablauf, kein Kernbaustein. Der Kern kann es schon: ein zweiter `AgentNode` mit höherem `effort` und eine Kante dorthin. Als mitgeliefertes Muster kommt es mit Teilprojekt 2.
- **Nebenläufigkeit, Kostengrenze, Scheduler, Weboberfläche** — Spec 17 nennt sie als offene Punkte. Kein Knoten läuft parallel.
- **OKF- und Wiki-Mechanik** gehört nach ultra-brain (Spec 14). Kein Modul im Kern kennt Frontmatter.
- **Hook-Migration** ist Teilprojekt 6, und ihr erster Schritt ist eine Bestandsaufnahme, kein Umbau.

## Selbstprüfung gegen die Spec

| Spec-Abschnitt | Umgesetzt in |
|---|---|
| 5.1 Agent SDK als Grundlage | Aufgabe 13 |
| 5.2 Drei Knotenarten | Aufgabe 2 (`node_kind`, Profil-Vorgabe), 6, 7 |
| 5.3 Unveränderlicher Zustand | Aufgabe 1 |
| 5.4 Journal als einzige Wiederaufnahmequelle | Aufgabe 3, 8 |
| 5.5 Ausführer | Aufgabe 6 |
| 5.6 Port mit Attrappe | Aufgabe 4 |
| 5.7 Dateischnitt | Tabelle oben, alle Aufgaben |
| 6 Abläufe sind Python | Aufgabe 11, 12 |
| 7 Drei Ebenen der Ablage | Aufgabe 11 (`.ultraloom/flows`), 9 (`config.toml`) |
| 8 Werkzeugprofile, lesender Standard, kein Fallback | Aufgabe 5, 2, 6 |
| 9 `ultraloom check`, Werkzeug × Ort, vier Stufen | Aufgabe 9, 10, 12 |
| 10 Effort-Eskalation als Kante | Aufgabe 2 (`effort` je Knoten); Muster in Teilprojekt 2 |
| 11 Drei Fehlersorten | Aufgabe 6 (`on_error`, Werkzeugfehler als Daten), 2 (Graphfehler) |
| 12 Bedienung | Aufgabe 12 |
| 13 Testen, Golden-Journal | Aufgabe 8, 14 |
| 15.1 Paket mit Extra | Aufgabe 1 (`pyproject.toml`), 12 (Meldung) |
| 15.2 Modulgrenze, gesichert | Aufgabe 13 (`test_module_boundary.py`) |
| 15.3 AGPL-3.0 | Aufgabe 1 (`license` im Paket), `LICENSE` liegt bereits |
