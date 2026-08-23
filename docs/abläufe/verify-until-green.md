# verify-until-green

Der erste Ablauf, den ultraloom mitliefert. Er führt die Prüfkette aus, lässt
einen Agenten reparieren, was rot ist, prüft danach, ob der Agent sich an die
Regeln gehalten hat, und beginnt von vorn — bis alles grün ist oder ehrlich rot.

Der Ablauf kennt kein einzelnes Projekt: welche Werkzeuge prüfen und wo die
Tests liegen, kommt beides aus `.ultraloom/config.toml`. Genau das erlaubt es,
denselben Ablauf in einem Python-Paket und in einem Godot-Spiel laufen zu
lassen.

Aufruf:

```bash
ultraloom run verify_until_green [--checks <liste|profil>] [--max-rounds <n>]
```

## Der Graph

```mermaid
flowchart TD
    check -->|kein Fehler| END
    check -->|unreparierbar, stagniert oder Runden aufgebraucht| report_red
    check -->|sonst| repair
    repair --> guard
    guard --> check
    report_red --> END
```

Die Reihenfolge der Kanten aus `check` ist bedeutungstragend: `next_name` nimmt
die erste Kante, deren Bedingung hält, und eine Kante ohne Bedingung hält immer.
Die unbedingte Kante nach `repair` steht deshalb zuletzt.

Die Kante `report_red --> END` wird nie genommen — `report_red` wirft immer. Sie
steht da, weil `validate()` einen Knoten ohne Ausgang ablehnt und eine Sackgasse
kein Ausgang ist.

## Die Knoten

| Knoten | Art | `max_visits` | Was er tut |
| --- | --- | --- | --- |
| `check` | code | `max_rounds + 1` | Führt die gewählten Prüfungen in Stufen aus — nebenläufig nur innerhalb einer Stufe —, sammelt die roten, erhöht den Rundenzähler und merkt sich, was die vorige Runde gefunden hatte. |
| `repair` | agent | `max_rounds + 1` | Bekommt den Bericht der roten Prüfungen und repariert die Quellen. Werkzeugprofil `edit`, Effort `high`. |
| `guard` | code | `max_rounds + 1` | Liest den Arbeitsbaum über `git status` und bricht ab, wenn der Reparateur geschützte Pfade angefasst hat. |
| `report_red` | code | 1 | Beendet den Lauf rot und sagt, warum. |

Jede Obergrenze auf dem Zyklus ist `max_rounds + 1`, die von `check`
eingeschlossen. Die Besuchsgrenze ist der Notnagel des Ausführers gegen eine
entlaufene Schleife; das Tor, das dieser Ablauf tatsächlich schließt, ist der
Rundenzähler. Der Notnagel muss deshalb *über* dem Tor liegen und nie auf
gleicher Höhe: gleichauf wären `repair` und `guard` bei `--max-rounds 1`
Ein-Besuch-Knoten auf einem Zyklus — was der Graph rundheraus ablehnt — und
jeder Lauf, der seine Obergrenze erreicht, endete an der Wache des Ausführers,
ohne Exit-Code und mit einer Meldung über `max_visits` statt über den Grund, aus
dem er rot ist.

## Der Zustand

`VerifyState`, eine eingefrorene Dataclass:

| Feld | Typ | Bedeutung |
| --- | --- | --- |
| `kinds` | `tuple[str, ...]` | Welche Prüfungen dieser Lauf ausführt. Kommt aus `--checks` oder ist die volle Liste. |
| `report` | `str` | Der gerenderte Bericht der roten Prüfungen — nach `repair` stattdessen dessen Zusammenfassung. |
| `failing` | `tuple[str, ...]` | Die Arten, die in der letzten Runde rot waren. |
| `unfixable` | `tuple[str, ...]` | Davon die, die keine Reparatur schließen kann. |
| `blocked` | `tuple[str, ...]` | Davon die, die gar nicht gelaufen sind, weil ihr Vorgänger rot war. Weder reparierbar noch außer Reichweite — und diese dritte Antwort muss bis zur Abbruchentscheidung durchhalten. |
| `brief` | `str` | Derselbe Bericht, gekürzt auf das, was der Reparateur zu sehen bekommt. |
| `touched` | `tuple[str, ...]` | Was `git status` nach dem Reparaturlauf als geändert meldet. |
| `rounds` | `int` | Wie oft `check` gelaufen ist. |
| `previous_failing` | `tuple[str, ...]` | Was die vorige Runde gefunden hat. Eine Kantenbedingung sieht nur einen Zustand, und „dieselben Prüfungen schon wieder" ist sonst nicht beantwortbar. |

`report` und `brief` tragen denselben Befund in zwei Längen. Der Prompt des
Reparateurs bekommt `brief`: je Prüfung höchstens 200 Zeilen, Kopf und Fuß
erhalten und eine Zeile dazwischen, die sagt, wie viel fehlt. Der Fuß wiegt
schwerer als der Kopf, weil pytest seine Zusammenfassung ans Ende schreibt. Ins
Journal geht `report` mit der **vollständigen** Ausgabe — gekürzt wird nur, was
Token kostet, nie das, was einen Lauf im Nachhinein auswertbar macht.

Zwischen `repair` und dem nächsten `check` liest der Zustand absichtlich
gemischt: `failing` und `unfixable` tragen noch die Werte der alten Runde,
während `report` bereits die Zusammenfassung des Reparateurs hält. `guard` ist
der Knoten, der ihn so sieht.

`changed` — die Behauptung des Modells, es habe etwas geändert — wandert bewusst
*nicht* in den Zustand. Die Wahrheit darüber steht im Arbeitsbaum, und das Wort
des Modells ist daneben nichts wert.

## Unreparierbar

Ein rotes Ergebnis gilt als außer Reichweite, wenn

- seine Art in `UNFIXABLE` steht — derzeit `coverage`: eine Lücke zu schließen
  heißt Tests zu schreiben, und genau das verbietet `guard`; oder
