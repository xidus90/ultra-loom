# Commit-Sprachprüfung — Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ultraloom bekommt ein Unterkommando `commit-msg`, das eine Commit-Nachricht ablehnt, die offensichtlich in der falschen Sprache geschrieben ist.

**Architecture:** Drei Schichten wie bei Policy und Hooks: `language` entscheidet über einen Text (nur Standardbibliothek), `config` liest `[commit]` aus `.ultraloom/config.toml`, `cli` liest die Datei, die git übergibt, und übersetzt das Urteil in Exit-Codes. Ein `.githooks/commit-msg` im Projekt ruft das Kommando.

**Tech Stack:** Python 3.13, `uv`, nur Standardbibliothek (`re`, `tomllib`, `pathlib`, `dataclasses`), pytest, ruff, mypy (strict), coverage.

**Spec:** `docs/.superpowers/specs/2026-08-25-commit-sprachpruefung-design.md`

## Global Constraints

- **Arbeitsverzeichnis** `C:/Users/micro/Documents/#GIT/ultraloom`, Zweig `feat/commit-message-language`. Prüfe mit `git rev-parse --show-toplevel`, dass du im Hauptcheckout stehst — nennt es ein anderes Verzeichnis als das, in dem du bist, arbeitest du am falschen Ort. **Nicht** `--git-dir` gegen `--git-common-dir` vergleichen; git antwortet in zwei Schreibweisen, und der Textvergleich schlägt fehl (siehe `CLAUDE.md`).
- **Vor jedem Commit `git diff --cached --stat` lesen.** Andere Sitzungen arbeiten im selben Checkout; am 2026-08-25 sind fünf fremde Umbenennungen in einen Commit geraten, weil nur die eigene Datei vorgemerkt, der Index aber nicht gelesen wurde.
- **TDD ohne Ausnahme:** erst der Test, laufen lassen, **als rot sehen**, dann die Implementierung.
- **100 % Coverage**, `fail_under = 100`. Jeder Ausschluss trägt seine Begründung.
- **mypy strict**, kein `Any`, kein `type: ignore` ohne Begründung dahinter.
- **ruff**, `select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF"]`, `line-length = 100`.
- **Sprache:** Docstrings, Kommentare und Meldungen **englisch** und **ASCII**. Ein typografisches `…` lässt `print` auf einer cp1252-Konsole abstürzen. Prosa unter `docs/.superpowers/` bleibt deutsch.
- **Eine Ausnahme von ASCII, und nur diese:** Testdaten, die Umlaute prüfen, enthalten Umlaute. Ein Test, der belegen soll, dass „für" gefunden wird, kann das nicht in ASCII tun. Die Ausnahme gilt für Zeichenketten *in* Tests, nicht für Kommentare, Docstrings oder Meldungen daneben.
- **Commits:** Nachricht über eine Datei und `git commit -F`, **ohne** `Co-Authored-By`, **ohne** `--no-gpg-sign`. Autor und Committer sind der Nutzer aus der git-Konfiguration. Datei danach löschen.
- **Kein `git push`.**
- **Ein Shell-Befehl je Aufruf.**
- **Modulgrenze:** `ultraloom.commit.*` darf `ultraloom.config` benutzen, nichts aus `checks` und nichts aus dem Harness (`graph`, `state`, `runner`, `model`, `discovery`).

---

### Task 1: Die Heuristik (`commit.language`)

Entscheidet über einen Text, kennt weder Dateien noch Konfiguration.

**Files:**
- Create: `src/ultraloom/commit/__init__.py`
- Create: `src/ultraloom/commit/language.py`
- Create: `tests/commit/__init__.py`
- Create: `tests/commit/test_language.py`

**Interfaces:**
- Consumes: nichts.
- Produces:
  - `type Language = Literal["en", "de"]`
  - `LANGUAGES: tuple[Language, ...]`
  - `Finding(line_number: int, line: str, hits: tuple[str, ...])`
  - `scan(text: str, language: Language, threshold: int, allow: tuple[re.Pattern[str], ...] = ()) -> tuple[Finding, ...]`
  - `STOPWORDS: Mapping[Language, frozenset[str]]`

