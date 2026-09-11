# Wiki-Flottenstandard, Stufe 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `.ultraloom/answers.toml` trägt brains Entscheidungen über einen Wiki-Bereich, und `ulinit` erzeugt daraus die `.brain.toml`, die brain liest — für jedes Projekt im Modus `brain`, das noch kein Manifest hat.

**Architecture:** Drei Schichten, jede mit eigenem Test. `internal/answers` bekommt drei Felder in `Wiki` (`Scope`, `Sources`, `Privacy`), die vierte Wiki-Art `vault` und eine reine Funktion, die fehlende Werte mit den Vorgaben von `brain init` füllt. `internal/render` erzeugt aus diesen Antworten eine `.brain.toml` mit der Kopfzeile, die jede erzeugte Datei trägt. `cmd/init` füllt die Vorgaben vor dem Rendern und lässt die `.brain.toml` weg, wo schon eine `.ultra-brain/config.toml` den Bereich erklärt.

**Tech Stack:** Go 1.27, `text/template` mit den Helfern `quote` und `list` aus `internal/render`, `github.com/BurntSushi/toml` in den Tests, brains Python-Manifestleser für den Nachweis.

**Spec:** `docs/.superpowers/specs/2026-09-10-wiki-flottenstandard-design.md`, Abschnitt „Teil 1: `answers.toml` wird die eine Entscheidungsdatei" und Stufentabelle, Zeile 1.

## Global Constraints

