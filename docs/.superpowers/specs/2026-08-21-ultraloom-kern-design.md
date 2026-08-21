# ultraloom — Kern-Design

**Stand:** 2026-08-21 · **Status:** zur Freigabe · **Zielgruppe:** intern (Entscheidungsgrundlage)

Dieses Dokument ist der Vertrag für Teilprojekt 1. Taucht beim Bauen eine
Streitfrage auf, gilt, was hier steht — nicht die Erinnerung und nicht die
Auslegung durch ein Modell.

---

## 1. Zweck und zentrale Frage

**Wie werden Entwicklungsabläufe, die heute an Disziplin hängen, zu Mechanik —
ohne dass die Mechanik ihre eigene Verlässlichkeit verliert?**

ultraloom ist ein Harness, der Abläufe als Graph ausführt: Knoten sind Schritte,
Kanten sind Übergänge mit Bedingungen. Er läuft unbeaufsichtigt, hält an
definierten Punkten für eine menschliche Entscheidung an, protokolliert jeden
Schritt maschinenlesbar und nimmt einen abgebrochenen Lauf wieder auf.

Er ersetzt Claude Code nicht. Interaktive Arbeit bleibt interaktiv. ultraloom ist
für Abläufe, die wiederholbar, auswertbar oder unbeaufsichtigt laufen sollen.

---

## 2. Der Nutzen, genau benannt

Claude Code bringt Skills, Hooks, Subagenten und Worktrees schon mit. Was
ultraloom hinzufügt, sind genau vier Dinge — und nur diese vier rechtfertigen
das Projekt:

| Fähigkeit | Bedeutet |
|---|---|
| Unbeaufsichtigter Lauf | Ein Ablauf startet und läuft durch, ohne dass jemand zusieht |
| Deterministische Kanten | Der nächste Schritt folgt aus Code, nicht aus einer Modellentscheidung |
| Dauerhafter Zustand | Ein Abbruch verliert nichts; der Lauf setzt am letzten Knoten fort |
| Maschinenlesbares Protokoll | Jeder Lauf ist auswertbar: Kosten, Dauer, Weg, Ausgang |

Fällt einer dieser vier Punkte bei einem geplanten Ablauf weg, ist der Ablauf in
Claude Code besser aufgehoben als in ultraloom.

---

## 3. Grundsätze

1. **Deterministisch, wo es geht.** Ein Modell läuft nur dort, wo Verstehen nötig
   ist. Alles andere ist normaler Code. Die Knotenart macht das sichtbar.
2. **Fallbacks sind Kanten, keine Automatik.** Alles, was der Kern hinter dem
   Rücken des Nutzers nachbessert, macht das Journal als Auswertungsgrundlage
   wertlos.
3. **ultraloom kennt kein Projekt; jedes Projekt darf ultraloom kennen.** Die
   Abhängigkeit zeigt in eine Richtung.
4. **Ein fehlendes Prüfwerkzeug ist ein Fehler, kein Grund zum Überspringen.**
   Ein Lauf, der grün meldet, weil er nichts geprüft hat, ist der einzige Fehler
   in diesem System, der wirklich schadet — er sieht wie Erfolg aus.
5. **Der Mensch entscheidet an den Punkten, die er dafür bestimmt hat.** Ein
   Freigabepunkt ist Teil des Ablaufs, keine Ausnahmebehandlung.
6. **Ohne Netz vollständig prüfbar.** Der Kern ist gegen eine Modellattrappe
   testbar; sonst ist die Coverage-Regel nicht erfüllbar.

---

## 4. Umfang von Teilprojekt 1

**Der Kern kann:** einen Graphen validieren und ausführen, Zustand halten und
fortschreiben, an Freigabepunkten anhalten, jeden Schritt journalisieren, einen
Lauf wiederaufnehmen und aus dem Journal wiedergeben, Werkzeugprofile
durchsetzen, Prüfwerkzeuge auflösen und als `ultraloom check` auch außerhalb
eines Laufs anbieten.

**Der Kern kann ausdrücklich nicht** und soll es auch nicht:

- Fachlogik jeder Art. Ein Knoten, der weiß, was ein OKF-Concept ist, gehört in
  das Projekt, dem OKF gehört.