- [ ] **Step 1: Write the failing tests**

`tests/commit/test_language.py`:

```python
"""What counts as obviously-the-wrong-language, line by line."""

from __future__ import annotations

import re

import pytest

from ultraloom.commit.language import Finding, scan


def test_an_english_message_is_clean() -> None:
    text = "Let the stop gate run one profile instead of the whole chain"
    assert scan(text, "en", 2) == ()


def test_german_prose_is_found() -> None:
    text = "Das Gate laeuft jetzt mit dem Profil und nicht mehr ueber die ganze Kette"
    found = scan(text, "en", 2)
    assert len(found) == 1
    assert found[0].line_number == 1
    assert len(found[0].hits) >= 2


def test_the_threshold_counts_per_line_not_per_message() -> None:
    """Two lines with one hit each are not one line with two.

    A body that lists two German page titles is exactly that shape, and it is
    the shape the threshold exists to let through.
    """
    text = "Add a page\n\nSee der Titel\nSee das Andere"
    assert scan(text, "en", 2) == ()


def test_one_hit_in_a_line_is_not_enough() -> None:
    text = "Rename the file to konzept-der-woche.md"
    assert scan(text, "en", 2) == ()


def test_a_quoted_sentence_does_not_count() -> None:
    """German turns up inside English messages; quoting is how."""
    text = 'The page says "der Bericht ist nicht vollstaendig" and it is right'
    assert scan(text, "en", 2) == ()


def test_a_code_span_does_not_count() -> None:
    text = "Rename `der_alte_name` to `the_new_name` and nicht more"
    assert scan(text, "en", 2) == ()


def test_a_path_does_not_count() -> None:
    text = "Move wiki/decisions/das-und-der-fall.md into the archive"
    assert scan(text, "en", 2) == ()


def test_a_trailer_does_not_count() -> None:
    text = "Fix the gate\n\nCo-Authored-By: Der Name <von@example.org>"
    assert scan(text, "en", 2) == ()


def test_the_diff_below_the_scissors_is_ignored() -> None:
    """`git commit --verbose` appends the whole diff, uncommented.

    Without the cut, every commit touching German prose would be refused.
    """
    text = (
        "Add the page\n"
        "# ------------------------ >8 ------------------------\n"
        "diff --git a/wiki/x.md b/wiki/x.md\n"
        "+der Bericht und das Ergebnis sind nicht vollstaendig\n"
    )
    assert scan(text, "en", 2) == ()


def test_comment_lines_are_ignored() -> None:
    """git writes its own hints into the file with a leading #."""
    text = "Add the page\n# Bitte gib eine Commit-Beschreibung fuer die Aenderungen ein\n"
    assert scan(text, "en", 2) == ()


def test_the_other_direction_finds_english_in_german() -> None:
    text = "The gate now runs with the profile and not with the whole chain"
    found = scan(text, "de", 2)
    assert len(found) == 1


def test_a_german_message_is_clean_under_de() -> None:
    text = "Das Gate laeuft jetzt mit dem Profil statt ueber die ganze Kette"
    assert scan(text, "de", 2) == ()


def test_an_allow_pattern_drops_the_whole_line() -> None:
    text = "Add the page\nQuelle: der Bericht und das Ergebnis"
    allow = (re.compile(r"^Quelle:"),)
    assert scan(text, "en", 2, allow) == ()


def test_a_finding_carries_the_line_and_its_hits() -> None:
    text = "Add a page\nDas Ergebnis und der Bericht fehlen"
    found = scan(text, "en", 2)
    assert found[0].line_number == 2
    assert "und" in found[0].hits


@pytest.mark.parametrize("word", ["die", "war", "man", "den", "hat", "in", "so", "an"])
def test_german_words_that_are_also_english_never_count(word: str) -> None:
    """"Let the process die in the war room" must not be a finding.

    Presence of a German word is evidence only when the word means nothing in
    the target language. A gate with false positives gets routed around with
    --no-verify and then protects nothing.
    """
    from ultraloom.commit.language import STOPWORDS

    assert word not in STOPWORDS["en"]


@pytest.mark.parametrize(
    "text",
    [
        "Das Ergebnis und der Bericht fehlen",
        "Für das Ergebnis und über den Bericht",
    ],
)
def test_umlauts_are_found_although_the_list_is_ascii(text: str) -> None:
    """A real German commit writes "für", the list spells "fuer".

    Without folding, the check would miss exactly the messages it exists for
    while passing their ASCII-transcribed cousins.
    """
    assert scan(text, "en", 2) != ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/commit/test_language.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.commit'`

