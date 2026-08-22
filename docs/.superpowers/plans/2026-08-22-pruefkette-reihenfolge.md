# Prüfkette: Reihenfolge, Prozessgruppe, mehrere Kommandos — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Prüfkette bekommt eine Reihenfolge zwischen Prüfungen, eine Zeitgrenze, die die ganze Prozessgruppe tötet, und mehrere Kommandos je Prüfart — damit in space ein grüner `precommit`-Lauf möglich wird.

**Architecture:** Ein neues Modul `process.py` übernimmt die Prozessführung (Popen, Lesefäden, Baumtötung) aus `checks.py`. `checks.py` bekommt einen gemeinsamen Scheduler `run_kinds`, den sowohl `run_all` als auch der Ablaufknoten benutzen; er ordnet Prüfarten in Stufen und führt sie stufenweise aus. Die Presets werden von Argv-Tupeln auf eine `Preset`-Dataclass mit `measuring`/`after`/`measure` gehoben, damit „wer misst" aus der angeforderten Menge folgt.

**Tech Stack:** Python 3.13, `uv`, pytest, `ruff`, `mypy`, `coverage`. Keine neuen Laufzeit-Abhängigkeiten — die Windows-Job-Objekte kommen über `ctypes` aus der Standardbibliothek.

**Spec:** [docs/.superpowers/specs/2026-08-22-pruefkette-reihenfolge-design.md](../specs/2026-08-22-pruefkette-reihenfolge-design.md)

## Global Constraints

- **Python >= 3.13.** `requires-python = ">=3.13"`, ruff `target-version = "py313"`, mypy `python_version = 3.13`.
- **Immer `uv`, nie `pip`.** Tests laufen als `uv run pytest`, Werkzeuge als `uvx <werkzeug>`.
- **TDD.** Erst der fehlschlagende Test, dann die Implementierung. Jeder Task endet mit einem Commit.
- **100 % Coverage, gemessen.** Jede Ausnahme trägt `# pragma: no cover  # <Grund>`; ein nacktes Pragma ist ein Fehler.
- **Typisierung ohne `Any` und ohne `# type: ignore`** außer mit begründendem Kommentar. `from __future__ import annotations` steht in jedem Modul.
- **Sprache:** Code, Bezeichner, Code-Kommentare, Commit-Nachrichten auf Englisch; Prosa-Dokumentation (`docs/`, README) auf Deutsch.
- **Kommentare erklären das Warum**, nie die Zeile darunter in Worten.
- **Imports stehen auf Modulebene.** Ausnahme nur mit begründendem Kommentar — `cli.py` importiert die Harness-Seite bewusst lokal, das bleibt so.
- **Die Modulgrenze hält:** `config` importiert nichts aus `checks`; `checks` und `process` importieren nichts aus der Harness-Seite (`graph`, `state`, `runner`, `journal`, `gate`, `model`, `discovery`). `tests/test_module_boundary.py` erzwingt das.
- **Grundsatz 4 (Kern-Design §3):** Ein fehlendes Prüfwerkzeug ist ein Fehler, kein Grund zum Überspringen. Nichts in diesem Plan darf eine nicht gelaufene Prüfung grün melden.

---

### Task 1: `process.run` — kein `communicate()` mehr

Die Ursache des Hängers ist `subprocess.run`: bei Fristablauf tötet es das Kind und ruft danach `communicate()`, das auf Pipe-Enden wartet, die ein überlebender Enkel offen hält. Dieser Task ersetzt das durch fortlaufende Lesefäden. Der Enkel überlebt hier noch — er stirbt in Task 2 —, aber der **Lauf hängt nicht mehr**.

**Files:**
- Create: `src/ultraloom/process.py`
- Test: `tests/test_process.py`

**Interfaces:**
- Consumes: nichts
- Produces:
  - `Completed(returncode: int, stdout: str, stderr: str, timed_out: bool = False, output_abandoned: bool = False)` — eingefrorene Dataclass mit `slots=True`
  - `run(argv: Sequence[str], *, cwd: Path, timeout: float) -> Completed`
  - `DRAIN_GRACE: float = 5.0`
  - `TerminateTree = Callable[[subprocess.Popen[bytes]], None]`

- [ ] **Step 1: Write the failing tests**

`tests/test_process.py`:

```python
"""Tests for running one child process without ever waiting on a dead pipe."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from ultraloom.process import Completed, run

# A grandchild that outlives its parent and keeps the inherited pipe open. This
# is the shape subprocess.run hangs on: the parent dies, the pipe does not
# close, and communicate() waits for an EOF that never comes.
_ORPHAN = (
    "import subprocess, sys; "
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
    "import time; time.sleep(30)"
)


def _python(code: str) -> tuple[str, ...]:
    return (sys.executable, "-c", code)


def test_it_reports_what_the_command_said(tmp_path: Path) -> None:
    completed = run(
        _python("import sys; print('out'); print('err', file=sys.stderr)"),
        cwd=tmp_path,
        timeout=30,
    )
    assert completed == Completed(returncode=0, stdout="out\n", stderr="err\n")


def test_it_reports_a_nonzero_exit(tmp_path: Path) -> None:
    completed = run(_python("raise SystemExit(3)"), cwd=tmp_path, timeout=30)
    assert completed.returncode == 3
    assert not completed.timed_out


def test_a_timeout_returns_instead_of_waiting_on_the_orphans_pipe(tmp_path: Path) -> None:
    """The whole point of the module: a hung tool must cost the timeout, not the run."""
    started = time.monotonic()
    completed = run(_python(_ORPHAN), cwd=tmp_path, timeout=1)
    elapsed = time.monotonic() - started

    assert completed.timed_out
    # Generous on purpose -- this is a wall-clock test, and a loaded machine is
    # allowed to be slow. It still fails hard against the old behaviour, which
    # would sit here for the full 30 seconds.
    assert elapsed < 20, f"run() waited {elapsed:.1f}s; a timed-out command must not block the run"


def test_it_keeps_what_a_timed_out_command_managed_to_write(tmp_path: Path) -> None:
    completed = run(
        _python("print('before the hang', flush=True); import time; time.sleep(30)"),
        cwd=tmp_path,
        timeout=1,
    )
    assert "before the hang" in completed.stdout


def test_a_large_output_does_not_deadlock_the_pipe(tmp_path: Path) -> None:
    """Without draining threads a chatty tool fills the pipe buffer and stops."""
    completed = run(
        _python("print('x' * 200_000)"),
        cwd=tmp_path,
        timeout=60,
    )
    assert completed.returncode == 0
    assert len(completed.stdout) > 200_000


def test_it_runs_in_the_directory_it_was_given(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("here", encoding="utf-8")
    completed = run(
        _python("print(open('marker.txt').read())"),
        cwd=tmp_path,
        timeout=30,
    )
    assert "here" in completed.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_process.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'ultraloom.process'`.

- [ ] **Step 3: Write the implementation**

`src/ultraloom/process.py`:

```python
"""Running one child process so that a hung tool costs its timeout and no more.

subprocess.run cannot do this. On a timeout it kills the direct child and then
calls communicate(), which waits for the pipes to close -- and a surviving
grandchild holds those same pipe ends open. The run then hangs at exactly the
point the timeout existed to prevent. Every check command in this project has
that shape: `uv run pytest` is a chain of at least two processes, and so is a
Godot launcher, and so is anything behind an [exec].prefix.

The answer is to never wait on a pipe: two threads drain stdout and stderr as
the process writes them, so the output is already collected before anything is
killed.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

# How long the draining threads get after the tree has been killed. They are
# reading from pipes nobody should be holding any more; if they are still
# blocked after this, something out there survived and the run gives up on the
# rest of the output rather than on itself.
DRAIN_GRACE = 5.0

type TerminateTree = Callable[[subprocess.Popen[bytes]], None]


@dataclass(frozen=True, slots=True)
class Completed:
    """What the process said, and whether it was allowed to finish saying it."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    # A draining thread that never came back: some descendant still holds the
    # pipe. Named in the result so a truncated capture does not read as a
    # command that simply said little.
    output_abandoned: bool = False


def run(argv: Sequence[str], *, cwd: Path, timeout: float) -> Completed:
    """Run one command to completion, or kill it when the timeout runs out."""
    process = subprocess.Popen(  # noqa: S603  # argv is built by checks, never a shell string
        tuple(argv),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    captured: dict[str, bytes] = {}
    drains = tuple(
        _drain(process, stream, name, captured)
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))
    )

    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_tree(process)
        process.wait()

    abandoned = False
    for thread in drains:
        thread.join(DRAIN_GRACE)
        if thread.is_alive():
            abandoned = True

    return Completed(
        returncode=process.returncode,
        stdout=_text(captured.get("stdout", b"")),
        stderr=_text(captured.get("stderr", b"")),
        timed_out=timed_out,
        output_abandoned=abandoned,
    )


def _drain(
    process: subprocess.Popen[bytes],
    stream: object,
    name: str,
    captured: dict[str, bytes],
) -> threading.Thread:
    """One daemon thread emptying one pipe into `captured`.

    Daemon, because an abandoned thread must not keep the interpreter alive:
    the whole point of this module is that one stuck descendant cannot hold the
    run hostage.
    """

    def pump() -> None:
        assert stream is not None  # noqa: S101  # both pipes were just requested
        with stream:  # type: ignore[attr-defined]  # Popen types the pipe as IO[bytes] | None
            captured[name] = stream.read()  # type: ignore[attr-defined]  # same

    thread = threading.Thread(target=pump, daemon=True, name=f"ultraloom-{name}")
    thread.start()
    return thread


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    """Kill the process. Task 2 replaces this with a kill of the whole tree."""
    process.kill()


def _text(raw: bytes) -> str:
    """Whatever the tool wrote, never an exception about how it wrote it."""
    return raw.decode("utf-8", errors="replace")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_process.py -v
```

