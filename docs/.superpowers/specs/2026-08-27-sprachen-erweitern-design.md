# Mehr Sprachen für die Commit-Sprachprüfung — Entwurf

Stand: 2026-08-27. Status: zur Umsetzung.

Baut auf `2026-08-25-commit-sprachpruefung-design.md` auf. Alles dort Gesagte
gilt weiter, sofern hier nichts anderes steht.

## Warum

Die Prüfung kennt heute ein Sprachpaar, deutsch gegen englisch. Der Anlass war
ein Agent mit deutscher Prosaregel in einem englischen Projekt — aber die
Sprachen, die in echtem Code neben Englisch auftauchen, sind vor allem
Chinesisch, Russisch, Spanisch und Portugiesisch. Für die tut das Werkzeug
heute nichts.

## Die Messung, die den Entwurf bestimmt

Anteil der Funktionswörter einer Sprache, die in der anderen ebenfalls
vorkommen — die Größe, an der die Heuristik hängt:

```
        en   de   nl   fr   es   pt   it
  de     9    -    0    3    0    3    0
  nl    23    0    -    6   10    3    6
  fr    12    2    5    -   25   15    7
  es    11    0    6   22    -   33   24
  pt     9    2    2   14   35    -    9
  it    11    0    5    8   32   11    -
```

Drei Schlüsse:

**Gegen Englisch tragen fast alle.** Spanisch 11 %, Französisch 12 %,
Portugiesisch 9 % — Deutsch liegt bei 9 %. Die Machart trägt weiter.

**Romanisch gegen romanisch trägt nicht.** 33 % zwischen Spanisch und
Portugiesisch. Das ist keine Schwelle, die man kalibrieren kann — und es ist
auch nicht nötig, denn wenn das Ziel Englisch ist, muss die Prüfung die beiden
nie auseinanderhalten.

**Zusammenlegen kostet nichts, filtern ist Pflicht.** Die Vereinigung aus
Deutsch, Romanisch, Polnisch und Türkisch liegt bei 9 % Homographen — dieselbe
Rate. Aber die kollidierenden Wörter sind `a`, `as`, `in`, `to`, `her`, `do`,
`no`: Hochfrequenzwörter des Englischen. „Add a fix to the parser as her review
asked" hätte fünf Treffer. Die Rate täuscht; die Wortidentität entscheidet.

## Was gebaut wird

### 1. Der Skript-Test

Eine Folge von Buchstaben in einer nicht-lateinischen Schrift zählt als **ein
Treffer**, genau wie ein Stoppwort. Damit gilt dieselbe Schwelle, dieselbe
Zeilenzählung, dieselben Ausnahmen — Spannen, `[[commit.allow]]`, Trailer,
Scherenschnitt — ohne einen einzigen neuen Mechanismus.

Erfasste Schriften: Han, Hiragana, Katakana, Hangul, Kyrillisch, Arabisch,
Hebräisch, Griechisch, Devanagari, Thai.

**Warum ein Treffer je Wort und nicht je Zeichen.** Ein einzelner zitierter
Begriff — ein Dateiname, ein Fehlertext, ein Eigenname — ist ein Treffer und
bleibt unter der Schwelle von zwei. Ein Satz ist mehrere und fliegt. Je Zeichen
gezählt wäre jedes chinesische Wort sofort über der Schwelle, und das Gate
hätte genau die Fehlalarme, die es unbrauchbar machen.

**Keine Kalibrierung nötig, und das ist der Punkt.** Ein Skript-Test ist keine
Heuristik: Kyrillisch ist kein Englisch, ohne Wortliste und ohne geratene
Schwelle. Er ist billiger *und* sicherer als alles Stoppwortbasierte — und er
deckt die vier Sprachen ab, die in echtem Code nach Englisch am häufigsten
vorkommen.

**Lateinische Schrift zählt nie**, auch nicht mit Diakritika. `für` und
`café` sind lateinisch geschrieben; sie gehören den Wortlisten, nicht dem
Skript-Test.

### 2. Die romanische Liste

Eine **verschmolzene** Liste für Spanisch, Portugiesisch, Französisch,
Italienisch, Rumänisch und Katalanisch statt sechs einzelner. Gemessen kostet
das nichts: 11 % Homographen verschmolzen, 11 % für Spanisch allein. Die große
Überlappung teilen die romanischen Sprachen miteinander, nicht mit Englisch.

### 3. Die Filterregel — die harte Anforderung

**Kein Wort einer Quellliste darf ein gewöhnliches Wort der Zielsprache sein.**
Die Listen werden je Ziel gefiltert, nicht global: `in` ist gegen Englisch
untauglich und gegen Deutsch ebenso, `come` nur gegen Englisch.

Das ist keine Stilfrage. Ohne den Filter lehnt die zusammengelegte Liste
gewöhnliches Englisch ab, und ein Gate mit Fehlalarmen wird mit `--no-verify`
umgangen und schützt danach nichts.

**Ein Test hält die Regel**, nicht ein Kommentar: Für jede Zielsprache wird
geprüft, dass die Vereinigung ihrer Quelllisten keines der bekannten
Hochfrequenzwörter dieser Sprache enthält.

## Was ausdrücklich nicht gebaut wird

- **Niederländisch.** 23 % Homographen mit Englisch — `die`, `in`, `is`, `of`,
  `over`, `van`, `was`. Es zöge die germanische Seite von 9 % auf 16 %. Erst
  messen, dann aufnehmen.
- **Vietnamesisch.** Lateinische Schrift mit hoher Diakritikadichte; das wäre
  ein dritter Mechanismus, kein Stoppwortproblem.
- **Romanisch gegen romanisch.** Siehe die Messung.
- **Polnisch, Türkisch, Indonesisch.** Sinnvolle Kandidaten, aber Beiwerk,
  solange sie niemand an echten Historien gemessen hat. Die Filterregel und die
  Verschmelzungsmachart sind so gebaut, dass sie später ohne Umbau dazukommen.

## Konfiguration

**Unverändert.** `language` bleibt die *Zielsprache*, und die Quellen ergeben
sich daraus. Kein neuer Schlüssel: Wer `language = "en"` schreibt, meint
„Commits sind englisch", und alles andere ist dann falsch — Chinesisch so gut
wie Deutsch.

`LANGUAGES` bleibt `("en", "de")`: Es sind weiter zwei mögliche *Ziele*. Was
wächst, ist die Menge der erkannten Quellen.

## Ehrlichkeit über das Belegte

Unverändert und weiterhin in der README:

- Die **deutsche Quellliste gegen Englisch** ist an einer echten Historie
  kalibriert.
- **Alles Neue ist es nicht.** Die romanische Liste und die englische Richtung
  sind Ausgangspunkte, nicht Messungen. `--calibrate` ist der Weg, das
  nachzuholen.
- Der **Skript-Test braucht keine Kalibrierung** und wird auch nicht so
  ausgewiesen — seine Schwelle ist die vorhandene, und seine Aussage ist
  strukturell, nicht statistisch.

## Grenzen

- Ein englischer Satz mit zwei zitierten chinesischen Begriffen *außerhalb*
  von Spannen wird abgelehnt. Dafür gibt es Rückstriche und
  `[[commit.allow]]` — dieselbe Antwort wie für deutsche Zitate heute.
- Die romanische Liste kann Spanisch nicht von Portugiesisch unterscheiden.
  Das ist Absicht und steht oben begründet.
