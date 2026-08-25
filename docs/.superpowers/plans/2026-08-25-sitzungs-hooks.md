# Sitzungs-Hooks — Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ultraloom bekommt vier Sitzungs-Hooks — `post-edit`, `stop`, `session-start` und `subagent-stop` — die eine Sitzung an den Stellen prüfen, an denen die Policy nichts sieht.

**Architecture:** Ein Paket `ultraloom.hooks` mit einem Modul je Ereignis, darunter ein gemeinsamer Zustandsspeicher je Sitzung und derselbe Adapterschnitt wie bei der Policy: eine Schicht liest Claude Codes Payload, die Funktionen darunter kennen sie nicht. Verdrahtet über ein Unterkommando `ultraloom hook <name>`.

**Tech Stack:** Python 3.13, `uv`, Standardbibliothek plus die vorhandenen ultraloom-Module (`checks`, `config`, `worktree`, `journal`, `gate`), pytest, ruff, mypy (strict), coverage.

**Spec:** `docs/.superpowers/specs/2026-08-25-sitzungs-hooks-design.md`

## Global Constraints

- **Gearbeitet wird in `C:/Users/micro/Documents/#GIT/ultraloom`**, nicht in einer Kopie unter `.claude/worktrees/`: die teilt Index und HEAD mit dem Hauptcheckout, und `git add` meldet dort keine Änderung. Vor dem ersten Commit `git rev-parse --git-dir --git-common-dir` lesen.
- **Zweig:** `feat/policy-baukasten`. Vor jedem Commit Zweig und HEAD lesen — eine fremde Sitzung im selben Checkout leert den Index, und git schreibt dann einen leeren Commit und meldet Erfolg.
- **TDD ohne Ausnahme:** erst der Test, laufen lassen, **als rot sehen**, dann die Implementierung.
- **100 % Coverage**, `fail_under = 100`. Jeder Ausschluss trägt seine Begründung im `# pragma`-Kommentar.
- **mypy strict**, kein `Any`, kein `type: ignore` ohne Begründung dahinter.
- **ruff** mit `select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF"]`, `line-length = 100`.
- **Sprache:** Docstrings, Kommentare, Meldungen und Commit-Texte **englisch** — `AGENTS.md` sagt das ausdrücklich, auch für Konfigurationsdateien. Nur die Prosa unter `docs/.superpowers/` und `README.de.md` ist deutsch.
- **Commits:** Nachricht mehrzeilig über eine Datei und `git commit -F <datei>`, nie über ein Heredoc. **Keine `Co-Authored-By`-Zeile** — weder für Claude noch für einen Agenten; Autor und Committer sind der Nutzer aus der git-Konfiguration. Datei danach löschen.
- **Kein `git push`.** Ob Commits das Remote erreichen, entscheidet ein Mensch.
- **Ein Shell-Befehl je Aufruf**, keine langen `&&`-Ketten.
- **Modulgrenze:** `ultraloom.hooks.*` darf `config`, `checks`, `worktree`, `journal` und `gate` benutzen, nichts aus dem Harness (`graph`, `state`, `runner`, `model`, `discovery`). `session_start` und `subagent_stop` dürfen zusätzlich `checks` **nicht** laden.
- **Tests gegen git** benutzen echte Repositories in `tmp_path` und `subprocess`, nie eine Attrappe. Commits dort brauchen `-c user.name=t -c user.email=t@t`, weil keine globale Identität vorausgesetzt werden darf.

---

### Task 1: Messen, was wirklich in der Payload steht

Die Spec nennt zwei offene Punkte, und beide sind Messungen. Sie stehen vor der ersten Zeile Code, weil der Entwurf von `stop` und `subagent-stop` an ihren Antworten hängt.

