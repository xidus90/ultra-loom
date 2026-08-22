# verify-until-green Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der erste mitgelieferte ultraloom-Ablauf prüft ein Projekt, lässt einen Agenten reparieren und wiederholt das, bis alles grün ist oder der Lauf ehrlich rot endet — in ultraloom und in space, allein über `config.toml` unterschieden.

**Architecture:** Zwei Kernänderungen tragen den Ablauf: der Journal-Cache greift nur noch beim Nachvollziehen eines bestehenden Laufs, und mitgelieferte Abläufe werden neben den projektspezifischen auffindbar. Der Ablauf selbst ist ein Vier-Knoten-Graph (`check` → `repair` → `guard` → zurück zu `check`) mit einem roten Ausgang; die Testsperre sitzt als Diff-Vergleich in `guard`, nicht im Werkzeugprofil.

**Tech Stack:** Python 3.13, uv, pytest, coverage, ruff, mypy. Kein neues Paket.

**Spec:** `docs/.superpowers/specs/2026-08-22-teilprojekt-2-verify-until-green-design.md`

## Global Constraints

- Python >= 3.13. `requires-python = ">=3.13"`, ruff `target-version = "py313"`, mypy `python_version = 3.13`.
- Immer `uv` / `uvx`, niemals `pip`. Tests laufen als `uv run pytest`.
- TDD: erst der fehlschlagende Test, dann die Implementierung. Jeder Task endet mit einem Commit.
- 100 % Coverage, gemessen. Ein Ausschluss trägt `# pragma: no cover  # <Grund>`.
- Statische Typen überall. Kein `Any` und kein `# type: ignore` ohne begründenden Kommentar.
- Imports auf Modulebene, außer ein lokaler Import trägt eine Begründung als Kommentar. In `cli.py` sind die Harness-Importe absichtlich lokal (Spec 15.2 des Kern-Designs) — diese Grenze bleibt.
- Code, Identifier, Code-Kommentare, Commit-Nachrichten auf Englisch. Dokumentation und Prosa auf Deutsch.
- Kommentiert wird das *Warum*, nie das *Was*.
- Jedes Modul hat ein Testmodul.

## Zwei Entwurfslücken, die beim Planen aufgefallen sind

Die Spec beschreibt den Ablauf, aber nicht, wie er an seine Parameter kommt und wie er Exit-Code 4 auslöst. Beides wird hier entschieden und in Task 4 und 5 gebaut:

**Parameter.** `find_flow` liefert heute ein statisches `flow` plus `initial` aus dem Modul. Ein mitgelieferter Ablauf kennt aber weder `Config` noch `--checks`. Ein Ablaufmodul darf deshalb statt `flow`/`initial` ein `build(context) -> LoadedFlow` definieren; `FlowContext` trägt `root`, `config` und die Optionen der Kommandozeile.

**Exit-Code 4.** `Result` trägt nur `status` und `detail`, und die CLI bildet jeden Fehler auf 1 ab. Ein Ablauf, der einen eigenen Code nennen will, wirft `FlowExit(code, message)`; der Runner reicht den Code über `Result.exit_code` durch, die CLI verwendet ihn.

---

### Task 1: Konfiguration — `tests`, `timeout`, Profile