- Werkzeuge bauen. Datei, Bash, Suche und MCP kommen vom Claude Agent SDK.
- Nebenläufigkeit über mehrere Knoten hinweg. Kanten sind sequentiell mit
  Verzweigung und Rückkanten. Fan-out kommt, wenn ein Ablauf es fordert.
- Scheduler, Weboberfläche, verteilte Ausführung.

Die vier Abläufe, für die ultraloom gebaut wird — Spec→Code→Wiki-Kreis,
Prüfschleife bis grün, Wissenspflege im Wiki, Pläne autonom abarbeiten — sind
Teilprojekte 2 bis 5, die Hook- und OKF-Arbeit ist Teilprojekt 6 und 7
(Abschnitt 16). Jedes bekommt eine eigene Spec und einen eigenen Plan.

---

## 5. Architektur

### 5.1 Grundlage: Claude Agent SDK

Ein `AgentNode` ist ein Aufruf ins Claude Agent SDK (`claude-agent-sdk`, Python).
Damit kommen Read/Write/Edit/Bash/Glob/Grep, Berechtigungen, Sessions, Hooks,
Subagenten und MCP-Server als Konfigurationsfeld — nichts davon wird
nachgebaut.

Zwei Folgen, die bewusst in Kauf genommen werden: ultraloom hängt am Tempo einer
Fremdbibliothek, und ein Knoten ist innen eine Blackbox — sichtbar ist sein
Ergebnis, nicht jeder Zwischenschritt. Beides ist der Preis dafür, die
Werkzeugschicht nicht selbst zu warten.

Die Alternative für einzelne, eng geschnittene Knoten bleibt offen: Messages API
mit Tool Runner hinter derselben Schnittstelle. Ein Knoten muss nicht wissen, wie
sein Nachbar mit dem Modell redet.

### 5.2 Drei Knotenarten

Die Unterscheidung ist die wichtigste Grenze im System. Dass ein Knoten seine Art
nennen muss, macht auf einen Blick sichtbar, wie viel Modell in einem Ablauf
steckt.

| Art | Was es ist | Kosten |
|---|---|---|
| `CodeNode` | Eine Python-Funktion. Bericht lesen, Linter starten, Frontmatter prüfen | Keine Tokens, byteweise reproduzierbar |
| `AgentNode` | Ein Modellaufruf mit Systemprompt, Werkzeugprofil, `effort`, erzwungenem Ausgabeschema | Tokens, nicht reproduzierbar |
| `GateNode` | Hält an und legt eine Frage vor; der Lauf endet aufnahmefähig | Keine |

Der Großteil jedes echten Ablaufs ist `CodeNode`.

### 5.3 Zustand

Ein unveränderliches, typisiertes Objekt. Ein Knoten bekommt es, gibt ein Delta
zurück, der Ausführer setzt beides zu einem neuen Zustand zusammen. Kein Knoten
schreibt in den Zustand hinein — sonst ist Wiederaufnahme unmöglich, weil der
Stand vor dem Knoten nicht mehr bekannt ist.

### 5.4 Journal

Eine JSONL-Datei pro Lauf, eine Zeile pro Knoten: Name, Knotenart, Hash der
Eingabe, Ergebnis, Werkzeugprofil, `effort`, Tokens, Dauer, Ausgang.

Das Journal ist absichtlich **ein** Ding statt zwei: dasselbe Journal ist das
Protokoll zum Auswerten und die einzige Quelle für die Wiederaufnahme. Bei einem
Neustart wird es abgespielt — Knoten mit unverändertem Eingabe-Hash liefern ihr
Ergebnis sofort aus dem Journal, der erste geänderte Knoten und alles danach
läuft echt.

### 5.5 Ausführer

Die Schleife: nächsten Knoten nach Kantenbedingung wählen, ausführen, Journal
schreiben, Zustand fortschreiben. Bei einem `GateNode` anhalten. Bei einem Fehler
entweder die `on_error`-Kante oder Abbruch mit wiederaufnehmbarem Stand.

### 5.6 Modell-Anschluss hinter einer Schnittstelle