**Files:**
- Create: `docs/.superpowers/specs/2026-08-25-sitzungs-hooks-payloads.md`
- Modify: `docs/.superpowers/specs/2026-08-25-sitzungs-hooks-design.md` (Abschnitt „Offene Punkte")

**Interfaces:**
- Consumes: nichts.
- Produces: belegte Feldnamen für Task 5 und Task 6.

- [ ] **Step 1: Write a payload recorder**

Ein Skript, das nichts tut außer aufschreiben, was ankommt. Nach `C:/Users/micro/AppData/Local/Temp/claude/hook-payloads/record.py`, **nicht** ins Repo — es ist ein Messwerkzeug, kein Erzeugnis:

```python
"""Writes whatever a hook receives to a file, then exits 0."""

import json
import sys
import time
from pathlib import Path

OUT = Path("C:/Users/micro/AppData/Local/Temp/claude/hook-payloads")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        event = payload.get("hook_event_name", "unknown")
    except json.JSONDecodeError:
        payload, event = {"raw": raw}, "unparsable"
    stamp = time.strftime("%H%M%S")
    (OUT / f"{event}-{stamp}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Register it for the four events**

In einer **eigenen** Sitzung, nicht in der arbeitenden: `.claude/settings.json` vorübergehend um vier Einträge ergänzen, die `uv run --no-project python <pfad>/record.py` für `SessionStart`, `PostToolUse`, `Stop` und `SubagentStop` aufrufen. Die vorhandene `PreToolUse`-Verdrahtung bleibt unangetastet.

- [ ] **Step 3: Provoke all four events**

Eine Sitzung starten (`SessionStart`), eine Datei schreiben (`PostToolUse`), einen Subagenten laufen lassen (`SubagentStop`), den Zug enden lassen (`Stop`). Für `Stop` zusätzlich einen Lauf mit einem Hook, der einmal Exit 2 gibt, damit ein **zweiter** `Stop` mit anderem Zustand ankommt.

- [ ] **Step 4: Read the recordings and write them down**

`docs/.superpowers/specs/2026-08-25-sitzungs-hooks-payloads.md` bekommt je Ereignis die vollständige Feldliste, wörtlich, mit einem Beispielwert je Feld (Pfade und Sitzungs-IDs gekürzt). Ausdrücklich zu beantworten:

1. Trägt die `Stop`-Payload ein Feld `stop_hook_active`, und welchen Wert hat es beim zweiten Aufruf?
2. Trägt die `SubagentStop`-Payload `agent_id` und `agent_type`?
3. Wie heißt das Feld mit der Sitzungskennung, und ist es über die Aufrufe hinweg stabil?

- [ ] **Step 5: Correct the design document**

Den Abschnitt „Offene Punkte" der Spec durch das Gemessene ersetzen. Fällt eine Antwort anders aus als vermutet — etwa: es gibt kein `stop_hook_active`, oder `agent_id` fehlt —, **hier anhalten und berichten**. Ohne `agent_id` braucht `subagent-stop` einen anderen Schlüssel für seinen Schnappschuss, und das ist eine Entwurfsfrage, keine Umsetzungsfrage.

- [ ] **Step 6: Remove the recorder from settings.json**

Die vier Einträge wieder entfernen. Prüfen, dass `.claude/settings.json` danach wieder genau den `PreToolUse`-Eintrag enthält und sonst nichts.

- [ ] **Step 7: Commit**

```bash
git add docs/.superpowers/specs
```

Nachricht:

```
Write down what the hook payloads actually carry

Measured rather than assumed: the design leaned on stop_hook_active and
agent_id, and neither was documented in the page it came from.
```

---

### Task 2: Der Zustand einer Sitzung (`hooks/state.py`)

Der Block-Zähler des Stop-Gates und die Remote-Schnappschüsse müssen zwischen zwei Aufrufen überdauern.

**Files:**
- Create: `src/ultraloom/hooks/__init__.py`
- Create: `src/ultraloom/hooks/state.py`
- Create: `tests/hooks/__init__.py`
- Create: `tests/hooks/test_state.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nichts.
- Produces:
  - `SessionState(blocks: int, snapshots: Mapping[str, str])` — eingefroren
  - `read(root: Path, session_id: str) -> SessionState`
  - `write(root: Path, session_id: str, state: SessionState) -> None`
  - `STATE_DIR = ".ultraloom/hooks"`

- [ ] **Step 1: Write the failing tests**

`tests/hooks/test_state.py`:

```python
"""What survives between two hook calls, and what happens when it does not."""

from __future__ import annotations

from pathlib import Path

from ultraloom.hooks.state import STATE_DIR, SessionState, read, write


def test_an_unknown_session_starts_at_zero(tmp_path: Path) -> None:
    assert read(tmp_path, "s1") == SessionState(blocks=0, snapshots={})


def test_what_is_written_comes_back(tmp_path: Path) -> None:
    write(tmp_path, "s1", SessionState(blocks=2, snapshots={"a1": "deadbeef"}))
    assert read(tmp_path, "s1") == SessionState(blocks=2, snapshots={"a1": "deadbeef"})


def test_two_sessions_do_not_share_a_counter(tmp_path: Path) -> None:
    """Two sessions in one checkout must not reset each other's gate."""
    write(tmp_path, "s1", SessionState(blocks=3, snapshots={}))
    write(tmp_path, "s2", SessionState(blocks=1, snapshots={}))
    assert read(tmp_path, "s1").blocks == 3
    assert read(tmp_path, "s2").blocks == 1


def test_it_lands_under_the_state_dir(tmp_path: Path) -> None:
    write(tmp_path, "s1", SessionState(blocks=1, snapshots={}))
    assert (tmp_path / STATE_DIR / "s1.json").is_file()


def test_a_broken_state_file_reads_as_empty(tmp_path: Path) -> None:
    """A damaged counter must not lock a session out of its own gate.

    Reading it as "nothing blocked yet" costs at most three extra rounds;
    raising here would end every turn with an internal error instead.
    """
    path = tmp_path / STATE_DIR / "s1.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    assert read(tmp_path, "s1") == SessionState(blocks=0, snapshots={})


def test_a_session_id_with_a_path_separator_is_refused(tmp_path: Path) -> None:
    """The id comes from outside; it must not choose where the file lands."""
    write(tmp_path, "../escape", SessionState(blocks=1, snapshots={}))
    assert not (tmp_path.parent / "escape.json").exists()
    assert (tmp_path / STATE_DIR).is_dir()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hooks/test_state.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.hooks'`

- [ ] **Step 3: Write the implementation**

`src/ultraloom/hooks/__init__.py`:

```python
"""The hooks that watch a session rather than a single tool call.

Above the policy in what it may import -- these hooks *are* check runs -- and
below the harness like everything else that a project without the agent extra
still gets.
"""
```

`src/ultraloom/hooks/state.py`:

```python
"""What one session remembers between two hook calls.

One file per session, not one per checkout: two sessions in the same working
copy would otherwise reset each other's block counter, and a gate that counts
somebody else's rounds is no gate.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

STATE_DIR = ".ultraloom/hooks"


@dataclass(frozen=True, slots=True)
class SessionState:
    """The counter and the snapshots one session carries."""

    blocks: int = 0
    snapshots: Mapping[str, str] = field(default_factory=dict)


def read(root: Path, session_id: str) -> SessionState:
    """What this session left behind, or an empty state.

    A file that cannot be read counts as empty. Raising instead would end
    every turn with an internal error over a counter whose worst case is three
    extra rounds.
    """
    path = _path(root, session_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        blocks = raw["blocks"]
        snapshots = raw["snapshots"]
        if not isinstance(blocks, int) or not isinstance(snapshots, dict):
            raise TypeError("state file has the wrong shape")
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return SessionState()
    return SessionState(blocks=blocks, snapshots=snapshots)


def write(root: Path, session_id: str, state: SessionState) -> None:
    """Keep this state for the next call."""
    path = _path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"blocks": state.blocks, "snapshots": dict(state.snapshots)}
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _path(root: Path, session_id: str) -> Path:
    """Where this session's file lives.

    The id arrives from outside, so it may not decide where the file lands:
    only the name's own last part is used, and a separator in it collapses to
    something harmless rather than climbing out of the directory.
    """
    safe = "".join(char for char in session_id if char.isalnum() or char in "-_") or "unnamed"
    return root / STATE_DIR / f"{safe}.json"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hooks/test_state.py -v`
Expected: PASS, 6 Tests.

- [ ] **Step 5: Ignore the state directory**

An `.gitignore` anhängen:

```
# Per-session hook state: a block counter and remote snapshots, worthless to
# anyone but the session that wrote them.
.ultraloom/hooks/
```

- [ ] **Step 6: Keep an agent from resetting its own gate**

An `.ultraloom/config.toml` in der bestehenden Pfadregel ergänzen — `.ultraloom/hooks/*` in die `match`-Liste aufnehmen, und den Grund im vorhandenen englischen Kommentarblock nennen: wer seinen eigenen Block-Zähler zurücksetzt, hat das Gate abgeschafft.

- [ ] **Step 7: Run the chain**

Run: `uv run ultraloom check all`
Expected: grün, 100 %.

- [ ] **Step 8: Commit**

```bash
git add src/ultraloom/hooks tests/hooks .gitignore .ultraloom/config.toml
```

Nachricht:

```
Remember a session's counter and snapshots

One file per session id, because two sessions in one checkout would
otherwise reset each other's gate. A damaged file reads as empty: the
worst case is three extra rounds, an exception would end every turn.
```

---

### Task 3: `session-start` und die Verdrahtung des Unterkommandos

**Files:**
- Create: `src/ultraloom/hooks/payload.py`
- Create: `src/ultraloom/hooks/session_start.py`
- Create: `src/ultraloom/hooks/cli.py`
- Create: `tests/hooks/test_payload.py`
- Create: `tests/hooks/test_session_start.py`
- Modify: `src/ultraloom/cli.py` (`_parser`, `main`)
- Modify: `tests/test_module_boundary.py`

**Interfaces:**
- Consumes: nichts aus Task 2.
- Produces:
  - `payload.read(stdin: TextIO) -> Mapping[str, Any]` — wirft `PayloadError`
  - `payload.PayloadError(ValueError)`
  - `payload.EXIT_OK = 0`, `payload.EXIT_INTERNAL = 1`, `payload.EXIT_BLOCKED = 2`
  - `session_start.run(stdin: TextIO, root: Path, stdout: TextIO, stderr: TextIO) -> int`
  - `cli.dispatch(args: argparse.Namespace, root: Path) -> int`

- [ ] **Step 1: Write the failing tests for the payload reader**

`tests/hooks/test_payload.py`:

```python
"""Reading a hook payload, and refusing what is not one."""

from __future__ import annotations

import io
import json

import pytest

from ultraloom.hooks.payload import PayloadError, read


def test_a_payload_comes_back_as_a_mapping() -> None:
    assert read(io.StringIO(json.dumps({"session_id": "s1"})))["session_id"] == "s1"


@pytest.mark.parametrize("raw", ["", "no json", "[]", "42", '"text"'])
def test_anything_that_is_not_an_object_is_refused(raw: str) -> None:
    with pytest.raises(PayloadError):
        read(io.StringIO(raw))
```

- [ ] **Step 2: Write the failing tests for session-start**

`tests/hooks/test_session_start.py`:

```python
"""What a fresh session is told about the runs it inherited."""

from __future__ import annotations

import io
import json
from pathlib import Path

from ultraloom.hooks.session_start import run


def _journal(root: Path, run_id: str, *lines: dict[str, object]) -> None:
    directory = root / ".ultraloom" / "runs"
    directory.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(line, sort_keys=True) for line in lines)
    (directory / f"{run_id}.jsonl").write_text(body + "\n", encoding="utf-8")


def _entry(node: str, outcome: str, detail: str | None = None) -> dict[str, object]:
    return {
        "node": node,
        "outcome": outcome,
        "detail": detail,
        "input_hash": "abc123",
        "data": None,
    }


def _payload() -> io.StringIO:
    return io.StringIO(json.dumps({"session_id": "s1", "hook_event_name": "SessionStart"}))


def test_a_project_without_runs_says_nothing(tmp_path: Path) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), tmp_path, out, err) == 0
    assert out.getvalue() == ""


def test_a_finished_run_is_not_reported(tmp_path: Path) -> None:
    _journal(tmp_path, "0001", _entry("verify", "ok"))
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), tmp_path, out, err) == 0
    assert out.getvalue() == ""


def test_a_paused_run_is_reported_with_its_question(tmp_path: Path) -> None:
    _journal(tmp_path, "0002", _entry("approve", "paused", "May I merge?"))
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), tmp_path, out, err) == 0
    said = out.getvalue()
    assert "0002" in said
    assert "May I merge?" in said
    assert "ultraloom resume 0002 --answer" in said


def test_every_paused_run_is_reported(tmp_path: Path) -> None:
    _journal(tmp_path, "0003", _entry("approve", "paused", "First?"))
    _journal(tmp_path, "0004", _entry("approve", "paused", "Second?"))
    out, err = io.StringIO(), io.StringIO()
    run(_payload(), tmp_path, out, err)
    assert "0003" in out.getvalue()
    assert "0004" in out.getvalue()


def test_a_damaged_journal_does_not_hide_the_others(tmp_path: Path) -> None:
    """One unreadable file is a finding, not a reason to say nothing at all."""
    _journal(tmp_path, "0005", _entry("approve", "paused", "Still open?"))
    directory = tmp_path / ".ultraloom" / "runs"
    (directory / "0006.jsonl").write_text("not a journal\n", encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), tmp_path, out, err) == 0
    assert "0005" in out.getvalue()
    assert "0006" in err.getvalue()


def test_an_unreadable_payload_is_an_internal_error(tmp_path: Path) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert run(io.StringIO("nonsense"), tmp_path, out, err) == 1
```

- [ ] **Step 3: Run both to verify they fail**

Run: `uv run pytest tests/hooks -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.hooks.payload'`

- [ ] **Step 4: Write the payload reader**

`src/ultraloom/hooks/payload.py`:

```python
"""Reading what Claude Code puts on stdin, and the exit codes it reads back.

Shared by all four hooks so the protocol is stated once. What exit 2 *means*
is not shared -- it depends on the event, and each hook says so itself.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, TextIO

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_BLOCKED = 2


class PayloadError(ValueError):
    """Raised when stdin does not carry a hook payload."""


def read(stdin: TextIO) -> Mapping[str, Any]:
    """The payload as a mapping, or a refusal naming why it is not one."""
    try:
        payload = json.loads(stdin.read())
    except json.JSONDecodeError as error:
        raise PayloadError(f"stdin is not JSON: {error}") from error
    if not isinstance(payload, dict):
        raise PayloadError("a hook payload is an object")
    return payload
```

- [ ] **Step 5: Write session-start**

`src/ultraloom/hooks/session_start.py`:

```python
"""Tells a fresh session which runs are still waiting for an answer.

A paused run has an address but no voice: nothing surfaces it in a new
session, and `resume` needs an id somebody has to know. This hook is where
that id comes from.
"""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from ultraloom.gate import pending_gate
from ultraloom.hooks.payload import EXIT_INTERNAL, EXIT_OK, PayloadError
from ultraloom.hooks.payload import read as read_payload
from ultraloom.journal import Journal, JournalError
from ultraloom.worktree import RUN_DIR


def run(stdin: TextIO, root: Path, stdout: TextIO, stderr: TextIO) -> int:
    """Report every paused run. Never blocks -- this is an announcement."""
    try:
        read_payload(stdin)
    except PayloadError as error:
        print(f"ultraloom hook session-start: {error}", file=stderr)
        return EXIT_INTERNAL

    for line in waiting(root, stderr):
        print(line, file=stdout)
    return EXIT_OK


def waiting(root: Path, stderr: TextIO) -> tuple[str, ...]:
    """One line per paused run, in run order."""
    directory = root / RUN_DIR
    if not directory.is_dir():
        return ()

    lines: list[str] = []
    for path in sorted(directory.glob("*.jsonl")):
        run_id = path.stem
        try:
            gate = pending_gate(Journal(path))
        except JournalError as error:
            # Named, not swallowed, and not fatal either: one damaged file is
            # a finding of its own, and hiding the other runs behind it would
            # turn a small defect into a silent one.
            print(f"ultraloom hook session-start: {error}", file=stderr)
            continue
        if gate is None:
            continue
        lines.append(
            f"run {run_id} is waiting at {gate.node}: {gate.question}\n"
            f"  answer it with: ultraloom resume {run_id} --answer \"…\""
        )
    return tuple(lines)
```

- [ ] **Step 6: Write the subcommand dispatcher**

`src/ultraloom/hooks/cli.py`:

```python
"""Which hook a call means, and where its streams come from."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ultraloom.hooks import session_start


def dispatch(args: argparse.Namespace, root: Path) -> int:
    """Run the named hook against the real streams."""
    if args.hook_name == "session-start":
        return session_start.run(sys.stdin, root, sys.stdout, sys.stderr)
    # argparse limits the choice, so this is the "no subcommand" case.
    print("ultraloom hook: say which hook to run", file=sys.stderr)
    return 1
```

- [ ] **Step 7: Wire it into the CLI**

In `_parser()` von `src/ultraloom/cli.py`, hinter dem `policy`-Block:

```python
    hook = subparsers.add_parser(
        "hook", parents=[common], help="run one of the session hooks"
    )
    hook_subs = hook.add_subparsers(dest="hook_name")
    hook_subs.add_parser(
        "session-start", parents=[common], help="report runs waiting at a gate"
    )
```

In `main()`, direkt hinter dem `policy`-Zweig und aus demselben Grund vor `load_config`:

```python
    if args.command == "hook":
        # Imported here, like the policy: a hook that only reads the journal
        # must not pay for the check chain, and `check` must not pay for it.
        from ultraloom.hooks import cli as hooks_cli

        return hooks_cli.dispatch(args, root)
```

- [ ] **Step 8: Extend the boundary test**

An `tests/test_module_boundary.py` anhängen, nach dem Muster des vorhandenen `_probe`:

```python
_SESSION_START_PROGRAM = _PREAMBLE + '''
import io
import sys

sys.stdin = io.StringIO("{}")
from ultraloom.cli import main

code = main(["hook", "session-start"])
report()
print("CHECKS:", "ultraloom.checks" in sys.modules)
print("EXIT:", code)
'''


def test_session_start_pulls_in_neither_the_harness_nor_the_check_chain() -> None:
    """It reads a directory; paying for the check chain would be absurd."""
    result = subprocess.run(
        [sys.executable, "-c", _SESSION_START_PROGRAM],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert "LEAKED: []" in result.stdout, result.stdout
    assert "CHECKS: False" in result.stdout, result.stdout
```

- [ ] **Step 9: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 10: Try it by hand**

```bash
echo '{"session_id":"s1","hook_event_name":"SessionStart"}' | uv run ultraloom hook session-start --root .
```

Expected: Exit 0. Im Hauptcheckout liegen vier abgeschlossene Läufe, also keine Ausgabe.

- [ ] **Step 11: Run the chain**

Run: `uv run ultraloom check all`
Expected: grün, 100 %.

- [ ] **Step 12: Commit**

```bash
git add src/ultraloom/hooks src/ultraloom/cli.py tests/hooks tests/test_module_boundary.py
```

Nachricht:

```
Say which runs are still waiting

A paused run has an address but no voice: nothing surfaces it in a new
session, and resume needs an id somebody has to know.
```

---

### Task 4: `post-edit`

**Files:**
- Create: `src/ultraloom/hooks/post_edit.py`
- Create: `tests/hooks/test_post_edit.py`
- Modify: `src/ultraloom/cli.py` (`_parser`), `src/ultraloom/hooks/cli.py` (`dispatch`)

**Interfaces:**
- Consumes: `payload.read`, `payload.EXIT_*` (Task 3).
- Produces: `post_edit.run(stdin: TextIO, root: Path, stderr: TextIO) -> int`

- [ ] **Step 1: Write the failing tests**

`tests/hooks/test_post_edit.py`:

```python
"""What the file that was just written gets told about itself."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from ultraloom.hooks.post_edit import formats, run


def _payload(tool: str, path: Path) -> io.StringIO:
    return io.StringIO(
        json.dumps(
            {
                "session_id": "s1",
                "hook_event_name": "PostToolUse",
                "tool_name": tool,
                "tool_input": {"file_path": str(path)},
            }
        )
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [("a.py", True), ("a.pyi", True), ("a.ipynb", False), ("a.md", False), ("a", False)],
)
def test_only_python_is_formatted(name: str, expected: bool) -> None:
    """A formatter that does not understand the file damages it.

    `.ipynb` is JSON; ruff format would not leave a notebook intact.
    """
    assert formats(Path(name)) is expected


def test_a_clean_file_says_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    written = tmp_path / "a.py"
    written.write_text('"""Fine."""\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    errors = io.StringIO()
    assert run(_payload("Write", written), tmp_path, errors) == 0
    assert errors.getvalue() == ""


def test_a_payload_without_a_path_does_nothing(tmp_path: Path) -> None:
    payload = io.StringIO(
        json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {}})
    )
    errors = io.StringIO()
    assert run(payload, tmp_path, errors) == 0


def test_a_file_outside_the_project_is_left_alone(tmp_path: Path) -> None:
    """The hook runs a project's checks; a file elsewhere is not its business."""
    outside = tmp_path.parent / "elsewhere.py"
    errors = io.StringIO()
    assert run(_payload("Write", outside), tmp_path, errors) == 0


def test_an_unreadable_payload_is_an_internal_error(tmp_path: Path) -> None:
    errors = io.StringIO()
    assert run(io.StringIO("nonsense"), tmp_path, errors) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hooks/test_post_edit.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.hooks.post_edit'`

- [ ] **Step 3: Write the implementation**

`src/ultraloom/hooks/post_edit.py`:

```python
"""Formats the file that was just written and reports what is left over.

Exit 2 blocks nothing here -- the tool has already run. It is how the finding
reaches the file that caused it, instead of surfacing forty seconds later in
the stop gate with nothing to connect it to.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO

from ultraloom.config import ConfigError, load_config
from ultraloom.hooks.payload import EXIT_BLOCKED, EXIT_INTERNAL, EXIT_OK, PayloadError
from ultraloom.hooks.payload import read as read_payload

# The profile this hook runs. Named here and not spelled out as kinds: a
# project that wants something else from an edit says so in its config.
PROFILE = "edit"

# What `ruff format` understands. A notebook is JSON, and a formatter that
# does not understand a file does not tidy it -- it breaks it.
_FORMATTED = (".py", ".pyi")


def formats(path: Path) -> bool:
    """Whether the formatter may touch this file."""
    return path.suffix in _FORMATTED


def run(stdin: TextIO, root: Path, stderr: TextIO) -> int:
    """Format, then check. Findings go to stderr for the agent to read."""
    try:
        payload = read_payload(stdin)
    except PayloadError as error:
        print(f"ultraloom hook post-edit: {error}", file=stderr)
        return EXIT_INTERNAL

    written = _written_path(payload.get("tool_input"), root)
    if written is None:
        return EXIT_OK

    try:
        config = load_config(root)
    except ConfigError as error:
        # Exit 1, not 2: a broken [verify] table is not this file's fault, and
        # a finding the agent cannot act on is noise at the wrong moment.
        print(f"ultraloom hook post-edit: {error}", file=stderr)
        return EXIT_INTERNAL

    return _check(written, config, root, stderr)


def _written_path(tool_input: Any, root: Path) -> Path | None:
    """The file this call wrote, if it wrote one inside the project."""
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "notebook_path"):
        raw = tool_input.get(key)
        if isinstance(raw, str):
            path = Path(raw)
            try:
                path.resolve().relative_to(root.resolve())
            except ValueError:
                return None
            return path
    return None
```

Den Rest von `_check` schreibt Schritt 5 — er braucht die Entscheidung aus Schritt 4.

- [ ] **Step 4: Move the profile resolution down into `config`**

Die Auflösung „Profilname → Liste von Kinds" liegt heute in `flows/verify_until_green.py`. Dort kommt der Hook nicht heran: das Modul importiert `discovery`, `graph`, `runner` und `state`, also den Harness, den `test_module_boundary.py` von der Prüfkette fernhält. Sie ein zweites Mal zu schreiben ist die Verdopplung, gegen die `worktree.py` in seinem eigenen Docstring argumentiert — also wandert sie dorthin, wo `profiles` ohnehin wohnt.

Nach `src/ultraloom/config.py`, mit einem Test in `tests/test_config.py`:

```python
def kinds_for(config: Config, requested: str) -> tuple[str, ...]:
    """The check kinds behind a profile name or a comma-separated list.

    Here and not in the flow that asked first: the flow sits above the harness
    boundary, and a hook below it needs the same answer. Two readings of one
    table would drift in exactly the details this function exists for.

    Raises:
        ConfigError: if a name is neither a profile nor a check kind, or if
            what it resolves to is empty -- a profile configured as an empty
            list would otherwise pass as "everything was checked".
    """
```

Der Rumpf ist der, den `_requested_kinds` im Flow heute hat; der Flow ruft danach `config.kinds_for` auf, statt es selbst zu tun. Der bestehende Flow-Test muss danach unverändert grün sein — schlägt er fehl, ist die Verschiebung nicht gleichwertig, und das ist ein Befund.

- [ ] **Step 5: Write `_check` using `config.kinds_for`**

Die Funktion fährt `ruff format` über die Datei, wenn `formats(path)`, danach die Kinds des Profils über `checks.run_kinds`. Alle roten Ergebnisse kommen gesammelt auf stderr — nicht nur das erste, aus demselben Grund wie bei der Policy — und ergeben Exit 2. Läuft ein Check gar nicht (`CheckUnavailableError`), ist das Exit 1: eine Kette, die nicht laufen kann, ist kein Befund über die Datei.

- [ ] **Step 6: Wire up the subcommand**

In `_parser()`: `hook_subs.add_parser("post-edit", parents=[common], help="format and check the file that was just written")`. In `hooks/cli.py` eine Zeile im `dispatch`.

- [ ] **Step 7: Run tests and the chain**

Run: `uv run pytest tests/hooks -v`
Expected: PASS.

Run: `uv run ultraloom check all`
Expected: grün, 100 %.

- [ ] **Step 8: Measure it**

```bash
echo '{"hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":"src/ultraloom/cli.py"}}' | uv run ultraloom hook post-edit --root .
```

Fünf Läufe mit `date +%s%N` um die Schleife. Die Spec veranschlagt rund 1 s. Liegt es über 3 s, **anhalten und berichten** — der Hook läuft nach jedem Schreibvorgang.

- [ ] **Step 9: Commit**

```bash
git add src/ultraloom/hooks src/ultraloom/cli.py tests/hooks
```

Nachricht:

```
Tell the file that was just written what is wrong with it

Exit 2 blocks nothing here; the tool has already run. It is how the
finding reaches the file that caused it instead of the stop gate forty
seconds later.
```

---

### Task 5: `subagent-stop`

**Files:**
- Create: `src/ultraloom/hooks/subagent_stop.py`
- Create: `tests/hooks/test_subagent_stop.py`
- Modify: `src/ultraloom/cli.py` (`_parser`), `src/ultraloom/hooks/cli.py`

**Interfaces:**
- Consumes: `state.read`, `state.write`, `SessionState` (Task 2); `payload.read` (Task 3).
- Produces:
  - `subagent_stop.run(stdin: TextIO, root: Path, stdout: TextIO, stderr: TextIO) -> int`
  - `subagent_stop.remote_refs(root: Path) -> str`
  - `subagent_stop.differences(before: str, after: str) -> tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

`tests/hooks/test_subagent_stop.py`:

```python
"""What a subagent changed, whether or not its report says so."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

from ultraloom.hooks.state import SessionState, write as write_state
from ultraloom.hooks.subagent_stop import differences, remote_refs, run


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _repo_with_remote(tmp_path: Path) -> Path:
    """A real repository with a real remote, both on disk."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(remote))
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    (work / "a.txt").write_text("one\n", encoding="utf-8")
    _git(work, "add", "a.txt")
    _git(work, "commit", "-m", "first")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "origin", "HEAD:refs/heads/master")
    return work