**Files:**
- Modify: `src/ultraloom/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nichts.
- Produces: `Config.test_paths: tuple[str, ...]`, `Config.timeout: int`, `Config.profiles: Mapping[str, tuple[str, ...]]`.

`test_paths` heißt nicht `tests`, weil `Config` bereits im Testmodul lebt und ein Feld namens `tests` sich in jedem Testkontext falsch liest. Der TOML-Schlüssel bleibt `tests`.

- [ ] **Step 1: Write the failing test**

```python
def test_reads_test_paths_timeout_and_profiles(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
        [verify]
        tests = ["tests/", "conftest.py"]
        timeout = 90

        [verify.profiles]
        edit = ["lint", "types"]
        precommit = ["lint", "types", "test", "coverage"]
        """,
    )

    config = load_config(tmp_path)

    assert config.test_paths == ("tests/", "conftest.py")
    assert config.timeout == 90
    assert config.profiles["edit"] == ("lint", "types")
    assert config.profiles["precommit"] == ("lint", "types", "test", "coverage")


def test_defaults_when_the_keys_are_absent(tmp_path: Path) -> None:
    _write_config(tmp_path, "[verify]\nlint = 'uvx ruff check .'\n")

    config = load_config(tmp_path)

    assert config.test_paths == ()
    assert config.timeout == 600
    assert config.profiles == {}


def test_rejects_a_profile_naming_an_unknown_check(tmp_path: Path) -> None:
    _write_config(tmp_path, "[verify.profiles]\nedit = ['lint', 'spelling']\n")

    with pytest.raises(ConfigError, match="unknown check 'spelling'"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("[verify]\ntests = 'tests/'\n", r"\[verify\].tests must be a list of strings"),
        ("[verify]\ntimeout = '90'\n", r"\[verify\].timeout must be an integer"),
        ("[verify]\ntimeout = 0\n", r"\[verify\].timeout must be greater than zero"),
        ("[verify]\ntimeout = true\n", r"\[verify\].timeout must be an integer"),
        ("[verify.profiles]\nedit = 'lint'\n", r"\[verify.profiles\].edit must be a list"),
    ],
)
def test_refuses_a_malformed_value(tmp_path: Path, body: str, message: str) -> None:
    _write_config(tmp_path, body)

    with pytest.raises(ConfigError, match=message):
        load_config(tmp_path)
```

`_write_config` ist die Hilfsfunktion, die `tests/test_config.py` bereits benutzt; falls sie dort noch nicht existiert, lege sie an:

```python
def _write_config(root: Path, body: str) -> None:
    path = root / CONFIG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -k "test_paths or timeout or profile" -v`
Expected: FAIL mit `AttributeError: 'Config' object has no attribute 'test_paths'`

- [ ] **Step 3: Write minimal implementation**

In `Config` drei Felder ergänzen:

```python
    test_paths: tuple[str, ...] = ()
    timeout: int = DEFAULT_TIMEOUT
    profiles: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
```

Oberhalb der Klasse:

```python
# Seconds per check command. The order of magnitude space's headless Godot
# suite needs; a project that runs longer says so rather than inheriting a
# limit that was chosen for somebody else's tools.
DEFAULT_TIMEOUT = 600
```

In `load_config`, nach der bestehenden `commands`-Schleife:

```python
    raw_tests = verify.get("tests", [])
    if not isinstance(raw_tests, list) or not all(isinstance(item, str) for item in raw_tests):
        raise ConfigError(f"{path}: [verify].tests must be a list of strings")

    timeout = verify.get("timeout", DEFAULT_TIMEOUT)
    # TOML's booleans are Python ints, and `timeout = true` is nobody's intent.
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        raise ConfigError(f"{path}: [verify].timeout must be an integer")
    if timeout <= 0:
        raise ConfigError(f"{path}: [verify].timeout must be greater than zero")

    profiles: dict[str, tuple[str, ...]] = {}
    for name, kinds in _table(verify, "profiles", path).items():
        if not isinstance(kinds, list) or not all(isinstance(kind, str) for kind in kinds):
            raise ConfigError(f"{path}: [verify.profiles].{name} must be a list of strings")
        for kind in kinds:
            # Caught here rather than at run time: a profile is read once, at
            # the start of a run, and a typo that only surfaces as a red check
            # halfway through looks like a finding rather than a mistake.
            if kind not in _CHECK_KINDS:
                raise ConfigError(f"{path}: [verify.profiles].{name} names unknown check {kind!r}")
        profiles[name] = tuple(kinds)
```

`_CHECK_KINDS` als Modulkonstante, **nicht** als Import aus `checks`: `config` liegt unter `checks` in der Abhängigkeitsrichtung, und `tests/test_module_boundary.py` nagelt das fest.

```python
# The check kinds a profile may name. Deliberately a copy of checks.KINDS and
# not an import: config sits below checks, and test_module_boundary keeps it
# there. test_config asserts the two lists stay equal.
_CHECK_KINDS = ("lint", "types", "test", "coverage")
```

Und im `return Config(...)` die drei Felder durchreichen:

```python
        test_paths=tuple(raw_tests),
        timeout=timeout,
        profiles=profiles,
```

- [ ] **Step 4: Den Kopie-Wächter dazuschreiben**

```python
def test_the_profile_kinds_match_the_check_kinds() -> None:
    # The copy in config._CHECK_KINDS exists to keep the dependency direction;
    # this is what stops it from drifting away from the original.
    from ultraloom.checks import KINDS

    assert config_module._CHECK_KINDS == KINDS
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Lint, types, coverage**

Run: `uvx ruff check . && uvx ruff format --check . && uvx mypy . && uv run coverage run -m pytest && uv run coverage report`
Expected: alles grün, Coverage 100 %

- [ ] **Step 7: Commit**

```bash
git add src/ultraloom/config.py tests/test_config.py
git commit -m "Read the test paths, the timeout and the check profiles"
```

---

### Task 2: Zeitgrenze für Prüfkommandos

**Files:**
- Modify: `src/ultraloom/checks.py:151-177` (`_run`)
- Test: `tests/test_checks.py`

**Interfaces:**
- Consumes: `Config.timeout` (Task 1).
- Produces: nichts Neues; `_run` liefert bei Überschreitung ein rotes `CheckResult`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_command_that_overruns_is_a_red_result(tmp_path: Path) -> None:
    config = Config(root=tmp_path, commands={"lint": _sleep_command(5)}, timeout=1)

    result = run_check("lint", config)

    assert not result.ok
    assert "timed out after 1s" in result.output
    assert result.kind == "lint"


def test_a_command_within_the_limit_is_untouched(tmp_path: Path) -> None:
    config = Config(root=tmp_path, commands={"lint": _sleep_command(0)}, timeout=30)

    assert run_check("lint", config).ok


def test_the_measuring_step_gets_the_limit_too(tmp_path: Path) -> None:
    # The measure step is a second process, so a shared budget would make its
    # limit depend on how long the first one took.
    command = Command("coverage", _argv(_sleep_command(0)), "test", measure=_argv(_sleep_command(5)))
    config = Config(root=tmp_path, timeout=1)

    result = _run_command(command, config)

    assert not result.ok
    assert "timed out after 1s" in result.output
```

Hilfen im Testmodul (`_sleep_command` baut ein plattformunabhängiges Kommando aus dem laufenden Interpreter, damit der Test auch auf Windows läuft):

```python
def _sleep_command(seconds: float) -> str:
    return shlex.join((sys.executable, "-c", f"import time; time.sleep({seconds})"))


def _argv(command: str) -> tuple[str, ...]:
    return tuple(shlex.split(command))
```

`_run_command` ist der neue, benannte Einstieg aus Step 3 — bis dahin schlägt der dritte Test mit `ImportError` fehl, was beabsichtigt ist.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_checks.py -k timed_out -v`
Expected: FAIL — der erste Test läuft fünf Sekunden und meldet dann `ok`

- [ ] **Step 3: Write minimal implementation**

`_run` bekommt die Grenze und einen zweiten `except`-Zweig:

```python
    try:
        completed = subprocess.run(
            argv,
            cwd=config.root,
            capture_output=True,
            text=True,
            check=False,
            timeout=config.timeout,
        )
    except subprocess.TimeoutExpired as expired:
        # A red result and not an exception: a check that never finished is a
        # check that failed, and giving it its own exception would buy the flow
        # a special path that ends in exactly the same place.
        partial = _decode(expired.stdout) + _decode(expired.stderr)
        detail = f"{shlex.join(argv)!r} timed out after {config.timeout}s"
        return CheckResult(kind, False, f"{detail}\n{partial}".rstrip(), source)
    except OSError as error:
        ...  # unverändert
```

`TimeoutExpired.stdout` ist `bytes | str | None` — capture_output plus text=True liefert `str`, aber der Typ der Ausnahme sagt das nicht:

```python
def _decode(captured: bytes | str | None) -> str:
    """What a timed-out process managed to write before it was killed.

    TimeoutExpired types its capture as bytes|str|None regardless of text=True,
    and the partial output is the only clue to *where* the tool hung.
    """
    if captured is None:
        return ""
    if isinstance(captured, bytes):
        return captured.decode("utf-8", errors="replace")
    return captured
```

Und `run_check` wird um den benannten Einstieg erweitert, den der dritte Test braucht:

```python
def run_check(kind: str, config: Config) -> CheckResult:
    """..."""  # docstring unverändert
    return _run_command(resolve_check(kind, config), config)


def _run_command(command: Command, config: Config) -> CheckResult:
    if command.measure:
        measured = _run(command.measure, command.kind, config, command.source)
        if not measured.ok:
            return measured
    return _run(command.argv, command.kind, config, command.source)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_checks.py -v`
Expected: PASS

- [ ] **Step 5: Lint, types, coverage**

Run: `uvx ruff check . && uvx ruff format --check . && uvx mypy . && uv run coverage run -m pytest && uv run coverage report`
Expected: alles grün

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/checks.py tests/test_checks.py
git commit -m "Stop a check that never finishes and report it as red"
```

---

### Task 3: Der Journal-Cache greift nur noch beim Nachvollziehen

**Files:**
- Modify: `src/ultraloom/runner.py` (`__init__`, `run`, `resume`, `_step`, `_why_it_looped`, Klassendocstring)
- Modify: `src/ultraloom/graph.py:21-35` (Docstring von `CodeNode.max_visits`)
- Modify: `README.md` (der Absatz über den Cache)
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: nichts.
- Produces: unverändertes öffentliches API. Verhalten: `run()` führt aus, `replay` und `resume` nutzen den Cache.

**Die genaue Regel** (feiner als Spec 3.1, weil `resume` ohne Antwort ebenfalls vom Cache lebt): der Cache ist aktiv, solange der Lauf *nachvollzieht*. Im Wiedergabe-Modus ist er es durchgehend. In `resume` ist er es ab dem Start und wird beim ersten Knoten abgeschaltet, für den kein Eintrag existiert — ab da läuft der Lauf vorwärts, und ein Zyklus, der danach einen früheren Knoten erneut betritt, führt ihn wirklich aus.

- [ ] **Step 1: Write the failing test**

```python
def test_a_second_run_over_the_same_journal_executes_again(tmp_path: Path) -> None:
    calls: list[int] = []
    graph: Graph[Counter] = Graph("count", start="tick")
    graph.add(CodeNode("tick", lambda data: (calls.append(1), {"n": data.n + 1})[1]))
    graph.edge("tick", END)
    journal = Journal(tmp_path / "run.jsonl")

    Runner(graph, journal).run(Counter(0))
    Runner(graph, journal).run(Counter(0))

    assert len(calls) == 2


def test_a_bounded_cycle_runs_every_pass_even_with_an_unchanging_payload(tmp_path: Path) -> None:
    calls: list[int] = []
    graph: Graph[Counter] = Graph("spin", start="tick")
    graph.add(CodeNode("tick", lambda _data: (calls.append(1), {})[1], max_visits=3))
    graph.edge("tick", "tick")
    result = Runner(graph, Journal(tmp_path / "run.jsonl")).run(Counter(0))

    assert result.status == "error"
    assert "max_visits" in (result.detail or "")
    # Three real executions, not one execution and two cache hits.
    assert len(calls) == 3


def test_resume_still_reconstructs_without_executing(tmp_path: Path) -> None:
    calls: list[str] = []
    graph, journal = _gate_flow(tmp_path, before=lambda: calls.append("before"))

    Runner(graph, journal).run(Payload(""))          # pauses at the gate
    calls.clear()
    result = Runner(graph, journal).resume(Payload(""), answer="yes")

    assert result.status == "done"
    assert calls == []  # the node before the gate was reconstructed, not re-run


def test_the_visit_limit_no_longer_blames_the_cache(tmp_path: Path) -> None:
    graph: Graph[Counter] = Graph("spin", start="tick")
    graph.add(CodeNode("tick", lambda _data: {}, max_visits=2))
    graph.edge("tick", "tick")

    result = Runner(graph, Journal(tmp_path / "run.jsonl")).run(Counter(0))

    assert "the journal served" not in (result.detail or "")
```

`_gate_flow` baut einen Ablauf mit **einem Knoten vor dem Gate** — die Fixture, die Teilprojekt 1 gefehlt hat (Spec 9.4). Das Gate sitzt bewusst *nicht* auf `graph.start`:

```python
def _gate_flow(tmp_path: Path, before: Callable[[], None]) -> tuple[Graph[Payload], Journal]:
    graph: Graph[Payload] = Graph("ask", start="prepare")
    graph.add(CodeNode("prepare", lambda _data: (before(), {"note": "prepared"})[1]))
    graph.add(GateNode("ask", question=lambda _d: "ok?", apply=lambda _d, answer: {"note": answer}))
    graph.add(CodeNode("finish", lambda _data: {}))
    graph.edge("prepare", "ask")
    graph.edge("ask", "finish")
    graph.edge("finish", END)
    return graph, Journal(tmp_path / "run.jsonl")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_runner.py -k "second_run or bounded_cycle or no_longer_blames" -v`
Expected: FAIL — `assert 1 == 2` beim ersten, `assert 1 == 3` beim zweiten

- [ ] **Step 3: Write minimal implementation**

In `__init__` hinter `self._replay = replay`:

```python
        # Whether this walk is retracing a journal that already exists. A replay
        # retraces from first node to last; a resume retraces only up to the
        # point where the old run stopped, and _step switches it off there. A
        # fresh run never retraces: a loop whose passes leave the payload alone
        # would otherwise be served its first pass forever and never check
        # anything a second time.
        self._retracing = replay
```

In `resume`, direkt vor jedem der beiden `self._walk(...)`-Aufrufe, die einen bestehenden Lauf fortsetzen:

```python
        self._retracing = True
```

(Beide Stellen: der Zweig `if answer is None` und der abschließende `return self._walk(..., _Answer(...))`.)

In `_step` die Cache-Abfrage bedingt machen:

```python
        if self._retracing:
            # The most recent *successful* entry, not the most recent one: both
            # the visit-limit path and a gate's pause write a non-ok entry under
            # the key of an entry that succeeded, and taking the latest match
            # would re-run a node that is already done.
            cached = self._journal.lookup(node.name, input_hash(node.name, state.data), outcome="ok")
            if cached is not None:
                return _Step(state.merged(cached.delta))
            if self._replay:
                # Not an error outcome: an error outcome would be offered the
                # node's on_error edge, and taking a fallback the original run
                # never took would make a broken replay look like a run that
                # handled a failure.
                raise ReplayGapError(f"node {node.name!r} is not in the journal")
            # A resume has caught up with where the old run stopped. Everything
            # from here is new work, including a second pass through a node the
            # journal already covers.
            self._retracing = False
```

`_why_it_looped` und sein Aufruf entfallen ersatzlos; die Zeile in `_walk` wird zu:

```python
                detail = str(error)
```

- [ ] **Step 4: Docstrings und README nachziehen**

Im `Runner`-Klassendocstring die Absätze über den Cache ersetzen:

```python
    """Walks a graph, journalling every step.

    A `run` executes every node it reaches. A `replay` executes none: it
    retraces the journal entry by entry. A `resume` retraces until it reaches
    the point where the earlier run stopped and executes from there — which is
    what makes answering a gate cheap without making a loop toothless.

    A node is recognised by its name and the input it saw, never by its
    implementation. Editing a node's body and replaying the same journal
    reproduces the old result for the new code. That is the price of the
    alternative: hashing a function body would throw a journal away on a
    cosmetic edit. Start a fresh run when a node changes.
    """
```

In `CodeNode` den zweiten Absatz ersetzen:

```python
    """A plain function. Costs no tokens and is reproducible byte for byte.

    `max_visits` raises the ceiling so this node may sit on a cycle. Every pass
    of a bounded cycle executes; the journal records each one under its own
    entry.
    """
```

In der README denselben Absatz suchen (`grep -n "served" README.md`) und auf dieselbe Aussage bringen.

- [ ] **Step 5: Den Golden-Journal-Test neu schreiben**

Der bestehende Golden-Journal-Test hält den Cache-Schlüssel fest und beschreibt damit jetzt etwas anderes. Finde ihn (`grep -rn "golden" tests/`) und schreibe ihn so um, dass er einen **Wiedergabe**-Lauf gegen ein aufgezeichnetes Journal stellt statt einen zweiten `run`. Der Vergleich bleibt Eintrag für Eintrag; nur der Anlass ändert sich.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -v`
Expected: PASS. Falls ein anderer Test auf dem alten Cache-Verhalten stand, ist das der Fund dieses Tasks — den Test auf die neue Regel bringen, nicht die Regel auf den Test.

- [ ] **Step 7: Lint, types, coverage**

Run: `uvx ruff check . && uvx ruff format --check . && uvx mypy . && uv run coverage run -m pytest && uv run coverage report`
Expected: alles grün

- [ ] **Step 8: Commit**

```bash
git add src/ultraloom/runner.py src/ultraloom/graph.py README.md tests/
git commit -m "Serve the journal cache only to a run that retraces one"
```

---

### Task 4: `FlowExit` — ein Ablauf nennt seinen Exit-Code

**Files:**
- Modify: `src/ultraloom/runner.py` (`Result`, `_step`, `_walk`)
- Modify: `src/ultraloom/cli.py:154-226` (`_flow_command`)
- Test: `tests/test_runner.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: nichts.
- Produces:
  - `class FlowExit(RuntimeError)` in `runner.py`, konstruiert als `FlowExit(code: int, message: str)`, mit Attribut `code: int`.
  - `Result.exit_code: int | None` — der Code, den ein `FlowExit` genannt hat, sonst `None`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_flow_exit_carries_its_code_into_the_result(tmp_path: Path) -> None:
    def refuse(_data: Payload) -> Delta:
        raise FlowExit(4, "the repairer changed a test file")

    graph: Graph[Payload] = Graph("stop", start="refuse")
    graph.add(CodeNode("refuse", refuse))
    graph.edge("refuse", END)

    result = Runner(graph, Journal(tmp_path / "run.jsonl")).run(Payload(""))

    assert result.status == "error"
    assert result.exit_code == 4
    assert result.detail == "the repairer changed a test file"


def test_an_ordinary_failure_names_no_code(tmp_path: Path) -> None:
    graph: Graph[Payload] = Graph("boom", start="boom")
    graph.add(CodeNode("boom", _raise(ValueError("no"))))
    graph.edge("boom", END)

    result = Runner(graph, Journal(tmp_path / "run.jsonl")).run(Payload(""))

    assert result.exit_code is None


def test_a_flow_exit_still_takes_the_error_edge(tmp_path: Path) -> None:
    # An exit code says how the *process* should end, not that the graph has
    # nothing left to do. A flow with a fallback keeps it.
    graph: Graph[Payload] = Graph("stop", start="refuse")
    graph.add(CodeNode("refuse", _raise(FlowExit(4, "nope"))))
    graph.add(CodeNode("cleanup", lambda _data: {"note": "cleaned"}))
    graph.edge("refuse", "cleanup", on_error=True)
    graph.edge("refuse", END)
    graph.edge("cleanup", END)

    result = Runner(graph, Journal(tmp_path / "run.jsonl")).run(Payload(""))

    assert result.status == "done"
```

Und für die CLI:

```python
def test_the_cli_returns_the_code_the_flow_named(tmp_path: Path, capsys) -> None:
    _write_flow(tmp_path, "stopper", _FLOW_THAT_EXITS_WITH_4)

    assert main(["run", "stopper", "--root", str(tmp_path), "--no-model"]) == 4
```

```python
_FLOW_THAT_EXITS_WITH_4 = """
from dataclasses import dataclass

from ultraloom.graph import END, CodeNode, Graph
from ultraloom.runner import FlowExit


@dataclass(frozen=True, slots=True)
class Payload:
    note: str = ""


def refuse(_data):
    raise FlowExit(4, "refused on purpose")


flow = Graph("stopper", start="refuse")
flow.add(CodeNode("refuse", refuse))
flow.edge("refuse", END)
initial = Payload()
"""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_runner.py -k flow_exit -v`
Expected: FAIL mit `ImportError: cannot import name 'FlowExit'`

- [ ] **Step 3: Write minimal implementation**

In `runner.py`, neben `ReplayGapError`:

```python
class FlowExit(RuntimeError):
    """Raised by a node that wants the process to end with a named code.

    A flow that has more than one way of failing needs more than one way of
    saying so: a hook cannot tell "the checks stayed red" from "the repairer
    touched a test file" if both arrive as 1. The code travels on the Result;
    it never reaches into sys.exit from inside a node.
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
```

`Result` bekommt ein Feld:

```python
    exit_code: int | None = None
```

In `_step`, im `except Exception`-Zweig, den Code mitnehmen:

```python
        except Exception as error:
            seconds = self._clock() - started
            self._write(node, state, {}, "error", 0, seconds, str(error))
            code = error.code if isinstance(error, FlowExit) else None
            return _Step(state, failed=True, detail=str(error), exit_code=code)
```

`_Step` bekommt dasselbe Feld (`exit_code: int | None = None`), und in `_walk` wird es in das Ergebnis gereicht:

```python
            if outcome.failed:
                fallback = self._graph.error_name(name)
                if fallback is None:
                    return Result("error", outcome.state, name, None, outcome.detail, outcome.exit_code)
                state, name = outcome.state, fallback
                continue
```

In `cli.py`, am Ende von `_flow_command`:

```python
    if result.status == "paused":
        return _EXIT_PAUSED
    if result.status == "done":
        return _EXIT_OK
    # A flow may name its own code; without one, a failure is a failure.
    return result.exit_code if result.exit_code is not None else _EXIT_FAIL
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_runner.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Lint, types, coverage**

Run: `uvx ruff check . && uvx ruff format --check . && uvx mypy . && uv run coverage run -m pytest && uv run coverage report`
Expected: alles grün

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/runner.py src/ultraloom/cli.py tests/
git commit -m "Let a flow name the exit code its failure deserves"
```

---

### Task 5: `FlowContext` und `build()` — ein Ablauf bekommt Parameter

**Files:**
- Modify: `src/ultraloom/discovery.py`
- Modify: `src/ultraloom/cli.py:154-226` (`_flow_command`)
- Test: `tests/test_discovery.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `Config` (Task 1).
- Produces:
  - `@dataclass(frozen=True, slots=True) class FlowContext: root: Path; config: Config; options: Mapping[str, str]`
  - `find_flow(name: str, root: Path, context: FlowContext | None = None) -> LoadedFlow` — ruft `module.build(context)`, wenn das Modul `build` definiert, sonst weiter über `flow`/`initial`.

- [ ] **Step 1: Write the failing test**

```python
_PARAMETERISED_FLOW = """
from dataclasses import dataclass

from ultraloom.discovery import LoadedFlow
from ultraloom.graph import END, CodeNode, Graph


@dataclass(frozen=True, slots=True)
class Payload:
    note: str = ""


def build(context):
    note = context.options["note"]
    flow = Graph("parameterised", start="only")
    flow.add(CodeNode("only", lambda _data: {"note": note}))
    flow.edge("only", END)
    return LoadedFlow(flow, Payload())
"""


def test_build_receives_the_context(tmp_path: Path) -> None:
    _write_flow(tmp_path, "parameterised", _PARAMETERISED_FLOW)
    context = FlowContext(root=tmp_path, config=Config(root=tmp_path), options={"note": "hello"})

    loaded = find_flow("parameterised", tmp_path, context)

    assert loaded.graph.name == "parameterised"


def test_a_flow_with_build_and_no_context_says_so(tmp_path: Path) -> None:
    _write_flow(tmp_path, "parameterised", _PARAMETERISED_FLOW)

    with pytest.raises(FlowLoadError, match="needs a context"):
        find_flow("parameterised", tmp_path)


def test_a_module_defining_both_build_and_flow_is_refused(tmp_path: Path) -> None:
    _write_flow(tmp_path, "both", _PARAMETERISED_FLOW + "\nflow = None\n")
    context = FlowContext(root=tmp_path, config=Config(root=tmp_path), options={})

    with pytest.raises(FlowLoadError, match="defines both"):
        find_flow("both", tmp_path, context)


def test_build_returning_the_wrong_type_is_refused(tmp_path: Path) -> None:
    _write_flow(tmp_path, "wrong", "def build(context):\n    return 'nope'\n")
    context = FlowContext(root=tmp_path, config=Config(root=tmp_path), options={})

    with pytest.raises(FlowLoadError, match="must return a LoadedFlow"):
        find_flow("wrong", tmp_path, context)


def test_a_plain_flow_module_still_loads_without_a_context(tmp_path: Path) -> None:
    _write_flow(tmp_path, "plain", _PLAIN_FLOW)  # the existing fixture

    assert find_flow("plain", tmp_path).graph.name == "plain"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_discovery.py -k build -v`
Expected: FAIL mit `ImportError: cannot import name 'FlowContext'`

- [ ] **Step 3: Write minimal implementation**

In `discovery.py`, oberhalb von `LoadedFlow`:

```python
@dataclass(frozen=True, slots=True)
class FlowContext:
    """What a flow needs to know about the run it is being built for.

    A bundled flow lives in ultraloom and knows nothing about the project it
    runs in: which tools check it, where its tests are, what the caller asked
    for on the command line. All three arrive here rather than through import
    time magic, so a flow stays a function of its inputs.
    """

    root: Path
    config: Config
    options: Mapping[str, str] = field(default_factory=dict)
```

In `find_flow` die Signatur erweitern und nach `exec_module` den neuen Zweig einziehen:

```python
    builder = getattr(module, "build", _ABSENT)
    has_flow = getattr(module, "flow", _ABSENT) is not _ABSENT
    if builder is not _ABSENT:
        if has_flow:
            # Both would leave the reader guessing which one runs, and the
            # answer would be an implementation detail of this function.
            raise FlowLoadError(f"{path}: defines both `build` and `flow`; keep one")
        if context is None:
            raise FlowLoadError(
                f"{path}: defines `build`, so it needs a context; "
                f"this caller loaded the flow without one"
            )
        if not callable(builder):
            raise FlowLoadError(f"{path}: `build` must be callable, got {type(builder).__name__}")
        try:
            built = builder(context)
        except Exception as error:
            raise FlowLoadError(f"{path}: build failed: {error}") from error
        if not isinstance(built, LoadedFlow):
            raise FlowLoadError(
                f"{path}: `build` must return a LoadedFlow, got {type(built).__name__}"
            )
        return built
```

Der bestehende `flow`/`initial`-Pfad bleibt darunter unverändert.

- [ ] **Step 4: Die CLI reicht den Kontext durch**

In `_flow_command`, den `find_flow`-Aufruf ersetzen:

```python
    context = FlowContext(root=root, config=config, options=_flow_options(args))
    try:
        loaded = find_flow(flow_name, root, context)
```

`_flow_options` liefert vorerst ein leeres Mapping und wird in Task 11 gefüllt:

```python
def _flow_options(args: argparse.Namespace) -> dict[str, str]:
    """The command line options a flow may read, as plain strings.

    Strings and not parsed values: the CLI has no business knowing what a flow
    means by "checks". Every flow narrows what it reads, and reports its own
    error when it cannot.
    """
    return {
        name: str(value)
        for name in ("checks", "max_rounds")
        if (value := getattr(args, name, None)) is not None
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_discovery.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 6: Lint, types, coverage**

Run: `uvx ruff check . && uvx ruff format --check . && uvx mypy . && uv run coverage run -m pytest && uv run coverage report`
Expected: alles grün

- [ ] **Step 7: Commit**

```bash
git add src/ultraloom/discovery.py src/ultraloom/cli.py tests/
git commit -m "Build a flow from a context so it can read the project's config"
```

---

### Task 6: Mitgelieferte Abläufe werden gefunden

**Files:**
- Modify: `src/ultraloom/discovery.py`
- Create: `src/ultraloom/flows/__init__.py` (bleibt leer, ist aber ab jetzt ein Suchort)
- Test: `tests/test_discovery.py`

**Interfaces:**
- Consumes: Task 5.
- Produces:
  - `list_flows(root: Path) -> tuple[FlowEntry, ...]` mit `FlowEntry(name: str, origin: str, problem: str | None)`; `origin` ist `"project"` oder `"bundled"`.
  - `find_flow` sucht erst im Projekt, dann im Paket.

**Achtung:** `list_flows` ändert seinen Rückgabetyp. Die eine bestehende Verwendung steht in `find_flow`s Fehlermeldung; sie wird hier mitgezogen.

- [ ] **Step 1: Write the failing test**

```python
def test_a_bundled_flow_is_found_without_a_project_directory(tmp_path: Path) -> None:
    names = [entry.name for entry in list_flows(tmp_path)]

    assert "verify_until_green" in names


def test_a_project_flow_shadows_a_bundled_one_of_the_same_name(tmp_path: Path) -> None:
    _write_flow(tmp_path, "verify_until_green", _PLAIN_FLOW)

    entries = {entry.name: entry for entry in list_flows(tmp_path)}

    assert entries["verify_until_green"].origin == "project"
    assert find_flow("verify_until_green", tmp_path).graph.name == "plain"


def test_a_file_that_cannot_be_a_flow_is_listed_with_its_reason(tmp_path: Path) -> None:
    directory = tmp_path / FLOW_DIR
    directory.mkdir(parents=True)
    (directory / "my-flow.py").write_text("", encoding="utf-8")

    entry = next(entry for entry in list_flows(tmp_path) if entry.name == "my-flow")

    assert entry.problem is not None
    assert "identifier" in entry.problem


def test_the_available_list_in_a_not_found_error_names_the_origins(tmp_path: Path) -> None:
    with pytest.raises(FlowNotFoundError, match=r"verify_until_green \(bundled\)"):
        find_flow("absent", tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_discovery.py -k bundled -v`
Expected: FAIL — `list_flows` liefert `tuple[str, ...]` und findet nichts

- [ ] **Step 3: Write minimal implementation**

```python
BUNDLED_PACKAGE = "ultraloom.flows"


@dataclass(frozen=True, slots=True)
class FlowEntry:
    """A flow the project could run, or a file that wanted to be one.

    A file with a `problem` is listed rather than hidden: silence about
    `my-flow.py` sends its author looking for a typo in the command line.
    """

    name: str
    origin: str
    problem: str | None = None


def _bundled_dir() -> Path:
    # importlib.resources would be the portable answer for a zipped install;
    # ultraloom is installed from source and `find_flow` needs a real path to
    # hand to spec_from_file_location either way.
    return Path(__file__).resolve().parent / "flows"


def _entries_in(directory: Path, origin: str) -> list[FlowEntry]:
    if not directory.is_dir():
        return []
    entries = []
    for path in sorted(directory.glob("*.py")):
        if path.stem == "__init__":
            continue
        problem = (
            None
            if path.stem.isidentifier()
            else f"{path.name} cannot be loaded: a flow name must be a Python identifier"
        )
        entries.append(FlowEntry(path.stem, origin, problem))
    return entries


def list_flows(root: Path) -> tuple[FlowEntry, ...]:
    """Every flow this project could run, project ones first, sorted by name."""
    project = _entries_in(root / FLOW_DIR, "project")
    taken = {entry.name for entry in project}
    # A project may replace a bundled flow by name. That is the whole mechanism
    # for "ultraloom's version is nearly right"; there is no override syntax.
    bundled = [entry for entry in _entries_in(_bundled_dir(), "bundled") if entry.name not in taken]
    return tuple(sorted(project + bundled, key=lambda entry: entry.name))


def _path_of(name: str, root: Path) -> Path | None:
    for directory in (root / FLOW_DIR, _bundled_dir()):
        candidate = directory / f"{name}.py"
        if candidate.is_file():
            return candidate
    return None
```

In `find_flow` die Pfadsuche ersetzen:

```python
    path = _path_of(name, root)
    if path is None:
        available = (
            ", ".join(f"{entry.name} ({entry.origin})" for entry in list_flows(root)) or "none"
        )
        raise FlowNotFoundError(f"no flow {name!r}; available: {available}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_discovery.py -v`
Expected: `test_a_bundled_flow_is_found_without_a_project_directory` schlägt weiter fehl — der Ablauf entsteht erst in Task 10. Markiere ihn bis dahin:

```python
@pytest.mark.xfail(reason="verify_until_green arrives in task 10", strict=True)
```

Task 10 entfernt die Markierung; `strict=True` sorgt dafür, dass das Vergessen auffällt.

- [ ] **Step 5: Lint, types, coverage**

Run: `uvx ruff check . && uvx ruff format --check . && uvx mypy . && uv run coverage run -m pytest && uv run coverage report`
Expected: alles grün

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/discovery.py src/ultraloom/flows/__init__.py tests/test_discovery.py
git commit -m "Find the flows ultraloom ships beside the ones a project keeps"
```

---

### Task 7: `VerifyState` und der Knoten `check`

**Files:**
- Create: `src/ultraloom/flows/verify_until_green.py`
- Create: `tests/flows/__init__.py`, `tests/flows/test_verify_until_green.py`

**Interfaces:**
- Consumes: `Config` (Task 1), `checks.run_all`/`run_check`.
- Produces:
  - `@dataclass(frozen=True, slots=True) class VerifyState` mit den Feldern aus Spec 4.1.
  - `UNFIXABLE: tuple[str, ...] = ("coverage",)`
  - `make_check(config: Config, runner: CheckRunner) -> Callable[[VerifyState], Delta]`, wobei `type CheckRunner = Callable[[str, Config], CheckResult]`.

Der Prüfläufer wird injiziert, damit die Ablauftests keine echten Werkzeuge starten. Der Vorgabewert ist `checks.run_check`.

- [ ] **Step 1: Write the failing test**

```python
def test_all_green_leaves_nothing_failing() -> None:
    step = make_check(_config(), _runner({"lint": True, "types": True}))

    delta = step(VerifyState(kinds=("lint", "types")))

    assert delta["failing"] == ()
    assert delta["unfixable"] == ()
    assert delta["rounds"] == 1


def test_a_red_check_is_named_and_rendered() -> None:
    step = make_check(_config(), _runner({"lint": False, "types": True}))

    delta = step(VerifyState(kinds=("lint", "types")))

    assert delta["failing"] == ("lint",)
    assert "lint" in str(delta["report"])
    assert "types" not in str(delta["report"])  # a green check is not worth a model's tokens


def test_coverage_is_red_but_out_of_the_repairers_reach() -> None:
    step = make_check(_config(), _runner({"coverage": False}))

    delta = step(VerifyState(kinds=("coverage",)))

    assert delta["failing"] == ("coverage",)
    assert delta["unfixable"] == ("coverage",)


def test_the_kinds_are_run_in_the_order_the_state_names() -> None:
    seen: list[str] = []

    def runner(kind: str, _config: Config) -> CheckResult:
        seen.append(kind)
        return CheckResult(kind, True, "", "test")

    make_check(_config(), runner)(VerifyState(kinds=("types", "lint")))

    assert sorted(seen) == ["lint", "types"]  # concurrent, so only the set is fixed


def test_rounds_counts_up_from_where_the_state_stood() -> None:
    step = make_check(_config(), _runner({"lint": True}))

    assert step(VerifyState(kinds=("lint",), rounds=2))["rounds"] == 3
```

Hilfen:

```python
def _config(**overrides: object) -> Config:
    defaults: dict[str, object] = {"root": Path("."), "test_paths": ("tests/",)}
    return Config(**{**defaults, "root": Path("."), **overrides})  # type: ignore[arg-type]  # Config is a dataclass; the kwargs are its fields


def _runner(outcomes: Mapping[str, bool]) -> CheckRunner:
    def run(kind: str, _config: Config) -> CheckResult:
        ok = outcomes[kind]
        return CheckResult(kind, ok, "" if ok else f"{kind} is unhappy", "test")

    return run
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/flows/test_verify_until_green.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.flows.verify_until_green'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Check, repair, check again — until it is green or honestly red.

The first flow ultraloom ships. It knows nothing about any one project: which
tools check it and where its tests live both arrive through Config, which is
what lets the same flow run in a Python package and in a Godot game.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from ultraloom.checks import CheckResult, run_check
from ultraloom.config import Config
from ultraloom.state import Delta

type CheckRunner = Callable[[str, Config], CheckResult]

# Red checks the repairer is not allowed to close. Closing a coverage gap means
# writing tests, and writing tests is exactly what the guard forbids -- so a
# repair pass for it would be an agent looking for a way around a rule.
UNFIXABLE: tuple[str, ...] = ("coverage",)


@dataclass(frozen=True, slots=True)
class VerifyState:
    """What one verification run knows about itself."""

    kinds: tuple[str, ...] = ()
    report: str = ""
    failing: tuple[str, ...] = ()
    unfixable: tuple[str, ...] = ()
    touched: tuple[str, ...] = ()
    rounds: int = 0


def make_check(config: Config, runner: CheckRunner = run_check) -> Callable[[VerifyState], Delta]:
    """The `check` node, bound to one project's configuration.

    The runner is a parameter so the flow's own tests never start a real tool:
    a test that shells out to ruff measures ruff.
    """

    def check(state: VerifyState) -> Delta:
        # Concurrent for the same reason checks.run_all is: subprocess.run
        # releases the GIL while it waits. Not run_all itself, because that one
        # runs every kind and this node runs the kinds the caller asked for.
        with ThreadPoolExecutor(max_workers=max(1, len(state.kinds))) as pool:
            results = tuple(pool.map(lambda kind: runner(kind, config), state.kinds))

        red = tuple(result for result in results if not result.ok)
        return {
            "failing": tuple(result.kind for result in red),
            "unfixable": tuple(result.kind for result in red if result.kind in UNFIXABLE),
            "report": _render(red),
            "rounds": state.rounds + 1,
        }

    return check


def _render(red: tuple[CheckResult, ...]) -> str:
    """The failing checks, for a human and for a model.

    Only the failing ones: a green check's output is noise in a terminal and
    paid-for noise in a prompt.
    """
    return "\n\n".join(f"## {result.kind} ({result.source})\n{result.output}" for result in red)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/flows/test_verify_until_green.py -v`
Expected: PASS

- [ ] **Step 5: Lint, types, coverage**

Run: `uvx ruff check . && uvx ruff format --check . && uvx mypy . && uv run coverage run -m pytest && uv run coverage report`
Expected: alles grün

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/flows/verify_until_green.py tests/flows/
git commit -m "Add the verify state and the check node"
```

---

### Task 8: Der Knoten `repair`

**Files:**
- Modify: `src/ultraloom/flows/verify_until_green.py`
- Test: `tests/flows/test_verify_until_green.py`

**Interfaces:**
- Consumes: Task 7.
- Produces:
  - `@dataclass(frozen=True, slots=True) class RepairResult: summary: str; changed: bool = False`
  - `REPAIR_PROMPT: str`
  - `make_repair() -> AgentNode[VerifyState]`

- [ ] **Step 1: Write the failing test**

```python
def test_the_prompt_carries_the_report_and_the_forbidden_paths() -> None:
    node = make_repair(test_paths=("tests/", "conftest.py"))
    state = VerifyState(kinds=("lint",), failing=("lint",), report="## lint\nE501 too long")

    prompt = node.prompt(state)

    assert "E501 too long" in prompt
    assert "tests/" in prompt
    assert "conftest.py" in prompt


def test_the_node_may_edit_and_thinks_hard() -> None:
    node = make_repair(test_paths=("tests/",))

    assert node.tools == "edit"
    assert node.effort == "high"
    assert node.schema is RepairResult


def test_the_reply_becomes_the_summary_of_the_pass() -> None:
    node = make_repair(test_paths=("tests/",))

    delta = node.apply(VerifyState(), RepairResult(summary="shortened the line", changed=True))

    assert delta == {"report": "shortened the line"}


def test_a_reply_of_the_wrong_type_is_refused() -> None:
    node = make_repair(test_paths=("tests/",))

    with pytest.raises(TypeError, match="RepairResult"):
        node.apply(VerifyState(), "I fixed it")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/flows/test_verify_until_green.py -k repair -v`
Expected: FAIL mit `NameError: name 'make_repair' is not defined`

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True, slots=True)
class RepairResult:
    """What the repairer says it did.

    Scalars only, because that is what a model adapter can describe as a JSON
    schema. `changed` is the model's own claim and is never trusted on its own:
    the guard node reads the working tree.
    """

    summary: str
    changed: bool = False


REPAIR_PROMPT = """\
The project's checks are failing. Fix the source so they pass.

{report}

Rules:
- Do NOT edit, weaken, skip or delete anything under: {forbidden}
  A failing test is a finding about the source, not a problem with the test.
- Change as little as possible. A narrow fix beats a rewrite.
- If a check fails for a reason you cannot fix in the source, say so in the
  summary and change nothing.

Answer with a summary of what you changed and whether you changed anything.
"""


def make_repair(test_paths: tuple[str, ...]) -> AgentNode[VerifyState]:
    """The `repair` node, told which paths it must keep its hands off."""
    forbidden = ", ".join(test_paths)

    def apply(_state: VerifyState, reply: object) -> Delta:
        if not isinstance(reply, RepairResult):
            # The runner types the reply as `object`, so this is the one place
            # a wrong shape can still be caught before it reaches the journal.
            raise TypeError(f"expected a RepairResult, got {type(reply).__name__}")
        # The summary replaces the report on purpose: the next `check` pass
        # overwrites it anyway, and carrying the old failures forward would let
        # a stale report reach the next prompt if that pass ever fails to run.
        return {"report": reply.summary}

    return AgentNode(
        "repair",
        prompt=lambda state: REPAIR_PROMPT.format(report=state.report, forbidden=forbidden),
        schema=RepairResult,
        apply=apply,
        tools="edit",
        effort="high",
        max_visits=5,
    )
```

Import ergänzen: `from ultraloom.graph import AgentNode`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/flows/test_verify_until_green.py -v`
Expected: PASS

- [ ] **Step 5: Lint, types, coverage**

Run: `uvx ruff check . && uvx ruff format --check . && uvx mypy . && uv run coverage run -m pytest && uv run coverage report`
Expected: alles grün

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/flows/verify_until_green.py tests/flows/test_verify_until_green.py
git commit -m "Add the repair node and the shape of its reply"
```

---

### Task 9: Der Knoten `guard` — die Testsperre

**Files:**
- Modify: `src/ultraloom/flows/verify_until_green.py`
- Test: `tests/flows/test_verify_until_green.py`

**Interfaces:**
- Consumes: Task 7, `FlowExit` (Task 4).
- Produces:
  - `type Differ = Callable[[Path], tuple[str, ...]]`
  - `changed_files(root: Path) -> tuple[str, ...]` — die Vorgabe, über `git status --porcelain -z -uall`
  - `make_guard(root: Path, test_paths: tuple[str, ...], differ: Differ = changed_files) -> Callable[[VerifyState], Delta]`

`git status --porcelain` und nicht `git diff`: der Agent legt womöglich eine neue Datei an, und eine ungetrackte Datei taucht in `git diff` nicht auf. `-z` und `-uall` aus demselben Grund wie in space' `quality.py`: ein Pfad mit Nicht-ASCII kommt sonst zitiert zurück, und ein ganzes untracked-Verzeichnis kollabiert sonst zu einem Eintrag.

- [ ] **Step 1: Write the failing test**

```python
def test_a_source_only_change_passes_and_is_recorded() -> None:
    guard = make_guard(Path("."), ("tests/",), differ=lambda _root: ("src/ultraloom/cli.py",))

    delta = guard(VerifyState())

    assert delta["touched"] == ("src/ultraloom/cli.py",)


def test_a_touched_test_file_stops_the_run_with_code_4() -> None:
    guard = make_guard(Path("."), ("tests/",), differ=lambda _root: ("tests/test_cli.py",))

    with pytest.raises(FlowExit) as raised:
        guard(VerifyState())

    assert raised.value.code == 4
    assert "tests/test_cli.py" in str(raised.value)


def test_a_prefix_match_is_not_a_path_match() -> None:
    # "tests/" must not forgive "tests_helper.py" and must not catch "testsuite/".
    guard = make_guard(Path("."), ("tests/",), differ=lambda _root: ("testsuite/thing.py",))

    assert guard(VerifyState())["touched"] == ("testsuite/thing.py",)


def test_a_single_file_may_be_protected() -> None:
    guard = make_guard(Path("."), ("conftest.py",), differ=lambda _root: ("conftest.py",))

    with pytest.raises(FlowExit):
        guard(VerifyState())


def test_nothing_changed_is_an_empty_record_not_a_failure() -> None:
    guard = make_guard(Path("."), ("tests/",), differ=lambda _root: ())

    assert guard(VerifyState())["touched"] == ()


def test_changed_files_reads_git(tmp_path: Path) -> None:
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")

    assert changed_files(tmp_path) == ("a.py",)


def test_changed_files_survives_a_directory_that_is_no_repository(tmp_path: Path) -> None:
    # Not a crash and not silence: an empty answer here would let the guard
    # wave through a repair pass it could not see.
    with pytest.raises(FlowExit) as raised:
        changed_files(tmp_path / "nowhere")

    assert raised.value.code == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/flows/test_verify_until_green.py -k guard -v`
Expected: FAIL mit `NameError: name 'make_guard' is not defined`

- [ ] **Step 3: Write minimal implementation**

```python
type Differ = Callable[[Path], tuple[str, ...]]

_EXIT_TOUCHED_A_TEST = 4


def changed_files(root: Path) -> tuple[str, ...]:
    """Every path git reports as changed, added or untracked below `root`.

    `status` and not `diff`, because a repairer may add a file, and an
    untracked file is invisible to `diff`. `-z` because a path holding
    non-ASCII comes back quoted otherwise, and `-uall` because the default
    collapses a whole untracked directory into one entry that is not a path to
    any file.
    """
    result = subprocess.run(
        ("git", "status", "--porcelain", "-z", "-uall"),
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        # A guard that cannot see the working tree must stop the run. Reading
        # an unanswerable question as "nothing changed" would disable exactly
        # the rule this node exists for.
        raise FlowExit(
            _EXIT_TOUCHED_A_TEST,
            f"cannot inspect the working tree in {root}: {result.stderr.strip()}",
        )
    # Each entry is "XY path"; a rename adds its original path as its own entry.
    return tuple(entry[3:] for entry in result.stdout.split("\0") if len(entry) > 3)


def _is_protected(path: str, test_paths: tuple[str, ...]) -> bool:
    candidate = PurePosixPath(path)
    for protected in test_paths:
        target = PurePosixPath(protected)
        if candidate == target or target in candidate.parents:
            return True
    return False


def make_guard(
    root: Path, test_paths: tuple[str, ...], differ: Differ = changed_files
) -> Callable[[VerifyState], Delta]:
    """The `guard` node: what the repairer did, measured against what it may do.

    In a node and not in the tool profile: a profile is a coarse permission and
    knows no paths, and which paths hold tests is something only the project
    knows. Reading the working tree afterwards also catches a change made by a
    detour the profile never named.
    """

    def guard(_state: VerifyState) -> Delta:
        touched = differ(root)
        forbidden = tuple(path for path in touched if _is_protected(path, test_paths))
        if forbidden:
            raise FlowExit(
                _EXIT_TOUCHED_A_TEST,
                "the repairer changed protected files: " + ", ".join(forbidden),
            )
        return {"touched": touched}

    return guard
```

Importe ergänzen: `subprocess`, `from pathlib import Path, PurePosixPath`, `from ultraloom.runner import FlowExit`.

**Achtung, Modulgrenze:** `flows/` importiert aus `runner`. Prüfe `tests/test_module_boundary.py` und trage die Richtung dort ein, falls sie eine Liste erlaubter Kanten führt.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/flows/test_verify_until_green.py -v`
Expected: PASS

- [ ] **Step 5: Lint, types, coverage**

Run: `uvx ruff check . && uvx ruff format --check . && uvx mypy . && uv run coverage run -m pytest && uv run coverage report`
Expected: alles grün

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/flows/verify_until_green.py tests/
git commit -m "Guard the test files against the repairer"
```

---

### Task 10: Der Graph, `report_red` und `build`

**Files:**
- Modify: `src/ultraloom/flows/verify_until_green.py`
- Modify: `tests/test_discovery.py` (die `xfail`-Markierung aus Task 6 entfernen)
- Test: `tests/flows/test_verify_until_green.py`

**Interfaces:**
- Consumes: Tasks 1, 4, 5, 7, 8, 9.
- Produces:
  - `stagnated(state: VerifyState, previous: tuple[str, ...]) -> bool` — als Teil von `make_check`s Delta, siehe unten
  - `build(context: FlowContext) -> LoadedFlow`

**Stagnation braucht ein Gedächtnis.** `VerifyState` bekommt dafür ein siebtes Feld, `previous_failing: tuple[str, ...]`, das `check` vor dem Überschreiben von `failing` sichert. Ohne das kann eine Kantenbedingung, die nur den aktuellen Zustand sieht, „unverändert" nicht feststellen.

- [ ] **Step 1: Write the failing test**

```python
def test_a_green_first_pass_ends_the_run(tmp_path: Path) -> None:
    result = _run_flow(tmp_path, outcomes=[{"lint": True}])

    assert result.status == "done"
    assert result.state.data.rounds == 1


def test_red_then_repaired_then_green(tmp_path: Path) -> None:
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": False}, {"lint": True}],
        repairs=[RepairResult("fixed the line", changed=True)],
        touched=[("src/thing.py",)],
    )

    assert result.status == "done"
    assert result.state.data.rounds == 2


def test_two_identical_red_passes_without_a_change_stop_the_run(tmp_path: Path) -> None:
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": False}, {"lint": False}],
        repairs=[RepairResult("I could not fix it", changed=False)],
        touched=[()],
    )

    assert result.status == "error"
    assert result.exit_code == 1
    assert "stagnated" in (result.detail or "")


def test_only_coverage_red_never_calls_the_model(tmp_path: Path) -> None:
    calls: list[str] = []
    result = _run_flow(
        tmp_path,
        outcomes=[{"coverage": False}],
        kinds=("coverage",),
        on_agent=calls.append,
    )

    assert result.exit_code == 1
    assert "coverage" in (result.detail or "")
    assert calls == []


def test_a_touched_test_file_ends_the_run_with_four(tmp_path: Path) -> None:
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": False}],
        repairs=[RepairResult("rewrote the test", changed=True)],
        touched=[("tests/test_thing.py",)],
    )

    assert result.exit_code == 4


