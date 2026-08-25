# Sitzungs-Hooks — Entwurf

Stand: 2026-08-25. Status: zur Durchsicht.

## Warum

Die Policy prüft einzelne Werkzeugaufrufe, bevor sie geschehen. Was sie nicht
kann: sagen, ob die Arbeit am Ende grün ist, ob ein Fehler an der Datei
auffällt, die gerade geschrieben wurde, ob ein pausierter Lauf auf eine Antwort
wartet — oder ob ein Subagent etwas getan hat, das sein Bericht verschweigt.

Fünf Ereignisse, fünf Fragen:

| Ereignis | Frage |
| --- | --- |
| `PostToolUse` | Ist die Datei, die gerade geschrieben wurde, für sich genommen in Ordnung? |
| `Stop` | Ist die Arbeit dieses Zuges grün, bevor der Zug endet? |
| `SessionStart` | Wartet aus einer früheren Sitzung noch etwas auf eine Antwort? |
| `SubagentStart` | Wo stand das Remote, bevor der Subagent lief? |
| `SubagentStop` | Was hat der Subagent getan, das in seinem Bericht fehlt? |

(`SubagentStart` kam bei der Umsetzung dazu: `SubagentStop` allein hat kein
Davor, und Task 1 hat gemessen, dass beide Ereignisse dieselbe `agent_id`
tragen.)

`SubagentStop` steht hier, weil der Vorfall, der in CLAUDE.md als Warnung
festgehalten ist, genau diese Form hatte: ein Implementierer-Subagent hat
`master` nach `origin` gepusht, und sein Bericht erwähnte es nicht.

## Verhältnis zur Policy

Die Policy ist Verhinderung, diese Hooks sind Feststellung. Beide werden
gebraucht: `PreToolUse` sperrt `git push`, aber nur, wenn der Befehl über ein
Werkzeug läuft, dessen Payload die Policy versteht. Ein Subagent, der über
einen Weg pusht, den keine Regel kennt, wird von der Policy nicht gefasst — von
einem Vergleich der Remote-Refs vor und nach seinem Lauf schon.

Gemeinsam ist beiden der Aufbau: die Logik liegt als Unterkommando in `src/`
unter der 100-%-Regel, die Datei unter `.claude/` ist die Verdrahtung.

## Was gebaut wird

Fünf Unterkommandos unter `ultraloom hook <name>`:

    ultraloom hook post-edit       # PostToolUse
    ultraloom hook stop            # Stop
    ultraloom hook session-start   # SessionStart
    ultraloom hook subagent-start  # SubagentStart
    ultraloom hook subagent-stop   # SubagentStop

Alle lesen ihre Payload von stdin, wie `ultraloom policy hook`, und benutzen
denselben Adapterschnitt: eine Schicht, die Claude Code versteht, und darunter
Funktionen, die es nicht müssen.

### Modulgrenze

`ultraloom.hooks.*` darf `ultraloom.config`, `ultraloom.checks`,
`ultraloom.journal` und `ultraloom.worktree` benutzen — anders als die Policy,
denn diese Hooks *sind* Prüfläufe. Nichts aus dem Harness (`graph`, `state`,
`runner`, `model`, `discovery`). `post-edit` und `stop` laden `checks`
ohnehin; `session-start` und `subagent-stop` dürfen es nicht, und
`test_module_boundary.py` hält das fest.

## Die fünf Hooks

### PostToolUse — `hook post-edit`

Matcher `Write|Edit|NotebookEdit`. Formatiert die geschriebene Datei mit
`ruff format` und fährt danach das Profil `edit` (lint + types, nach der
Umsetzung gemessen: 1,5 bis 2 s). Befunde gehen per Exit 2 auf stderr; das
Werkzeug ist zu diesem Zeitpunkt längst gelaufen, „blockieren" heißt hier also
nur, dass der Befund an der Datei ankommt, die ihn ausgelöst hat, statt erst
eine Minute später im Stop-Gate.

Notebooks bekommen kein `ruff format` — `.ipynb` ist JSON, und ein Formatierer,
der die Datei nicht versteht, macht sie kaputt. Der Pfad wird dann übersprungen,
nicht geraten.

### Stop — `hook stop`

Fährt `check all` (nach der Umsetzung gemessen: 60 bis 62 s) — oder mit
`--checks` nur ein Profil — und blockt mit Exit 2, bis alles grün ist.