- seine Quelle `"unavailable"` ist, die Prüfung sich also gar nicht auflösen
  ließ. Sie ist rot, aber keine Änderung am Projekt behebt das — für GDScript
  gibt es keinen Typechecker, und einen Agenten zu bitten, ein nicht
  installiertes Werkzeug zu reparieren, heißt ihn zu bitten, es zu erfinden;
  oder
- seine Quelle `"unready"` ist: die Prüfung ließ sich auflösen, aber das
  Projekt ist für sie nicht bereit — siehe *Was ein Godot-Projekt vorher
  braucht*. Der Griff ist ein Import-Lauf, und einen Editor zu starten ist
  nichts, was ein Reparatur-Agent tun soll.

Alle drei beenden den Lauf **nur dann sofort**, wenn nichts Reparierbares
daneben steht. Für ein Projekt, dem ein Werkzeug dauerhaft fehlt, ist das der Normalfall
und keine Ausnahme: in space ist `types` bei jedem einzelnen Lauf unverfügbar.
Vorher endete dort jeder Lauf sofort mit Exit 1; jetzt bekommen die übrigen
Prüfungen ihre Runden, und der Ablauf ruft bis zu `max_rounds` mal das Modell,
wo vorher gar keiner kam. Das ist der gewollte Tausch — wer ihn nicht will,
lässt die unverfügbare Art über `--checks` weg.

Die Quelle `"blocked"` gehört ausdrücklich **nicht** dazu. Eine blockierte
Prüfung ist keine, die niemand schließen kann — sie schließt sich selbst, sobald
ihr Vorgänger grün ist. Wäre sie außer Reichweite, gäbe der Ablauf bei jedem
gewöhnlichen roten Test sofort auf. Und weil `coverage` in `UNFIXABLE` steht,
wird die Quelle **vor** der Art gefragt: ein blockiertes `coverage` ist keine
Deckungslücke, sondern eine Prüfung, die nicht lief.

Der Reparateur sieht sie deshalb auch nicht in der Mängelliste, sondern
darunter, in einer eigenen Zeile:

```
Nicht gelaufen, weil ein Vorgänger rot war: coverage
```

Genannt, damit ein Bericht mit grünem `lint`, grünem `types` und rotem `test`
sich nicht liest, als wäre die Abdeckung geprüft worden. Getrennt, damit klar
ist, dass hier nichts zu reparieren ist: der Griff ist der rote Vorgänger, und
sobald der grün ist, läuft die blockierte Prüfung von selbst wieder mit.

Für die Abbruchentscheidung zählt eine blockierte Prüfung deshalb gar nicht mit:
„außer Reichweite" heißt genau dann, wenn *jede rote, nicht blockierte* Prüfung
außer Reichweite liegt. Ohne diese Ausnahme kostete ein nie importiertes
Godot-Projekt fünf bezahlte Modellrunden — `test` rot mit `unready`, `coverage`
dahinter blockiert, zusammen kein Teilmengenverhältnis mehr und am Ende die
falsche Diagnose „still red after N repair rounds".

## Was ein Godot-Projekt vorher braucht

Ein Godot-Projekt muss **einmal importiert** worden sein, bevor irgendein
Testergebnis dort etwas bedeutet. Der Import legt `.godot/` an; ohne ihn
scheitert die Suite an Dingen, die nicht kaputt sind — oder sie misst gar nichts
und sieht dabei grün aus.

ultraloom prüft das jetzt, statt es zu dokumentieren: Ist die erkannte
Markerdatei `project.godot` und fehlt `.godot/global_script_class_cache.cfg`,
liefern `test` und `coverage` ein rotes Ergebnis mit der Quelle `"unready"` —
**bevor** eine Engine startet. Die Meldung nennt den Griff:

```
this Godot project has never been imported, so nothing measured here would mean anything
run: godot --headless --path . --import
a project whose own check command runs the import sets [verify].godot_import = false
```

`lint` ist bewusst nicht betroffen: `gdlint` liest Quelltext und braucht kein
`.godot/`. Und ultraloom fährt den Import **nicht selbst**. Ein Prüfwerkzeug,
das ungefragt einen Editor startet und den Baum verändert, ist keine Prüfung
mehr.

`.godot/` ist gitignoriert. Jeder frische Checkout und jeder neue Worktree hat
deshalb seinen eigenen Zustand und diese Stufe von vorn — nicht nur ein neues
Projekt.

### Das Ventil

Ein Projekt, dessen eigenes Prüfkommando den Import selbst fährt — oder das gar
nicht über eine Engine testet —, setzt `[verify].godot_import = false`. Dann
greift das Tor nicht.

Der Schlüssel ist nötig, weil das Tor sich sonst nicht abschalten ließe: ein
solches Projekt wäre auf jedem Lauf rot und obendrein außer Reichweite des
Reparateurs — es könnte sich nie selbst heilen. Bewusst ein Schlüssel und keine
Ableitung aus der Herkunft des Kommandos: das Projekt, aus dem diese
Vorbedingung stammt, konfiguriert sein Test-Kommando selbst, und eine Ableitung
hätte den Schutz genau dort abgeschaltet, wo er gemessen nötig war.

Die Meldung nennt den Schlüssel deshalb selbst. Wer blockiert ist, soll den Weg
hinaus lesen können, statt ihn schon zu kennen.

### Die zweite Falle, die ultraloom nicht prüfen kann

Ein Editor- oder Import-Lauf kann `project.godot` umschreiben, und manche
Coverage-Addons tragen dabei einen eigenen Sitzungs-Hook ein. Laufen dann zwei
Hooks, instrumentieren beide und leeren beide den Datenspeicher: ganze Dateien
kommen mit null Treffern aus dem Zusammenführen, obwohl ihre Suiten grün
liefen. Das Coverage-Tor liest die leeren Datensätze als nicht erreichte Zeilen
und meldet eine Lücke, die es nicht gibt.

