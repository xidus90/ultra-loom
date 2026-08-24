# Agent Settings Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein ultraloom-Reparaturlauf lädt nur noch die versionierten Einstellungen des Zielprojekts, und ein Projekt kann stattdessen eine Datei benennen.

**Architecture:** Ein neuer TOML-Schlüssel `[agent].settings` trägt beides. Beim Laden der Konfiguration wird seine Liste in zwei Felder aufgeteilt — reservierte Wörter werden zu `setting_sources`, ein Pfad wird zu `settings_file`. Beide reisen wie `cli_path` über `_model` zum Adapter und landen in `_options_for`. Kein Weg durch `runner.py`, weil das eine Eigenschaft des Modells ist und nicht eines Requests.

**Tech Stack:** Python 3.13, `uv`, pytest, `claude-agent-sdk` (Extra `agent`), TOML über `tomllib`.

**Spec:** `docs/.superpowers/specs/2026-08-24-agent-settings-sources-design.md`

## Global Constraints

- Doku, Prosa und Kommentare deutsch; Code, Bezeichner, Commits und Meldungen englisch.
- TDD: erst der fallende Test, dann die minimale Implementierung.
- 100 % Coverage; ein Ausschluss immer mit Begründung.
- Statische Typen, kein `Any` und kein `type: ignore` ohne Grund.
- Kommentiere das Warum, nie die Zeile darunter.
- Tests laufen mit `uv run pytest`, Linter mit `uv run ruff check .`, Typen mit `uv run mypy src tests`.
- Die drei reservierten Wörter heißen exakt `"user"`, `"project"`, `"local"` — sie sind `SettingSource` aus dem SDK, nicht frei gewählt.
- Standard ohne Schlüssel: `("project",)` und kein Pfad.
- Reihenfolge der Liste bedeutet nichts; `setting_sources` wird sortiert und doppelfrei abgelegt, weil es Teil des Prompt-Cache-Präfixes wird (dieselbe Begründung wie in `tools.py`).
- Höchstens ein Pfad. Mehrere sind ein `ConfigError`.
- Der Entwurf fügt **keinen** MCP-Schalter hinzu; `[agent].mcp_servers` bleibt unverändert.

---

### Task 1: Der Konfigurationsschlüssel

**Files:**
- Modify: `src/ultraloom/config.py` (Konstanten oben bei `CLI_PATH_ENV`, `Config`-Felder bei `cli_path`, Aufruf im Rumpf von `load_config` neben `cli_path = _cli_path(...)`, neue Funktion `_settings_from` hinter `_cli_path`)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nichts aus früheren Tasks.
- Produces:
  - `Config.setting_sources: tuple[str, ...]`, Standard `("project",)`
  - `Config.settings_file: Path | None`, Standard `None`
  - `_settings_from(configured: object, root: Path, path: Path) -> tuple[tuple[str, ...], Path | None]`

- [ ] **Step 1: Write the failing tests**

Ans Ende von `tests/test_config.py` anhängen:

```python
def test_without_the_key_a_run_loads_the_projects_own_settings(tmp_path: Path) -> None:
    write_config(tmp_path, "[agent]\n")

    config = load_config(tmp_path)

    assert config.setting_sources == ("project",)
    assert config.settings_file is None


def test_the_reserved_words_become_setting_sources(tmp_path: Path) -> None:
    write_config(tmp_path, '[agent]\nsettings = ["local", "project"]\n')

    assert load_config(tmp_path).setting_sources == ("local", "project")


def test_the_order_of_the_list_does_not_travel(tmp_path: Path) -> None:
    """Sorted and duplicate-free: it becomes part of a prompt cache prefix."""
    write_config(tmp_path, '[agent]\nsettings = ["project", "local", "project"]\n')

    assert load_config(tmp_path).setting_sources == ("local", "project")


def test_an_empty_list_is_isolation_and_not_the_default(tmp_path: Path) -> None:
    write_config(tmp_path, "[agent]\nsettings = []\n")

    config = load_config(tmp_path)

    assert config.setting_sources == ()
    assert config.settings_file is None


def test_a_path_becomes_the_settings_file(tmp_path: Path) -> None:
    (tmp_path / "hooks").mkdir()
    named = tmp_path / "hooks" / "repair.json"
    named.write_text("{}", encoding="utf-8")
    write_config(tmp_path, '[agent]\nsettings = ["hooks/repair.json"]\n')

    config = load_config(tmp_path)

    assert config.setting_sources == ()
    assert config.settings_file == named


def test_words_and_a_path_may_be_mixed(tmp_path: Path) -> None:
    named = tmp_path / "repair.json"
    named.write_text("{}", encoding="utf-8")
    write_config(tmp_path, '[agent]\nsettings = ["project", "repair.json"]\n')

    config = load_config(tmp_path)

    assert config.setting_sources == ("project",)
    assert config.settings_file == named


def test_settings_that_are_not_a_list_of_strings_are_refused(tmp_path: Path) -> None:
    write_config(tmp_path, "[agent]\nsettings = 1\n")

    with pytest.raises(ConfigError, match=r"\[agent\].settings must be a list of strings"):
        load_config(tmp_path)


def test_two_files_are_refused_because_the_sdk_loads_one(tmp_path: Path) -> None:
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    write_config(tmp_path, '[agent]\nsettings = ["a.json", "b.json"]\n')

    with pytest.raises(ConfigError, match="the SDK loads one"):
        load_config(tmp_path)


def test_a_file_that_is_not_there_is_refused_with_the_three_words(tmp_path: Path) -> None:
    write_config(tmp_path, '[agent]\nsettings = ["porject"]\n')

    with pytest.raises(ConfigError, match="nor an existing file"):
        load_config(tmp_path)


def test_managed_settings_are_named_rather_than_read_as_a_path(tmp_path: Path) -> None:
    write_config(tmp_path, '[agent]\nsettings = ["managed"]\n')

    with pytest.raises(ConfigError, match="managed settings always apply"):
        load_config(tmp_path)
```

