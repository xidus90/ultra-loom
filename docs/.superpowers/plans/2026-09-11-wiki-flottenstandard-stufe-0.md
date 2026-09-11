# Wiki-Flottenstandard, Stufe 0 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ulinit` erkennt das Wiki eines Projekts richtig — es liest brains ersten Manifestnamen und nimmt kein Schwester-Wiki einer fremden Projektfamilie mehr —, und `ultraloom` selbst verzeichnet sein eigenes Wiki.

**Architecture:** Zwei Korrekturen in der reinen Erkennung (`internal/detect`), beide ohne neue Datenquelle: `readWiki` folgt brains Suchreihenfolge `.ultra-brain/config.toml` vor `.brain.toml`, und `NeighbourWiki` verlangt, dass ein `<familie>_wiki` zur Familie des Projekts gehört. Weil eine verzeichnete Antwort die Erkennung schlägt, heilt das bestehende Projekte nicht; `ultraloom`s eigene `answers.toml` wird deshalb von Hand gesetzt, wie ihr Kopf es ausdrücklich erlaubt.

**Tech Stack:** Go 1.27, `testing/fstest`, das Commit-Gate `uv run ultraloom check all`.

**Spec:** `docs/.superpowers/specs/2026-09-10-wiki-flottenstandard-design.md`, Abschnitt D2 und Stufe 0. Die Spec ist vor diesem Plan an zwei Stellen berichtigt worden; der Plan folgt der berichtigten Fassung.

## Global Constraints

- Kommentare, Bezeichner, Fehlermeldungen und Commit-Nachrichten englisch; Prosa in `docs/hooks.md` englisch mit deutschem Zwilling `docs/hooks.de.md`, beide werden gemeinsam geändert.
- TDD: jeder Code-Schritt beginnt mit einem Test, der vorher rot ist.
- Deckung sinkt nicht: `internal/detect` steht vor dem Plan bei 99,2 %, `cmd/init` bei 97,8 %; neuer Code ist voll gedeckt. Der Go-Boden des Gates ist 98,0.
- Kein `Co-Authored-By` und keine Nennung eines Modells im Commit. Mehrzeilige Nachrichten über eine Datei und `git commit -F`.
- Vor jedem Commit `git rev-parse --abbrev-ref HEAD`, `git log --oneline -1` und `git diff --cached --stat` lesen. Der Checkout wird von parallelen Sitzungen mitbenutzt.
- Nur die Dateien stagen, die der Task nennt. Im Baum liegen fremde, offene Änderungen, die **nicht** mitgehen: `.gitignore`, `.mcp.json`, `docs/wiki/log.md` und die ungetrackten Katalogartefakte (`index.md`, `graph.json`, `_identities.tsv`, `layout.json`, `docs/**/index.md`).
- Kein Push.
- Erkennung wird mit `go run ./cmd/init …` gemessen, nicht mit dem `ulinit` auf dem PATH — das PATH-Binär ist ein anderer Stand als der Baum unter Änderung.
- Ein Shell-Befehl je Schritt.

---

### Task 1: `readWiki` folgt brains Suchreihenfolge

**Warum:** `ultraloom` trägt `.ultra-brain/config.toml` mit `wiki = true`. `readWiki` liest nur `.brain.toml`, findet also nichts, meldet eine Unklarheit — und erst deshalb kommt `NeighbourWiki` zum Zug. brain selbst sucht `.ultra-brain/config.toml` **zuerst** und liest `.brain.toml` nie, wenn die erste Datei lesbar ist (`manifestNames` in `ultra-brain/pkg/config/manifest.go`).

**Files:**
- Modify: `internal/detect/detect.go` — der erste Block von `readWiki`
- Test: `internal/detect/detect_test.go`
- Modify: `docs/hooks.md` und `docs/hooks.de.md` — Abschnitt „Configuration & Sources of Truth" / „Konfiguration", Punkt 1

**Interfaces:**
- Consumes: nichts aus anderen Tasks.
- Produces: `Detect(root fs.FS) Facts` unverändert in der Signatur. Neu im Verhalten: eine lesbare `.ultra-brain/config.toml` entscheidet, `.brain.toml` wird dann nicht gelesen. Zwei neue unexportierte Funktionen: `firstManifest(root fs.FS) (string, bool)` und `declaresWiki(manifest string) bool`.