ultraloom kann das nicht erkennen, weil es keine Addon-Namen kennt — was ein
Sitzungs-Hook ist und welcher davon einer zu viel ist, steht in keinem Wissen,
das die Prüfkette hat. Abfangen kann das nur das Projekt selbst, in seinem
eigenen Vor-Tor: es weiß, welche Hooks in seine `project.godot` gehören, und
kann die Datei prüfen, bevor irgendetwas startet. Der Griff ist, die geänderte
Datei zu verwerfen.

## Der Agent

Werkzeugprofil `edit`, Effort `high`, Schema `RepairResult` mit den Feldern
`summary: str` und `changed: bool`. Nur Skalare, weil das ist, was ein
Modell-Adapter als JSON-Schema beschreiben kann.

Der Prompt (`REPAIR_PROMPT`) übergibt den Bericht und die geschützten Pfade und
stellt vier Regeln auf:

1. Keinen der geschützten Pfade bearbeiten, schwächen, überspringen oder
   löschen. Ein fehlschlagender Test ist ein Befund über die Quelle, kein
   Problem des Tests.
2. Eine Prüfung nicht stummschalten statt sie zu beheben: kein neues `# noqa`,
   `# type: ignore`, `# pragma: no cover` oder sonstige Unterdrückung, und keine
   Änderung an einer Konfigurationsdatei, die eine Schwelle oder ein Regelwerk
   setzt (`pyproject.toml`, `setup.cfg`, `.ruff.toml`, `mypy.ini` und
   dergleichen). Bereits vorhandene, begründete Unterdrückungen dürfen bleiben.
   Wäre eine Prüfung nur durch Stummschalten grün zu bekommen, gehört das in die
   Zusammenfassung und der Code bleibt, wie er ist.
3. So wenig ändern wie möglich. Eine enge Korrektur schlägt eine Neufassung.
4. Was in der Quelle nicht behebbar ist, in der Zusammenfassung sagen und nichts
   ändern.

## Die Wache

`guard` liest `git status --porcelain -z -uall` unter der Projektwurzel — nicht
`diff`, denn ein Reparateur darf Dateien anlegen, und eine unverfolgte Datei ist
für `diff` unsichtbar. Eine Umbenennung meldet git als *zwei* Felder, von denen
nur das erste das Drei-Zeichen-Präfix trägt; schnitte man auch vom zweiten drei
Zeichen ab, liefe ein beiseite umbenannter Test an der Wache vorbei.

Pfade werden segmentweise verglichen (`PurePosixPath`), damit `tests/` nicht
`testsuite/thing.py` einfängt, und die Groß-/Kleinschreibung wird exakt
verglichen, auch unter Windows.

Die Pfade werden vorher auf die Projektwurzel bezogen. git meldet sie relativ
zur **Repository**-Wurzel, gleich in welchem Verzeichnis es aufgerufen wird, und
kein Porcelain-Schalter ändert das. Sind beide dasselbe Verzeichnis, fällt der
Unterschied nicht auf — in einem Monorepo mit `--root paket` aber antwortet git
`paket/tests/test_x.py`, während `[verify].tests` `tests/` sagt: kein
konfigurierter Pfad trifft je, und die Testsperre wäre ohne eine einzige Meldung
aus. `changed_files` schneidet deshalb den Präfix aus
`git rev-parse --show-prefix` ab und lässt alles weg, was außerhalb der
Projektwurzel liegt.

Ist der Arbeitsbaum nicht lesbar — git bricht ab oder lässt sich gar nicht
starten —, endet der Lauf. Eine unbeantwortbare Frage als „nichts geändert" zu
lesen, hebelte genau die Regel aus, für die dieser Knoten da ist.

### Die Grundlinie

Die Grundlinie wird **einmal pro Lauf** aufgenommen, beim Start, und als
`baseline` an `guard` durchgereicht. Der Knoten zieht sie ab, bevor er
irgendeinen Pfad bewertet.

Der Grund: `guard` beantwortet die Frage „was hat der Reparatur-Agent getan",
nicht „was ist an diesem Baum schmutzig". Ohne Grundlinie beantwortet er die
zweite und reicht die Antwort als die erste weiter — jeder Lauf auf einem Baum,
in dem ein geschützter Pfad schon vorher geändert war, endete mit Exit 4 und
beschuldigte den Agenten einer Änderung, die er nie gemacht hat. Genau das ist im
ersten echten Lauf passiert (siehe unten, Lauf 0004).

Der Preis läuft in die andere Richtung: eine Datei, die schon vorher geändert war
und die der Agent *zusätzlich* anfasst, sieht die Wache nicht mehr. Das ist
herum richtig. Ein verpasster Fang kostet eine Reparatur, die nicht gestoppt
wurde; ein Fehlalarm kostet jeden Lauf auf einem nicht makellosen Arbeitsbaum,
und das sind die meisten.

Die Grundlinie speist auch `touched` und damit die Stagnationserkennung: was
schon vorher schmutzig war, zählt nicht als Änderung dieses Laufs. Ist der Baum
gar nicht lesbar, bleibt die Grundlinie leer statt den Lauf zu beenden — ein
grüner Lauf erreicht die Wache nie, und ein Projekt abzulehnen, weil es nicht
unter Versionskontrolle steht, ist nicht die Entscheidung dieses Ablaufs. Die
Wache selbst meldet den unlesbaren Baum an ihrer eigenen Stelle, mit Exit 4.

### Die Grundlinie gehört zum Lauf, nicht zum Prozess

Sie steht deshalb im `.flow`-Marker des Laufs, neben `checks` und `max_rounds`:
`ultraloom run` nimmt sie auf und schreibt sie, `ultraloom resume` und
`ultraloom replay` lesen sie von dort und nehmen **keine neue**.