Expected: PASS (7 Tests).

- [ ] **Step 5: Lint, types, coverage of the new module**

```bash
uvx ruff check src/ultraloom/process.py tests/test_process.py && uvx ruff format --check src/ultraloom/process.py tests/test_process.py && uvx mypy src/ultraloom/process.py
```

Expected: alles sauber. Bleibt eine Zeile ungedeckt, bekommt sie ein `# pragma: no cover  # <Grund>` — oder besser einen Test.

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/process.py tests/test_process.py
git commit -m "Stop waiting on the pipe a dead process left behind"
```

---

### Task 2: Den ganzen Baum töten

Jetzt stirbt auch der Enkel. Die Plattformweiche ist eine gewöhnliche Funktion, damit die Auswahl auf jeder Maschine für beide Plattformen prüfbar ist; nur der fremde Systemaufruf selbst bleibt ungedeckt.

**Files:**
- Modify: `src/ultraloom/process.py`
- Test: `tests/test_process.py`

**Interfaces:**
- Consumes: `run`, `Completed`, `TerminateTree` aus Task 1
- Produces:
  - `spawn_kwargs(platform: str) -> dict[str, object]`
  - `terminator(platform: str) -> TerminateTree`
  - `_terminate_posix(process)`, `_terminate_windows(process)`

- [ ] **Step 1: Write the failing tests**

Ans Ende von `tests/test_process.py`:

```python
import os
import subprocess

import pytest

from ultraloom.process import spawn_kwargs, terminator, _terminate_posix, _terminate_windows

# A parent that spawns a grandchild writing a marker file every 100ms, then
# hangs. If the grandchild survives the timeout, the file keeps growing after
# run() returned -- which is exactly the bug being fixed.
_TICKING_GRANDCHILD = (
    "import subprocess, sys, time; "
    "subprocess.Popen([sys.executable, '-c', "
    "\"import time\\nwhile True:\\n    open('tick.txt','a').write('.')\\n    time.sleep(0.1)\""
    "]); "
    "time.sleep(30)"
)


def test_the_switch_answers_for_both_platforms() -> None:
    """Selectable on any machine: the choice is testable, only the syscall is not."""
    assert terminator("win32") is _terminate_windows
    assert terminator("linux") is _terminate_posix
    assert terminator("darwin") is _terminate_posix


def test_posix_asks_for_its_own_session() -> None:
    assert spawn_kwargs("linux") == {"start_new_session": True}


def test_windows_starts_suspended() -> None:
    """Suspended, so no fast child can spawn a grandchild before the job exists."""
    flags = spawn_kwargs("win32")["creationflags"]
    assert isinstance(flags, int)
    assert flags & subprocess.CREATE_SUSPENDED


def test_a_timeout_kills_the_grandchild_too(tmp_path: Path) -> None:
    run(_python(_TICKING_GRANDCHILD), cwd=tmp_path, timeout=2)

    tick = tmp_path / "tick.txt"
    assert tick.exists(), "the grandchild never started; the test proves nothing"
    before = tick.stat().st_size
    time.sleep(1.5)
    assert tick.stat().st_size == before, "the grandchild outlived the timeout"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_process.py -v -k "grandchild or platform or suspended or session"
```

Expected: FAIL — `ImportError: cannot import name 'spawn_kwargs'`.

- [ ] **Step 3: Write the implementation**

In `src/ultraloom/process.py`: `_terminate_tree` durch die Weiche ersetzen und `Popen` die Plattform-Argumente geben.

```python
import ctypes
import os
import signal
import sys

# Windows job object constants, from winnt.h. Spelled out rather than imported:
# the standard library exposes none of them.
_JOB_OBJECT_ASSIGN_PROCESS = 0x0002
_JOB_OBJECT_TERMINATE = 0x0008
_JOB_OBJECT_QUERY = 0x0004
_JOB_ALL_ACCESS = _JOB_OBJECT_ASSIGN_PROCESS | _JOB_OBJECT_TERMINATE | _JOB_OBJECT_QUERY


def spawn_kwargs(platform: str) -> dict[str, object]:
    """How to start a process so that its descendants can be reached later.

    POSIX gets a session of its own, so one killpg reaches every descendant.
    Windows is started *suspended*: the job is created and the process assigned
    to it before it runs a single instruction. Started first and assigned after,
    a fast child could already have spawned a grandchild that never belongs to
    the job -- and that grandchild is the one this whole module is about.
    """
    if platform == "win32":
        return {"creationflags": subprocess.CREATE_SUSPENDED}
    return {"start_new_session": True}


def terminator(platform: str) -> TerminateTree:
    """The kill that reaches the whole tree on this platform."""
    if platform == "win32":
        return _terminate_windows
    return _terminate_posix


def _terminate_posix(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)  # pragma: no cover  # POSIX-only syscall; the Windows CI machine never reaches it
    except (ProcessLookupError, PermissionError):
        # Already gone, or in a session this process may not signal. Either way
        # there is nothing left to kill and nothing worth raising over.
        process.kill()


def _terminate_windows(process: subprocess.Popen[bytes]) -> None:
    handle = getattr(process, "_ultraloom_job", None)
    if handle is None:
        process.kill()
        return
    ctypes.windll.kernel32.TerminateJobObject(handle, 1)  # pragma: no cover  # Windows-only syscall; a POSIX machine never reaches it  # type: ignore[attr-defined]  # windll exists only on Windows
```

`run` wird angepasst:

```python
def run(argv: Sequence[str], *, cwd: Path, timeout: float) -> Completed:
    process = subprocess.Popen(  # noqa: S603  # argv is built by checks, never a shell string
        tuple(argv),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **spawn_kwargs(sys.platform),  # type: ignore[arg-type]  # the kwargs differ per platform by design
    )
    if sys.platform == "win32":  # pragma: no cover  # the POSIX branch is the one a Linux machine sees
        _adopt_into_job(process)
    ...
    except subprocess.TimeoutExpired:
        timed_out = True
        terminator(sys.platform)(process)
        process.wait()
```

Und die Job-Zuweisung samt Fortsetzen:

```python
def _adopt_into_job(process: subprocess.Popen[bytes]) -> None:  # pragma: no cover  # Windows-only; every call below is a syscall a POSIX machine does not have
    """Create a job, put the suspended process in it, then let it run.

    The handle rides on the Popen object because that is what `_terminate_windows`
    is handed. A private attribute on a foreign object is not pretty; the
    alternative is a second mapping keyed by pid, and a pid can be reused.
    """
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]  # windll exists only on Windows
    job = kernel32.CreateJobObjectW(None, None)
    kernel32.AssignProcessToJobObject(job, int(process._handle))  # noqa: SLF001
    process._ultraloom_job = job  # type: ignore[attr-defined]  # see the docstring
    for thread_id in _thread_ids(process.pid):
        thread = kernel32.OpenThread(_THREAD_SUSPEND_RESUME, False, thread_id)
        kernel32.ResumeThread(thread)
        kernel32.CloseHandle(thread)
```

**Hinweis für den Umsetzenden:** `CREATE_SUSPENDED` erfordert das Fortsetzen des Hauptthreads. Der einfachste zuverlässige Weg unter Windows ist `ResumeThread` auf den Hauptthread — `subprocess` gibt dessen Handle nicht heraus, deshalb der Umweg über `_thread_ids`. Ist das in der Praxis zu fragil, ist die zulässige Alternative: **ohne** `CREATE_SUSPENDED` starten, sofort dem Job zuweisen und das Restrisiko im Kommentar benennen. Diese Entscheidung gehört in den Commit und in eine Notiz für das Review — nicht stillschweigend.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_process.py -v
```

Expected: PASS (11 Tests).

- [ ] **Step 5: Lint and types**

```bash
uvx ruff check src/ultraloom/process.py tests/test_process.py && uvx mypy src/ultraloom/process.py
```

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/process.py tests/test_process.py
git commit -m "Kill the whole process tree when a check runs out of time"
```

---

### Task 3: `checks._run` benutzt `process.run`

**Files:**
- Modify: `src/ultraloom/checks.py:236-280` (`_run`), Imports
- Test: `tests/test_checks.py`

**Interfaces:**
- Consumes: `process.run`, `process.Completed`
- Produces: unveränderte `CheckResult`-Semantik; `_run` wirft weiterhin nicht

- [ ] **Step 1: Write the failing test**

Ans Ende von `tests/test_checks.py`:

```python
def test_a_timed_out_check_names_its_partial_output(tmp_path: Path) -> None:
    """The timeout message survives the move to process.run, and so does what was written."""
    python_project(tmp_path)
    config = Config(
        root=tmp_path,
        commands={"lint": (py("print('half done', flush=True); import time; time.sleep(30)"),)},
        timeout=1,
    )

    result = run_check("lint", config)

    assert not result.ok
    assert "timed out after 1s" in result.output
    assert "half done" in result.output
```

*(Der Test setzt bereits `commands` als Tupel — das kommt in Task 4. Bis dahin: `commands={"lint": "..."}`. Der Umsetzende passt die eine Zeile in Task 4 mit an.)*

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_checks.py -k timed_out_check_names -v
```

Expected: FAIL — die Teilausgabe fehlt, weil `TimeoutExpired.stdout` bei einem hängenden Enkel leer bleibt.

- [ ] **Step 3: Write the implementation**

`_run` in `src/ultraloom/checks.py` ersetzen:

```python
from ultraloom import process


def _run(argv: tuple[str, ...], kind: str, config: Config, source: str) -> CheckResult:
    try:
        completed = process.run(argv, cwd=config.root, timeout=config.timeout)
    except OSError as error:
        # A tool that is not installed must read as a failed check, not as a
        # traceback that takes the whole chain down with it.
        detail = f"could not run {shlex.join(argv)!r}: {error}"
        if not Path(argv[0]).is_absolute() and len(Path(argv[0]).parts) > 1:
            detail += (
                f"\nhint: {argv[0]!r} is a relative path, and a command is not looked up "
                f"relative to the project root. Use `uv run` (or an absolute path)."
            )
        return CheckResult(kind, False, detail, source)

    output = completed.stdout + completed.stderr
    if completed.timed_out:
        detail = f"{shlex.join(argv)!r} timed out after {config.timeout}s"
        if completed.output_abandoned:
            # Said out loud: a descendant still holds the pipe, so what follows
            # is what had arrived by then and not everything the tool wrote.
            detail += " (output incomplete: a descendant still held the pipe)"
        return CheckResult(kind, False, f"{detail}\n{output}".rstrip(), source)
    return CheckResult(kind, completed.returncode == 0, output, source)
```

`_decode` wird ersatzlos gelöscht — `process.run` liefert bereits Text. Der zugehörige Test in `tests/test_checks.py` (Import und Testfunktion für `_decode`) verschwindet mit ihm.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_checks.py -v
```

Expected: PASS. Schlägt ein Test wegen des entfernten `_decode`-Imports fehl, wird er mitgelöscht.

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/checks.py tests/test_checks.py
git commit -m "Route every check command through the process module"
```

---

### Task 4: Drei Konfigurationsgestalten für `lint`, `types`, `test`

**Files:**
- Modify: `src/ultraloom/config.py` (`Config.commands`, `Config.threaded`, Parsing)
- Modify: `src/ultraloom/checks.py` (`resolve_check` liest `config.commands[kind]` als Tupel)
- Test: `tests/test_config.py`, `tests/test_checks.py`

**Interfaces:**
- Consumes: `Config` aus Task 3
- Produces:
  - `Config.commands: Mapping[str, tuple[str, ...]]` (**Bruch:** war `Mapping[str, str]`)
  - `Config.threaded: frozenset[str] = frozenset()`

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:

```python
def test_a_string_command_stays_one_command(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify]\nlint = "gdlint ."\n')
    assert load_config(tmp_path).commands["lint"] == ("gdlint .",)


def test_a_list_holds_several_commands_in_order(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify]\nlint = ["gdlint .", "gdformat --check ."]\n')
    assert load_config(tmp_path).commands["lint"] == ("gdlint .", "gdformat --check .")


def test_the_table_form_carries_commands_and_the_switch(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        '[verify.lint]\ncommands = ["gdlint .", "gdformat --check ."]\nthreaded = true\n',
    )
    config = load_config(tmp_path)
    assert config.commands["lint"] == ("gdlint .", "gdformat --check .")
    assert "lint" in config.threaded


def test_threaded_defaults_to_off(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify.lint]\ncommands = ["gdlint ."]\n')
    assert load_config(tmp_path).threaded == frozenset()


def test_the_table_form_needs_commands(tmp_path: Path) -> None:
    write_config(tmp_path, "[verify.lint]\nthreaded = true\n")
    with pytest.raises(ConfigError, match="commands"):
        load_config(tmp_path)


def test_an_empty_command_list_is_refused(tmp_path: Path) -> None:
    """A kind that names no command is a check nobody runs -- and it must not look green."""
    write_config(tmp_path, "[verify.lint]\ncommands = []\n")
    with pytest.raises(ConfigError, match="empty"):
        load_config(tmp_path)


def test_a_blank_command_in_a_list_is_refused(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify]\nlint = ["gdlint .", "  "]\n')
    with pytest.raises(ConfigError, match="empty"):
        load_config(tmp_path)


def test_threaded_must_be_a_boolean(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify.lint]\ncommands = ["x"]\nthreaded = 1\n')
    with pytest.raises(ConfigError, match="true or false"):
        load_config(tmp_path)
```

*(`write_config` ist der bestehende Helfer der Datei; falls er dort anders heißt, wird der vorhandene benutzt.)*

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_config.py -v -k "command or threaded or table"
```

Expected: FAIL — `assert 'gdlint .' == ('gdlint .',)`.

- [ ] **Step 3: Write the implementation**

In `src/ultraloom/config.py`:

```python
@dataclass(frozen=True, slots=True)
class Config:
    root: Path
    commands: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    threaded: frozenset[str] = frozenset()
    ...
```

Die Schleife über `_KINDS` ersetzen:

```python
    commands: dict[str, tuple[str, ...]] = {}
    threaded: set[str] = set()
    for kind in _KINDS:
        if kind not in verify:
            continue
        commands[kind], is_threaded = _commands_for(kind, verify[kind], path)
        if is_threaded:
            threaded.add(kind)
```

Und der Leser:

```python
def _commands_for(kind: str, value: object, path: Path) -> tuple[tuple[str, ...], bool]:
    """One kind's commands, from any of its three shapes.

    A string is one command, a list is several, a table is several plus the
    switches. TOML itself rules out the string-and-table collision: a key
    cannot be both, and the parser refuses the file before it reaches here.
    """
    if isinstance(value, str):
        return (_checked((value,), kind, path),), False
    if isinstance(value, list):
        return _checked(tuple(value), kind, path), False
    if isinstance(value, dict):
        raw = value.get("commands")
        if raw is None:
            raise ConfigError(f"{path}: [verify.{kind}] must name `commands`")
        if not isinstance(raw, list):
            raise ConfigError(f"{path}: [verify.{kind}].commands must be a list of strings")
        is_threaded = value.get("threaded", False)
        if not isinstance(is_threaded, bool):
            raise ConfigError(f"{path}: [verify.{kind}].threaded must be true or false")
        return _checked(tuple(raw), kind, path), is_threaded
    raise ConfigError(f"{path}: [verify].{kind} must be a string, a list of strings, or a table")


def _checked(commands: tuple[object, ...], kind: str, path: Path) -> tuple[str, ...]:
    """Every command is a non-blank string, checked before any prefix is prepended.

    With an [exec].prefix configured, a blank command line leaves the bare
    prefix, and a prefix that exits 0 turns a check nobody configured into a
    green line -- the one failure in this system that actually does damage.
    """
    if not commands:
        raise ConfigError(f"{path}: [verify.{kind}] names an empty list of commands")
    for command in commands:
        if not isinstance(command, str):
            raise ConfigError(f"{path}: [verify].{kind} must hold strings")
        if not command.strip():
            raise ConfigError(f"{path}: [verify].{kind} holds an empty command")
    return tuple(str(command) for command in commands)
```

In `src/ultraloom/checks.py` die Auflösung anpassen — sie liefert weiterhin **ein** Argv, mehrere kommen in Task 6:

```python
    if kind in config.commands:
        words = tuple(shlex.split(config.commands[kind][0]))
        return Command(kind, config.exec_prefix + words, "config")
```

Der bisherige Leer-Check in `resolve_check` entfällt: `load_config` weist die leere Zeichenkette jetzt beim Laden ab. Ein `Config`-Objekt, das Fremdcode von Hand mit einem leeren Kommando baut, ist ein Programmierfehler — der bisherige Test dafür wird auf `load_config` umgeschrieben, nicht gelöscht.

- [ ] **Step 4: Run the whole suite**

```bash
uv run pytest -q
```

Expected: PASS. Jede Stelle, die `commands={"lint": "..."}` schreibt, wird auf `("...",)` gezogen — auch der Test aus Task 3.

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/config.py src/ultraloom/checks.py tests/test_config.py tests/test_checks.py
git commit -m "Let a check kind name more than one command"
```

---

### Task 5: `max_parallel` und `[verify.after]`

**Files:**
- Modify: `src/ultraloom/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `Config` aus Task 4
- Produces:
  - `Config.max_parallel: int` (Vorgabe `os.process_cpu_count() or 1`)
  - `Config.after: Mapping[str, str] = {}`

- [ ] **Step 1: Write the failing tests**

```python
def test_max_parallel_defaults_to_the_available_cpus(tmp_path: Path) -> None:
    assert load_config(tmp_path).max_parallel == (os.process_cpu_count() or 1)


def test_max_parallel_can_be_set(tmp_path: Path) -> None:
    write_config(tmp_path, "[verify]\nmax_parallel = 2\n")
    assert load_config(tmp_path).max_parallel == 2


def test_max_parallel_must_be_positive(tmp_path: Path) -> None:
    write_config(tmp_path, "[verify]\nmax_parallel = 0\n")
    with pytest.raises(ConfigError, match="greater than zero"):
        load_config(tmp_path)


def test_after_names_one_predecessor_per_kind(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify.after]\ncoverage = "test"\n')
    assert load_config(tmp_path).after == {"coverage": "test"}


def test_after_refuses_an_unknown_kind(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify.after]\ncoverage = "typecheck"\n')
    with pytest.raises(ConfigError, match="unknown check"):
        load_config(tmp_path)


def test_after_refuses_a_cycle(tmp_path: Path) -> None:
    """A cycle is caught when the file is read, never as a run that never ends."""
    write_config(tmp_path, '[verify.after]\ncoverage = "test"\ntest = "coverage"\n')
    with pytest.raises(ConfigError, match="cycle"):
        load_config(tmp_path)


def test_after_refuses_a_kind_that_waits_for_itself(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify.after]\ntest = "test"\n')
    with pytest.raises(ConfigError, match="cycle"):
        load_config(tmp_path)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_config.py -v -k "max_parallel or after"
