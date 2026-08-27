# Prüfart `docs` — Entwurf

Stand: 2026-08-27. Status: zur Durchsicht.

## Warum

`AGENTS.md` verlangt, dass jede Dokumentationsseite zweisprachig vorliegt: die
Datei ohne Suffix ist der englische Standard, die deutsche trägt `.de.md`
daneben. Das ist mechanisch entscheidbar und wird heute von nichts geprüft. Eine
Seite, deren Übersetzung fehlt, fällt frühestens auf, wenn jemand sie sucht.

`tests/test_flow_docs.py` prüft eine benachbarte, aber andere Frage: ob das Bild
einer Flow-Seite zum Graphen passt, den das Modul baut. Er findet die
Sprachvarianten, die es gibt, und hält beide gegen den Graphen — er merkt aber
nicht, wenn eine fehlt, und er gilt nur für die gebündelten Flows dieses Repos.
Beides bleibt so; die Vollständigkeit ist eine eigene Frage.

Das Vorbild aus den Nachbarprojekten ist `wiki_gate.py`, das in drei Repos
byte-identisch liegt und per Stop-Hook erzwingt, dass die Wikipflege nicht
übersprungen wird. Sein Kriterium — "im Nachbar-Repo wurde seit Sessionstart
committet" — wird hier bewusst *nicht* übernommen: es sagt nur, dass irgendetwas
angefasst wurde, und ist zu befriedigen, ohne etwas zu dokumentieren. Die
Sprachpaar-Vollständigkeit sagt etwas Prüfbares.

Dass dieselbe Datei dreimal kopiert liegt und jedes Repo einen Drift-Test
dagegen fährt, ist im Übrigen genau das Problem, für das ultraloom die Antwort
ist.

## Was gebaut wird

Eine fünfte Prüfart `docs` mit einem **eingebauten** Prüfer statt einem externen
Kommando, konfiguriert über eine neue `[docs]`-Tabelle in
`.ultraloom/config.toml`.

Eingebaut und nicht als Preset-Kommando, weil es kein Werkzeug gibt, das diese
Frage beantwortet. Ein Preset müsste eines erfinden, und ein erfundenes Kommando
sähe aus wie eine Prüfung und wäre keine — dasselbe Argument, mit dem das
Godot-Preset auf `coverage` verzichtet.

## Schema

    [docs]
    dir      = "docs"          # Pflicht, sonst gibt es die Prüfart nicht
    variants = ["", "de"]      # Pflicht: "" ist die Datei ohne Suffix
    exclude  = ["vendor/**"]   # optional, relativ zu dir

`variants` nennt die Suffixe. `""` steht für die Datei ohne Suffix, `"de"` für
`.de.md`. Die Reihenfolge bedeutet nichts; es zählt die Menge.

Mehr als zwei Varianten sind erlaubt und kosten nichts — eine dritte Sprache ist
ein Eintrag mehr.

## Wann die Prüfart existiert

Ohne `[docs]` gibt es die Prüfart **nicht**: sie ist dann kein Teil von
`check all`, und `check docs` meldet, dass das Projekt keine `[docs]` hat.

Das ist die zentrale Entscheidung dieses Entwurfs, und sie widerspricht der
sonst geltenden Regel "eine Prüfung, die nicht aufgelöst werden kann, wird als
Fehlschlag gemeldet, nie übersprungen". Die Regel ist richtig für die vier
bestehenden Arten: jedes Projekt hat Quellcode, also auch eine sinnvolle Antwort
auf `lint`. Nicht jedes Projekt hat zweisprachige Dokumentation, und ein
`UNAVAILABLE` bei jedem `check all` in jedem Projekt würde die Meldung
entwerten, die für den echten Fall gedacht ist.

Der Präzedenzfall steht im Haus: das Godot-Preset lässt `coverage` weg, und
`kinds_for` sowie `run_kinds` gehen damit um. `docs` ist derselbe Fall, nur von
der Konfiguration her statt von der Sprache.

`KINDS` in `checks.py` wird um `"docs"` erweitert — die Konstante sagt, welche
Arten es *gibt*. Was ein konkretes Projekt läuft, entscheidet sich davon
getrennt, und die Stelle dafür ist zu benennen, sonst läuft `docs` doch überall:
`run_all` baut seine Liste heute als `run_kinds(KINDS, config)`. Sie wird zu
`run_kinds(available(config), config)`, wobei `available` aus `KINDS` das
herausnimmt, was dieses Projekt nicht hat. Heute ist das genau `docs` ohne
`[docs]`; die Funktion ist trotzdem der richtige Ort, weil sie die Frage stellt,
die das Godot-Preset schon implizit beantwortet.

`_CHECK_KINDS` in `config.py` (die Liste, gegen die `kinds_for` einen Namen
prüft) bekommt `"docs"` ebenfalls. Sie beantwortet eine dritte Frage — ist das
ein Name, den es gibt — und muss `check docs` durchlassen, damit die Meldung
über die fehlende `[docs]`-Tabelle überhaupt erreicht wird statt eines
"unknown check". Dass beide Konstanten dasselbe aufzählen und getrennt gepflegt
werden, ist bestehende Doppelung und nicht Gegenstand dieses Entwurfs; ein Test,
der sie gegeneinander hält, ist billig und gehört dazu.

## Der Prüfer

1. Listet rekursiv alle `*.md` unter `dir`.
2. Wirft weg, was in einem Pfadsegment mit führendem Punkt liegt (siehe unten).
3. Wirft weg, was ein `exclude`-Muster trifft.
4. Gruppiert nach Stamm: `x.md` und `x.de.md` gehören zu `x`.
5. Meldet jede Gruppe, der eine Variante fehlt.