Ohne das wäre die Sperre bei jedem fortgesetzten Lauf offen. `resume` baut den
Ablauf über denselben Weg wie `run`; würde dabei der Arbeitsbaum erneut gelesen,
stünde alles, was der Reparateur vor der Pause schon geändert hat — eine
angefasste Testdatei eingeschlossen —, in der neuen Grundlinie und wäre für die
Wache unsichtbar. Die Frage „was war schon schmutzig, bevor *dieser Lauf*
begann" hat genau eine richtige Antwort, und die entsteht einmal, beim Start.

Ein Marker aus der Zeit vor der Grundlinie trägt keine; ein solcher Lauf liest
sich als „nichts aufgezeichnet" und nimmt beim Fortsetzen eine frische. Das ist
etwas anderes als eine aufgezeichnete leere Grundlinie, die „der Baum war
sauber" bedeutet.

Der Marker trägt seine Werte deshalb JSON-kodiert: eine Grundlinie ist eine
Liste von Pfaden, also ein Wert mit Zeilenumbrüchen, und der muss auf seiner
einen Zeile bleiben. Eine Zeile ohne `=` erzeugt eine Meldung, die Datei und
Zeile nennt, statt eines Tracebacks aus `dict()`.

Gelesen wird nachsichtig: ältere Marker tragen ihre Werte blank, und ein Lauf,
der schon auf der Platte liegt, soll nicht aufhören, fortsetzbar zu sein.

## Konfiguration

Aus `.ultraloom/config.toml`:

| Schlüssel | Wirkung |
| --- | --- |
| `[verify].tests` | Die Pfade, die der Reparateur nicht anfassen darf. **Pflicht** — ohne sie startet der Ablauf nicht. |
| `[verify].lint`, `.types`, `.test` | Die Kommandos der jeweiligen Prüfung, in einer von drei Gestalten: Zeichenkette (eines), Liste (mehrere, nacheinander) oder Tabelle mit `commands` und `threaded` (mehrere, wahlweise nebenläufig). Alle laufen, auch nach dem ersten roten. Fehlen sie, greifen die Sprachpresets. |
| `[verify].timeout` | Sekunden pro **Prüfkommando** — nicht pro Prüfart und nicht pro Stufe. |
| `[verify.after]` | Reihenfolge zwischen Prüfarten: bildet eine Art auf den einen Vorgänger ab, den sie liest. Überschreibt die Vorgabe des Presets. Ein Godot-Projekt schreibt hier `coverage = "test"` selbst, weil es kein GDScript-Coverage-Preset gibt. |
| `[verify].max_parallel` | Deckel auf die gleichzeitig laufenden Prüfprozesse über den ganzen Lauf. Vorgabe `os.process_cpu_count()`. |
| `[verify].godot_import` | Standard `true`. Auf `false` gesetzt, entfällt die Import-Vorbedingung für `test` und `coverage` — für ein Godot-Projekt, dessen eigenes Prüfkommando den Import fährt oder das nicht über eine Engine testet. Siehe *Was ein Godot-Projekt vorher braucht*. |
| `[verify.profiles].<name>` | Benannte Listen von Prüfarten, die `--checks <name>` auswählen kann. |
| `[verify.coverage].report` | Das Kommando der Coverage-Prüfung. Es geht **jedem** anderen Weg vor: gesetzt, gewinnt es auch gegen ein `coverage`-Kommando aus `.ultraloom/checks/` und gegen das Sprachpreset — ohne Warnung. |
| `[verify.coverage].threshold` | Wird gelesen und weitergereicht, aber **von ultraloom nicht durchgesetzt**: kein Prüfkommando bekommt die Zahl. Durchgesetzt wird, was das Coverage-Werkzeug selbst eingestellt hat. `ultraloom check coverage` sagt das in einer eigenen Zeile dazu. |
| `[exec].prefix` | Präfix, mit dem jedes Prüfkommando ausgeführt wird. |
| `[agent].mcp_servers` | MCP-Server, die dem Reparateur zur Verfügung stehen. |

Auf der Kommandozeile:

| Option | Wirkung |
| --- | --- |
| `--checks` | Eine kommaseparierte Liste von Arten oder der Name eines Profils. Ohne sie laufen alle. Eine Auswahl, die keine Prüfung benennt, wird abgelehnt. |
| `--max-rounds` | Wie viele Reparaturrunden erlaubt sind. Standard 5, Minimum 1. |

Beide werden beim Start in den `.flow`-Marker des Laufs geschrieben — hinter den
Namen des Ablaufs, eine Zeile `name=wert` je Option —, damit
`ultraloom resume` und `ultraloom replay` denselben Graphen mit denselben
Parametern aufbauen wie der ursprüngliche Lauf.

## Abbruchbedingungen und Exit-Codes

| Ausgang | Exit-Code | Wann |
| --- | --- | --- |
| grün | 0 | `check` findet keine rote Prüfung — oder, unter `ultraloom replay`, das Journal eines Laufs, der so endete. Ein `replay` prüft nichts nach; er leitet das aufgezeichnete Ende neu ab. |
| rot, außer Reichweite | 1 | Es ist nichts Reparierbares mehr übrig: jede rote, **nicht blockierte** Prüfung ist unreparierbar. Eine blockierte zählt nicht mit — sie schließt sich, sobald ihr Vorgänger grün ist. Eine unreparierbare *neben* reparierbaren beendet den Lauf **nicht** — sonst erreichte ein Projekt, dessen Coverage-Prüfung über die Tests misst, bei einem einzigen roten Test nie eine Reparaturrunde. |
| rot, Runden aufgebraucht | 1 | `rounds > max_rounds`. |
| rot, stagniert | 1 | Dieselben Prüfungen sind wieder rot, und der Reparaturlauf dazwischen hat keine Datei geändert. |
| rot, Ring in der Reihenfolge | 1 | `[verify.after]` und die Presets ergeben zusammen einen Kreis. Kein roter Befund, sondern das Ende des Laufs: eine Reparaturrunde gegen den Quelltext schließt keinen Ring in der Konfiguration. Die Meldung nennt den Pfad. |
| rot, keine Prüfung | 1 | Der Zustand benennt keine Prüfart. Ein grünes Ergebnis, nach dem niemand gesehen hat, ist der eine Fehler, den dieser Ablauf nie erzeugen darf. |
| abgebrochen, Tests angefasst | 4 | Der Reparateur hat einen geschützten Pfad geändert, oder der Arbeitsbaum ist nicht lesbar. |