Und in `test_a_project_without_a_config_gets_empty_defaults` zwei Zeilen ergänzen, direkt hinter `assert config.mcp_servers == ()`:

```python
    assert config.setting_sources == ("project",)
    assert config.settings_file is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py -k "settings or reserved or managed or isolation" -v`
Expected: FAIL mit `AttributeError: 'Config' object has no attribute 'setting_sources'`

- [ ] **Step 3: Write the minimal implementation**

In `src/ultraloom/config.py`, hinter der Konstante `CLI_PATH_ENV`:

```python
# The three settings files Claude Code discovers on its own. Anything else in
# [agent].settings is a path to one more file, and that one the SDK loads into
# the flag layer, where it outranks all three.
_SETTING_SOURCES = ("user", "project", "local")

# The fourth level. Named here so it can be refused with its own reason rather
# than die as a file that is not there -- it always applies, and nothing
# ultraloom sets overrides it.
_MANAGED = "managed"
```

In `Config`, hinter dem Feld `cli_path`:

```python
    # Which settings a run loads, and one file it loads on top of them. Sorted
    # and duplicate-free: this ends up in the CLI command and therefore in a
    # prompt cache prefix, where set iteration order must never leak.
    setting_sources: tuple[str, ...] = ("project",)
    settings_file: Path | None = None
```

Hinter der Funktion `_cli_path`:

```python
def _settings_from(
    configured: object, root: Path, path: Path
) -> tuple[tuple[str, ...], Path | None]:
    """The words become sources, a path becomes the one named file.

    One key rather than two, because the two SDK fields behind it only make
    sense together: a run that names a file and forgets to empty the sources
    would load the file *and* everything it meant to replace.
    """
    if configured is None:
        # Absent means the default, and the default is the project's own
        # versioned settings -- the only source that travels into a worktree.
        return ("project",), None
    if not isinstance(configured, list) or not all(isinstance(entry, str) for entry in configured):
        raise ConfigError(f"{path}: [agent].settings must be a list of strings")

    sources: list[str] = []
    files: list[str] = []
    for entry in configured:
        if entry in _SETTING_SOURCES:
            sources.append(entry)
        elif entry == _MANAGED:
            raise ConfigError(
                f"{path}: [agent].settings names {entry!r}, but managed settings always "
                "apply and cannot be selected"
            )
        elif (root / entry).is_file():
            files.append(entry)
        else:
            raise ConfigError(
                f'{path}: [agent].settings: {entry!r} is neither "user"/"project"/"local" '
                f"nor an existing file under {root}"
            )
    if len(files) > 1:
        raise ConfigError(
            f"{path}: [agent].settings names {len(files)} files ({', '.join(files)}); "
            "the SDK loads one"
        )
    return tuple(sorted(set(sources))), (root / files[0] if files else None)
```

Im Rumpf von `load_config`, direkt hinter `cli_path = _cli_path(agent.get("cli_path"), path)`:

```python
    setting_sources, settings_file = _settings_from(agent.get("settings"), root, path)
```

und in den `Config(...)`-Aufruf, hinter `cli_path=cli_path,`:

```python
        setting_sources=setting_sources,
        settings_file=settings_file,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS, alle

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/config.py tests/test_config.py
cat > /tmp/ul-commit.txt <<'EOF'
Let a project say which settings a run loads

One key carries both SDK fields, because a run that named a file and left
the sources alone would load the file and everything it meant to replace.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
git commit -F /tmp/ul-commit.txt
```

---

### Task 2: Der Adapter reicht beides an das SDK