def test_the_round_ceiling_ends_the_run(tmp_path: Path) -> None:
    # Five repairs that each change something and never help.
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": False}] * 7,
        repairs=[RepairResult(f"attempt {n}", changed=True) for n in range(6)],
        touched=[(f"src/attempt_{n}.py",) for n in range(6)],
        max_rounds=5,
    )

    assert result.exit_code == 1
    assert result.state.data.rounds == 6  # five repairs, six checks


def test_a_state_that_starts_mid_run_is_not_a_special_case(tmp_path: Path) -> None:
    # Deliberately not the shape every other fixture here has: the plan's own
    # fixtures are suggestions, and a run that starts at rounds=2 is the case a
    # resume produces.
    result = _run_flow(
        tmp_path,
        outcomes=[{"lint": True}],
        initial=VerifyState(kinds=("lint",), rounds=2, previous_failing=("lint",)),
    )

    assert result.status == "done"
    assert result.state.data.rounds == 3


def test_a_missing_test_paths_setting_refuses_to_start(tmp_path: Path) -> None:
    context = FlowContext(root=tmp_path, config=Config(root=tmp_path), options={})

    with pytest.raises(ValueError, match=r"\[verify\].tests"):
        build(context)


def test_the_checks_option_may_name_a_profile(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",), profiles={"edit": ("lint", "types")})
    context = FlowContext(root=tmp_path, config=config, options={"checks": "edit"})

    loaded = build(context)

    assert loaded.initial.kinds == ("lint", "types")


def test_the_checks_option_may_be_a_list(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",))
    context = FlowContext(root=tmp_path, config=config, options={"checks": "lint,types"})

    assert build(context).initial.kinds == ("lint", "types")


def test_an_unknown_check_name_is_refused_before_the_run(tmp_path: Path) -> None:
    config = Config(root=tmp_path, test_paths=("tests/",))
    context = FlowContext(root=tmp_path, config=config, options={"checks": "spelling"})

    with pytest.raises(ValueError, match="unknown check 'spelling'"):
        build(context)
```

`_run_flow` baut den Graphen mit eingesetzten Attrappen und lässt einen echten `Runner` darüber laufen — der Ablauf wird als Ablauf geprüft, nicht knotenweise:

```python
def _run_flow(
    tmp_path: Path,
    outcomes: list[Mapping[str, bool]],
    repairs: list[RepairResult] | None = None,
    touched: list[tuple[str, ...]] | None = None,
    kinds: tuple[str, ...] = ("lint",),
    max_rounds: int = 5,
    initial: VerifyState | None = None,
    on_agent: Callable[[str], None] = lambda _prompt: None,
) -> Result[VerifyState]:
    passes = iter(outcomes)
    diffs = iter(touched or [])

    def runner(kind: str, _config: Config) -> CheckResult:
        ...  # reads the pass that _next_pass fixed for this round

    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=runner,
        differ=lambda _root: next(diffs, ()),
        max_rounds=max_rounds,
    )
    model = _ScriptedModel(repairs or [], on_agent)
    state = initial if initial is not None else VerifyState(kinds=kinds)
    return Runner(graph, Journal(tmp_path / "run.jsonl"), model=model).run(state)
```

Die Prüfläufer-Attrappe muss **je Runde** dieselbe Antwort geben, egal in welcher Reihenfolge die nebenläufigen Aufrufe eintreffen. Deshalb wird der Durchlauf beim ersten Aufruf einer Runde festgelegt:

```python
class _Passes:
    """One outcome mapping per round, handed to every kind in that round.

    The check node runs its kinds concurrently, so a plain iterator would give
    the two kinds of one round two different rounds' answers.
    """

    def __init__(self, outcomes: list[Mapping[str, bool]]) -> None:
        self._outcomes = outcomes
        self._round = -1
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def outcome(self, kind: str) -> bool:
        with self._lock:
            if kind in self._seen or self._round < 0:
                self._round += 1
                self._seen = set()
            self._seen.add(kind)
            current = self._outcomes[min(self._round, len(self._outcomes) - 1)]
        return current.get(kind, True)
```

`_ScriptedModel` erfüllt `ultraloom.model.port.Model` und gibt der Reihe nach die vorgegebenen `RepairResult`:

```python
class _ScriptedModel:
    def __init__(self, replies: list[RepairResult], on_ask: Callable[[str], None]) -> None:
        self._replies = iter(replies)
        self._on_ask = on_ask

    def ask(self, request: Request) -> Reply:
        self._on_ask(request.prompt)
        return Reply(value=next(self._replies), tokens=0)
```

Prüfe die genauen Namen von `Request`/`Reply` in `src/ultraloom/model/port.py`, bevor du das schreibst.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/flows/test_verify_until_green.py -k "green_first_pass or stagnat" -v`
Expected: FAIL mit `NameError: name 'assemble' is not defined`

- [ ] **Step 3: `previous_failing` ergänzen**

In `VerifyState` als letztes Feld:

```python
    previous_failing: tuple[str, ...] = ()
```

Und in `make_check`s Delta:

```python
            # What the previous pass found, saved before `failing` is
            # overwritten: an edge condition sees one state, so "the same
            # checks failed again" is only answerable if the state carries it.
            "previous_failing": state.failing,
```

- [ ] **Step 4: `report_red`, `assemble` und `build` schreiben**

```python
_EXIT_STILL_RED = 1


def _why_red(state: VerifyState, max_rounds: int) -> str:
    if state.unfixable:
        return (
            f"still red and out of reach: {', '.join(state.unfixable)}. "
            f"Closing these means writing tests, which the repairer must not do."
        )
    if state.rounds > max_rounds:
        return f"still red after {max_rounds} repair rounds: {', '.join(state.failing)}"
    return (
        f"stagnated: {', '.join(state.failing)} failed twice over and the last "
        f"repair pass changed nothing"
    )


def _stagnated(state: VerifyState) -> bool:
    return bool(state.failing) and state.failing == state.previous_failing and not state.touched


def assemble(
    config: Config,
    root: Path,
    check_runner: CheckRunner = run_check,
    differ: Differ = changed_files,
    max_rounds: int = 5,
) -> Graph[VerifyState]:
    """The graph, with everything it talks to passed in.

    Separate from `build` so the flow's tests can put a scripted checker and a
    scripted working tree in front of a real Runner: a flow is worth testing as
    a flow, not as four functions that were each fine on their own.
    """

    def report_red(state: VerifyState) -> Delta:
        raise FlowExit(_EXIT_STILL_RED, _why_red(state, max_rounds))

    def out_of_rounds(state: VerifyState) -> bool:
        return state.rounds > max_rounds

    graph: Graph[VerifyState] = Graph("verify-until-green", start="check")
    # One more than repair: the last check grades the last repair pass.
    graph.add(CodeNode("check", make_check(config, check_runner), max_visits=max_rounds + 1))
    graph.add(make_repair(config.test_paths))
    graph.add(CodeNode("guard", make_guard(root, config.test_paths, differ), max_visits=max_rounds))
    graph.add(CodeNode("report_red", report_red))

    # Order matters: next_name takes the first edge whose condition holds, and
    # an edge without one always holds. The unconditional edge goes last.
    graph.edge("check", END, when=lambda state: not state.failing)
    graph.edge(
        "check",
        "report_red",
        when=lambda state: bool(state.unfixable) or _stagnated(state) or out_of_rounds(state),
    )
    graph.edge("check", "repair")
    graph.edge("repair", "guard")
    graph.edge("guard", "check")
    graph.edge("report_red", END)
    return graph


def build(context: FlowContext) -> LoadedFlow:
    """Assemble the flow for one project and one command line."""
    config = context.config
    if not config.test_paths:
        raise ValueError(
            "verify-until-green needs [verify].tests in .ultraloom/config.toml: "
            "the paths the repairer must not touch. Without it there is nothing "
            "stopping a failing test from being edited away."
        )
    kinds = _kinds_from(context.options.get("checks"), config)
    max_rounds = int(context.options.get("max_rounds", 5))
    graph = assemble(config, context.root, max_rounds=max_rounds)
    return LoadedFlow(graph, VerifyState(kinds=kinds))


def _kinds_from(requested: str | None, config: Config) -> tuple[str, ...]:
    """What `--checks` asked for: a profile name, a list, or everything."""
    if requested is None:
        return KINDS
    if requested in config.profiles:
        return config.profiles[requested]
    kinds = tuple(part.strip() for part in requested.split(",") if part.strip())
    unknown = [kind for kind in kinds if kind not in KINDS]
    if unknown:
        known = ", ".join(KINDS)
        profiles = ", ".join(sorted(config.profiles)) or "none"
        raise ValueError(
            f"unknown check {unknown[0]!r}; known checks: {known}; profiles: {profiles}"
        )
    return kinds
```

Importe ergänzen: `from ultraloom.checks import KINDS, run_check`, `from ultraloom.discovery import FlowContext, LoadedFlow`, `from ultraloom.graph import END, AgentNode, CodeNode, Graph`.

**`report_red` ist ein `CodeNode` mit einer Kante nach `END`**, obwohl er immer wirft: `Graph.validate` verlangt, dass jeder Knoten erreichbar ist und keine Sackgasse bildet. Die Kante wird nie genommen.

- [ ] **Step 5: Die `xfail`-Markierung aus Task 6 entfernen**

In `tests/test_discovery.py` den `@pytest.mark.xfail(...)` über `test_a_bundled_flow_is_found_without_a_project_directory` löschen.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 7: Lint, types, coverage**

Run: `uvx ruff check . && uvx ruff format --check . && uvx mypy . && uv run coverage run -m pytest && uv run coverage report`
Expected: alles grün

- [ ] **Step 8: Commit**

```bash
git add src/ultraloom/flows/verify_until_green.py tests/
git commit -m "Assemble the verify-until-green graph and its red exit"
```

---

### Task 11: `--checks` und `--max-rounds` auf der Kommandozeile

**Files:**
- Modify: `src/ultraloom/cli.py:78-110` (`_parser`)
- Modify: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `_flow_options` (Task 5), `build` (Task 10).
- Produces: `run` akzeptiert `--checks` und `--max-rounds`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_options_reach_the_flow(tmp_path: Path) -> None:
    _write_flow(tmp_path, "echo_options", _FLOW_THAT_ECHOES_ITS_OPTIONS)

    assert main(["run", "echo_options", "--root", str(tmp_path), "--no-model",
                 "--checks", "lint,types", "--max-rounds", "2"]) == 0


def test_a_flow_without_the_options_is_unaffected(tmp_path: Path) -> None:
    _write_flow(tmp_path, "plain", _PLAIN_FLOW)

    assert main(["run", "plain", "--root", str(tmp_path), "--no-model"]) == 0


def test_max_rounds_must_be_a_number(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["run", "anything", "--root", str(tmp_path), "--max-rounds", "soon"])

    assert raised.value.code == 2  # argparse's own usage error
```

```python
_FLOW_THAT_ECHOES_ITS_OPTIONS = """
from dataclasses import dataclass

from ultraloom.discovery import LoadedFlow
from ultraloom.graph import END, CodeNode, Graph


@dataclass(frozen=True, slots=True)
class Payload:
    note: str = ""


def build(context):
    assert context.options["checks"] == "lint,types"
    assert context.options["max_rounds"] == "2"
    flow = Graph("echo_options", start="only")
    flow.add(CodeNode("only", lambda _data: {"note": "seen"}))
    flow.edge("only", END)
    return LoadedFlow(flow, Payload())
"""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -k options -v`
Expected: FAIL mit `unrecognized arguments: --checks`

- [ ] **Step 3: Write minimal implementation**

In `_parser`, beim `run`-Unterbefehl:

```python
    run.add_argument(
        "--checks",
        default=None,
        help="which checks to run: a comma-separated list, or a profile from [verify.profiles]",
    )
    run.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="how many repair rounds a flow may take (default: the flow's own limit)",
    )