```

Expected: FAIL — `AttributeError: 'Config' object has no attribute 'max_parallel'`.

- [ ] **Step 3: Write the implementation**

```python
import os


def _default_parallelism() -> int:
    # process_cpu_count honours a CPU affinity mask, which a build agent may
    # well set; cpu_count would promise cores this process cannot use.
    return os.process_cpu_count() or 1
```

`Config` erweitern:

```python
    max_parallel: int = field(default_factory=_default_parallelism)
    after: Mapping[str, str] = field(default_factory=dict)
```

Im Parser:

```python
    max_parallel = verify.get("max_parallel", _default_parallelism())
    if not isinstance(max_parallel, int) or isinstance(max_parallel, bool):
        raise ConfigError(f"{path}: [verify].max_parallel must be an integer")
    if max_parallel <= 0:
        raise ConfigError(f"{path}: [verify].max_parallel must be greater than zero")

    after = _after_from(_table(verify, "after", path), path)
```

Und die Prüfung des Graphen:

```python
def _after_from(raw: Mapping[str, Any], path: Path) -> Mapping[str, str]:
    """The dependency edges, validated so a bad one cannot become a run that hangs."""
    edges: dict[str, str] = {}
    for kind, predecessor in raw.items():
        if not isinstance(predecessor, str):
            raise ConfigError(f"{path}: [verify.after].{kind} must be a string")
        for name in (kind, predecessor):
            if name not in _CHECK_KINDS:
                raise ConfigError(f"{path}: [verify.after] names unknown check {name!r}")
        edges[kind] = predecessor

    for kind in edges:
        seen = {kind}
        current = kind
        while current in edges:
            current = edges[current]
            if current in seen:
                raise ConfigError(f"{path}: [verify.after] has a cycle through {current!r}")
            seen.add(current)
    return edges
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/config.py tests/test_config.py
git commit -m "Read the parallelism cap and the ordering between checks"
```

---

### Task 6: `Command` trägt mehrere Argv

**Files:**
- Modify: `src/ultraloom/checks.py` (`Command`, `resolve_check`, `_run_command`)
- Modify: `src/ultraloom/cli.py` (falls `Command.argv` dort gelesen wird)
- Test: `tests/test_checks.py`

**Interfaces:**
- Consumes: `Config.commands`, `Config.threaded` aus Task 4
- Produces:
  - `Command(kind: str, argvs: tuple[tuple[str, ...], ...], source: str, measure: tuple[str, ...] = (), threaded: bool = False, warning: str = "")` — **`argv` heißt jetzt `argvs` und ist ein Tupel von Argv**

- [ ] **Step 1: Write the failing tests**

```python
def test_a_configured_kind_resolves_all_its_commands(tmp_path: Path) -> None:
    config = Config(root=tmp_path, commands={"lint": ("first .", "second .")})
    command = resolve_check("lint", config)
    assert command.argvs == (("first", "."), ("second", "."))


def test_every_command_gets_the_exec_prefix(tmp_path: Path) -> None:
    config = Config(
        root=tmp_path,
        commands={"lint": ("first", "second")},
        exec_prefix=("docker", "compose", "exec", "-T", "app"),
    )
    command = resolve_check("lint", config)
    assert all(argv[:5] == ("docker", "compose", "exec", "-T", "app") for argv in command.argvs)


def test_the_threaded_switch_reaches_the_command(tmp_path: Path) -> None:
    config = Config(root=tmp_path, commands={"lint": ("a", "b")}, threaded=frozenset({"lint"}))
    assert resolve_check("lint", config).threaded


def test_every_command_runs_even_after_a_red_one(tmp_path: Path) -> None:
    """A half list of findings costs the repairer a whole extra round."""
    python_project(tmp_path)
    config = Config(
        root=tmp_path,
        commands={
            "lint": (
                py("import sys; print('first says no'); sys.exit(1)"),
                py("print('second still ran')"),
            )
        },
    )

    result = run_check("lint", config)

    assert not result.ok
    assert "first says no" in result.output
    assert "second still ran" in result.output


def test_several_commands_are_labelled_in_the_report(tmp_path: Path) -> None:
    python_project(tmp_path)
    config = Config(root=tmp_path, commands={"lint": (py("print('a')"), py("print('b')"))})

    output = run_check("lint", config).output

    assert output.count("$ ") == 2, "each command names itself, or the report cannot be read"


def test_a_single_command_keeps_the_report_it_always_had(tmp_path: Path) -> None:
    python_project(tmp_path)
    config = Config(root=tmp_path, commands={"lint": (py("print('only')"),)})
    assert run_check("lint", config).output == "only\n"


def test_a_threaded_kind_runs_its_commands_at_the_same_time(tmp_path: Path) -> None:
    python_project(tmp_path)
    sleeper = py("import time; time.sleep(2)")
    config = Config(
        root=tmp_path,
        commands={"lint": (sleeper, sleeper)},
        threaded=frozenset({"lint"}),
        max_parallel=4,
    )

    started = time.monotonic()
    run_check("lint", config)
    elapsed = time.monotonic() - started

    # Two two-second sleeps: sequential is 4s, concurrent is 2s. The bound sits
    # between them with room for a loaded machine, which is why it is 3.5 and
    # not 2.5. Relative and generous on purpose -- this is the suite's second
    # wall-clock test.
    assert elapsed < 3.5, f"the two commands took {elapsed:.1f}s; they did not overlap"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_checks.py -v -k "argvs or commands or threaded or labelled"
```

Expected: FAIL — `AttributeError: 'Command' object has no attribute 'argvs'`.

- [ ] **Step 3: Write the implementation**

```python
@dataclass(frozen=True, slots=True)
class Command:
    """A resolved check: what to run, and where the decision came from.

    `argvs` is a *sequence* because a kind may have several equal-ranking
    commands -- two linters that check different things. They all run, even
    after a red one: the point of the chain is a complete list of findings,
    and half a list costs the repairer a whole extra round.

    `measure` is the step that prepares what `argvs` then reads, and it is not
    equal-ranking: a report over data nobody measured is meaningless, so its
    failure stops the check.
    """

    kind: str
    argvs: tuple[tuple[str, ...], ...]
    source: str
    measure: tuple[str, ...] = ()
    threaded: bool = False
    # Prepended to the output when this check reads something no command in
    # this run produced. A warning and never a verdict -- see spec §8.
    warning: str = ""
```

`resolve_check`, konfigurierter Zweig:

```python
    if kind in config.commands:
        argvs = tuple(config.exec_prefix + tuple(shlex.split(line)) for line in config.commands[kind])
        return Command(kind, argvs, "config", threaded=kind in config.threaded)
```

Der Coverage-, Skript- und Preset-Zweig liefern je ein Argv, verpackt als Ein-Element-Tupel: `Command(kind, (argv,), source)`.

Und die Ausführung:

```python
def _run_command(command: Command, config: Config, gate: Semaphore | None = None) -> CheckResult:
    gate = gate or BoundedSemaphore(config.max_parallel)
    if command.measure:
        measured = _run(command.measure, command.kind, config, command.source, gate)
        if not measured.ok:
            return measured

    if command.threaded and len(command.argvs) > 1:
        with ThreadPoolExecutor(max_workers=len(command.argvs)) as pool:
            results = tuple(
                pool.map(lambda argv: _run(argv, command.kind, config, command.source, gate),
                         command.argvs)
            )
    else:
        results = tuple(
            _run(argv, command.kind, config, command.source, gate) for argv in command.argvs
        )

    return _merged(command, results)


def _merged(command: Command, results: tuple[CheckResult, ...]) -> CheckResult:
    """One verdict and one report out of however many commands ran.

    With a single command the report is byte for byte what it always was: a
    heading over a lone command would change every existing output for nothing.
    The order is the configured one, never the order they finished in -- a
    report whose lines move between runs cannot be compared.
    """
    if len(results) == 1:
        output = results[0].output
    else:
        output = "\n\n".join(
            f"$ {shlex.join(argv)}\n{result.output.rstrip()}"
            for argv, result in zip(command.argvs, results, strict=True)
        )
    if command.warning:
        output = f"{command.warning}\n{output}"
    return CheckResult(
        command.kind,
        all(result.ok for result in results),
        output,
        command.source,
    )
```

`_run` bekommt den geteilten Deckel:

```python
def _run(argv, kind, config, source, gate: Semaphore) -> CheckResult:
    with gate:
        try:
            completed = process.run(argv, cwd=config.root, timeout=config.timeout)
        except OSError as error:
            ...
```

Importe: `from threading import BoundedSemaphore, Semaphore`.

- [ ] **Step 4: Run the whole suite**

```bash
uv run pytest -q
```

Expected: PASS. Jeder bestehende Test, der `command.argv` liest, wird auf `command.argvs[0]` gezogen.

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/checks.py src/ultraloom/cli.py tests/test_checks.py
git commit -m "Run every command a check kind names, labelled and capped"
```

---

### Task 7: `Preset` als Dataclass, mit knappen Werkzeugmodi

**Files:**
- Modify: `src/ultraloom/checks.py` (`PRESETS`, `resolve_check`, `_preset_godot_binary`)
- Test: `tests/test_checks.py`

**Interfaces:**
- Consumes: `Command` aus Task 6
- Produces:
  - `Preset(argv: tuple[str, ...], measuring: tuple[str, ...] = (), measure: tuple[str, ...] = (), after: str = "")`
  - `PRESETS: Mapping[str, Mapping[str, Preset]]`

- [ ] **Step 1: Write the failing tests**