**Files:**
- Modify: `src/ultraloom/model/agent_sdk.py` (`AgentSdkModel.__init__`, `_options_for`)
- Test: `tests/test_agent_sdk.py`

**Interfaces:**
- Consumes: nichts aus Task 1 zur Laufzeit — der Adapter nimmt die Werte als Argumente, nicht das `Config`-Objekt.
- Produces:
  - `AgentSdkModel(cwd: Path, cli_path: Path | None = None, setting_sources: Sequence[str] = ("project",), settings_file: Path | None = None)`
  - `_options_for` liefert zusätzlich `"setting_sources": list[str]` immer und `"settings": str` nur bei gesetztem `settings_file`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_agent_sdk.py` das Stub-Dataclass `_Options` um zwei Felder erweitern, hinter `output_format`:

```python
    setting_sources: list[str] | None = None
    settings: str | None = None
```

Und drei Tests anhängen:

```python
def test_a_run_loads_the_projects_own_settings_by_default(
    stub_sdk: StubSdk, tmp_path: Path
) -> None:
    AgentSdkModel(cwd=tmp_path).ask(a_request())

    assert stub_sdk.options.setting_sources == ["project"]
    assert stub_sdk.options.settings is None


def test_configured_sources_reach_the_sdk(stub_sdk: StubSdk, tmp_path: Path) -> None:
    AgentSdkModel(cwd=tmp_path, setting_sources=("local", "project")).ask(a_request())

    assert stub_sdk.options.setting_sources == ["local", "project"]


def test_a_named_settings_file_reaches_the_sdk_as_a_string(
    stub_sdk: StubSdk, tmp_path: Path
) -> None:
    named = tmp_path / "repair.json"

    AgentSdkModel(cwd=tmp_path, setting_sources=(), settings_file=named).ask(a_request())

    assert stub_sdk.options.setting_sources == []
    assert stub_sdk.options.settings == str(named)