def _payload(agent_id: str = "a1") -> io.StringIO:
    return io.StringIO(
        json.dumps(
            {
                "session_id": "s1",
                "hook_event_name": "SubagentStop",
                "agent_id": agent_id,
                "agent_type": "general-purpose",
            }
        )
    )


def test_no_snapshot_says_so_rather_than_claiming_nothing_happened(tmp_path: Path) -> None:
    """Without a before, there is no after -- and silence would read as "clean"."""
    work = _repo_with_remote(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), work, out, err) == 0
    assert "no snapshot" in out.getvalue()


def test_an_unchanged_remote_is_reported_as_nothing(tmp_path: Path) -> None:
    work = _repo_with_remote(tmp_path)
    write_state(work, "s1", SessionState(snapshots={"a1": remote_refs(work)}))
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), work, out, err) == 0
    assert out.getvalue() == ""


def test_a_push_is_reported(tmp_path: Path) -> None:
    """The incident this hook exists for: a push nobody mentioned."""
    work = _repo_with_remote(tmp_path)
    write_state(work, "s1", SessionState(snapshots={"a1": remote_refs(work)}))
    (work / "a.txt").write_text("two\n", encoding="utf-8")
    _git(work, "add", "a.txt")
    _git(work, "commit", "-m", "second")
    _git(work, "push", "origin", "HEAD:refs/heads/master")

    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), work, out, err) == 0
    assert "origin" in out.getvalue()
    assert "refs/heads/master" in out.getvalue()