Der Modellzugang liegt hinter einem Port, mit einer Attrappe daneben — dasselbe
Muster, das ultra-brain für die Suchschicht nutzt (`search/port.py` +
`search/fake.py`). Der Kern ist damit vollständig ohne Modellaufruf und ohne Netz
testbar.

### 5.7 Dateischnitt

```
src/ultraloom/
  graph.py            Knoten- und Kantentypen, Graphbau, Validierung
  state.py            Zustandsobjekt und Delta-Zusammenführung
  journal.py          JSONL schreiben, lesen, abspielen
  runner.py           Ausführungsschleife
  gate.py             Freigabepunkte
  tools.py            Werkzeugprofile
  checks.py           Auflösung der Prüfwerkzeuge
  config.py           .ultraloom/config.toml lesen
  discovery.py        Abläufe im Projekt finden
  model/port.py       Modellschnittstelle
  model/agent_sdk.py  Anbindung an das Claude Agent SDK
  model/fake.py       Attrappe für Tests
  cli.py              Kommandozeile
  flows/              Mitgelieferte, allgemeine Abläufe
```

Jede Datei ein Zweck, jede mit Testmodul.

---

## 6. Wie ein Ablauf aussieht

Abläufe sind Python, nicht YAML. Kanten tragen Bedingungen, und eine Bedingung in
YAML ist entweder eine Mini-Sprache, die man erfindet und debuggt, oder
eingebetteter Code ohne Typen.

```python
flow = Graph("verify-until-green")

flow.add(CodeNode("run_tests", run_test_suite))
flow.add(CodeNode("read_reports", read_coverage_and_lint))
flow.add(AgentNode(
    "repair",
    prompt=REPAIR_PROMPT,
    schema=RepairResult,
    tools="edit",          # tool profile, not a raw allowlist
    effort="high",
    max_visits=5,          # the loop guard lives on the node
))

flow.edge("run_tests", "read_reports")
flow.edge("read_reports", END,      when=lambda s: s.all_green)
flow.edge("read_reports", "repair", when=lambda s: not s.all_green)
flow.edge("repair", "run_tests")
```

Ein `AgentNode` gibt ein schemavalidiertes Objekt zurück, keinen Fließtext. Prosa
aus einem Knoten in den nächsten zu geben ist die Stelle, an der solche Systeme
unzuverlässig werden.

---

## 7. Wo was liegt

Drei Ebenen, nach einer Faustregel getrennt: **Lässt sich der Unterschied
zwischen zwei Projekten als Konfiguration ausdrücken, gehört der Ablauf nach
ultraloom. Braucht er Wissen über die Welt des Projekts, gehört er ins Projekt.**

| Ebene | Ort | Beispiel |
|---|---|---|
| Kern | ultraloom, als Bibliothek installiert | Ausführer, Journal, Knotenarten |
| Allgemeine Abläufe | ultraloom, `flows/` | Prüfschleife bis grün |
| Projektspezifische Abläufe | `<projekt>/.ultraloom/flows/*.py` | Spec→Code→Wiki-Kreis von space |

Ein allgemeiner Ablauf holt sich das Projektspezifische aus der Konfiguration:

```toml
# <projekt>/.ultraloom/config.toml
[verify]
test     = ".tools/godot4-headless.cmd --headless -s test/run.gd"
lint     = "uvx gdlint ."
coverage = { report = "coverage-report/lcov.info", threshold = 100 }
```

Damit läuft `ultraloom run verify-until-green` in mehreren Projekten, ohne dass
eines davon eine Zeile Ablaufcode besitzt.

Erweist sich ein projektspezifischer Ablauf beim dritten Projekt als doch
allgemein, wandert er nach `flows/` und lässt eine Konfigurationszeile zurück.
Das ist Beförderung, kein Umbau.

---

## 8. Werkzeugprofile

Der Standard für einen `AgentNode` ist lesend. Schreibrechte und Shell müssen
explizit angefordert werden.

| Profil | Werkzeuge |
|---|---|
| `read_only` (Standard) | `Read`, `Grep`, `Glob` |
| `edit` | zusätzlich `Edit`, `Write` |
| `shell` | zusätzlich `Bash` |
| `mcp` | zusätzlich die konfigurierten MCP-Server |