- Kommentare, Bezeichner, Fehlermeldungen und Commit-Nachrichten englisch; Prosa in `docs/hooks.md` englisch mit deutschem Zwilling `docs/hooks.de.md`, beide werden gemeinsam geändert.
- TDD: jeder Code-Schritt beginnt mit einem Test, der vorher rot ist.
- Deckung sinkt nicht; neuer Code ist voll gedeckt, mit genau einer benannten Ausnahme in Task 3 (der Fehlerzweig von `filepath.Abs`, den kein Test herstellen kann — dieselbe Ausnahme trägt `gather` in `cmd/init/main.go`). Der Go-Boden des Gates ist 98,0; Python bleibt bei 100 %.
- Kein `Co-Authored-By` und keine Nennung eines Modells im Commit. Mehrzeilige Nachrichten über eine Datei und `git commit -F`.
- Vor jedem Commit `git rev-parse --abbrev-ref HEAD`, `git log --oneline -1` und `git diff --cached --stat` lesen; nur die Dateien stagen, die der Task nennt.
- Kein Push.
- Ein Shell-Befehl je Schritt.
- Erkennung und Installer werden mit `go run ./cmd/init …` gemessen, nicht mit dem `ulinit` auf dem PATH.
- Die erzeugte `.brain.toml` enthält genau: `[area] scope`, `[area] wiki = true`, `[layout] sources`, `[layout] wiki`, `[index] include`, `[privacy] mode`. **Kein `[maintenance]`** (Begründung in Task 2) und **kein `[wiki] path`** (Begründung unter „Außerhalb").

## Entscheidungen, die dieser Plan trifft

Die Spec lässt drei Dinge offen; gemessen am 2026-09-11 entschieden:

1. **Die Vorgaben sind die von `brain init`** (`detect_defaults` in `ultra-brain/src/brain/init.py`): `scope = "project/<Verzeichnisname>"`, `sources = "docs"`, wenn das Projekt einen Ordner `docs` hat, sonst `"."`, das Bündel eine Ebene darunter (`docs/wiki/` beziehungsweise `wiki/`), `privacy = "manual_cloud"`. Ein Projekt, das `ulinit` und `brain init` nacheinander sieht, bekommt so dieselben Werte von beiden.
2. **`vault` wird in Stufe 1 nur ein gültiger Wert**, ohne eigenes Manifest. Wie ein `vault`-Manifest aussehen muss, ist ungemessen: brains Python-Leser kennt `[area] readonly`, und bei einem `readonly`-Bereich liegen Wiki und Katalog laut `ManifestDir` im Zustandsverzeichnis. Das entscheidet eine spätere Stufe.
3. **Die Vorgaben werden zur Laufzeit gefüllt, nicht nur in `Defaults`.** `decisions()` in `cmd/init/run.go` lädt eine verzeichnete `answers.toml` unverändert; jedes bestehende Projekt hat die drei neuen Schlüssel nicht. Weil vorhandene Dateien übersprungen werden und `ultraloom sync` fehlt (Spec-Defekt D5), landen die gefüllten Werte bei einem bestehenden Projekt nicht in dessen `answers.toml`, sondern nur in der `.brain.toml`, die es noch nicht hat.

---

### Task 1: Die Antwortdatei trägt brains Entscheidungen

**Files:**
- Modify: `internal/answers/answers.go` — `Wiki`, `WikiModes`, `Load`, neu `PrivacyModes`, `contains`, `WithBrainDefaults`
- Test: `internal/answers/answers_test.go`
- Test: `internal/interview/interview_test.go`

**Interfaces:**
- Consumes: nichts aus anderen Tasks.
- Produces:
  - `type Wiki struct { Mode, Bundle, Scope, Sources, Privacy string }` mit den TOML-Schlüsseln `mode`, `bundle`, `scope`, `sources`, `privacy`.
  - `var WikiModes = []string{"brain", "neighbour_repo", "vault", "none"}`
  - `var PrivacyModes = []string{"automatic_cloud", "local_only", "manual_cloud"}`
  - `func (w Wiki) WithBrainDefaults(projectName string, hasDocs bool) Wiki`

- [ ] **Step 1: Die roten Tests in `answers_test.go` schreiben**

An das Ende von `internal/answers/answers_test.go` anhängen (`strings` ist dort schon importiert):

```go
func TestLoadReadsTheBrainDecisions(t *testing.T) {
	loaded, err := Load([]byte("[gates.wiki]\nmode    = \"brain\"\nbundle  = \"docs/wiki/\"\n" +
		"scope   = \"project/x\"\nsources = \"docs\"\nprivacy = \"local_only\"\n"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	want := Wiki{Mode: "brain", Bundle: "docs/wiki/", Scope: "project/x", Sources: "docs", Privacy: "local_only"}
	if loaded.Gates.Wiki != want {
		t.Fatalf("wiki = %+v, want %+v", loaded.Gates.Wiki, want)
	}
}

// vault is the fourth kind of wiki: the project's wiki lives in the vault, and
// the area is registered read-only. Stage 1 only has to accept the answer.
func TestLoadAcceptsTheVaultMode(t *testing.T) {
	if _, err := Load([]byte("[gates.wiki]\nmode = \"vault\"\n")); err != nil {
		t.Fatalf("Load refused vault: %v", err)
	}
}

// brain refuses a privacy mode outside its set when it reads the manifest.
// Refused here, the typo is reported where it was made.
func TestLoadRefusesAPrivacyModeBrainWouldRefuse(t *testing.T) {
	_, err := Load([]byte("[gates.wiki]\nmode = \"brain\"\nprivacy = \"public\"\n"))
	if err == nil || !strings.Contains(err.Error(), "privacy") {
		t.Fatalf("err = %v, want a refusal that names privacy", err)
	}
}

func TestBrainDefaultsFollowBrainInitWithADocsFolder(t *testing.T) {
	got := Wiki{Mode: "brain"}.WithBrainDefaults("ultraloom", true)
	want := Wiki{Mode: "brain", Bundle: "docs/wiki/", Scope: "project/ultraloom", Sources: "docs", Privacy: "manual_cloud"}
	if got != want {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

func TestBrainDefaultsFollowBrainInitWithoutADocsFolder(t *testing.T) {
	got := Wiki{Mode: "brain"}.WithBrainDefaults("tool", false)
	want := Wiki{Mode: "brain", Bundle: "wiki/", Scope: "project/tool", Sources: ".", Privacy: "manual_cloud"}
	if got != want {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

func TestBrainDefaultsKeepEveryRecordedAnswer(t *testing.T) {
	recorded := Wiki{Mode: "brain", Bundle: "notes/", Scope: "project/other", Sources: "src", Privacy: "local_only"}
	if got := recorded.WithBrainDefaults("ultraloom", true); got != recorded {
		t.Fatalf("got %+v, want the recorded answers unchanged", got)
	}
}

func TestBrainDefaultsLeaveEveryOtherModeAlone(t *testing.T) {
	for _, mode := range []string{"none", "neighbour_repo", "vault"} {
		w := Wiki{Mode: mode, Bundle: "iam_wiki/"}
		if got := w.WithBrainDefaults("iam_backend", true); got != w {
			t.Fatalf("mode %s: got %+v, want %+v", mode, got, w)
		}
	}
}
```

- [ ] **Step 2: Den roten Test in `interview_test.go` schreiben**

An das Ende von `internal/interview/interview_test.go` anhängen:

```go
func TestTheVaultModeIsAnAnswer(t *testing.T) {
	var out bytes.Buffer
	start := answered()
	start.Gates.Wiki.Mode = ""
	got, err := Run(strings.NewReader("vault\n"), &out, true, start)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if got.Gates.Wiki.Mode != "vault" {
		t.Fatalf("mode = %q, want vault (output: %s)", got.Gates.Wiki.Mode, out.String())
	}
}
```

- [ ] **Step 3: Rot sehen**

Run: `go test ./internal/answers/ ./internal/interview/`

Expected: FAIL beim Übersetzen von `internal/answers` (`unknown field Scope in struct literal`, `w.WithBrainDefaults undefined`). `internal/interview` baut gegen `answers` und fällt mit.

- [ ] **Step 4: `answers.go` erweitern**

In `internal/answers/answers.go` den Typ `Wiki` ersetzen durch:

```go
type Wiki struct {
	Mode   string `toml:"mode"`
	Bundle string `toml:"bundle"`
	// The three below are brain's decisions about this area. ulinit writes
	// .brain.toml from them; for every mode but brain they stay empty.
	Scope   string `toml:"scope"`
	Sources string `toml:"sources"`
	Privacy string `toml:"privacy"`
}
```

`WikiModes` ersetzen durch:

```go
// WikiModes is the whole set. A mode outside it is a typo, and a typo that
// silently disables the wiki gate is the expensive kind.
//
// vault is a project whose wiki lives in the vault rather than in the
// repository, registered read-only -- the shape space has. Stage 1 of the
// fleet wiki standard only accepts it; what a vault project's manifest must
// say is left to a later stage.
var WikiModes = []string{"brain", "neighbour_repo", "vault", "none"}

// PrivacyModes is brain's own set: read_manifest in ultra-brain's
// src/brain/manifest.py and ReadManifest in pkg/config/manifest.go both refuse
// anything else. Checked here, a typo is reported where it was typed rather
// than when brain first reads the manifest.
var PrivacyModes = []string{"automatic_cloud", "local_only", "manual_cloud"}
```

In `Load` direkt nach der Prüfung von `loaded.Gates.Wiki.Mode` einfügen:

```go
	if loaded.Gates.Wiki.Privacy != "" && !contains(PrivacyModes, loaded.Gates.Wiki.Privacy) {
		return Answers{}, fmt.Errorf(
			"answers.toml: [gates.wiki].privacy is %q, must be one of %v",
			loaded.Gates.Wiki.Privacy, PrivacyModes)
	}
```

Die Funktion `valid` ersetzen durch `contains` und ihren Aufruf in `Load` von `!valid(loaded.Gates.Wiki.Mode)` auf `!contains(WikiModes, loaded.Gates.Wiki.Mode)` ändern:

```go
func contains(all []string, value string) bool {
	for _, known := range all {
		if known == value {
			return true
		}
	}
	return false
}
```

Und am Ende der Datei anfügen:

```go
// WithBrainDefaults fills what a brain area needs and the answers do not say,
// with the values `brain init` proposes (detect_defaults in ultra-brain's
// src/brain/init.py): scope project/<directory>, sources docs when the project
// has a docs folder and the repository root otherwise, the bundle one level
// below the sources, privacy manual_cloud. A project that meets both tools is
// then told the same thing by each.
//
// A recorded answer is never replaced, and every mode but brain comes back
// unchanged: those modes write no manifest, and a scope filled in for them
// would be an answer nobody gave.
func (w Wiki) WithBrainDefaults(projectName string, hasDocs bool) Wiki {
	if w.Mode != "brain" {
		return w
	}
	sources, bundle := ".", "wiki/"
	if hasDocs {
		sources, bundle = "docs", "docs/wiki/"
	}
	if w.Scope == "" {
		w.Scope = "project/" + projectName
	}
	if w.Sources == "" {
		w.Sources = sources
	}
	if w.Bundle == "" {
		w.Bundle = bundle
	}
	if w.Privacy == "" {
		w.Privacy = "manual_cloud"
	}
	return w
}
```

- [ ] **Step 5: Grün sehen, mit Deckung**

Run: `go test ./internal/answers/ ./internal/interview/ -cover`

Expected: beide `ok`; `internal/answers` bei 100 %. Die bestehenden Tests, darunter `TestLoadRefusesAnUnknownWikiMode` und `TestAWikiModeOutsideTheSetIsRejected`, laufen unverändert mit.

- [ ] **Step 6: Stagen und den Index lesen**

Run: `git add internal/answers/answers.go internal/answers/answers_test.go internal/interview/interview_test.go`

Dann: `git diff --cached --stat` — Expected: genau diese drei Dateien.

- [ ] **Step 7: Commit**

Nachricht in `docs/.superpowers/sdd/msg-s1-task1.txt`:

```text
Let the answers carry brain's decisions about the wiki area

A project in brain mode needs a scope, a sources root and a privacy mode
before anything can write the manifest brain reads. [gates.wiki] now holds
them, beside mode and bundle.

WithBrainDefaults fills what the answers leave out with the values brain init
proposes -- project/<directory>, docs or the repository root, the bundle one
level below, manual_cloud -- so a project that meets both tools is told the
same thing by each. It never replaces a recorded answer, and it leaves every
other mode alone: those write no manifest.

vault joins the modes as a valid answer only; what its manifest must say is
not measured yet. A privacy mode outside brain's own three is refused when
the answers are loaded, where the typo was made.
```

Run: `git commit -F docs/.superpowers/sdd/msg-s1-task1.txt`

Expected: Commit-Gate grün.

---

### Task 2: Aus den Antworten wird die `.brain.toml`

**Files:**
- Create: `internal/render/templates/brain.toml.tmpl`
- Modify: `internal/render/render.go` — `view`, `brainView`, `newView`, `brainInclude`, `Render`
- Modify: `internal/render/templates/answers.toml.tmpl` — Tabelle `[gates.wiki]`
- Test: `internal/render/render_test.go`

**Interfaces:**
- Consumes: Task 1 — `answers.Wiki` mit `Scope`, `Sources`, `Privacy`.
- Produces: `Render(a answers.Answers, coverageLane bool)` liefert zusätzlich den Schlüssel `".brain.toml"`, genau dann, wenn `a.Gates.Wiki.Mode == "brain"`. Task 3 verlässt sich auf genau diesen Schlüsselnamen.

- [ ] **Step 1: Die roten Tests schreiben**

In `internal/render/render_test.go` unter `func fixture()` einfügen:

```go
// brainFixture is fixture with a wiki in brain mode and every brain decision
// answered, the shape WithBrainDefaults leaves behind for a docs project.
func brainFixture() answers.Answers {
	a := fixture()
	a.Gates.Wiki = answers.Wiki{Mode: "brain", Bundle: "docs/wiki/",
		Scope: "project/ultraloom", Sources: "docs", Privacy: "manual_cloud"}
	return a
}

// brainManifest is the part of .brain.toml that brain's readers use.
type brainManifest struct {
	Area struct {
		Scope string `toml:"scope"`
		Wiki  bool   `toml:"wiki"`
	} `toml:"area"`
	Layout struct {
		Sources string `toml:"sources"`
		Wiki    string `toml:"wiki"`
	} `toml:"layout"`
	Index struct {
		Include []string `toml:"include"`
	} `toml:"index"`
	Privacy struct {
		Mode string `toml:"mode"`
	} `toml:"privacy"`
}
```

Den Test `TestEveryGeneratedFileSaysWhereItCameFrom` ersetzen durch:

```go
func TestEveryGeneratedFileSaysWhereItCameFrom(t *testing.T) {
	// Both fixtures: only the brain one renders .brain.toml.
	for _, a := range []answers.Answers{fixture(), brainFixture()} {
		files, err := Render(a, true)
		if err != nil {
			t.Fatalf("Render: %v", err)
		}
		for name, body := range files {
			if name == ".ultraloom/answers.toml" || strings.HasSuffix(name, ".md") {
				continue // the source itself and markdown docs do not carry this comment
			}
			if !strings.Contains(body, "generated from .ultraloom/answers.toml") {
				t.Fatalf("%s has no provenance header", name)
			}
		}
	}
}
```

Den Test `TestEveryRenderedFileIsValidToml` ersetzen durch:

```go
// TestEveryRenderedFileIsValidToml is the check the golden files cannot make:
// they only say the output did not change, not that it can be read at all.
func TestEveryRenderedFileIsValidToml(t *testing.T) {
	// Both shapes: the branch that leaves [verify.coverage] out puts a comment
	// block where a section stood, and a stray line there would be a file the
	// generated project cannot read at all. Both fixtures, so .brain.toml is
	// among the files checked.
	for _, a := range []answers.Answers{fixture(), brainFixture()} {
		for _, coverageLane := range []bool{true, false} {
			files, err := Render(a, coverageLane)
			if err != nil {
				t.Fatalf("Render: %v", err)
			}
			for name, body := range files {
				if strings.HasSuffix(name, ".md") {
					continue
				}
				var parsed map[string]any
				if _, err := toml.Decode(body, &parsed); err != nil {
					t.Fatalf("%s is not valid TOML: %v\n%s", name, err, body)
				}
			}
		}
	}
}
```

Und an das Ende von `render_test.go` anhängen:

```go
func TestABrainAnswerRendersTheManifestBrainReads(t *testing.T) {
	files, err := Render(brainFixture(), true)
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	body, ok := files[".brain.toml"]
	if !ok {
		t.Fatal("no .brain.toml was rendered for a brain answer")
	}
	var got brainManifest
	if _, err := toml.Decode(body, &got); err != nil {
		t.Fatalf(".brain.toml is not valid TOML: %v\n%s", err, body)
	}
	if got.Area.Scope != "project/ultraloom" || !got.Area.Wiki {
		t.Fatalf("[area] = %+v, want scope project/ultraloom and wiki = true", got.Area)
	}
	// The bundle is answered with a trailing slash; brain's layout path has none.
	if got.Layout.Sources != "docs" || got.Layout.Wiki != "docs/wiki" {
		t.Fatalf("[layout] = %+v, want sources docs and wiki docs/wiki", got.Layout)
	}
	wantInclude := []string{"docs/*.md", "docs/**/*.md", "README*.md"}
	if !reflect.DeepEqual(got.Index.Include, wantInclude) {
		t.Fatalf("[index] include = %v, want %v", got.Index.Include, wantInclude)
	}
	if got.Privacy.Mode != "manual_cloud" {
		t.Fatalf("[privacy] mode = %q, want manual_cloud", got.Privacy.Mode)
	}
	// No [maintenance]: nothing installs the merge hook it would promise.
	if strings.Contains(body, "[maintenance]") {
		t.Fatalf(".brain.toml promises a maintenance hook nothing installs:\n%s", body)
	}
}

func TestAnAreaWithoutDocsIndexesEveryMarkdownFile(t *testing.T) {
	a := brainFixture()
	a.Gates.Wiki.Sources, a.Gates.Wiki.Bundle = ".", "wiki/"
	files, err := Render(a, true)
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	var got brainManifest
	if _, err := toml.Decode(files[".brain.toml"], &got); err != nil {
		t.Fatalf(".brain.toml is not valid TOML: %v", err)
	}
	if got.Layout.Wiki != "wiki" || !reflect.DeepEqual(got.Index.Include, []string{"**/*.md"}) {
		t.Fatalf("layout wiki %q, include %v; want wiki and [**/*.md]", got.Layout.Wiki, got.Index.Include)
	}
}

func TestOnlyTheBrainModeRendersAManifest(t *testing.T) {
	for _, mode := range []string{"none", "neighbour_repo", "vault"} {
		a := fixture()
		a.Gates.Wiki.Mode = mode
		files, err := Render(a, true)
		if err != nil {
			t.Fatalf("Render: %v", err)
		}
		if _, ok := files[".brain.toml"]; ok {
			t.Fatalf("mode %s rendered a .brain.toml", mode)
		}
	}
}

func TestTheBrainDecisionsReadBackFromTheAnswers(t *testing.T) {
	want := brainFixture()
	files, err := Render(want, true)
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	back, err := answers.Load([]byte(files[".ultraloom/answers.toml"]))
	if err != nil {
		t.Fatalf("the rendered answers do not load: %v", err)
	}
	if back.Gates.Wiki != want.Gates.Wiki {
		t.Fatalf("wiki = %+v, want %+v", back.Gates.Wiki, want.Gates.Wiki)
	}
}
```

- [ ] **Step 2: Rot sehen**

Run: `go test ./internal/render/`

Expected: FAIL. `TestABrainAnswerRendersTheManifestBrainReads` mit „no .brain.toml was rendered for a brain answer", `TestAnAreaWithoutDocsIndexesEveryMarkdownFile` mit einem Dekodierfehler oder leeren Werten, `TestTheBrainDecisionsReadBackFromTheAnswers` mit fehlendem `Scope`, `Sources` und `Privacy`. `TestOnlyTheBrainModeRendersAManifest` ist schon grün.

- [ ] **Step 3: Die Vorlage anlegen**

`internal/render/templates/brain.toml.tmpl` mit genau diesem Inhalt anlegen:

```text
# generated from .ultraloom/answers.toml -- edit that and re-run init
# brain reads this file to know the area; every value comes from [gates.wiki].
[area]
scope = {{ quote .Answers.Gates.Wiki.Scope }}
wiki  = true

[layout]
sources = {{ quote .Answers.Gates.Wiki.Sources }}
wiki    = {{ quote .Brain.Wiki }}

[index]
include = {{ list .Brain.Include }}

[privacy]
mode = {{ quote .Answers.Gates.Wiki.Privacy }}
```

- [ ] **Step 4: `render.go` erweitern**

In `internal/render/render.go` im Typ `view` nach dem Feld `CoverageLane bool` einfügen:

```go
	// Brain is what .brain.toml needs beyond the answers themselves, worked
	// out here so the template stays a list of keys. It is zero for every
	// mode but brain, which is also the only mode that renders the file.
	Brain brainView
```

Unter dem Typ `view` einfügen:

```go
type brainView struct {
	// Wiki is the bundle as brain's layout names it: without the trailing
	// slash the answers carry.
	Wiki    string
	Include []string
}

// brainInclude is the index glob list for a sources root.
//
// For docs, `docs/*.md` stands beside `docs/**/*.md` on purpose. brain's Go
// indexer compiles `docs/**/*.md` into a pattern that requires a directory
// below docs, and its Python indexer does not, so the two binaries index
// different files: measured on 2026-09-10 in ultraloom, 68 entries against 72,
// the four missing ones being the Markdown files directly under docs. With
// both globs the two agree. For any other root brain init writes `**/*.md`,
// which both indexers read alike.
func brainInclude(sources string) []string {
	if sources == "docs" {
		return []string{"docs/*.md", "docs/**/*.md", "README*.md"}
	}
	return []string{"**/*.md"}
}
```

In `newView` direkt vor `return data` einfügen:

```go
	if a.Gates.Wiki.Mode == "brain" {
		data.Brain = brainView{
			Wiki:    strings.TrimSuffix(a.Gates.Wiki.Bundle, "/"),
			Include: brainInclude(a.Gates.Wiki.Sources),
		}
	}
