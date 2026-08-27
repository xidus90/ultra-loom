# Sprachen erweitern — Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Der Commit-Sprachprüfung einen Skript-Test für nicht-lateinische
Schriften und eine verschmolzene romanische Wortliste geben.

**Architecture:** Beides erzeugt Treffer im vorhandenen Sinn, sodass Schwelle,
Zeilenzählung, Spannen, `[[commit.allow]]`, Trailer und Scherenschnitt
unverändert weitergelten. Kein zweiter Mechanismus.

**Tech Stack:** Python, `unicodedata` aus der Standardbibliothek — keine neue
Abhängigkeit.

**Spec:** `docs/.superpowers/specs/2026-08-27-sprachen-erweitern-design.md`

## Global Constraints

- TDD. 100 % Coverage (`fail_under = 100`), mypy strict, kein `Any`, kein
  `type: ignore` ohne Begründung, ruff sauber.
- Kommentare, Docstrings, Fehlermeldungen, Testnamen und Commit-Nachrichten
  **englisch und reines ASCII**. Deutsche Prosa nur unter `docs/` und in
  `README.de.md`. Ausnahme: Testdaten, die fremde Schriften prüfen — die
  brauchen die echten Zeichen.
- Commits tragen nur die Identität des Nutzers, kein Modell- oder Agentenhinweis.
- Kein `git push`.
- `LANGUAGES` bleibt `("en", "de")` — es wachsen die Quellen, nicht die Ziele.
- Die Filterregel der Spec ist bindend und wird durch einen Test gehalten, nicht
  durch einen Kommentar.
- Vor jedem Commit `git rev-parse --abbrev-ref HEAD` und
  `git diff --cached --stat` lesen; mehrere Sitzungen teilen diesen Checkout.
- Mehrzeilige Commit-Nachrichten über eine Datei und `git commit -F`.

---

### Task 1: Der Skript-Test

**Files:**
- Modify: `src/ultraloom/commit/language.py`
- Test: `tests/commit/test_language.py`

**Interfaces:**
- Consumes: `scan(text, language, threshold, allow=())`, `_hits(line, stopwords, *, is_subject)`
- Produces: Treffer aus nicht-lateinischen Schriften, die in derselben
  `Finding.hits`-Folge landen wie Stoppworttreffer.

- [ ] **Step 1: Die fehlschlagenden Tests schreiben**

Erfasste Schriften: Han, Hiragana, Katakana, Hangul, Cyrillic, Arabic, Hebrew,
Greek, Devanagari, Thai.

```python
def test_two_words_of_a_non_latin_script_are_a_finding() -> None:
    findings = scan("Fix the parser\n\n修复解析 器错误", "en", 2)
    assert findings and findings[0].line_number == 3


def test_a_single_quoted_term_stays_below_the_threshold() -> None:
    # One term is a citation, not a sentence -- the shape a hook must let pass.
    assert scan("Rename the 北京 constant", "en", 2) == ()


def test_a_script_run_counts_once_however_long_it_is() -> None:
    # Counting characters would put every Chinese word over the threshold at once.
    findings = scan("Fix\n\n修复解析器错误修复", "en", 2)
    assert findings == ()


def test_latin_with_diacritics_is_not_a_script_hit() -> None:
    assert scan("Add a café fixture and a naïve retry", "en", 2) == ()


def test_a_script_hit_obeys_the_span_exemption() -> None:
    assert scan("Rename `修复 解析` to parse", "en", 2) == ()


def test_a_script_hit_obeys_an_allow_rule() -> None:
    import re
    rule = (re.compile(r"^Sample: "),)
    assert scan("Fix\n\nSample: 修复 解析", "en", 2, rule) == ()


def test_a_script_hit_is_scored_for_a_german_target_too() -> None:
    findings = scan("Fehler beheben\n\nисправление ошибки", "de", 2)
    assert findings and findings[0].line_number == 3


def test_each_covered_script_produces_hits() -> None:
    samples = {
        "Han": "修复 解析",
        "Hiragana": "これは それは",
        "Katakana": "パーサ エラー",
        "Hangul": "파서 오류",
        "Cyrillic": "исправление ошибки",
        "Arabic": "إصلاح الخطأ",
        "Hebrew": "תיקון שגיאה",
        "Greek": "διόρθωση σφάλματος",
        "Devanagari": "त्रुटि सुधार",
        "Thai": "แก้ไข ข้อผิด",
    }
    for name, text in samples.items():
        assert scan(f"Fix\n\n{text}", "en", 2), name
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/commit/test_language.py -q`

- [ ] **Step 3: Umsetzen**

Ein Treffer je zusammenhängendem Lauf von Buchstaben *einer* nicht-lateinischen
Schrift. Die Schriftzugehörigkeit über `unicodedata.name()` des Zeichens oder
über Codepunktbereiche bestimmen — welches von beiden, entscheidet der
Implementierer nach Lesbarkeit und Geschwindigkeit; die Wahl gehört in einen
Kommentar. Nur Zeichen mit `unicodedata.category(...).startswith("L")` zählen,
damit Satzzeichen keine Läufe trennen oder erzeugen.

