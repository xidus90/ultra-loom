# Hooks in Go, für drei Höste

**Datum:** 2026-09-10
**Stand:** entworfen, nicht umgesetzt

## Ziel

Kein Hook dieses Projekts läuft mehr über Python. Die vier Ereignisse, die
heute `uv run --project … ultraloom hook …` aufrufen, werden Unterbefehle von
`ulguard`, und sie funktionieren auf Claude Code, auf Antigravity (Gemini) und
— über eine benannte, noch leere Naht — auf Codex (ChatGPT).

Python verschwindet damit aus dem Hook-Pfad, nicht aus dem Projekt: der
Agent-Flow `flows/verify_until_green.py` und `model/*` hängen am
`claude-agent-sdk==0.2.143` und bleiben, ebenso der Einsprung
`[project.scripts] ultraloom` in `pyproject.toml`, den sie brauchen. Auch die
Coverage-Lane rechnet weiter mit `uv run coverage` als Kindprozess. „Go" heißt
hier: die Entscheidung liegt in Go. Nicht: auf der Maschine ist kein Python.

## Ausgangslage, vermessen

Vier von sechs Hook-Ereignissen laufen über Python (`.claude/settings.json`),
zwei über Go (`ulguard`). Der Abhängigkeitsschluss der vier:

| Python-Modul | LOC | Testzeilen |
|---|---|---|
| `hooks/` (payload, state, session_start, subagent_start, subagent_stop, stop, cli) | 604 | 576+ |
| `checks.py` | 844 | 1455 |
| `process.py` | 848 | 846 |
| `config.py` | 448 | 837 |
| `worktree.py` | 249 | 404 |
| `journal.py`, `gate.py`, `state.py` | 213 | 593 |
| `hooks/coverage-check.py` | 129 | 222 |

Rund 3.300 Zeilen Produktivcode und knapp 5.000 Zeilen Tests. Die Tests sind
der Kostentreiber, nicht der Code.

Drei Vermutungen wurden vor dem Entwurf widerlegt und sind hier festgehalten,
damit sie nicht wiederkehren:

- `internal/verify` ist **kein** Port des Runners, sondern 191 Zeilen Helfer
  (Coverage-Parsing, gofmt).
- `internal/coverage/check.go` portiert `hooks/coverage-check.py` **nicht**. Es
  beantwortet für `ulinit`, *ob* ein Projekt eine Schwelle erzwingt; das Skript
  *führt* die Lane aus. Ähnlicher Name, zwei Aufgaben.
- `cmd/guard/post_edit.go:45` startet Kinder als schlichtes
  `exec.Command("cmd","/c",…)` ohne eigene Zeitgrenze. Für ein 300-Sekunden-Gate
  mit hängenden Werkzeugketten ist das keine Grundlage; `internal/child` ist neu
  zu schreiben.

Ebenfalls vermessen: `internal/mirrorcfg` liest nur `[worktree]` und sagt im
Paketkommentar, jede andere Tabelle „belongs to the Python side". Dieser Satz
wird durch `internal/ulconfig` falsch und muss mit.

## Hostmatrix

Belegt aus `antigravity/0.24.0/docs/MIGRATION.md:133-142`: Antigravity feuert
`PreToolUse`, `PostToolUse`, `PreInvocation` (Claudes `UserPromptSubmit`) und
`Stop`. `SessionStart`, `SessionEnd`, `PreCompact`, `Notification` und
`SubagentStop` **fallen weg** — der Host hat sie nicht.

| ultraloom-Hook | Claude Code | Antigravity | Codex |
|---|---|---|---|
| Schreibschranke | `PreToolUse` | `PreToolUse` | Naht |
| Nach-Bearbeitung | `PostToolUse` | `PostToolUse` | Naht |
| `session-start` | `SessionStart` | `PreInvocation` + Sitzungsmarke | Naht |
| `subagent-start` | `SubagentStart` | `PreToolUse`, Matcher `invoke_subagent` | Naht |
| `subagent-stop` | `SubagentStop` | `PostToolUse`, Matcher `invoke_subagent` | Naht |
| `stop` (Gate) | `Stop` | `Stop`, **flache** Liste | Naht |

Die Subagent-Ereignisse sind auf Antigravity verlustfrei nachbaubar, weil
`invoke_subagent` dort ein Werkzeug ist: ein Matcher darauf in Pre- und
PostToolUse liefert Start und Ende. `session-start` hat keinen Auslöser; es
wird über `PreInvocation` plus einer Sitzungsmarke im Zustandsverzeichnis
nachgebaut — einmal je Sitzung melden, danach nur bei Änderung des
Gate-Zustands.

Die flache Liste bei `Stop` ist kein Detail: Antigravity nimmt dort kein
`{matcher, hooks}`, Claude schon. `ulinit` braucht deshalb einen zweiten
Schreiber für `.agents/hooks.json` neben dem für `.claude/settings.json`.

### Codex: was belegt ist und was nicht