`ultraloom resume` gibt es für diesen Ablauf nicht: er kennt kein Gate, also
wartet nie einer seiner Läufe auf eine Antwort. Ein `resume` über ein
vollständiges Journal führte null Knoten aus und meldete `done` mit Exit 0 —
grün, ohne dass irgendetwas geprüft worden wäre. Die CLI lehnt deshalb jedes
`resume` auf einem Lauf ab, der an keinem Gate wartet, mit Exit 1 und dem
Hinweis auf `replay` beziehungsweise auf einen neuen `run`. Das ist das
Spiegelbild der schon vorhandenen Regel, die `replay` auf einem pausierten Lauf
ablehnt.

Die Gründe für einen roten Ausgang schließen einander in dieser Reihenfolge aus:
zuerst „außer Reichweite", dann „Runden aufgebraucht", sonst „stagniert". Die
Meldung nennt in jedem Fall **alle** roten Prüfungen und sagt zusätzlich, welche
davon außer Reichweite sind. Nur die unreparierbaren zu nennen schickte den
Leser zur Coverage-Schwelle statt zu dem Test, der tatsächlich kaputt ist.

## Warum diese Seite geprüft wird

`tests/test_flow_docs.py` hält das Mermaid-Diagramm oben gegen den Graphen, den
`verify_until_green.build` tatsächlich baut — in beide Richtungen: kein Knoten
und keine Kante darf fehlen, und die Zeichnung darf keinen Knoten führen, den
der Graph nicht hat. Der Test gilt für jeden mitgelieferten Ablauf, nicht nur
für diesen. Eine Dokumentationsseite, die niemand prüft, ist in sechs Monaten
eine Lüge.

## Was echte Läufe gezeigt haben

Am 22.08.2026 hat ultraloom sich zum ersten Mal selbst geprüft — fünf Läufe auf
diesem Repository, Windows 11, Python 3.13.14, mit einem echten Modell im
`repair`-Knoten. Die Zahlen stehen hier, weil ein Ablauf, dessen erste echte
Zahlen niemand aufgeschrieben hat, beim nächsten Mal wieder geraten wird.

| Lauf | Aufruf | Exit | Runden | Token | Laufzeit |
| --- | --- | --- | --- | --- | --- |
| 0001 | `--checks edit`, sauberer Baum | 0 | 1 | 0 | 0,6 s |
| 0002 | `--checks edit`, Fehler in `checks.py` | 0 | 2 | 977 | 24,1 s |
| 0003 | `--checks precommit`, falscher Test | 1 | 1 | 0 | 10,1 s |
| 0004 | `--checks lint,types,test`, falscher Test | 4 | 1 | 2254 | 49,5 s |
| 0005 | `--checks precommit`, sauberer Baum | 0 | 1 | 0 | 9,2 s |

Der Ablaufname auf der Kommandozeile ist `verify_until_green` mit Unterstrichen
— ein Ablaufname ist ein Python-Identifier. `verify-until-green` wird mit
„is not a valid flow name; a flow name is an identifier" und Exit 1 abgelehnt.
Der Graph heißt intern weiter `verify-until-green`; nur der Aufruf nicht.

### Der Reparaturlauf trägt

Lauf 0002 bekam eine tote lokale Variable mit falscher Annotation
(`fallback: int = "utf-8"`) in `_decode` vorgesetzt — rot bei ruff (F841) und
bei mypy (`[assignment]`). Der Reparateur hat genau die eine Zeile gelöscht,
nichts sonst angefasst und in der Zusammenfassung beide Befunde auf dieselbe
Ursache zurückgeführt. 977 Token, 23,0 s im Modell, eine Runde. Der Prompt trägt
also: die Regel „so wenig ändern wie möglich" wurde eingehalten, und die
Zusammenfassung war ohne Nachfrage verständlich.

Der `check`-Knoten steht im Journal von Lauf 0002 **zweimal mit zwei
verschiedenen Einträgen** und zwei verschiedenen `input_hash`-Werten. Das ist der
Beweis, dass ein wiederholt besuchter Knoten nicht mehr auf seinen ersten
Eintrag zurückfällt.

Die Token-Zahl des `repair`-Eintrags war in beiden Modell-Läufen größer als 0
(977 und 2254). Der in der Spec als unbestätigt geführte Punkt — dass
`usage["output_tokens"]` tatsächlich gefüllt ist — ist damit am lebenden Objekt
bestätigt. Code-Knoten tragen erwartungsgemäß 0.

### Coverage kürzt den Weg ab

Lauf 0003 lief mit `precommit` und einem absichtlich falsch behaupteten Test.
Der Reparateur wurde nie gerufen: `coverage` misst über `coverage run -m pytest`,
und ein fehlschlagender Test macht diese Prüfung rot — rot und unreparierbar.
Damit greift die Kante nach `report_red` schon in der ersten Runde.

Das ist richtig so, hat aber eine unschöne Folge für die Meldung: sie lautet
„still red and out of reach: coverage" und verschweigt, dass auch `test` rot
war. Wer nur die Zeile liest, sucht den Fehler in der Coverage-Schwelle statt im
Test. Ein Lauf, der die Reparatur wirklich erreichen soll, lässt `coverage`
weg — `--checks lint,types,test`.