```

`--max-rounds` landet als `args.max_rounds`, was `_flow_options` bereits liest.

- [ ] **Step 4: README ergänzen**

Einen Abschnitt über `verify-until-green` schreiben: was der Ablauf tut, die zwei Optionen, die Konfigurationsschlüssel `[verify].tests`, `[verify].timeout`, `[verify.profiles]`, und die Exit-Codes 0/1/3/4. Auf `docs/abläufe/verify-until-green.md` verweisen (Task 12).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 6: Lint, types, coverage**

Run: `uvx ruff check . && uvx ruff format --check . && uvx mypy . && uv run coverage run -m pytest && uv run coverage report`
Expected: alles grün

- [ ] **Step 7: Commit**

```bash
git add src/ultraloom/cli.py README.md tests/test_cli.py
git commit -m "Take the check selection and the round ceiling on the command line"
```

---

### Task 12: Die Ablaufseite und der Test, der sie festnagelt

**Files:**
- Create: `docs/abläufe/verify-until-green.md`
- Create: `tests/test_flow_docs.py`
- Modify: `src/ultraloom/discovery.py` (nur falls der Test einen Zugriff braucht, den es noch nicht gibt)

**Interfaces:**
- Consumes: `list_flows`, `find_flow` (Task 6), `assemble` (Task 10).
- Produces: `Graph.edges() -> tuple[tuple[str, str], ...]` — Kantenpaare (Quelle, Ziel), sortiert. `Graph` hält `_edges` privat; der Test braucht einen Weg hinein, und ein Test, der auf `_edges` zugreift, ist ein Test, der die Kapselung aufbricht.

- [ ] **Step 1: Write the failing test**

```python
def test_every_bundled_flow_has_a_documentation_page() -> None:
    for entry in list_flows(Path(".")):
        if entry.origin != "bundled":
            continue
        assert _page_for(entry.name).is_file(), f"{entry.name} has no page under docs/abläufe/"


