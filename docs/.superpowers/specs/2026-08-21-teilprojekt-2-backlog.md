# Backlog aus Teilprojekt 1 für Teilprojekt 2

Diese Datei hält fest, was während der Ausführung von Teilprojekt 1 bewusst
liegen gelassen wurde. Sie ist kein Fehlerbericht: jeder Punkt wurde gesehen,
beurteilt und mit Begründung verschoben. Die Arbeitsspuren, aus denen sie
stammt, sind nach dem Abschluss gelöscht worden — diese Datei ist das, was
davon neben dem Code weiterlebt.

## Entwurfsentscheidungen, die offen sind

**Zeitgrenze für Prüfkommandos.** `checks.py` ruft `subprocess.run` ohne
`timeout` auf. Ein hängender Linter blockiert `run_all` unbegrenzt und gibt
keine Ausgabe — die Prüfkette sieht dann aus, als täte sie nichts. Der Plan
hat die Zeitgrenze nicht vorgesehen; sie ist eine Entwurfsentscheidung
(welche Grenze, und wird eine Überschreitung ein rotes `CheckResult` oder ein
Abbruch?), keine Reparatur. **Dies ist der oberste Punkt der Liste.**

**Der Journal-Cache ist unbedingt.** Ein Knoten mit einem `ok`-Eintrag unter
seinem `(Name, input_hash)` liefert dessen Delta zurück, statt zu laufen — auch
außerhalb des Replay-Modus. Folge: ein begrenzter Zyklus ist wirkungslos, wenn
seine Nutzlast sich nicht bei jedem Durchlauf ändert, und ein Bibliotheksnutzer,
der `run()` zweimal auf demselben Journal aufruft, bekommt beim zweiten Mal
nichts ausgeführt. Beides ist jetzt dokumentiert (`Runner`-Klassendocstring,
`CodeNode.max_visits`, README) und die Meldung der Besuchsgrenze sagt, wenn ein
Knoten aus dem Journal bedient wurde. Das Abschlussreview hätte den Cache enger
geschlüsselt — auf „wir betreten einen Lauf erneut" statt „irgendein Eintrag
existiert". Dagegen steht, dass der Schlüssel das ist, was der
Golden-Journal-Test festnagelt; eine Änderung berührt Wiederaufnahme, Wiedergabe
und Besuchsgrenze gleichzeitig. Wenn Teilprojekt 2 Wiederholschleifen braucht,
ist das die erste Frage.

**Schema-Semantik des Modell-Adapters.** `_schema_of` verlangt inzwischen eine
eingefrorene Dataclass aus Skalarfeldern und verweigert alles andere mit einem
`ModelError`, statt es still zu `"string"` zu machen; `required` wird für Felder
ohne Default gesetzt. Was fehlt, ist eine Entscheidung darüber, wie reichhaltig
`AgentNode.schema` sein darf — verschachtelte Dataclasses, Listen, Optionals.

**`mcp__<server>` ohne Werkzeugsegment.** `resolve_tools` erzeugt Bezeichner der
Form `mcp__<server>`, SDK-Bezeichner sind `mcp__<server>__<tool>`. Der Adapter
reicht die serverweite Form unverändert an `allowed_tools` (eine
Berechtigungsregel) und filtert sie aus `tools` (der Obergrenze eingebauter
Werkzeuge, die diesen Namen nicht kennt). Abgeleitet aus dem Parser des SDK,
nicht gegen einen laufenden MCP-Server gemessen.

## Was ein echter Lauf noch beweisen muss

Der Contract-Test (`uv run pytest -m contract`) ist nie gelaufen — er braucht
Credentials und Netz. Introspektion belegt die *Feldnamen und Typen* des SDK;
was sie nicht belegt: dass `usage["output_tokens"]` tatsächlich gefüllt wird und
dass `structured_output` unter `--json-schema` ein `dict` trägt. Solange das
offen ist, ist die Token-Abrechnung unbestätigt. `usage.get("output_tokens", 0)`
liefert bei einer Umbenennung still Kosten von 0 — der Drift-Wächter kann
Dictionary-Schlüssel strukturell nicht abdecken.