- [ ] **Step 3: Write the implementation**

`src/ultraloom/commit/__init__.py`:

```python
"""Whether a commit message is obviously in the wrong language.

Not whether it is in the right one -- nothing can decide that. The smaller
question is the one the observed failure asks: a language rule that lives only
in files nothing loads automatically stops holding, and the messages that
follow are not subtly off, they are plainly another language.
"""
```

`src/ultraloom/commit/language.py`:

```python
"""The decision itself: one text against one word list.

No files, no configuration. Whoever wants to understand what counts as a
finding reads this module and nothing else.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

type Language = Literal["en", "de"]

LANGUAGES: tuple[Language, ...] = ("en", "de")

# Function words of the other language that mean nothing in the target one.
# Presence is evidence; a word that is also ordinary English is not, however
# German it feels.
#
# Deliberately absent from the German list, each a normal English word: die,
# war, man, den, hat, in, so, an. "Let the process die in the war room" must
# not be a finding.
#
# The German list is calibrated: in one project's history, a hundred English
# commits against sixteen German ones, and these are the words that separate
# them. The English list is not -- see the spec's "Grenzen".
STOPWORDS: Mapping[Language, frozenset[str]] = {
    # Searched when the target language is English.
    "en": frozenset(
        {
            "der", "das", "dem", "des", "und", "oder", "nicht", "ein", "eine",
            "einen", "einem", "eines", "einer", "sind", "waren", "haben",
            "wird", "wurde", "werden", "mit", "von", "fuer", "ueber", "aus",
            "nach", "ohne", "beim", "zum", "zur", "zu", "auf", "durch",
            "gegen", "dass", "weil", "wenn", "schon", "noch", "jeden", "jede",
            "jeder", "wieder", "statt", "samt", "unter", "zusammen", "heraus",
            "ihn", "fest",
        }
    ),
    # Searched when the target language is German. Function words with no
    # German homograph. Not calibrated against a corpus -- the threshold for
    # this direction is a starting point, not a measurement.
    "de": frozenset(
        {
            "the", "and", "with", "this", "that", "from", "which", "into",
            "there", "their", "would", "should", "could", "because", "while",
            "about", "against", "between", "through", "without", "instead",
            "rather", "still", "already", "every", "each", "again",
        }
    ),
}

# `git commit --verbose` appends the whole diff below this marker, uncommented.
# The diff carries whatever the change touched, so scoring it would refuse
# every commit that goes near prose in the other language.
SCISSORS = re.compile(r"^#\s*-+\s*>8\s*-+")

# Shapes that carry the other language inside an otherwise fine message. All
# four are removed from a line before it is scored, because a gate with false
# positives gets routed around with --no-verify and then protects nothing.
TRAILER = re.compile(r"^[A-Za-z-]+:\s")
CODE_SPAN = re.compile(r"`[^`]*`")
QUOTED_SPAN = re.compile(r"\"[^\"]*\"")
PATH_TOKEN = re.compile(r"\S*(?:[/\\]\S*|\.[A-Za-z0-9]{1,5})(?=\s|$)")

# Words may carry umlauts even where the stopword list spells them out:
# a real German commit writes "fuer" or "für", and both must be found. The
# list is ASCII, so the text is folded to match it -- see _fold.
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# The stopword lists are ASCII because this file is. German text is not:
# "für" and "über" are the normal spellings. Folding the text rather than
# doubling every entry keeps one list instead of two that can drift.
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


@dataclass(frozen=True, slots=True)
class Finding:
    """One line that reads as the wrong language, and why."""

    line_number: int
    line: str
    hits: tuple[str, ...]


def scan(
    text: str,
    language: Language,
    threshold: int,
    allow: tuple[re.Pattern[str], ...] = (),
) -> tuple[Finding, ...]:
    """Every line whose stopword count reaches the threshold.

    Per line and not per message: a body listing two page titles in the other
    language is two lines of one hit, not one line of two, and the second
    reading would refuse it.
    """
    stopwords = STOPWORDS[language]
    findings: list[Finding] = []

    for number, line in enumerate(text.splitlines(), start=1):
        if SCISSORS.match(line):
            # Everything below belongs to the diff, not to the message.
            break
        if line.startswith("#"):
            continue
        if any(pattern.search(line) for pattern in allow):
            continue
        hits = _hits(line, stopwords)
        if len(hits) >= threshold:
            findings.append(Finding(number, line, hits))
    return tuple(findings)


def _hits(line: str, stopwords: frozenset[str]) -> tuple[str, ...]:
    """The stopwords in one line, after the exempt shapes are removed."""
    if TRAILER.match(line):
        return ()
    stripped = PATH_TOKEN.sub(" ", QUOTED_SPAN.sub(" ", CODE_SPAN.sub(" ", line)))
    folded = stripped.lower().translate(_FOLD)
    return tuple(word for word in _WORD.findall(folded) if word in stopwords)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/commit/test_language.py -v`
Expected: PASS, 16 Tests.

- [ ] **Step 5: Run the chain**

Run: `uv run ultraloom check all`
Expected: grün, 100 %.

- [ ] **Step 6: Commit**

```bash
git diff --cached --stat
```

```bash
git add src/ultraloom/commit tests/commit
```

Nachricht:

```
Decide whether a text is obviously the wrong language

Per line, not per message: two page titles in the other language are two
lines of one hit. Four shapes are removed before scoring -- trailers, code
spans, quotes and paths -- because a gate with false positives gets routed
around with --no-verify and then protects nothing.
```

---

### Task 2: Konfiguration (`commit.config`)

**Files:**
- Create: `src/ultraloom/commit/config.py`
- Create: `tests/commit/test_config.py`

**Interfaces:**
- Consumes: `Language`, `LANGUAGES` aus Task 1.
- Produces:
  - `CommitPolicy(language: Language, threshold: int, allow: tuple[re.Pattern[str], ...])`
  - `load_commit_policy(root: Path) -> CommitPolicy | None` — `None`, wenn kein `[commit]`-Abschnitt existiert
  - wirft `ultraloom.config.ConfigError` bei jedem Schemafehler

- [ ] **Step 1: Write the failing tests**

`tests/commit/test_config.py`:

```python
"""The [commit] section, and what happens when it is wrong."""

from __future__ import annotations

from pathlib import Path

import pytest

from ultraloom.commit.config import load_commit_policy
from ultraloom.config import ConfigError


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / ".ultraloom").mkdir()
    (tmp_path / ".ultraloom" / "config.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_no_config_file_means_no_policy(tmp_path: Path) -> None:
    assert load_commit_policy(tmp_path) is None


def test_no_commit_section_means_no_policy(tmp_path: Path) -> None:
    """Opt-in: a project without a language rule gets no check."""
    root = _write(tmp_path, '[verify]\nlint = "ruff check ."\n')
    assert load_commit_policy(root) is None


def test_a_language_alone_is_enough(tmp_path: Path) -> None:
    root = _write(tmp_path, '[commit]\nlanguage = "en"\n')
    policy = load_commit_policy(root)
    assert policy is not None
    assert policy.language == "en"
    assert policy.threshold == 2


def test_the_threshold_can_be_raised(tmp_path: Path) -> None:
    root = _write(tmp_path, '[commit]\nlanguage = "en"\nthreshold = 3\n')
    policy = load_commit_policy(root)
    assert policy is not None
    assert policy.threshold == 3


def test_allow_patterns_are_compiled(tmp_path: Path) -> None:
    root = _write(tmp_path, """
[commit]
language = "en"

[[commit.allow]]
regex  = "^Quelle:"
reason = "Zitierte Quelle, keine Prosa."
""")
    policy = load_commit_policy(root)
    assert policy is not None
    assert policy.allow[0].search("Quelle: der Bericht") is not None


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('[commit]\nlanguage = "fr"', "must be one of"),
        ("[commit]\nlanguage = 1", "must be one of"),
        ('[commit]\nlanguage = "en"\nthreshold = "zwei"', "must be an integer"),
        ('[commit]\nlanguage = "en"\nthreshold = 0', "must be greater than zero"),
        ('[commit]\nlanguage = "en"\nthreshold = true', "must be an integer"),
        ('[commit]\nthreshold = 2', "needs a `language`"),
        ('[commit]\nlanguage = "en"\n[[commit.allow]]\nregex = "["\nreason = "x"',
         "invalid regex"),
        ('[commit]\nlanguage = "en"\n[[commit.allow]]\nregex = "^x"', "needs a `reason`"),
        (
            '[commit]\nlanguage = "en"\n[[commit.allow]]\nreason = "x"',
            "needs a `regex`; unlike the policy's path rules there is no `match`",
        ),
        ('commit = "no table"', r"\[commit\] must be a table"),
    ],
)
def test_a_broken_schema_is_refused_by_name(tmp_path: Path, body: str, message: str) -> None:
    root = _write(tmp_path, body)
    with pytest.raises(ConfigError, match=message):
        load_commit_policy(root)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/commit/test_config.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.commit.config'`