```

In `Render` direkt nach dem Block `if has(a.Project.Agents, "gemini") { … }` einfügen:

```go
	// No [maintenance] table in it: brain init writes `on_merge = true`, which
	// promises a merge hook that nothing installs (brain init's own install_hook
	// is never used), and brain's two readers even disagree on the branch key
	// -- `merge_branch` in what brain init writes, `branch` in what
	// read_manifest reads.
	if a.Gates.Wiki.Mode == "brain" {
		targetsList = append(targetsList, fileTarget{"brain.toml.tmpl", ".brain.toml"})
	}
```

- [ ] **Step 5: Die Antwortvorlage erweitern**

In `internal/render/templates/answers.toml.tmpl` ersetzen:

```text
[gates.wiki]
mode   = {{ quote .Answers.Gates.Wiki.Mode }}
bundle = {{ quote .Answers.Gates.Wiki.Bundle }}
```

durch:

```text
[gates.wiki]
mode   = {{ quote .Answers.Gates.Wiki.Mode }}
bundle = {{ quote .Answers.Gates.Wiki.Bundle }}
{{ if .Answers.Gates.Wiki.Scope }}scope   = {{ quote .Answers.Gates.Wiki.Scope }}
{{ end }}{{ if .Answers.Gates.Wiki.Sources }}sources = {{ quote .Answers.Gates.Wiki.Sources }}
{{ end }}{{ if .Answers.Gates.Wiki.Privacy }}privacy = {{ quote .Answers.Gates.Wiki.Privacy }}
{{ end }}
```

Die Zeile danach bleibt die Leerzeile vor `# An empty list is an answer …`. Die Ausrichtung ist gewollt: alle fünf Gleichheitszeichen stehen in Spalte 8, und `mode   = "…"` bleibt Zeichen für Zeichen, wie `cmd/init/run_test.go` es wörtlich erwartet. Für einen Modus ohne diese drei Werte entsteht dieselbe Datei wie bisher.