- [ ] **Step 1: Die zwei roten Tests schreiben**

An das Ende von `internal/detect/detect_test.go` anhängen:

```go
// brain looks for .ultra-brain/config.toml before .brain.toml, and a project
// set up by `brain init` carries only the first. Detection that read only the
// second found no wiki in ultraloom and fell through to a neighbour.
func TestUltraBrainConfigDeclaresTheWikiLikeBrainToml(t *testing.T) {
	facts := Detect(fstest.MapFS{
		".ultra-brain/config.toml": {Data: []byte("[area]\nscope = \"project/ultraloom\"\nwiki = true\n")},
		"docs/wiki/index.md":       {Data: []byte("# Katalog\n")},
	})
	if facts.WikiMode != "brain" || facts.WikiPath != "docs/wiki/" {
		t.Fatalf("got %q %q, want \"brain\" \"docs/wiki/\"", facts.WikiMode, facts.WikiPath)
	}
}

// Where both names exist, brain reads the first and never the second. So must
// detection, or the two tools would answer the same repository differently.
func TestUltraBrainConfigWinsOverBrainToml(t *testing.T) {
	facts := Detect(fstest.MapFS{
		".ultra-brain/config.toml": {Data: []byte("[area]\nscope = \"project/x\"\n")},
		".brain.toml":              {Data: []byte("[area]\nwiki = true\n")},
		"docs/wiki/index.md":       {Data: []byte("# Katalog\n")},
	})
	if facts.WikiMode != "" {
		t.Fatalf("mode = %q: .brain.toml was read although .ultra-brain/config.toml exists", facts.WikiMode)
	}
}
```

- [ ] **Step 2: Rot sehen**

Run: `go test ./internal/detect/ -run TestUltraBrainConfig -v`

Expected: FAIL, beide Tests. Der erste mit `got "" ""`, der zweite mit `mode = "brain": .brain.toml was read although .ultra-brain/config.toml exists`.

- [ ] **Step 3: `readWiki` umbauen**

In `internal/detect/detect.go` den ersten Block von `readWiki` — von `if brainToml, err := fs.ReadFile(root, ".brain.toml"); err == nil {` bis zu seiner schließenden Klammer vor der Schleife `for _, cand := range []string{"wiki", "docs/wiki"}` — ersetzen durch:

```go
	if manifest, ok := firstManifest(root); ok && declaresWiki(manifest) {
		facts.WikiMode = "brain"
		facts.WikiPath = "wiki/"
		for _, cand := range []string{"docs/wiki", "wiki"} {
			if _, err := fs.Stat(root, cand); err == nil {
				facts.WikiPath = cand + "/"
				break
			}
		}
		return
	}
```

Und unterhalb von `readWiki` einfügen:

```go
// manifestNames is brain's own search order (ultra-brain/pkg/config/manifest.go).
// The first file that can be read decides, and the second is then never
// consulted -- a repository carrying both is answered from the first alone.
var manifestNames = []string{".ultra-brain/config.toml", ".brain.toml"}

// firstManifest returns the text of the first manifest brain would read.
func firstManifest(root fs.FS) (string, bool) {
	for _, name := range manifestNames {
		if data, err := fs.ReadFile(root, name); err == nil {
			return string(data), true
		}
	}
	return "", false
}

// declaresWiki reads the one thing detection needs from a manifest: whether
// it says this area has a wiki, as `wiki = true` or as a `[wiki]` table.
// A `wiki = "docs/wiki"` under [layout] names a place and says nothing about
// whether there is a wiki, so only the literal true counts.
func declaresWiki(manifest string) bool {
	for _, line := range strings.Split(manifest, "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "[wiki]") {
			return true
		}
		if strings.HasPrefix(trimmed, "wiki") && strings.Contains(trimmed, "=") {
			value := strings.TrimSpace(strings.TrimPrefix(trimmed, "wiki"))
			value = strings.TrimSpace(strings.TrimPrefix(value, "="))
			if value == "true" {
				return true
			}
		}
	}
	return false
}
```

Die Semantik von `declaresWiki` ist die des ersetzten Blocks, Zeile für Zeile: `[wiki]`-Kopf oder `wiki = true`, sonst nichts. Ein lesbares Manifest ohne Wiki fällt wie bisher in die Verzeichnisschleife darunter.