- [ ] **Step 3: Write the implementation**

Aufbau wie `src/ultraloom/policy/config.py` — lies es zuerst und folge seiner Machart: `tomllib.loads`, jede Meldung nennt die Stelle so, wie die Datei sie schreibt, `reason` als Pflichtfeld, `ConfigError` beim Lesen statt zur Laufzeit. Anders als bei der Policy nimmt `[[commit.allow]]` nur `regex`, kein `match`: Ein Glob hat auf eine Textzeile angewandt keine klare Bedeutung, und ein unbesehen als Regex kompiliertes `match = "WIP*"` würde still etwas anderes bedeuten, als wer es schreibt, erwartet.

Zwei Punkte, die dieses Modul anders macht als die Policy, beide mit Kommentar zu belegen:

- **`load_commit_policy` gibt `None` zurück**, wenn `[commit]` fehlt. Die Policy hat eingebaute Sicherheitsregeln, die auch ohne Konfiguration gelten; hier gibt es nichts, was ohne eine gewählte Sprache gälte.
- **`language` hat keine Vorgabe.** Ein Projekt, das den Abschnitt anlegt, ohne die Sprache zu nennen, hat sich noch nicht entschieden — eine geratene Vorgabe würde Commits nach einer Regel ablehnen, die niemand gewählt hat.

