# Werkzeugauflösung — Entwurf

Stand: 2026-08-27. Status: zur Durchsicht.

## Warum

Die Presets in `ultraloom.checks` nennen ihre Werkzeuge nackt: `godot`,
`eslint`, `tsc`, `vitest`. Das setzt voraus, dass sie im PATH stehen. Für die
Python-Presets stimmt das durch `uv`/`uvx`, für die anderen nicht — ein Godot
liegt auf keiner Windows-Maschine im PATH, und ein `vitest` ohne installierte
Abhängigkeiten auch nicht.

Was heute passiert, wenn es fehlt: `subprocess.Popen` wirft `FileNotFoundError`,
der über `_run_or_report` als `error` herauskommt. Für einen Reparaturlauf ist
das die teuerste aller Antworten — er sieht eine rote Prüfung, sieht keinen
Hinweis, dass keine Quelländerung sie schließen kann, und verbrennt Runden.
`UNAVAILABLE` gibt es genau für diesen Fall bereits; es wird an dieser Stelle nur
nicht erreicht.

Das Vorbild ist `space/.claude/hooks/toolchain.py`. Sein Docstring hält den
gemessenen Fehlschlag fest: die beiden Godot-Pfade standen als absolute Pfade in
`.claude/settings.json`, und ein Maschinenwechsel machte jede Prüfung, die die
Engine braucht, still oder irreführend rot. Ein Pfad in einer Konfigurationsdatei
ist eine Behauptung über eine Maschine; eine Auflösung in Code ist eine
Behauptung über das Projekt.

Denselben Schluss zieht ultraloom für die Claude-CLI bereits: `[agent].cli_path`
plus `ULTRALOOM_CLI_PATH`, wobei die Variable die Datei schlägt. Dieser Entwurf
verallgemeinert das auf die Prüfwerkzeuge.

## Was gebaut wird

Ein Modul `ultraloom.toolchain` mit einer öffentlichen Funktion:

```python
def resolve(name: str, root: Path, env: Mapping[str, str]) -> Path | None
```

Kandidaten in dieser Reihenfolge, jeder auf Existenz geprüft statt geglaubt:

1. `ULTRALOOM_TOOL_<NAME>` — `name` großgeschrieben, `-` zu `_`. Die Maschine
   sagt, wo ihr Godot liegt.
2. `<root>/.ultraloom/tools/<name>` — der projektlokale Platz. Auf Windows
   zusätzlich mit `.exe`, `.cmd`, `.bat` in dieser Reihenfolge.
3. `shutil.which(name)` — der PATH als letzte Instanz.

`None` heißt "nirgends gefunden". Ein leerer Wert der Variablen zählt als nicht
gesetzt, damit eine Maschine sie wieder abschalten kann — dieselbe Regel wie bei
`ULTRALOOM_CLI_PATH`.

**Dieses Modul lädt nichts herunter.** Die Arbeitsteilung ist streng, wie im
Vorbild: was `.ultraloom/tools/` füllt, ist nicht ultraloom. Ein
`ultraloom tools install` wäre ein eigenes Vorhaben mit einer eigenen Frage
(woher, welche Version, wer signiert das) und gehört nicht hierher.

## Wo aufgelöst wird, und wo nicht

Nur auf `argv[0]` eines **Preset**-Kommandos. Drei Fälle bleiben ausgenommen,
jeder aus einem eigenen Grund:

**Projekteigene Kommandos aus `[verify]`** — die hat ein Mensch geschrieben und
meint sie so. Wer dort `./scripts/lint.sh` schreibt, hat den Pfad gewählt.

**Alles bei gesetztem `[exec].prefix`** — das Kommando läuft dann in einem
Container. Ein absoluter Pfad von dieser Maschine wäre dort falsch, und die
Auflösung würde aus einem funktionierenden Aufruf einen kaputten machen. Das ist
der Fall, der bei einer unbedachten Umsetzung Schaden anrichtet, und er gehört
in einen eigenen Test.

**Argumente, die nach Werkzeugen aussehen** — bei `uvx ruff check .` wird `uvx`
aufgelöst und `ruff` nicht. `ruff` ist ein Argument von uvx und auf dieser
Maschine keine ausführbare Datei.