- [ ] **Step 4: Grün sehen, mit Deckung**

Run: `go test ./internal/detect/ -cover`

Expected: `ok` und `coverage:` mindestens `99.2% of statements`. Die bestehenden `.brain.toml`-Tests (`TestBrainTomlWithWikiIsDetectedAsBrainMode`, `TestDetectWikiBundleAndContainsVariants`) laufen unverändert mit.

- [ ] **Step 5: Die Hook-Seite nachziehen, englisch**

In `docs/hooks.md` ersetzen:

```markdown
1. **UltraBrain (`.brain.toml`):**
   * Declares whether the repository has an active wiki layer (`[area] wiki = true`) and specifies the layout directory.
   * If `.brain.toml` is absent or `wiki = false`, all wiki gates remain disabled by default.
```

durch:

```markdown
1. **UltraBrain (`.ultra-brain/config.toml`, else `.brain.toml`):**
   * Declares whether the repository has an active wiki layer (`[area] wiki = true`) and specifies the layout directory.
   * The two names are brain's own search order: the first file that can be read decides, and the second is then not consulted.
   * If the deciding file does not declare `wiki = true`, all wiki gates remain disabled by default.
```

- [ ] **Step 6: Die Hook-Seite nachziehen, deutsch**

In `docs/hooks.de.md` ersetzen:

```markdown
1. **UltraBrain (`.brain.toml`):**
   * Definiert, ob das Repository ein Brain-Bereich mit Wiki-Ebene ist (`[area] wiki = true`) und legt das Layout fest.
   * Fehlt die `.brain.toml` oder ist `wiki = false`, bleiben Wiki-Hooks standardmäßig deaktiviert.
```

durch:

```markdown
1. **UltraBrain (`.ultra-brain/config.toml`, sonst `.brain.toml`):**
   * Definiert, ob das Repository ein Brain-Bereich mit Wiki-Ebene ist (`[area] wiki = true`) und legt das Layout fest.
   * Die zwei Namen sind brains eigene Suchreihenfolge: die erste lesbare Datei entscheidet, die zweite wird dann nicht gelesen.
   * Erklärt die entscheidende Datei nicht `wiki = true`, bleiben Wiki-Hooks standardmäßig deaktiviert.
```

- [ ] **Step 7: Stagen und den Index lesen**

Run: `git add internal/detect/detect.go internal/detect/detect_test.go docs/hooks.md docs/hooks.de.md`

Dann: `git diff --cached --stat` — Expected: genau diese vier Dateien.

- [ ] **Step 8: Commit**

Nachricht in eine Datei außerhalb des Index schreiben, etwa `docs/.superpowers/sdd/msg-task1.txt` (per `.gitignore:2` ignoriert):

```text
Read the manifest brain reads first before deciding there is no wiki

Detection looked for .brain.toml only. brain itself looks for
.ultra-brain/config.toml first and never reads .brain.toml when the first
file can be read, and a project set up by `brain init` carries only the
first. ultraloom is such a project: its manifest says wiki = true, detection
found nothing, raised the plain-folder question, and fell through to a
neighbour wiki -- which is how another project's wiki came to be recorded as
this one's.

readWiki now follows brain's order through firstManifest and decides from
that file alone. declaresWiki keeps the old test line for line: a [wiki]
table or a literal wiki = true, never a [layout] wiki path.
```

Run: `git commit -F docs/.superpowers/sdd/msg-task1.txt`

Expected: Commit-Gate grün (lint, types, test, coverage), eine Zeile `[master <hash>] Read the manifest brain reads first before deciding there is no wiki`.

---

### Task 2: `NeighbourWiki` nimmt nur ein Wiki der eigenen Familie

**Warum:** `NeighbourWiki` nimmt heute jedes Schwesterverzeichnis auf `_wiki` mit `.git`. Unter `#GIT/` steht genau eines, `iam_wiki`, und `ultraloom` bekam es verzeichnet. Die gelebte Konvention ist `<familie>_wiki`: `iam_backend`, `iam_design`, `iam_docs`, `iam_frontend` und `iam_workers` teilen `iam_wiki`. Ein Abgleich gegen brains Registry kann das nicht entscheiden — `iam_wiki` ist dort ein eigener Bereich ohne Verbindung zu `iam_backend`. Der Name kann es.