Ein Knoten, der Coverage-Berichte deuten soll, kann dann keine Quelldatei
anfassen — nicht weil er brav ist, sondern weil das Werkzeug fehlt. Das Journal
schreibt mit, welches Profil ein Knoten hatte.

**Kein Fallback auf Werkzeugebene.** Fehlt einem Knoten ein Werkzeug, scheitert
er. Ein Knoten, der ersatzweise über `Bash` schreibt, weil `Edit` nicht erlaubt
war, hat die Sicherung ausgehebelt — und man sieht es erst im Diff.

---

## 9. Prüfwerkzeuge: `ultraloom check`

Die Prüfkette ist nicht nur ein Innenteil des Ausführers, sondern ein
öffentliches Unterkommando. Sie wird für Stufe 3 unten ohnehin gebaut; sie von
außen aufrufbar zu machen kostet fast nichts und macht sie an zwei Stellen
nutzbar — als `CodeNode` in einem Graphen und als Claude-Code-Hook in einer
interaktiven Sitzung. Damit gibt es genau eine Wahrheit darüber, was in einem
Projekt „sauber" heißt.

```
ultraloom check lint       # Rückgabewert 0 oder 1, Meldungen auf stderr
ultraloom check types
ultraloom check tests
ultraloom check coverage --threshold 100
```

Das ist kein zweiter Zweck des Projekts, sondern derselbe von zwei Seiten
aufgerufen.

### 9.1 Zwei unabhängige Achsen: Werkzeug und Ausführungsort

Ein Prüfkommando besteht aus zwei Teilen, die getrennt bestimmt werden. Das
Werkzeug kommt aus der Sprachvoreinstellung, der Ausführungsort aus dem Projekt:

```toml
# <projekt>/.ultraloom/config.toml
[exec]
prefix = "docker compose exec -T frontend"
```

Ohne diese Trennung müsste ein Projekt, das durch eine Container-Grenze prüft,
jedes Kommando vollständig ausschreiben — und hätte von den Voreinstellungen
keinen Nutzen mehr. Genau dann schreibt man wieder alles selbst, und der
Vervielfältigung ist nichts entgegengesetzt.

### 9.2 Sprachvoreinstellungen

| Erkannt an | Lint | Typen | Tests / Coverage |
|---|---|---|---|
| `pyproject.toml` | `uvx ruff check`, `uvx ruff format --check` | `uvx mypy` | `uvx coverage` |
| `package.json` | `eslint .` | `tsc --noEmit` | `vitest run --coverage` |
| `project.godot` | `uvx gdlint` | — (GDScript hat keine) | Godot-Headless-Aufruf |

Fehlt eine Fähigkeit in einer Sprache — GDScript hat keinen Typechecker —, wird
das als bekannte Einschränkung gemeldet, nicht als bestandene Prüfung.

### 9.3 Auflösung, vierstufig — erster Treffer gewinnt

1. **`.ultraloom/config.toml`** im Projekt. Explizit gesetzt schlägt alles.
2. **Prüfskripte an einem konventionellen Ort:** ausführbare Dateien
   `.ultraloom/checks/{test,lint,types,coverage}.*`. Existieren sie, werden sie
   aufgerufen statt eine eigene Kette zu erfinden. Ein Projekt, dessen Prüfungen
   schon woanders liegen — etwa space' `.claude/hooks/coverage_gate.py` —, legt
   dort einen einzeiligen Aufruf ab. Das ist Konvention über einen benannten
   Pfad, **nicht** Absuchen des Projekts nach etwas, das nach einem Prüfskript
   aussieht: Letzteres wäre Raten und fällt unter Grundsatz 4.
3. **Sprachvoreinstellung** aus 9.2, mit dem Präfix aus 9.1.
4. **Fehler.** Erkennt ultraloom nichts, bricht es ab und sagt, was es nicht
   wusste. Es rät nicht.

Erkennung nimmt Arbeit ab; Raten nähme Verlässlichkeit — der Unterschied ist
Stufe 4. Ohne Voreinstellungen kostet jedes neue Projekt erst eine
Konfigurationsdatei, bevor irgendetwas läuft, und ein Werkzeug, das vor dem
ersten Nutzen Arbeit verlangt, wird beim dritten Projekt nicht mehr benutzt.

