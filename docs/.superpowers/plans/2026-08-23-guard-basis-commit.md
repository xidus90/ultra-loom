# Guard misst gegen einen Basis-Commit — Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der guard des Flows `verify-until-green` soll eine berührte Testdatei auch dann finden, wenn der Reparateur sie committet hat.

**Architecture:** Die Grundlinie eines Laufs bekommt neben ihrer Schmutzmenge einen Basis-Commit. Der guard misst `git diff --name-only --no-renames <base>` vereinigt mit dem, was `git status` meldet, statt `git status` allein. Ohne Basis-Commit wird der Lauf verweigert, statt halb zu messen.

**Tech Stack:** Python 3.14, `uv`, pytest, mypy (strict), ruff.

**Spec:** `docs/.superpowers/specs/2026-08-23-guard-basis-commit-design.md`

## Global Constraints

- TDD ohne Ausnahme: jeder Test wird zuerst geschrieben, laufen gelassen und *als rot gesehen*, bevor die Implementierung entsteht.
- 100 % Coverage. Jeder Ausschluss trägt eine Begründung.
- Statische Typen überall; `uv run mypy src tests` muss sauber sein. Kein `Any`, kein `type: ignore` ohne Grund.
- Dieses Projekt schreibt Docstrings und Kommentare englisch, seine Benutzermeldungen deutsch. Beim Bearbeiten einer Datei gilt, was sie schon spricht.
- Kommentiert wird das Warum, nie die Zeile darunter.
- Tests gegen git benutzen echte Repositories in `tmp_path` und `subprocess`, nie eine Attrappe. Commits brauchen `-c user.name=t -c user.email=t@t`, weil keine globale Identität vorausgesetzt werden darf.
- Commit-Nachrichten englisch, mehrzeilig über eine Datei und `git commit -F <datei>` — nie über ein Heredoc.
- Ein Shell-Befehl je Aufruf, keine langen `&&`-Ketten.
- Gearbeitet wird im Projektordner `C:/Users/micro/Documents/#GIT/ultraloom`, **nicht** in einer Kopie unter `.claude/worktrees/`: die ist von `.git/info/exclude` ignoriert, und git meldet dort keine Änderung.

---

### Task 1: `head_commit` — der Basis-Commit, und wann es keinen gibt

**Files:**
- Modify: `src/ultraloom/worktree.py`
- Test: `tests/test_worktree.py`

**Interfaces:**
- Consumes: nichts.
- Produces: `head_commit(root: Path) -> str` — der volle SHA von HEAD. Wirft `WorktreeError`, wenn `root` kein Repository ist, das Repository keinen Commit hat, oder git `root` ignoriert.

- [ ] **Step 1: Write the failing tests**

In `tests/test_worktree.py`, unter dem vorhandenen `_repo`-Helfer:

```python
def test_head_commit_is_the_sha_of_head(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    sha = head_commit(repo)

    assert len(sha) == 40
    assert sha == subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_head_commit_reads_a_detached_head(tmp_path: Path) -> None:
    """A detached HEAD is no special case: the diff needs a commit, not a branch."""
    repo = _repo(tmp_path)
    sha = head_commit(repo)
    subprocess.run(("git", "checkout", "-q", "--detach", sha), cwd=repo, check=True)

    assert head_commit(repo) == sha


def test_a_repository_without_a_commit_has_no_head(tmp_path: Path) -> None:
    """`git init` and nothing else: HEAD names a branch that does not exist yet."""
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)

    with pytest.raises(WorktreeError):
        head_commit(tmp_path)


def test_a_directory_outside_any_repository_has_no_head(tmp_path: Path) -> None:
    outside = tmp_path / "plain"
    outside.mkdir()

    with pytest.raises(WorktreeError):
        head_commit(outside)


def test_head_commit_refuses_a_root_git_ignores(tmp_path: Path) -> None:
    """A project copy parked below an ignored path answers with the *outer* HEAD.

    Measuring against that is worse than not measuring: every file of the copy
    then reads as a change the repairer made.
    """
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("copy/\n", encoding="utf-8")
    copy = repo / "copy"
    copy.mkdir()

    with pytest.raises(WorktreeError):
        head_commit(copy)
```

