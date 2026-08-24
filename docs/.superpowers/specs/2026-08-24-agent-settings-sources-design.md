# Welche Umgebung ein Reparaturlauf erbt

Entwurf, 24.08.2026. Schließt den Backlog-Punkt *`setting_sources` bleibt
ungesetzt* aus `2026-08-21-teilprojekt-2-backlog.md`.

## Der Befund

`model/agent_sdk.py` übergibt `setting_sources` nicht. Das ist kein
Nicht-Setzen mit neutraler Wirkung: `None` heißt im SDK ausdrücklich „alle
Quellen laden, wie die CLI" (`types.py:2226`). Ein ultraloom-Lauf erbt heute
also die vollständige Werkzeugumgebung der Maschine, auf der er läuft — nur
sagt das niemand.

Gemessen in space, Lauf 0005: die `SessionStart`- und `Stop`-Hooks des Projekts
liefen mit, `PostToolUse` nicht. Der Backlog führt den `SessionStart`-Hook als
fremden Seiteneffekt, weil er eine `override.cfg` in den Arbeitsbaum schrieb.

## Warum der Seiteneffekt keiner ist

`space/.claude/hooks/session_start.py:302` schreibt die Datei aus einem Grund,
den ultraloom teilt: Godot löst `user://` aus `config/name` auf, nicht aus dem
Projektverzeichnis. Jeder Worktree teilt sich denselben Save-Ordner, und spaces
Suite ruft in fünf Testdateien `SaveStore.clear()` in Setup und Teardown. Der
Hook-Kommentar nennt den Befund, der dazu führte: ein Test einmal rot, dreimal
danach nicht reproduzierbar.

Damit dreht sich die Frage um. Ein Reparaturlauf ohne diesen Hook prüft nicht
sauberer, sondern unzuverlässiger — er repariert ein Rot, das seine eigene
Isolation erzeugt hat. Der Baum *ohne* `override.cfg` ist der unreproduzierbare.

## Die Entscheidung

**Ein Lauf erbt die versionierte Umgebung des Zielprojekts und sonst nichts.**
Standard: `["project"]`, also `.claude/settings.json`.

Die drei Quellen sind ungleich viel wert, und der Maßstab ist der Worktree:

| Quelle | Datei | Im frischen Worktree? | Pro Projekt? |
| --- | --- | --- | --- |
| `project` | `.claude/settings.json` | ja, wenn versioniert — sie reist im Commit mit | ja |
| `local` | `.claude/settings.local.json` | nein, untracked | ja, aber nicht übertragbar |
| `user` | `~/.claude/settings.json` | ja, aber maschinenweit | nein |

`local` fehlt genau in dem Fall, für den ultraloom gebaut ist. `user` ist das
Gegenteil von „pro Projekt" — in der gemessenen Umgebung bringt es einen
globalen `SessionStart`-Hook, der eine Versionsdatei schreibt, und sonst nichts.

Die Vorbedingung gehört mitgesagt: *Hooks pro Projekt* heißt ab hier *Hooks, die
im Repo stehen*. Ein Projekt, das seine Hooks in `settings.local.json` hält,
verliert sie im Worktree-Lauf — heute schon, aber ab hier verspricht ultraloom
etwas, das dort nicht hält. Deshalb der Pfad-Ausweg in Abschnitt *Der Schlüssel*.

## Was nicht dieselbe Schraube ist

Der Backlog nennt im selben Absatz, dass das SDK dem Reparateur die global
konfigurierten MCP-Server anbietet, und liest beides als eine Frage. Es ist
zweierlei: `setting_sources` deckt ausschließlich die drei `settings.json`, die
MCP-Server stehen in `~/.claude.json` und kommen über einen anderen Weg. Diese
Entscheidung räumt die Werkzeugrunde aus Lauf 0005 **nicht** ab. Der Punkt
bleibt offen und gehört gesondert entschieden.

## Der Schlüssel

Ein Schlüssel, zwei Wertsorten, weil zwei SDK-Felder dahinterstehen, die nur
gemeinsam Sinn ergeben.

```toml
[agent]
settings = ["project"]                       # Standard
settings = ["project", "local"]              # mehrere Ebenen
settings = []                                # Isolation, gar keine Umgebung
settings = ["hooks/repair.json"]             # eine benannte Datei, relativ zu --root
settings = ["project", "../.claude/settings.json"]
```

- `"user"`, `"project"`, `"local"` sind reservierte Wörter. Sie werden zu
  `setting_sources`.
- Alles andere ist ein Pfad relativ zu `--root` und wird zum SDK-Feld
  `settings` (CLI-Flag `--settings`).
- Steht kein Wort in der Liste, ist `setting_sources` leer und es gilt genau die
  benannte Datei.

### Höchstens ein Pfad