- [ ] **Step 6: Grün sehen, mit Deckung**

Run: `go test ./internal/render/ -cover`

Expected: `ok`, Deckung nicht unter dem Wert vor dem Task. `TestRenderMatchesTheGoldenFiles` läuft unverändert mit — die einzige Golden-Datei ist `unenforced_.ultraloom_config.toml`, und `fixture()` hat den Modus `none`.

- [ ] **Step 7: Stagen und den Index lesen**

Run: `git add internal/render/render.go internal/render/render_test.go internal/render/templates/brain.toml.tmpl internal/render/templates/answers.toml.tmpl`

Dann: `git diff --cached --stat` — Expected: genau diese vier Dateien.

- [ ] **Step 8: Commit**

Nachricht in `docs/.superpowers/sdd/msg-s1-task2.txt`:

```text
Render the manifest brain reads from the answers

A brain answer now renders .brain.toml beside the other generated files,
with the provenance header they all carry. It says what brain's readers use:
[area] scope and wiki = true, [layout] sources and wiki, [index] include,
[privacy] mode.

The include list for a docs root carries docs/*.md beside docs/**/*.md.
brain's Go indexer reads the second as requiring a directory below docs and
its Python indexer does not; measured on 2026-09-10, the two indexed 68 and
72 files of this repository. With both globs they agree.

No [maintenance] table: brain init writes on_merge = true for a merge hook
nothing installs, and brain's own readers disagree on the branch key.

[gates.wiki] in answers.toml writes the three new keys only when they carry a
value, aligned so that `mode   = ` stays as it was.
```