**Kurzschluss zuerst:** Ist seit der letzten grünen Prüfung nichts dazugekommen,
endet der Hook sofort mit 0 — gemessen rund 300 ms. Ein Zug, der nur gelesen und
geantwortet hat, kostet sonst eine volle Minute für eine Antwort, die schon
feststeht.

Gemessen wird das mit `worktree.changed_since(root, base)` — **nicht** mit
`changed_files`, das gar keine Basis nimmt. Der Unterschied ist derselbe, den
`2026-08-23-guard-basis-commit-design.md` für den `guard`-Knoten beschreibt: was
ein Zug *committet* hat, verschwindet aus `git status`, und ein Gate auf
`changed_files` schwiege genau dann, wenn jemand committet hat.

Die Basis einer Sitzung entsteht in zwei Schritten, und beide werden gebraucht:

1. `session-start` legt `head_commit` als Anfangsbasis ab, damit schon der
   **erste** Zug eine hat.
2. `stop` schreibt sie nach jedem **grünen** Durchgang auf das aktuelle
   `head_commit` fort. Ein einmal grün geprüfter Commit taucht damit nie
   wieder auf — ohne das liefe nach dem ersten Commit jeder weitere Zug der
   Sitzung die volle Kette.

**`--checks` fährt ein Profil statt der ganzen Kette.** Das Argument nimmt,
was `ultraloom run --checks` nimmt — einen Profilnamen aus `[verify.profiles]`
oder eine kommagetrennte Liste von Arten — und wird von demselben `kinds_for`
aufgelöst; ohne das Argument bleibt es bei allen Arten. Der Grund ist die
Trennung zwischen Prüfungen, die den Quelltext lesen, und solchen, die ihn
ausführen: In einem Spielprojekt gemessen kostete ein Zugende mit dem Stop-Gate
36 Minuten, fast alles davon die Godot-Suite (639 s seriell) und der
Coverage-Bericht — fällig am Ende jedes Zuges. Suite und Coverage-Schwelle
gehören ans Commit-Gate, das Gate am Zug fährt die statischen Prüfungen.

Ein Durchgang unter `--checks` schreibt die Basis **nicht** fort. Die Basis
heißt „alles bis hierher ist geprüft"; ein Profil ohne Suite hat das nicht
geprüft, und eine fortgeschriebene Basis versteckte die ungeprüfte Arbeit vor
jedem späteren Zug. Ein unbekannter Name ist Exit 1 mit der Meldung von
`kinds_for` — eine kaputte Konfiguration ist kein Urteil über die Arbeit.

Nach einem **roten** Durchgang bleibt die Basis stehen. Sie fortzuschreiben
hieße, den nächsten Zug kurzzuschließen — das Gate hätte sich selbst
abgeschaltet.

Fehlt die Basis, weil der Hook mitten in einer Sitzung eingeschaltet wurde,
fällt `stop` auf `changed_files` zurück **und sagt das**: eine Messung mit
bekannter Blindstelle darf nicht wie eine vollständige aussehen.

Damit beantwortet das Gate nicht „ist alles seit Sitzungsbeginn grün", sondern
„ist alles grün, was seit der letzten grünen Prüfung dazugekommen ist" — die
Frage, die es beantworten kann, ohne jeden Zug 45 Sekunden zu kosten.

**Block-Zähler:** Höchstens drei Blockaden je Sitzung, danach eskaliert der Hook
an den Menschen und lässt den Zug enden. Der Zähler löst zugleich das
Schleifenproblem: ein Stop-Hook, der immer wieder blockt, hält eine Sitzung
sonst endlos in Bewegung.

Das Feld `stop_hook_active` gibt es — Task 1 hat es gemessen: beim ersten
Aufruf `false`, beim erzwungenen zweiten `true`. Gelesen wird es trotzdem
**nicht**. Es sagt „schon einmal geblockt", nie *wie oft*, kann die Obergrenze
also nicht tragen; und eine zweite Quelle, die dem Zähler widersprechen kann,
macht das Gate genau dann unerklärlich, wenn jemand versucht, aus ihm
herauszukommen.

**Aushängen:** Die Datei `.claude/.no-verify` setzt das Gate aus, solange sie
existiert. Für den Fall, dass jemand bewusst rot abgeben will.

### SessionStart — `hook session-start`

