# Generierte Dateien im Pfad-Guard — Entwurf

Stand: 2026-08-27. Status: umgesetzt.

## Warum

Der Pfad-Guard der Policy kennt heute zwei Regelgruppen: Geheimnisse, und seit
`5d7e503` die Kontrolldateien des Stop-Gates. Beide beantworten die Frage "darf
ein Agent das schreiben" mit einer Aussage über die Datei — nicht mit einer
Hausordnung.

Es gibt eine dritte Gruppe derselben Art, die noch fehlt: Dateien, die die
Ausgabe eines Werkzeugs sind. Eine Lockdatei von Hand zu ändern ist in jedem
Projekt und in jeder Sprache falsch; sie entsteht aus einem Resolverlauf und
sagt aus, was der Resolver aufgelöst hat. Ein Agent, der eine Zeile darin
korrigiert, hat nicht das Projekt geändert, sondern die Behauptung über das
Projekt.

Das Vorbild ist `iam_backend/.claude/hooks/guard_paths.py`, das genau diese
Gruppe schützt — dort zusammen mit generierten Django-Migrationen.

## Was gebaut wird

Zwei Dinge, mit einer bewussten Grenze dazwischen.

**Eingebaut**: eine dritte `paths`-Regel in `ultraloom.policy.config.DEFAULTS`
für Lockdateien.

**Nur dokumentiert**: ein Beispielblock in beiden READMEs für das, was
projektabhängig ist — allen voran generierte Migrationen.

## Die Grenze, und warum sie dort liegt

Der Unterschied ist nicht "Sicherheit gegen Hausordnung". Er ist *generiert*
gegen *sieht generiert aus*.

Eine Lockdatei ist überall dasselbe. Für `uv.lock`, `Cargo.lock` oder
`package-lock.json` gibt es keine Umgebung, in der eine Handänderung die
richtige Handlung wäre. Der Merge-Konflikt sieht wie ein Gegenbeispiel aus, ist
aber keins: auch dort ist die Auflösung ein erneuter Resolverlauf.

`migrations/0001_x.py` ist Django. Dasselbe Verzeichnis trägt anderswo
handgeschriebene SQL-Migrationen, die geändert werden *sollen*, und Alembic
benennt seine Dateien ohne die vierstellige Nummer. Eine eingebaute Regel würde
dort eine legitime Änderung blocken.

Ein Fehlalarm in den Voreinstellungen ist teurer als eine fehlende Regel: er
kostet das Vertrauen in die anderen. Der Kommentar über `DEFAULTS` beschreibt
den Ausgang schon — bei der ersten Reibung wird `defaults = false` gesetzt, und
das nimmt die Regeln gegen Geheimnisse mit.

## Die eingebaute Regel

```python
Rule(
    patterns=(
        "uv.lock", "poetry.lock", "package-lock.json", "yarn.lock",
        "pnpm-lock.yaml", "Cargo.lock", "composer.lock", "Gemfile.lock",
        "go.sum",
    ),
    reason="a lock file is written by its resolver, not by hand",
    is_regex=False,
    tools=None,
)
```

`tools=None`, also Write wie Edit: eine Lockdatei neu anzulegen ist derselbe
Fehler wie sie zu ändern.

Nicht in der Liste steht `requirements.txt`. Sie wird vielerorts von Hand
gepflegt, und genau dort wäre die Regel der Fehlalarm, den dieser Entwurf
vermeiden will.

Die Muster stehen als Glob, nicht als Regex: es sind feste Dateinamen, und
`PurePosixPath.full_match` trifft sie auf jeder Ebene nur dann, wenn der Pfad
genau so lautet. Ein `vendor/uv.lock` wird damit **nicht** getroffen. Das ist
für die Umsetzung zu entscheiden: entweder `**/uv.lock` neben jedem Namen, oder
die Feststellung, dass eine Lockdatei im Wurzelverzeichnis liegt und ein
verschachtelter Fund ein anderes Projekt ist, das seine eigene Konfiguration
haben soll. Der Entwurf empfiehlt das Zweite — ein Monorepo, dessen Teilprojekte
eigene Locks tragen, ist ein Fall für dessen eigene `[policy.paths]`.

## Der dokumentierte Block

Neuer Abschnitt in `README.md` und `README.de.md`, direkt hinter *What is
blocked without any configuration* / *Ohne Konfiguration*, überschrieben *Was ein
Projekt selbst ergänzen sollte*:

```toml
[[policy.paths.rules]]
regex  = "(^|/)migrations/\d{4}_[^/]+\.py$"
reason = "a generated migration is rewritten by makemigrations, not by hand"
```

`regex` und nicht `match`, weil die vierstellige Nummer als Glob
`[0-9][0-9][0-9][0-9]` im README unlesbar wäre. Die beiden Schlüssel schließen
einander aus — das ist die bestehende Schemaregel, keine neue.

Der Abschnitt sagt auch, warum das hier steht und nicht eingebaut ist — sonst
liest es sich wie ein Versäumnis.

## Tests

Der eine Codeteil, der über die Regelkonstante hinausgeht, ist ein Test über den
README-Block. Er

1. schneidet den TOML-Block aus `README.md` (Fence mit ```toml unter der
   bekannten Überschrift),
2. schreibt ihn als `.ultraloom/config.toml` in ein `tmp_path`,
3. lädt ihn mit `load_ruleset` und
4. prüft ihn gegen `apps/core/migrations/0002_add_field.py` (verweigert) und
   `apps/core/models.py` (erlaubt).

Damit wird ein Beispiel, das nicht parst oder nicht trifft, rot statt still
falsch. Ein Doku-Vorschlag, den niemand nachrechnet, ist in sechs Monaten eine
Lüge — dasselbe Argument, das `test_flow_docs.py` trägt.

Dazu die gewöhnlichen Tests der neuen Regelgruppe: `uv.lock` wird verweigert,
`requirements.txt` nicht, und `defaults = false` wirft auch diese Gruppe weg.

## Doku

Beide READMEs: die neue Regelgruppe im Defaults-Abschnitt, mit ihrer Begründung
und mit `requirements.txt` als benannter Ausnahme. Der einleitende Satz zählt
dann drei Gruppen auf — Geheimnisse, die Kontrollen des Gates, generierte
Dateien — statt der heutigen zwei.

## Ausdrücklich nicht in diesem Vorhaben

- Regeln gegen Kommandos. `commands` bleibt leer. Wer `uv lock` von Hand aufruft,
  tut das Richtige, und ein Verbot von `pip` ist Hausordnung.
- Eine Erkennung generierter Dateien am Inhalt (Kopfzeilen wie "DO NOT EDIT").
  Reizvoll, aber es ist eine `content`-Regel gegen eine Zeichenkette, die jede
  handgeschriebene Datei ebenso tragen kann.
