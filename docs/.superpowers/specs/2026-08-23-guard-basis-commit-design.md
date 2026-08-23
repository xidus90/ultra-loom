# Guard misst gegen einen Basis-Commit

Entwurf, 23.08.2026.

## Das Problem

`make_guard` fragt `changed_files`, und das fragt `git status --porcelain`
— also den Arbeitsbaum gegen HEAD. Committet der Reparateur seine Änderung,
ist der Arbeitsbaum sauber: `status` meldet nichts, `touched` ist leer,
`forbidden` ist leer, und eine geänderte Testdatei geht durch die Sperre.
Dieselbe leere Antwort trifft nebenbei `_stagnated`, das eine erfolgreiche
Reparaturrunde dann als Stillstand liest.

Heute ist das nur dadurch entschärft, dass das Werkzeugprofil `edit` kein
Bash enthält, der Reparateur also gar nicht committen kann. Die Sperre hängt
damit an einer Profilentscheidung, die anderswo aus ganz anderem Grund
gelockert werden kann — sie ist kein Teil der Sperre selbst.

## Die Regel

Der guard beantwortet die Frage „was hat der Reparaturlauf getan", und der
Bezugspunkt dieser Frage ist der Zustand beim Start des Laufs. Dieser Zustand
besteht aus zwei Teilen, und keiner ersetzt den anderen:

- dem **Commit**, auf dem der Lauf begonnen hat, und
- dem, was zu diesem Zeitpunkt schon **schmutzig** im Baum lag.

Der Commit fängt alles, was der Reparateur seither committet hat. Die
Schmutzmenge entschuldigt weiterhin, was vor dem Lauf schon geändert war und
dem Reparateur nicht angelastet werden darf. Beides zusammen ist die
Grundlinie.

Gemessen, nicht verboten: ein Commit des Reparateurs bleibt erlaubt und wird
sichtbar wie eine Arbeitsbaum-Änderung. Nur eine berührte Testdatei löst
Exit 4 aus. `reset`, `rebase` und `amend` verstecken dabei nichts, weil der
Diff inhaltsbasiert ist — er vergleicht den Baum des Basis-Commits mit dem
Arbeitsbaum und nicht zwei Historien.

## Was sich ändert

### `worktree.py`

Zwei Funktionen neben `changed_files`, das unverändert bleibt (die CLI
braucht es weiter für die Schmutzmenge):

- `head_commit(root) -> str` — `git rev-parse HEAD`. `WorktreeError`, wenn
  es keinen gibt: kein Repository, Repository ohne Commit, unauflösbarer
  HEAD. `_refuse_if_ignored` gilt hier ebenfalls: eine Projektkopie unter
  einem ignorierten Pfad liegt immer noch in einem Repository, `rev-parse
  HEAD` liefert dort bereitwillig den SHA des umgebenden Repositories, und
  gegen den zu messen wäre schlimmer als gar nicht zu messen -- der Diff
  nennt dann jede Datei der Kopie als Änderung des Reparateurs.
  Ein detached HEAD ist ausdrücklich **kein** Sonderfall — `rev-parse
  HEAD` liefert dort denselben SHA wie sonst, und der Diff braucht keinen
  Zweignamen.
- `changed_since(root, base) -> tuple[str, ...]` — die Vereinigung aus
  `git diff --name-only --no-renames <base>` (verfolgte Dateien, das
  Committete eingeschlossen) und den untracked-Pfaden aus dem heutigen
  `status`. `--no-renames`, damit eine Umbenennung als alter *und* neuer
  Pfad erscheint statt als ein Feld, das der guard erst deuten müsste.

Beide Antworten laufen durch dieselbe `_prefix`-Umrechnung und denselben
`RUN_DIR`-Ausschluss wie `changed_files` heute. Eine Relokation, nicht zwei:
zwei Umrechnungen derselben Pfade würden genau in den Parsing-Details
auseinanderlaufen, für die dieses Modul existiert.

