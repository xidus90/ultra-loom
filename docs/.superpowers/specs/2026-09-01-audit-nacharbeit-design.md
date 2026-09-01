# Audit-Nacharbeit: Gates, Multi-Marker und Aufräumen

Stand 2026-09-01. Grundlage ist ein Vollaudit des Repositoriums (Go, Python,
Sprach- und Framework-Abdeckung, Repo-Hygiene). Alle hier genannten Befunde
sind am laufenden Baum belegt, nicht vermutet.

Ausgangslage: `go test ./...` grün, `uv run pytest` 911 passed. Die Fehler
unten sind also keine roten Tests, sondern Stellen, an denen kein Test hinsieht.

## Grundsatz

Drei Pakete, in dieser Reihenfolge. Paket 1 zuerst, weil es die Gates
repariert, an denen die Arbeit an Paket 2 und 3 gemessen wird: solange
`ulinit check coverage` ohne `--summary` grün meldet und `.gitignore` neue
Dateien unter `internal/coverage/` verschluckt, ist jedes Grün aus den späteren
Paketen unbelegt.

Für jeden Befund gilt TDD im engen Sinn: zuerst ein Test, der den heutigen
Zustand rot zeigt. Diese Fehler existieren, weil kein Test sie deckte -- ein
Fix ohne vorangehenden roten Test wiederholt genau diesen Fehler.

## Paket 1 -- Gates, die nicht greifen

### 1.1 `ulinit check coverage` ohne `--summary` ist immer grün

`cmd/init/check.go:64`. Der gesamte Auswertungsblock hängt an
`if *summary != ""`; fehlt das Flag, fällt die Funktion auf `return 0` durch,
ohne zu messen und ohne etwas zu sagen.

`docs/.superpowers/plans/2026-08-29-ecosystem-integration-and-native-tooling.md:571`
schlägt genau die Form ohne `--summary` vor:

    report    = "ulinit check coverage --go-floor=98"

Das ist der Fehler, gegen den `internal/coverage/check.go` im eigenen
Paketkommentar antritt.

**Soll:** Ein leeres `--summary` ist ein Fehler, kein Erfolg. Exit 1 mit einer
Meldung, die sagt, welches Flag fehlt.

### 1.2 `.gitignore` verschluckt Quelltext

`.gitignore:42` und `:44`. Die Muster `*cov*` und `cover*` sind unverankert und
greifen auf jeden Basename im Baum:

    .gitignore:44:cover*  hooks/coverage-check.py
    .gitignore:44:cover*  internal/coverage/check.go
    .gitignore:44:cover*  internal/verify/coverage.go
    .gitignore:42:*cov*   tests/test_discovery.py

Getrackte Dateien rettet nur der Index. Eine *neue* Datei unter
`internal/coverage/` wäre für `git status` und `git add` unsichtbar. Dass die
Falle scharf ist, zeigt die Historie in beide Richtungen: `cmd/guard/guard_cov`
(3c48817) und `internal/verify/cover` (5323f7d) wurden je einmal versehentlich
committet und wieder entfernt.

Zeile 43 `$*` ist zusätzlich wirkungslos.

**Soll:** Wurzelverankerte Regeln für die tatsächlichen Artefakte --
`/coverage`, `/coverage.out`, `/cover`, `/guard_cover`, `/cov_*.out`,
`/.coverage` -- dieselbe Disziplin, die die Binärregeln darüber schon haben.
Das wirkungslose Muster entfällt, `*.out` wird auf die Wurzel verankert.

**Gegenprobe im Test:** `git check-ignore` über die drei Quelldateien oben darf
nichts mehr melden.

### 1.3 Die Django-Migrationsregel feuert nie

`cmd/guard/guard.go:88`. `matchGlob` gibt für jedes Muster mit Schrägstrich
direkt `filepath.Match(pattern, path)` zurück, und dort überschreitet `*`
keinen Separator. Nachgemessen:

    migrations/0001_init.py        true
    myapp/migrations/0001_init.py  false
    src/app/migrations/0002_x.py   false

Django legt Migrationen ausschließlich unter `<app>/migrations/` ab. Der
Schutz, den der Interviewtext ausdrücklich verspricht, greift damit in keinem
realen Django-Projekt.

**Soll:** `matchGlob` lernt `**` an beliebiger Stelle, nicht nur als Suffix
`/**`. `migrationGlob` wird zu `**/migrations/[0-9][0-9][0-9][0-9]_*.py`.