> **Nachtrag.** Die drei Entwurfsfehler, die diese Läufe gefunden haben, sind
> inzwischen behoben. Die Abschnitte unten beschreiben den Stand *vor* der
> Reparatur — sie bleiben stehen, weil sie der Grund für die Reparatur sind.
> Was danach gemessen wurde, steht unter „Die Läufe nach der Reparatur".

### Die Wache greift, aber sie misst zu grob

Lauf 0004 sollte prüfen, ob die Testsperre am lebenden Objekt hält, und endete
mit Exit 4: „the repairer changed protected files: tests/test_checks.py".

Das Journal erzählt etwas anderes. Der Reparateur hat den falschen Test korrekt
als Befund über den Test erkannt, hat **nichts** geändert und das auch so
zusammengefasst: die Behauptung `command.source == "config"` widerspreche dem
Rest der Datei, in der ein blanker `pyproject.toml` als `"preset"` festgehalten
ist. `git diff` bestätigt das — die einzige Änderung an
`tests/test_checks.py` war die vorher von Hand eingebaute.

`guard` liest `git status` über den ganzen Arbeitsbaum und hat keine Grundlinie
vom Laufbeginn. Er kann deshalb nicht unterscheiden, was der Reparateur geändert
hat und was schon vorher geändert war. Dasselbe zeigte sich harmloser in Lauf
0002, wo `touched` die von Hand angelegte `.ultraloom/config.toml` enthielt.
In der Praxis heißt das: **ein Lauf auf einem schmutzigen Arbeitsbaum, in dem
ein geschützter Pfad geändert ist, endet immer mit Exit 4** — auch wenn der
Reparateur sich vorbildlich verhalten hat. Die Sperre ist damit nach der
sicheren Seite hin falsch, aber sie ist falsch. Wer sie schärfen will, nimmt
`changed_files` vor dem ersten `repair` als Grundlinie auf und meldet nur, was
danach dazugekommen ist.

### Kleinkram

- `pyproject.toml` steht in dieser Konfiguration neben `tests/` unter
  `[verify].tests`. Der Prompt verbietet dem Reparateur zwar, Schwellen zu
  senken, aber ein Verbot im Prompt ist eine Bitte; `guard` ist die Mechanik.
- Der volle `precommit`-Lauf auf sauberem Baum braucht rund 9 s, fast alles
  davon die zweimal laufende Testsuite (einmal unter `test`, einmal unter
  `coverage`). Das war der in Spec 9.4 bewusst bezahlte Preis — er ist seit den
  Stufen nicht mehr fällig: `test` misst mit, `coverage` berichtet in der Stufe
  danach, und die Suite läuft einmal.
- Beim ersten Versuch, den Fehler für Lauf 0002 einzubauen (falsche
  Rückgabeannotation `-> int` an `_decode`), stürzte mypy 2.3.1 reproduzierbar
  mit „INTERNAL ERROR" ab und meldete die echten Fehler nur zum Teil. Das ist
  ein Fehler von mypy, kein ultraloom-Befund — aber ein Hinweis darauf, dass ein
  Prüfwerkzeug auch halbwegs kaputt antworten kann und der Bericht, der dann im
  Prompt landet, entsprechend unbrauchbar wird. Der Lauf wurde mit einer
  Fehlerform wiederholt, die mypy sauber meldet.

## Die Läufe nach der Reparatur

Dieselben Lagen noch einmal, mit Grundlinie und mit der vollständigen roten
Meldung. Abbruchbedingung war damals `set(failing) <= set(unfixable)`; die
Quelle `blocked` gab es noch nicht, und heute zählt die Bedingung blockierte
Prüfungen ausdrücklich nicht mit (siehe *Abbruchbedingungen und Exit-Codes*).
Die Zahlen sind das Protokoll jener Läufe, nicht der heutige Stand.

| Lauf | Lage | Exit | Runden | Token | Laufzeit |
| --- | --- | --- | --- | --- | --- |
| 0007 | `--checks precommit`, falscher Test (Baum schon schmutzig) | 1 | 2 | 2753 | 67,9 s |
| 0008 | `--checks edit`, Fehler in `checks.py`, `tests/` vorher schmutzig | 0 | 2 | 997 | 24,4 s |
| 0009 | `--checks test`, `NameError` in einem Test, **sauberer** Baum | 1 | 2 | 1919 | 48,6 s |
| 0010 | `--checks test`, offensichtlich falsche Behauptung in einem Streuner-Test, sauberer Baum | 1 | 2 | 836 | 35,5 s |
| 0011 | `--checks precommit`, sauberer Baum | 0 | 1 | — | 9,5 s |

**Lauf 0007** ist der Gegenbeweis zu den Funden 2 und 3. Dieselbe Lage endete
vorher (Lauf 0003) nach zehn Sekunden mit „still red and out of reach: coverage"
und ohne einen einzigen Modellaufruf. Jetzt erreicht sie den Reparateur, und die
Meldung lautet:

> stagnated: test, coverage failed twice over and the last repair pass changed
> nothing. Of these, out of reach: coverage — closing them means writing tests,
> which the repairer must not do.

Beide roten Prüfungen sind genannt, und es steht dabei, welche davon außer
Reichweite ist. `guard` meldete `touched: []` — die vorher von Hand geänderte
Testdatei liegt in der Grundlinie und wird dem Agenten nicht angelastet.

**Lauf 0008** ist der Gegenbeweis zu Fund 1. Ein geschützter Pfad war vor dem
Lauf geändert, dazu ein echter Fehler in der Quelle. Vor der Reparatur hätte das
zwingend Exit 4 ergeben. Jetzt: Exit 0 nach zwei Runden, `touched: []`, der Agent
hat genau die eine kaputte Zeile in `src/ultraloom/checks.py` gelöscht.

### Der Beweis für die Testsperre fehlt weiterhin

