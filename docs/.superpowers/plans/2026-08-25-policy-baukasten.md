# Policy-Baukasten — Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ultraloom bekommt eine konfigurierbare Policy, die Werkzeugaufrufe gegen Regeln über Pfade, Kommandos und Dateiinhalte prüft und sie mit einer Begründung ablehnt.

**Architecture:** Drei Schichten unterhalb des Harness: `rules` entscheidet (nur Standardbibliothek), `config` liest `[policy.*]` aus `.ultraloom/config.toml` und ergänzt eingebaute Sicherheitsregeln, `hook` übersetzt Claude Codes Payload in Subjects und Exit-Codes. Das CLI bekommt ein Unterkommando `policy`; damit es billig bleibt, wandert der Import der Prüfkette in `cli.py` in die Funktionen.

**Tech Stack:** Python 3.14, `uv`, nur Standardbibliothek im Produktionscode (`tomllib`, `re`, `fnmatch`, `pathlib`, `json`, `dataclasses`), pytest, ruff, mypy (strict), coverage.

**Spec:** `docs/.superpowers/specs/2026-08-25-policy-baukasten-design.md`

## Global Constraints

- **Gearbeitet wird in `C:/Users/micro/Documents/#GIT/ultraloom`**, nicht in einer Kopie unter `.claude/worktrees/`: die ist von `.git/info/exclude` ignoriert, teilt Index und HEAD mit dem Hauptcheckout, und `git add` meldet dort keine Änderung. Vor dem ersten Commit `git rev-parse --git-dir --git-common-dir` lesen; sind beide gleich, ist es kein Worktree.
- **Zweig:** `feat/guard-baukasten`, angelegt von `5d1c43e`. Vor jedem Commit Zweig und HEAD lesen — eine fremde Sitzung im selben Checkout leert den Index, und git schreibt dann einen leeren Commit und meldet Erfolg.
- **TDD ohne Ausnahme:** jeder Test wird zuerst geschrieben, laufen gelassen und *als rot gesehen*, bevor die Implementierung entsteht.
- **100 % Coverage**, `fail_under = 100`. Jeder Ausschluss trägt seine Begründung im `# pragma`-Kommentar.
- **mypy strict**, `files = ["src", "tests"]`. Kein `Any`, kein `type: ignore` ohne Begründung dahinter.
- **ruff** mit `select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF"]`, `line-length = 100`.
- **Sprache:** Dieses Projekt schreibt Docstrings, Kommentare und Benutzermeldungen **englisch**. Beim Bearbeiten einer Datei gilt, was sie schon spricht. Die Planprosa hier ist deutsch, der Code darin ist es nicht.
- **Kommentiert wird das Warum**, nie die Zeile darunter.
- **Commit-Nachrichten englisch**, mehrzeilig über eine Datei und `git commit -F <datei>`, nie über ein Heredoc.
- **Ein Shell-Befehl je Aufruf**, keine langen `&&`-Ketten.
- **Modulgrenze:** `ultraloom.policy.*` darf `ultraloom.config` importieren, nichts aus `ultraloom.checks` und nichts aus `graph`, `state`, `runner`, `journal`, `gate`, `model`, `discovery`.
- **Name:** `policy`, nicht `guard`. `guard` ist in `flows/verify_until_green.py` für den Knoten vergeben, der misst, was ein Reparateur angefasst hat.

---

### Task 1: Die Engine (`policy.rules`)

Entscheidet, ob ein Subject erlaubt ist. Kennt weder Dateien noch JSON.

**Files:**
- Create: `src/ultraloom/policy/__init__.py`
- Create: `src/ultraloom/policy/rules.py`
- Create: `tests/policy/__init__.py`
- Create: `tests/policy/test_rules.py`

**Interfaces:**
- Consumes: nichts.
- Produces:
  - `type Kind = Literal["paths", "commands", "content"]`
  - `type Mode = Literal["deny", "allow"]`
  - `KINDS: tuple[Kind, ...]`
  - `Rule(patterns: tuple[str, ...], reason: str, is_regex: bool, tools: frozenset[str] | None)`
  - `RuleGroup(mode: Mode, rules: tuple[Rule, ...])`
  - `Ruleset(groups: Mapping[Kind, RuleGroup])`
  - `Subject(kind: Kind, value: str, tool: str)`
  - `Verdict(allowed: bool, reasons: tuple[str, ...])`
  - `evaluate(ruleset: Ruleset, subject: Subject) -> Verdict`

- [ ] **Step 1: Write the failing tests**

`tests/policy/test_rules.py`:

```python
"""The decision matrix, case by case."""

from __future__ import annotations

import pytest

from ultraloom.policy.rules import Kind, Mode, Rule, RuleGroup, Ruleset, Subject, evaluate


def _set(kind: Kind, mode: Mode, *rules: Rule) -> Ruleset:
    """Typed rather than str: mypy strict reads the tests too."""
    return Ruleset(groups={kind: RuleGroup(mode=mode, rules=rules)})


def _rule(
    *patterns: str,
    reason: str = "because",
    regex: bool = False,
    tools: frozenset[str] | None = None,
) -> Rule:
    return Rule(patterns=patterns, reason=reason, is_regex=regex, tools=tools)


def test_a_kind_without_rules_allows() -> None:
    """A kind nobody configured stops nothing."""
    verdict = evaluate(Ruleset(groups={}), Subject("paths", "src/a.py", "Write"))
    assert verdict.allowed
    assert verdict.reasons == ()


def test_deny_lets_an_unmatched_path_through() -> None:
    rules = _set("paths", "deny", _rule(".env"))
    assert evaluate(rules, Subject("paths", "src/a.py", "Write")).allowed


def test_deny_stops_a_matching_path_and_says_why() -> None:
    rules = _set("paths", "deny", _rule(".env", reason="no secrets"))
    verdict = evaluate(rules, Subject("paths", ".env", "Write"))
    assert not verdict.allowed
    assert verdict.reasons == ("no secrets",)


def test_deny_collects_every_matching_rule() -> None:
    """All reasons at once: otherwise the agent clears them one round at a time."""
    rules = _set(
        "paths",
        "deny",
        _rule(".env", reason="first"),
        _rule("*.env", reason="second"),
    )
    verdict = evaluate(rules, Subject("paths", ".env", "Write"))
    assert verdict.reasons == ("first", "second")


def test_a_list_of_patterns_shares_one_reason() -> None:
    rules = _set("paths", "deny", _rule(".env", "*.pem", reason="secrets"))
    assert not evaluate(rules, Subject("paths", "server.pem", "Write")).allowed


def test_globs_span_directories_only_with_double_star() -> None:
    """`config/*` must not reach `config/a/b`, or a pattern locks more than it says."""
    rules = _set("paths", "deny", _rule("config/*"))
    assert evaluate(rules, Subject("paths", "config/a/b", "Write")).allowed
    assert not evaluate(rules, Subject("paths", "config/a", "Write")).allowed


def test_a_double_star_reaches_down() -> None:
    rules = _set("paths", "deny", _rule(".aws/**"))
    assert not evaluate(rules, Subject("paths", ".aws/creds/x", "Write")).allowed


def test_commands_match_as_plain_globs_not_as_paths() -> None:
    """A command line is no path: the slash in `rm -rf a/b` separates nothing."""
    rules = _set("commands", "deny", _rule("rm -rf *"))
    assert not evaluate(rules, Subject("commands", "rm -rf a/b", "Bash")).allowed


def test_a_regex_rule_searches_anywhere_in_the_value() -> None:
    rules = _set("commands", "deny", _rule(r"^git\s+push\b", regex=True))
    assert not evaluate(rules, Subject("commands", "git  push --force", "Bash")).allowed
    assert evaluate(rules, Subject("commands", "git pushed", "Bash")).allowed


def test_a_tools_filter_narrows_a_rule() -> None:
    rules = _set("paths", "deny", _rule("docs/**", tools=frozenset({"Write"})))
    assert not evaluate(rules, Subject("paths", "docs/a.md", "Write")).allowed
    assert evaluate(rules, Subject("paths", "docs/a.md", "Edit")).allowed


def test_allow_refuses_everything_it_does_not_name() -> None:
    rules = _set("paths", "allow", _rule("src/**", reason="src only"))
    assert evaluate(rules, Subject("paths", "src/a.py", "Write")).allowed
    denied = evaluate(rules, Subject("paths", "other.py", "Write"))
    assert not denied.allowed
    assert denied.reasons == ('no rule in [policy.paths] allows this; mode is "allow"',)


def test_allow_stops_at_the_first_permission() -> None:
    """A second reason why something is allowed does not change the answer."""
    rules = _set("paths", "allow", _rule("src/**"), _rule("**"))
    assert evaluate(rules, Subject("paths", "src/a.py", "Write")).allowed


def test_allow_with_no_rules_refuses() -> None:
    """An empty allowlist allows nothing -- anything else would be a silent failure."""
    rules = _set("paths", "allow")
    assert not evaluate(rules, Subject("paths", "src/a.py", "Write")).allowed


def test_an_invalid_regex_is_refused_when_the_rule_is_built() -> None:
    with pytest.raises(ValueError, match="invalid regex"):
        Rule(patterns=("[",), reason="x", is_regex=True, tools=None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/policy/test_rules.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.policy'`

- [ ] **Step 3: Write the implementation**

`src/ultraloom/policy/__init__.py`:

```python
"""Rules about what a tool call may touch.

Below the check chain and below the harness: the policy runs before every tool
call, so what it imports is its price and not a detail. test_module_boundary
holds that promise.

Named `policy` and not `guard`: `flows/verify_until_green.py` already has a
`guard` node, and it answers a different question -- what a repairer touched,
not what anyone may touch.
"""
```

`src/ultraloom/policy/rules.py`:

```python
"""The decision itself: one subject against one ruleset.

No files, no processes, no JSON. Whoever wants to understand the matrix of
mode, defaults and tool filter reads this file and nothing else.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

type Kind = Literal["paths", "commands", "content"]

type Mode = Literal["deny", "allow"]

KINDS: tuple[Kind, ...] = ("paths", "commands", "content")


@dataclass(frozen=True, slots=True)
class Rule:
    """One pattern or several, sharing a single reason."""

    patterns: tuple[str, ...]
    reason: str
    is_regex: bool
    # None means "every tool of this kind" and is not the same as an empty set,
    # which would match no tool at all.
    tools: frozenset[str] | None

    def __post_init__(self) -> None:
        """A broken expression fails when built, not on its first hit.

        Otherwise the message would depend on which file happens to be written
        first -- and a policy that raises while checking does not block, it
        lets through.
        """
        if self.is_regex:
            for pattern in self.patterns:
                try:
                    re.compile(pattern)
                except re.error as error:
                    raise ValueError(f"invalid regex {pattern!r}: {error}") from error


@dataclass(frozen=True, slots=True)
class RuleGroup:
    """Every rule of one kind, together with its mode."""

    mode: Mode
    rules: tuple[Rule, ...]


@dataclass(frozen=True, slots=True)
class Ruleset:
    """What a project says in total. A missing kind stops nothing."""

    groups: Mapping[Kind, RuleGroup]


@dataclass(frozen=True, slots=True)
class Subject:
    """What is checked: a path, a command line or a piece of content."""

    kind: Kind
    value: str
    tool: str


@dataclass(frozen=True, slots=True)
class Verdict:
    """The answer. `reasons` is empty when allowed."""

    allowed: bool
    reasons: tuple[str, ...]


def evaluate(ruleset: Ruleset, subject: Subject) -> Verdict:
    """Whether this subject may pass, and if not, why not."""
    group = ruleset.groups.get(subject.kind)
    if group is None:
        return Verdict(allowed=True, reasons=())

    matching = tuple(rule for rule in group.rules if _matches(rule, subject))

    if group.mode == "allow":
        # The first hit is enough: a second reason why something is allowed
        # does not change the answer.
        if matching:
            return Verdict(allowed=True, reasons=())
        return Verdict(
            allowed=False,
            reasons=(f'no rule in [policy.{subject.kind}] allows this; mode is "allow"',),
        )

    # Deny: every hit, not just the first. Otherwise the agent clears one reason
    # after another and needs a round per rule.
    if matching:
        return Verdict(allowed=False, reasons=tuple(rule.reason for rule in matching))
    return Verdict(allowed=True, reasons=())


def _matches(rule: Rule, subject: Subject) -> bool:
    """Whether this rule concerns this subject -- tool first, then patterns."""
    if rule.tools is not None and subject.tool not in rule.tools:
        return False
    return any(_hits(pattern, rule.is_regex, subject) for pattern in rule.patterns)


def _hits(pattern: str, is_regex: bool, subject: Subject) -> bool:
    """A single pattern against the value.

    Paths are matched as paths and everything else as flat text: only
    PurePosixPath.full_match knows `**` across directory boundaries, and it
    keeps `config/*` from reaching `config/a/b`. For a command line the same
    rule would be wrong -- the slash in `rm -rf a/b` separates no levels.
    """
    if is_regex:
        return re.search(pattern, subject.value) is not None
    if subject.kind == "paths":
        return PurePosixPath(subject.value).full_match(pattern)
    return fnmatch.fnmatch(subject.value, pattern)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/policy/test_rules.py -v`
Expected: PASS, 14 Tests.

- [ ] **Step 5: Run the chain**

Run: `uv run ultraloom check all`
Expected: lint, types, test, coverage grün. Ist die Coverage rot, fehlt ein Test — nicht ein `pragma`.

- [ ] **Step 6: Commit**

Nachricht in `commit-msg.txt` schreiben, dann:

```bash
git add src/ultraloom/policy tests/policy
```

```bash
git commit -F commit-msg.txt
```

Inhalt der Nachricht:

```
feat(policy): decide a subject against a ruleset

Three kinds of rule -- paths, commands, content -- with a mode per kind.
Deny reports every matching rule at once so a repair takes one round
rather than one per rule; allow stops at the first permission.
```

Danach `commit-msg.txt` löschen.

---

### Task 2: Konfiguration und Voreinstellungen (`policy.config`)

**Files:**
- Create: `src/ultraloom/policy/config.py`
- Create: `tests/policy/test_config.py`

**Interfaces:**
- Consumes: `Kind`, `KINDS`, `Mode`, `Rule`, `RuleGroup`, `Ruleset` aus Task 1.
- Produces:
  - `load_ruleset(root: Path) -> Ruleset`
  - `DEFAULTS: Mapping[Kind, tuple[Rule, ...]]`
  - wirft `ultraloom.config.ConfigError` bei jedem Schemafehler.

- [ ] **Step 1: Write the failing tests**

`tests/policy/test_config.py`:

```python
"""The [policy.*] schema, and what happens when it is wrong."""

from __future__ import annotations

from pathlib import Path

import pytest

from ultraloom.config import ConfigError
from ultraloom.policy.config import DEFAULTS, load_ruleset
from ultraloom.policy.rules import Subject, evaluate


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / ".ultraloom").mkdir()
    (tmp_path / ".ultraloom" / "config.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_a_project_without_a_config_still_guards_secrets(tmp_path: Path) -> None:
    """A repo where nobody set anything up is protected anyway."""
    ruleset = load_ruleset(tmp_path)
    assert not evaluate(ruleset, Subject("paths", ".env", "Write")).allowed


def test_the_defaults_cover_the_documented_paths() -> None:
    """What the README promises is what the module holds -- or the two drift."""
    patterns = {pattern for rule in DEFAULTS["paths"] for pattern in rule.patterns}
    assert {
        ".env", ".env.*", "*.pem", "*.key", "id_rsa*", "*.p12",
        ".npmrc", ".pypirc", "credentials.json", ".aws/**",
    } <= patterns


def test_no_command_is_denied_by_default() -> None:
    """`git push` is policy, not security, and belongs in the project file."""
    assert DEFAULTS["commands"] == ()


def test_project_rules_are_added_to_the_defaults(tmp_path: Path) -> None:
    root = _write(tmp_path, """
[[policy.paths.rules]]
match = "uv.lock"
reason = "the lock belongs to uv"
""")
    ruleset = load_ruleset(root)
    assert not evaluate(ruleset, Subject("paths", "uv.lock", "Write")).allowed
    assert not evaluate(ruleset, Subject("paths", ".env", "Write")).allowed


def test_defaults_false_throws_the_built_in_rules_away(tmp_path: Path) -> None:
    root = _write(tmp_path, """
[policy.paths]
defaults = false
""")
    assert evaluate(load_ruleset(root), Subject("paths", ".env", "Write")).allowed


def test_the_defaults_come_first(tmp_path: Path) -> None:
    """The order of the messages is the order in which one reads the file."""
    root = _write(tmp_path, """
[[policy.paths.rules]]
match = ".env"
reason = "the project as well"
""")
    verdict = evaluate(load_ruleset(root), Subject("paths", ".env", "Write"))
    assert verdict.reasons[-1] == "the project as well"
    assert len(verdict.reasons) == 2


def test_allow_mode_beats_the_defaults(tmp_path: Path) -> None:
    """Whoever inverts the mode takes on the responsibility entirely."""
    root = _write(tmp_path, """
[policy.paths]
mode = "allow"

[[policy.paths.rules]]
match = "**"
reason = "everything goes"
""")
    assert evaluate(load_ruleset(root), Subject("paths", ".env", "Write")).allowed


def test_a_tools_filter_is_read(tmp_path: Path) -> None:
    root = _write(tmp_path, """
[[policy.paths.rules]]
match = "docs/**"
tools = ["Write"]
reason = "Write only"
""")
    ruleset = load_ruleset(root)
    assert not evaluate(ruleset, Subject("paths", "docs/a.md", "Write")).allowed
    assert evaluate(ruleset, Subject("paths", "docs/a.md", "Edit")).allowed


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('[policy.nowhere]\nmode = "deny"', "unknown policy kind"),
        ('[policy.paths]\nmode = "maybe"', 'must be "deny" or "allow"'),
        ("[policy.paths]\ndefaults = 1", "must be true or false"),
        ('[[policy.paths.rules]]\nreason = "x"', "needs `match` or `regex`"),
        (
            '[[policy.paths.rules]]\nmatch = "a"\nregex = "b"\nreason = "x"',
            "carries both `match` and `regex`",
        ),
        ('[[policy.paths.rules]]\nmatch = []\nreason = "x"', "names no pattern"),
        ('[[policy.paths.rules]]\nmatch = "a"', "needs a `reason`"),
        ('[[policy.paths.rules]]\nmatch = 1\nreason = "x"', "must be a string or a list"),
        (
            '[[policy.paths.rules]]\nmatch = "a"\nreason = "x"\ntools = "Write"',
            "must be a list of strings",
        ),
        ('[[policy.commands.rules]]\nregex = "["\nreason = "x"', "invalid regex"),
        ('[policy.paths]\nrules = "no list"', "must be a list of tables"),
        ('policy = "no table"', r"\[policy\] must be a table"),
    ],
)
def test_a_broken_schema_is_refused_by_name(tmp_path: Path, body: str, message: str) -> None:
    """Every message names the spot the way the file spells it."""
    root = _write(tmp_path, body)
    with pytest.raises(ConfigError, match=message):
        load_ruleset(root)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/policy/test_config.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.policy.config'`

- [ ] **Step 3: Write the implementation**

`src/ultraloom/policy/config.py`:

```python
"""What [policy.*] in .ultraloom/config.toml means.

The built-in rules live as a constant in this module and not in a shipped TOML
file: a file can go missing, a constant cannot.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ultraloom.config import CONFIG_NAME, ConfigError
from ultraloom.policy.rules import KINDS, Kind, Mode, Rule, RuleGroup, Ruleset

# Security only. `git push` or `pip` instead of `uv` are house rules and belong
# in the project file where they can be seen -- a built-in rule nobody reads
# gets killed with defaults=false at the first friction, taking the real ones
# with it.
DEFAULTS: Mapping[Kind, tuple[Rule, ...]] = {
    "paths": (
        Rule(
            patterns=(
                ".env",
                ".env.*",
                "*.pem",
                "*.key",
                "id_rsa*",
                "*.p12",
                ".npmrc",
                ".pypirc",
                "credentials.json",
                ".aws/**",
            ),
            reason="secrets are not written by an agent",
            is_regex=False,
            tools=None,
        ),
    ),
    "content": (
        Rule(
            patterns=(
                r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
                r"\bAKIA[0-9A-Z]{16}\b",
                r"\bsk-[A-Za-z0-9]{20,}\b",
            ),
            reason="this looks like a credential in plain text",
            is_regex=True,
            tools=None,
        ),
    ),
    "commands": (),
}


def load_ruleset(root: Path) -> Ruleset:
    """This project's rules, together with the built-in ones.

    With no file at all only the defaults apply: a repo without configuration
    is protected without anyone having set anything up.
    """
    path = root / CONFIG_NAME
    raw: Mapping[str, Any] = {}
    # is_file() and not exists(): a *directory* of that name would raise past
    # every ConfigError handler on the way out.
    if path.is_file():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ConfigError(f"{path}: {error}") from error

    policy = raw.get("policy", {})
    if not isinstance(policy, dict):
        raise ConfigError(f"{path}: [policy] must be a table")

    for name in policy:
        # Caught here rather than ignored: a typo in the heading would
        # otherwise read as "this project configured nothing".
        if name not in KINDS:
            raise ConfigError(f"{path}: unknown policy kind [policy.{name}]")

    groups: dict[Kind, RuleGroup] = {}
    for kind in KINDS:
        table = policy.get(kind, {})
        if not isinstance(table, dict):
            raise ConfigError(f"{path}: [policy.{kind}] must be a table")
        groups[kind] = _group(kind, table, path)
    return Ruleset(groups=groups)


def _group(kind: Kind, table: Mapping[str, Any], path: Path) -> RuleGroup:
    """One [policy.<kind>] section: mode, defaults, own rules."""
    raw_mode = table.get("mode", "deny")
    if raw_mode not in ("deny", "allow"):
        raise ConfigError(f'{path}: [policy.{kind}].mode must be "deny" or "allow"')

    defaults = table.get("defaults", True)
    # TOML has real booleans; `defaults = 1` is nobody's intent and must not
    # switch the protection off.
    if not isinstance(defaults, bool):
        raise ConfigError(f"{path}: [policy.{kind}].defaults must be true or false")

    raw_rules = table.get("rules", [])
    if not isinstance(raw_rules, list) or not all(isinstance(item, dict) for item in raw_rules):
        raise ConfigError(f"{path}: [[policy.{kind}.rules]] must be a list of tables")

    # Defaults first: the order of the messages is the order in which one reads
    # the configuration. Under "allow" they contribute nothing -- there only
    # what is permitted counts -- so they are left out.
    built_in = DEFAULTS[kind] if defaults and raw_mode == "deny" else ()
    rules = built_in + tuple(
        _rule(kind, item, path, index) for index, item in enumerate(raw_rules)
    )
    return RuleGroup(mode=_mode(raw_mode), rules=rules)


def _mode(value: str) -> Mode:
    """Narrowing for mypy only: the value was checked one line earlier."""
    return "allow" if value == "allow" else "deny"


def _rule(kind: Kind, item: Mapping[str, Any], path: Path, index: int) -> Rule:
    """A single rule, with a message that names where it sits."""
    where = f"[[policy.{kind}.rules]] #{index + 1}"

    has_match = "match" in item
    has_regex = "regex" in item
    if has_match and has_regex:
        raise ConfigError(f"{path}: {where} carries both `match` and `regex`; use exactly one")
    if not has_match and not has_regex:
        raise ConfigError(f"{path}: {where} needs `match` or `regex`")

    patterns = _patterns(item["regex"] if has_regex else item["match"], path, where)

    reason = item.get("reason")
    if not isinstance(reason, str) or not reason:
        # A block without a reason produces exactly the kind of message an
        # agent argues with or works around.
        raise ConfigError(f"{path}: {where} needs a `reason`")

    raw_tools = item.get("tools")
    if raw_tools is not None and (
        not isinstance(raw_tools, list) or not all(isinstance(name, str) for name in raw_tools)
    ):
        raise ConfigError(f"{path}: {where}.tools must be a list of strings")
    tools = None if raw_tools is None else frozenset(raw_tools)

    try:
        return Rule(patterns=patterns, reason=reason, is_regex=has_regex, tools=tools)
    except ValueError as error:
        raise ConfigError(f"{path}: {where}: {error}") from error


def _patterns(raw: object, path: Path, where: str) -> tuple[str, ...]:
    """A string or a list of them, never anything else and never empty."""
    if isinstance(raw, str):
        values: Sequence[str] = (raw,)
    elif isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        values = raw
    else:
        raise ConfigError(f"{path}: {where} must be a string or a list of strings")
    if not values:
        # An empty list would look like a block and be none.
        raise ConfigError(f"{path}: {where} names no pattern")
    return tuple(values)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/policy -v`
Expected: PASS, Task 1 und 2 zusammen.

- [ ] **Step 5: Run the chain**

Run: `uv run ultraloom check all`
Expected: alles grün.

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/policy/config.py tests/policy/test_config.py
```

Nachricht:

```
feat(policy): read [policy.*] and the built-in security rules

Defaults live as a constant, not as a shipped TOML file: a file can go
missing. A broken schema raises ConfigError while reading rather than
surfacing as a rule that never fires.
```

---

### Task 3: `cli.py` verschlankt, und die Zahl dazu

Die Policy läuft bei jedem Werkzeugaufruf. `ultraloom.checks` kostet 25 ms Importzeit und wird auf dem Policy-Pfad nie gebraucht.

**Files:**
- Modify: `src/ultraloom/cli.py` (der Import von `ultraloom.checks` am Modulkopf, `_check`, `_report`)
- Create: `tests/test_cli_imports.py`
- Modify: `docs/.superpowers/specs/2026-08-25-policy-baukasten-design.md` (die Zahl aus Schritt 5)

**Interfaces:**
- Consumes: nichts aus Task 1 und 2.
- Produces: nichts Neues. `cli.main` bleibt in Signatur und Verhalten unverändert.

- [ ] **Step 1: Write the failing test**

`tests/test_cli_imports.py`:

```python
"""What `import ultraloom.cli` may cost, measured by what it loads.

A millisecond threshold would be shaky on a shared machine -- the same bare
interpreter measured between 80 and 117 ms on one day. What is deterministic is
the cause: which modules the import pulls in. This holds the lazy imports
against the next contributor who adds one at the top of the file again.
"""

from __future__ import annotations

import subprocess
import sys

_PROGRAM = """
import sys
import ultraloom.cli

expensive = [
    name
    for name in ("ultraloom.checks", "concurrent.futures", "ctypes")
    if name in sys.modules
]
print("LEAKED:", expensive)
"""


def test_importing_the_cli_does_not_pull_in_the_check_chain() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROGRAM],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "LEAKED: []" in result.stdout, result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_imports.py -v`
Expected: FAIL — `LEAKED: ['ultraloom.checks', 'concurrent.futures', 'ctypes']`

- [ ] **Step 3: Move the import into the functions**

In `src/ultraloom/cli.py` die Modulkopfzeile

```python
from ultraloom.checks import CheckResult, CheckUnavailableError, run_all, run_check
```

streichen und `CheckResult` in den bestehenden `TYPE_CHECKING`-Block aufnehmen, weil `_report` es nur als Annotation braucht:

```python
if TYPE_CHECKING:
    # Type-only, so the check side still imports nothing from the harness at
    # runtime — the boundary is about sys.modules, not about annotations.
    from ultraloom.checks import CheckResult
    from ultraloom.graph import Graph
    from ultraloom.model.port import Model
```

In `_check` als erste Zeile des Rumpfs:

```python
def _check(kind: str, config: Config, threshold: int | None) -> int:
    # Imported here and not at the top: the policy path and `--help` would
    # otherwise pay 25 ms for a chain they never touch. tests/test_cli_imports
    # holds this.
    from ultraloom.checks import CheckUnavailableError, run_all, run_check
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS, 660 Tests plus der neue. Schlägt etwas fehl, fehlt ein Name zur Laufzeit — der gehört in dieselbe lokale Importzeile, nicht zurück nach oben.

- [ ] **Step 5: Measure and record**

```bash
for i in 1 2 3 4 5; do .venv/Scripts/ultraloom.exe --help > /dev/null; done
```

Mit `date +%s%N` um die Schleife herum messen, davor dasselbe für `.venv/Scripts/python.exe -c "pass"` als Grundlinie — die absolute Zahl schwankt, die Differenz nicht. Beide Zahlen in den Abschnitt "Kosten" der Spec eintragen. Bleibt die Differenz zum nackten Interpreter über 60 ms, hier anhalten und berichten, statt Punkt 2 der Maßnahmenliste eigenmächtig anzufangen.

- [ ] **Step 6: Commit**

```bash
git add src/ultraloom/cli.py tests/test_cli_imports.py docs/.superpowers/specs/2026-08-25-policy-baukasten-design.md
```

Nachricht:

```
perf(cli): load the check chain only when a check runs

The policy runs before every tool call, so the CLI's import cost is its
price. A test on sys.modules holds this rather than a millisecond
threshold, which a shared machine cannot keep.
```

---

### Task 4: Der Adapter und das Unterkommando (`policy.hook`)

**Files:**
- Create: `src/ultraloom/policy/hook.py`
- Create: `src/ultraloom/policy/cli.py`
- Create: `tests/policy/test_hook.py`
- Modify: `src/ultraloom/cli.py` (`_parser`, `main`)
- Modify: `tests/test_module_boundary.py`

**Interfaces:**
- Consumes: `load_ruleset` (Task 2), `evaluate`, `Subject` (Task 1).
- Produces:
  - `subjects(tool: str, tool_input: Mapping[str, Any], root: Path) -> tuple[Subject, ...]`
  - `run(stdin: TextIO, root: Path, stderr: TextIO) -> int`
  - `EXIT_OK = 0`, `EXIT_INTERNAL = 1`, `EXIT_DENIED = 2`
  - `cli.dispatch(args: argparse.Namespace, root: Path) -> int`

- [ ] **Step 1: Write the failing tests**

`tests/policy/test_hook.py`:

```python
"""The adapter: payload in, exit code out. Rules are test_rules' business."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from ultraloom.policy.hook import run, subjects


def _payload(tool: str, tool_input: dict[str, Any]) -> io.StringIO:
    return io.StringIO(json.dumps({"tool_name": tool, "tool_input": tool_input}))


def _config(tmp_path: Path, body: str) -> Path:
    (tmp_path / ".ultraloom").mkdir()
    (tmp_path / ".ultraloom" / "config.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_an_unrelated_tool_yields_nothing(tmp_path: Path) -> None:
    """Short circuit before everything else: no kind touched, no config read."""
    assert subjects("WebFetch", {"url": "https://x"}, tmp_path) == ()


def test_write_yields_a_path_and_a_content_subject(tmp_path: Path) -> None:
    found = subjects("Write", {"file_path": str(tmp_path / "a.py"), "content": "x"}, tmp_path)
    assert [(s.kind, s.value) for s in found] == [("paths", "a.py"), ("content", "x")]


def test_edit_reads_the_new_string(tmp_path: Path) -> None:
    found = subjects("Edit", {"file_path": str(tmp_path / "a.py"), "new_string": "new"}, tmp_path)
    assert [(s.kind, s.value) for s in found] == [("paths", "a.py"), ("content", "new")]


def test_bash_yields_a_command_subject(tmp_path: Path) -> None:
    found = subjects("Bash", {"command": "git push"}, tmp_path)
    assert [(s.kind, s.value) for s in found] == [("commands", "git push")]


def test_an_absolute_path_is_made_relative_to_the_project(tmp_path: Path) -> None:
    """Claude Code sends absolute paths; a rule `.env` would never match one."""
    found = subjects("Write", {"file_path": str(tmp_path / "sub" / ".env")}, tmp_path)
    assert found[0].value == "sub/.env"


def test_a_path_outside_the_project_stays_absolute(tmp_path: Path) -> None:
    outside = tmp_path.parent / "elsewhere.txt"
    found = subjects("Write", {"file_path": str(outside)}, tmp_path)
    assert found[0].value == outside.as_posix()


def test_a_tool_input_without_the_expected_keys_yields_nothing(tmp_path: Path) -> None:
    """A payload shape we do not recognise is not a reason to block."""
    assert subjects("Bash", {}, tmp_path) == ()
    assert subjects("Write", {}, tmp_path) == ()


def test_an_allowed_write_exits_zero(tmp_path: Path) -> None:
    errors = io.StringIO()
    payload = _payload("Write", {"file_path": str(tmp_path / "src" / "a.py"), "content": "x"})
    assert run(payload, tmp_path, errors) == 0
    assert errors.getvalue() == ""


def test_a_denied_write_exits_two_and_says_why(tmp_path: Path) -> None:
    root = _config(tmp_path, """
[[policy.paths.rules]]
match = "secrets/**"
reason = "not in here"
""")
    errors = io.StringIO()
    payload = _payload("Write", {"file_path": str(root / "secrets" / "a"), "content": "x"})
    assert run(payload, root, errors) == 2
    assert "not in here" in errors.getvalue()


def test_every_reason_is_reported_not_only_the_first(tmp_path: Path) -> None:
    root = _config(tmp_path, """
[[policy.paths.rules]]
match = ".env"
reason = "first reason"
""")
    errors = io.StringIO()
    payload = _payload("Write", {"file_path": str(root / ".env"), "content": "x"})
    assert run(payload, root, errors) == 2
    assert "secrets are not written by an agent" in errors.getvalue()
    assert "first reason" in errors.getvalue()


def test_a_broken_config_blocks_rather_than_letting_through(tmp_path: Path) -> None:
    """The one failure mode that does real damage: passing silently."""
    root = _config(tmp_path, '[[policy.paths.rules]]\nmatch = 1\nreason = "x"')
    errors = io.StringIO()
    payload = _payload("Write", {"file_path": str(root / "a")})
    assert run(payload, root, errors) == 2
    assert "must be a string or a list" in errors.getvalue()


@pytest.mark.parametrize("raw", ["", "no json", "[]", '{"tool_name": 5}', "{}"])
def test_an_unreadable_payload_is_an_internal_error(tmp_path: Path, raw: str) -> None:
    """Exit 1, never 2: a broken policy must not lock up a session."""
    errors = io.StringIO()
    assert run(io.StringIO(raw), tmp_path, errors) == 1
    assert "unreadable hook payload" in errors.getvalue()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/policy/test_hook.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.policy.hook'`

- [ ] **Step 3: Write the implementation**

`src/ultraloom/policy/hook.py`:

```python
"""Claude Code's hook protocol, translated into subjects and exit codes.

The only place in this repo that knows how Claude Code speaks. A second
harness would get a second module beside this one, not an `if` inside it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TextIO

from ultraloom.config import ConfigError
from ultraloom.policy.config import load_ruleset
from ultraloom.policy.rules import Subject, evaluate

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_DENIED = 2

# Which tool touches which kinds. A tool that is not listed here ends the run
# before any configuration is read.
_PATH_TOOLS = ("Write", "Edit", "MultiEdit")
_CONTENT_KEYS = {"Write": "content", "Edit": "new_string", "MultiEdit": "new_string"}


def subjects(tool: str, tool_input: Mapping[str, Any], root: Path) -> tuple[Subject, ...]:
    """What is to be checked about this tool call. Empty means nothing."""
    if tool == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return ()
        return (Subject("commands", command, tool),)

    if tool not in _PATH_TOOLS:
        return ()

    found: list[Subject] = []
    raw_path = tool_input.get("file_path")
    if isinstance(raw_path, str):
        found.append(Subject("paths", _relative(raw_path, root), tool))

    content = tool_input.get(_CONTENT_KEYS[tool])
    if isinstance(content, str):
        found.append(Subject("content", content, tool))
    return tuple(found)


def _relative(raw: str, root: Path) -> str:
    """The path the way a rule spells it: relative to the root, with `/`.

    Claude Code sends absolute paths, which a rule `.env` would never match,
    and a pattern should hit the same thing on Windows as on POSIX. What lies
    outside the root stays absolute -- a rule aiming there must say the whole
    path.
    """
    path = Path(raw)
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def run(stdin: TextIO, root: Path, stderr: TextIO) -> int:
    """Read one payload, check it, and answer with an exit code."""
    try:
        payload = json.loads(stdin.read())
        tool = payload["tool_name"]
        tool_input = payload.get("tool_input", {})
        if not isinstance(tool, str) or not isinstance(tool_input, dict):
            raise TypeError("tool_name must be a string and tool_input a table")
    except (json.JSONDecodeError, TypeError, KeyError, AttributeError) as error:
        # Exit 1 and not 2: a broken policy must not lock up a session.
        print(f"ultraloom policy: unreadable hook payload: {error}", file=stderr)
        return EXIT_INTERNAL

    to_check = subjects(tool, tool_input, root)
    if not to_check:
        return EXIT_OK

    try:
        ruleset = load_ruleset(root)
    except ConfigError as error:
        # Exit 2, not 1: a policy that passes silently on a broken config is
        # the one failure mode that does real damage.
        print(f"ultraloom policy: {error}", file=stderr)
        return EXIT_DENIED

    reasons = [
        reason for subject in to_check for reason in evaluate(ruleset, subject).reasons
    ]
    if not reasons:
        return EXIT_OK

    print(f"ultraloom policy refused this {tool}:", file=stderr)
    for reason in reasons:
        print(f"  - {reason}", file=stderr)
    return EXIT_DENIED
```

`src/ultraloom/policy/cli.py`:

```python
"""The two call shapes, kept apart from the payload handling."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ultraloom.config import ConfigError
from ultraloom.policy.config import load_ruleset
from ultraloom.policy.hook import EXIT_DENIED, EXIT_OK, run
from ultraloom.policy.rules import KINDS, Subject, evaluate


def dispatch(args: argparse.Namespace, root: Path) -> int:
    """`policy hook` reads stdin, `policy check` takes the value as an argument."""
    if args.policy_command == "check":
        return _manual(args.kind, args.value, args.tool, root)
    return run(sys.stdin, root, sys.stderr)


def _manual(kind: str, value: str, tool: str, root: Path) -> int:
    """By hand: the same decision, without a payload around it."""
    try:
        ruleset = load_ruleset(root)
    except ConfigError as error:
        print(f"ultraloom policy: {error}", file=sys.stderr)
        return EXIT_DENIED

    # argparse limited the choice to KINDS, so the index is safe; going through
    # the tuple is how mypy learns the same thing.
    subject = Subject(KINDS[KINDS.index(kind)], value, tool)  # type: ignore[arg-type]  # see above
    verdict = evaluate(ruleset, subject)
    if verdict.allowed:
        return EXIT_OK
    for reason in verdict.reasons:
        print(f"  - {reason}", file=sys.stderr)
    return EXIT_DENIED
```

- [ ] **Step 4: Wire up the subcommand**

In `_parser()` von `src/ultraloom/cli.py`, hinter dem `check`-Block:

```python
    policy = subparsers.add_parser(
        "policy", parents=[common], help="check a tool call against the project's policy"
    )
    policy_subs = policy.add_subparsers(dest="policy_command")
    policy_subs.add_parser("hook", parents=[common], help="read a Claude Code payload from stdin")
    manual = policy_subs.add_parser("check", parents=[common], help="check one value by hand")
    manual.add_argument("kind", choices=("paths", "commands", "content"))
    manual.add_argument("value")
    manual.add_argument("--tool", default="Write", help="the tool name a rule may filter on")
```

In `main()`, bei den übrigen Unterkommandos:

```python
    if args.command == "policy":
        # Imported here so `check` and `run` never load the policy, and the
        # policy never loads them.
        from ultraloom.policy import cli as policy_cli

        return policy_cli.dispatch(args, root)
```

- [ ] **Step 5: Extend the boundary test**

An `tests/test_module_boundary.py` anhängen. Dasselbe Kindprozess-Muster wie im bestehenden Test, nur fährt es `policy hook` statt `check all`:

```python
_POLICY_PROGRAM = _PREAMBLE + '''
import io
import sys

sys.stdin = io.StringIO("")
from ultraloom.cli import main

# Exit 1 is the expected outcome here: the payload is empty. What is tested is
# what the call loaded, not how it decided.
main(["policy", "hook"])
report()
print("CHECKS:", "ultraloom.checks" in sys.modules)
'''


def test_the_policy_pulls_in_neither_the_harness_nor_the_check_chain() -> None:
    """The policy runs before every tool call; what it loads is its price."""
    result = subprocess.run(
        [sys.executable, "-c", _POLICY_PROGRAM],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert "LEAKED: []" in result.stdout, result.stdout
    assert "CHECKS: False" in result.stdout, result.stdout
```

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Run the chain**

Run: `uv run ultraloom check all`
Expected: grün, Coverage 100 %.

- [ ] **Step 8: Commit**

```bash
git add src/ultraloom/policy src/ultraloom/cli.py tests/policy tests/test_module_boundary.py
```

Nachricht:

```
feat(policy): read Claude Code payloads and answer with exit codes

An unreadable payload is exit 1 and never blocks; a broken config is
exit 2 and does, because a policy that passes silently is worse than
one that refuses loudly.
```

---

### Task 5: README, README.de und Ablaufbild

**Files:**
- Modify: `README.md` (neuer Abschnitt vor `## The harness (optional)`)
- Modify: `README.de.md` (derselbe Abschnitt an derselben Stelle)
- Create: `docs/abläufe/policy.md`

**Interfaces:**
- Consumes: alles aus Task 1 bis 4.
- Produces: nichts, was Code liest.

- [ ] **Step 1: Write the README section**

Abschnitt "Policy" vor `## The harness (optional)`. Er enthält: wofür sie da ist, die zwei Aufrufformen, das vollständige Schema mit je einem Beispiel pro Regelart, **die vollständige Liste der Voreinstellungen**, die Vorrangregel im Allow-Modus, das Exit-Protokoll und den Grund, warum eine kaputte Konfiguration blockt. Die Liste der Voreinstellungen wird von `test_the_defaults_cover_the_documented_paths` gegen den Quelltext gehalten — beim Ändern der einen Seite fällt die andere auf.

- [ ] **Step 2: Mirror it into README.de.md**

Derselbe Abschnitt auf Deutsch, an derselben Stelle. Die Codebeispiele bleiben identisch.

- [ ] **Step 3: Write the flow document**

`docs/abläufe/policy.md` nach dem Muster von `docs/abläufe/verify-until-green.md`: ein Mermaid-Graph plus Erklärung. Der Graph zeigt Payload → Werkzeug bekannt? → Arten → Konfiguration lesbar? → Modus → Treffer → Verdikt → Exit-Code.

- [ ] **Step 4: Check whether the docs test covers this**

Run: `uv run pytest tests/test_flow_docs.py -v`
Expected: PASS. Prüft der Test nur Flows des Harness, bleibt die Policy außen vor — dann hier nichts erzwingen, sondern im Bericht erwähnen.

- [ ] **Step 5: Run the chain**

Run: `uv run ultraloom check all`
Expected: grün.

- [ ] **Step 6: Commit**

```bash
git add README.md README.de.md "docs/abläufe/policy.md"
```

Nachricht:

```
docs(policy): describe the rules, the defaults and the exit codes

The list of built-in patterns belongs where it can be read without
opening the source; a test holds it against the module.
```

---

### Task 6: Das eigene Repo unter die Policy stellen

**Files:**
- Create: `.claude/settings.json`
- Modify: `.ultraloom/config.toml`

**Interfaces:**
- Consumes: `ultraloom policy hook` aus Task 4.
- Produces: nichts für Code.

- [ ] **Step 1: Write the project rules**

An `.ultraloom/config.toml` anhängen:

```toml
[[policy.paths.rules]]
match  = [".ultraloom/runs/*", "uv.lock", ".coverage"]
reason = "An edited journal destroys what replay exists for; the lock belongs to uv."

[[policy.commands.rules]]
regex  = "^\\s*git\\s+push\\b"
reason = "Whether commits reach the remote is a human's decision (CLAUDE.md)."

[[policy.commands.rules]]
regex  = "^\\s*pip\\s+install\\b"
reason = "This project uses uv, never pip."
```

- [ ] **Step 2: Write the hook configuration**

`.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "\"${CLAUDE_PROJECT_DIR}/.venv/Scripts/ultraloom.exe\" policy hook",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 3: Verify by hand, both ways**

```bash
.venv/Scripts/ultraloom.exe policy check commands "git push origin master"
```

Expected: Exit 2, Begründung auf stderr.

```bash
.venv/Scripts/ultraloom.exe policy check commands "git status"
```

Expected: Exit 0, keine Ausgabe.

- [ ] **Step 4: Verify the payload path**

```bash
echo '{"tool_name":"Write","tool_input":{"file_path":".ultraloom/runs/0001.jsonl","content":"x"}}' | .venv/Scripts/ultraloom.exe policy hook
```

Expected: Exit 2, Begründung über das Journal.

- [ ] **Step 5: Commit**

```bash
git add .claude/settings.json .ultraloom/config.toml
```

Nachricht:

```
chore(policy): guard this repository with its own rules

The two rules that have a history here: a subagent pushed master once,
and an edited journal would cost replay its meaning.
```

---

## Was danach ansteht, aber nicht hierher gehört

- Die übrigen Hooks dieses Repos: `post_edit` (Profil `edit`), `stop` (`check all`, blockend mit Zähler bis 3, Marker `.claude/.no-verify`), `session_start` (pausierte Läufe melden). Entworfen im Gespräch, noch ohne Spec.
- Das Ausrollen nach `space` und `iam_backend`, je ein eigener Vorgang.
