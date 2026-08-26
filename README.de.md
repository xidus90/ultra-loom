# ultraloom

[English](README.md)

Eine Prüfkette, die eine einzige Schnittstelle vor ruff, eslint, gdlint, mypy,
tsc, pytest, vitest und coverage setzt — und einen optionalen Graph-Harness für
Agenten-Abläufe.

## Die Prüfkette

    uvx ultraloom check lint
    uvx ultraloom check types
    uvx ultraloom check test
    uvx ultraloom check coverage
    uvx ultraloom check all

Keine Installation im Projekt, keine LLM-Abhängigkeit, kein API-Schlüssel. Das
Werkzeug für jede Prüfung kommt aus einem Sprach-Preset; wo es läuft, steht in
der `.ultraloom/config.toml` des Projekts.

`--threshold` setzt die Zahl, die ultraloom neben der Coverage-Prüfung
*ausweist*. ultraloom erzwingt sie nicht — ob der Lauf besteht, entscheidet
die eigene Konfiguration des Coverage-Werkzeugs. Eine Zeile, die "ok" für eine
Schwelle liest, die niemand geprüft hat, ist der eine Fehler in diesem System,
der wirklich Schaden anrichtet. Konkret, für Python: `coverage report` nimmt
seinen Exit-Code aus `fail_under` und aus nichts anderem — ohne diesen
Schlüssel in der eigenen Konfiguration des Projekts ist ein Lauf mit 83 % grün.
Dasselbe gilt für `[verify.coverage].report` — einen Report-Befehl zu benennen
bringt niemanden dazu, eine Zahl zu erzwingen.

In Python misst `check coverage`, bevor er berichtet: `coverage report` liest
nur eine Datei, die irgendein früherer Lauf erst geschrieben haben muss. Wer
diese Messung vornimmt, folgt aus der Menge der angeforderten Prüfungen, nicht
allein aus der Tabelle — siehe *Reihenfolge zwischen den Prüfungen* weiter
unten. In `check all` läuft die Suite **einmal**: `test` läuft unter
`coverage run`, und `coverage report` liest in der nächsten Stufe, was jener
geschrieben hat.

Eine Prüfung wird in dieser Reihenfolge aufgelöst, und ultraloom rät nie
darüber hinaus:

1. `[verify].<kind>` in `.ultraloom/config.toml`
2. `.ultraloom/checks/<kind>.*` — ein selbst geschriebenes Skript. Eine
   `.py`-Datei läuft mit ultralooms eigenem Interpreter, alles andere direkt;
   bei mehreren Treffern gewinnt der erste nach Name — also ein Skript pro
   Prüfung.
3. das Preset für die Sprache, die ultraloom über eine Marker-Datei erkennt
   (`pyproject.toml`, `package.json`, `project.godot`)

Eine Prüfung, die sich nicht auflösen lässt, wird als Fehlschlag gemeldet,
nie übersprungen.

Die Presets verlangen von ihren Werkzeugen die knappen Ausgabemodi, denn
einen Prüfbericht liest ein reparierender Agent, der bei jeder Runde für
jedes seiner Zeichen zahlt. Eine Folge davon lohnt im Voraus:
`mypy --no-error-summary` streicht auch die Zeile "Success: no issues found",
sodass eine grüne `types`-Prüfung gar nichts schreibt. Das Urteil hängt am
Exit-Code, wie schon immer — aber ein leerer Bericht ist keine Prüfung, die
nicht gelaufen ist. GDScript hat aus derselben Familie von Gründen kein
Coverage-Preset: Die Werkzeuge, die es messen, sind ein Editor-Addon und ein
Skript im Projekt selbst, und keins von beiden ist ein Befehl, den ein
anderes Projekt laufen lassen könnte; einen zu erfinden sähe wie eine Prüfung
aus, ohne eine zu sein. Ein solches Projekt nennt seinen eigenen unter
`[verify.coverage]`.

## Konfiguration

`.ultraloom/config.toml`, alles davon optional:

```toml
[verify]
lint = "ruff check ."                 # ein String: ein Befehl, wie bisher
types = ["mypy src", "pyright"]       # eine Liste: mehrere, einer nach dem anderen
test = "pytest -q"
max_parallel = 4                      # Standard: os.process_cpu_count()

[verify.lint]                         # eine Tabelle: mehrere, mit Schaltern
commands = ["gdlint .", "gdformat --check ."]
threaded = true

[verify.after]                        # Reihenfolge zwischen den Prüfungen
coverage = "test"

[verify.coverage]
threshold = 100
report = "coverage.xml"

[exec]
# Jedem Prüfbefehl vorangestellt, für ein Projekt, das in einem Container baut.
prefix = "docker compose exec -T web"

[agent]
# MCP-Server, die ein Agentenknoten mit dem Werkzeugprofil "mcp" erreichen darf.
mcp_servers = ["wiki"]
# Welche Einstellungen ein Reparaturlauf lädt. Die drei reservierten Wörter
# stammen von Claude Code; alles andere ist ein Pfad zu einer Datei, relativ zu --root.
settings = ["project"]
# Wo die Claude-CLI liegt, wenn die eigene Suche des SDK sie nicht findet.
cli_path = "C:/Users/me/AppData/Local/Programs/claude/claude.exe"
```

`[agent].cli_path` ist für die Maschine, deren einzige Claude-CLI etwas ist,
das das SDK nicht starten will — etwa ein npm-Shim namens `claude.CMD`. Ohne
ihn stirbt jeder Agentenknoten wenige Sekunden nach dem Start, mit einer
Meldung über eine Option, die ultraloom nie angeboten hat.
`ULTRALOOM_CLI_PATH` sagt dasselbe und **schlägt** die Datei: Wer die
Variable exportiert, tut das, weil die Datei des Projekts auf dieser Maschine
falsch ist — umgekehrt wäre die Variable überall tot, sobald ein einziges
Projekt den Schlüssel aufgeschrieben hätte. Ein leerer Wert zählt auf beiden
Seiten als ungesetzt; so schaltet eine Maschine, die die Variable exportiert,
sie wieder ab. Ein Pfad, der keine Datei ist, wird beim Lesen der
Konfiguration abgelehnt — vor dem ersten Knoten statt einmal pro
Agentenaufruf.

Dasselbe gilt, wenn gar nichts konfiguriert ist: Ein `run`, dessen Ablauf
einen Agentenknoten hat, sucht einmalig nach einer startbaren CLI, bevor der
Lauf überhaupt existiert, und nennt, welcher der drei Auswege zu nehmen wäre,
falls es keine gibt. Ein Ablauf aus Codeknoten und ein Lauf mit `--no-model`
stellen die Frage nie.

`[agent].settings` sagt, welche Einstellungen ein Lauf erbt. Der Standard ist
`["project"]` — die eigene `.claude/settings.json` des Zielprojekts, und
sonst nichts. Diese Quelle reist als einzige in einen Git-Worktree mit, weil
sie die einzige versionierte ist; `.claude/settings.local.json` ist
unversioniert und bleibt zurück, und `~/.claude/settings.json` gehört zur
Maschine, nicht zum Projekt. Gegen einen Reparaturlauf gerechnet ist der
Unterschied nicht nur Ordnung: Ohne die Nutzereinstellungen sank der Prompt
der ersten Runde von 14 381 auf 4 901 Tokens, weil die dort konfigurierten
Plugins und Skills nicht mehr geladen werden.