**Ein fehlendes Werkzeug ist ein Fehler, kein Grund zum Überspringen.** Jedes
ausgelassene Prüfwerkzeug landet als solches im Journal, und ein Lauf mit
ausgelassener Prüfung erreicht den Endzustand „grün" nie.

---

## 10. Effort-Eskalation

Der einzige Fallback, der sich rechnet: ein `AgentNode` läuft auf
`effort: "low"`, ein `CodeNode` danach prüft das Ergebnis, und scheitert die
Prüfung, führt eine Kante zurück auf denselben Knoten mit `high` oder `xhigh`.
Der Normalfall bleibt billig, teuer wird nur der Zweifelsfall.

Als Muster in `flows/` mitgeliefert, aber **als sichtbare Kante im Ablauf** —
nicht als verborgene Kernmagie. Sonst weiß man beim Auswerten nicht, ob ein guter
Lauf gut war oder nur teuer.

**Kein Modell-Fallback bei Ablehnung.** Der `fallbacks`-Parameter der API deckt
Sicherheitsablehnungen ab; bei Entwicklungsarbeit an den vorgesehenen Projekten
tritt das praktisch nie auf, und Rate-Limits und Serverfehler wiederholt das SDK
selbst. Tritt es je auf, sagt es das Journal, und dann wird es gebaut.

---

## 11. Fehlerbehandlung

Drei Sorten, absichtlich getrennt:

| Sorte | Beispiel | Behandlung |
|---|---|---|
| Werkzeugfehler | Test rot, Linter klagt | Kein Fehler, sondern Daten: fließt in den Zustand, wird über Kanten behandelt |
| Knotenfehler | Ausnahme, Schema verletzt, Modell nicht erreichbar | `on_error`-Kante oder Abbruch mit wiederaufnehmbarem Stand |
| Graphfehler | Unerreichbarer Knoten, Zyklus ohne Zähler | Vor dem ersten Knoten erkannt, nicht während des Laufs |

Die Graph-Validierung hat zwei Sicherungen: unerreichbare Knoten sind ein Fehler,
und ein Zyklus ohne `max_visits` ist ein Fehler. Rückkanten sind erlaubt — die
Prüfschleife braucht sie —, aber nie unbegrenzt.

---

## 12. Bedienung

Ein angehaltener Lauf braucht eine Adresse.

| Befehl | Wirkung |
|---|---|
| `ultraloom run <flow>` | Startet; läuft bis Ende, Gate oder Fehler |
| `ultraloom show <run-id>` | Journal lesbar, mit Tokens und Dauer pro Knoten |
| `ultraloom resume <run-id> [--answer ...]` | Nach Gate oder Abbruch weiter |
| `ultraloom replay <run-id>` | Alles aus dem Journal, ohne einen Modellaufruf |
| `ultraloom check <lint\|types\|tests\|coverage>` | Eine Prüfung nach Abschnitt 9, auch außerhalb eines Laufs |

`replay` erlaubt, ein Fehlverhalten zu untersuchen, ohne es erneut zu bezahlen.
`check` ist der Einstieg für Claude-Code-Hooks (Abschnitt 14).

---

## 13. Testen

- **Attrappe statt Netz.** `model/fake.py` liefert vorgegebene Antworten. Der
  ganze Kern ist damit ohne Modellaufruf prüfbar.
- **Jede Knotenart** hat ihr Testmodul.
- **Wiederaufnahme** bekommt einen eigenen Test: Journal abschneiden, neu laufen,
  Ergebnis muss gleich sein.
- **Golden-Journal-Test** hält die Reproduzierbarkeit fest: gleicher Ablauf plus
  gleiche Attrappe muss dasselbe Journal ergeben.
- **Graph-Validierung** wird gegen kaputte Graphen getestet, nicht nur gegen
  gute.
- **Die Modulgrenze** wird getestet: `ultraloom check` läuft in einer Umgebung
  ohne installiertes Claude Agent SDK durch (Abschnitt 15.2).
- TDD, 100 % Coverage, ruff und mypy sauber — nach den Projektregeln. Python
  ≥ 3.13, Abhängigkeiten über `uv`.