## Was das Abschlussreview nachgetragen hat

Vier Punkte, die während der Ausführung von Teilprojekt 2 gesehen und verschoben
wurden und bis zum Abschlussreview nur im Ausführungsledger standen — der ist
git-ignoriert und stirbt mit dem Arbeitsbereich.

**Die Zeitgrenze tötet nur das Kind, nicht die Enkel.** `checks._run` ruft
`subprocess.run(..., timeout=…)` — die Grenze aus §8 der Spec, Vorgabe 600
Sekunden. `subprocess.run` beendet bei Zeitüberschreitung **den direkten
Kindprozess** und ruft danach `communicate()`, um dessen Ausgabe einzusammeln.
Hält ein überlebender Enkel dieselben Pipe-Enden noch offen, kommt dieser Aufruf
nicht zurück, und der Lauf hängt genau dort unbegrenzt, wo die Grenze ihn
gerade davor bewahren sollte. Das ist kein Randfall: `uv run pytest` ist eine
Kette aus mindestens zwei Prozessen, ein Godot-Starter ebenso, und jede Prüfung,
die über ein Präfix aus `[exec].prefix` läuft, hat dieselbe Form. Verschoben,
weil die Reparatur die Prozessführung austauscht — `Popen` mit einer
Prozessgruppe beziehungsweise einem Job-Objekt unter Windows, `kill` auf die
ganze Gruppe, und ein zweites, kürzeres Zeitfenster für das Einsammeln der
Ausgabe. Kosten des Liegenlassens: die Zeitgrenze ist auf genau den Prüfketten
wirkungslos, für die sie geschrieben wurde. **Dies ist der wichtigste der vier.**

**Committet der Reparateur, sieht die Wache nichts.** `guard` misst über
`git status`, also über den *Arbeitsbaum*. Ein Agent, der seine Änderung
committet, hinterlässt einen sauberen Baum: `changed_files` meldet nichts, kein
Pfad wird geprüft, und eine geänderte Testdatei geht durch. Heute entschärft,
nicht gelöst — das Werkzeugprofil `edit` enthält kein Bash, der Agent hat also
keinen Weg zu `git commit`. Verschoben, weil die härtere Grundlage eine andere
Messung wäre: der Vergleich gegen einen beim Laufstart festgehaltenen
Ausgangs-Commit statt gegen den Arbeitsbaum. Das berührt die Grundlinie, den
Fall „Projekt ohne Repository" und die Frage, was bei einem Lauf auf einem
Detached Head gilt. Kosten: die Sperre hängt an einer Profilentscheidung, die
anderswo aus einem ganz anderen Grund gelockert werden kann.

**Das Pausenfenster gehört niemandem.** Die Grundlinie wird beim `run`
aufgenommen und im `.flow`-Marker mitgeführt. Ändert ein Mensch zwischen `run`
und `resume` eine geschützte Datei — legitim, an seinem eigenen Baum —, steht
sie in keiner Grundlinie: nicht in der aufgezeichneten, denn die ist älter, und
eine neue wird bewusst nicht genommen. Die Wache lastet sie dem Reparateur an,
Exit 4 gegen einen Unschuldigen. Verschoben, weil die naheliegende Abhilfe die
Lücke aufmacht, gegen die die Aufzeichnung überhaupt existiert: nähme `resume`
eine frische Grundlinie, wäre alles, was der Reparateur vor der Pause schon
geändert hat, entschuldigt. Eine ehrliche Lösung müsste die beiden Urheber
auseinanderhalten können, und dazu fehlt jeder Anhaltspunkt. Kosten: gering,
solange `verify_until_green` kein Gate hat — der Ablauf pausiert heute nie. Der
Punkt wird scharf, sobald Teilprojekt 4 die Gate-Variante der Testsperre baut.

