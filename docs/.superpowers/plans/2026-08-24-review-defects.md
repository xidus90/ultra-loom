# Review-Defekte D1–D3 — Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking. Jeder Test wird zuerst geschrieben und *als rot gesehen*, bevor Implementierung entsteht.

**Goal:** Die drei Defekte aus der Ganz-Projekt-Review vom 24.08.: D1 (leerer Run-Marker endet in rohem Traceback statt Satz), D2 (ein Lauf außerhalb eines Repos darf beginnen, was er auf `resume` nie beenden kann), D3 (zwei Sessionen teilen einen Checkout — hiermit beendet: dieser Plan läuft im isolierten Worktree `.worktrees/review-fixes` auf eigenem Branch `feature/review-fixes`). **Nichts wird gepusht** — ausdrückliche Vorgabe des Nutzers.

**Architecture:** D1 ist eine Zeile Schutz an der Stelle, die `MarkerError` schon für die andere Unlesbarkeitsart hat. D2 verschiebt die Verweigerung dorthin, wo sie hingehört: Ein Flow erklärt bei der Ladung, ob er gegen einen Basis-Commit misst (`LoadedFlow.needs_baseline`, Default `False`), und die CLI verweigert den *Start* früh — bevor Journal oder Marker existieren — statt den Lauf als Zombie zu erlauben, dessen jeder `resume` scheitert. Die bestehende Resume-Verweigerung bleibt stehen: sie bewacht jetzt Alt-Marker und beschädigte Marker, statt die einzige Schutzwand zu sein.

**Tech Stack:** Python 3.13+, `uv`, pytest, mypy (strict), ruff.

**Spec:** Review vom 24.08.2026 (Ganz-Projekt-Review, HEAD `5e7db2b`), Defekte D1/D2/D3.

## Global Constraints

- TDD ohne Ausnahme: rot gesehen, dann minimal grün.
- 100 % Coverage, `fail_under` greift; kein Ausschluss ohne Begründung.
- Statische Typen überall; `uv run mypy src tests` sauber.
- Docstrings und Kommentare englisch (so sprechen es die Dateien), Benutzermeldungen im Ton der je Datei bestehenden Meldungen (englische Sätze).
- Kommentiert wird das Warum, nie die Zeile darunter.
- Tests gegen git benutzen echte Repositories in `tmp_path` und `subprocess`; Commits mit `-c user.name=t -c user.email=t@t`.
- Commit-Nachrichten englisch, mehrzeilig über Datei und `git commit -F <datei>` — nie Heredoc. Je Task ein Commit.
- Gearbeitet wird ausschließlich in `C:/Users/micro/Documents/#GIT/ultraloom/.worktrees/review-fixes`. Der Pfad ist in `.gitignore` (Absicht — isolierter Workspace), der Branch `feature/review-fixes` ist echt und lokal sichtbar. **Kein `git push` in diesem Plan.**
- Ein Shell-Befehl je Aufruf bei git-Operationen.

---

### Task 1 (D1): Ein leerer Marker ist ein Satz, kein Traceback

**Files:**
- Modify: `src/ultraloom/cli.py` (`_recorded_run`, nach dem Einlesen)
- Test: `tests/test_cli.py`

**Interfaces:** Consumes: `MarkerError` (existiert). Produces: nichts Neues — dieselbe Ausnahme deckt nun beide Unlesbarkeitsarten ab: Zeile ohne `=` *und* Datei ohne erste Zeile.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, neben dem vorhandenen Trennzeichen-Test:

```python
def test_an_empty_marker_is_refused_by_name(tmp_path: Path) -> None:
    """An empty marker cannot say which flow a run belongs to.

    `splitlines()` answers it with nothing, and tuple unpacking would end the
    command in a bare ValueError naming neither the file nor the problem --
    the same reason the separator case below raises MarkerError.
    """
    marker = _marker(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8")

    with pytest.raises(MarkerError) as excinfo:
        _recorded_run(tmp_path, "0001")

    assert "0001.flow" in str(excinfo.value)


def test_resume_of_a_run_with_an_empty_marker_names_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command line turns the unreadable marker into a refusal, not a traceback."""
    marker = _marker(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8")

    exit_code = main(["resume", "0001", "--root", str(tmp_path)])

    assert exit_code == EXIT_FAIL
    assert "0001.flow" in capsys.readouterr().err
```

Importe ergänzen: `MarkerError`, `_recorded_run` (falls noch nicht importiert), analog zum vorhandenen Test.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_cli.py -k "empty_marker" -q
```

Erwartet: der Unit-Test scheitert mit `ValueError: not enough values to unpack` — genau der Traceback aus der Review. Der CLI-Test scheitert am Exit-Code bzw. fehlendem Satz.

- [ ] **Step 3: Write the minimal implementation**

In `_recorded_run` direkt nach dem Einlesen:

```python
    lines = marker.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].strip():
        # An empty marker cannot say which flow the run belongs to. Raised
        # rather than unpacked: `flow_name, *rest = lines` would end the
        # command in a bare ValueError naming neither the file nor the
        # problem -- the same reason the separator case below raises.
        raise MarkerError(f"{marker}: says nothing -- not even which flow it belongs to")
    flow_name, *rest = lines
```

- [ ] **Step 4: Verify GREEN + Suite**

```bash
uv run pytest tests/test_cli.py -q
```

- [ ] **Step 5: Commit**

```
Say which marker is empty instead of failing to unpack it