Run: `git commit -F docs/.superpowers/sdd/msg-s1-task2.txt`

Expected: Commit-Gate grün.

---

### Task 3: `ulinit` füllt die Vorgaben und schreibt kein zweites Manifest

**Files:**
- Modify: `cmd/init/run.go` — `run`, neu `projectName`, `isDir`, Konstanten `brainManifestPath`, `ultraBrainConfigPath`
- Test: `cmd/init/run_test.go`
- Modify: `docs/hooks.md`, `docs/hooks.de.md` — Abschnitt „Configuration & Sources of Truth" / „Konfiguration", Punkt 1
- Modify: `docs/.superpowers/specs/2026-09-10-wiki-flottenstandard-design.md` — Stufentabelle, Zeile 1
- Modify: `OFFENE_AUFGABEN.md` — Matrixzeile „Wiki-Flottenstandard"

**Interfaces:**
- Consumes: Task 1 — `func (w answers.Wiki) WithBrainDefaults(projectName string, hasDocs bool) answers.Wiki`. Task 2 — `Render` liefert `".brain.toml"` für den Modus `brain`.
- Produces: keine neuen Schnittstellen nach außen. Im Bericht eines Laufs steht die Notiz `.ultra-brain/config.toml already declares this area: no .brain.toml was written`, wenn sie greift.