Die Prüfskripte unter `.ultraloom/checks/` bleiben ebenfalls unberührt; sie
werden über ihren gefundenen Pfad gestartet und haben mit PATH-Auflösung nichts
zu tun.

## Was bei Misserfolg passiert

`CheckUnavailableError` mit einer Meldung, die alle drei Wege benennt:

    lint: `godot` not found. Set ULTRALOOM_TOOL_GODOT, put it in
    .ultraloom/tools/, or add it to PATH.

Über den bestehenden Pfad in `_run_or_report` wird daraus ein `CheckResult` mit
`source=UNAVAILABLE`. Damit weiß der Reparatur-Flow, was er heute nicht weiß:
dass keine Quelländerung diese Prüfung schließt.

Die Meldung nennt die Prüfart voran, weil ein Bericht mit vier roten Zeilen sonst
nicht sagt, welche davon an einer fehlenden Installation liegt.

## Architektur

`ultraloom.toolchain` importiert nur die Standardbibliothek — kein `config`, kein
`checks`. Es beantwortet eine Frage über das Dateisystem und sonst nichts. Damit
bleibt es unter der Modulgrenze, die `tests/test_module_boundary.py` prüft, und
ist ohne Konfigurationsobjekt testbar.

`ultraloom.checks` ruft es an genau einer Stelle: dort, wo aus einem `Preset` die
tatsächliche `argv` wird. Die Entscheidung, ob überhaupt aufgelöst wird
(`exec_prefix` leer? Preset und nicht Konfiguration?), fällt dort und nicht im
Toolchain-Modul — sonst müsste dieses die Konfiguration kennen.

## Tests

Gegen ein `tmp_path` als `root` und eine handgereichte `env`, ohne die echte
Umgebung anzufassen:

- Die Variable gewinnt gegen ein vorhandenes projektlokales Werkzeug.
- Eine Variable, die auf nichts zeigt, fällt durch auf den nächsten Kandidaten,
  statt den Pfad weiterzureichen. Das ist der Kern des Vorbilds und der Test, der
  die naive Umsetzung fängt.
- Eine leere Variable zählt als nicht gesetzt.
- Das projektlokale Werkzeug gewinnt gegen PATH.
- Auf Windows wird `.exe`/`.cmd`/`.bat` in fester Reihenfolge probiert; die
  Auswahl ist als reine Funktion über eine Dateiliste testbar, damit sie auf
  einer POSIX-Maschine nicht ungeprüft bleibt — dasselbe Muster wie
  `spawn_kwargs(platform)` in `process.py`.
- Nichts gefunden ergibt `None`.

In `checks`:

- Ein Preset mit unauffindbarem `argv[0]` ergibt ein `CheckResult` mit
  `source=UNAVAILABLE` und einer Meldung, die alle drei Wege nennt.
- Bei gesetztem `[exec].prefix` bleibt die `argv` unverändert, auch wenn das
  Werkzeug lokal auflösbar wäre.
- Ein Kommando aus `[verify]` bleibt unverändert.
- `uvx ruff check .` löst `uvx` auf und lässt `ruff` stehen.

## Doku

Beide READMEs: ein Abschnitt *Wo die Werkzeuge herkommen* mit der
Kandidatenordnung, dem Namensschema der Variablen und dem ausdrücklichen Satz,
dass ultraloom nichts installiert. Dazu der Hinweis, dass `[exec].prefix` die
Auflösung abschaltet — wer im Container prüft, soll nicht rätseln, warum seine
Variable nichts tut.

Kein neues Flussdiagramm: das hier ist kein Flow, sondern eine Funktion.

## Reihenfolge der Umsetzung

1. `toolchain.resolve` samt Tests, ohne Aufrufer. Danach ist die Auflösung
   fertig und niemand hängt davon ab.
2. Der Aufruf in `checks`, zusammen mit den Ausnahmen. Erst hier wird das
   Verhalten sichtbar.
3. Doku in beiden READMEs.

## Ausdrücklich nicht in diesem Vorhaben

- Installieren. Siehe oben.
- Versionsprüfung ("dein gdlint ist zu alt"). Eine eigene Frage mit eigenen
  Fehlermodi.
- Auflösung für die Claude-CLI. Die hat mit `[agent].cli_path` ihren eigenen,
  bereits begründeten Weg; die beiden zusammenzulegen hieße, eine funktionierende
  Fläche für Symmetrie umzubauen.