Der Bericht nennt die **fehlende Datei**, nicht die Gruppe:

    docs/flows/policy.de.md is missing (docs/flows/policy.md exists)

Ein Reparierer soll sie anlegen können, ohne sich den Namen herzuleiten. Das ist
dieselbe Überlegung wie beim `-m` im Coverage-Preset: den Fund benennen, statt
die Fundstelle zu umschreiben.

Wie jede Prüfart läuft der Prüfer vollständig durch und meldet alle Funde, nicht
nur den ersten — eine halbe Liste kostet eine weitere bezahlte Runde durch das
Modell.

### Punkt-Segmente

Jedes Pfadsegment mit führendem Punkt fällt heraus, auf jeder Ebene, Dateien wie
Verzeichnisse. Der führende Punkt ist die Konvention für "Werkzeugdaten, kein
Inhalt", und unter einem Doku-Verzeichnis trifft das ausnahmslos:
`.superpowers/`, `.obsidian/`, `.vitepress/`, `.github/`.

Das ist eine Voreinstellung, keine Vorbelegung von `exclude` — sonst verschwände
sie, sobald jemand `exclude` für etwas anderes setzt.

Der Nebeneffekt ist das beste Argument dafür: ultraloom selbst braucht dann
keinen einzigen `exclude`-Eintrag. `docs/.superpowers/**` — die Arbeitspapiere,
die laut `AGENTS.md` ausdrücklich nicht übersetzt werden — fällt schon durch die
Konvention. Eine Voreinstellung, die den bekannten Fall trifft, ohne dass jemand
sie schreibt, ist richtig gewählt.

**Bewusst offen**: wie man die Punkt-Regel wieder aufhebt. Ein
`include`-Schlüssel wäre die naheliegende Erweiterung, kostet heute aber Schema
und Tests für einen Fall, den niemand hat, und lässt sich später ohne Bruch
nachrüsten. Das steht hier als Entscheidung, nicht als Versäumnis.

## Stellung in der Kette

`docs` liest von keiner anderen Prüfart und keine liest von ihm: eine eigene
Stufe braucht es nicht, es läuft in Stufe 0 neben `lint`. `[verify.after]` kann
es wie jede andere Art umhängen.

Der Prüfer startet keinen Prozess. Damit zählt er nicht gegen `max_parallel`,
und `[exec].prefix` betrifft ihn nicht — beides ist in der Umsetzung sichtbar zu
machen, weil die bestehende Maschinerie von einem Kommando ausgeht.

## Tests

- Ein Verzeichnis mit `a.md` und `a.de.md` ist grün.
- Fehlt `a.de.md`, ist es rot, und die Meldung nennt genau diesen Pfad.
- Fehlt umgekehrt `a.md` bei vorhandenem `a.de.md`, ebenso.
- Zwei Funde ergeben zwei Zeilen, nicht eine.
- `docs/.superpowers/plan.md` wird ignoriert, ohne dass `exclude` gesetzt ist.
- `docs/x/.notes/a.md` ebenso — die Regel gilt auf jeder Ebene, nicht nur oben.
- `exclude = ["vendor/**"]` wirkt zusätzlich zur Punkt-Regel.
- Ohne `[docs]` ist `docs` nicht Teil von `check all`, und `check docs` meldet
  das verständlich.
- Eine dritte Variante wird geprüft wie die zweite.
- Ein leeres `variants` oder ein fehlendes `dir` ist `ConfigError` beim Lesen.
- Ein `dir`, das auf nichts zeigt, ist ein Fehlschlag der Prüfart und kein
  stilles Grün — sonst schaltet ein Tippfehler die Prüfung ab.

Dazu die eigene Anwendung: ultraloom konfiguriert `[docs]` in seiner
`.ultraloom/config.toml`, und `check all` prüft von da an die eigenen
Sprachpaare mit.

## Doku

Beide READMEs: die Prüfart in der Übersicht, das Schema mit den drei Schlüsseln,
die Punkt-Regel samt Begründung, und der Satz, dass es die Prüfart ohne `[docs]`
nicht gibt. Die Stufentabelle bekommt eine Spalte oder eine Fußnote.

`AGENTS.md` bekommt einen Satz: die Sprachregel wird jetzt geprüft, und wo.

## Reihenfolge der Umsetzung

1. Der Prüfer als reine Funktion über eine Dateiliste — Gruppierung, Punkt-Regel,
   Ausschlüsse, Bericht. Ohne Konfiguration und ohne Dateisystem testbar.
2. `[docs]` im Schema, samt Fehlern beim Lesen.
3. Einhängen in `KINDS`, `kinds_for` und `run_kinds`, inklusive des Falls "keine
   `[docs]`".
4. Die eigene Konfiguration in ultralooms `.ultraloom/config.toml`.
5. Doku in beiden READMEs und in `AGENTS.md`.

## Ausdrücklich nicht in diesem Vorhaben

- Inhaltliche Prüfung der Übersetzung. Ob die deutsche Seite dasselbe sagt wie
  die englische, entscheidet kein Programm.
- Der Rückverweis zwischen den Varianten ("Each variant links to the other under
  its heading", `AGENTS.md`). Prüfbar, aber eine zweite Regel mit eigenen
  Fehlalarmen — ein eigener Schritt, wenn die Vollständigkeit steht.
- Kopplungsregeln zwischen `src/` und `docs/`. Das war die zweite Option in der
  Vorüberlegung und wurde verworfen: "irgendetwas unter `docs/` wurde angefasst"
  ist zu befriedigen, ohne etwas zu dokumentieren.
- Ein Stop-Hook. `docs` ist eine Prüfart und läuft in der bestehenden Kette; ein
  eigener Hook wäre eine zweite Stelle mit derselben Zuständigkeit.