Bewusst **kein** implizites `**/`-Präfix: eine Policy-Regel, die stillschweigend
mehr schützt als sie sagt, ist dieselbe Klasse Überraschung wie eine, die
weniger schützt. Bestehende Muster -- `.ultraloom/runs/*`, `.ultraloom/hooks/*`
-- ändern ihr Verhalten dadurch nicht.

`migrationGlob` steht heute doppelt im Baum
(`internal/interview/interview.go:25` und `cmd/init/run.go:522`) und wird zu
einer Konstanten zusammengezogen.

**Migrationshinweis:** Projekte, die das alte Muster bereits in ihrer
`policy.toml` stehen haben, behalten eine Regel, die nur in der Wurzel greift.
Das ist zu dokumentieren.

### 1.4 Ein ungültiger Regex deaktiviert eine Policy-Regel lautlos

`cmd/guard/guard.go:165` und `:172`. `matched, _ := regexp.MatchString(...)`
verwirft den Compile-Fehler; `matched` ist dann `false` und der Guard antwortet
`ExitOK`. Ein Tippfehler in einer Policy-Zeile ist ununterscheidbar von
"erlaubt" -- betroffen wären die Regeln gegen `git push` und `pip install`.

**Soll:** Regexe beim Laden der Policy einmal mit `regexp.Compile` prüfen. Ein
ungültiger Ausdruck endet mit `ExitDenied` und einer Meldung, die die Regel
benennt -- wie der TOML-Parsefehler daneben. Das erledigt zugleich das
wiederholte Kompilieren bei jedem Aufruf.

### 1.5 `KeyError` statt Fehlermeldung bei C++

`src/ultraloom/checks.py:264`. `_LANGUAGE_NAMES` (Zeile 147) kennt drei Marker,
`PRESETS` hat vier. Reproduziert:

    ultraloom check types --root <cmake-projekt>
    KeyError: 'CMakeLists.txt'

Der generische `except Exception` in `_run_or_report` macht daraus
`source="error"` statt `UNAVAILABLE`. Die sorgfältig formulierte Meldung "a
known limitation, not a passed check" erreicht niemanden.

**Soll:** `_LANGUAGE_NAMES` deckt jeden Schlüssel aus `PRESETS` ab. Ein Test
hält die beiden Tabellen dauerhaft deckungsgleich, damit ein künftiges Preset
den Fehler nicht wiederholt. Fällt mit Paket 2 zusammen, das zwei weitere
Marker hinzufügt.

### 1.6 Stop-Hook zeigt auf ein nicht existierendes Verzeichnis

`.claude/settings.json:70` verweist auf
`${CLAUDE_PROJECT_DIR}/.ultraloom/vendor/ultraloom`; das Verzeichnis existiert
nicht, und `.ultraloom/installed.toml` bestätigt mit leerem `[vendor] ref`, dass
nie vendored wurde. Drei weitere Hooks wurden bereits auf die Projektwurzel
umgestellt, dieser blieb stehen.

**Soll:** Analog zu den drei anderen auf `${CLAUDE_PROJECT_DIR}`.

## Paket 2 -- Multi-Marker, Go- und Rust-Preset

### 2.1 Das Problem

`detect` und `checks.py` teilen keinen Datensatz. Die Go-Seite erkennt 25
Stacks über 40 Signale; die Python-Seite entscheidet über eine eigene,
vierzeilige Markerliste. Die erkannten Stacks fließen nur nach `answers.toml`
und werden nirgends in einen Check umgesetzt -- `detect` ist heute im
Wesentlichen ein Dokumentationsgenerator.

Zwei Folgen wiegen schwer:

**`go` und `rust` haben `tooling`-Einträge, aber kein Preset.** In einem reinen
Go-Repo liefert `_marker()` `None` und *jeder* Check scheitert. Das trifft
ultraloom selbst: die Go-Hälfte läuft nur durch Gates, weil
`.ultraloom/config.toml` sie von Hand als `commands`-Liste nachträgt.

**`_marker()` gibt genau einen Marker zurück** -- den ersten Treffer in
Dict-Reihenfolge. Ein Python-Backend mit `package.json`-Frontend bekommt nur
die Python-Kette, und nichts sagt es.

### 2.2 Die Trennung: primärer gegen beitragende Marker

`Command.argvs` ist bereits eine Sequenz gleichrangiger Kommandos, die alle
laufen, auch nach einem roten (`checks.py:162`). Der Mechanismus für
Multi-Marker existiert also; er wird nur nicht gefüllt. `CheckResult` und die
Ausgabe bleiben unverändert.

`_marker(root)` wird zu `_markers(root) -> tuple[str, ...]` und liefert alle
Treffer in `PRESETS`-Reihenfolge.

