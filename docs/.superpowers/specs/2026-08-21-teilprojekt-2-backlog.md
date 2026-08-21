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