```python
from ultraloom.checks import PRESETS, Preset


def test_the_python_test_preset_can_measure_when_asked(tmp_path: Path) -> None:
    assert PRESETS["pyproject.toml"]["test"].measuring[:4] == ("uv", "run", "coverage", "run")


def test_the_python_coverage_preset_waits_for_test(tmp_path: Path) -> None:
    assert PRESETS["pyproject.toml"]["coverage"].after == "test"


def test_the_python_coverage_preset_can_still_measure_alone(tmp_path: Path) -> None:
    assert PRESETS["pyproject.toml"]["coverage"].measure[:4] == ("uv", "run", "coverage", "run")


def test_the_godot_coverage_preset_waits_and_cannot_measure_itself(tmp_path: Path) -> None:
    """In Godot the report is a by-product of the suite; there is no second way to get it."""
    preset = PRESETS["project.godot"]["coverage"]
    assert preset.after == "test"
    assert preset.measure == ()


def test_the_node_preset_stays_one_stage(tmp_path: Path) -> None:
    assert PRESETS["package.json"]["coverage"].after == ""


def test_the_presets_ask_their_tools_to_be_terse(tmp_path: Path) -> None:
    """Every token of a check report is a token the repairer pays for, every round."""
    assert "--output-format=concise" in PRESETS["pyproject.toml"]["lint"].argv
    assert "--tb=short" in PRESETS["pyproject.toml"]["test"].argv
    assert "--skip-covered" in PRESETS["pyproject.toml"]["coverage"].argv
    assert "--no-error-summary" in PRESETS["pyproject.toml"]["types"].argv


def test_a_preset_resolves_to_one_command(tmp_path: Path) -> None:
    python_project(tmp_path)
    command = resolve_check("lint", Config(root=tmp_path))
    assert command.source == "preset"
    assert len(command.argvs) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_checks.py -v -k preset
```

Expected: FAIL — `ImportError: cannot import name 'Preset'`.

- [ ] **Step 3: Write the implementation**

```python
@dataclass(frozen=True, slots=True)
class Preset:
    """What a language's tool for one check kind looks like.

    Three fields with distinct jobs, and the distinction is the whole point:

    `measuring` — this check can measure as a by-product, if somebody needs it
    `after`     — this check reads what another one leaves behind
    `measure`   — if nobody measures for me, I measure myself
    """

    argv: tuple[str, ...]
    measuring: tuple[str, ...] = ()
    measure: tuple[str, ...] = ()
    after: str = ""


_PYTEST = ("uv", "run", "pytest", "-q", "--tb=short", "--no-header")
_COVERAGE_RUN = ("uv", "run", "coverage", "run", "-m", "pytest", "-q", "--tb=short", "--no-header")

PRESETS: Mapping[str, Mapping[str, Preset]] = {
    "pyproject.toml": {
        "lint": Preset(("uvx", "ruff", "check", ".", "--output-format=concise")),
        "types": Preset(("uvx", "mypy", "--no-error-summary", "--no-pretty")),
        # `measuring` rather than a second suite run: with coverage in the same
        # run, `test` measures as it goes and the report reads what it wrote.
        # Alone, `test` stays the fast path and pays no measuring overhead.
        "test": Preset(_PYTEST, measuring=_COVERAGE_RUN),
        # `--skip-covered --skip-empty`: the files at 100% are the ones nobody
        # needs to read, and in a project that holds the line they are almost
        # all of them.
        "coverage": Preset(
            ("uv", "run", "coverage", "report", "--skip-covered", "--skip-empty"),
            measure=_COVERAGE_RUN,
            after="test",
        ),
    },
    "package.json": {
        "lint": Preset(("eslint", ".")),
        "types": Preset(("tsc", "--noEmit")),
        "test": Preset(("vitest", "run")),
        # One stage: vitest measures and reports in the same run, so there is
        # nothing for coverage to wait on.
        "coverage": Preset(("vitest", "run", "--coverage")),
    },
    "project.godot": {
        "lint": Preset(("uvx", "gdlint", ".")),
        "test": Preset(("godot", "--headless", "--quit")),
        # No `measure` and no `measuring`: in Godot the report *is* a
        # by-product of the suite, and there is no second way to produce it.
        # A coverage check without a test run in the same pass therefore reads
        # whatever the last run left -- which is what the warning says.
        "coverage": Preset(("uvx", "nano-coverage", "report"), after="test"),
    },
}
```

`resolve_check` im Preset-Zweig:

```python
    preset = PRESETS[marker]
    if kind not in preset:
        raise CheckUnavailableError(
            f"{_LANGUAGE_NAMES[marker]} has no {kind} tool — a known limitation, not a passed check"
        )
    entry = preset[kind]
    return Command(
        kind,
        (config.exec_prefix + entry.argv,),
        "preset",
        measure=config.exec_prefix + entry.measure if entry.measure else (),
    )
```

Die Prüfung „mehr als zwei Schritte" entfällt — die Dataclass macht sie unmöglich. `_preset_godot_binary` liest `PRESETS["project.godot"]["test"].argv[0]`.

**Hinweis:** Das Godot-Coverage-Kommando (`nano-coverage report`) ist eine Vermutung über das Werkzeug, das space benutzt. Der Umsetzende prüft den tatsächlichen Aufruf in space' `.claude/hooks/coverage_gate.py` und setzt ihn ein; findet sich keiner, bleibt `coverage` bei Godot **ohne** Preset (wie heute) und behält nur `after` über `[verify.after]`. Das ist eine Feststellung, keine Entwurfsfrage — aber sie gehört in den Commit.

- [ ] **Step 4: Run the whole suite**

```bash
uv run pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/checks.py tests/test_checks.py
git commit -m "Give presets a shape that can say who measures"
```

---

### Task 8: Die `alongside`-Regel

**Files:**
- Modify: `src/ultraloom/checks.py` (`resolve_check`, `run_check`)
- Test: `tests/test_checks.py`

**Interfaces:**
- Consumes: `Preset` aus Task 7
- Produces:
  - `resolve_check(kind: str, config: Config, *, alongside: frozenset[str] = frozenset()) -> Command`
  - `run_check(kind: str, config: Config, alongside: frozenset[str] = frozenset()) -> CheckResult`

- [ ] **Step 1: Write the failing tests**

```python
def test_test_measures_when_coverage_runs_too(tmp_path: Path) -> None:
    python_project(tmp_path)
    command = resolve_check("test", Config(root=tmp_path), alongside=frozenset({"test", "coverage"}))
    assert command.argvs[0][:4] == ("uv", "run", "coverage", "run")


def test_test_alone_stays_the_fast_path(tmp_path: Path) -> None:
    python_project(tmp_path)
    command = resolve_check("test", Config(root=tmp_path), alongside=frozenset({"test"}))
    assert command.argvs[0][:3] == ("uv", "run", "pytest")


def test_coverage_drops_its_own_measuring_when_test_measures_for_it(tmp_path: Path) -> None:
    python_project(tmp_path)
    command = resolve_check(
        "coverage", Config(root=tmp_path), alongside=frozenset({"test", "coverage"})
    )
    assert command.measure == (), "the suite must not run twice in one pass"


def test_coverage_alone_measures_for_itself(tmp_path: Path) -> None:
    python_project(tmp_path)
    command = resolve_check("coverage", Config(root=tmp_path), alongside=frozenset({"coverage"}))
    assert command.measure[:4] == ("uv", "run", "coverage", "run")


def test_the_empty_default_behaves_like_running_alone(tmp_path: Path) -> None:
    """Every existing caller keeps the behaviour it had."""
    python_project(tmp_path)
    assert resolve_check("coverage", Config(root=tmp_path)).measure[:4] == (
        "uv", "run", "coverage", "run",
    )


def test_a_configured_test_command_never_counts_as_measuring(tmp_path: Path) -> None:
    """ultraloom cannot know whether a foreign test command measures, so it does not guess."""
    python_project(tmp_path)
    config = Config(root=tmp_path, commands={"test": ("my-own-suite",)})
    command = resolve_check("coverage", config, alongside=frozenset({"test", "coverage"}))
    assert command.measure[:4] == ("uv", "run", "coverage", "run")


def test_godot_coverage_warns_when_nothing_measured_for_it(tmp_path: Path) -> None:
    godot_project(tmp_path)
    command = resolve_check("coverage", Config(root=tmp_path), alongside=frozenset({"coverage"}))
    assert "lief in diesem Lauf nicht" in command.warning


def test_godot_coverage_is_quiet_when_test_ran(tmp_path: Path) -> None:
    godot_project(tmp_path)
    command = resolve_check(
        "coverage", Config(root=tmp_path), alongside=frozenset({"test", "coverage"})
    )
    assert command.warning == ""
```

*(`godot_project` ist der bestehende Helfer der Datei.)*

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_checks.py -v -k "alongside or measures or warns"
```

Expected: FAIL — `TypeError: resolve_check() got an unexpected keyword argument 'alongside'`.

- [ ] **Step 3: Write the implementation**

```python
def resolve_check(
    kind: str,
    config: Config,
    *,
    alongside: frozenset[str] = frozenset(),
) -> Command:
    """Find the command for this check, or refuse to guess.

    `alongside` names the kinds running in this same pass. It decides who
    measures: a check that can measure as a by-product does so when something
    depends on it, and a check that depends on it then skips its own measuring
    step. Empty by default, so a caller that resolves one kind on its own gets
    a check that stands alone -- correct, and possibly slower than what the
    scheduler would have built. That silent precedence is the price of a
    signature that does not force every caller to know about the others.
    """