**Reihenfolge zwischen Prüfungen** stand schon oben, aus dem space-Lauf, und ist
dort als oberster Punkt der Liste vermerkt.

## Kleinere offene Punkte

- `runner._why_it_looped` erklärt die Besuchsgrenze erst, wenn sie erreicht ist.
  Ein Gate-Zyklus mit gleichbleibender Nutzlast und großzügigem `max_visits`
  dreht viele Durchläufe durch den Cache, bevor irgendetwas gesagt wird.
- Eine Antwort, deren Pause-Hash der Lauf nie erreicht, wird still verworfen.
  Praktisch nur erreichbar durch ein von Hand bearbeitetes Journal oder einen
  zwischen Pause und Wiederaufnahme geänderten Graphen.
- `list_flows` filtert auf Identifier und *verschweigt* damit eine Datei wie
  `my-flow.py`, statt zu erklären, warum sie unbrauchbar ist. Gehört zur
  Diagnose-Arbeit an der CLI.
- `tests/test_config.py` trägt noch einen Grenztest, der Quelltext durchsucht —
  dieselbe Redundanz gegenüber `test_module_boundary.py`, die anderswo bereits
  entfernt wurde.
- Der Nebenläufigkeitstest in `tests/test_checks.py` misst Wanduhrzeit. Er ist
  sorgfältig relativ formuliert, bleibt aber der einzige Flake-Kandidat der
  Suite.
- `src/ultraloom/flows/__init__.py` ist ein leeres Paket, das niemand
  importiert — der Platzhalter für die mitgelieferten Abläufe aus Teilprojekt 2.
- `PendingGate` hat ein drittes Feld bekommen (`input_hash`). Positionale
  Konstruktion durch Fremdcode bricht; vor 0.1.0 unkritisch, aber es ist eine
  Signaturänderung.
- Der Exit-Code für „wartet an einem Freigabepunkt" ist von 2 auf 3 gewandert,
  damit er nicht mit argparses eigenem Nutzungsfehler kollidiert. Dokumentiert in
  der README.

## Eine Lehre, die teurer war als die anderen

Der schwerste Fehler des Teilprojekts — `resume` mit einer Antwort verwarf jedes
Delta vor dem Freigabepunkt und zerbrach die Wiedergabe — hat ein Aufgaben-Review,
eine Fix-Runde und zwei darauf aufbauende Aufgaben überlebt. Der Grund war nicht
Nachlässigkeit: **jede Gate-Fixture im Branch setzte das Gate auf `graph.start`**,
und genau dort hebt sich der Fehler auf. Die Fixture stammte aus dem Plan selbst.

Wenn ein Plan eine Test-Fixture vorgibt, erben alle darauf aufbauenden Aufgaben
deren blinde Flecken. Für Teilprojekt 2 heißt das: die Fixtures des Plans sind
Vorschläge, und mindestens eine Variante sollte die Form verlassen, die der Plan
vorgemacht hat.

# Was Teilprojekt 2 hinterlässt

Derselbe Zweck wie oben, eine Runde später: gesehen, beurteilt, mit Begründung
verschoben. Gefunden hat das meiste davon Task 14 — der erste Lauf des Ablaufs
`verify_until_green` in einem fremden Projekt (space: Godot 4, GDScript,
headless gdUnit4, Nano Coverage nach LCOV, kein Typechecker). Die Läufe selbst
stehen auf der Ablaufseite `docs/abläufe/verify-until-green.md`; hier steht, was
davon Arbeit bleibt.

## Der Agentenpfad hängt an einer ungepinnten Fremdversion

**`claude-agent-sdk` ist nicht gepinnt, und die Wahl entscheidet über Lauf oder
Nichtlauf.** Das Extra nennt weder Untergrenze noch Deckel. In der Umgebung von
Task 14 löste das auf `0.2.144` auf, und dieses Rad brachte keine
`_bundled/claude.exe` mit. Das SDK fiel auf das `claude.CMD` aus PATH zurück und
**verweigerte den Start**: „Refusing to execute batch script … no reliable
escaping for cmd.exe exists." Das ist kein Randfall und keine Verschlechterung
der Qualität, sondern ein harter Fehlschlag des gesamten Agentenpfads — jeder
Lauf mit Modell endet mit `outcome=error`, bevor ein einziges Token fließt. Mit
`0.2.143`, das die `.exe` mitbringt, läuft es.