def test_differences_names_both_sides() -> None:
    before = "aaa\trefs/heads/master\n"
    after = "bbb\trefs/heads/master\nccc\trefs/heads/topic\n"
    found = differences(before, after)
    assert any("refs/heads/master" in line for line in found)
    assert any("refs/heads/topic" in line for line in found)


def test_a_repository_without_a_remote_is_not_an_error(tmp_path: Path) -> None:
    work = tmp_path / "solo"
    work.mkdir()
    _git(work, "init")
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), work, out, err) == 0


def test_an_unreadable_payload_is_an_internal_error(tmp_path: Path) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert run(io.StringIO("nonsense"), tmp_path, out, err) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hooks/test_subagent_stop.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.hooks.subagent_stop'`

- [ ] **Step 3: Write the implementation**

Kernpunkte, die der Code tragen muss — der Rest folgt dem Muster der anderen Hooks:

- `remote_refs(root)` ruft `git ls-remote origin` mit einem **Timeout** und gibt bei jedem Fehlschlag (kein Remote, kein Netz, Zeitüberschreitung) eine leere Zeichenkette zurück. Ein nicht erreichbares Remote ist kein Befund über den Subagenten.
- `differences(before, after)` vergleicht die Zeilenmengen und nennt jede Referenz, deren Hash sich geändert hat oder die neu oder verschwunden ist — beide Richtungen, nicht nur „neu".
- `run` liest den Schnappschuss zu `agent_id` aus dem Sitzungszustand. Fehlt er, wird das gesagt: „no snapshot for this subagent; nothing to compare". Schweigen wäre eine Aussage, die niemand geprüft hat.
- **Nie Exit 2.** Der Push ist geschehen; den Subagenten am Aufhören zu hindern, macht ihn nicht rückgängig. Der Kommentar im Code sagt das.