Liest `.ultraloom/runs/` und meldet Läufe, die an einem Gate auf eine Antwort
warten, samt der Frage und der Zeile, mit der man sie beantwortet
(`ultraloom resume <id> --answer …`). Ein pausierter Lauf ist sonst in keiner
neuen Sitzung sichtbar.

Blockiert nie; ein Befund geht als Kontext in die Sitzung.

### SubagentStop — `hook subagent-stop`

Vergleicht den Zustand vor und nach dem Subagenten und meldet, was er
verändert hat:

- **Remote-Refs.** `git ls-remote origin` vor und nach dem Lauf. Jede
  Abweichung ist ein Push und wird gemeldet — laut CLAUDE.md ist das eine
  Entscheidung, die einem Menschen gehört.
- **HEAD und Zweig.** Neue Commits werden mit ihrer Kurzfassung genannt.
  Commits darf ein Lauf machen; unsichtbar bleiben sollen sie nicht.

Der Schnappschuss davor entsteht beim ersten Aufruf je `agent_id`; die Payload
trägt `agent_id` und `agent_type`. Fehlt der Schnappschuss — etwa weil der Hook
erst mitten in der Sitzung eingeschaltet wurde — wird das gemeldet und nichts
behauptet.

**Kein Exit 2.** Der Push ist zu diesem Zeitpunkt geschehen; den Subagenten am
Aufhören zu hindern, macht ihn nicht rückgängig. Der Wert liegt in der
Sichtbarkeit, und die braucht kein Blockieren.

## Zustand

`.ultraloom/hooks/<session_id>.json` hält, was zwischen zwei Aufrufen überdauern
muss: den Block-Zähler des Stop-Gates, den Basis-Commit der Sitzung und die
Remote-Schnappschüsse je `agent_id`. Eine Datei je Sitzung, damit zwei gleichzeitige Sitzungen im selben
Checkout sich nicht gegenseitig den Zähler verstellen.

Das Verzeichnis gehört in `.gitignore` und in die Pfadregeln der Policy: ein
Agent, der seinen eigenen Block-Zähler zurücksetzt, hat das Gate abgeschafft.

## Exit-Protokoll

Wie bei der Policy und aus demselben Grund:

    0  in Ordnung, oder bewusst übersprungen
    1  interner Fehler — blockt nie
    2  Befund; was das bewirkt, hängt am Ereignis

Was Exit 2 je Ereignis bedeutet, ist nicht dasselbe, und die Spec hält es
ausdrücklich fest, weil ein Irrtum hier still ist: bei `Stop` verhindert es das
Beenden — bei `SubagentStop` täte es das auch, weshalb dieser Hook es nie
zurückgibt (siehe seinen Abschnitt oben) —, bei `PostToolUse` zeigt es nur den
Text an den Agenten, bei `SessionStart` nur an den Menschen.

**Ein abgestürzter Prüflauf ist Exit 1, ein roter Prüflauf Exit 2.** Die
Unterscheidung ist in diesem Repo besonders heikel, weil die Hooks ultraloom
mit ultraloom prüfen: ein kaputtes `checks.py` darf die Sitzung nicht
einsperren, aber eine rote Kette muss sie anhalten.

**Exit 1 nur, wenn die Kette gar kein verwertbares Urteil geliefert hat**, also
**jedes** rote Ergebnis `unavailable` ist. Ein unavailable neben einem echten
Befund ergibt Exit 2. Die ursprüngliche Fassung fragte `any` statt `all` und
traf damit auch den Fall „diese Prüfart gibt es in diesem Projekt legitim
nicht": Ein GDScript-Projekt hat keinen Typechecker und konfiguriert kein
`types`-Kommando, trug also in jedem einzelnen Lauf ein unavailable. Das Gate
fuhr dort am 2026-08-25 die volle Kette über 565 s, fand einen echten Verstoß
und beendete mit Exit 1 und „the chain could not run" — es konnte strukturell
nie blockieren und setzte nie etwas durch. Die unavailable-Ergebnisse werden
weiter mitgemeldet, damit der Agent die fehlende Prüfart sieht; sie verdecken
die Befunde daneben nicht mehr.

## Kosten

Gemessen am 2026-08-25, Hauptcheckout:

| Hook | Aufwand |
| --- | --- |
| `post-edit` | **1,5 bis 2 s** im Median, einzelne Läufe bis 7 s |
| `stop` | **60 bis 62 s** bei geänderten Dateien, **rund 300 ms** im Kurzschluss |
| `session-start` | Lesen eines Verzeichnisses |
| `subagent-stop` | ein `git ls-remote`, also netzabhängig — Timeout 10 s, und ein Fehlschlag ist eine leere Antwort, kein Exit 1 |