`"user"`, `"project"` und `"local"` sind reservierte Wörter. Alles andere ist
ein Pfad relativ zu `--root`, der zusätzlich zu ihnen geladen wird:

```toml
[agent]
settings = []                                # überhaupt keine geerbten Einstellungen
settings = ["hooks/repair.json"]             # eine benannte Datei, und nur sie
settings = ["project", "../.claude/settings.json"]
```

Höchstens ein Pfad: `--settings` nimmt einen einzigen, und mehrere
zusammenzuführen hieße, Claude Codes eigene Merge-Semantik hier nachzubauen.
Die Reihenfolge in der Liste bedeutet nichts — die Vorrangordnung stammt von
Claude Code und läuft über managed settings, `--settings`,
`.claude/settings.local.json`, `.claude/settings.json`,
`~/.claude/settings.json`, oben der höchste. Ein benannter Pfad übertrifft
damit beide Projektdateien bei jedem skalaren Schlüssel; Hooks summieren
sich, Skalare tun es nicht.

Ein Pfad, der keine Datei ist, wird beim Lesen der Konfiguration abgelehnt —
womit auch ein vertipptes Wort auffällt: `"porject"` ist ein Pfad, und die
Meldung nennt die drei, die keine sind. `"managed"` wird namentlich
abgelehnt, denn managed settings gelten immer, und nichts davon überschreibt
sie.

`[agent].settings` betrifft Settings-Dateien und sonst nichts. Die
MCP-Server, die eine Maschine in `~/.claude.json` konfiguriert, kommen auf
einem anderen Weg und bleiben unberührt — sie kosten ebenfalls keine Tokens,
denn die `tools`-Obergrenze hält sie aus dem Prompt heraus: Der Adapter nennt
die eingebauten Werkzeuge erschöpfend, und was er nicht nennt, erreicht das
Modell nie. `[agent].mcp_servers` hält nichts heraus; es ist eine
Allow-Liste, die höchstens `allowed_tools` verbreitert.

Welches Wheel von `claude-agent-sdk` installiert wird, entscheidet darüber,
ob der Agenten-Pfad überhaupt läuft; deshalb pinnt das Extra genau eine
Version. Die Wheels für eine bestimmte Plattform tragen eine
`claude`-Ausführbare mit sich, das plattformunabhängige nicht — und 0.2.144
kam ohne Windows-Wheel, sodass das SDK auf Windows in genau dieser Version
nichts zum Starten hatte. Eine Untergrenze hätte nicht geholfen: Kaputt war
gerade die *neuere* Version.

`lint`, `types` und `test` nehmen drei Gestalten an, unterscheidbar nach
Typ: ein String ist ein Befehl, eine Liste sind mehrere, und eine Tabelle
ist die vollständige Form mit `commands` (erforderlich, nicht leer) und
`threaded` (Standard `false`). Einen String und eine Tabelle unter demselben
Namen kann TOML nicht ausdrücken, daher lehnt der Parser das ab, bevor
ultraloom es je sieht.

`coverage` nimmt **keine** der drei an und sagt das in jeder Gestalt: Ein
String oder eine Liste unter `[verify]` wird mit "[coverage] must be a
table" abgelehnt (die Meldung nennt das Blatt, nicht die vollständige
Überschrift), und ein `[verify.coverage]` mit `commands` oder `threaded` wird
namentlich abgelehnt, mit Verweis auf `report`. Dorthin gehört der Befehl.
Was *nicht* aufgefangen wird, ist ein Tippfehler innerhalb von
`[verify.coverage]` — ein Schlüssel, der weder `report` noch `threshold` ist,
wird kommentarlos ignoriert, sodass `reprot = "…"` die Prüfung bei ihrem
Skript oder ihrem Preset lässt.

Jeder Befehl einer Art läuft, auch die hinter dem ersten roten: Dem
Reparateur schuldet man die volle Liste der Befunde, und eine halbe Liste
kostet eine weitere bezahlte Runde durchs Modell. `threaded = true` führt
sie gleichzeitig aus und ist deshalb ein reiner Geschwindigkeitsschalter —
das Urteil fällt entweder so oder so gleich. Das Timeout gilt pro Befehl,
sodass die Frist eines Linters nicht davon abhängt, wie viele Geschwister er
hat. Ein leeres `commands` oder ein leerer Befehl darin ist ein Fehler: Es
würde allein der `[exec].prefix` laufen, und ein Prefix mit Exit-Code 0
meldete eine Prüfung, die niemand konfiguriert hat, als bestanden.

`max_parallel` begrenzt die gleichzeitig laufenden Prüf-*Prozesse* über den
ganzen Lauf — Stufen, Arten und Befehle teilen sich einen Zähler, und
Leser-Threads zählen nicht dagegen. Ohne diese Begrenzung ist
`threaded = true` eine Selbstfalle: Vier Godot-Prozesse gleichzeitig sind
nicht viermal so schnell.

### Reihenfolge zwischen den Prüfungen

Prüfungen laufen in **Stufen**: innerhalb einer Stufe nebeneinander, die
Stufen nacheinander. Die Kanten liefert das Sprach-Preset; `[verify.after]`
überschreibt sie und bildet eine Art auf die eine Art ab, von der sie liest.

| Sprache | Stufe 0 | Stufe 1 |
| --- | --- | --- |
| Python | lint, types, test | coverage |
| Node | lint, types, test, coverage | — |
| GDScript | lint, test | (keine) |

Node bleibt einstufig, weil `vitest run --coverage` misst und berichtet, in
einem einzigen Lauf. Die Tabelle zeigt, was die *Presets* für einen Lauf
antworten, der jede Art anfordert; ein Projekt, das eine Art selbst
konfiguriert, bekommt seinen eigenen Befehl, und eine Stufe existiert nur
für die tatsächlich angeforderten Arten.

Die GDScript-Zeile ist kurz, weil zwei Presets fehlen, und keins davon ist
ein Versäumnis dieser Tabelle. Es gibt kein `types`-Preset — GDScript hat
keinen Typechecker zu benennen, also fällt `check types` in einem
Godot-Projekt auf ein rotes "GDScript has no types tool — a known
limitation, not a passed check" durch — außer das Projekt benennt einen
eigenen Befehl unter `[verify].types` oder legt ein Skript an
`.ultraloom/checks/types.*`; beides wird zuerst gefunden. Und es gibt kein
`coverage`-Preset — die Werkzeuge, die GDScript-Coverage messen, sind ein
Editor-Addon und ein Skript im Projekt selbst, und keins von beiden ist ein
Befehl, den ein anderes Projekt laufen lassen könnte. Eine zweite Stufe gibt
es darum gar nicht, bis das Projekt sie anlegt: Ein Godot-Projekt, das
Coverage misst, benennt seinen Report-Befehl unter `[verify.coverage].report`
**und** seine Ordnung unter `[verify.after]` — `coverage = "test"` — selbst.
Beide Lücken sind Lücken der Presets, nicht dieser Seite.