def test_the_page_names_every_node_and_every_edge() -> None:
    graph = assemble(Config(root=Path("."), test_paths=("tests/",)), Path("."))
    diagram = _mermaid_block(_page_for("verify_until_green"))

    for name in graph.node_names():
        assert name in diagram, f"node {name!r} is missing from the diagram"
    for source, target in graph.edges():
        assert _edge_drawn(diagram, source, target), f"edge {source} -> {target} is missing"


def test_the_page_draws_no_node_the_graph_does_not_have() -> None:
    graph = assemble(Config(root=Path("."), test_paths=("tests/",)), Path("."))
    drawn = _nodes_drawn(_mermaid_block(_page_for("verify_until_green")))

    assert drawn <= set(graph.node_names()) | {"END"}


def test_a_page_that_lost_a_node_fails_the_check(tmp_path: Path) -> None:
    # The check has to be able to fail, or it is decoration.
    diagram = 'check --> repair\n    repair --> guard\n'

    assert not _edge_drawn(diagram, "guard", "check")
```

Die Hilfen im Testmodul: `_page_for` bildet den Modulnamen auf den Dateinamen ab (`verify_until_green` → `verify-until-green.md`), `_mermaid_block` schneidet den ```mermaid-Block aus, `_nodes_drawn` liest die Bezeichner am Zeilenanfang und vor einem `-->`, `_edge_drawn` sucht `<quelle> -->` gefolgt von `<ziel>` in derselben Zeile.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_flow_docs.py -v`
Expected: FAIL — `docs/abläufe/verify-until-green.md` existiert nicht, und `Graph` hat weder `edges` noch `node_names`

- [ ] **Step 3: `Graph` um zwei Leser erweitern**

```python
    def node_names(self) -> tuple[str, ...]:
        """Every node's name, in the order they were added."""
        return tuple(self._nodes)

    def edges(self) -> tuple[tuple[str, str], ...]:
        """Every edge as (source, target), in the order they were added.

        Published for the documentation check: a diagram that has drifted from
        the graph is worse than no diagram, and comparing the two needs a way
        in that is not `_edges`.
        """
        return tuple(
            (source, edge.dst) for source, edges in self._edges.items() for edge in edges
        )