Verschoben, weil die richtige Antwort mehr ist als eine Zahl in
`pyproject.toml`: eine Untergrenze schließt genau den Fall nicht aus, der hier
auftrat — die *neuere* Version war die kaputte —, ein Deckel veraltet, und ein
Rad ohne gebündelte CLI ist auf manchen Plattformen die einzige Wahl. Der
Adapter setzt heute kein `cli_path`; dort müsste die Diagnose vermutlich
ansetzen: beim Start prüfen, ob eine ausführbare CLI erreichbar ist, und
andernfalls sagen, welche der drei Abhilfen gemeint ist. Kosten des
Liegenlassens: ein `uv sync` auf einer frischen Maschine kann den Agentenpfad
ohne Zutun stilllegen, und die Meldung zeigt auf cmd.exe statt auf die
Installation.

**`setting_sources` bleibt ungesetzt.** Der Adapter (`model/agent_sdk.py`)
übergibt das Feld nicht, also gilt der Standard des SDK. Gemessen in space heißt
das: die `SessionStart`- und `Stop`-Hooks des Projekts liefen im Reparaturlauf
mit, `PostToolUse` nicht. Der `SessionStart`-Hook schrieb dabei eine
`override.cfg` in den Arbeitsbaum — ein Seiteneffekt, den weder der Reparateur
verursacht hat noch die Wache erklären kann, und der nur deshalb harmlos blieb,
weil die Grundlinie ihn vor `guard` abdeckte. Verschoben, weil die Entscheidung
eine Richtungsfrage ist und keine Reparatur: Soll ein ultraloom-Lauf die
Werkzeugumgebung des Projekts *erben* (dann ist er realistisch, aber teurer und
mit fremden Seiteneffekten) oder nicht (dann ist er reproduzierbar, aber
verhält sich anders als eine Sitzung von Hand)? Beides ist vertretbar; still
danebenstehen ist es nicht.

Dazu gehört, dass das SDK dem Reparateur die **global konfigurierten
MCP-Server des Benutzers** anbietet. In Lauf 0005 versuchte er,
`mcp__context-mode__ctx_execute` für einen eigenen gdlint-Lauf zu benutzen, und
wurde von `permission_mode: "dontAsk"` abgewiesen. Die Sperre hält also — aber
die Werkzeuge stehen im Prompt, kosten Token und in diesem Fall eine
Werkzeugrunde. `[agent].mcp_servers` sagt heute, was *zusätzlich* erlaubt ist,
und nichts darüber, was ohnehin schon da ist.

## Was die Prüfkette über Werkzeuge annimmt

**Ein Exit-Code ist das ganze Urteil — und manche Prüfwerkzeuge kennen ihn
nicht.** `checks._run` liest `returncode`, sonst nichts. Die Prüfungen von space
sind Claude-Code-Hooks: `coverage_gate.py` meldet seine Befunde über
`hookSpecificOutput` nach stdout und beendet sich **immer** mit 0, weil Exit 2
auf `Stop` dem Agenten das Ende des Zuges verweigern würde. Direkt als
Prüfkommando eingetragen las ein *fehlender* LCOV-Bericht als bestandene
Coverage-Prüfung. Das ist genau der eine Fehlschlag, den `verify-until-green`
nie erzeugen darf, und ultraloom kann ihn strukturell nicht bemerken. In space
steht deshalb eine dünne Hülle davor, die dieselben `findings()` ruft und nur
den Kanal wechselt. Verschoben, weil die Alternative — Ausgabe deuten statt
Exit-Code lesen — eine schlechtere Regel wäre: sie rät. Was fehlt, ist nicht
Mechanik, sondern eine gut sichtbare Warnung in der Dokumentation: **jedes
Prüfkommando, das aus einem Hook-Skript kommt, ist daraufhin anzusehen, ob es
seinen Befund im Exit-Code trägt.** Kosten: ein Projekt, das das übersieht,
bekommt eine grüne Prüfung, die nie etwas geprüft hat.