`_refuse_if_ignored` gilt für `changed_since` genauso: ein von git
ignorierter Root beantwortet auch einen Diff nicht vollständig.

### Grundlinie und Marker

`FlowContext.baseline` wird von `frozenset[str] | None` zu
`Baseline | None` mit

```python
@dataclass(frozen=True, slots=True)
class Baseline:
    commit: str
    dirty: frozenset[str]
```

Der Marker bekommt neben `baseline=` eine Zeile `baseline_commit=`. Fehlt
sie, gibt `_recorded_run` für die Grundlinie `None` zurück, und `resume`
wie `replay` enden mit einer Meldung, die sagt, dass dieser Lauf vor der
Verschärfung gestartet wurde und neu gestartet werden muss. Den SHA beim
Fortsetzen nachzutragen wäre genau das Alibi, das die Grundlinie verhindern
soll: alles vor der Pause Committete wäre dann Ausgangszustand.

### `Differ`

```python
type Differ = Callable[[Path, str], tuple[str, ...]]
```

Der Basis-Commit wandert in die Signatur, damit die Testinjektion sieht,
wogegen gemessen wird, statt ihn hinter einem Closure zu verstecken.

### Absage ohne Basis-Commit

In `verify_until_green.build`, nicht in der CLI. Ein Flow ohne guard braucht
keinen Basis-Commit, und die CLI weiß nicht, welcher Flow einen braucht.
`_baseline` in der CLI nimmt den SHA auf, wenn es einen gibt, und bleibt
sonst ohne. Die Absage fällt damit einmal, an der Stelle, die sie begründen
kann, und **vor** der ersten Reparaturrunde statt danach — heute läuft ein
Projekt ohne Repository erst eine ganze Runde und stirbt dann im guard an
einem `WorktreeError`.

Die Meldung nennt den Grund und den Ausweg: ohne Commit gibt es keinen
Bezugspunkt, gegen den eine berührte Testdatei feststellbar wäre.

## Tests

TDD, jeder Fall vor seiner Implementierung rot. Echte Repositories in
`tmp_path`, keine Attrappe für git: dieses Modul existiert wegen der
Parsing-Details, und eine Attrappe würde die Attrappe prüfen.

1. Der Reparateur committet eine Testdatei → Exit 4, die Meldung nennt sie.
2. Der Reparateur committet eine Quelldatei → der Lauf geht weiter, und
   `touched` nennt sie (sonst liest `_stagnated` die Runde als Stillstand).
3. Eine vor dem Lauf schmutzige Testdatei bleibt entschuldigt — auch dann,
   wenn der Reparateur sie anschließend mitcommittet.
4. Umbenennung `tests/a.py` → `src/a.py`, committet → Exit 4.
5. Detached HEAD → wird normal gemessen.
6. Kein Repository → Absage beim Start.
7. Repository ohne Commit → Absage beim Start.
8. Marker ohne `baseline_commit` → `resume` und `replay` verweigern.
9. `--root package` im Monorepo → die Pfade kommen relativ zu `root`
   zurück, aus Diff und `status` gleichermaßen.
10. Ein von git ignorierter Root → `changed_since` verweigert wie
    `changed_files`.

## Dokumentation

`docs/abläufe/verify-until-green.md`: der Graph ändert sich nicht, aber die
Erklärung des guard-Knotens beschreibt das Arbeitsbaum-Messen und wird damit
falsch. Die Docstrings von `make_guard` und `assemble` beschreiben die
Grundlinie ebenfalls als reine Pfadmenge.

## Ausdrücklich nicht Teil davon

- HEAD-Bewegung als solche zu verbieten. Ein Reparateur, der sauber
  committet, tut nichts Verbotenes; der Diff sieht ihn ohnehin.
- Das Werkzeugprofil `edit` zu ändern. Die Sperre soll unabhängig davon
  halten, nicht das Profil ersetzen.