Die Importzeile der Testdatei wird zu:
`from ultraloom.worktree import WorktreeError, changed_files, head_commit`

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_worktree.py -k head_commit -q
```

Erwartet: `ImportError: cannot import name 'head_commit'`.

- [ ] **Step 3: Write the implementation**

In `src/ultraloom/worktree.py`, hinter `changed_files`:

```python
def head_commit(root: Path) -> str:
    """The commit a run starts on, as git spells it.

    `rev-parse HEAD` and not `--short`: the answer travels in a run marker and
    is read back rounds later, and an abbreviated SHA is only unique for as
    long as the repository stays the size it was.

    Three ways of having no answer, all of them `WorktreeError`: no repository,
    a repository without a commit -- `git init` leaves HEAD naming a branch
    that does not exist yet -- and a root git ignores. The last one is why
    `_refuse_if_ignored` is asked here at all: such a directory *is* inside a
    repository, so `rev-parse` answers readily with the surrounding
    repository's HEAD. Measuring against that is worse than not measuring, as
    every file of the parked copy then reads as the repairer's doing.
    """
    _refuse_if_ignored(root)
    return _git(root, "rev-parse", "HEAD").strip()
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_worktree.py -q
```

- [ ] **Step 5: Commit**

Nachricht in eine Datei schreiben, dann `git add src/ultraloom/worktree.py tests/test_worktree.py` und `git commit -F <datei>`:

```
Read the commit a run starts on

Three ways of having no answer and all of them refused, the ignored root
above all: it answers with the surrounding repository's HEAD, which is a
worse baseline than none at all.
```

---

### Task 2: `changed_since` — was sich seit dem Basis-Commit geändert hat

**Files:**
- Modify: `src/ultraloom/worktree.py`
- Test: `tests/test_worktree.py`

**Interfaces:**
- Consumes: `head_commit(root: Path) -> str` aus Task 1; die vorhandenen `_status`, `_parse_status`, `_prefix`, `_refuse_if_ignored`, `_git`, `RUN_DIR`.
- Produces: `changed_since(root: Path, base: str) -> tuple[str, ...]` — jeder Pfad, der sich zwischen dem Baum von `base` und dem jetzigen Arbeitsbaum unterscheidet, plus jeder untracked Pfad. Relativ zu `root`, ohne `RUN_DIR`, sortiert und dublettenfrei.

- [ ] **Step 1: Write the failing tests**

```python
def test_changed_since_sees_a_commit_the_working_tree_no_longer_shows(tmp_path: Path) -> None:
    """The blind spot this whole change exists for."""
    repo = _repo(tmp_path)
    base = head_commit(repo)
    (repo / "tests" / "test_cli.py").write_text("x = 2\n", encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=repo, check=True)
    subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "sneaky"),
        cwd=repo,
        check=True,
    )

    assert changed_files(repo) == ()  # the tree is clean -- and that is the point
    assert changed_since(repo, base) == ("tests/test_cli.py",)


def test_changed_since_reports_an_untracked_file(tmp_path: Path) -> None:
    """`diff` cannot see one, so the status answer is unioned in."""
    repo = _repo(tmp_path)
    base = head_commit(repo)
    (repo / "new.py").write_text("z = 3\n", encoding="utf-8")

    assert changed_since(repo, base) == ("new.py",)


def test_changed_since_names_both_sides_of_a_rename(tmp_path: Path) -> None:
    """--no-renames, so a test moved out of the way cannot walk past the guard."""
    repo = _repo(tmp_path)
    base = head_commit(repo)
    subprocess.run(("git", "mv", "tests/test_cli.py", "src_test.py"), cwd=repo, check=True)
    subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "moved"),
        cwd=repo,
        check=True,
    )

    assert set(changed_since(repo, base)) == {"tests/test_cli.py", "src_test.py"}


def test_changed_since_reports_a_path_once(tmp_path: Path) -> None:
    """Committed *and* edited again: diff and status both name it."""
    repo = _repo(tmp_path)
    base = head_commit(repo)
    (repo / "a.c").write_text("int one;\n", encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=repo, check=True)
    subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one"),
        cwd=repo,
        check=True,
    )
    (repo / "a.c").write_text("int two;\n", encoding="utf-8")

    assert changed_since(repo, base) == ("a.c",)


def test_changed_since_leaves_out_the_run_directory(tmp_path: Path) -> None:
    """ultraloom's own journal is not the repairer's doing."""
    repo = _repo(tmp_path)
    base = head_commit(repo)
    runs = repo / RUN_DIR
    runs.mkdir(parents=True)
    (runs / "0001.jsonl").write_text("{}\n", encoding="utf-8")

    assert changed_since(repo, base) == ()