- [ ] **Step 4: Run tests and the chain**

Run: `uv run pytest tests/commit -v` → PASS
Run: `uv run ultraloom check all` → grün, 100 %

- [ ] **Step 5: Commit**

```bash
git diff --cached --stat
```

```bash
git add src/ultraloom/commit/config.py tests/commit/test_config.py
```

Nachricht:

```
Read [commit] and refuse a broken one while reading

Opt-in by design: without the section there is no check, because there is
no sensible default language to guess.
```

---

### Task 3: Das Unterkommando

**Files:**
- Create: `src/ultraloom/commit/cli.py`
- Create: `tests/commit/test_cli.py`
- Modify: `src/ultraloom/cli.py` (`_parser`, `main`)
- Modify: `tests/test_module_boundary.py`

**Interfaces:**
- Consumes: `scan`, `Finding` (Task 1); `load_commit_policy`, `CommitPolicy` (Task 2).
- Produces:
  - `run(path: Path, root: Path, stderr: TextIO) -> int`
  - `EXIT_OK = 0`, `EXIT_INTERNAL = 1`, `EXIT_WRONG_LANGUAGE = 2`

- [ ] **Step 1: Write the failing tests**

`tests/commit/test_cli.py`:

```python
"""File in, exit code out. The heuristic is test_language's business."""

from __future__ import annotations

import io
from pathlib import Path

from ultraloom.commit.cli import run


def _project(tmp_path: Path, config: str) -> Path:
    (tmp_path / ".ultraloom").mkdir()
    (tmp_path / ".ultraloom" / "config.toml").write_text(config, encoding="utf-8")
    return tmp_path


def _message(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text(text, encoding="utf-8")
    return path


def test_without_a_commit_section_everything_passes(tmp_path: Path) -> None:
    root = _project(tmp_path, '[verify]\nlint = "ruff check ."\n')
    path = _message(tmp_path, "Das Gate laeuft jetzt mit dem Profil und nicht anders")
    errors = io.StringIO()
    assert run(path, root, errors) == 0
    assert errors.getvalue() == ""


def test_an_english_message_passes(tmp_path: Path) -> None:
    root = _project(tmp_path, '[commit]\nlanguage = "en"\n')
    path = _message(tmp_path, "Let the gate run one profile")
    errors = io.StringIO()
    assert run(path, root, errors) == 0


def test_a_german_message_is_refused_with_its_lines(tmp_path: Path) -> None:
    root = _project(tmp_path, '[commit]\nlanguage = "en"\n')
    path = _message(tmp_path, "Add a thing\n\nDas Ergebnis und der Bericht fehlen")
    errors = io.StringIO()
    assert run(path, root, errors) == 2
    said = errors.getvalue()
    assert "line 3" in said
    assert "und" in said
    assert "--no-verify" in said


def test_a_missing_file_is_an_internal_error(tmp_path: Path) -> None:
    root = _project(tmp_path, '[commit]\nlanguage = "en"\n')
    errors = io.StringIO()
    assert run(tmp_path / "nope", root, errors) == 1


def test_a_broken_config_is_an_internal_error_not_a_refusal(tmp_path: Path) -> None:
    """A typo in the config must not block every commit in the repository.

    The opposite of the policy's rule, and deliberately: a policy that passes
    silently gives away a file, while a language gate that passes costs a
    message in the wrong language. Blocking every commit is the larger harm
    here, and the mistake surfaces at the next `ultraloom check` anyway.
    """
    root = _project(tmp_path, '[commit]\nlanguage = "klingon"\n')
    path = _message(tmp_path, "Add a thing")
    errors = io.StringIO()
    assert run(path, root, errors) == 1
    assert "klingon" in errors.getvalue()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/commit/test_cli.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ultraloom.commit.cli'`