Der **erste** ist der primäre und verhält sich exakt wie der heutige
Rückgabewert. Er allein speist:

- `_predecessor_of` -- die Reihenfolgekante `coverage after test`
- `_measuring_state` und `_has_dependant` -- den Messschritt
- `_stages` und `_blocker` -- die Stufenbildung
- `_unready` -- die Godot-Importvorbedingung

Damit ändert sich für jedes bestehende Projekt an Kanten, Messschritt und
Coverage **nichts**. Das ist die Garantie dieser Variante.

Die übrigen Marker steuern in `resolve_check` ausschließlich ihr `Preset.argv`
zu den `argvs` von `lint`, `types` und `test` bei -- nicht `measuring`, nicht
`measure`, nicht `after`. Diese drei Felder gehören zum primären Marker, und
genau dort verläuft die Grenze dieses Vorhabens.

### 2.3 Fehlende Werkzeuge

`_located` (`checks.py:290`) wirft heute `CheckUnavailableError`, sobald das
Werkzeug eines Presets nicht auf PATH liegt, und `unavailable` zählt laut
`_blocker` als rot. Unverändert übernommen hieße das: ein Python-Repo mit einer
einzigen `install.sh` wäre ohne installiertes `shellcheck` rot. Auch dieses
Repo wäre betroffen.

**Soll:** `_located` filtert den einzelnen argv, statt den ganzen Check zu
werfen. Ein beitragender Stack ohne Werkzeug wird übersprungen und in
`Command.warning` benannt -- der Bericht sagt ausdrücklich, was nicht geprüft
wurde.

Bleibt am Ende **kein** argv übrig, greift die bestehende
`__post_init__`-Invariante und der Check ist `UNAVAILABLE`. Nie ein Pass über
null Kommandos.

Der primäre Marker behält das heutige Verhalten: fehlt sein Werkzeug, ist der
Check rot.

### 2.4 Neue Presets

Ans **Ende** der `PRESETS`-Reihenfolge, damit kein bestehendes Projekt seinen
primären Marker wechselt.

| Marker | lint | types | test |
|---|---|---|---|
| `go.mod` | `go vet ./...` | `go build ./...` | `go test ./...` |
| `Cargo.toml` | `cargo clippy --all-targets -- -D warnings` | `cargo check --all-targets` | `cargo test` |

Bei Go übernimmt der Compiler den Typecheck; ein eigener Typechecker existiert
nicht und wird nicht erfunden.

### 2.5 Zwei bewusste Lücken

Beide nach dem Vorbild der Godot-Coverage begründet statt geraten:

**Go-Coverage** geht nicht durch die Preset-Kette. `go tool cover -func` braucht
einen Messschritt, und der bleibt dem primären Marker vorbehalten. Dieses Repo
behält dafür seine `report`-Zeile in `.ultraloom/config.toml`.

**`gofmt`** kann kein Preset-Lint sein: `gofmt -l` gibt die nicht formatierten
Dateien aus und exitet dabei **0**. Ohne Wrapper ist es nicht gate-fähig.

### 2.6 Randfall

Ist Godot nicht der primäre Marker, greift die Importvorbedingung in `_unready`
nicht mehr. Im Plan gesondert zu behandeln.

## Paket 3 -- Aufräumen

### 3.1 Toter Code

Jede Behauptung per grep gegen `src/`, `tests/`, `cmd/` und `internal/` geprüft:

- `internal/render/render.go:24` -- `var targets` unbenutzt; `Render` baut ab
  Zeile 85 eine eigene lokale Liste mit vier weiteren Einträgen.
- `internal/detect/cpp_tests.go:10` -- `DetectCPPTestFramework`, einziger
  Aufrufer ist der eigene Test. Nimmt zudem als einzige Funktion im Paket
  `os.ReadFile` statt `fs.FS` und bricht den Testbarkeitsvertrag des
  Paketkommentars.
- `internal/tooling/tooling.go:14` -- `ToolSpec.Description`: 14 Zuweisungen,
  null Leser.
- `src/ultraloom/hooks/__pycache__/post_edit.pyc` -- verwaist; der Subbefehl
  existiert nicht mehr.

### 3.2 `render.Render` gibt einen Fehler zurück, der nie kommt

`internal/render/render.go:79`. `one()` (Zeile 214) verwirft den
Ausführungsfehler mit `_ = parsed.Execute(...)`, also ist der Rückgabewert
immer `nil` und jede Fehlerbehandlung darum herum unerreichbar.

Der Kommentar auf `cmd/init/run.go:121` behauptet das Gegenteil: "Handled
anyway: a swallowed template error would write half a configuration."