Eine nicht angeforderte Art fällt aus den Stufen heraus, ohne den Rest
aufzuhalten: `check coverage` allein läuft sofort statt hinter einer leeren
Stufe 0. Ein Zyklus in den Kanten wird mit dem gefundenen Pfad abgelehnt,
nicht begangen.

**Wer misst, in einem Satz:** Läuft die Prüfung, auf die ich warte, in
ebendiesem Durchgang und kann nebenbei messen, dann misst sie — sonst messe
ich selbst.

| angefordert | `test` läuft als | `coverage` läuft als | Suite läuft |
| --- | --- | --- | --- |
| test + coverage | `coverage run -m pytest` | `coverage report`, die Stufe danach | 1 |
| nur test | `pytest` | — | 1, ohne Messungs-Overhead |
| nur coverage | — | messen, dann berichten | 1 |
| `check all` | `coverage run -m pytest` | `coverage report`, die Stufe danach | 1 |

Ein Projekt, das `test` selbst konfiguriert, hat keine messende Variante,
die ultraloom kennt; `coverage` fällt also darauf zurück, selbst zu messen.
ultraloom rät nicht, ob der Test-Befehl eines anderen nebenbei misst.

### Warum eine Prüfung rot ist

Neben einem Werkzeug, das schlicht etwas gefunden hat, trägt ein rotes
Ergebnis eine Quelle:

| Quelle | Bedeutung |
| --- | --- |
| `unavailable` | die Prüfung ließ sich überhaupt nicht auflösen — keine Konfiguration, kein Skript, kein Preset. Rot, nie übersprungen. |
| `unready` | sie löste sich auf, aber das Projekt ist nicht bereit dafür (ein Godot-Projekt, das nie importiert wurde). |
| `blocked` | sie lief nicht, weil die Prüfung, auf die sie wartet, rot war. |

`blocked` ist rot wie die anderen und wird nicht übersprungen — aber es ist
auch nicht unerreichbar: Es erledigt sich in dem Moment, da sein Vorgänger
grün wird. Es ist deshalb nichts, was ein Reparateur anfassen sollte, und
`verify-until-green` lässt es außer Betracht, wenn die Entscheidung fällt,
aufzugeben.

### Bevor man eine Prüfung konfiguriert

**Ein Prüfbefehl, der aus einem Hook-Skript stammt, muss angesehen werden.**
ultraloom liest den Exit-Code und sonst nichts. Hook-Skripte berichten ihre
Befunde routinemäßig auf stdout und enden absichtlich mit 0 — ein
Claude-Code-`Stop`-Hook, der mit 2 endete, würde dem Agenten sein Zugende
verwehren. Direkt als Prüfbefehl eingetragen liest sich ein solches Skript
als bestandene Prüfung, ganz gleich, was es fand, und ultraloom kann es
nicht unterscheiden. Eine dünne Hülle davor hilft: Sie ruft dieselben
Befunde auf und wechselt nur den Kanal.

**Ein Befehl, der einen langlebigen Enkelprozess hinterlässt, ist rot**,
selbst wenn er mit 0 endete, und kostet zusätzlich fünf Sekunden. ultraloom
sammelt die Ausgabe eines Befehls auf Leser-Threads; ein Daemon oder Server,
den der Befehl gestartet hat, hält die Pipe offen, die Leser lassen sich
nicht einsammeln, und nach einer Gnadenfrist gibt man sie auf. Was
zurückkam, ist dann ein Präfix — und eine Schwelle oder eine Fehlerzahl kann
in dem Teil stecken, der fehlt. Eine Prüfung, deren Ausgabe niemand
vollständig lesen konnte, ist keine bestandene Prüfung. Der Bericht sagt
das mit eigenen Worten.

## Policy

    ultraloom policy check <art> <wert>   # von Hand oder aus einem Skript
    ultraloom policy hook                 # liest Claude Codes Payload von stdin

Regeln darüber, was ein Agent nicht anfassen darf, stehen üblicherweise als
Prosa in einer CLAUDE.md oder als handgeschriebenes Hook-Skript in einem
einzelnen Repository. Prosa erzwingt nichts, und ein Skript pro Repo driftet.
Die Policy beantwortet die zweite Frage derselben Art, die auch die Prüfkette
beantwortet: nicht *ist dieses Projekt grün*, sondern *darf dieser
Werkzeugaufruf überhaupt stattfinden* — überall mit demselben Werkzeug und mit
einer Begründung, die der Agent zu lesen bekommt.

Sie verweigert über drei Arten von Subjekt: den **Pfad**, auf den ein
Dateiwerkzeug schreibt, die **Kommandozeile**, die `Bash` ausführen würde, und
den **Inhalt**, den ein Dateiwerkzeug auf die Platte legen würde. Werkzeugnamen
selbst sind bewusst keine Art — das leisten Claude Codes eigene `permissions`,
und eine zweite Stelle mit derselben Zuständigkeit ist eine Quelle für
Widersprüche.

### Die Regeln

Jede Art bekommt ihren eigenen Abschnitt in `.ultraloom/config.toml` und jeder
Abschnitt seinen eigenen Modus:

```toml
[policy.paths]
mode = "deny"        # "allow" dreht um: nur Genanntes ist schreibbar
defaults = true      # false wirft die eingebauten Regeln ab

[[policy.paths.rules]]
match  = [".ultraloom/runs/*", "uv.lock"]
reason = "An edited journal destroys what replay exists for."

[[policy.commands.rules]]
regex  = '(^|[\n;&|(`])\s*git\s+push(?![\w-])'
reason = "Whether commits reach the remote is a human's decision."

[[policy.content.rules]]
regex  = 'type:\s*ignore(?!\s*#)'
tools  = ["Write", "Edit"]
reason = "No type: ignore without a reason behind it."
```

Die Begründungen stehen englisch in der Konfiguration, weil sie als
Fehlermeldung beim Agenten landen und dieses Projekt seine Meldungen englisch
schreibt.

Eine Regel trägt `match` (ein Glob) oder `regex`, genau eines von beiden —
beides zugleich wäre die Frage, ob UND oder ODER gilt, und wird beim Lesen der
Datei abgelehnt. Beide nehmen eine Zeichenkette oder eine Liste davon, mehrere
Muster teilen sich dann eine Begründung, ODER dazwischen; eine leere Liste wird
abgelehnt, statt als Regel zu bleiben, die nie greift. `tools` ist ein
optionaler Filter und keine eigene Art: fehlt er, gilt die Regel für jedes
Werkzeug ihrer Art. `reason` ist Pflicht, weil eine Sperre ohne Begründung genau
die Sorte Meldung erzeugt, gegen die ein Agent argumentiert oder die er umgeht.

Schreib Ausdrücke als TOML-Literalstrings ('...'). In einem Basic-String muss
jeder Backslash doppelt stehen, und ein vergessener macht aus `\s` still ein
`s` — eine Regel, die weiterhin lädt und weiterhin trifft, nur eben etwas
anderes.

An der Verankerung wird eine Kommando-Regel umgangen. Dem Vergleich wird die
ganze Kommandozeile gereicht, `re.search` läuft ohne `MULTILINE`, und damit
meint `^` deren Anfang und sonst nichts: `^git push` blockt `git push` und
lässt `git commit -m x && git push` durch — also genau die Form, für die die
Regel geschrieben wurde. Nimm die Alternativen mit auf und beende das Wort
selbst: `` (^|[\n;&|(`])\s*git\s+push(?![\w-]) `` fängt `;`, `&&`, eine Pipe,
eine Subshell und eine zweite Zeile, während `(?![\w-])` `git pushd` und `git
push-notes` draußen hält, wo ein bloßes ``\b`` sie hereinnähme.