- [ ] **Step 3: Write the implementation**

Der Adapter liest die Datei, holt die Policy, ruft `scan` und schreibt die Befunde. Die Meldung nennt **jede** beanstandete Zeile mit Nummer und Treffern, dazu den Ausweg und dass er die Regel nicht aufhebt:

```
ultraloom commit-msg: this message reads as German, and commits here are English.
  line 3: Das Ergebnis und der Bericht fehlen
          hits: das, und, der
Rewrite it, or use `git commit --no-verify` if this cannot wait. The next
commit runs this check again.
```

- [ ] **Step 4: Wire up the subcommand**

In `_parser()` von `src/ultraloom/cli.py`, hinter dem `hook`-Block:

```python
    commit_msg = subparsers.add_parser(
        "commit-msg", parents=[common], help="check a commit message's language"
    )
    commit_msg.add_argument("path", help="the message file git passes to the hook")
```

In `main()`, bei `policy` und `hook` — vor `load_config`, aus demselben Grund: Das Kommando liest `[commit]` selbst, und ein Fehler in `[verify]` ist nicht seine Sache.

- [ ] **Step 5: Extend the boundary test**

An `tests/test_module_boundary.py` anhängen, nach dem Muster der vorhandenen Proben: `commit-msg` in einem Kindprozess, und weder Harness-Module noch `ultraloom.checks` dürfen danach in dessen `sys.modules` stehen. Ein Sprachgate, das die Prüfkette lädt, zahlt bei jedem Commit dafür.