---

## 14. Bestehende Hooks: Inventar und Zuordnung

Stand 2026-08-21, erhoben über alle Repositories unter `#GIT`:

| Projekt | Claude-Code-Hooks | Ereignisse | Weitere |
|---|---|---|---|
| space | 13 Dateien, 5123 Zeilen | SessionStart, PostToolUse, Stop | `.githooks/` |
| iam_backend | 5 Dateien, 1439 Zeilen | PreToolUse, PostToolUse, Stop | `docker/hooks/`, `hooks/` |
| iam_frontend | 1 Datei, 440 Zeilen | Stop | `.husky/pre-commit` |
| iam_workers | 1 Datei, 440 Zeilen | Stop | — |
| iam_wiki | — | `hooks: {}` (leer) | — |
| ultra-brain | keine | — | — |
| `~/.claude/` global | keine | — | — |

Zwei Befunde tragen Entscheidungen dieser Spec:

**`wiki_gate.py` liegt dreimal** — 476, 440 und 440 Zeilen, drei verschiedene
Hashes. Das ist keine Ähnlichkeit, sondern eine kopierte und auseinandergedriftete
Datei; welche Fassung die richtige ist, weiß niemand mehr. Das ist der stärkste
vorliegende Beleg dafür, dass Mechanik einen Ort braucht.

**iam_frontend prüft durch eine Container-Grenze** (`docker compose exec -T
frontend npx eslint .` und so weiter). Daraus folgt die Trennung von Werkzeug und
Ausführungsort in Abschnitt 9.1 — ohne sie wäre dieses Projekt von den
Voreinstellungen ausgeschlossen.

### Zuordnung

| Was | Wohin | Warum |
|---|---|---|
| Ablauf-Mechanik | ultraloom (Teilprojekt 1) | Kern |
| Qualitätsprüfungen als Werkzeug × Ort | `ultraloom check` (Abschnitt 9) | Fällt aus dem Kern fast heraus |
| OKF-Mechanik: Frontmatter, Typ→Ordner, Index, Log-Zwang | **ultra-brain** | Dort wohnt die Wiki-Schicht und das OKF-Format schon; über den geplanten MCP später auch für Agenten erreichbar |
| Vokabular: Typen, Tags, Ordner, Ausführungspräfix | Projekt | Projektwissen bleibt im Projekt |
| Verdrahtung: welcher Hook wann feuert | `~/.claude/settings.json` | Global gesetzt gilt in jedem Projekt, auch in denen, die heute keinen Hook haben |

Die Wissens-Gates gehören ausdrücklich **nicht** nach ultraloom. Ein
Agent-Harness, der OKF-Frontmatter validiert, hätte einen zweiten Zweck — und
jedes Projekt, das ihn installiert, schleppte ein fremdes Weltbild mit.

**Nicht in ultraloom gehören auch Skills.** Ein Skill ist Prompt-Wissen für eine
Sitzung mit einem Menschen darin; ein Knoten-Prompt ist Anweisung für einen
unbeaufsichtigten Lauf mit erzwungenem Ausgabeschema. Das klingt nach derselben
Sache und ist es nicht — ein Prompt, der beides bedienen muss, bedient keines
gut. Skills bleiben in `~/.claude/skills/` und `<projekt>/.claude/skills/`.

---

## 15. Veröffentlichung, Paketschnitt und Lizenz

ultraloom soll öffentlich werden — nicht zu einem Termin, aber als Ziel, das
Entscheidungen jetzt schon bindet.

### 15.1 Die Prüfkette ist der öffentliche Teil, der Harness ist optional

Ein Prüfwerkzeug, das beim Installieren ein LLM-SDK und einen API-Zugang
verlangt, wird nicht installiert — auch nicht von einem Projekt, das zunächst nur
Hooks möchte. Deshalb ein Paket mit einem Extra:

```
uvx ultraloom check lint            # Prüfung ohne jede Installation
uv add ultraloom                    # Prüfkette als Abhängigkeit
uv add "ultraloom[agent]"           # zusätzlich der Graph-Harness
```

