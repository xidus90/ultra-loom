# policy

Kein Ablauf des Harness, sondern der Weg einer einzelnen Entscheidung: Claude
Code fragt vor einem Werkzeugaufruf, und `ultraloom policy hook` antwortet mit
einem Exit-Code. Die Verzweigung aus Art, Modus, Voreinstellungen und Treffern
ist als Prosa unlesbar; darum steht sie hier als Bild.

Aufruf:

```bash
ultraloom policy hook                   # Payload von stdin
ultraloom policy check <art> <wert>     # dieselbe Entscheidung von Hand
```

Die Regeln selbst, ihr Schema und die vollständige Liste der Voreinstellungen
stehen in der [README](../../README.de.md#policy).

## Der Weg einer Entscheidung

```mermaid
flowchart TD
    payload["Payload von stdin"] --> lesbar{"JSON lesbar,<br/>tool_name da?"}
    lesbar -->|nein| exit1["Exit 1 — interner Fehler"]
    lesbar -->|ja| arten{"Berührt das Werkzeug<br/>eine Regelart?"}
    arten -->|nein| exit0["Exit 0 — erlaubt"]
    arten -->|ja| subjects["Subjects bilden:<br/>Pfad, Kommando, Inhalt"]
    subjects --> config{"Konfiguration<br/>lesbar?"}
    config -->|nein| exit2["Exit 2 — verweigert"]
    config -->|ja| modus{"Modus der Art"}
    modus -->|deny| deny{"Trifft eine Regel?<br/>Voreinstellungen + Projekt"}
    deny -->|nein| exit0
    deny -->|ja, eine oder mehrere| exit2
    modus -->|allow| allow{"Erlaubt eine Regel?<br/>nur die Allowlist"}
    allow -->|ja| exit0
    allow -->|nein| exit2
```

## Was die Verzweigungen bedeuten

**`tool_name` zuerst.** Der Hook liest den Werkzeugnamen und endet mit 0, bevor
er eine Konfigurationsdatei anfasst, wenn das Werkzeug keine Regelart berührt.
Er läuft vor jedem `Write`, `Edit` und `Bash`; sein eigener Aufwand ist deshalb
eine Anforderung und keine Nebensache. Aus demselben Grund liegt der Import der
Prüfkette in `cli.py` in den Funktionen und nicht im Modulkopf.

**Ein Aufruf, mehrere Subjects.** `Write`, `Edit` und `MultiEdit` ergeben ein
Pfad-Subjekt; der Inhalt kommt bei `Write` aus `content`, bei `Edit` aus
`new_string` und bei `MultiEdit` aus jedem `new_string` in `edits` -- ein
Inhalts-Subjekt je Ersetzung. `Bash` ergibt sein `command`. Geprüft werden
alle, und die Begründungen aller landen zusammen auf stderr.

**Die kaputte Konfiguration blockt.** Sie ist Exit 2 und nicht Exit 1. Eine
Policy, die stillschweigend durchlässt, sobald ihre eigene Konfiguration
unlesbar ist, wäre genau die Sperre, die man für vorhanden hält und die nicht
da ist. Exit 1 bleibt echten Innenfehlern vorbehalten: unlesbare Payload,
leeres stdin — und er blockt nie, weil eine defekte Policy keine Sitzung
einsperren darf.

**Deny sammelt, Allow bricht ab.** Im Deny-Modus werden alle treffenden Regeln
ausgewertet, die Voreinstellungen zuerst und danach die Projektregeln in der
Reihenfolge der Datei. Sonst räumte der Agent einen Grund aus, liefe in den
nächsten und bräuchte eine Runde je Regel. Im Allow-Modus beendet die erste
passende Erlaubnis die Prüfung — ein zweiter Grund, warum etwas erlaubt ist,
ändert die Antwort nicht.

**Im Allow-Modus fallen die Voreinstellungen weg.** Dort zählt allein die
Allowlist, auch gegenüber den eingebauten Sperren. Wer den Modus umdreht,
übernimmt die Verantwortung ganz.

## Fehlt die Konfiguration ganz

Dann greifen die Voreinstellungen, und der Weg durch das Bild ist derselbe: die
Datei fehlt, das ist kein Fehler, der Modus ist `deny`, und geprüft wird gegen
die eingebauten Regeln. Ein Repo ohne `.ultraloom/config.toml` ist damit
geschützt, ohne dass jemand etwas eingerichtet hat.