- [ ] **Step 1: Die roten Tests schreiben**

An das Ende von `cmd/init/run_test.go` anhängen:

```go
// A project that answers brain and carries no manifest gets the one brain
// reads, built from its answers and the defaults brain init would propose.
func TestABrainProjectGetsItsManifest(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "docs/wiki/index.md", "---\nokf_version: 1\n---\n")
	o := Options{Root: root, Yes: true, CommitLanguage: "en", DocsLanguage: "de",
		Look: notOnPath, Getenv: noEnv}
	mustRun(t, o)
	body := read(t, root, ".brain.toml")
	for _, want := range []string{
		"scope = \"project/" + filepath.Base(root) + "\"",
		"wiki  = true",
		"sources = \"docs\"",
		"wiki    = \"docs/wiki\"",
		"include = [\"docs/*.md\", \"docs/**/*.md\", \"README*.md\"]",
		"mode = \"manual_cloud\"",
	} {
		if !strings.Contains(body, want) {
			t.Fatalf(".brain.toml lacks %q:\n%s", want, body)
		}
	}
}

// brain reads .ultra-brain/config.toml first and never looks at .brain.toml
// beside it, so a second manifest there would be a file nothing reads.
func TestAnUltraBrainConfigKeepsTheManifestOut(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, ".ultra-brain/config.toml", "[area]\nscope = \"project/x\"\nwiki = true\n")
	makeFile(t, root, "docs/wiki/index.md", "# Katalog\n")
	o := Options{Root: root, Yes: true, CommitLanguage: "en", DocsLanguage: "de",
		Look: notOnPath, Getenv: noEnv}
	report := mustRun(t, o)
	if _, err := os.Stat(filepath.Join(root, ".brain.toml")); !os.IsNotExist(err) {
		t.Fatalf(".brain.toml was written beside .ultra-brain/config.toml (stat: %v)", err)
	}
	if !strings.Contains(report, ".ultra-brain/config.toml already declares this area") {
		t.Fatalf("the report does not say why no manifest was written:\n%s", report)
	}
}

func TestAProjectWithoutAWikiGetsNoManifest(t *testing.T) {
	root := t.TempDir()
	mustRun(t, answered(root))
	if _, err := os.Stat(filepath.Join(root, ".brain.toml")); !os.IsNotExist(err) {
		t.Fatalf("a project answering mode none got a .brain.toml (stat: %v)", err)
	}
}
```

- [ ] **Step 2: Rot sehen**

Run: `go test ./cmd/init/ -run "BrainProjectGetsItsManifest|UltraBrainConfigKeepsTheManifestOut|WithoutAWikiGetsNoManifest" -v`

Expected: FAIL in `TestABrainProjectGetsItsManifest` (`.brain.toml` fehlt oder trägt leere Werte, weil die Vorgaben noch nicht gefüllt werden) und in `TestAnUltraBrainConfigKeepsTheManifestOut` (die Datei entsteht, und die Notiz fehlt). `TestAProjectWithoutAWikiGetsNoManifest` ist schon grün.

- [ ] **Step 3: `run.go` erweitern**

In `cmd/init/run.go` unter der Konstante `mcpPath` einfügen:

```go
// brainManifestPath is the manifest ulinit writes for a brain area, and
// ultraBrainConfigPath the one brain itself looks for first. brain reads the
// first of the two that exists and never both.
const (
	brainManifestPath    = ".brain.toml"
	ultraBrainConfigPath = ".ultra-brain/config.toml"
)
```

In `run` direkt vor der Zeile `enforced := coverage.Enforced(` einfügen:

```go
	// The brain decisions a recorded answers.toml does not hold yet -- every
	// project answered before these keys existed -- come from brain init's own
	// defaults, so the manifest rendered below is never written with empty
	// values. A recorded answer stays as it is.
	filled.Gates.Wiki = filled.Gates.Wiki.WithBrainDefaults(
		projectName(opts.Root), isDir(opts.Root, "docs"))
```

In `run` direkt nach der Zeile `notes = append(notes, coverageNote(filled, enforced)...)` einfügen:

```go
	// A project that already carries .ultra-brain/config.toml is declared, and
	// brain would never read a .brain.toml beside it. An existing .brain.toml
	// needs no such care: like every existing file it is skipped when the plan
	// is prepared.
	if _, rendered := files[brainManifestPath]; rendered && readOr(opts.Root, ultraBrainConfigPath) != nil {
		delete(files, brainManifestPath)
		notes = append(notes, ultraBrainConfigPath+" already declares this area: no "+
			brainManifestPath+" was written")
	}
```

Und unter der Funktion `readOr` einfügen:

```go
// projectName is the directory name brain init takes an area's scope from.
//
// Abs fails only when the working directory itself cannot be read, which no
// test can arrange from inside the process; the branch is uncovered for that
// reason and handled anyway, the same as in gather.
func projectName(root string) string {
	absolute, err := filepath.Abs(root)
	if err != nil {
		return filepath.Base(root)
	}
	return filepath.Base(absolute)
}

// isDir says whether name is a directory below root.
func isDir(root, name string) bool {
	info, err := os.Stat(filepath.Join(root, filepath.FromSlash(name)))
	return err == nil && info.IsDir()
}
```

- [ ] **Step 4: Grün sehen, mit Deckung**

Run: `go test ./cmd/init/ -cover`

Expected: `ok`, Deckung nicht unter 97,8 %. Die bestehenden Tests laufen unverändert mit, darunter `TestAWikiInTheProjectAnswersTheWikiQuestion`, das `mode   = "brain"` wörtlich in der `answers.toml` sucht.

- [ ] **Step 5: Nachweis mit brains eigenem Leser — Probeprojekt anlegen**

Run: `mkdir -p docs/.superpowers/sdd/stufe1-probe/docs/wiki`

Dann: `printf -- '---\nokf_version: 1\n---\n' > docs/.superpowers/sdd/stufe1-probe/docs/wiki/index.md`

Das Verzeichnis liegt unter `docs/.superpowers/sdd/`, das `.gitignore:2` ignoriert.

- [ ] **Step 6: Nachweis — den Installer im Probeprojekt fahren**

Run: `go run ./cmd/init --yes --root docs/.superpowers/sdd/stufe1-probe --commit-language en --docs-language de --agents claude`

Expected: Exit 0, und im Bericht steht unter `created:` die Zeile `.brain.toml`.

- [ ] **Step 7: Nachweis — brains Python-Leser liest die Datei**

Run: `uv run --project "C:/Users/micro/Documents/#GIT/ultra-brain" python -c "from pathlib import Path; from brain.manifest import read_manifest; m = read_manifest(Path('docs/.superpowers/sdd/stufe1-probe/.brain.toml')); print(m.scope, m.wiki, m.layout, m.include, m.privacy_mode)"`

Expected, genau so (eine Warnung von `uv` zu `VIRTUAL_ENV` davor ist bekannt und unbedeutend):

```text
project/stufe1-probe True {'sources': 'docs', 'wiki': 'docs/wiki'} ('docs/*.md', 'docs/**/*.md', 'README*.md') manual_cloud
```

Warum dieser Leser und nicht `brain status`: `brain status` nimmt den Wikipfad über `FindWikiPath`, und das fällt ohne passenden Schlüssel auf ein vorhandenes `docs/wiki` zurück — es zeigte `docs\wiki` auch **ohne** jede `.brain.toml`. `read_manifest` dagegen verlangt `[area] scope` und bricht sonst mit `ManifestError` ab; es beweist, dass brain die Datei versteht.

Weicht die Ausgabe ab oder bricht der Leser ab, **anhalten und melden**.

- [ ] **Step 8: Nachweis — Probeprojekt entfernen**

Run: `rm -rf docs/.superpowers/sdd/stufe1-probe`

- [ ] **Step 9: Die Hook-Seite nachziehen, englisch**

In `docs/hooks.md` ersetzen:

```markdown
   * The two names are brain's own search order: the first file that can be read decides, and the second is then not consulted.
```

durch:

```markdown
   * The two names are brain's own search order: the first file that can be read decides, and the second is then not consulted.
   * `ulinit` writes `.brain.toml` from `[gates.wiki]` in `.ultraloom/answers.toml` when the mode is `brain` and neither file exists yet; a manifest already there is left as it stands.
```

- [ ] **Step 10: Die Hook-Seite nachziehen, deutsch**

In `docs/hooks.de.md` ersetzen:

```markdown
   * Die zwei Namen sind brains eigene Suchreihenfolge: die erste lesbare Datei entscheidet, die zweite wird dann nicht gelesen.
```

durch:

```markdown
   * Die zwei Namen sind brains eigene Suchreihenfolge: die erste lesbare Datei entscheidet, die zweite wird dann nicht gelesen.
   * `ulinit` schreibt `.brain.toml` aus `[gates.wiki]` in `.ultraloom/answers.toml`, wenn der Modus `brain` ist und noch keine der beiden Dateien existiert; ein vorhandenes Manifest bleibt, wie es ist.
```

- [ ] **Step 11: Die Spec nachziehen**

In `docs/.superpowers/specs/2026-09-10-wiki-flottenstandard-design.md` ersetzen:

```markdown
| 1 | Teil 1: `answers.Answers` erweitern, `.brain.toml` generieren, `vault` als vierte Mode | Stufe 0 |
```

durch:

```markdown
| 1 | Teil 1: `answers.Answers` erweitern, `.brain.toml` generieren, `vault` als vierte Mode — `vault` zunächst nur als gültiger Wert, ohne eigenes Manifest. Plan: `docs/.superpowers/plans/2026-09-11-wiki-flottenstandard-stufe-1.md` | Stufe 0 |
```

- [ ] **Step 12: Den Tracker nachziehen**

In `OFFENE_AUFGABEN.md` in der Matrixzeile „Wiki-Flottenstandard" die Zelle für die nächste Aktion ersetzen. Ihr jetziger Text beginnt mit `Stufe 1 planen:` und endet mit `siehe Abschnitt 5 und 6 |`. Neuer Text der Zelle:

```markdown
Stufe 2 planen: die Hookeinträge `brain guard` und `brain wiki-gate` sowie `.agents/hooks.json` als zweiter Schreiber. Stufe 1 (die Antwortdatei trägt `scope`, `sources` und `privacy`, `ulinit` erzeugt daraus `.brain.toml`, `vault` ist ein gültiger Wert) ist nach `docs/.superpowers/plans/2026-09-11-wiki-flottenstandard-stufe-1.md` umgesetzt; Stufe 0 ging am 2026-09-11 als `eb0e5f6`..`7485f63` nach master |
```

Die Statuszelle `🟢 **Stufe 0 gemergt**` in derselben Zeile wird zu `🟡 **Stufe 1 umgesetzt**`.

Wenn eine der beiden Zellen einen anderen Wortlaut hat — eine parallele Sitzung führt diese Datei mit —, die gleiche Absicht an der entsprechenden Stelle umsetzen und das im Bericht sagen.

- [ ] **Step 13: Das volle Gate fahren**

Run: `uv run ultraloom check all`

Expected: Exit 0 — `lint: ok`, `types: ok`, `test: ok`, `coverage: ok`, Go-Coverage mindestens 98,0 %.

- [ ] **Step 14: Stagen und den Index lesen**

Run: `git add cmd/init/run.go cmd/init/run_test.go docs/hooks.md docs/hooks.de.md docs/.superpowers/specs/2026-09-10-wiki-flottenstandard-design.md OFFENE_AUFGABEN.md`

Dann: `git diff --cached --stat` — Expected: genau diese sechs Dateien.

- [ ] **Step 15: Commit**

Nachricht in `docs/.superpowers/sdd/msg-s1-task3.txt`:

```text
Write the brain manifest on init, and never a second one

ulinit now fills the brain decisions a recorded answers.toml does not hold
yet with brain init's own defaults, before rendering, so a project answered
before these keys existed still gets a manifest with values in it.

A project that already carries .ultra-brain/config.toml gets no .brain.toml:
brain reads the first of the two names that exists and never both, so a
second file there would be one nothing reads. The report says so. An
existing .brain.toml is skipped like every existing file.

Proven with brain's own reader, not with brain status: status resolves the
wiki path through FindWikiPath, which falls back to an existing docs/wiki and
showed that path without any manifest at all. read_manifest requires
[area] scope and parsed the manifest written for a throwaway project into
scope, wiki = true, layout, include and privacy as rendered.
```

Run: `git commit -F docs/.superpowers/sdd/msg-s1-task3.txt`

Expected: Commit-Gate grün.

---

## Außerhalb dieses Plans

- **Registry-Eintrag.** `ulinit` erzeugt das Manifest, trägt den Bereich aber nicht in brains `registry.toml` ein. Die Spec weist das keiner Stufe zu; ohne Eintrag kennt die Pflegeschleife den Bereich nicht. Gehört vor den Ausroll-Schritt (Stufe 5) entschieden.
- **`[wiki] path`.** brains `FindWikiPath` (`pkg/wiki/gate.go`, genutzt von `brain status` und `brain wiki-gate`) liest den Wikipfad aus `[wiki] path`, nicht aus `[layout] wiki`, das `pkg/config` und der Python-Leser nehmen. Für `docs/wiki` und `wiki` greift sein Rückfall auf das vorhandene Verzeichnis. Ein Bündel an anderer Stelle fände `wiki-gate` nicht — der dritte Riss innerhalb von brain, Stufe 4.
- **Das `vault`-Manifest.** Siehe „Entscheidungen", Punkt 2.
- **`[relevance] "wiki/**"`.** Der Vorgabe-Glob passt nicht zu `docs/wiki/**`. Kein Code liest `[relevance]` heute; offen, bis ein Leser entsteht.
- **Die gefüllten Werte in bestehenden `answers.toml`.** Werden erst mit `ultraloom sync` geschrieben (Spec-Defekt D5).