def test_changed_since_answers_relative_to_root_in_a_monorepo(tmp_path: Path) -> None:
    """git answers repository-relative whatever the working directory is."""
    repo = _repo(tmp_path)
    package = repo / "package"
    (package / "tests").mkdir(parents=True)
    (package / "tests" / "test_x.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=repo, check=True)
    subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "package"),
        cwd=repo,
        check=True,
    )
    base = head_commit(package)
    (package / "tests" / "test_x.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "gone.py").write_text("elsewhere\n", encoding="utf-8")

    # Relative to `root`, and nothing from outside it: that is not this
    # project's change.
    assert changed_since(package, base) == ("tests/test_x.py",)


def test_changed_since_refuses_a_root_git_ignores(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = head_commit(repo)
    (repo / ".gitignore").write_text("copy/\n", encoding="utf-8")
    copy = repo / "copy"
    copy.mkdir()

    with pytest.raises(WorktreeError):
        changed_since(copy, base)


def test_changed_since_refuses_a_base_git_does_not_know(tmp_path: Path) -> None:
    """An unresolvable base must never read as "nothing changed"."""
    repo = _repo(tmp_path)

    with pytest.raises(WorktreeError):
        changed_since(repo, "0" * 40)
```

Importzeile der Testdatei:
`from ultraloom.worktree import RUN_DIR, WorktreeError, changed_files, changed_since, head_commit`

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_worktree.py -k changed_since -q
```

Erwartet: `ImportError: cannot import name 'changed_since'`.

- [ ] **Step 3: Lift the shared tail out of `changed_files`, then implement**

`changed_files` und `changed_since` beantworten dieselbe Frage in derselben Schreibweise; die Umrechnung darf nur einmal existieren, sonst laufen die beiden Antworten genau dort auseinander, wo der guard sie vergleicht. In `src/ultraloom/worktree.py`:

```python
def _relocate(root: Path, paths: tuple[str, ...]) -> tuple[str, ...]:
    """Repository-relative paths as a caller below `root` spells them.

    Anything outside `root` is dropped -- it is not this project's change --
    and so is everything below `RUN_DIR`, which is ultraloom's own doing and
    never the repairer's. Both callers go through here, because two spellings
    of the same path would end up being compared against each other.
    """
    if not paths:
        # Nothing to relocate, so the second git call is not worth its process.
        return paths
    prefix = _prefix(root)
    if prefix:
        paths = tuple(path[len(prefix) :] for path in paths if path.startswith(prefix))
    # After the relocation, so the comparison is against the spelling a caller
    # below `root` would use rather than the repository-relative one.
    return tuple(path for path in paths if not path.startswith(RUN_DIR + "/"))
```

`changed_files` endet damit auf

```python
    _refuse_if_ignored(root)
    return _relocate(root, _parse_status(_status(root)))
```

Der erklärende Docstring von `changed_files` bleibt vollständig stehen; nur der Rumpf schrumpft. Dann:

```python
def changed_since(root: Path, base: str) -> tuple[str, ...]:
    """Every path that differs between `base` and the working tree, below `root`.

    The union of two questions, because neither answers alone: `diff` sees what
    was committed since `base` but is blind to an untracked file, and `status`
    sees the untracked file but reads a committed change as a clean tree. That
    second blindness is why this function exists -- a repairer that commits its
    edit leaves `status` with nothing to report, and the guard built on it then
    lets an edited test file through.

    `--no-renames`, so a rename comes back as its old *and* its new path. Git
    would otherwise report the pair as one entry, and a test moved out of the
    way would be a path the guard never compares against its protected list.

    Content-based, so a `reset`, a `rebase` or an `amend` hides nothing: this
    compares the tree of `base` against the tree on disk, not two histories.

    An unresolvable `base` is a `WorktreeError` and never an empty answer, for
    the reason every refusal in this module has: a question git cannot answer
    must not be read as "nothing changed".
    """
    _refuse_if_ignored(root)
    diff = _git(root, "diff", "--name-only", "--no-renames", base)
    committed = tuple(line for line in diff.splitlines() if line)
    reported = _parse_status(_status(root))
    return tuple(sorted(set(_relocate(root, committed)) | set(_relocate(root, reported))))
```

Zwei Hinweise für den Umsetzer:

- `git diff <base>` vergleicht `base` mit dem Arbeitsbaum und schließt Gestagetes ein; ein zweiter Aufruf mit `--cached` ist nicht nötig.
- `_parse_status` liefert hier mehr als nur untracked-Pfade. Das ist beabsichtigt und billiger als ein zweites Statusformat, weil die Vereinigung die Dubletten schluckt.

- [ ] **Step 4: Run the whole worktree suite**

```bash
uv run pytest tests/test_worktree.py -q
```

Erwartet: alles grün, die bestehenden `changed_files`-Tests eingeschlossen — der Umbau darf sie nicht bewegen.

- [ ] **Step 5: Commit**

`git add src/ultraloom/worktree.py tests/test_worktree.py`, dann `git commit -F <datei>` mit:

```
Answer what changed since a commit, not since HEAD

A repairer that commits its edit leaves a clean working tree, so status
alone reports nothing. The diff sees it; the union with status keeps the
untracked file that a diff cannot see.
```

---

### Task 3: `Baseline` — die Grundlinie bekommt ihren Bezugspunkt

**Files:**
- Modify: `src/ultraloom/discovery.py:28-48`
- Test: `tests/test_discovery.py`

**Interfaces:**
- Consumes: nichts.
- Produces: `Baseline(commit: str, dirty: frozenset[str] = frozenset())`, und `FlowContext.baseline` wird von `frozenset[str] | None` zu `Baseline | None`.

- [ ] **Step 1: Write the failing test**

In `tests/test_discovery.py`:

```python
def test_a_baseline_carries_both_halves_of_the_starting_state() -> None:
    """Neither half replaces the other: the commit is what a change is measured
    against, the dirty set is what must not be laid at the repairer's door."""
    root = Path(".")
    baseline = Baseline(commit="abc", dirty=frozenset({"src/a.py"}))
    context = FlowContext(
        root=root, config=Config(root=root, test_paths=("tests/",)), baseline=baseline
    )

    assert context.baseline is not None
    assert context.baseline.commit == "abc"
    assert context.baseline.dirty == frozenset({"src/a.py"})
```

`Baseline` in die Importzeile aus `ultraloom.discovery` aufnehmen.

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_discovery.py -k baseline_carries -q
```

Erwartet: `ImportError: cannot import name 'Baseline'`.

- [ ] **Step 3: Implement**

In `src/ultraloom/discovery.py`, über `FlowContext`:

```python
@dataclass(frozen=True, slots=True)
class Baseline:
    """What the working tree looked like when a run started.

    Two halves, and neither stands in for the other. `commit` is what a change
    is measured *against*, so a repairer that commits its edit stays as visible
    as one that leaves it unstaged. `dirty` is what was already changed at that
    moment and must not be laid at the repairer's door.

    Frozen and carried in the run marker, because the question "what did this
    run start from" has one right answer and it comes into being at the start.
    """

    commit: str
    dirty: frozenset[str] = frozenset()
```

Das Feld wird `baseline: Baseline | None = None`, und der Absatz über `baseline` im Docstring von `FlowContext` wird auf beide Hälften umgeschrieben — mit dem alten Satz, dass `None` etwas anderes heißt als „der Baum war sauber".

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_discovery.py -q
```

`tests/test_cli.py` und `tests/flows/test_verify_until_green.py` sind an dieser Stelle rot. Das ist erwartet und wird in Task 4 und 5 geschlossen.

- [ ] **Step 5: Commit**

`git add src/ultraloom/discovery.py tests/test_discovery.py`, dann `git commit -F <datei>`:

```
Give the baseline the commit it is measured against

A set of paths says what was already dirty but not what it was dirty
against. Both halves travel together from here on.
```

---

### Task 4: Der Run-Marker merkt sich den Basis-Commit

**Files:**
- Modify: `src/ultraloom/cli.py:190-260`, `src/ultraloom/cli.py:305-405`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Baseline` aus Task 3, `head_commit` aus Task 1.
- Produces:
  - `_baseline(root: Path) -> Baseline | None` — `None`, wo es keinen Basis-Commit gibt.
  - `_recorded_run(root: Path, run_id: str) -> tuple[str, dict[str, str], Baseline | None] | None` — die Grundlinie ist `None`, wenn der Marker keine `baseline_commit`-Zeile hat.
  - `_remember_run(root: Path, run_id: str, flow_name: str, options: dict[str, str], baseline: Baseline | None) -> None`.
  - Neue Markerzeile `baseline_commit=<sha>` neben `baseline=`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_run_records_the_commit_it_started_on(tmp_path: Path) -> None:
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    (tmp_path / "seed.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=tmp_path, check=True)
    subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first"),
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "dirty.py").write_text("y = 2\n", encoding="utf-8")
    write_flow(tmp_path, "plain", A_FLOW)

    main(["run", "plain", "--root", str(tmp_path), "--no-model"])

    recorded = _recorded_run(tmp_path, "0001")
    assert recorded is not None
    _, options, baseline = recorded
    assert baseline is not None
    assert baseline.commit == head_commit(tmp_path)
    assert "dirty.py" in baseline.dirty
    # Neither half is an option a flow validates.
    assert "baseline" not in options
    assert "baseline_commit" not in options


def test_a_marker_without_a_baseline_commit_records_no_baseline(tmp_path: Path) -> None:
    """A run started before this rule existed. Half a baseline is no baseline."""
    marker = _marker(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('plain\nbaseline="tests/a.py"\n', encoding="utf-8")

    recorded = _recorded_run(tmp_path, "0001")

    assert recorded == ("plain", {}, None)


def test_resume_refuses_a_run_that_recorded_no_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Filling the commit in now would hand the repairer everything it
    committed before the pause as its starting state."""
    write_flow(tmp_path, "plain", A_FLOW)
    marker = _marker(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("plain\n", encoding="utf-8")
    (tmp_path / ".ultraloom" / "runs" / "0001.jsonl").write_text("", encoding="utf-8")

    code = main(["resume", "0001", "--root", str(tmp_path), "--no-model"])

    assert code == _EXIT_FAIL
    assert "started before" in capsys.readouterr().err


def test_a_run_outside_a_repository_records_no_baseline(tmp_path: Path) -> None:
    """No commit, no baseline -- and the flow that needs one says so itself."""
    write_flow(tmp_path, "plain", A_FLOW)

    main(["run", "plain", "--root", str(tmp_path), "--no-model"])

    recorded = _recorded_run(tmp_path, "0001")
    assert recorded is not None and recorded[2] is None
```

Die vorhandenen Tests werden mitgezogen, nicht neu erfunden:

- `test_a_run_records_what_was_already_dirty` — prüft jetzt `baseline.dirty`, und das `tmp_path`-Repository braucht einen ersten Commit, damit überhaupt eine Grundlinie entsteht.
- `test_a_resumed_run_keeps_the_baseline_of_its_first_start` — `_remember_run(..., Baseline("abc", frozenset({"tests/a.py"})))`, und die Zusicherung vergleicht gegen `Baseline("abc", frozenset({"tests/a.py"}))`.
- `test_a_baseline_of_many_paths_stays_one_marker_line` — `_remember_run(..., Baseline("abc", paths))` und erwartet jetzt **drei** Markerzeilen statt zwei.
- `test_a_clean_tree_is_recorded_as_an_empty_baseline_not_as_none` — `_remember_run(..., Baseline("abc", frozenset()))`, und `recorded[2] == Baseline("abc", frozenset())`.
- `test_a_marker_from_before_the_baseline_existed_still_reads` — bleibt inhaltlich, erwartet für die Grundlinie aber `None`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_cli.py -k baseline -q
```

- [ ] **Step 3: Implement**

In `src/ultraloom/cli.py` neben `_BASELINE`:

```python
_BASELINE_COMMIT = "baseline_commit"
```

`_remember_run` nimmt `baseline: Baseline | None` und schreibt beide Schlüssel, oder keinen:

```python
    if baseline is not None:
        options = options | {
            _BASELINE: "\n".join(sorted(baseline.dirty)),
            _BASELINE_COMMIT: baseline.commit,
        }
```

Der Marker wird auch ohne Grundlinie geschrieben — ohne ihn fände `resume` den Flow nicht, und die Absage soll von der Grundlinie kommen und nicht von einer fehlenden Datei.

`_recorded_run` liest beide zurück und gibt nur dann eine Grundlinie heraus, wenn der Commit dabei ist:

```python
    dirty = options.pop(_BASELINE, None)
    commit = options.pop(_BASELINE_COMMIT, None)
    # Both or neither. A marker holding only the path set was written before
    # the commit existed, and reading it as a baseline would measure the run
    # against a tree the repairer has already had its hands on.
    baseline = None if commit is None else Baseline(commit, _decode_baseline(dirty or ""))
    return flow_name.strip(), options, baseline
```

`_baseline` gibt `None` zurück, wo es keinen Commit gibt:

```python
def _baseline(root: Path) -> Baseline | None:
    """What a run starts from, or None where git cannot say.

    The dirty set is only worth taking once a commit stands behind it: without
    one there is nothing to measure a change against, and half a baseline reads
    like a whole one at every later call site. The flow that needs one refuses
    the run; a flow that does not never needed git at all.
    """
    try:
        return Baseline(head_commit(root), frozenset(changed_files(root)))
    except WorktreeError:
        return None
```

Im `run`-Zweig wird `taken` damit `Baseline | None`. Im `resume`/`replay`-Zweig, direkt nach dem Auspacken von `recorded`:

```python
        if baseline is None:
            print(
                f"run {run_id} was started before the guard measured against a "
                "commit, or outside a repository; start a new run with "
                "`ultraloom run`",
                file=sys.stderr,
            )
            return _EXIT_FAIL
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_cli.py -q
```

- [ ] **Step 5: Commit**

`git add src/ultraloom/cli.py tests/test_cli.py`, dann `git commit -F <datei>`:

```
Carry the starting commit in the run marker

Taken once and read back on every continuation. Asking git again on
resume would answer with the tree the repairer has meanwhile edited, and
a run that recorded no commit is refused rather than measured by half.
```

---

### Task 5: Der guard misst gegen den Basis-Commit

**Files:**
- Modify: `src/ultraloom/flows/verify_until_green.py:31`, `:325-380`, `:435-500`, `:515-540`
- Test: `tests/flows/test_verify_until_green.py`

**Interfaces:**
- Consumes: `changed_since`, `head_commit`, `changed_files`, `WorktreeError` aus `ultraloom.worktree`; `Baseline` aus `ultraloom.discovery`.
- Produces:
  - `type Differ = Callable[[Path, str], tuple[str, ...]]`
  - `make_guard(root: Path, test_paths: tuple[str, ...], differ: Differ = changed_since, baseline: Baseline | None = None) -> Callable[[VerifyState], Delta]` — wirft `ValueError` ohne `baseline`.
  - `assemble(config: Config, root: Path, check_runner: CheckRunner | None = None, differ: Differ = changed_since, max_rounds: int = 5, baseline: Baseline | None = None, head: Callable[[Path], str] = head_commit) -> Graph[VerifyState]`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_committed_test_file_still_stops_the_run() -> None:
    """The blind spot: the guard must not depend on the tree staying dirty."""
    guard = make_guard(
        Path("."),
        ("tests/",),
        differ=lambda _root, _base: ("tests/test_cli.py",),
        baseline=Baseline("abc", frozenset()),
    )

    with pytest.raises(FlowExit) as raised:
        guard(VerifyState())

    assert raised.value.code == 4
    assert "tests/test_cli.py" in str(raised.value)


def test_the_guard_measures_against_the_recorded_commit() -> None:
    """Not against HEAD, which the repairer may have moved."""
    seen: list[str] = []

    def differ(_root: Path, base: str) -> tuple[str, ...]:
        seen.append(base)
        return ()

    guard = make_guard(
        Path("."), ("tests/",), differ=differ, baseline=Baseline("abc", frozenset())
    )
    guard(VerifyState())

    assert seen == ["abc"]


def test_a_guard_without_a_baseline_is_refused() -> None:
    """A guard with no reference point cannot tell a repair from a starting state."""
    with pytest.raises(ValueError, match="baseline"):
        make_guard(Path("."), ("tests/",), differ=lambda _root, _base: ())


def test_assemble_refuses_a_project_with_no_commit_to_measure_against(tmp_path: Path) -> None:
    """Before the first repair round, not after it: the run cannot be guarded."""

    def head(_root: Path) -> str:
        raise WorktreeError("no HEAD here")

    with pytest.raises(ValueError, match="commit"):
        assemble(
            config=Config(root=tmp_path, test_paths=("tests/",)),
            root=tmp_path,
            differ=lambda _root, _base: (),
            head=head,
        )


def test_build_refuses_a_project_with_no_commit(tmp_path: Path) -> None:
    """The same refusal on the road a real run takes."""
    context = FlowContext(root=tmp_path, config=Config(root=tmp_path, test_paths=("tests/",)))

    with pytest.raises(ValueError, match="commit"):
        build(context)
```

Die vorhandenen guard-Tests werden mitgezogen: jedes `differ=lambda _root: ...` wird `differ=lambda _root, _base: ...`, jedes `baseline=frozenset({...})` wird `baseline=Baseline("abc", frozenset({...}))`. Der Helfer `_run_flow` übergibt `differ=lambda _root, _base: next(diffs, ())` und `baseline=Baseline("abc", frozenset())`. `test_assemble_takes_the_baseline_once_when_it_builds_the_graph` bekommt zusätzlich `head=lambda _root: "abc"` und zählt weiter die Differ-Aufrufe.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/flows/test_verify_until_green.py -q
```

- [ ] **Step 3: Implement**

Importe:

```python
from ultraloom.discovery import Baseline, FlowContext, LoadedFlow
from ultraloom.worktree import WorktreeError, changed_files, changed_since, head_commit
```

```python
type Differ = Callable[[Path, str], tuple[str, ...]]
```

`make_guard` nimmt `baseline: Baseline | None = None` und verweigert `None`:

```python
    if baseline is None:
        raise ValueError(
            "guard needs a baseline: without a commit to measure against it "
            "cannot tell a repair from what the tree already looked like"
        )
```

Im Rumpf wird `differ(root)` zu `differ(root, baseline.commit)`, und `touched` subtrahiert `baseline.dirty` statt der bisherigen Menge. Der Docstring bekommt einen Absatz dazu, dass gegen einen Commit gemessen wird — ein Commit des Reparateurs ist damit sichtbar wie eine ungestagte Änderung, und `reset`, `rebase` und `amend` verstecken nichts, weil der Diff Inhalte vergleicht und keine Historien. Der Absatz über den Preis (eine vorher schon schmutzige Datei, die der Reparateur danach ebenfalls anfasst, bleibt unsichtbar) bleibt unverändert stehen: er gilt weiter.

`assemble` nimmt `head: Callable[[Path], str] = head_commit` dazu, und der bisherige `baseline is None`-Zweig wird ersetzt:

```python
    if baseline is None:
        try:
            baseline = Baseline(head(root), frozenset(changed_files(root)))
        except WorktreeError as error:
            # Refused, not fallen back on: a guard measuring against nothing is
            # a guard that says yes to everything, and saying no is this flow's
            # whole job. Raised here rather than in `build`, so a direct caller
            # takes the same refusal the command line does -- and it lands
            # before the first repair round rather than after it.
            raise ValueError(
                "verify-until-green needs a commit to measure the repairer "
                f"against, and git gives none for {root}: {error}"
            ) from error
```

Der alte Kommentar über das Schlucken des `WorktreeError` verschwindet mitsamt seiner Begründung — sie gilt nicht mehr. `build` reicht `context.baseline` unverändert weiter; die Absage kommt aus `assemble`.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/flows/test_verify_until_green.py -q
```

- [ ] **Step 5: Commit**

`git add src/ultraloom/flows/verify_until_green.py tests/flows/test_verify_until_green.py`, dann `git commit -F <datei>`:

```
Measure the repairer against the commit the run started on

A commit is now as visible to the guard as an unstaged edit, so the rule
no longer rests on the edit profile happening to lack Bash. A project
with no commit to measure against is refused before the first round.
```

---

### Task 6: Ein Lauf über ein echtes Repository, Ende zu Ende

**Files:**
- Test: `tests/flows/test_verify_until_green.py`

**Interfaces:**
- Consumes: alles aus Task 1 bis 5.
- Produces: nichts.

Die Tests aus Task 5 fahren gegen einen eingespeisten Differ. Dieser hier fährt gegen git, weil genau die Verdrahtung zwischen Flow und `changed_since` die Stelle ist, an der die Sperre bisher auseinanderfiel.

- [ ] **Step 1: Write the failing test**

```python
def test_a_repairer_that_commits_a_test_file_does_not_get_past_the_real_guard(
    tmp_path: Path,
) -> None:
    """No injected differ: the wiring between the flow and git is the point."""
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("assert False\n", encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=tmp_path, check=True)
    subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first"),
        cwd=tmp_path,
        check=True,
    )

    def runner(
        kind: str, _config: Config, _alongside: frozenset[str] = frozenset()
    ) -> CheckResult:
        return CheckResult(kind, False, f"{kind} is unhappy", "test")

    def repair_then_commit() -> None:
        (tmp_path / "tests" / "test_a.py").write_text("assert True\n", encoding="utf-8")
        subprocess.run(("git", "add", "-A"), cwd=tmp_path, check=True)
        subprocess.run(
            ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "sneaky"),
            cwd=tmp_path,
            check=True,
        )

    graph = assemble(
        config=Config(root=tmp_path, test_paths=("tests/",)),
        root=tmp_path,
        check_runner=runner,
        max_rounds=2,
    )
    model = FakeModel(
        [Reply(RepairResult("done", changed=True), tokens=0, side_effect=repair_then_commit)]
    )
    result = Runner(graph, Journal(tmp_path / "run.jsonl"), model=model).run(
        VerifyState(kinds=("test",))
    )

    assert result.exit_code == 4
    assert "tests/test_a.py" in (result.detail or "")
```

Hinweis: `Reply` in dieser Datei kennt heute kein `side_effect`. Falls es fehlt, wird der Attrappe ein optionales `side_effect: Callable[[], None] | None = None` gegeben, das `FakeModel` vor der Rückgabe aufruft. Das ist die Attrappe des Tests, nicht Produktionscode — und `.ultraloom/runs` liegt hier ohnehin außerhalb dessen, was `changed_since` meldet.

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/flows/test_verify_until_green.py -k real_guard -q
```

- [ ] **Step 3: Make it pass**

Sitzen Task 1 bis 5 richtig, braucht dieser Test keinen weiteren Produktionscode — nur das `side_effect` in der Attrappe. Scheitert er trotzdem, ist das ein echter Befund und wird in `verify_until_green.py` oder `worktree.py` behoben, nie im Test weggeschrieben.

- [ ] **Step 4: Run the full gate**

```bash
uv run pytest -q
```

```bash
uv run mypy src tests
```

```bash
uv run ruff check src tests
```

- [ ] **Step 5: Commit**

`git add tests/flows/test_verify_until_green.py`, dann `git commit -F <datei>`:

```
Prove the guard against a real repository, not an injected differ

Every other test hands the guard a scripted answer. This one lets the
repairer actually commit, because the wiring between the flow and git is
where the rule used to fall apart.
```

---

### Task 7: Doku und Coverage

**Files:**
- Modify: `docs/abläufe/verify-until-green.md`
- Test: `tests/test_flow_docs.py` (läuft unverändert)

- [ ] **Step 1: Read the page and find what became false**

```bash
uv run python -c "print(open('docs/abläufe/verify-until-green.md', encoding='utf-8').read())"
```

Der Graph ändert sich nicht — `check`, `repair`, `guard`, `report_red` und alle Kanten bleiben, also bleibt auch das Mermaid-Bild wie es ist. Falsch geworden ist die Prosa zum guard-Knoten: sie beschreibt das Lesen des Arbeitsbaums.

- [ ] **Step 2: Rewrite the guard section**

Die neue Fassung sagt: der guard misst gegen den Commit, auf dem der Lauf begonnen hat, vereinigt mit dem, was `git status` meldet; ein Commit des Reparateurs ist damit so sichtbar wie eine ungestagte Änderung; was vor dem Lauf schon schmutzig war, bleibt entschuldigt; ein Projekt ohne Commit wird abgelehnt, bevor die erste Reparaturrunde läuft. Der schon bekannte Preis bleibt benannt: eine vorher schon schmutzige Datei, die der Reparateur danach ebenfalls anfasst, bleibt unsichtbar.

- [ ] **Step 3: Run the documentation test**

```bash
uv run pytest tests/test_flow_docs.py -q
```

- [ ] **Step 4: Check coverage**

```bash
uv run pytest --cov=ultraloom --cov-report=term-missing -q
```

Erwartet: 100 %. Jede unerreichte Zeile wird entweder getestet oder mit einer Begründung ausgeschlossen — nie stillschweigend.

- [ ] **Step 5: Commit**

`git add "docs/abläufe/verify-until-green.md"`, dann `git commit -F <datei>`:

```
Say what the guard actually measures

The page described a guard reading the working tree. It reads a diff
from the run's starting commit now, and a drawing nobody checks is a lie
six months later.
```