Codex ist auf der Entwicklungsmaschine nicht installiert (`which codex` leer,
kein `~/.codex`). Belegt ist allein
`superpowers/6.3.0/docs/porting-to-a-new-harness.md:240-243, 788`: Codex hat
einen `hooks/hooks.json`-Mechanismus, „runs no session-start hook", und das
Superpowers-Manifest erklärt `hooks` absichtlich leer, um die Erkennung zu
unterdrücken. Welche Ereignisse Codex feuert und in welcher Form, ist von hier
nicht nachrechenbar.

Dieselbe Doku warnt vor genau der naheliegenden Verwechslung: „A hook *system*
is not a session-start *event*." Ein Host führte nur Pre/Post-Tool und Stop,
während die Zeichenkette `SessionStart` in seinem Binary Telemetrie war.

Der Codex-Adapter wird deshalb als Naht gebaut: Vertrag dokumentiert, ein
einziger Test, der belegt, dass ein unbekannter Host **geschlossen** fällt
(Exit 2). Kein Code, der aussieht, als würde er laufen.

### Zwei ungemessene Punkte, Stufe 0

Bevor Code darauf baut, wird gemessen:

1. **Liest Antigravity die JSON-Hülle auf stdout, oder zählt nur der
   Exit-Code?** ultra-brain hat das am 2026-09-06 gemessen und in
   `hooks/guard.sh` festgehalten: die deny-Hülle allein wurde nicht gelesen,
   eine Probedatei landete trotz Verweigerung auf der Platte, erst Exit 2
   wirkte.
2. **Kann `PreInvocation` Kontext in das Modell schreiben?** Wenn nicht, ist
   `session-start` auf Gemini nicht nachbaubar und der Inhalt gehört als Prosa
   nach `GEMINI.md`.

## Bausteine

Drei Schichten.

**Kern**, hostunabhängig, kennt keine JSON-Hülle:

| Paket | Aus | Zweck |
|---|---|---|
| `internal/child` | `process.py` | ein Kind mit Zeitgrenze, Prozessbaum-Tötung, Pipe-Absaugung |
| `internal/lanes` | `checks.py`, `runner.py` | Lanes ausführen, Ergebnisse sammeln |
| `internal/ulconfig` | `config.py` | `.ultraloom/config.toml` vollständig lesen |
| `internal/gitwork` | `worktree.py` | HEAD, geänderte Dateien, Vergleich seit Basis |
| `internal/journal` | `journal.py`, `gate.py`, `state.py` | Lauf-Journal, Gate- und Sitzungszustand |

**Naht**, `internal/hostio`: eine normalisierte Nutzlast (`Event`, `Tool`,
`Paths`, `SessionID`) und eine normalisierte Antwort (`Verdict`: durchlassen,
verweigern mit Grund, Kontext nachschieben). Der Kern sieht nur diese zwei
Typen.

**Adapter**, `internal/hostio/{claude,antigravity,codex}.go`: Nutzlast
erkennen, Nutzlast lesen, Antwort schreiben.

Erkennung ohne `--host`-Flag, an der Nutzlast, wie `brain guard` es tut:
`hook_event_name` mit `tool_input.file_path` ist Claude, `TargetFile` ist
Antigravity. Ein Flag wäre ein zweiter Ort, an dem dieselbe Wahrheit steht.

Unterbefehle in `cmd/guard/`, nach dem Muster der sechs vorhandenen in
`cmd/guard/main.go`: `hook session-start`, `hook subagent-start`,
`hook subagent-stop`, `hook stop`, `check all`, `check coverage`.

## Fehlerverhalten: das Gate fällt geschlossen

`payload.py` kennt 0 durchlassen, 1 interner Fehler, 2 blockieren. `stop.py`
gibt an sieben Stellen 1 zurück: `:100`, `:109`, `:146`, `:207`, `:218`,
`:227`, `:248`.

Nachgerechnet gegen den Vertrag ist 1 beim Host ein *nicht* blockierender
Fehler — die Runde endet trotzdem. Belegt in `ultra-brain/pkg/guard/guard.go:22-28`,
dort am 2026-09-06 gemessen. Für ultraloom heißt das: **eine kaputte
`.ultraloom/config.toml` schaltet das Stop-Gate still ab.** Der Lauf endet
grün, obwohl nichts geprüft wurde.

Der Port übernimmt das nicht. Jeder Fehler, der verhindert, dass das Gate
*läuft*, verlässt mit 2 und nennt den Grund. Exit 1 bleibt allein, wo es nichts
zu blockieren gibt — `session-start` etwa hat kein Urteil zu fällen. Die
Go-Tests halten das fest, statt die Python-Zeilen abzuschreiben.

Kein `fail_open`-Schalter. Ein Schalter, den jemand setzt und vergisst, führt
zum heutigen Zustand zurück, nur unsichtbarer.

## Nachweis