```

Der Preset-Zweig wird zu:

```python
    entry = preset[kind]
    argv = entry.argv
    measure = entry.measure
    warning = ""

    if entry.measuring and _has_dependant(kind, marker, config, alongside):
        # Something in this pass reads what this check leaves behind, so it
        # measures as it goes -- and that dependant drops its own measuring
        # step below. One suite run instead of two.
        argv = entry.measuring

    if entry.after:
        if _measures_for(entry.after, marker, config, alongside):
            measure = ()
        elif not measure:
            warning = (
                f"Achtung: `{entry.after}` lief in diesem Lauf nicht; "
                "dieser Bericht kann von einem älteren Lauf stammen."
            )

    return Command(
        kind,
        (config.exec_prefix + argv,),
        "preset",
        measure=config.exec_prefix + measure if measure else (),
        warning=warning,
    )
```

Die zwei Helfer:

```python
def _measures_for(kind: str, marker: str, config: Config, alongside: frozenset[str]) -> bool:
    """Whether `kind` runs in this pass *and* measures while it does.

    A kind the project configured itself never counts: ultraloom cannot know
    whether a foreign test command measures, and guessing here would produce a
    coverage report over data nobody wrote.
    """
    if kind not in alongside or kind in config.commands:
        return False
    if _script_for(kind, config.root) is not None:
        return False
    entry = PRESETS[marker].get(kind)
    return entry is not None and bool(entry.measuring)


def _has_dependant(kind: str, marker: str, config: Config, alongside: frozenset[str]) -> bool:
    """Whether some kind in this pass waits for `kind`."""
    return any(
        _predecessor_of(other, marker, config) == kind for other in alongside if other != kind
    )


def _predecessor_of(kind: str, marker: str, config: Config) -> str:
    """What this kind waits for: the project's answer first, then the language's."""
    if kind in config.after:
        return config.after[kind]
    entry = PRESETS[marker].get(kind)
    return entry.after if entry is not None else ""
```

`run_check` reicht `alongside` durch:

```python
def run_check(
    kind: str, config: Config, alongside: frozenset[str] = frozenset()
) -> CheckResult:
    command = resolve_check(kind, config, alongside=alongside)
    ...
```

- [ ] **Step 4: Run the whole suite**

```bash
uv run pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/checks.py tests/test_checks.py
git commit -m "Let the requested set decide which check does the measuring"
```

---

### Task 9: `run_kinds` — Stufen, `blocked`, ein Pool

**Files:**
- Modify: `src/ultraloom/checks.py` (`run_all` → `run_kinds`, `_run_or_report`)
- Test: `tests/test_checks.py`

**Interfaces:**
- Consumes: `run_check`, `_predecessor_of` aus Task 8
- Produces:
  - `BLOCKED: str = "blocked"`
  - `CheckRunner = Callable[[str, Config, frozenset[str]], CheckResult]`
  - `run_kinds(kinds: Sequence[str], config: Config, runner: CheckRunner = run_check) -> tuple[CheckResult, ...]`
  - `run_all(config: Config) -> tuple[CheckResult, ...]` — bleibt, delegiert

- [ ] **Step 1: Write the failing tests**

```python
from ultraloom.checks import BLOCKED, run_kinds


def _fake(record: list[str], red: set[str] | None = None) -> CheckRunner:
    red = red or set()

    def runner(kind: str, config: Config, alongside: frozenset[str]) -> CheckResult:
        record.append(kind)
        return CheckResult(kind, kind not in red, "", "fake")

    return runner


def test_coverage_runs_after_test(tmp_path: Path) -> None:
    python_project(tmp_path)
    record: list[str] = []
    run_kinds(("lint", "types", "test", "coverage"), Config(root=tmp_path), _fake(record))
    assert record.index("coverage") > record.index("test")


def test_a_red_predecessor_blocks_its_dependant(tmp_path: Path) -> None:
    python_project(tmp_path)
    results = run_kinds(
        ("test", "coverage"), Config(root=tmp_path), _fake([], red={"test"})
    )
    coverage = next(result for result in results if result.kind == "coverage")
    assert not coverage.ok
    assert coverage.source == BLOCKED
    assert "test" in coverage.output


def test_a_blocked_check_never_starts_its_tool(tmp_path: Path) -> None:
    python_project(tmp_path)
    record: list[str] = []
    run_kinds(("test", "coverage"), Config(root=tmp_path), _fake(record, red={"test"}))
    assert "coverage" not in record


def test_blocking_is_transitive(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify.after]\ncoverage = "test"\ntest = "lint"\n')
    python_project(tmp_path)
    results = run_kinds(
        ("lint", "test", "coverage"), load_config(tmp_path), _fake([], red={"lint"})
    )
    assert [result.source for result in results if result.kind != "lint"] == [BLOCKED, BLOCKED]


def test_an_unavailable_predecessor_blocks_too(tmp_path: Path) -> None:
    """Red is red: a missing tool leaves nothing for the dependant to read either."""
    def runner(kind: str, config: Config, alongside: frozenset[str]) -> CheckResult:
        if kind == "test":
            raise CheckUnavailableError("no suite here")
        return CheckResult(kind, True, "", "fake")

    python_project(tmp_path)
    results = run_kinds(("test", "coverage"), Config(root=tmp_path), runner)
    assert [result.source for result in results] == ["unavailable", BLOCKED]


def test_a_kind_whose_predecessor_was_not_asked_for_runs_at_once(tmp_path: Path) -> None:
    python_project(tmp_path)
    record: list[str] = []
    run_kinds(("coverage",), Config(root=tmp_path), _fake(record))
    assert record == ["coverage"]


def test_the_results_keep_the_order_they_were_asked_in(tmp_path: Path) -> None:
    python_project(tmp_path)
    results = run_kinds(("coverage", "lint", "test"), Config(root=tmp_path), _fake([]))
    assert [result.kind for result in results] == ["coverage", "lint", "test"]


def test_every_check_learns_who_else_is_running(tmp_path: Path) -> None:
    seen: list[frozenset[str]] = []

    def runner(kind: str, config: Config, alongside: frozenset[str]) -> CheckResult:
        seen.append(alongside)
        return CheckResult(kind, True, "", "fake")

    python_project(tmp_path)
    run_kinds(("test", "coverage"), Config(root=tmp_path), runner)
    assert all(group == frozenset({"test", "coverage"}) for group in seen)


def test_a_check_that_blows_up_does_not_discard_the_others(tmp_path: Path) -> None:
    def runner(kind: str, config: Config, alongside: frozenset[str]) -> CheckResult:
        if kind == "lint":
            raise RuntimeError("boom")
        return CheckResult(kind, True, "", "fake")

    python_project(tmp_path)
    results = run_kinds(("lint", "types"), Config(root=tmp_path), runner)
    assert [result.source for result in results] == ["error", "fake"]


def test_run_all_still_runs_every_kind(tmp_path: Path) -> None:
    python_project(tmp_path)
    assert tuple(result.kind for result in run_all(Config(root=tmp_path))) == KINDS
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_checks.py -v -k "run_kinds or blocked or stage or transitive"
```

Expected: FAIL — `ImportError: cannot import name 'run_kinds'`.

- [ ] **Step 3: Write the implementation**

```python
# A red result whose cause is another check: reported with a source of its own,
# because neither "failed" nor "unavailable" says that this check never ran and
# will run fine as soon as its predecessor is green.
BLOCKED = "blocked"

type CheckRunner = Callable[[str, Config, frozenset[str]], CheckResult]


def run_kinds(
    kinds: Sequence[str],
    config: Config,
    runner: CheckRunner = run_check,
) -> tuple[CheckResult, ...]:
    """Run these checks in dependency order and report them in the order asked.

    Concurrent within a stage with plain threads: subprocess waiting releases
    the GIL, so parallel waiting reaches most of its ceiling without a special
    interpreter (spec 9.4). Sequential *between* stages, because a check that
    reads what another one writes cannot start at the same time as it.

    The one scheduler both callers use. `ultraloom check all` and the
    verify_until_green flow ran their own pools once, and a stage built into
    only one of them would leave the flow -- the reason this exists -- running
    unordered.
    """
    if not kinds:
        raise ValueError("run_kinds needs at least one check; a run that checks nothing is not a pass")

    alongside = frozenset(kinds)
    marker = _marker(config.root)
    results: dict[str, CheckResult] = {}

    for stage in _stages(kinds, marker, config):
        pending = tuple(kind for kind in stage if _blocker(kind, marker, config, results) is None)
        for kind in stage:
            blocker = _blocker(kind, marker, config, results)
            if blocker is not None:
                results[kind] = CheckResult(
                    kind, False, f"läuft nicht, weil `{blocker}` rot war", BLOCKED
                )
        if not pending:
            continue
        with ThreadPoolExecutor(max_workers=len(pending)) as pool:
            for result in pool.map(
                lambda kind: _run_or_report(kind, config, alongside, runner), pending
            ):
                results[result.kind] = result

    return tuple(results[kind] for kind in kinds)


def _stages(kinds: Sequence[str], marker: str | None, config: Config) -> tuple[tuple[str, ...], ...]:
    """The requested kinds, grouped so that nothing runs before what it reads.

    A kind whose predecessor was not requested lands in the first stage: it has
    nothing to wait for in *this* run. Whether it then reads a stale report is
    a question ultraloom cannot answer, and `resolve_check` says so in a
    warning rather than guessing.
    """
    requested = set(kinds)
    depth: dict[str, int] = {}

    def level(kind: str) -> int:
        if kind in depth:
            return depth[kind]
        predecessor = _predecessor_of(kind, marker, config) if marker else config.after.get(kind, "")
        # The config loader rejects cycles, so this recursion terminates.
        depth[kind] = level(predecessor) + 1 if predecessor in requested else 0
        return depth[kind]

    ordered: dict[int, list[str]] = {}
    for kind in kinds:
        ordered.setdefault(level(kind), []).append(kind)
    return tuple(tuple(ordered[key]) for key in sorted(ordered))