```

Dazu Tests in `tests/test_graph.py`.

- [ ] **Step 4: Die Seite schreiben**

`docs/abläufe/verify-until-green.md`, deutsch, mit: Mermaid-Diagramm (das aus Spec 6, mit `report_red --> END` ergänzt), Knotentabelle mit `max_visits`, Zustandstabelle, Prompt und Schema des Agenten, Konfigurationsschlüssel, Abbruchbedingungen mit Exit-Codes. Der Mermaid-Block muss jeden Knotennamen wörtlich enthalten — also `report_red`, nicht `red` als Kurzform.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_flow_docs.py tests/test_graph.py -v`
Expected: PASS

- [ ] **Step 6: Lint, types, coverage**

Run: `uvx ruff check . && uvx ruff format --check . && uvx mypy . && uv run coverage run -m pytest && uv run coverage report`
Expected: alles grün

- [ ] **Step 7: Commit**

```bash
git add docs/abläufe/ tests/test_flow_docs.py tests/test_graph.py src/ultraloom/graph.py
git commit -m "Document the flow's graph and check the drawing against it"
```

---

### Task 13: Der erste echte Lauf — ultraloom auf sich selbst

**Files:**
- Create: `.ultraloom/config.toml`
- Modify: `docs/abläufe/verify-until-green.md` (nur, falls der Lauf etwas zeigt, was die Seite verschweigt)