**Soll:** `one()` reicht den Fehler zurück, `Render` gibt ihn durch. Damit wird
der Kommentar von einer Lüge zur Wahrheit, statt gestrichen zu werden.

### 3.3 Kommentare, die gegen den Code lügen

- `pyproject.toml:64` und `.ultraloom/config.toml:14` -- beide beschreiben
  `hooks/gofmt-check.py` bzw. `tests/hooks/test_gofmt_check.py`; keine der
  beiden Dateien existiert. Die Lane ist längst `./ulinit check gofmt`.
- `cmd/guard/status.go:110` -- "Size Limit in <5ms": es gibt in `cmd/guard/`
  keine Größenprüfung.
- `cmd/guard/status.go:184` -- "non-code files: instant 0ms exit": gilt nur für
  `explicitIgnoredExtensions`; alles ohne bekannte Endung löst den Vollsweep
  aus.
- `cmd/init/run.go:48` gegen `:320` -- zwei Definitionen desselben
  pre-commit-Hooks, bereits mit abweichendem Kommentartext auseinandergelaufen.
- `src/ultraloom/hooks/subagent_stop.py:137` -- "through `process.run` like
  every other child": `worktree.py:156` und `hooks/coverage-check.py:60` tun
  das nicht.
- `src/ultraloom/process.py:301` -- `_decode` heißt `_text` (Zeile 830).
- `src/ultraloom/process.py:299` -- `PYTHONIOENCODING` erreicht nur
  Python-Kinder, nicht `ruff`, `eslint` oder `go`; der Docstring begründet die
  Variable generisch.
- `src/ultraloom/hooks/stop.py:123` -- rät, `.claude/.no-verify` zu entfernen,
  in einem Zweig, der nur läuft, wenn die Datei nicht existiert.
- `src/ultraloom/hooks/subagent_start.py:271` und `subagent_stop.py:375` --
  melden `agent_id`, wenn die `session_id` fehlt.

### 3.4 AGENTS.md-Verstoß: deutsche Meldungen im Quelltext

AGENTS.md verlangt Englisch für alles, was nicht Prosa ist, Fehlermeldungen
eingeschlossen. Drei Stellen verstoßen dagegen:

- `src/ultraloom/checks.py:346`
- `src/ultraloom/checks.py:696`
- `src/ultraloom/flows/verify_until_green.py:213`

Die deutschen Wortlisten in `src/ultraloom/commit/language.py` bleiben: das sind
Daten der Spracherkennung, keine Meldungen.

### 3.5 `hooks/coverage-check.py`

Da Paket 2 in der gewählten Variante die Coverage-Lane nicht anfasst, bleibt
dieser Wrapper bestehen und wird repariert:

- Zeile 60: `subprocess.run(text=True)` ohne `encoding` -- dekodiert mit
  `locale.getencoding()`, hier `cp1252`. Für die in cp1252 undefinierten Bytes
  stirbt der Leser-Thread still, `stdout` kommt als `None` zurück, und `tail()`
  (Zeile 103) macht daraus einen `TypeError`. Der Gate endet mit einem Traceback
  statt mit einem Verdikt.
- Zeile 60: kein `timeout` -- ein hängendes `go test ./...` blockiert den
  Precommit unbegrenzt.
- Zeile 74 und 89: `coverage report` und `go tool cover` sind nicht gegen
  `OSError` abgesichert, nur der Messschritt in Zeile 66 ist es.

**Soll:** `encoding="utf-8"`, `errors="replace"`, ein `timeout`, und alle drei
Aufrufe unter dieselbe `OSError`-Behandlung. Alternativ `ultraloom.process.run`
verwenden, wie `commit/calibrate.py:97` es tut.

### 3.6 Repositorium

- `.gitattributes` -- nur `*.go` und die Render-Templates sind auf LF gepinnt.
  Im frischen Klon kommen `.githooks/pre-commit` und `scripts/install.sh` mit
  CRLF; unter WSL ist das ein `bad interpreter`. Ergänzen um
  `.githooks/* text eol=lf`, `*.sh text eol=lf`, `hooks/*.py text eol=lf`.
- `./ulinit` -- `.githooks/commit-msg` und `.ultraloom/config.toml:56` rufen ein
  gitignoriertes Binary im Wurzelverzeichnis, das `scripts/install.*` nie
  dorthin legen. Auf den installierten Shim aus `$GOBIN` umstellen, mit
  verständlichem Abbruch samt Verweis auf `scripts/install.*`, wenn er fehlt.