**Eine Prüfart, ein Kommando.** `config._KINDS` erlaubt je Art genau eine
Zeichenkette. space lintet mit zweien: `gdlint` und `gdformat --check` laufen
über dieselben Verzeichnisse und sind beide „lint". Die Konfiguration von space
fährt heute nur `gdlint`; `gdformat` fehlt damit gegenüber dem, was das Projekt
selbst prüft. Der Ausweg existiert — ein Skript unter `.ultraloom/checks/`, das
beide ruft —, verlagert aber Konfiguration in ausführbaren Code, den niemand
liest. Verschoben, weil die naheliegende Erweiterung, eine Liste statt einer
Zeichenkette, sofort Folgefragen aufmacht: Läuft nach dem ersten roten Kommando
noch das zweite? Wie sieht der Bericht aus, den der Reparateur bekommt? Die
Presets tragen die Antwort in Ansätzen (`measure` plus `argv`), aber für
mehrere gleichrangige Kommandos ist sie nicht gebaut.

**Zwischen Prüfungen gibt es keine Reihenfolge.** Spec 9.4 nimmt an, Prüfungen
seien unabhängig, und lässt sie deshalb nebenläufig laufen. In space ist der
LCOV-Bericht ein Nebenprodukt des Suitenlaufs: das Coverage-Tor liest den
Bericht, den die Suite erst acht Minuten später schreibt, und meldet „no
coverage report". Das Python-Preset löst dasselbe Problem mit einem
`measure`-Schritt, der die Suite ein zweites Mal fährt — für eine Godot-Suite
keine Option, weil das weitere acht Minuten kostet. Das Tor von space löst es
über Reihenfolge und reicht einen Zeitstempel weiter (`measured_after`), damit
ein alter Bericht nicht als neuer durchgeht. Verschoben als Entwurfsfrage: eine
Abhängigkeit „coverage nach test" ist leicht gesagt und berührt die
Nebenläufigkeit, den Bericht und die Frage, ob eine Prüfung ausfällt, wenn die
Prüfung, auf die sie wartet, rot ist. **Dies ist der oberste Punkt dieser
Liste** — er ist der Grund, warum in space kein grüner `precommit`-Lauf steht.

## Kleinere offene Punkte

- **Stille Präzedenz bei Coverage.** `resolve_check` prüft
  `config.coverage_report` **vor** `config.commands`. Wer sowohl
  `[verify.coverage].report` als auch ein `coverage`-Kommando setzt, bekommt
  ohne Warnung das erste. Die Reihenfolge ist jetzt auf der Ablaufseite
  dokumentiert; eine Warnung beim Laden wäre ehrlicher, ist aber eine
  Entscheidung darüber, wie viel `load_config` beurteilen darf.
- **Die Schwelle wird nicht durchgesetzt.** `[verify.coverage].threshold` wird
  gelesen und weitergereicht, aber kein Kommando bekommt sie — durchgesetzt
  wird, was das Coverage-Werkzeug selbst eingestellt hat. `ultraloom check
  coverage` sagt das in einer eigenen Zeile; die Ablaufseite sagt es jetzt
  auch. Was fehlt, ist die Entscheidung, ob der Schlüssel überhaupt bleiben
  soll.