def _blocker(
    kind: str, marker: str | None, config: Config, results: Mapping[str, CheckResult]
) -> str | None:
    """The predecessor that failed, if there is one.

    Any red result blocks, `unavailable` and `unready` included: a report over
    a suite that never ran is worth exactly as much as one over a suite that
    failed. Transitive by construction -- a blocked check is itself red, so
    whatever waits on it is blocked in turn.
    """
    predecessor = _predecessor_of(kind, marker, config) if marker else config.after.get(kind, "")
    if not predecessor:
        return None
    result = results.get(predecessor)
    if result is None or result.ok:
        return None
    return predecessor


def _run_or_report(
    kind: str, config: Config, alongside: frozenset[str], runner: CheckRunner
) -> CheckResult:
    """One check, with any failure of its own turned into a visible result.

    Broad on purpose. `pool.map` re-raises the first exception when the tuple
    is built, so one check blowing up would discard the results of every check
    that already succeeded. `Exception`, deliberately not `BaseException`:
    KeyboardInterrupt and SystemExit must still stop the run.
    """
    try:
        return runner(kind, config, alongside)
    except CheckUnavailableError as error:
        # Reported, not skipped: a run that looks green because nothing ran is
        # the one failure in this system that actually does damage.
        return CheckResult(kind, False, str(error), "unavailable")
    except Exception as error:
        return CheckResult(kind, False, f"{type(error).__name__}: {error}", "error")


def run_all(config: Config) -> tuple[CheckResult, ...]:
    """Every check this project has, in the fixed order of KINDS."""
    return run_kinds(KINDS, config)
```

**Hinweis:** `_predecessor_of` aus Task 8 nimmt `marker: str`; hier kann `marker` `None` sein (ein Projekt ohne erkennbare Sprache). Der Umsetzende zieht die `None`-Behandlung in `_predecessor_of` hinein, statt sie an drei Aufrufstellen zu wiederholen — dann verschwinden die `if marker else`-Zweige oben.

- [ ] **Step 4: Run the whole suite**

```bash
uv run pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/checks.py tests/test_checks.py
git commit -m "Give the check chain one scheduler with stages"
```

---

### Task 10: Der Ablaufknoten benutzt den Scheduler

**Files:**
- Modify: `src/ultraloom/flows/verify_until_green.py:56-121` (`make_check`, `_result_for`, `_out_of_reach`, `_render`)
- Test: `tests/flows/test_verify_until_green.py`

**Interfaces:**
- Consumes: `run_kinds`, `BLOCKED`, `CheckRunner` aus Task 9
- Produces: unveränderte `VerifyState`-Felder; `_render` bekommt einen Block für blockierte Prüfungen

- [ ] **Step 1: Write the failing tests**

```python
from ultraloom.checks import BLOCKED


def test_a_blocked_check_is_not_out_of_reach() -> None:
    """It closes itself the moment `test` goes green -- giving up on it would end
    the flow at every ordinary red test."""
    from ultraloom.flows.verify_until_green import _out_of_reach

    assert not _out_of_reach(CheckResult("coverage", False, "", BLOCKED))


def test_the_node_runs_checks_in_dependency_order(tmp_path: Path) -> None:
    record: list[str] = []

    def runner(kind: str, config: Config, alongside: frozenset[str]) -> CheckResult:
        record.append(kind)
        return CheckResult(kind, True, "", "fake")

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    check = make_check(Config(root=tmp_path), runner)
    check(VerifyState(kinds=("test", "coverage")))

    assert record.index("coverage") > record.index("test")