**Interfaces:**
- Consumes: alles davor.
- Produces: nichts für spätere Tasks; der Beweis ist das Ergebnis.

Dies ist der erste Task, der Modell-Credentials braucht. Er ist kein TDD-Zyklus, sondern ein Experiment mit Protokoll.

- [ ] **Step 1: Die Konfiguration anlegen**

```toml
# .ultraloom/config.toml — ultraloom prüft sich selbst.
[verify]
tests = ["tests/"]

[verify.profiles]
edit      = ["lint", "types"]
precommit = ["lint", "types", "test", "coverage"]
```

Kein `lint`/`types`/`test`-Kommando: das Python-Preset trifft bereits zu, und ein Eintrag, der das Preset wiederholt, ist eine Zeile, die veralten kann. Genau das ist mit „allein über `config.toml` unterschieden" gemeint.

- [ ] **Step 2: Den grünen Fall bestätigen**

Run: `uv run ultraloom run verify-until-green --checks edit`
Expected: Exit 0, `rounds == 1`, kein Modellaufruf.

- [ ] **Step 3: Einen echten Fehler einbauen**

Eine Quelldatei so verändern, dass `ruff` und `mypy` sie beanstanden — zum Beispiel eine ungenutzte Variable und eine falsche Annotation in `src/ultraloom/checks.py`. Die Änderung **nicht** committen.