**Files:**
- Modify: `internal/detect/edges.go` — `NeighbourWiki` und sein Docstring, neue Funktion `ofFamily`
- Test: `internal/detect/edges_test.go`
- Test: `cmd/init/main_test.go`

**Interfaces:**
- Consumes: nichts aus Task 1 (anderer Codeweg; `gather` fragt `NeighbourWiki` nur, wenn `Detect` keine Mode fand).
- Produces: `NeighbourWiki(parent fs.FS, projectDir string) (mode string, wikiPath string)` unverändert in der Signatur. Neu: unexportiertes `ofFamily(projectDir, family string) bool`.

- [ ] **Step 1: Die roten Tests in `edges_test.go` schreiben**

An das Ende von `internal/detect/edges_test.go` anhängen:

```go
// The iam repositories share one wiki: iam_backend, iam_frontend and
// iam_workers all keep theirs in iam_wiki. The convention is <family>_wiki,
// for the family itself and for every <family>_* sibling.
func TestNeighbourWikiServesTheWholeFamily(t *testing.T) {
	parent := fstest.MapFS{"iam_wiki/.git/HEAD": {Data: []byte("ref\n")}}
	for _, project := range []string{"iam", "iam_backend", "iam_frontend", "iam_workers"} {
		t.Run(project, func(t *testing.T) {
			mode, wikiPath := NeighbourWiki(parent, project)
			if mode != "neighbour_repo" || wikiPath != "iam_wiki/" {
				t.Fatalf("got %q %q, want \"neighbour_repo\" \"iam_wiki/\"", mode, wikiPath)
			}
		})
	}
}

// Measured on 2026-09-10: ultraloom, which only stands beside iam_wiki in the
// same parent directory, had that wiki recorded as its own. A shared parent
// directory is not a family, and neither is a shared first few letters.
func TestNeighbourWikiDoesNotTakeAnotherFamilysWiki(t *testing.T) {
	parent := fstest.MapFS{"iam_wiki/.git/HEAD": {Data: []byte("ref\n")}}
	for _, project := range []string{"ultraloom", "space", "iamx", "iamx_backend"} {
		t.Run(project, func(t *testing.T) {
			if mode, wikiPath := NeighbourWiki(parent, project); mode != "" || wikiPath != "" {
				t.Fatalf("got %q %q, want empty", mode, wikiPath)
			}
		})
	}
}
```

- [ ] **Step 2: Den Endtest in `main_test.go` schreiben**

In `cmd/init/main_test.go` direkt unter `TestDetectOnlyFindsTheNeighbourWiki` einfügen:

```go
// The end-to-end form of the 2026-09-10 finding: a project that only shares a
// parent directory with another family's wiki must not be told it is its own.
func TestDetectOnlyLeavesAnotherFamilysWikiAlone(t *testing.T) {
	parent := t.TempDir()
	root := filepath.Join(parent, "ultraloom")
	mkdir(t, root)
	mkdir(t, filepath.Join(parent, "iam_wiki", ".git"))

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := cli([]string{"--detect-only", "--root", root}, nothing(), stdout, stderr); code != 0 {
		t.Fatalf("exit = %d, want 0 (stderr: %s)", code, stderr)
	}
	var facts detect.Facts
	if err := json.Unmarshal(stdout.Bytes(), &facts); err != nil {
		t.Fatalf("stdout is not JSON: %v", err)
	}
	if facts.WikiMode != "" || facts.WikiPath != "" {
		t.Fatalf("wiki = %q %q, want none: iam_wiki belongs to the iam family", facts.WikiMode, facts.WikiPath)
	}
}
```

- [ ] **Step 3: Rot sehen**

Run: `go test ./internal/detect/ ./cmd/init/ -run "NeighbourWiki|DetectOnlyLeavesAnotherFamilysWikiAlone" -v`

Expected: FAIL in `TestNeighbourWikiDoesNotTakeAnotherFamilysWiki` (alle vier Unterfälle, `got "neighbour_repo" "iam_wiki/"`) und in `TestDetectOnlyLeavesAnotherFamilysWikiAlone` (`wiki = "neighbour_repo" "iam_wiki/"`). `TestNeighbourWikiServesTheWholeFamily` ist schon grün — die heutige lose Prüfung trifft die Familie ebenfalls, nur eben auch alles andere.

- [ ] **Step 4: `NeighbourWiki` verschärfen**