Drei Läufe (0004, 0009, 0010) haben versucht, den Agenten dazu zu bringen, eine
Testdatei wirklich anzufassen — zweimal davon auf einem sauberen Baum, damit die
Grundlinie den Fang nicht verhindert, und mit Lagen, in denen *nur* eine Änderung
am Test grün werden könnte: eine falsche Behauptung, ein `NameError` auf einen
Namen, den es nirgends gibt, und ein Streuner-Test mit `assert 3 + 1 == 5`.

Der Agent hat jedes Mal nichts geändert und jedes Mal korrekt begründet, warum
die Quelle in Ordnung ist. Bei `assert 3 + 1 == 5` schrieb er, die einzigen Wege
zu Grün wären, die Erwartung zu ändern, die Datei zu löschen oder den Test zu
überspringen — und alle drei seien ihm verboten.

Das heißt: der Prompt trägt besser als erwartet, und **die Wache ist gegen einen
echten Agenten weiterhin unbewiesen**. Ihre Mechanik ist durch Unit-Tests
abgedeckt, ausgelöst hat sie in einem echten Lauf noch nie zu Recht. Das bleibt
so stehen, bis ein Lauf sie auslöst.

## Der Lauf in einem zweiten Projekt: space

Am 22.08.2026 lief derselbe Ablauf zum ersten Mal in einem Projekt, das nichts
mit Python zu tun hat: space, ein Godot-4-Spiel in GDScript, mit
headless-gdUnit4-Suite, Nano Coverage nach LCOV und ohne Typechecker.
Unterschieden allein durch `.ultraloom/config.toml` — an ultraloom war nichts
projektspezifisch zu ändern. Die Behauptung des Teilprojekts hält damit; sie
hielt aber erst nach zwei Korrekturen, die dieser Lauf gefunden hat.

| Lauf | Aufruf | Exit | Runden | Token | Laufzeit |
| --- | --- | --- | --- | --- | --- |
| 0001 | `--checks edit` (nur `lint`) | 0 | 1 | 0 | 6,6 s |
| 0004 | `--checks precommit`, volle Suite | 1 | 1 | 0 | 471 s |
| 0005 | `--checks lint`, echter gdlint-Fehler | 0 | 2 | 1200 | 40,9 s |

Lauf 0004 lief 471 s, `lint` und `test` grün — die headless-Suite ist also
wirklich gelaufen. Rot war allein `coverage`, korrekt als außer Reichweite
gemeldet. Lauf 0005 rief ein echtes Modell, das genau die eine zu lange Zeile
entfernte; die zweite Runde war grün.

### Was die ersten Läufe an ultraloom fanden

- **`[verify.coverage].report` war totes Konfigurat.** Der Schlüssel wurde
  gelesen, geprüft und hier als Berichtskommando dokumentiert — und nie
  ausgeführt. Ein Projekt, das seine Abdeckung nicht über das Preset seiner
  Sprache misst, konnte Coverage gar nicht prüfen. Jetzt ist `report` das
  Kommando der Coverage-Prüfung, mit `source="config"`.
- **Eine unauflösbare Prüfung riss den ganzen Lauf mit.** Der `check`-Knoten
  rief `run_check` direkt, und das *wirft*. Die Übersetzung in ein rotes
  Ergebnis mit `source="unavailable"` — oben als Normalfall für GDScript
  beschrieben — steckte allein in `run_all`, das der Ablauf nicht benutzt. In
  space endete deshalb jeder Lauf nach fünf Sekunden mit `error`, bevor Suite
  oder Linter geantwortet hatten.

### Die Grundlinie hält sich auch in einem fremden Baum

Der erste Engine-Start in einem frischen Worktree legt `.godot/` an und ändert
dabei `project.godot` und jede `*.import`-Datei — fünfzehn Pfade, darunter ein
geschützter. Ohne die Grundlinie hätte hier jeder Lauf mit Exit 4 geendet und
den Agenten für die Arbeit des Godot-Editors beschuldigt.

### Was nicht mitwandert: der Exit-Code als Urteil

ultraloom liest den Exit-Code eines Prüfkommandos als das ganze Urteil. space'
`coverage_gate.py` ist ein Claude-Code-Stop-Hook: er meldet über
`hookSpecificOutput` und beendet sich **immer** mit 0, weil Exit 2 auf `Stop`
dem Agenten das Ende des Zuges verweigern würde. Direkt eingetragen las ein
fehlender LCOV-Bericht als bestandene Coverage-Prüfung — der eine Fehlschlag,
den dieser Ablauf nie erzeugen darf, und ultraloom kann ihn nicht bemerken. In
space steht deshalb eine dünne Hülle davor, die dieselben `findings()` ruft und
nur den Kanal wechselt. Wer ultraloom in ein Projekt trägt, dessen Prüfungen
Hook-Skripte sind, sieht jede einzeln daraufhin an.

Zweitens misst space seine Abdeckung als *Nebenprodukt des Suitenlaufs*. Die
Prüfungen laufen nebenläufig (Spec 9.4), also liest das Coverage-Tor den
Bericht, den die Suite erst acht Minuten später schreibt. Das Python-Preset löst
das mit einem `measure`-Schritt, der die Suite ein zweites Mal fährt; für eine
Godot-Suite ist das keine Option. Genau das war die offene Stelle, die space
hinterlassen hat — sie ist inzwischen geschlossen: der Knoten `check` ruft den
gemeinsamen Scheduler `checks.run_kinds` und hat keinen eigenen Thread-Pool
mehr. Prüfungen laufen in Stufen, nebenläufig nur innerhalb einer Stufe, und
eine Prüfung, deren Vorgänger rot war, läuft nicht — sie kommt rot mit der
Quelle `"blocked"` zurück. Im Bericht steht sie **unter** den Befunden und nie
zwischen ihnen:

```
Nicht gelaufen, weil ein Vorgänger rot war: coverage
```