TDD, Test vor Code, 100 % Coverage. Vorlage sind die knapp 5.000 Python-Testzeilen
— jeder Fall wird gegen den Code nachgerechnet, nicht abgeschrieben. Der Befund
oben ist genau ein Fall, in dem der Python-Test das falsche Verhalten
festhält.

Golden-Dateien für die drei Antwortformen, damit ein Formatwechsel eines Hosts
als Testfehler auffällt und nicht im Betrieb.

Zwei plattformgebundene Coverage-Ausschlüsse, beide begründet:

- Job-Objekt (Windows) und `killpg` (POSIX) laufen je nur auf einem System. Die
  Wahl liegt hinter einer Funktion nach dem Muster von `terminator` in
  `process.py`, damit jeder Arm auf dem anderen System als Einheit testbar ist;
  Dateien mit Build-Tag, wie `internal/junction/junction_windows.go` es schon
  macht.
- Der Codex-Adapter hat einen Test: unbekannter Host ⇒ Exit 2. Mehr wäre
  geraten.

## Stufen

Jede Stufe endet grün und wird einzeln übergeben. Gearbeitet wird im Worktree
`.worktrees/go-hooks`: die Sitzung, die den Stop-Hook umschreibt, läuft unter
ihm.

**Stufe 0 — Messen und Vorarbeit, kein Verhalten geändert.**
`internal/settings/merge.go:407` (`toolKey`) lernt `ulguard hook <x>` wie
`ultraloom hook <x>` zu lesen. Ohne das tragen alle vier Ereignisse den
Schlüssel `ulguard`, und die Eintragsidentität stimmt nur noch zufällig über
`firstOwnedIndex`. Dazu die zwei Messungen aus der Hostmatrix.

**Stufe 1 — Naht und leichtester Hook.** `internal/hostio` mit Claude- und
Antigravity-Adapter und der Codex-Naht, `internal/journal`, `gitwork` nur mit
HEAD. Dann `ulguard hook session-start` (90 Zeilen Python).

**Stufe 2 — Subagent-Paar.** `internal/child`: `cmd.WaitDelay`, Job-Objekt auf
Windows, `killpg` auf POSIX. Dazu `gitwork` vollständig. Dann
`hook subagent-start` und `hook subagent-stop`.

**Stufe 3 — Stop-Gate.** `internal/ulconfig`, `internal/lanes`, dann
`hook stop` mit der Exit-2-Reparatur.

**Stufe 4 — Lanes als Befehl.** `ulguard check all` und `check coverage`
ersetzen `uv run ultraloom check all` im erzeugten Pre-Commit-Hook
(`cmd/init/run.go:337`) und `hooks/coverage-check.py`. Der Python-Arm der
Coverage-Lane bleibt ein Kindprozess.

**Stufe 5 — Schnitt.** `cmd/init/run.go` schaltet alle Vorlagen um und bekommt
den zweiten Schreiber für `.agents/hooks.json`. Dann fallen
`src/ultraloom/hooks/`, `checks.py`, `runner.py`, `process.py`, `config.py`,
`worktree.py`, `journal.py`, `gate.py`, `state.py` und ihre Tests. `cli.py`
verliert `hook` und `check`; `tests/test_cli.py` (1410 Zeilen) und
`tests/test_module_boundary.py` (260) sind eigene Aufgaben, keine
Nebenwirkung.

Reihenfolge innerhalb jeder Stufe: der Go-Hook steht und ist grün, *dann*
schaltet `ulinit` um, *dann* fällt der Python-Hook. Nie umgekehrt.

## Installation

Zuletzt und nur hinter grünem Gate. `~/go/bin/ulguard` ist ein 41-Byte-Shim auf
`ulguard.exe`; ein `go install` schaltet die Schreibschranke jeder laufenden
ultraloom-Sitzung um, auch der migrierenden. Das bisherige `ulguard.exe` wird
vorher als `.old` beiseitegelegt — der Rückfallweg, den die Maschine für
`brain.exe` schon von Hand führt.

## Außerhalb des Schnitts

- `flows/verify_until_green.py`, `model/*` und
  `pyproject.toml [project.scripts] ultraloom`: bleiben Python am
  `claude-agent-sdk`.
- `commit/language.py` (1037 Zeilen): kein Hook, nicht betroffen.
- `ultra-brain/hooks/git/ultraloom.sh:21` ruft `python -c` für ein
  `os.path.relpath`. Ein Pfadausdruck, kein Urteil, und in einem anderen Repo.
  Eigene Runde.
- `.ultraloom/config.toml` hat keine Wiki-Gate-Mode gesetzt, deshalb schreibt
  `ulinit` die `brain`-Einträge nicht (`cmd/init/run.go:704-720`). Der
  `brain guard`-Eintrag in `.claude/settings.json` wurde am 2026-09-10 von Hand
  in init's Form nachgetragen (Timeout 15, `ultraLoomOwned`). Ob die Wiki-Mode
  gesetzt wird — und damit auch `brain wiki-gate` auf Stop dazukommt —
  entscheidet eine eigene Runde.