`--settings` nimmt einen. Mehrere hießen, dass ultraloom sie selbst zu einem
Objekt verschmilzt, also Claudes Merge-Semantik nachbaut — Hook-Arrays hängen
aneinander, skalare Schlüssel überschreiben. Das ist dasselbe zweite Regelwerk,
das `find_cli` in `model/agent_sdk.py` ausdrücklich vermeidet, und es driftet
beim ersten Versionssprung. Wer zwei Dateien braucht, schreibt eine dritte, die
beide enthält.

### Die Reihenfolge in der Liste bedeutet nichts

Die Rangfolge ist Claudes und steht fest
([Dokumentation](https://code.claude.com/docs/en/settings)), höchste zuerst:

| # | Ebene | Datei |
| --- | --- | --- |
| 1 | Managed settings | `managed-settings.json`, MDM oder die claude.ai-Konsole |
| 2 | Command line | `claude --settings` |
| 3 | Project local | `.claude/settings.local.json` |
| 4 | Shared project | `.claude/settings.json` |
| 5 | User | `~/.claude/settings.json` |

`["local", "project"]` und `["project", "local"]` sind dieselbe Konfiguration.
Und weil der benannte Pfad auf Ebene 2 liegt, schlägt er bei
`["project", "<pfad>"]` sowohl `project` als auch `local` in jedem skalaren
Konflikt. Hooks summieren sich, skalare Schlüssel nicht.

### Die vierte Ebene ist nicht wählbar

Das SDK kennt drei Quellen: `SettingSource = Literal["user", "project",
"local"]`. Managed settings stehen darüber und gelten immer; nichts, was
ultraloom setzt, überschreibt sie. `"managed"` wird deshalb als reserviertes
Wort *erkannt* und mit eigener Begründung abgelehnt, statt als unbekannter Pfad
an der Existenzprüfung zu sterben.

## Was abgelehnt wird

| Eingabe | Meldung |
| --- | --- |
| kein `list[str]` | `[agent].settings must be a list of strings` |
| zwei Pfade | `[agent].settings names two files (a, b); the SDK loads one` |
| Pfad existiert nicht | `[agent].settings: "x" is neither "user"/"project"/"local" nor an existing file under <root>` |
| `"managed"` | `managed settings always apply and cannot be selected` |

Die Existenzprüfung fängt den Tippfehler mit ab: `"porject"` ist ein Pfad, der
nicht existiert, und die Meldung nennt die drei erlaubten Wörter.

Geprüft wird beim Laden der Konfiguration, nicht beim Lauf — wie bei
`cli_path`, wo die Existenz ausdrücklich Sache von `Config` ist. Ein Lauf, der
still ohne die Hooks des Projekts prüft, ist der Fehler, den diese Prüfung
verhindert.

## Wo es im Code landet

Das ist eine Eigenschaft des Modells, nicht eines Requests — wie `cli_path`.
Der Weg durch `runner.py`, den `mcp_servers` nimmt, entfällt.

- `config.py`: zwei Felder auf `Config` (`setting_sources: tuple[str, ...]`,
  `settings_file: Path | None`), ein TOML-Schlüssel. Aufgeteilt und geprüft
  beim Laden, neben `_cli_path`.
- `cli.py`, `_model`: beide Felder an `AgentSdkModel` durchgereicht.
- `model/agent_sdk.py`, `_options_for`: `setting_sources` immer gesetzt,
  `settings` nur wenn vorhanden — nach demselben Muster, das `cli_path` heute
  benutzt, und aus demselben Grund: ein `None` an das SDK zu geben, wo
  ultraloom keine Antwort hat, überlässt dem SDK eine Entscheidung, die es
  ändern darf.

## Tests

- Der bestehende Wächtertest in `test_agent_sdk.py`, der die Optionsnamen gegen
  die installierte `ClaudeAgentOptions` hält, bekommt `setting_sources` und
  `settings` dazu.
- Config-Tests für die vier Ablehnungen aus der Tabelle.
- Ein Test, der Wörter und Pfad korrekt getrennt sieht, inklusive der Mischung.
- Ein Test für den Standard: ohne Schlüssel steht `["project"]` in den Optionen.

## Benannte Unbekannte

`PostToolUse` blieb in Lauf 0005 aus, obwohl der Matcher (`Write|Edit`) das
Werkzeug des Reparateurs deckt und `space/.claude/settings.json` versioniert
ist. Warum, ist ungeklärt. Diese Spec sagt deshalb zu, dass die Einstellungen
des Projekts **geladen** werden — nicht, dass jeder darin konfigurierte Hook
läuft. Wer die Zusage schärfer braucht, misst zuerst.

Ungeprüft ist ebenso, ob die CLI `.claude/` von `--root` aus nach oben sucht.
Falls nicht, ist der benannte Pfad die Antwort für das Monorepo, und genau
dafür steht er im Entwurf.

## Was der Entwurf nicht tut

- Er räumt die global konfigurierten MCP-Server nicht ab (eigener Punkt, oben).
- Er erzwingt nicht, dass ein Zielprojekt `.claude/settings.json` versioniert.
  Ultraloom kann das nicht, und der Pfad-Ausweg macht es unnötig.