Pfade werden als Pfade gematcht und alles andere als flacher Text. Ein
Pfadmuster geht durch `PurePosixPath.full_match` — als einziges hier kennt es
`**` über Verzeichnisgrenzen hinweg, ohne das ist `.aws/**` kein sinnvolles
Muster, und es hält `config/*` von `config/a/b` fern. Für eine Kommandozeile
wäre dieselbe Regel falsch: der Schrägstrich in `rm -rf a/b` trennt keine
Ebenen, also gehen Kommandos und Inhalte durch `fnmatch`. Claude Code liefert
absolute Pfade; der Hook macht sie relativ zur Projektwurzel und normalisiert
die Trennzeichen auf `/`, damit ein Muster unter Windows und POSIX dasselbe
trifft. Was außerhalb der Wurzel liegt, bleibt absolut, und eine Regel, die
dorthin zielt, muss den ganzen Pfad nennen.

Der Modus sitzt an der Art und nicht an der ganzen Policy. Ein globales
`mode = "allow"` würde mit den Pfaden auch jedes Kommando verbieten, das niemand
genannt hat — für Pfade nützlich, für Kommandos unbenutzbar.

Im Modus `deny` werden **alle** treffenden Regeln gemeldet, nicht nur die erste:
gewänne der erste Treffer, räumte der Agent einen Grund aus, liefe in den
nächsten und bräuchte eine Runde je Regel für eine Entscheidung, die er beim
ersten Mal vollständig hätte treffen können. Im Modus `allow` beendet die erste
Erlaubnis die Prüfung, und ein Subjekt, das nichts erlaubt, wird mit dem Hinweis
abgelehnt, dass der Modus `allow` ist.

### Was ohne jede Konfiguration gesperrt ist

Ohne `.ultraloom/config.toml` greifen die eingebauten Regeln trotzdem — ein Repo
ist geschützt, ohne dass jemand etwas eingerichtet hat. Sie sind ausschließlich
sicherheitsrelevant und stehen als Konstante in `ultraloom.policy.config`, nicht
in einer mitgelieferten TOML-Datei: eine Datei kann fehlen, eine Konstante
nicht.