- **Ein Projekt mit Build-Cache braucht einen Einrichtungsschritt, von dem der
  Ablauf nichts weiß.** *Erledigt für Godot:* fehlt
  `.godot/global_script_class_cache.cfg`, sind `test` und `coverage` rot mit der
  Quelle `"unready"`, bevor eine Engine startet. Offen bleibt die allgemeine
  Form — jede andere Sprache mit Build-Cache bringt ihre eigene Markerdatei mit,
  und die Vorbedingung steht heute als Sonderfall im Code statt als Feld neben
  dem Preset. Das Ventil ist `[verify].godot_import = false`, für ein Projekt,
  das den Import selbst fährt oder gar nicht über eine Engine testet; ein
  weiterer Sonderfall, den die allgemeine Form mit auflösen müsste.
- **`_marker` ist first-hit über `PRESETS`.** *Gesehen:* ein Godot-Projekt, das
  zusätzlich eine `pyproject.toml` trägt — für seine Werkzeugkette, für Skripte
  —, wird als Python-Projekt erkannt; die Godot-Presets greifen nicht, und die
  neue Import-Vorbedingung greift ebenfalls nie. *Warum verschoben:*
  vorbestehendes Verhalten der Erkennung, aber die Vorbedingung erbt es still,
  und das ist neu. Eine Reparatur heißt zu entscheiden, was bei mehreren Markern
  gilt — Reihenfolge, Nachfrage, ein expliziter Schlüssel —, und das ist eine
  Entwurfsfrage über die ganze Prüfkette, nicht über diese eine Vorbedingung.
  *Was es kostet:* diese Entscheidung, plus einen Weg, wie ein Projekt seine Art
  selbst benennt.
- **Die Sitzungs-Hook-Falle kann ultraloom nicht prüfen.** *Gesehen:* ein
  Editor- oder Import-Lauf schreibt `project.godot` um, ein Coverage-Addon
  trägt dabei einen zweiten Sitzungs-Hook ein; beide instrumentieren, beide
  leeren den Datenspeicher, und ganze Dateien kommen mit null Treffern aus dem
  Zusammenführen, obwohl ihre Suiten grün liefen. Das Coverage-Tor liest das als
  nicht erreichte Zeilen. *Warum verschoben:* die Prüfung verlangt Wissen, das
  die Prüfkette bewusst nicht hat — welche Addons es gibt, wie ihre Hooks
  heißen, welcher davon einer zu viel ist. Eine Liste von Addon-Namen in
  ultraloom wäre am Tag nach dem nächsten Addon falsch. *Was es kostet:* ein
  Format, in dem ein Projekt seine eigenen Vorbedingungen als Daten beschreibt
  (Datei, Muster, Meldung), plus die Entscheidung, wie viel davon ultraloom
  auswerten darf, ohne zum halben Linter für fremde Konfigurationsdateien zu
  werden. Bis dahin fängt es das Prüf-Tor des Projekts selbst ab, und die
  Ablaufseite benennt die Falle.
- **`uv pip install -e` bricht an einem absoluten Windows-Pfad mit `#`.** Die
  Meldung nennt `C:\Users\micro\Documents` und behauptet, dort liege kein
  Python-Projekt: der Pfad wird an `#` abgeschnitten. Ein relativer Pfad
  funktioniert. Fremdes Werkzeug, aber es kostet beim nächsten Mal wieder eine
  Viertelstunde, und die Installationsanleitung von ultraloom nennt absolute
  Pfade.
- **Die `unavailable`-Übersetzung steht an zwei Stellen**
  (`checks._run_or_report` und `flows/verify_until_green._result_for`). Bewusst
  asymmetrisch: der Ablauf fängt nur `CheckUnavailableError`, `run_all`
  zusätzlich alles andere, damit ein echter Fehler im Ablauf sichtbar bleibt,
  statt still als rote Prüfung zu enden. Als Ermessensfrage festgehalten, nicht
  als Schuld.
- **Der Beweis für die Testsperre fehlt weiterhin.** Fünf Läufe in zwei
  Projekten haben versucht, einen echten Agenten dazu zu bringen, eine
  Testdatei anzufassen; keiner hat es geschafft. Die Wache ist durch Unit-Tests
  abgedeckt und gegen ein echtes Modell unbewiesen.