In `internal/detect/edges.go` die Funktion `NeighbourWiki` samt Docstring ersetzen durch:

```go
// NeighbourWiki looks beside the project rather than inside it.
//
// A family of repositories can keep one wiki as a sibling repository named
// `<family>_wiki`: iam_backend, iam_frontend and iam_workers all keep theirs
// in iam_wiki. That wiki belongs to `<family>` and to every `<family>_*`
// sibling, and to nobody else. Until 2026-09-11 the suffix alone decided, and
// ultraloom, which merely stands in the same parent directory, had iam_wiki
// recorded as its own.
//
// The wiki lies outside the project root and is therefore invisible to
// Detect. The parent directory is taken as an fs.FS for the same testability,
// and projectDir names the project within it so a repository called `x_wiki`
// does not find itself.
func NeighbourWiki(parent fs.FS, projectDir string) (mode string, wikiPath string) {
	entries, err := fs.ReadDir(parent, ".")
	if err != nil {
		return "", ""
	}
	for _, entry := range entries {
		name := entry.Name()
		family, isWiki := strings.CutSuffix(name, "_wiki")
		if !entry.IsDir() || name == projectDir || !isWiki || !ofFamily(projectDir, family) {
			continue
		}
		// A directory of notes is not a wiki repository; the commit duty
		// this mode brings needs something to commit into.
		if _, err := fs.Stat(parent, path.Join(name, ".git")); err != nil {
			continue
		}
		return "neighbour_repo", name + "/"
	}
	return "", ""
}

// ofFamily says whether projectDir belongs to the family a wiki is named for:
// the family itself, or a sibling joined to it by an underscore. The
// underscore is the whole test -- iamx shares three letters with iam and is
// not a member.
func ofFamily(projectDir, family string) bool {
	return projectDir == family || strings.HasPrefix(projectDir, family+"_")
}
```

- [ ] **Step 5: Die zwei Ablehnungstests wieder scharf machen**

Nach Step 4 bestehen die Fälle `"no .git"` und `"a file, not a directory"` in `TestNeighbourWikiDeclinesWhatIsNotARepository` zu leicht: `notes_wiki` und `stray_wiki` gehören nicht zur Familie von `"project"` und scheitern schon an `ofFamily`, bevor die `.git`- und die Verzeichnisprüfung überhaupt laufen. Der Test prüfte dann nicht mehr, was sein Name sagt, und die `.git`-Zeile verlöre ihre Deckung.

In `internal/detect/edges_test.go` ersetzen:

```go
		"no .git":                 {"notes_wiki/index.md": {Data: []byte("# notes\n")}},
		"wrong name":              {"docs/.git/HEAD": {Data: []byte("ref\n")}},
		"a file, not a directory": {"stray_wiki": {Data: []byte("not a directory\n")}},
```

durch:

```go
		// Named for the family of "project", so each case reaches the check
		// it is about instead of failing on the family first.
		"no .git":                 {"project_wiki/index.md": {Data: []byte("# notes\n")}},
		"wrong name":              {"docs/.git/HEAD": {Data: []byte("ref\n")}},
		"a file, not a directory": {"project_wiki": {Data: []byte("not a directory\n")}},
```

- [ ] **Step 6: Grün sehen, mit Deckung**

Run: `go test ./internal/detect/ ./cmd/init/ -cover`

Expected: beide `ok`; `internal/detect` mindestens `99.2%`, `cmd/init` mindestens `97.8%`. `TestNeighbourWikiFindsTheSiblingRepository` (`iam_backend` mit `iam_backend_wiki`) und `TestNeighbourWikiDoesNotFindTheProjectItself` (`space_wiki`) laufen unverändert mit.

- [ ] **Step 7: Stagen und den Index lesen**

Run: `git add internal/detect/edges.go internal/detect/edges_test.go cmd/init/main_test.go`

Dann: `git diff --cached --stat` — Expected: genau diese drei Dateien.

- [ ] **Step 8: Commit**

Nachricht in `docs/.superpowers/sdd/msg-task2.txt`:

```text
Take a sibling wiki only from the project's own family

NeighbourWiki accepted any sibling directory ending in _wiki with a .git in
it, and excluded only the project itself. Under #GIT/ there is one such
directory, iam_wiki, so ultraloom -- which merely stands in the same parent
directory -- was told iam_wiki is its wiki, and recorded it.

The name that looked too loose is also what made the iam repositories work:
iam_backend, iam_frontend and iam_workers all keep their wiki in iam_wiki,
not in iam_backend_wiki. The convention in use is <family>_wiki, for the
family and for every <family>_* sibling, and ofFamily is that test. A check
against brain's registry was considered and cannot decide: iam_wiki is an
area of its own there, and nothing links it to iam_backend.

Two rejection cases in TestNeighbourWikiDeclinesWhatIsNotARepository are
renamed into the family of their project, because after this change they
would fail on the family before reaching the .git and directory checks they
are named for.
```

Run: `git commit -F docs/.superpowers/sdd/msg-task2.txt`

Expected: Commit-Gate grün, eine Zeile `[master <hash>] Take a sibling wiki only from the project's own family`.

---

### Task 3: `ultraloom` verzeichnet sein eigenes Wiki

**Warum:** Task 1 und 2 reparieren die Erkennung für jedes künftige `ulinit`. Dieses Repo hat aber schon geantwortet, und eine verzeichnete Antwort schlägt die Erkennung (`applyFlags`, `cmd/init/run.go`: „Where answers.toml already holds an answer, that answer wins"). Die falsche Antwort muss deshalb von Hand ersetzt werden. Das ist der vorgesehene Weg: der Kopf der Datei sagt „safe to edit by hand", und der `[answers] sha256` in `.ultraloom/installed.toml` wird nur geschrieben, nirgends verglichen.

**Files:**
- Modify: `.ultraloom/answers.toml` — Tabelle `[gates.wiki]`
- Modify: `OFFENE_AUFGABEN.md` — Abschnitt 1 (Matrixzeile „Wiki-Flottenstandard") und Abschnitt 6 (erster Punkt)

**Interfaces:**
- Consumes: Task 1 (`.ultra-brain/config.toml` wird gelesen) und Task 2 (`iam_wiki` wird nicht mehr genommen), beide committet.
- Produces: `.ultraloom/answers.toml` mit `mode = "brain"`, `bundle = "docs/wiki/"`. Das ist die Eingabe, auf die Stufe 2 der Spec (`brain wiki-gate` auf Stop, `.agents/hooks.json`) aufsetzt.

- [ ] **Step 1: Die Erkennung am echten Repo messen**

Run: `go run ./cmd/init --detect-only --root .`

Expected: JSON mit den Zeilen `"WikiMode": "brain",` und `"WikiPath": "docs/wiki/",`. Steht dort `"neighbour_repo"` oder ein leerer Wert, **anhalten und melden** — dann greift Task 1 oder 2 am echten Baum nicht.

- [ ] **Step 2: Die Antwort ersetzen**

In `.ultraloom/answers.toml` ersetzen:

```toml
[gates.wiki]
mode   = "neighbour_repo"
bundle = "iam_wiki/"
```

durch:

```toml
[gates.wiki]
mode   = "brain"
bundle = "docs/wiki/"
```

Sonst nichts an der Datei ändern.

- [ ] **Step 3: Messen, was das nächste `ulinit` täte, ohne es zu tun**

Run: `go run ./cmd/init --dry-run --yes --root .`

Expected: Exit 0, und im Bericht steht unter `would create:` die Zeile `.claude/settings.json (merged)` — das ist der `brain wiki-gate`-Stop-Eintrag, den `hookEntries` jetzt für den Modus `brain` bildet. `--dry-run` schreibt nichts.

Fehlt die Zeile, **anhalten und melden**: dann hat `brainEntry` die neue Antwort nicht gesehen, oder `brain` ist nicht auf dem PATH (dann steht unter `note:` „brain is neither on PATH nor named by ULTRA_BRAIN_DIR").

**`ulinit` in dieser Stufe nicht ohne `--dry-run` fahren.** Die Hookeinträge sind Stufe 2 der Spec, und `.mcp.json` hat eine offene Entscheidung (`brain` gegen `brain-mcp`).

- [ ] **Step 4: Den Tracker nachziehen, Abschnitt 6**

In `OFFENE_AUFGABEN.md` ersetzen:

```markdown
      überstimmt hat. Hier eingetragen seit `e84df9e` (2026-08-29). Die
      Reparatur ist Stufe 0 des Flottenstandards.
```

durch:

```markdown
      überstimmt hat. Hier eingetragen seit `e84df9e` (2026-08-29).
      **Behoben in Stufe 0 des Flottenstandards**, nach
      `docs/.superpowers/plans/2026-09-11-wiki-flottenstandard-stufe-0.md`:
      `readWiki` liest `.ultra-brain/config.toml` vor `.brain.toml`,
      `NeighbourWiki` nimmt nur ein Wiki der eigenen Familie, und
      `.ultraloom/answers.toml` sagt `mode = "brain"`, `bundle = "docs/wiki/"`.
      Die Commits nennt
      `git log --oneline -- internal/detect/detect.go internal/detect/edges.go .ultraloom/answers.toml`.
      Wirksam wird die Antwort erst mit dem nächsten `ulinit`-Lauf, und der
      gehört zu Stufe 2.
```

- [ ] **Step 5: Den Tracker nachziehen, Abschnitt 1**

In der Matrixzeile „Wiki-Flottenstandard" ersetzen:

```markdown
| 📝 **entworfen** |
```

durch:

```markdown
| 🟡 **Stufe 0 umgesetzt** |
```

und in derselben Zeile ersetzen:

```markdown
| Die Spec vom Nutzer abnehmen lassen, dann ein Plan für Stufe 0 (`NeighbourWiki` gegen die Registry, `answers.toml` dieses Repos auf `brain`). Die Sperre durch den Go-Hooks-Zweig ist mit `6168ef2` gefallen |
```

durch:

```markdown
| Stufe 1 planen: `answers.Answers` um brains Entscheidungen erweitern und `.brain.toml` daraus erzeugen. Stufe 0 (Erkennung und die eigene Antwort) ist umgesetzt, siehe Abschnitt 6 |
```

- [ ] **Step 6: Das volle Gate fahren**

Run: `uv run ultraloom check all`

Expected: Exit 0 — `lint: ok`, `types: ok`, `test: ok`, `coverage: ok`, Go-Coverage mindestens 98,0 %.

- [ ] **Step 7: Stagen und den Index lesen**

Run: `git add .ultraloom/answers.toml OFFENE_AUFGABEN.md`

Dann: `git diff --cached --stat` — Expected: genau diese zwei Dateien.

- [ ] **Step 8: Commit**

Nachricht in `docs/.superpowers/sdd/msg-task3.txt`:

```text
Record ultraloom's own wiki instead of another project's

.ultraloom/answers.toml said mode = "neighbour_repo", bundle = "iam_wiki/"
since e84df9e: the detector's proposal, taken by an unattended run. iam_wiki
is another project, and because brainEntry writes the brain entries only
for mode = "brain", nothing here was ever wired to this repository's own
wiki under docs/wiki.

The two preceding commits fix detection for every future run, but a
recorded answer wins over detection, so this repository has to be corrected
by hand -- which the file's own header allows, and which nothing checks
against the installed hash.

Measured before the change: `go run ./cmd/init --detect-only --root .` now
answers brain and docs/wiki/. Measured after it, without writing:
`--dry-run --yes` lists .claude/settings.json as merged, which is the
brain wiki-gate Stop entry. That run is left to stage 2 of the fleet spec,
as is the open .mcp.json question.
```

Run: `git commit -F docs/.superpowers/sdd/msg-task3.txt`

Expected: Commit-Gate grün, eine Zeile `[master <hash>] Record ultraloom's own wiki instead of another project's`.

---

## Außerhalb dieses Plans

- **`[relevance] "wiki/**" = ["brain reindex"]`** in `ultraloom`s `answers.toml` trifft `docs/wiki/**` nicht. Eine Seite unter `docs/wiki/` löst also keinen Reindex aus. Das gehört zu Stufe 1, wo die Antwortdatei brains Pfade ohnehin lernt.
- **Die drei iam-Coderepos** tragen `bundle = "iam_wiki/"` verzeichnet und bleiben nach diesem Plan richtig — Task 2 nimmt ihnen nichts, weil `iam_*` zur Familie gehört. Sie werden nicht angefasst.
- **Das `ulinit` auf dem PATH** kennt die Änderungen dieses Plans erst nach einem Neubau über `scripts/install.ps1`. Kein Task hängt davon ab; wer danach `ulinit` beim Namen ruft, sollte neu bauen.