Timeouts in `.claude/settings.json`: `post-edit` 60 s, `stop` 300 s,
`session-start` 20 s, `subagent-start` 30 s, `subagent-stop` 30 s.

Der Wert für `stop` stand hier zuerst mit „rund 45 s" — geschätzt aus der
Prüfkette allein. Nachgemessen am 2026-08-25 im Hauptcheckout: **60 bis 62 s**
für einen vollen Durchgang von `check all`, und **rund 300 ms**, wenn der
Kurzschluss greift. Das Timeout von 300 s bleibt damit fünffach über dem
gemessenen Wert; der Kurzschluss ist der Grund, dass ein Zug ohne Änderung
nichts kostet.

Der Wert für `post-edit` stand hier zuerst mit „rund 1 s" — das war die Summe
der beiden Prüfungen (lint 337 ms, types 664 ms) ohne den Prozessstart und ohne
`ruff format`. Nach der Umsetzung gemessen: Median 1,5 bis 2 s, einzelne Läufe
bis 7 s, wobei die Ausreißer aus der Auflösung von `uv` kommen und nicht aus
dem Formatierer (der misst allein 131 bis 137 ms). Das ist der Preis nach
**jedem** Schreibvorgang — spürbar, aber innerhalb des Timeouts. Fällt er
jemandem zur Last, ist der nächste Hebel nicht der Formatierer, sondern der
Prozessstart.

## Tests

Je Hook ein Modul unter `tests/hooks/`, dazu die Adapterschicht wie bei der
Policy: Payload-Fixtures für die Exit-Codes, reine Funktionen für die
Entscheidungen. Der Block-Zähler, der Kurzschluss des Stop-Gates und der
Vergleich der Remote-Refs werden gegen echte Repositories in `tmp_path` mit
`subprocess` geprüft, nie gegen eine Attrappe — Commits dort brauchen
`-c user.name=t -c user.email=t@t`, weil keine globale Identität vorausgesetzt
werden darf.

100 % Coverage wie im übrigen Repo.

## Gemessen statt vermutet

Die beiden offenen Punkte sind beantwortet. Die vollständigen Feldlisten stehen
in `docs/.superpowers/specs/2026-08-25-sitzungs-hooks-payloads.md`; hier nur,
was der Entwurf daraus braucht:

1. **`stop_hook_active` gibt es.** In jeder `Stop`- und `SubagentStop`-Payload,
   beim ersten Aufruf `false`, beim durch Exit 2 erzwungenen zweiten `true`.
   Der Block-Zähler kann sich darauf stützen; er ersetzt ihn nicht, weil das
   Feld nur „schon einmal geblockt" sagt und nicht „wie oft".
2. **`agent_id` und `agent_type` gibt es** bei `SubagentStop`, dazu
   `agent_transcript_path`. Die `session_id` dort ist die der Muttersitzung —
   je Subagent unterscheidet nur `agent_id`.
3. **`SubagentStart` existiert** und trägt dieselbe `agent_id`. Der
   Schnappschuss für `subagent-stop` wird deshalb je Subagent in einem eigenen
   Hook `subagent-start` genommen, nicht gröber je Sitzung in `session-start`.
4. **Mehrere Einträge desselben Ereignisses laufen gleichzeitig**, nicht
   nacheinander: zwei `Stop`-Einträge mit je zwei Sekunden Verweildauer
   starteten 2 ms auseinander und überlappten vollständig. Der Block-Zähler
   gehört deshalb in **einen** Eintrag; zwei Hooks, die ihn beide fortschreiben,
   verlieren Hochzählungen.

Die Sitzungskennung heißt `session_id` und ist über alle Aufrufe einer Sitzung
hinweg stabil.

## Ausdrücklich nicht in diesem Vorhaben

- **Die Worktree-Falle** (`git-dir` == `git-common-dir` unter
  `.claude/worktrees/`). Sie gehört zu `SessionStart`, ist aber ein eigener
  Befund mit eigener Mechanik und bekommt eine eigene Spec.
- **MCP-Werkzeuge in der Policy.** `mcp__<server>__<tool>` kann schreiben und
  wird heute nicht geprüft.
- **Das Ausrollen nach space und iam_backend.**