- [ ] **Step 4: Take the snapshot somewhere**

`SubagentStop` allein hat kein Davor. Prüfe anhand der Messung aus Task 1, ob es ein `SubagentStart`-Ereignis mit derselben `agent_id` gibt. Wenn ja: einen zweiten Hook `subagent-start` ergänzen, der nur den Schnappschuss schreibt. Wenn nein: den Schnappschuss in `session-start` nehmen und je Sitzung statt je Subagent führen — dann meldet der Hook, was seit **Sitzungsbeginn** passiert ist, was gröber, aber ehrlich ist. **Diese Entscheidung im Bericht nennen**, samt dem, was die Messung hergab.

- [ ] **Step 5: Wire up, run, and check**

Unterkommando `subagent-stop` in `_parser()` und `hooks/cli.py`. Dann:

Run: `uv run pytest tests/hooks -v` → PASS
Run: `uv run ultraloom check all` → grün, 100 %

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/hooks src/ultraloom/cli.py tests/hooks
```

Nachricht:

```
Notice what a subagent did to the remote

The incident in CLAUDE.md had this shape: a subagent pushed master and
its report did not say so. Blocking would not undo the push, so this
only looks and tells.
```

---

### Task 6: `stop`

Der riskanteste Hook: Er kann eine Sitzung anhalten. Er kommt zuletzt, damit die anderen bereits laufen, wenn er es tut.

**Files:**
- Create: `src/ultraloom/hooks/stop.py`
- Create: `tests/hooks/test_stop.py`
- Modify: `src/ultraloom/cli.py` (`_parser`), `src/ultraloom/hooks/cli.py`

**Interfaces:**
- Consumes: `state.read`, `state.write`, `SessionState` (Task 2); `payload.read` (Task 3).
- Produces:
  - `stop.run(stdin: TextIO, root: Path, stderr: TextIO) -> int`
  - `stop.MAX_BLOCKS = 3`
  - `stop.MARKER = ".claude/.no-verify"`

- [ ] **Step 1: Write the failing tests**

`tests/hooks/test_stop.py`:

```python
"""Whether a turn may end, and how often it may be told that it may not."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from ultraloom.hooks.state import SessionState, read as read_state, write as write_state
from ultraloom.hooks.stop import MARKER, MAX_BLOCKS, run


def _payload(session: str = "s1") -> io.StringIO:
    return io.StringIO(json.dumps({"session_id": session, "hook_event_name": "Stop"}))


def test_the_marker_switches_the_gate_off(tmp_path: Path) -> None:
    marker = tmp_path / MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8")
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors) == 0


def test_a_session_that_changed_nothing_is_not_checked(tmp_path: Path) -> None:
    """A turn that only read and answered must not cost forty-five seconds."""
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors) == 0
    assert errors.getvalue() == ""


def test_the_counter_stops_blocking_after_three_rounds(tmp_path: Path) -> None:
    """The escalation is the point: a gate that never gives up locks the session."""
    write_state(tmp_path, "s1", SessionState(blocks=MAX_BLOCKS))
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors) == 0
    assert "gave up" in errors.getvalue()


def test_a_block_raises_the_counter(tmp_path: Path) -> None:
    """Whatever the outcome, a blocked turn must be counted or the cap is void."""
    before = read_state(tmp_path, "s1").blocks
    assert before == 0
```

Die drei Tests, die eine **rote Kette** brauchen, kommen in Schritt 2 — sie hängen daran, wie `run` die Kette aufruft, und das entscheidet Schritt 3.

- [ ] **Step 2: Decide how the chain is called, from the code**

`run` braucht zwei Dinge, die es nicht selbst erledigen soll: „hat sich etwas geändert?" und „ist die Kette grün?". Für das erste gibt es `worktree.changed_files(root)` und `worktree.changed_since(root, base)`; sieh nach, welches der beiden der `guard`-Knoten in `flows/verify_until_green.py` benutzt und **warum** (die Antwort steht in `docs/.superpowers/specs/2026-08-23-guard-basis-commit-design.md`), und nimm dieselbe. Für das zweite gibt es `checks.run_all(config)`.

Damit die Tests eine rote Kette herstellen können, ohne 45 Sekunden zu warten, nimmt `run` beide als Parameter mit einer Vorgabe — dem Muster folgend, das `checks._run` und `process.run` im Repo bereits benutzen: die Syscalls kommen von außen, die Entscheidung wird getestet. Schreib die drei fehlenden Tests gegen diese Signatur:

1. Geänderte Dateien und grüne Kette → Exit 0, Zähler bleibt.
2. Geänderte Dateien und rote Kette → Exit 2, Befunde auf stderr, Zähler +1.
3. Kette wirft `CheckUnavailableError` → Exit 1, Zähler bleibt, und die Meldung sagt, dass die Kette nicht laufen konnte.

- [ ] **Step 3: Write the implementation**

Reihenfolge in `run`, und sie ist nicht beliebig:

1. Payload lesen — kaputt heißt Exit 1.
2. Marker `.claude/.no-verify` — vorhanden heißt Exit 0, ohne irgendetwas zu fahren.
3. Zähler ≥ `MAX_BLOCKS` — dann Exit 0 mit einer Meldung, die sagt, dass das Gate aufgegeben hat und was rot war. Vor dem Prüfen, nicht danach: 45 Sekunden für ein Ergebnis, das ohnehin niemanden mehr aufhält, sind verschwendet.
4. Kurzschluss: nichts geändert → Exit 0.
5. Kette fahren. Grün → Exit 0. Rot → Zähler +1, alle roten Kinds auf stderr, Exit 2. Nicht lauffähig → Exit 1, Zähler unverändert.

- [ ] **Step 4: Run tests and the chain**

Run: `uv run pytest tests/hooks/test_stop.py -v` → PASS
Run: `uv run ultraloom check all` → grün, 100 %

- [ ] **Step 5: Try both directions by hand**

```bash
echo '{"session_id":"probe","hook_event_name":"Stop"}' | uv run ultraloom hook stop --root .
```

Im sauberen Hauptcheckout: Exit 0 durch den Kurzschluss, sofort. Danach eine Datei ändern und denselben Aufruf wiederholen: Die Kette läuft, und bei grüner Kette kommt Exit 0 nach rund 45 Sekunden. Beide Zeiten berichten.

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/hooks src/ultraloom/cli.py tests/hooks
```

Nachricht:

```
Hold a turn until the chain is green

Three blocks per session, then it gives up and says so: a gate that
never yields locks the session it was meant to protect. A turn that
changed nothing skips the chain entirely.
```

---

### Task 7: Verdrahtung, Doku und die Probe aufs Ganze

**Files:**
- Modify: `.claude/settings.json`
- Modify: `README.md`, `README.de.md`
- Create: `docs/abläufe/session-hooks.md`, `docs/abläufe/session-hooks.de.md`

**Interfaces:**
- Consumes: alle vier Hooks.
- Produces: nichts für Code.

- [ ] **Step 1: Wire the four events**

`.claude/settings.json` um `PostToolUse` (Matcher `Write|Edit|NotebookEdit`, Timeout 60), `Stop` (Timeout 300), `SessionStart` (Timeout 20) und `SubagentStop` (Timeout 30) ergänzen. Der vorhandene `PreToolUse`-Eintrag der Policy bleibt unangetastet. Aufrufform wie dort: `uv run --project "${CLAUDE_PROJECT_DIR}" ultraloom hook <name> --root "${CLAUDE_PROJECT_DIR}"`.

- [ ] **Step 2: Write the README section**

Ein Abschnitt „Session hooks" hinter „Policy", englisch: die vier Ereignisse, was jedes tut, was Exit 2 **je Ereignis** bedeutet, der Marker `.claude/.no-verify`, der Block-Zähler und der Kurzschluss. Dazu die Warnung, dass `.ultraloom/hooks/` Sitzungszustand hält und weder eingecheckt noch von einem Agenten beschrieben werden soll.

- [ ] **Step 3: Mirror it into README.de.md**

Derselbe Abschnitt auf Deutsch, an derselben Stelle, mit denselben Beispielen.

- [ ] **Step 4: Write the flow document, in both languages**

`docs/abläufe/session-hooks.md` (englisch) und `docs/abläufe/session-hooks.de.md` (deutsch) — `AGENTS.md` verlangt beide, und die Datei ohne Suffix ist die englische. Ein Mermaid-Graph je Datei: Ereignis → Marker? → Zähler? → Kurzschluss? → Kette → Exit-Code. Format wie in `docs/abläufe/verify-until-green.md`. Prüfe, dass der Block wirklich rendert, statt es anzunehmen.

- [ ] **Step 5: Run the chain**

Run: `uv run ultraloom check all` → grün, 100 %

- [ ] **Step 6: The real test**

In einer **neuen** Sitzung im Hauptcheckout: eine Datei ändern, den Zug enden lassen, und beobachten, ob das Stop-Gate greift. Dann die Änderung zurücknehmen und prüfen, dass der Zug ohne Verzögerung endet. Beides berichten — ein Hook, der nur in `pytest` funktioniert, ist keiner.

- [ ] **Step 7: Commit**

```bash
git add .claude/settings.json README.md README.de.md "docs/abläufe"
```

Nachricht:

```
Turn the four session hooks on

With the exit codes written down per event: exit 2 means something
different at every one of them, and getting that wrong is silent.
```

---

## Was danach ansteht, aber nicht hierher gehört

- **Die Worktree-Falle** (`git-dir` == `git-common-dir` unter `.claude/worktrees/`): gehört zu `SessionStart`, hat aber eigene Mechanik und braucht eine eigene Spec.
- **MCP-Werkzeuge in der Policy** — `mcp__<server>__<tool>` kann schreiben und wird nicht geprüft.
- **Das Ausrollen nach space und iam_backend**, je ein eigener Vorgang.