An empty run marker answered resume with a bare ValueError naming
neither the file nor the problem -- the traceback the refusal one
line later existed to prevent.
```

---

### Task 2 (D2): Wer gegen einen Basis-Commit misst, beginnt nicht ohne einen

**Files:**
- Modify: `src/ultraloom/discovery.py` (`LoadedFlow`: neues Feld)
- Modify: `src/ultraloom/flows/verify_until_green.py` (`build`: Deklaration)
- Modify: `src/ultraloom/cli.py` (`_flow_command`, `run`-Zweig: frühe Verweigerung vor `_remember_run`)
- Test: `tests/test_cli.py`, `tests/test_discovery.py`

**Interfaces:**
- Produces: `LoadedFlow.needs_baseline: bool = False` — ein Flow erklärt damit, dass seine Knoten den Lauf gegen den Basis-Commit messen.
- Consumes: `_baseline(root)` (liefert `None` außerhalb eines Repos), bestehende Reihenfolge `find_flow` → Prüfung → `_remember_run` (nichts wird angelegt, wenn verweigert wird).

- [ ] **Step 1: Write the failing tests**

```python
def test_a_guarded_flow_refuses_to_start_outside_a_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A run that every resume would refuse must not be allowed to begin.

    Started outside a repository there is no commit to measure against, the
    pause at the gate would succeed, and every later answer would fail --
    a run begun only to be unfinishable.
    """
    write_flow(tmp_path, "guarded", GUARDED_FLOW)   # wie A_FLOW, aber needs_baseline deklariert
    ...
```

*Umsetzungshinweis:* Der CLI-Test nutzt denselben Weg wie die vorhandenen Outside-Repo-Tests: Flow-Skript nach `.ultraloom/flows/` schreiben, das beim Laden einen `LoadedFlow` mit `needs_baseline=True` zurückgibt (das Flow-Modul baut selbst, also genügt ein Mini-Graph mit einem Code-Knoten plus Deklaration). Dann:

```python
    exit_code = main(["run", "guarded", "--root", str(tmp_path), "--no-model"])

    assert exit_code == EXIT_FAIL
    assert "commit" in capsys.readouterr().err.lower()
    # Nothing of the run exists: no journal, no marker.
    assert not (tmp_path / ".ultraloom" / "runs" / "0001.jsonl").exists()
    assert not (tmp_path / ".ultraloom" / "runs" / "0001.flow").exists()


def test_an_unguarded_flow_still_starts_outside_a_repository(tmp_path: Path) -> None:
    """No baseline, no need: a gate-only flow outside a repository runs as before."""
```

Discovery-Unit-Test:

```python
def test_a_loaded_flow_declares_no_baseline_need_by_default() -> None:
    """Flows that never measure against a commit owe no declaration."""
    assert LoadedFlow(graph=..., initial=...).needs_baseline is False
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_cli.py -k "outside_a_repository" -q
uv run pytest tests/test_discovery.py -k "needs_baseline" -q
```

Erwartet: `AttributeError`/falscher Exit-Code — der Lauf beginnt heute (Exit 3 „paused") statt zu verweigern.

- [ ] **Step 3: Minimal implementation**

1. `discovery.py`: `LoadedFlow` um `needs_baseline: bool = False` erweitern (Docstring: warum die Erklärung beim Flow liegt und der Default nein sagt).
2. `verify_until_green.py::build`: `return LoadedFlow(cast(Graph[object], graph), VerifyState(kinds=kinds), needs_baseline=True)` — mit Why-Kommentar (Guard misst gegen den Basis-Commit; ohne einen wäre jeder Lauf ein Zombie).
3. `cli.py`, `run`-Zweig, nach `find_flow` und vor `_remember_run`:

```python
        if taken is None and loaded.needs_baseline:
            # Before anything of the run exists. A guard flow started without
            # a commit to measure against pauses at its gate and then refuses
            # every resume -- begun only to be unfinishable.
            print(
                f"{flow_name} measures its repairs against the commit it starts "
                f"from, and git gives {root} none; start it inside a repository",
                file=sys.stderr,
            )
            return _EXIT_FAIL
```

(Platzierung so, dass `loaded` bereits geladen ist; `taken` existiert schon.)

- [ ] **Step 4: Verify GREEN + whole suite**

```bash
uv run pytest tests/ -q
```

Der bestehende Resume-Verweigerungstest bleibt grün: Er bewacht jetzt Alt-/Beschädigte Marker.

- [ ] **Step 5: Commit**

```
Refuse a guard run that every resume would refuse

A flow that measures against its starting commit now says so at
load time, and the CLI refuses the start before anything of the
run exists -- instead of allowing a pause that no answer can carry
onward.
```

---

### Task 3: Gate, Doku, Stand festhalten

- [ ] **Step 1: Full Gate**

```bash
uv run coverage run -m pytest -q
uv run coverage report
uv run ruff check .
uv run mypy src tests
```

Erwartet: alle Tests grün, 100 % Line+Branch, ruff sauber, mypy strict sauber.

- [ ] **Step 2: README**

Im Abschnitt zu Grenzen/known limits (falls vorhanden, sonst unter `check`/`run`): zwei Sätze — guard flows brauchen ein Repository, und ein unlesbarer Marker wird benannt statt als Traceback zu enden.

- [ ] **Step 3: Commit + Bericht**

```
Document where guarded runs start and what markers say
```

Danach: `git log --oneline master..HEAD` als Nachweis, **kein Push**.