Pfade, Begründung *secrets are not written by an agent*:

    .env   .env.*   *.pem   *.key   id_rsa*   *.p12
    .npmrc   .pypirc   credentials.json   .aws/**

Inhalte, Begründung *this looks like a credential in plain text*:

    -----BEGIN [A-Z ]*PRIVATE KEY-----
    \bAKIA[0-9A-Z]{16}\b
    \bsk-[A-Za-z0-9]{20,}\b

Kommandos: keine. `git push` und `pip` statt `uv` sind Politik, nicht
Sicherheit, und gehören in die Projektkonfiguration, wo man sie sieht. Eine
eingebaute Regel, die niemand nachliest, wird bei der ersten Reibung mit
`defaults = false` erschlagen — und nimmt die echten mit.

Die eingebauten stehen zuerst in der Liste der Begründungen, danach die
Projektregeln in der Reihenfolge der Datei. Sie gelten **nur im Modus `deny`**:
wer eine Art auf `allow` dreht, bekommt die Allowlist und sonst nichts, die
Voreinstellungen eingeschlossen. Den Modus umzudrehen heißt, die Verantwortung
ganz zu übernehmen.

### Exit-Codes

    0  erlaubt, oder das Werkzeug berührt keine Regel
    1  interner Fehler — blockt nie; eine defekte Policy darf keine Sitzung einsperren
    2  verweigert; alle Begründungen auf stderr

**Eine kaputte Konfiguration ist Exit 2, nicht Exit 1.** Eine Policy, die
stillschweigend durchlässt, wenn ihre eigene Konfiguration unlesbar ist, ist
derselbe Fehlermodus, vor dem diese README neben der Coverage-Prüfung warnt:
eine Zeile „ok" für etwas, das niemand geprüft hat. Exit 1 bleibt echten
Innenfehlern vorbehalten — unlesbare Payload, leeres stdin.

Als Claude-Code-Hook, in `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|NotebookEdit|Bash|PowerShell",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --project \"${CLAUDE_PROJECT_DIR}\" ultraloom policy hook",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

Der Hook liest zuerst `tool_name` und endet mit 0, bevor er eine Konfiguration
anfasst, wenn das Werkzeug keine Art berührt — er läuft vor jedem `Write`,
`Edit`, `NotebookEdit`, `Bash` und `PowerShell`, sein eigener Aufwand ist
deshalb eine Anforderung. Jedes Dateiwerkzeug ergibt ein Pfad- und ein
Inhalts-Subjekt, aber jedes benennt die beiden Schlüssel anders:

| Werkzeug       | Pfad            | Inhalt       |
| -------------- | --------------- | ------------ |
| `Write`        | `file_path`     | `content`    |
| `Edit`         | `file_path`     | `new_string` |
| `NotebookEdit` | `notebook_path` | `new_source` |

`NotebookEdit` mit `edit_mode = "delete"` ergibt nur den Pfad: sein
`new_source` verlangt das Schema zwar, geschrieben wird es dabei nie, eine
Inhaltsregel wäre dort also eine Falschmeldung. `Bash` und `PowerShell`
ergeben beide ihr `command`, eine Regel der Art `commands` deckt also beide
Shells ab — eine `git push`-Regel, die nur `Bash` kannte, war unter Windows
gar keine Regel.

`policy check` ist dieselbe Entscheidung ohne Payload darum herum, für Hand und
Skript: `ultraloom policy check commands "git push origin master"`. `--tool`
sagt, welchen Werkzeugnamen ein `tools`-Filter sehen soll; voreingestellt ist
`Write`.

Die Entscheidung ist gezeichnet in `docs/flows/policy.de.md`.

## Commit-Nachrichten

    ultraloom commit-msg <Datei>         # was der git-Hook ausführt
    ultraloom commit-msg --calibrate N   # was eine Schwelle abgelehnt hätte

Eine Historie halb auf Englisch und halb auf Deutsch ist schwer zu lesen und
noch schwerer zu durchsuchen, und dieses Abdriften ist nie eine Entscheidung —
es ist ein eiliger Commit nach dem anderen. Dieses Gate fängt das ab, solange
die Nachricht noch im Editor steht.

**Opt-in, ohne Vorgabe.** Ohne einen `[commit]`-Abschnitt in
`.ultraloom/config.toml` wird die Nachricht gar nicht erst gelesen. Es gibt
keine sinnvolle Sprache, gegen die zu prüfen wäre, wenn niemand eine gewählt
hat — anders als bei `[policy.*]` gilt hier ohne den Abschnitt keine Regel.

### Konfiguration

```toml
[commit]
# Pflicht. "en" oder "de" — die Sprache, in der hier committet wird.
language = "en"

# Optional, Vorgabe 2. Stoppworttreffer je Zeile, ab denen sie abgelehnt wird.
threshold = 2

# Optional. Zeilen, die dieses Projekt nie gewertet haben will, je mit Grund.
[[commit.allow]]
regex  = '^Revert "'
reason = "A revert repeats the original subject verbatim, whatever it said."
```

`[[commit.allow]]` nimmt `regex` und `reason`, beide Pflicht, und sonst nichts.
Anders als bei den Pfadregeln der Policy gibt es kein `match`: Ein Glob hat
gegen eine Textzeile keine klare Bedeutung — wäre `WIP*` die ganze Zeile oder
irgendwo darin? — und wer `match` schreibt, bekommt eine Fehlermeldung, statt
dass es still als Regex übersetzt würde, wo `WIP*` klammheimlich zu `WIP`
gefolgt von beliebig vielen `P` würde. Das Muster wird beim Lesen der
Konfiguration übersetzt, ein kaputtes fällt also sofort auf, statt auf den
Commit zu warten, der zufällig zuerst passt.

Jeder Wert wird beim Lesen geprüft, und ein Fehler wird zusammen mit der Datei
genannt, aus der er stammt. Ein kaputtes `[commit]` ist Exit 1, nicht Exit 2 —
siehe die Exit-Codes weiter unten.

### Die Heuristik

Funktionswörter der *anderen* Sprache, die in dieser nichts bedeuten. Für
`language = "en"` ist die Liste deutsch: `der`, `das`, `und`, `nicht`, `ein`,
`wird`, `mit`, `von` und rund vierzig weitere. Ausdrücklich nicht darin, jedes
ein gewöhnliches englisches Wort: `die`, `war`, `man`, `den`, `hat`, `in`,
`so`, `an`. „Let the process die in the war room" darf kein Befund sein.

Treffer zählen **je Zeile, nicht je Nachricht**. Ein Text, der zwei deutsche
Seitentitel aufzählt, sind zwei Zeilen mit je einem Treffer — nicht eine Zeile
mit zweien, was die zweite Lesart ablehnen würde.

Umlaute werden vor dem Vergleich aufgelöst (`ä` zu `ae`, `ö` zu `oe`, `ü` zu
`ue`, `ß` zu `ss`), `für` und `fuer` sind für die Prüfung also dasselbe Wort,
während die Wortliste selbst ASCII bleibt.

### Was nie gewertet wird

Zeilen, die mit `#` beginnen, weil git dort seine eigenen Hinweise schreibt,
und alles unterhalb der Scherenmarke `# ------------------------ >8 ---`, die
`git commit --verbose` anhängt — der Diff darunter enthält, was immer die
Änderung berührt, und ihn zu werten hieße, jeden Commit abzulehnen, der
fremdsprachige Prosa anfasst.

Innerhalb einer Zeile werden fünf Formen entfernt, bevor gezählt wird:

| Form            | Beispiel                    | Warum                              |
| --------------- | --------------------------- | ---------------------------------- |
| Trailer-Zeilen  | `Ref: das und der`          | Ein git-Trailer, keine Prosa (nicht Zeile 1) |
| Code-Spans      | `` `das und der` ``         | Zitierte Bezeichner und Ausgaben   |
| Zitate          | `He said "das und der"`     | Ein Zitat ist nicht die eigene Rede|
| Pfad-Token      | `docs/das/und.md`, `der.py` | Ein Dateiname ist kein Satz        |
| Namenspartikel  | `von Neumann`, `de Broglie` | Der Partikel gehört zum Namen      |

Ein Trailer ist die großgeschriebene Bindestrichform — `Co-Authored-By`,
`Signed-off-by` — oder eines von `Fixes`, `Closes`, `Refs`, `Ref`, `Cc`,
`Link`, `Bug`, `BREAKING CHANGE`. Sonst nichts: eine
Conventional-Commit-Betreffzeile wie `fix:` oder `docs:` ist Prosa und wird
gewertet.

Code-Spans und Zitate dürfen über einen Zeilenumbruch reichen, über beliebig
viele Zeilen: Die Prüfung führt beim Durchlaufen der Nachricht mit, ob ein
Span offen ist, also sind beide Hälften ausgenommen und jede Zeile, die ganz
darin liegt, ebenso. Gewertet wird weiterhin je Zeile — jede Zeile behält
ihre eigene Zählung und ihre eigene Schwellenentscheidung; übertragen wird nur
die Frage, ob ein Span offen ist.

Ein offener Span endet an einer Leerzeile. Ein Absatzumbruch ist kein
plausibles Span-Inneres, und diese Grenze zählt: Ein Trennzeichen, das sich mit
nichts paart — ein Backtick oder ein `"` als Satzzeichen, wie in `80" breit` —,
öffnet einen Span, und ohne die Grenze liefe dieser Span bis zum Ende der
Nachricht und ließe jede Zeile darunter stillschweigend durch. Ein Tor, das
sich selbst abschaltet, ist schlimmer als eines, das zu viel ablehnt, der
Schaden endet also am Absatz.

Innerhalb eines Absatzes gilt der Rest der Zeile nach einem ungepaarten
Trennzeichen als zitiert. Nur das doppelte Anführungszeichen trennt, ein
Apostroph in `don't` öffnet also nichts.

Zeilen, die mit `#` beginnen, bewegen diesen Zustand nie: git hat sie
geschrieben und entfernt sie wieder, bevor die Nachricht gespeichert wird, ein
Trennzeichen dort gehört also zu keinem Span des Autors.

Für Zeile 1 gilt die Ausnahme nie. Ein Trailer-Block beginnt nicht auf der
Betreffzeile, während `Ref:` und `Auto-merge:` völlig taugliche Betreffs sind —
und bei einem einzeiligen Commit ist der Betreff die ganze Nachricht, eine
Ausnahme dort schaltete das Tor also genau dort ab, wo es zählt.

Ein Namenspartikel ist das kleingeschriebene Wort gefolgt von einem
großgeschriebenen; deutsche Prosa setzt dort einen Artikel oder ein
kleingeschriebenes Substantiv. Ohne diese Regel erreicht eine Nachricht, die
zwei solche Namen zitiert, die Schwelle von allein.

### Die Schwelle kalibrieren

Keine Zahl trägt von einem Repository zum nächsten: Ein Projekt, dessen Commits
Pfade, Paketnamen oder fremdsprachige Titel zitieren, erreicht jede Schwelle
früher als eines mit schlichter Prosa. Also messen, bevor das Gate angeht.

    ultraloom commit-msg --calibrate 100 --language en --root .

Liest die letzten `N` Nachrichten per `git log` und druckt je Schwelle, wie
viele sie abgelehnt hätte, samt deren Betreffzeilen. Hier antwortet dieselbe
Prüfung, die auch der Hook ausführt, `[[commit.allow]]` eingeschlossen — sonst
meldete die Tabelle Kosten, die das konfigurierte Gate nie verlangt.

`--language` gibt es, weil ein Projekt ohne `[commit]` noch keine Sprache hat,
die zu lesen wäre — genau darum wird ja zuerst gemessen. Ist ein
`[commit]`-Abschnitt da, überschreibt das Flag ihn nur für diese Messung. Fehlt
beides, lehnt der Befehl ab, statt zu raten. Eine Anzahl unter 1 wird ebenfalls
abgelehnt: `git log -n -1` heißt *unbegrenzt* und `-n 0` druckt eine leere
Tabelle, beides beantwortete einen Tippfehler mit etwas, das wie ein Ergebnis
aussieht.

`--language` gehört zu `--calibrate` und zu sonst nichts. `ultraloom commit-msg
<Datei> --language de` ist ein Fehler, keine Gefälligkeit: Die Sprache des
Hooks muss aus `[commit]` kommen, denn ein Flag, das sie überschriebe, ließe
einen Commit die Regel wählen, nach der er beurteilt wird. `--calibrate` neben
einer Nachrichtendatei wird aus dem milderen Grund abgelehnt, dass ein Flag nie
still übergangen werden soll.

**Die deutsche Richtung ist nicht kalibriert.** Die Wortliste für
`language = "de"` ist von Hand geschrieben und nie an einem deutschsprachigen
Repository gemessen worden. Ihre Schwelle ist ein Anfangswert, kein Ergebnis;
wer ihr trauen will, misst sie vorher mit `--calibrate`. Die englische Richtung
ist an der Historie eines Projekts kalibriert — hundert englische Commits gegen
sechzehn deutsche — und hat hier eine zweite Messung: `--calibrate 100
--language en` über ultraloom selbst lehnt am 2026-08-26 genau eine der letzten
hundert Nachrichten ab, bei Schwelle 1 und bei Schwelle 2 dieselbe. Diese
Nachricht ist ein englischer Commit *über* die Stoppwortliste, der `das, und`
blank in einer Klammer zitiert; sie ist die ehrliche Grenze der Heuristik und
der Grund, warum es Code-Spans und `[[commit.allow]]` gibt. Eine geratene Zahl
als gemessene auszugeben, wäre genau der Fehler, den dieses Werkzeug verhindern
soll.

### Exit-Codes

    0  die Nachricht ist in Ordnung, oder das Projekt hat kein [commit]
    1  interner Fehler — kaputte Konfiguration, unlesbare Datei, falsches Flag
    2  abgelehnt; jede beanstandete Zeile auf stderr

**Eine kaputte Konfiguration ist hier Exit 1 und unter der Policy Exit 2.** Die
Asymmetrie ist Absicht: Die Policy schützt vor einem Werkzeugaufruf, der nicht
stattfinden darf, dort ist Schweigen der größere Schaden. Dieses Gate schützt
einen Stil, und wegen eines Tippfehlers in einer TOML-Datei jeden Commit im
Repository zu blockieren, ist schlimmer, als einen durchzulassen — der Fehler
fällt beim nächsten `ultraloom check` auf.

Die Ablehnung nennt jede gefundene Zeile, nicht nur die erste, mit den
Treffern, die sie gewertet haben:

```
ultraloom commit-msg: this message reads as German, and commits here are English.
  line 1: Fix das und der thing
          hits: das, und, der
Rewrite it, or use `git commit --no-verify` if this cannot wait. The next
commit runs this check again.
```

Alle, weil eine nach der anderen den Autor je Zeile einmal durch den Editor
schickt und jede Runde eine weitere Gelegenheit ist, nach `--no-verify` zu
greifen. Und `--no-verify` steht mit Absicht da: Ein Gate, das seinen eigenen
Ausweg verschweigt, bekommt einen drumherum gebaut. Der Satz danach ist der
Punkt — der Ausweg gilt für diesen Commit, nicht für den Zweig.

### Der git-Hook

ultraloom liefert das Kommando, nicht den Hook. Drei Zeilen machen einen daraus:

```sh
#!/usr/bin/env sh
exec ultraloom commit-msg "$1"
```

Es gibt kein `install`-Unterkommando. Ein Werkzeug, das ungefragt in `.git/`
schreibt oder eine git-Einstellung verstellt, ist genau die Sorte
Nebenwirkung, die dieses Projekt anderswo kritisiert; drei Zeilen in einer
README sind ehrlicher.

Ein Hook unter `.git/hooks/` ist nicht versioniert und fehlt in einem frischen
Klon. Also gehört die Datei ins Repository, und git wird einmal je Checkout
darauf gezeigt:

```sh
mkdir -p .githooks
# die drei Zeilen von oben nach .githooks/commit-msg schreiben, dann:
chmod +x .githooks/commit-msg
git config core.hooksPath .githooks
```

`core.hooksPath` ist Konfiguration je Klon und lässt sich nicht committen, die
`git config`-Zeile gehört also in die Einrichtungsanleitung des Projekts.
Committet wird der Hook selbst, damit ihn niemand rekonstruieren muss.

Wo ultraloom nicht im `PATH` liegt, schreibt man den Aufruf aus —
`exec uv run --project . ultraloom commit-msg "$1"` — und bedenkt, dass git den
Hook vom Wurzelverzeichnis des Arbeitsbaums aus startet.

## Sitzungs-Hooks

    ultraloom hook session-start    # SessionStart
    ultraloom hook post-edit        # PostToolUse
    ultraloom hook subagent-start   # SubagentStart
    ultraloom hook subagent-stop    # SubagentStop
    ultraloom hook stop             # Stop

Die Policy beantwortet, *ob dieser Werkzeugaufruf geschehen darf*. Diese fünf
Hooks beantworten, was sie nicht sieht: ob die eben geschriebene Datei in
Ordnung ist, ob die Arbeit dieses Zuges grün ist, bevor der Zug endet, ob ein
pausierter Lauf noch auf eine Antwort wartet, und was ein Subagent getan hat,
das sein Bericht verschweigt. Jeder liest die Payload von Claude Code über
stdin, genau wie `ultraloom policy hook`.

| Ereignis | Hook | Was er tut |
| -------- | ---- | ---------- |
| `SessionStart` | `session-start` | Nennt jeden an einem Gate pausierten Lauf samt Frage und der `ultraloom resume`-Zeile, die sie beantwortet. Schreibt den Commit auf, mit dem die Sitzung beginnt. |
| `PostToolUse` | `post-edit` | Fährt `ruff format` über die geschriebene Datei, danach das Profil `edit`. |
| `SubagentStart` | `subagent-start` | Hält fest, wo `origin` und der lokale `HEAD` vor dem Lauf des Subagenten standen. |
| `SubagentStop` | `subagent-stop` | Nennt jede Remote-Referenz, die sich bewegt hat, neu ist oder verschwunden ist, und jeden Commit, den `HEAD` dazubekommen hat. |
| `Stop` | `stop` | Fährt die Kette — oder mit `--checks` ein Profil — und hält den Zug an, solange etwas rot ist. |

### Was Exit 2 je Ereignis bedeutet

    0  in Ordnung, oder bewusst übersprungen
    1  interner Fehler — hält nie etwas auf
    2  ein Befund; was er bewirkt, hängt am Ereignis

Exit 2 ist nicht überall dasselbe, und ein Irrtum darüber ist still:

- Bei `Stop` **hält er den Zug an**. Der Agent bekommt die Befunde und wird
  gebeten, noch einmal zu gehen.
- Bei `PostToolUse` blockiert er nichts — das Werkzeug ist längst gelaufen. Er
  ist nur der Weg, auf dem der Befund die Datei erreicht, die ihn ausgelöst
  hat, statt eine Minute später im Stop-Gate aufzutauchen, wo ihn nichts mehr
  mit ihr verbindet.
- Bei `SessionStart` und `SubagentStart` kommt er nie vor; beide melden und
  geben 0 zurück.
- Bei `SubagentStop` kommt er **mit Absicht** nie vor. Der Push ist zu diesem
  Zeitpunkt geschehen; den Subagenten am Aufhören zu hindern, macht ihn nicht
  rückgängig.

Eine Kette, die gar nicht laufen konnte, ist Exit 1, nie Exit 2 — aber nur,
wenn sie *gar kein* verwertbares Urteil geliefert hat, also **jedes** rote
Ergebnis `unavailable` ist. Ein einzelnes unavailable neben einem echten Befund
bleibt Exit 2. Die engere Regel ist teuer bezahlt: Ein GDScript-Projekt
konfiguriert kein `types`-Kommando, weil die Sprache keinen Typechecker hat, und
trug damit in jedem Lauf ein unavailable. Nach der alten „irgendeines"-Lesart
fuhr das Gate die volle Kette, fand einen echten Verstoß und gab trotzdem Exit 1
zurück — es konnte dort strukturell nie blockieren. Fehlende Prüfarten werden
weiter gemeldet, sie verdecken die Befunde daneben nur nicht mehr.

Diese Unterscheidung wiegt hier schwerer als anderswo: Die Hooks prüfen
ultraloom mit ultraloom, und ein kaputtes `checks.py` darf keine Sitzung
einsperren.

### Das Stop-Gate

Drei Dinge halten es davon ab, zur Falle zu werden:

- **Der Marker.** Solange `.claude/.no-verify` existiert, endet das Gate mit 0,
  ohne irgendetwas zu lesen oder zu fahren. Für einen Zug, den jemand bewusst
  rot abgeben will.
- **Der Block-Zähler.** Höchstens `MAX_BLOCKS` = 3 Blockaden je Sitzung; danach
  sagt das Gate, dass es aufgegeben hat, und lässt den Zug enden. Ein Gate, das
  nie nachgibt, sperrt die Sitzung ein, die es schützen sollte, und aus dieser
  Sitzung heraus gibt es keinen Ausweg. Ein grüner Durchgang setzt den Zähler
  *nicht* zurück — sonst erreichte eine Sitzung, die zwischen rot und grün
  wechselt, die Grenze nie.
- **Der Kurzschluss.** Ein Zug, der nichts geändert hat, endet mit 0 nach rund
  300 ms, statt eine Minute für ein Ergebnis auszugeben, das schon feststeht.

Was als *geändert* zählt, misst `changed_since(root, base)` und nicht der
Arbeitsbaum: Was ein Zug **committet**, verschwindet aus `git status`, und ein
Gate allein auf dem Arbeitsbaum schwiege genau dann, wenn jemand etwas
Ungeprüftes committet hat. Die Basis schreibt `session-start`, und jeder grüne
Durchgang schreibt sie fort — nie ein geblockter, das schaltete das Gate nach
einem einzigen Befund ab. Wurde das Gate mitten in einer Sitzung eingeschaltet,
gibt es keine Basis; `stop` fällt dann auf den Arbeitsbaum zurück **und sagt
das**, denn eine Messung mit bekannter Blindstelle darf nicht wie eine
vollständige aussehen.

Das Gate zieht seine eigenen Zustandsdateien von dem ab, was es sieht. Ohne das
sähe jeder Zug nach dem ersten geändert aus — wegen der Datei, die das Gate
selbst geschrieben hat.

### Ein Profil statt der ganzen Kette

    ultraloom hook stop --checks edit

`--checks` nimmt, was `ultraloom run --checks` nimmt: einen Profilnamen aus
`[verify.profiles]` oder eine kommagetrennte Liste von Prüfarten. Ohne das
Argument fährt das Gate alle Arten — das bisherige Verhalten.

Der Grund, warum ein Projekt das braucht, ist die Trennung zwischen Prüfungen,
die den Quelltext nur *lesen*, und solchen, die ihn *ausführen*. In einem
Spielprojekt kostete ein Zugende 36 Minuten, fast alles davon die Godot-Suite
(639 s seriell) und der Coverage-Bericht — fällig am Ende jedes einzelnen
Zuges, auch bei einem Zug, der eine Zeile Dokumentation geändert hat. Statische
Prüfungen gehören zum Edit und zum Zug; Suite und Coverage-Schwelle führen das
Projekt aus und gehören zum Commit, wo das Commit-Gate jenes Projekts sie
ohnehin fährt.

**Ein Lauf mit Profil schreibt die Basis nicht fort.** Die Basis ist das Wort
des Gates für „alles bis hierher ist geprüft“, und ein Profil, das die Suite
auslässt, hat sie nicht geprüft. Würde die Basis trotzdem weiterrücken, hielte
der nächste Zug die ungeprüfte Arbeit für erledigt, und die Suite liefe an
keinem Gate je. Unter `--checks` wächst die Spanne also nur — bezahlbar genau
deshalb, weil das Profil wegen seiner Billigkeit gewählt wurde.

Ein unbekanntes Profil oder eine unbekannte Prüfart ist Exit 1 mit der
Meldung von `kinds_for`, derselben, die `ultraloom run --checks` druckt. Der
Zug wird davon nie gehalten: eine kaputte Konfiguration ist kein Urteil über
die Arbeit.

### Verdrahtung

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run --project \"${CLAUDE_PROJECT_DIR}\" ultraloom hook stop --root \"${CLAUDE_PROJECT_DIR}\"",
            "timeout": 300
          }
        ]
      }
    ]
  }
}
```

`PostToolUse` bekommt den Matcher `Write|Edit|NotebookEdit`; die anderen vier
greifen auf alles. Timeouts: `post-edit` 60, `stop` 300, `session-start` 20,
`subagent-start` 30, `subagent-stop` 30.

**Je Ereignis genau ein Eintrag, und das ist keine Geschmacksfrage.** Mehrere
Einträge desselben Ereignisses starten *gleichzeitig*, nicht nacheinander —
zwei gemessene `Stop`-Einträge starteten 2 ms auseinander und überlappten
vollständig. Ein Block-Zähler, der auf zwei Einträge verteilt ist, verliert
Hochzählungen, und das ist ein Gate, das nicht zählt. Wer hier später etwas
ergänzt, hängt es in denselben Eintrag.

### Das Zustandsverzeichnis

`.ultraloom/hooks/<session_id>.json` hält, was zwischen zwei Aufrufen
überdauern muss: den Block-Zähler, den Basis-Commit der Sitzung und je einen
Remote-Schnappschuss pro Subagent. Eine Datei je Sitzung, damit zwei Sitzungen
im selben Checkout sich nicht gegenseitig den Zähler verstellen.

Es gehört in `.gitignore` und in die Pfadregeln der Policy: Ein Agent, der
seinen eigenen Block-Zähler zurücksetzt, hat das Gate abgeschafft.

Die Entscheidung ist gezeichnet in `docs/flows/session-hooks.de.md`.

## Der Harness (optional)

    uv add "ultraloom[agent]"

Führt einen Ablauf als Graphen aus: Knoten sind Schritte, Kanten sind
Übergänge mit Bedingungen. Er journalt jeden Schritt, hält an
Freigabepunkten an und setzt einen abgebrochenen Lauf dort fort, wo er
stehen blieb.

    ultraloom run <flow>       # einen Ablauf starten; druckt eine Lauf-ID
    ultraloom show <id>        # das Journal dieses Laufs ausgeben, eine Zeile pro Schritt
    ultraloom resume <id> --answer "yes"
    ultraloom replay <id>      # den Lauf aus seinem Journal neu ableiten, ohne Modellaufruf

### verify-until-green

Der Ablauf, den ultraloom mitbringt. Er führt die Prüfungen aus, übergibt
jede rote an den Reparateur und führt sie erneut aus — bis alles grün ist,
bis sich nichts mehr bewegt oder bis die Rundengrenze erreicht ist.

    ultraloom run verify_until_green
    ultraloom run verify_until_green --checks lint,types
    ultraloom run verify_until_green --checks quick --max-rounds 5

Unterstriche auf der Kommandozeile: Ein Ablaufname ist ein
Python-Bezeichner, darum wird `ultraloom run verify-until-green` mit Exit 1
abgelehnt. Innerhalb heißt der Graph weiterhin `verify-until-green` — nur
der Aufruf tut es nicht.

`--checks` nimmt eine kommagetrennte Liste von Prüfarten oder den Namen
eines Profils aus `[verify.profiles]`. Fehlt sie, führt der Ablauf jede
Prüfung aus. `--max-rounds` begrenzt die Reparaturrunden; fehlt es, greift
die eigene Grenze des Ablaufs. Der Ablauf prüft beides selbst beim Bauen und
verweigert den Start mit einer Meldung, die nennt, was er erwartet hatte —
so wird aus einem Tippfehler nie ein langer Lauf.

Der Reparateur darf die Pfade in `[verify].tests` nicht anfassen — eine
Prüfung, die grün wird, weil ihr Test bearbeitet wurde, ist die eine
Reparatur ohne jeden Wert. Coverage wird überhaupt nie repariert, aus
demselben Grund: Eine Coverage-Lücke schließen heißt, Tests schreiben.

Jede Reparatur wird gegen den Commit gemessen, auf dem der Lauf begonnen hat,
darum startet dieser Ablauf nur innerhalb eines Git-Repositorys; anderswo gibt
es nichts, wogegen zu messen wäre, und ein Lauf, der ohne einen begonnen wurde,
würde pausieren und dann jede Antwort verweigern. Ein `resume` eines älteren Laufs, dessen
Marker keinen Commit nennt, wird genauso verweigert — dann lieber einen neuen
Lauf starten.

```toml
[verify]
# Von diesem Ablauf verlangt: die Pfade, die der Reparateur in Ruhe lassen muss.
tests = ["tests"]
# Sekunden, die eine einzelne Prüfung dauern darf, bevor sie abgeschnitten wird.
timeout = 600

[verify.profiles]
quick = ["lint", "types"]
full = ["lint", "types", "test", "coverage"]
```

Exit-Codes: `0` grün, `1` weiter rot nach der letzten Runde, `3` wartet an
einem Freigabepunkt, `4` der Lauf wurde wegen der geschützten Testpfade
gestoppt — entweder hat der Reparateur einen angefasst, oder der Arbeitsbaum
ließ sich nicht lesen, um es festzustellen.

Der Ablauf ist ausführlich beschrieben in
`docs/flows/verify-until-green.de.md`.

### Einen Ablauf schreiben

Ein Ablauf ist ein Python-Modul unter `.ultraloom/flows/<name>.py`. Sein
Name muss ein schlichter Bezeichner sein. Das Modul definiert zwei Dinge
auf Modulebene:

```python
from dataclasses import dataclass

from ultraloom.graph import END, CodeNode, GateNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    note: str = ""


flow: Graph[Data] = Graph("greet", start="write")
flow.add(CodeNode("write", lambda d: {"note": "hello"}))
flow.add(
    GateNode(
        "approve",
        question=lambda d: f"send {d.note!r}?",
        apply=lambda d, answer: {"note": answer},
    )
)
flow.edge("write", "approve")
# Jeder Knoten braucht einen Ausweg, auch der letzte: Er geht Richtung END.
flow.edge("approve", END)

initial = Data()
```

`flow` muss ein `Graph` sein; `initial` ist die eingefrorene Dataclass, von
der der Lauf ausgeht. Das Modul wird bei jedem Laden ausgeführt und nie in
`sys.modules` registriert.

### Das Journal, und was ein Resume nachspielt

Ein `run` führt jeden Knoten aus, den er erreicht. Das Journal wird nur
gelesen, während ein Gang einen anderen *nachzeichnet*: Ein `replay`
zeichnet vom ersten bis zum letzten Eintrag nach, ein `resume` zeichnet bis
zu der Stelle nach, an der der frühere Lauf stehen blieb, und arbeitet von
dort wirklich.

Was nachgezeichnet wird, hängt an der *Eingabe* eines Knotens — seinem
Namen und den Daten, die er sah —, nicht an seinem Code. Ändert man einen
Knoten mitten in einem Lauf und spielt erneut ab, kommt das alte Ergebnis
aus dem Journal zurück. Wenn ein Knoten sich ändert, braucht es einen
frischen Lauf.

So leistet eine Schleife Arbeit, selbst wenn sie ihre Fracht unangetastet
lässt. `max_visits` hebt die Obergrenze eines Knotens, damit er auf einem
Zyklus sitzen darf, und jeder Durchlauf dieses Zyklus wird wirklich
ausgeführt — genau das braucht ein Knoten, der die Außenwelt misst, ohne
sie zu verändern.

### Exit-Codes

| Code | Bedeutung |
| ---- | ------- |
| 0 | der Befehl gelang; ein Ablauflauf erreichte sein Ende |
| 1 | eine Prüfung schlug fehl, oder der Befehl ließ sich nicht ausführen |
| 2 | argparse wies die Kommandozeile zurück (seine eigene Konvention) |
| 3 | der Ablauf hielt an einem Freigabepunkt an und wartet auf eine Antwort |
| 4 | ein Ablauf stoppte sich selbst; verify-until-green nutzt ihn für die geschützten Testpfade |

## Lizenz

AGPL-3.0-or-later. Siehe `LICENSE`.