- [ ] **Step 6: Run tests and the chain**

Run: `uv run pytest -q` → PASS
Run: `uv run ultraloom check all` → grün, 100 %

- [ ] **Step 7: Try it by hand, both ways**

```bash
printf 'Let the gate run one profile\n' > /tmp/msg-ok.txt
```

```bash
uv run ultraloom commit-msg /tmp/msg-ok.txt --root .
```

Erwartet: Exit 0, keine Ausgabe (ultraloom hat selbst keinen `[commit]`-Abschnitt — das ist der Opt-in-Fall).

- [ ] **Step 8: Commit**

```bash
git diff --cached --stat
```

```bash
git add src/ultraloom/commit src/ultraloom/cli.py tests/commit tests/test_module_boundary.py
```

Nachricht:

```
Refuse a commit message written in the wrong language

Exit 1 for a broken config rather than exit 2: blocking every commit over
a typo is the larger harm, and the mistake surfaces at the next check.
```

---

### Task 4: Der Kalibriermodus

**Files:**
- Modify: `src/ultraloom/commit/cli.py`, `src/ultraloom/cli.py`
- Create: `src/ultraloom/commit/calibrate.py`
- Create: `tests/commit/test_calibrate.py`

**Interfaces:**
- Consumes: `scan` (Task 1), `load_commit_policy` (Task 2).
- Produces: `calibrate(messages: Sequence[str], language: Language, thresholds: Sequence[int]) -> Mapping[int, tuple[int, ...]]` — je Schwelle die Indizes der Nachrichten, die abgelehnt würden.

- [ ] **Step 1: Write the failing test**

`tests/commit/test_calibrate.py`:

```python
"""What a threshold would cost, measured against real messages."""

from __future__ import annotations

from ultraloom.commit.calibrate import calibrate

_MESSAGES = (
    "Let the gate run one profile",                      # 0: English
    "Rename the page to der-alte-fall.md",               # 1: one hit, a path
    'The page says "der Bericht und das Ergebnis"',      # 2: quoted
    "Das Ergebnis und der Bericht fehlen vollstaendig",  # 3: German prose
)


def test_a_higher_threshold_refuses_fewer() -> None:
    result = calibrate(_MESSAGES, "en", (1, 2, 3))
    assert 3 in result[2]
    # Sets, not tuples: comparing tuples with <= is lexicographic and would
    # pass on orderings that have nothing to do with "refuses a subset".
    assert set(result[3]) <= set(result[2])
    assert set(result[2]) <= set(result[1])


def test_the_calibrated_default_refuses_only_the_prose() -> None:
    """Two is the line between the false-positive shapes and real prose."""
    assert calibrate(_MESSAGES, "en", (2,))[2] == (3,)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/commit/test_calibrate.py -v`