- `go.mod` -- `go 1.22` bei installiertem `go1.27`; `x/sys` und `x/term` auf
  `v0.18.0` (02/2024). Direktive heben, Abhängigkeiten aktualisieren.
- `.ultraloom/installed.toml` -- listet `GEMINI.md`, die nie existierte.
  Entweder erzeugen (wie `CLAUDE.md` ein Verweis auf `AGENTS.md`) oder den
  Eintrag streichen.
- Zwei leere Verzeichnisreste entfernen: `.worktrees/bench-ultraloom` und
  `.claude/worktrees/teilprojekt-1-kern-tasks-1-8-88653d`. Beide antworten auf
  `git rev-parse --show-toplevel` mit dem Hauptcheckout, sind also keine
  Worktrees.

## Ausdrücklich nicht in diesem Vorhaben

Zwei Punkte bleiben draußen, weil sie eine Entscheidung des Nutzers verlangen
und keine technische:

- **`.worktrees/installer-kern`**, 472 MB, davon 446 MB `.venv` (das
  Haupt-`.venv` ist 14 MB). Offen, ob `feat/installer-kern` gemergt ist.
- **Auslagerung der READMEs.** Von 1235 Zeilen sind rund 700 reiner
  Referenzstoff; für zwei der drei Blöcke existiert unter `docs/` bereits ein
  Ort. Die READMEs sind entgegen der ersten Vermutung strukturell synchron
  (beide exakt 67 Überschriften H1--H3 in identischer Reihenfolge).

Ebenfalls draußen, als eigene Vorhaben vorgemerkt:

- **Weitere Sprachen und Frameworks.** Nach Go und Rust sind Shell
  (`shellcheck -f gcc`, `shfmt -d`), die Poetry/uv-Unterscheidung, Deno,
  Markdown und GitHub Actions sowie C#/.NET die nächsten nach Nutzen je
  Aufwand. GitHub Actions verlangt zusätzlich eine Ausnahme für `.github` in
  `searchAreas` (`internal/detect/detect.go:145` überspringt alle
  Punktverzeichnisse).
- **Multi-Marker für die Coverage-Lane.** Löst "Two languages, one slot"
  (`.ultraloom/config.toml:64`) wirklich auf und macht `hooks/coverage-check.py`
  entbehrlich. Verlangt `Command.measure` als Sequenz sowie `_predecessor_of`
  und `_measuring_state` pro Marker.
- **Weitere Korrektheitsbefunde** aus dem Audit, die keines der drei Pakete
  berührt: `getWorkspaceDir` mit absoluten Windows-Pfaden
  (`cmd/guard/post_edit.go:160`), ungequotete Pfade in der Shell-Zeile
  (`:203` bis `:272`), `--root` vor dem Hook-Namen (`src/ultraloom/cli.py:175`),
  `cp1252`-Ausgabe (`cli.py:247`), der uv-Installationsbefehl mit Pipe ohne
  Shell (`internal/tooling/tooling.go:19`), `MultiEdit` im Matcher
  (`cmd/guard/guard.go:134`), `--help` mit Exit 1 (`cmd/guard/main.go:39`),
  `clip(limit=1)` (`flows/verify_until_green.py:65`), der Absolutpfad in
  `.agents/hooks.json`.

## Prüfung

Jeder Befund bekommt einen Test, der vor dem Fix rot ist. Beide Suiten bleiben
grün, die Coverage-Schwellen unverändert: `fail_under = 100` für Python, 98.0
für Go.

Besonderes Augenmerk auf die Stellen, an denen der Fehler gerade darin bestand,
dass ein Test fehlte:

- 1.1 -- ein Aufruf ohne `--summary` muss rot sein.
- 1.2 -- `git check-ignore` über die drei Quelldateien muss leer bleiben.
- 1.3 -- `matchGlob` gegen Pfade in Unterverzeichnissen.
- 1.5 -- `_LANGUAGE_NAMES` und `PRESETS` deckungsgleich.
- 2.3 -- ein beitragender Stack ohne Werkzeug: grün mit Warnung; kein argv
  übrig: `UNAVAILABLE`.

Für 3.6 (`.gitattributes`) ist die Gegenprobe ein frischer Klon in einem
Wegwerfverzeichnis mit `git ls-files --eol`.

## Ablage und Ablauf

Plan nach `docs/.superpowers/plans/`. Umsetzung subagentengetrieben, ein
Subagent je Aufgabe, Berichte werden selbst nachgeprüft -- insbesondere per
`git ls-remote origin <branch>`, nicht anhand des Berichts. Kein Push ohne
ausdrückliche Freigabe.