```

Im Wächtertest `test_every_name_the_adapter_uses_exists_on_the_installed_sdk` hinter dem `with_cli`-Block:

```python
    # Same reason as cli_path: `settings` appears only when a project named a
    # file, so the shape above never carries it.
    with_file = AgentSdkModel(
        cwd=tmp_path, setting_sources=(), settings_file=tmp_path / "repair.json"
    )._options_for(a_request())
    assert set(with_file) <= option_fields, (
        f"the SDK no longer takes {sorted(set(with_file) - option_fields)}"
    )

    # Names are not enough here either: a source the SDK does not know would be
    # passed straight through to the CLI and change which files load.
    known = set(typing.get_args(sdk.types.SettingSource))
    assert set(options["setting_sources"]) <= known, (
        f"the SDK no longer knows {sorted(set(options['setting_sources']) - known)}"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent_sdk.py -k "settings or sources" -v`
Expected: FAIL mit `TypeError: AgentSdkModel.__init__() got an unexpected keyword argument 'setting_sources'`

- [ ] **Step 3: Write the minimal implementation**

In `src/ultraloom/model/agent_sdk.py`, `__init__` ersetzen:

```python
    def __init__(
        self,
        cwd: Path,
        cli_path: Path | None = None,
        setting_sources: Sequence[str] = ("project",),
        settings_file: Path | None = None,
    ) -> None:
        self._cwd = cwd
        self._cli_path = cli_path
        self._setting_sources = tuple(setting_sources)
        self._settings_file = settings_file
```

Dafür oben ergänzen: `from collections.abc import AsyncIterator, Sequence`.

In `_options_for`, in das Dict hinter `"cwd": str(self._cwd),`:

```python
            # Always passed, never left to the SDK: `None` there means "load
            # every source, like the CLI", which is a machine's answer and not
            # a project's. An empty list is isolation and says so.
            "setting_sources": list(self._setting_sources),
```

Und hinter dem `cli_path`-Block:

```python
        if self._settings_file is not None:
            # The flag layer, which outranks all three discovered files. Only
            # when a project named one -- the same reason cli_path is optional.
            options["settings"] = str(self._settings_file)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_agent_sdk.py -v`
Expected: PASS, alle — einschließlich `test_every_name_the_adapter_uses_exists_on_the_installed_sdk`

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/model/agent_sdk.py tests/test_agent_sdk.py
cat > /tmp/ul-commit.txt <<'EOF'
Stop letting the machine answer which settings load

Passing no setting_sources was never neutral: the SDK reads None as load
everything the CLI would. The adapter now always says, and the guard test
holds both new names against the installed SDK.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
git commit -F /tmp/ul-commit.txt
```

---

### Task 3: Verdrahtung und Konfigurationsreferenz

**Files:**
- Modify: `src/ultraloom/cli.py:491-500` (`_model`)
- Modify: `README.md` (Abschnitt *Configuration*, hinter dem Absatz zu `[agent].cli_path`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Config.setting_sources` und `Config.settings_file` aus Task 1; die Signatur von `AgentSdkModel` aus Task 2.
- Produces: nichts, worauf ein späterer Task aufbaut.

- [ ] **Step 1: Write the failing test**

Ans Ende von `tests/test_cli.py` anhängen:

```python
def test_the_model_is_built_from_what_the_project_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring, not the adapter: _model must not drop what config read."""
    from ultraloom import cli
    from ultraloom.config import Config

    seen: dict[str, object] = {}

    class _Spy:
        def __init__(self, **kwargs: object) -> None:
            seen.update(kwargs)

    monkeypatch.setattr("ultraloom.model.agent_sdk.AgentSdkModel", _Spy)
    named = tmp_path / "repair.json"
    config = Config(root=tmp_path, setting_sources=("local",), settings_file=named)

    cli._model(tmp_path, config)

    assert seen["setting_sources"] == ("local",)
    assert seen["settings_file"] == named
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_the_model_is_built_from_what_the_project_configured -v`
Expected: FAIL mit `KeyError: 'setting_sources'`

- [ ] **Step 3: Write the minimal implementation**

In `src/ultraloom/cli.py`, die letzte Zeile von `_model` ersetzen:

```python
    return AgentSdkModel(
        cwd=root,
        cli_path=config.cli_path,
        setting_sources=config.setting_sources,
        settings_file=config.settings_file,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS, alle

- [ ] **Step 5: Write the configuration reference**

In `README.md`, im Beispielblock unter *Configuration* hinter `mcp_servers = ["wiki"]`:

```toml
# Which settings a repair run loads. The three reserved words are Claude Code's
# own; anything else is a path to one file, relative to --root.
settings = ["project"]
```

Und als Prosa hinter dem `[agent].cli_path`-Absatz:

````markdown
`[agent].settings` says which settings a run inherits. The default is
`["project"]` — the target project's own `.claude/settings.json`, and nothing
else. That is the one source that travels into a git worktree, because it is
the one that is versioned; `.claude/settings.local.json` is untracked and stays
behind, and `~/.claude/settings.json` belongs to the machine rather than to the
project. Measured against a repair run, the difference is not only tidiness:
dropping the user's settings cut the first round's prompt from 14 381 to 4 901
tokens, because the plugins and skills configured there stop loading.

`"user"`, `"project"` and `"local"` are reserved words. Anything else is a path
relative to `--root`, loaded on top of them:

```toml
[agent]
settings = []                                # no inherited settings at all
settings = ["hooks/repair.json"]             # one named file, and only it
settings = ["project", "../.claude/settings.json"]
```

At most one path: `--settings` takes one, and merging several would mean
rebuilding Claude Code's own merge semantics here. The order inside the list
means nothing — the precedence is Claude Code's and runs managed settings,
`--settings`, `.claude/settings.local.json`, `.claude/settings.json`,
`~/.claude/settings.json`, highest first. A named path therefore outranks both
project files on any scalar key; hooks add up, scalars do not.

A path that is not a file is refused when the configuration is read, which is
also what catches a misspelled word: `"porject"` is a path, and the message
names the three that are not. `"managed"` is refused by name, because managed
settings always apply and nothing here overrides them.

`[agent].settings` covers settings files and nothing else. The MCP servers a
machine configures in `~/.claude.json` arrive by a different route and are
unaffected — they cost no tokens either, because `[agent].mcp_servers` and the
tool profile in `tools.py` keep them out of the prompt.
````

- [ ] **Step 6: Run the whole gate**

Run: `uv run pytest && uv run ruff check . && uv run mypy src tests`
Expected: alles grün, Coverage bei 100 %

- [ ] **Step 7: Commit**

```bash
git add src/ultraloom/cli.py tests/test_cli.py README.md
cat > /tmp/ul-commit.txt <<'EOF'
Carry the configured settings to the model

The wiring is the half a unit test of the adapter cannot see: config read
the keys, the adapter takes them, and nothing in between dropped them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
git commit -F /tmp/ul-commit.txt
```

---

## Was dieser Plan nicht tut

- Kein MCP-Schalter. Gemessen spart er nichts, weil der `tools`-Deckel die MCP-Werkzeuge ohnehin aus dem Prompt hält.
- Keine Startdiagnose für ein Projekt, das `.claude/settings.json` nicht versioniert. Der Pfad-Ausweg deckt den Fall, und eine Heuristik, die „untracked" von „absichtlich abwesend" unterscheiden will, wäre geraten.
- Keine Antwort darauf, ob die CLI `.claude/` von `--root` aus nach oben sucht. Steht als benannte Unbekannte in der Spec; der benannte Pfad ist die Antwort für das Monorepo, falls nicht.