def test_the_report_names_what_did_not_run(tmp_path: Path) -> None:
    def runner(kind: str, config: Config, alongside: frozenset[str]) -> CheckResult:
        return CheckResult(kind, kind != "test", "suite is red", "fake")

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    check = make_check(Config(root=tmp_path), runner)
    delta = check(VerifyState(kinds=("test", "coverage")))

    assert "Nicht gelaufen, weil ein Vorgänger rot war: coverage" in delta["report"]
    assert "coverage" in delta["failing"], "a check that did not run is never a passed check"
    assert "coverage" not in delta["unfixable"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/flows/test_verify_until_green.py -v -k "blocked or dependency or did_not_run"
```

Expected: FAIL — `_out_of_reach` kennt `blocked` nicht bzw. der Knoten läuft ungeordnet.

- [ ] **Step 3: Write the implementation**

`make_check` verliert seinen Pool:

```python
def make_check(config: Config, runner: CheckRunner = run_check) -> Callable[[VerifyState], Delta]:
    """The `check` node, bound to one project's configuration.

    The runner is a parameter so the flow's own tests never start a real tool:
    a test that shells out to ruff measures ruff.
    """

    def check(state: VerifyState) -> Delta:
        if not state.kinds:
            raise FlowExit(
                _EXIT_STILL_RED,
                "no checks to run: the state names none, so nothing was verified",
            )

        # checks.run_kinds and not a pool of our own: the ordering between
        # checks lives there, and a second scheduler here would run this flow
        # -- the one the ordering was written for -- unordered.
        results = run_kinds(state.kinds, config, runner)

        red = tuple(result for result in results if not result.ok)
        return {
            "failing": tuple(result.kind for result in red),
            "unfixable": tuple(result.kind for result in red if _out_of_reach(result)),
            "report": _render(red),
            "rounds": state.rounds + 1,
            "previous_failing": state.failing,
        }

    return check
```

`_result_for` wird gelöscht — `run_kinds` übersetzt jetzt selbst.

```python
def _out_of_reach(result: CheckResult) -> bool:
    """Whether a red check is one no repair pass could close.

    UNREADY joins UNAVAILABLE here. BLOCKED deliberately does not: a check that
    did not run because its predecessor was red closes itself the moment that
    predecessor goes green, and calling it out of reach would end the flow at
    every ordinary red test.
    """
    return result.kind in UNFIXABLE or result.source in (UNAVAILABLE, UNREADY)
```

Und `_render` bekommt seinen Schlussblock:

```python
def _render(red: tuple[CheckResult, ...]) -> str:
    blocked = tuple(result.kind for result in red if result.source == BLOCKED)
    findings = tuple(result for result in red if result.source != BLOCKED)
    rendered = ...  # unchanged rendering of `findings`
    if blocked:
        # Below the findings, not among them: it is nothing the repairer can
        # touch. Named all the same, so a report with a green lint, a green
        # types and a red test does not read as though coverage had been checked.
        rendered += f"\n\nNicht gelaufen, weil ein Vorgänger rot war: {', '.join(blocked)}"
    return rendered
```

- [ ] **Step 4: Run the whole suite**

```bash
uv run pytest -q
```

Expected: PASS. Jede Fake-Runner-Fixture der Datei bekommt den dritten Parameter `alongside`.

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/flows/verify_until_green.py tests/flows/test_verify_until_green.py
git commit -m "Run the flow's checks through the shared scheduler"
```

---

### Task 11: Die Ausgabe Richtung Modell kürzen

**Files:**
- Modify: `src/ultraloom/flows/verify_until_green.py` (`_render`)
- Test: `tests/flows/test_verify_until_green.py`

**Interfaces:**
- Consumes: `_render` aus Task 10
- Produces: `clip(output: str, *, limit: int = MODEL_OUTPUT_LINES) -> str` in `verify_until_green`, `MODEL_OUTPUT_LINES: int = 200`

- [ ] **Step 1: Write the failing tests**

```python
from ultraloom.flows.verify_until_green import MODEL_OUTPUT_LINES, clip


def test_short_output_is_untouched() -> None:
    assert clip("one\ntwo\n") == "one\ntwo\n"


def test_long_output_keeps_both_ends() -> None:
    lines = "\n".join(str(number) for number in range(1000))
    clipped = clip(lines)

    assert "0" in clipped.splitlines()[0]
    assert "999" in clipped.splitlines()[-1]
    assert len(clipped.splitlines()) < MODEL_OUTPUT_LINES + 5


def test_the_clip_says_how_much_it_dropped() -> None:
    clipped = clip("\n".join(str(number) for number in range(1000)))
    assert "Zeilen ausgelassen" in clipped


def test_more_of_the_tail_survives_than_of_the_head() -> None:
    """pytest writes its summary last, and the summary is the part worth keeping."""
    lines = "\n".join(str(number) for number in range(1000))
    body = clip(lines).splitlines()
    marker = next(index for index, line in enumerate(body) if "ausgelassen" in line)
    assert len(body) - marker > marker


def test_the_check_result_itself_keeps_everything(tmp_path: Path) -> None:
    """Clipped towards the model, complete in the journal -- or a run stops being auditable."""
    long_output = "\n".join(str(number) for number in range(1000))

    def runner(kind: str, config: Config, alongside: frozenset[str]) -> CheckResult:
        return CheckResult(kind, False, long_output, "fake")

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    results = run_kinds(("lint",), Config(root=tmp_path), runner)
    assert results[0].output == long_output
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/flows/test_verify_until_green.py -v -k clip
```

Expected: FAIL — `ImportError: cannot import name 'clip'`.

- [ ] **Step 3: Write the implementation**

```python
# Lines of one check's output the repairer gets to see. Every line past this is
# a line paid for in every round of the loop, and a red pytest run is easily
# two thousand of them.
MODEL_OUTPUT_LINES = 200


def clip(output: str, *, limit: int = MODEL_OUTPUT_LINES) -> str:
    """Head and tail of a long output, with the gap named.

    Tool-agnostic on purpose: a parser would need to know which tool wrote
    this, and behind an [exec].prefix, a wrapper script and `uv run` that is
    not reliably answerable.

    The tail gets two thirds of the budget. pytest writes its summary last, and
    so does coverage -- the end of a report is where the verdict lives.
    """
    lines = output.splitlines()
    if len(lines) <= limit:
        return output

    tail = limit * 2 // 3
    head = limit - tail
    dropped = len(lines) - limit
    return "\n".join(
        [*lines[:head], f"    [... {dropped} Zeilen ausgelassen ...]", *lines[-tail:]]
    )
```

In `_render` wird jede Prüfausgabe durch `clip` geschickt. `CheckResult.output` bleibt unangetastet.

- [ ] **Step 4: Run the whole suite**

```bash
uv run pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/flows/verify_until_green.py tests/flows/test_verify_until_green.py
git commit -m "Clip a long check report on its way to the repairer"
```

---

### Task 12: CLI und Modulgrenze nachziehen

**Files:**
- Modify: `src/ultraloom/cli.py` (`_check`)
- Modify: `tests/test_module_boundary.py` (Kommentar über den Thread-Pool)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_kinds`, `BLOCKED`
- Produces: keine neue API

- [ ] **Step 1: Write the failing tests**

```python
def test_check_all_reports_a_blocked_check_as_failed(tmp_path: Path, capsys) -> None:
    """Never green, never silent: the line is there and the exit code is red."""
    write_config(
        tmp_path,
        '[verify]\ntest = "python -c \\"raise SystemExit(1)\\""\n\n'
        '[verify.after]\ncoverage = "test"\n',
    )
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")

    code = main(["check", "all", "--root", str(tmp_path)])

    assert code == 1
    assert "coverage: failed [blocked]" in capsys.readouterr().out
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_cli.py -v -k blocked
```

- [ ] **Step 3: Write the implementation**

In `cli.py` bleibt `_check` fast unverändert — `run_all` delegiert bereits. Zu prüfen ist nur, dass `_report` die neue Quelle unverändert ausgibt (das tut es, sie steht in der Klammer) und dass der Aufruf `run_check(kind, config)` weiterhin ohne `alongside` gültig ist (ist er, Vorgabe leer).

Der Kommentar in `tests/test_module_boundary.py` über `run_all` und den Thread-Pool wird auf `run_kinds` gezogen — die Aussage („alles läuft in diesem einen Prozess, deshalb ist ein `sys.modules`-Schnappschuss eine vollständige Antwort") gilt weiter, der Name stimmt nicht mehr.

- [ ] **Step 4: Run the whole suite**

```bash
uv run pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/cli.py tests/test_cli.py tests/test_module_boundary.py
git commit -m "Show a blocked check on the command line"
```

---

### Task 13: Dokumentation

**Files:**
- Modify: `README.md`
- Modify: `docs/abläufe/verify-until-green.md`
- Modify: `docs/.superpowers/specs/2026-08-21-teilprojekt-2-backlog.md`
- Test: `tests/test_flow_docs.py` (läuft unverändert mit)

**Interfaces:**
- Consumes: alles Vorangegangene
- Produces: keine API

- [ ] **Step 1: README ergänzen**

Im Konfigurationsabschnitt, auf Deutsch:

- die drei Gestalten von `lint`/`types`/`test` mit dem TOML-Beispiel aus Spec §5
- `threaded`, `max_parallel`, `[verify.after]` mit je einem Satz zur Bedeutung
- die Stufentabelle aus Spec §3
- die Regel „wer misst" in einem Satz, plus die vier Fälle als Tabelle
- die Quelle `blocked` in der Liste der Quellen, mit dem Hinweis, dass sie rot ist und sich von selbst schließt
- **die Warnung aus dem space-Backlog**, die bisher nirgends steht: *Jedes Prüfkommando, das aus einem Hook-Skript stammt, ist daraufhin anzusehen, ob es seinen Befund im Exit-Code trägt.* Ein Hook, der sich immer mit 0 beendet, liest als bestandene Prüfung.

- [ ] **Step 2: Ablaufseite ergänzen**

`docs/abläufe/verify-until-green.md`:

- der Prüfknoten läuft jetzt gestuft; das Mermaid-Diagramm ändert sich **nicht** (der Graph hat dieselben Knoten und Kanten — `tests/test_flow_docs.py` prüft genau das und muss grün bleiben)
- ein Absatz über `blocked`: was der Reparateur sieht und warum er es nicht anfassen soll
- ein Absatz über die Kürzung: der Reparateur sieht bis zu 200 Zeilen je Prüfung, das Journal alles

- [ ] **Step 3: Backlog fortschreiben**

Die drei erledigten Punkte in `2026-08-21-teilprojekt-2-backlog.md` als **erledigt** markieren, mit einem Verweis auf diese Spec — nicht löschen: die Begründung, warum sie damals verschoben wurden, ist die Geschichte des Entwurfs.

Neu aufnehmen, was dieser Umfang gesehen und verschoben hat:
- Der `precommit`-Lauf in space misst zum ersten Mal, was `threaded` und die eingesparte zweite Suite bringen — die Zahlen gehören auf die Ablaufseite.
- Falls Task 2 ohne `CREATE_SUSPENDED` gebaut wurde: das Restfenster benennen.
- Falls Task 7 kein echtes Godot-Coverage-Kommando gefunden hat: als offener Punkt.

- [ ] **Step 4: Verify**

```bash
uv run pytest tests/test_flow_docs.py -v
```

Expected: PASS — die Seite deckt sich weiterhin mit dem Graphen.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/
git commit -m "Say in the documents what the check chain now does"
```

---

### Task 14: Der Nachweis — ein grüner `precommit`-Lauf in space

Das Abnahmekriterium. Die Unit-Tests können grün sein, während die Kette an genau dem Fall scheitert, für den sie geschrieben wurde; in diesem Projekt ist das schon einmal passiert.

**Files:**
- Modify: `<space>/.ultraloom/config.toml`
- Modify: `docs/abläufe/verify-until-green.md` (Lauf-Notiz)

**Interfaces:**
- Consumes: alles Vorangegangene
- Produces: keine API

- [ ] **Step 1: Vollständige Prüfung von ultraloom selbst**

```bash
uv run pytest -q && uvx ruff check . && uvx ruff format --check . && uvx mypy src tests
```

Expected: alles grün, keine unbegründeten Ausnahmen.

- [ ] **Step 2: Coverage messen**

```bash
uv run coverage run -m pytest -q && uv run coverage report --skip-covered --skip-empty
```

Expected: 100 %. Jede Lücke bekommt einen Test oder ein `# pragma: no cover  # <Grund>`.

- [ ] **Step 3: ultraloom in space installieren**

```bash
uv pip install -e ../ultraloom
```

**Hinweis:** ein **relativer** Pfad. Ein absoluter Windows-Pfad mit `#` darin wird von `uv` an der Raute abgeschnitten und die Meldung behauptet dann, dort liege kein Python-Projekt. Steht als bekannter Fremdwerkzeug-Fehler im Backlog.

- [ ] **Step 4: space' Konfiguration auf die neuen Schlüssel ziehen**

```toml
[verify.lint]
commands = ["gdlint .", "gdformat --check ."]
threaded = true

[verify.after]
coverage = "test"
```

`gdformat --check` kommt damit zum ersten Mal überhaupt zum Laufen — es fehlte bisher gegenüber dem, was space selbst prüft.

- [ ] **Step 5: Den Lauf fahren**

```bash
ultraloom check all --root .
```

Expected: `coverage` läuft **nach** `test` und findet den LCOV-Bericht, den die Suite geschrieben hat. Kein „no coverage report" mehr.

Dann der eigentliche Lauf:

```bash
ultraloom run verify_until_green --root . --checks precommit
```

- [ ] **Step 6: Was gemessen wurde, aufschreiben**

Auf die Ablaufseite, mit Zahlen statt Behauptungen: Dauer mit und ohne `threaded`, Dauer von `check all` in ultraloom selbst (eine Suite statt zwei), und ob der Lauf grün endete. Ein roter Lauf wird **nicht** wegdefiniert — er ist der nächste Befund und gehört genauso auf die Seite.

- [ ] **Step 7: Commit**

```bash
git add docs/abläufe/verify-until-green.md
git commit -m "Record what the first ordered check run measured"
```

---

## Selbstreview

**Spec-Abdeckung:** §2 → Task 9, 10. §3 → Task 5, 9. §4 → Task 7, 8. §5 → Task 4, 5. §6 → Task 6. §7 → Task 1, 2, 3. §8 → Task 6 (Zusammenführung, `warning`), 9 (`blocked`), 10 (`_out_of_reach`, `_render`), 12 (CLI). §9 → Task 7 (knappe Modi), 11 (Kürzung). §10 → keine Tasks, per Definition. §11 → die Testschritte jedes Tasks plus Task 14. §12 → Task 13 (Backlog).

**Bekannte Bruchstellen**, die der Umsetzende erwarten muss:
- `Config.commands` wird von `Mapping[str, str]` zu `Mapping[str, tuple[str, ...]]` (Task 4) — trifft jeden bestehenden Test, der `commands=` setzt.
- `Command.argv` heißt `argvs` und ist ein Tupel von Argv (Task 6).
- `CheckRunner` bekommt einen dritten Parameter (Task 9) — trifft jede Fake-Runner-Fixture in `tests/flows/`.
- `checks._decode` und `flows/verify_until_green._result_for` werden gelöscht.

Diese vier sind Absicht und stehen in der Spec; sie werden im jeweiligen Task mitgezogen, nicht als Folgearbeit vertagt.