Der Hauptfall ist die erste Zeile: ein Hook ruft `uvx ultraloom check lint` auf,
und das Projekt braucht ultraloom nirgends eingetragen — genau so, wie Abschnitt
9.2 `uvx ruff` und `uvx gdlint` aufruft. Damit zahlt sich die Extras-Trennung
doppelt aus, weil `uvx` nur das Nötige holt und das Agent SDK nie anfasst.

`ultraloom run` ohne das Extra bricht mit einer klaren Meldung ab, die zu
`uv add "ultraloom[agent]"` auffordert — nicht mit einem `ImportError`.

Ein Repo, ein Name, eine Testsuite. Eine spätere Aufspaltung in zwei Pakete
bleibt möglich, weil `checks.py` und `config.py` ohnehin getrennt liegen; die
Gegenrichtung — zwei Pakete wieder zu einem machen — wäre die unangenehmere.

Die Spannung wird nicht wegdefiniert: der Name `ultraloom` bewirbt den Harness,
während der öffentlich nützliche Teil die Prüfkette ist. Das README erklärt
deshalb die Prüfkette zuerst und den Harness als das Optionale.

### 15.2 Die Modulgrenze, und wie sie gesichert wird

Der Prüfteil — `checks.py`, `config.py` und der `check`-Zweig von `cli.py` —
importiert nichts aus `graph.py`, `runner.py`, `state.py` oder `model/`. Das
Claude Agent SDK wird ausschließlich in `model/agent_sdk.py` geladen, und dort
lokal in der Funktion: der Fall „optionale Abhängigkeit" aus den Projektregeln,
mit begründendem Kommentar.

**Ein Test führt `ultraloom check lint` in einer Umgebung ohne installiertes Agent
SDK aus.** Läuft er durch, hält die Grenze; bricht er, hat jemand einen Import an
die falsche Stelle geschrieben. Das ist der wichtigste Test dieser Spec, weil er
die Zusage „der Harness ist optional" gegen Erosion sichert — eine Zusage ohne
Test verfällt.

### 15.3 Lizenz: AGPL-3.0

Nutzung ist jedem erlaubt, privat ohne jede Auflage. Wer ultraloom weitergibt
oder als Netzwerkdienst betreibt, muss seinen Code offenlegen. Namensnennung ist
eingebaut, weil Copyright-Hinweise erhalten bleiben müssen. Echtes,
OSI-anerkanntes Open Source — Beiträge sind damit rechtlich sauber, was bei einer
Nicht-kommerziell-Lizenz nicht der Fall wäre.

Zwei Folgen, die man kennen muss:

- **Die Prüfkette wird als Kommando aufgerufen** (`ultraloom check lint` aus einem
  Hook). Das ist Ausführung, keine Verlinkung: das geprüfte Projekt wird davon
  nicht berührt, so wie ein GPL-Compiler das Kompilierte nicht ansteckt. Für den
  Teil, der öffentlich werden soll, ist Copyleft folgenlos.
- **Der Harness wird importiert.** Ein Projekt, das Abläufe gegen `ultraloom`
  schreibt und weitergegeben wird, ist betroffen. Solange der Urheber alleiniger
  Rechteinhaber ist, kann er sich selbst andere Bedingungen geben; sobald fremde
  Beiträge angenommen werden, verlangt das eine Beitragsvereinbarung. Diese
  Entscheidung fällt beim ersten Fremdbeitrag, nicht vorher.

### 15.4 Zwei Verteilwege, beide nötig

| Was | Wie verteilt | Warum dieser Weg |
|---|---|---|
| Prüflogik | Python-Paket | Wird auch von `CodeNode`s im Graphen aufgerufen, nicht nur von Hooks |
| Hook-Verdrahtung und Skills | Claude-Code-Plugin | Ein Plugin trägt Hook-Einträge und Skills; genau dafür vorgesehen |

Ein Plugin lässt sich auch nur für den eigenen Rechner installieren. Es ersetzt
damit den globalen Eintrag aus Abschnitt 14, sobald die Verdrahtung teilbar sein
soll.

### 15.5 Was die Bestandsaufnahme für die Veröffentlichung ergab

Geprüft am 2026-08-21 über alle 20 Hook-Dateien in space und den iam-Projekten:

- **Keine Geheimnisse.** Suche nach Key-, Token-, Passwort- und
  Private-Key-Mustern: kein Treffer. Der einzige Fund ist ein Kommentar in
  `iam_backend/guard_paths.py` — ein Hook, der Geheimnisse *schützt*.
- **Die projektinternen Bezüge sind flach:** Repo-Namen und Pfade (`iam_wiki`,
  `iam_backend`, `iam_frontend`, `iam_workers`), die Umgebungsvariable
  `IAM_TEST`, zweimal `Kontari` in space. Kein eingewobenes Domänenwissen.
  Extraktion ist Handarbeit, keine Archäologie.
- **Lizenzdateien fehlen** in space, ultra-brain und allen iam-Projekten. Für
  ultraloom ist sie mit dieser Spec gesetzt.
- **Nicht geprüft:** die Sichtbarkeit der GitHub-Repositories — `gh` ist auf dem
  Rechner nicht installiert. Wem der generische Anteil an Kundenarbeit gehört,
  ist keine technische Frage und hier nicht entschieden.

### 15.6 Bindende Vorgabe für die Hook-Migration

**Generischen Hook-Code neu schreiben, nicht die Historie transplantieren.** Wer
`git filter-repo` benutzt, um etwa `lint.py` samt Geschichte nach ultraloom zu
holen, nimmt jeden Commit mit — samt Projektnamen und allem, was in diesen Zeilen
je stand. Ein öffentliches Repo mit fremder Historie lässt sich nicht
nachträglich reinigen, ohne alle Hashes zu brechen. Ein Neuschrieb gegen Tests
kostet einmal Aufwand und ist danach frei von Vergangenheit.

Ebenso bindend: Repo-Namen raus, Pfade in die Konfiguration, keine
projektspezifische Umgebungsvariable im Kern. Grundsatz 3 ist damit keine
Stilregel mehr, sondern eine Anforderung mit Zähnen.

---

## 16. Reihenfolge

| Teilprojekt | Inhalt | Repo |
|---|---|---|
| 1 | **Dieser Kern**, samt `ultraloom check` | ultraloom |
| 2 | Prüfschleife bis grün — der einfachste echte Ablauf | ultraloom |
| 3 | Spec→Code→Wiki-Kreis für space | space |
| 4 | Pläne autonom abarbeiten, mit Freigabepunkten | ultraloom |
| 5 | Wissenspflege im Wiki — braucht den ultra-brain-MCP | space, ultra-brain |
| 6 | Hook-Migration: Generisches nach `ultraloom check`, Verdrahtung global | ultraloom, `~/.claude/` |
| 7 | OKF-Mechanik vereinheitlichen, `wiki_gate.py`-Drift auflösen | ultra-brain |

Teilprojekt 2 ist absichtlich der erste Ablauf: es fordert Rückkanten,
Werkzeugprofile, Prüfwerkzeug-Auflösung und Journal, aber kaum Urteilsvermögen.
Ein Fehler dort liegt am Kern, nicht am Ablauf.

Teilprojekt 6 verlangt Vorsicht: space' 5123 Zeilen Hooks **laufen heute**. Das
ist der teuerste Zustand, um etwas versehentlich zu brechen. Erster Schritt ist
deshalb eine Bestandsaufnahme Zeile für Zeile — was ist generisch, was nicht —,
nicht ein Umbau.

Teilprojekt 7 gehört in ein anderes Repo und hat dort seine eigene Reihenfolge.
Es steht hier nur, damit die Zuordnung aus Abschnitt 14 nicht verloren geht.

---

## 17. Offene Punkte

Bewusst offengelassen, weil noch kein Ablauf sie fordert:

- **Nebenläufigkeit.** Fan-out über mehrere Knoten kommt, wenn ein Ablauf es
  braucht. Bis dahin sequentiell.
- **Kosten-Obergrenze pro Lauf.** Das Journal misst die Kosten schon; eine harte
  Grenze wird erst sinnvoll, wenn echte Zahlen vorliegen.
- **Verhältnis zu Claude-Code-Hooks.** Das Agent SDK führt sie aus; ob das bei
  space' `coverage_gate.py` zu doppelter Prüfung führt, zeigt Teilprojekt 2.