- [ ] **Step 4: Den Reparaturlauf ausführen**

Run: `uv run ultraloom run verify-until-green --checks edit`
Expected: Exit 0 nach ein bis zwei Runden; `git diff` zeigt, dass der Agent die Quelldatei repariert und keine Testdatei angefasst hat.

- [ ] **Step 5: Das Journal lesen**

Run: `uv run ultraloom show <run-id>`
Expected: `check` erscheint zweimal mit **zwei verschiedenen Einträgen** — das ist der Beweis, dass Task 3 wirkt. Der `repair`-Eintrag trägt eine Token-Zahl größer als 0; ist sie 0, ist das der in Spec 10 genannte unbestätigte Punkt und gehört als Fund notiert, nicht weggesehen.

- [ ] **Step 6: Die Testsperre am lebenden Objekt prüfen**

Einen Test so verändern, dass er fehlschlägt, ohne dass die Quelle falsch ist (etwa eine Assertion auf einen falschen Wert). Dann:

Run: `uv run ultraloom run verify-until-green --checks precommit`
Expected: Entweder Exit 4 (der Agent hat den Test angefasst, die Sperre hat gegriffen) oder Exit 1 mit einer Zusammenfassung, die sagt, dass die Quelle in Ordnung ist. Beides ist ein bestandener Lauf; ein Exit 0 wäre der Fehlschlag.

- [ ] **Step 7: Alles zurücksetzen und committen**

```bash
git checkout -- src/ tests/
git add .ultraloom/config.toml docs/
git commit -m "Configure ultraloom to verify itself"
```

- [ ] **Step 8: Die Funde festhalten**

Was der Lauf gezeigt hat — Token-Zahlen, Laufzeit, ob die Prompts trugen, ob die Meldungen verständlich waren — in `docs/abläufe/verify-until-green.md` unter einem Abschnitt „Was echte Läufe gezeigt haben" notieren. Ein Ablauf, dessen erste echte Zahlen niemand aufgeschrieben hat, wird beim nächsten Mal wieder geraten.

---

### Task 14: Der zweite echte Lauf — space

**Files:**
- Create (im space-Worktree): `.ultraloom/config.toml`
- Modify (in ultraloom): was Schritt 4 findet

**Interfaces:**
- Consumes: alles davor.
- Produces: die Antwort auf die Frage, die Teilprojekt 2 stellt.

- [ ] **Step 1: Einen Worktree für space anlegen**

```bash
git -C "C:/Users/micro/Documents/#GIT/space" worktree add .claude/worktrees/ultraloom-verify -b try/ultraloom-verify
```

- [ ] **Step 2: ultraloom dort installieren**

Aus dem space-Worktree heraus, gegen den ultraloom-Branch dieses Teilprojekts — als editierbare Installation, damit eine Korrektur an ultraloom sofort dort wirkt:

```bash
uv pip install -e "C:/Users/micro/Documents/#GIT/ultraloom/.claude/worktrees/teilprojekt-1-kern-tasks-1-8-88653d[agent]"
```

- [ ] **Step 3: Die Konfiguration schreiben**

```toml
# space/.ultraloom/config.toml
[verify]
lint  = "uvx gdlint ."
test  = ".tools/godot4-headless.cmd --headless -s test/run.gd"
tests = ["test/"]
timeout = 900

[verify.coverage]
report    = "coverage-report/lcov.info"
threshold = 100

[verify.profiles]
edit      = ["lint"]
precommit = ["lint", "test", "coverage"]
```

Kein `types`: GDScript hat keinen Typechecker, und `checks` meldet das bereits als bekannte Einschränkung statt als bestandene Prüfung. Der genaue Pfad des Test-Kommandos ist gegen `space/.claude/hooks/toolchain.py` und `godot_quality.py` zu prüfen, bevor er hier steht.

- [ ] **Step 4: Den grünen Fall laufen lassen**

Run: `uv run ultraloom run verify-until-green --checks edit`
Expected: Exit 0.

**Was hier schiefgeht, ist der Ertrag des Teilprojekts.** Jede Stelle, an der der Ablauf etwas über Python annimmt, kommt hier heraus. Erwartete Kandidaten, die aber keine Vorwegnahme sein sollen: der `coverage`-Zweig (space misst über Nano Coverage nach LCOV, nicht über `coverage report` — `checks` hat für `project.godot` gar kein Coverage-Preset, meldet also „unavailable", was als rote Prüfung durchkommt und richtig ist), und die Laufzeit der headless-Suite gegen `[verify].timeout`.

Jede nötige Korrektur gehört in den ultraloom-Branch, mit Test, nach demselben TDD-Zyklus wie jeder Task davor.

- [ ] **Step 5: Den vollen Lauf ausführen**

Run: `uv run ultraloom run verify-until-green --checks precommit`
Expected: Der Lauf endet mit einer Aussage, die stimmt — grün, oder rot mit nachvollziehbarer Begründung. Ein Lauf, der grün meldet, ohne die Suite gestartet zu haben, ist der einzige unbedingte Fehlschlag.

- [ ] **Step 6: Die Doppelprüfungs-Frage beantworten**

Abschnitt 17 des Kern-Designs fragt, ob das Agent SDK space' `coverage_gate.py` als Claude-Code-Hook zusätzlich ausführt und damit doppelt prüft. Beobachte das während des `repair`-Knotens und schreibe die Antwort in `docs/abläufe/verify-until-green.md`.

- [ ] **Step 7: Die space-Konfiguration committen**

```bash
git -C "C:/Users/micro/Documents/#GIT/space/.claude/worktrees/ultraloom-verify" add .ultraloom/config.toml
git -C "C:/Users/micro/Documents/#GIT/space/.claude/worktrees/ultraloom-verify" commit -m "Configure the ultraloom verify flow"
```

- [ ] **Step 8: Die Funde in ultraloom festhalten und committen**

Erst wenn Schritt 4 und 5 stehen, geht der ultraloom-Branch nach main. Dafür `superpowers:finishing-a-development-branch` verwenden.

---

## Selbstprüfung des Plans

**Spec-Abdeckung.** Abschnitt 1 → Tasks 13, 14. Abschnitt 2 → alle. Abschnitt 3.1 → Task 3. Abschnitt 3.2 → Task 6. Abschnitt 4 → Tasks 7–10. Abschnitt 5 → Task 9. Abschnitt 6 → Task 12. Abschnitt 7.1/7.2 → Tasks 1, 11. Abschnitt 7.3 → Task 4 (Codes), Tasks 9 und 10 (wer sie wirft). Abschnitt 8 → Task 2. Abschnitt 9.1 → Tasks 7–10. Abschnitt 9.2 → Task 3. Abschnitt 9.3 → Tasks 13, 14. Abschnitt 9.4 → Task 3 Step 1 (`_gate_flow` setzt das Gate nicht auf `graph.start`) und Task 10 (`test_a_state_that_starts_mid_run_is_not_a_special_case`, plus die Varianten, in denen die erste Reparatur nicht gelingt). Abschnitt 10 → Tasks 13 Step 5 und 14 Step 6.

**Zwei Ergänzungen gegenüber der Spec**, oben unter „Zwei Entwurfslücken" begründet: `FlowContext`/`build` (Task 5) und `FlowExit`/`Result.exit_code` (Task 4). Beide gehören in die Spec nachgetragen, sobald der Plan angenommen ist.

**Eine Verfeinerung gegenüber Spec 3.1**: die Cache-Regel ist „solange der Lauf nachvollzieht", nicht „im Replay und in resume" — `resume` schaltet den Cache beim ersten fehlenden Eintrag ab, sonst würde ein Zyklus nach dem Freigabepunkt wieder aus dem Journal bedient. Steht in Task 3.

**Namen, die über Tasks hinweg gelten:** `Config.test_paths`, `Config.timeout`, `Config.profiles`, `FlowContext(root, config, options)`, `FlowEntry(name, origin, problem)`, `LoadedFlow(graph, initial)`, `FlowExit(code, message)`, `Result.exit_code`, `VerifyState(kinds, report, failing, unfixable, touched, rounds, previous_failing)`, `RepairResult(summary, changed)`, `make_check`, `make_repair`, `make_guard`, `assemble`, `build`, `changed_files`, `Graph.node_names`, `Graph.edges`.