Der Treffer wird in `_hits` erzeugt, **nach** dem Ausblenden der Spannen und
Pfade, damit alle vorhandenen Ausnahmen ohne Zutun gelten. Als Trefferzeichenkette
den Lauf selbst nehmen, gekürzt auf eine sinnvolle Länge, damit die Meldung
lesbar bleibt.

- [ ] **Step 4: Tests laufen lassen, Erfolg bestätigen**

- [ ] **Step 5: Volle Kette und Commit**

Run: `uv run ultraloom check all`

---

### Task 2: Die romanische Liste und die Filterregel

**Files:**
- Modify: `src/ultraloom/commit/language.py`
- Test: `tests/commit/test_language.py`

**Interfaces:**
- Consumes: `STOPWORDS: Mapping[Language, frozenset[str]]`
- Produces: dieselbe Abbildung, je Ziel um die romanischen Quellwörter
  erweitert und gegen die Zielsprache gefiltert.

- [ ] **Step 1: Die fehlschlagenden Tests schreiben**

```python
def test_spanish_prose_is_refused_where_commits_are_english() -> None:
    findings = scan("Fix\n\nCorrige el error que aparece con la entrada", "en", 2)
    assert findings and findings[0].line_number == 3


def test_portuguese_prose_is_refused_where_commits_are_english() -> None:
    findings = scan("Fix\n\nCorrige o erro que aparece com a entrada", "en", 2)
    assert findings and findings[0].line_number == 3


def test_french_prose_is_refused_where_commits_are_english() -> None:
    findings = scan("Fix\n\nCorrige les erreurs qui apparaissent avec cette entree", "en", 2)
    assert findings and findings[0].line_number == 3


def test_ordinary_english_survives_the_merged_list() -> None:
    # The union collides with a, as, in, to, her, do, no -- all high-frequency
    # English. Without the filter this line would carry five hits.
    assert scan("Add a fix to the parser as her review asked", "en", 2) == ()


def test_no_source_word_is_ordinary_in_its_target_language() -> None:
    # The rule the spec makes binding, held by a test rather than a comment.
    ordinary_english = {
        "a", "as", "in", "to", "her", "do", "no", "son", "come", "the", "and",
        "or", "not", "on", "is", "are", "was", "be", "at", "by", "of", "for",
        "with", "if", "then", "than", "there", "here", "now", "new", "old",
        "set", "get", "put", "run", "may", "can", "will", "does", "did", "all",
        "over", "from", "this", "that", "die", "war", "man", "den", "hat", "so",
        "an", "fest", "still", "plus", "sans", "tout", "le", "lo", "tan", "do",
    }
    assert not (STOPWORDS["en"] & ordinary_english)

    ordinary_german = {
        "in", "so", "am", "da", "im", "man", "ist", "war", "wir", "sie", "er",
        "es", "wie", "was", "nun", "hat", "bei", "aus", "als", "ich", "du",
    }
    assert not (STOPWORDS["de"] & ordinary_german)
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

- [ ] **Step 3: Umsetzen**

Eine verschmolzene romanische Liste anlegen — Spanisch, Portugiesisch,
Französisch, Italienisch, Rumänisch, Katalanisch —, sie zu den vorhandenen
Quellen des jeweiligen Ziels hinzunehmen und **gegen die Zielsprache filtern**.
Der Filter gehört in den Code, nicht in die Handarbeit an der Liste: Eine
Konstante je Zielsprache nennt deren gewöhnliche Wörter, und die Vereinigung
wird beim Aufbau um sie erleichtert. So kann eine spätere Liste nicht
versehentlich einschleppen, was hier ausgeschlossen wurde.

Der Kommentar über der Liste sagt, welche Quelle kalibriert ist (die deutsche
gegen Englisch) und welche nicht (alles Neue).

- [ ] **Step 4: Tests laufen lassen, Erfolg bestätigen**

- [ ] **Step 5: Volle Kette und Commit**

---

### Task 3: Kalibrierung, Doku und Endprüfung

**Files:**
- Modify: `README.md`, `README.de.md`
- Modify: `docs/.superpowers/specs/2026-08-25-commit-sprachpruefung-design.md` (Verweis auf den neuen Entwurf)
- Test: keine neuen, sofern kein Code geändert wird

- [ ] **Step 1: Messen**

Run: `uv run ultraloom commit-msg --calibrate 100 --language en --root .`

Die Tabelle gehört in den Bericht. Erscheint eine neue Ablehnung, die vorher
nicht da war, ist das ein Befund und **kein** Anlass, die Listen stillschweigend
zu beschneiden: melden, nicht reparieren.

- [ ] **Step 2: Beide READMEs nachziehen**

Zu beschreiben sind: der Skript-Test samt der Regel „ein Treffer je Wortlauf,
nicht je Zeichen" und warum; die erfassten Schriften; die romanische Gruppe und
warum sie verschmolzen ist; die Filterregel; und unverändert die Ehrlichkeit
darüber, was kalibriert ist und was ein Ausgangspunkt.

Beide Dateien müssen dasselbe sagen.

- [ ] **Step 3: Volle Kette und Commit**