Expected: FAIL mit `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation and the flag**

`calibrate` wendet `scan` je Schwelle auf jede Nachricht an und sammelt die Indizes der abgelehnten. Das Kommando bekommt `--calibrate <n>`: Es liest die letzten `n` Nachrichten über `git log --format=%B -n <n>` (getrennt an `\0` über `-z`, weil eine Nachricht Leerzeilen enthält) und druckt eine Tabelle — je Schwelle die Zahl der Ablehnungen und die erste Zeile jeder abgelehnten Nachricht.

Der git-Aufruf geht über `ultraloom.process.run` mit Timeout, wie im Rest des Projekts, nicht über ein eigenes `subprocess`.

- [ ] **Step 4: Run tests and the chain**

Run: `uv run pytest tests/commit -v` → PASS
Run: `uv run ultraloom check all` → grün, 100 %

- [ ] **Step 5: Calibrate against this repository**

```bash
uv run ultraloom commit-msg --calibrate 100 --root .
```

ultraloom's eigene Commits sind englisch. Erwartet: bei Schwelle 2 keine Ablehnung. Lehnt es welche ab, **halte an und berichte** — dann ist entweder die Wortliste zu breit oder eine der vier Ausnahmen greift nicht, und beides gehört gefunden, bevor jemand die Prüfung einschaltet.

- [ ] **Step 6: Commit**

```bash
git diff --cached --stat
```

```bash
git add src/ultraloom/commit src/ultraloom/cli.py tests/commit
```

Nachricht:

```
Let a project measure its own threshold

The built-in two is calibrated against one project's history. Anyone
raising or lowering it should see first what it would have refused.
```

---

### Task 5: Doku und der git-Hook

**Files:**
- Modify: `README.md`, `README.de.md`
- Modify: `docs/.superpowers/specs/2026-08-25-commit-sprachpruefung-design.md` (Ergebnis der Kalibrierung)

**Interfaces:**
- Consumes: alles aus Task 1 bis 4.
- Produces: nichts für Code.

- [ ] **Step 1: Write the README section**

Ein Abschnitt „Commit messages" hinter „Policy". Er enthält: wofür es da ist, das vollständige Schema mit beiden Sprachen, die vier eingebauten Ausnahmen, `--calibrate`, das Exit-Protokoll — und die drei Zeilen für den git-Hook:

```sh
#!/usr/bin/env sh
exec ultraloom commit-msg "$1"
```

Dazu der Hinweis auf `core.hooksPath`, weil ein Hook unter `.git/hooks/` nicht versioniert ist und in einem frischen Klon fehlt.

**Ausdrücklich hineinschreiben**, dass die englische Wortliste *nicht* kalibriert ist: Für `language = "de"` ist die Schwelle ein Anfangswert, bis jemand sie an einem deutschsprachigen Repository misst. Eine geratene Zahl als gemessene auszugeben, wäre genau der Fehler, den dieses Werkzeug verhindern soll.

- [ ] **Step 2: Mirror it into README.de.md**

Derselbe Abschnitt auf Deutsch, an derselben Stelle, mit denselben Beispielen.

- [ ] **Step 3: Record the calibration in the spec**

Das Ergebnis aus Task 4 Schritt 5 in den Abschnitt „Die Heuristik" eintragen: wie viele Commits geprüft wurden und wie viele bei Schwelle 2 abgelehnt worden wären. Damit hat die Vorgabe eine zweite Messung neben space' Historie.

- [ ] **Step 4: Run the chain**

Run: `uv run ultraloom check all` → grün

- [ ] **Step 5: Commit**

```bash
git diff --cached --stat
```

```bash
git add README.md README.de.md docs/.superpowers/specs
```

Nachricht:

```
Document the commit message check and its git hook

Including what is not calibrated: the English word list has no corpus
behind it, and the README says so rather than implying otherwise.
```

---

## Was danach ansteht, aber nicht hierher gehört

- **Kommentare und Docstrings.** Dieselbe Sprachregel gilt dort, aber die Falschmeldungsfläche ist eine andere — Fachbegriffe, Namen und zitierte Ausgaben stehen im Quelltext dichter.
- **Weitere Sprachpaare.** Jedes braucht eine Wortliste, die jemand kalibriert hat.
- **space auf das Werkzeug umstellen.** `commit_language.py` dort kann entfallen, sobald dieses Kommando dasselbe leistet — eigener Vorgang, mit einem Vergleich beider Urteile über dieselbe Historie.