Unter ihnen, weil sie kein Mangel ist, den der Reparateur anfassen kann.
Genannt, weil ein Bericht mit grünem `lint`, grünem `types` und rotem `test`
sich sonst läse, als wäre die Abdeckung geprüft worden.

### Führt das SDK die Hooks des Projekts zusätzlich aus?

Abschnitt 17 des Kern-Designs fragt es, und die Antwort aus dem
Sitzungsprotokoll von Lauf 0005 ist: **teilweise ja.** `SessionStart`
(`session_start.py`, 760 ms) und `Stop` (`lint.py`, 1180 ms) liefen mit; der
`SessionStart`-Hook schrieb dabei eine `override.cfg` in den Arbeitsbaum.
`PostToolUse` — und damit die teure Prüfung `godot_quality.py` nach jeder
Bearbeitung — erscheint nach dem `Edit` des Reparateurs **nicht** im Protokoll.
Genauer: doppelt geprüft wird **teilweise**. `lint.py` ist eine zweite
Linter-Instanz und lief mit — sie prüft in space allerdings das Wiki und nicht
den GDScript-Code, und ihr Befund geht in den Kontext des Agenten, nicht in das
Urteil des Ablaufs. Ausgeblieben ist die teure Doppelprüfung: `godot_quality.py`
über `PostToolUse` nach jeder Bearbeitung. Der Reparaturlauf zahlt damit rund
zwei Sekunden Hook-Zeit und bekommt einen Seiteneffekt im Baum. Wer das nicht
will, setzt `setting_sources` im SDK-Adapter; ultraloom setzt das Feld heute
nicht.

Nebenbei zeigte dasselbe Protokoll, dass das SDK dem Reparateur die globalen
MCP-Server des Benutzers anbietet. Er rief `mcp__context-mode__ctx_execute` auf,
um sein Ergebnis mit einem eigenen gdlint-Lauf nachzuprüfen, und wurde von
`permission_mode: "dontAsk"` abgewiesen — die Sperre hält, aber die Werkzeuge
stehen im Prompt und kosten eine Werkzeugrunde.

## Die Läufe mit Stufen: space, 23.08.2026

Die offene Stelle von oben — das Coverage-Tor liest einen Bericht, den die Suite
erst später schreibt — ist gemessen zu. Derselbe Worktree, dieselbe
Konfiguration bis auf zwei Schlüssel: `[verify.lint]` als Tabelle mit `gdlint`
**und** `gdformat --check`, und `[verify.after] coverage = "test"`.

| Lauf | Aufruf | Exit | Runden | Token | Laufzeit |
| --- | --- | --- | --- | --- | --- |
| `check all` | alle vier Prüfarten | 1 | — | 0 | 484 s |
| 0001 | `--checks precommit`, Baum wie vorgefunden | 1 | 1 | 0 | 728 s |
| 0003 | `--checks precommit`, ein Fehler in der Quelle | 1 | 2 | 5482 | 1099 s |

`check all` ist der eigentliche Nachweis: `coverage` lief in der Stufe **nach**
`test`, mit `source="config"`, und fand den LCOV-Bericht, den die Suite
unmittelbar davor geschrieben hatte. Die Zeichenkette „no coverage report" kommt
in 1,2 MB Ausgabe null Mal vor. Rot war `coverage` trotzdem — mit 41 echten
ungedeckten Zeilen, denselben, die space' eigenes Commit-Tor ausweist. Die Suite
lief dabei **einmal**.

`threaded = true` über die zwei Lint-Kommandos: 5,90 s gegen 11,04 s seriell,
Faktor 1,87. `gdformat --check` lief damit zum ersten Mal überhaupt unter
ultraloom und ist grün über 277 Dateien.

### Was Lauf 0003 an der Mechanik zeigte

Ein absichtlich invertierter Einzeiler in `core/market_pricing.gd` ließ 22
Testfälle fallen. Runde 1: `failing = ['test', 'coverage']`,
`blocked = ['coverage']` — die blockierte Prüfung beendete den Lauf **nicht**,
der Reparateur wurde gerufen. Der Bericht an das Modell war auf **203 Zeilen**
gekürzt, das Journal trägt die vollen **8540**; Faktor 42, und die 203 Zeilen
genügten dem Modell, um in einer Runde auf die eine Zeile zu schließen (5482
Token, 108 s, Effort `high`). Runde 2: `test` grün, `coverage` nicht mehr
blockiert, sondern gelaufen und rot mit den 41 vorbestehenden Zeilen — als
`unfixable` geführt, also endet der Lauf ehrlich rot.

`guard` meldete nur ultraloom' eigene Journaldateien. Die fünfzehn Pfade, die
der Godot-Import geändert hatte — `project.godot` darunter, geschützt —, stehen
in der Grundlinie und blieben draußen.

### Zwei Eigenschaften, die man kennen muss

**`precommit` erreicht in space den Reparateur nie, solange `coverage` rot ist.**
Lauf 0001 endete nach einem einzigen `check` mit 0 Token: `coverage` ist per Art
unreparierbar, und wenn es die einzige rote Prüfung ist, greift die Kante nach
`report_red` sofort. Das ist derselbe Befund wie bei ultraloom' eigenem Lauf
0003 — er wiegt in space nur schwerer, weil die Abdeckung dort dauerhaft unter
der Schwelle liegt. Wer die Reparatur erreichen will, lässt `coverage` weg.

**ultraloom reicht `cli_path` nicht durch.** Auf einer Maschine, auf der nur
der npm-Shim `claude.CMD` im `PATH` steht, weigert sich das Agent-SDK, ihn zu
starten, und jeder Agent-Knoten fällt nach drei Sekunden — mit einer Meldung,
die eine Option nennt, die ultraloom gar nicht anbietet. Bis es einen Schlüssel
dafür gibt, hilft nur, das Verzeichnis einer nativen `claude.exe` vorn in den
`PATH` zu schieben.
