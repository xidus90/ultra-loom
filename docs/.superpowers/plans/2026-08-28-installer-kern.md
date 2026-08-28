# Installer-Kern (P1) — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ultraloom init` als Go-Binary, das einen Projektstack erkennt, die nicht ablesbaren Entscheidungen erfragt und daraus die Erzwingungsausstattung eines Projekts erzeugt.

**Architecture:** Eine reine Erkennungsfunktion liefert Fakten über einen Verzeichnisbaum; ein Interview ergänzt sie zu Antworten in `.ultraloom/answers.toml`; ein Renderer erzeugt daraus per `go:embed`-Vorlagen die Zieldateien im Speicher; ein Schreiber legt sie erst ab, wenn alle fertig sind. `.claude/settings.json` ist die einzige Datei, die zusammengeführt statt übersprungen wird.

**Tech Stack:** Go 1.22+, Standardbibliothek (`text/template`, `embed`, `encoding/json`, `io/fs`, `os/exec`), eine Fremdabhängigkeit: `github.com/BurntSushi/toml` zum Lesen von TOML. Geschrieben wird TOML über Vorlagen, nicht über einen Encoder — die Kommentare in `answers.toml` sind Teil des Produkts.

**Spec:** `docs/.superpowers/specs/2026-08-28-installer-kern-design.md`

## Global Constraints

- **Go 1.22 oder neuer.** Auf dieser Maschine ist Go noch nicht installiert — Task 1 richtet es ein.
- **Modulpfad:** `github.com/xidus90/ultra-loom` (das Remote dieses Repos).
- **Zielplattformen:** windows, darwin, linux, freebsd, openbsd, netbsd — je amd64 und arm64. Cross-Compile muss ohne cgo gelingen (`CGO_ENABLED=0`).
- **Sprache:** Prosa und Dokumentation deutsch, Code, Bezeichner, Kommentare, Commits und Meldungen englisch. Kommentare stehen auf einer anderen Abstraktionsebene als die Zeile darunter.
- **TDD, 100 % Coverage.** Jeder Ausschluss trägt eine Begründung.
- **Keine `interface{}`/`any` ohne Grund**, keine stillen Fehler: jede Funktion, die scheitern kann, gibt `error` zurück.
- **Exit-Codes:** 0 fertig oder nichts zu tun · 1 eigener Fehler, nichts geschrieben · 2 das Projekt sagt nein.
- **Kein Netz außer beim Vendoring** (Task 9), und dort nur `git`.
- **Keine absoluten Maschinenpfade in versionierten Dateien.**

---

## Dateistruktur

| Datei | Verantwortung |
|---|---|
| `go.mod`, `go.sum` | Modul und die eine Abhängigkeit |
| `cmd/init/main.go` | Flags, Exit-Codes, Verdrahtung — sonst nichts |
| `internal/detect/detect.go` | reine Erkennung: `fs.FS` hinein, `Facts` heraus |
| `internal/detect/signals.go` | die Signaltabelle als Daten |
| `internal/answers/answers.go` | `Answers`-Typ, Lesen aus TOML, Vorbelegung aus `Facts` |
| `internal/interview/interview.go` | Fragen, TTY-Erkennung, Flag-Übersteuerung |
| `internal/render/render.go` | Vorlagen rendern, Ergebnis als `map[string]string` |
| `internal/render/templates/` | die eingebetteten Vorlagen |
| `internal/settings/merge.go` | der `settings.json`-Merge samt Eigentümerbegriff |
| `internal/coverage/check.go` | prüft `fail_under`, setzt es nie |
| `internal/vendor/vendor.go` | Klon auf festen Ref, `installed.toml` |
| `internal/brainpath/find.go` | brain suchen: Shim, PATH, `ULTRA_BRAIN_DIR` |
| `internal/write/atomic.go` | erst alles rendern, dann schreiben |

Jede `internal/`-Einheit hat ihre `_test.go` daneben. Nichts unter `internal/` ruft `os.Exit` oder liest Flags — das tut allein `cmd/init/main.go`.

---

### Task 1: Go-Werkzeugkette und die Go-Spur im Gate

Ohne installiertes Go läuft kein Test dieses Plans, und ohne Gate-Spur prüft ultralooms Stop-Gate den Go-Anteil nie.

**Files:**
- Create: `go.mod`
- Create: `cmd/init/main.go`
- Create: `cmd/init/main_test.go`
- Modify: `.ultraloom/config.toml`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nichts
- Produces: `main.version` (Konstante `string`), Binärname `ultraloom-init`

- [ ] **Step 1: Go installieren und prüfen**

```bash
winget install --id GoLang.Go --silent --accept-package-agreements --accept-source-agreements
```

Danach eine neue Shell öffnen und prüfen:

```bash
go version
```

Erwartet: `go version go1.2x.y windows/amd64`. Meldet die Shell weiterhin `command not found`, liegt Go unter `C:\Program Files\Go\bin` — diesen Pfad in die Benutzer-PATH-Variable aufnehmen.

- [ ] **Step 2: Modul anlegen**

```bash
cd "/c/Users/micro/Documents/#GIT/ultraloom" && go mod init github.com/xidus90/ultra-loom
```

- [ ] **Step 3: Den fehlschlagenden Test schreiben**

`cmd/init/main_test.go`:

```go
package main

import "testing"

// The version is the one thing a user can ask for before anything is
// configured, so it is also the first thing that must exist.
func TestVersionIsNotEmpty(t *testing.T) {
	if version == "" {
		t.Fatal("version must not be empty")
	}
}
```

- [ ] **Step 4: Test laufen lassen, Fehlschlag prüfen**

Run: `go test ./cmd/init/`
Expected: FAIL, `undefined: version`

- [ ] **Step 5: Minimale Umsetzung**

`cmd/init/main.go`:

```go
// Command ultraloom-init installs the enforcement of one project.
//
// Everything it decides lives under internal/; this file is only the edge:
// flags in, exit code out. A hook that cannot be tested without a process
// is a hook nobody tests.
package main

import (
	"flag"
	"fmt"
	"os"
)

const version = "0.1.0"

func main() {
	showVersion := flag.Bool("version", false, "print the version and exit")
	flag.Parse()
	if *showVersion {
		fmt.Println(version)
		os.Exit(0)
	}
	fmt.Fprintln(os.Stderr, "not implemented yet")
	os.Exit(1)
}
```

- [ ] **Step 6: Test laufen lassen, Erfolg prüfen**

Run: `go test ./cmd/init/`
Expected: PASS

- [ ] **Step 7: Die Go-Spur ins Gate hängen**

In `.ultraloom/config.toml` den `[verify]`-Block auf die Tabellenform bringen, damit beide Sprachen laufen:

```toml
[verify.lint]
commands = ["uv run ruff check .", "gofmt -l cmd internal", "go vet ./..."]
threaded = true

[verify.test]
commands = ["uv run pytest", "go test ./..."]
threaded = true
```

`gofmt -l` gibt die unformatierten Dateien aus und **beendet mit 0**, auch wenn es welche findet. Deshalb dahinter ein Wrapper-Skript `hooks/gofmt-check.sh`, das die Ausgabe zu einem Exit-Code macht:

```bash
#!/usr/bin/env bash
# gofmt reports by printing names, not by failing. A gate needs the opposite.
set -euo pipefail
unformatted="$(gofmt -l "$@")"
if [ -n "$unformatted" ]; then
  printf 'not gofmt-clean:\n%s\n' "$unformatted" >&2
  exit 1
fi
```

Der Eintrag lautet dann `bash hooks/gofmt-check.sh cmd internal`.

- [ ] **Step 8: Build-Artefakte ignorieren**

An `.gitignore` anhängen:

```
/ultraloom-init
/ultraloom-init.exe
```

- [ ] **Step 9: Gate laufen lassen**

Run: `uv run --project . ultraloom check lint --root . && uv run --project . ultraloom check test --root .`
Expected: beide grün

- [ ] **Step 10: Commit**

```bash
git add go.mod cmd/init/main.go cmd/init/main_test.go .ultraloom/config.toml .gitignore hooks/gofmt-check.sh
git commit -m "Give the repo a second language and a gate that checks it"
```

---

### Task 2: Erkennung — Fakten aus einem Verzeichnisbaum

**Files:**
- Create: `internal/detect/detect.go`
- Create: `internal/detect/signals.go`
- Create: `internal/detect/detect_test.go`

**Interfaces:**
- Consumes: nichts
- Produces:
  - `type Facts struct { Stacks []string; HasGit bool; HooksPath string; WikiMode string; WikiPath string; Ambiguous []string }`
  - `func Detect(root fs.FS) Facts`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`internal/detect/detect_test.go`:

```go
package detect

import (
	"testing"
	"testing/fstest"
)

func TestUvManagedPythonIsDetected(t *testing.T) {
	tree := fstest.MapFS{
		"pyproject.toml": {Data: []byte("[project]\nname = \"x\"\n")},
		"uv.lock":        {Data: []byte("")},
	}
	facts := Detect(tree)
	if !has(facts.Stacks, "python") {
		t.Fatalf("stacks = %v, want python", facts.Stacks)
	}
	if !has(facts.Stacks, "uv") {
		t.Fatalf("stacks = %v, want uv", facts.Stacks)
	}
}

func TestGodotWithDotnetKeepsBothStacks(t *testing.T) {
	tree := fstest.MapFS{
		"project.godot": {Data: []byte("config_version=5\n\n[dotnet]\n\nproject/assembly_name=\"space\"\n")},
		"space.csproj":  {Data: []byte("<Project/>")},
	}
	facts := Detect(tree)
	for _, want := range []string{"godot", "gdscript", "csharp"} {
		if !has(facts.Stacks, want) {
			t.Fatalf("stacks = %v, want %s", facts.Stacks, want)
		}
	}
}

func TestAnEmptyTreeDetectsNothingAndSaysSo(t *testing.T) {
	facts := Detect(fstest.MapFS{})
	if len(facts.Stacks) != 0 {
		t.Fatalf("stacks = %v, want none", facts.Stacks)
	}
}

func has(all []string, one string) bool {
	for _, candidate := range all {
		if candidate == one {
			return true
		}
	}
	return false
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `go test ./internal/detect/`
Expected: FAIL, `undefined: Detect`

- [ ] **Step 3: Signaltabelle als Daten schreiben**

`internal/detect/signals.go`:

```go
package detect

// A signal is a file that means something, plus what it means.
//
// Data rather than a chain of ifs: the table is what a reader of the spec
// compares against, and a new stack is a row instead of a branch.
type signal struct {
	// path is matched literally; glob is matched with path.Match. Exactly
	// one of them is set.
	path  string
	glob  string
	stacks []string
	// contains, when set, must appear in the file for the signal to count.
	// That is what separates a Godot project with C# from one without.
	contains string
}

var signals = []signal{
	{path: "pyproject.toml", stacks: []string{"python"}},
	{path: "uv.lock", stacks: []string{"python", "uv"}},
	{path: "requirements.txt", stacks: []string{"python"}},
	{path: "manage.py", stacks: []string{"python", "django"}},
	{path: "project.godot", stacks: []string{"godot", "gdscript"}},
	{path: "project.godot", stacks: []string{"csharp"}, contains: "[dotnet]"},
	{glob: "*.csproj", stacks: []string{"csharp"}},
	{glob: "*.sln", stacks: []string{"csharp"}},
	{path: "tsconfig.json", stacks: []string{"typescript"}},
	{path: "package.json", stacks: []string{"node"}},
	{path: "Cargo.toml", stacks: []string{"rust"}},
	{path: "go.mod", stacks: []string{"go"}},
}
```

- [ ] **Step 4: Erkennung schreiben**

`internal/detect/detect.go`:

```go
// Package detect answers what a project is, and nothing else.
//
// It takes an fs.FS rather than a path so the tests need no directories on
// disk, and it writes nothing: every decision that follows from these facts
// is made elsewhere. `--dry-run` is free because of that.
package detect

import (
	"io/fs"
	"path"
	"sort"
	"strings"
)

// Facts is what a tree says about itself.
type Facts struct {
	Stacks    []string
	HasGit    bool
	HooksPath string
	WikiMode  string
	WikiPath  string
	// Ambiguous carries findings that must not be decided here -- two
	// stacks that rarely coexist, a package.json that may be tooling only.
	// The interview resolves them.
	Ambiguous []string
}

// Detect reads the root and one level below it, for workspaces.
func Detect(root fs.FS) Facts {
	found := map[string]bool{}
	for _, sig := range signals {
		if matches(root, sig) {
			for _, stack := range sig.stacks {
				found[stack] = true
			}
		}
	}
	facts := Facts{Stacks: sorted(found)}
	if _, err := fs.Stat(root, ".git"); err == nil {
		facts.HasGit = true
	}
	if entries, err := fs.ReadDir(root, "wiki"); err == nil && len(entries) > 0 {
		facts.WikiMode, facts.WikiPath = "brain", "wiki/"
	}
	return facts
}

func matches(root fs.FS, sig signal) bool {
	names := candidates(root, sig)
	for _, name := range names {
		if sig.contains == "" {
			return true
		}
		body, err := fs.ReadFile(root, name)
		if err == nil && strings.Contains(string(body), sig.contains) {
			return true
		}
	}
	return false
}

func candidates(root fs.FS, sig signal) []string {
	if sig.path != "" {
		if _, err := fs.Stat(root, sig.path); err == nil {
			return []string{sig.path}
		}
		return nil
	}
	entries, err := fs.ReadDir(root, ".")
	if err != nil {
		return nil
	}
	var hits []string
	for _, entry := range entries {
		if ok, _ := path.Match(sig.glob, entry.Name()); ok {
			hits = append(hits, entry.Name())
		}
	}
	return hits
}

func sorted(set map[string]bool) []string {
	var all []string
	for key := range set {
		all = append(all, key)
	}
	sort.Strings(all)
	return all
}
```

- [ ] **Step 5: Test laufen lassen, Erfolg prüfen**

Run: `go test ./internal/detect/ -v`
Expected: alle drei PASS

- [ ] **Step 6: Gegen die echten Repos prüfen**

Ein kurzer Handlauf, der beweist, dass die Tabelle auf echte Bäume passt — kein Test, sondern eine Messung:

```bash
cd "/c/Users/micro/Documents/#GIT/ultraloom" && go run ./cmd/init --detect-only --root "C:/Users/micro/Documents/#GIT/space"
```

Das `--detect-only`-Flag existiert dafür in `main.go` (drei Zeilen: `Detect(os.DirFS(root))`, JSON ausgeben, Exit 0). Erwartet für space: `godot`, `gdscript`, `csharp`, `python`, `uv`.

- [ ] **Step 7: Commit**

```bash
git add internal/detect/ cmd/init/main.go
git commit -m "Ask a tree what it is, without writing anything"
```

---

### Task 3: Antworten lesen und aus Fakten vorbelegen

**Files:**
- Create: `internal/answers/answers.go`
- Create: `internal/answers/answers_test.go`

**Interfaces:**
- Consumes: `detect.Facts` aus Task 2
- Produces:
  - `type Answers struct { Project Project; Gates Gates; Policy Policy; Relevance map[string][]string }`
  - `type Project struct { Stacks []string; DocsLanguage string; CommitLanguage string }`
  - `type Gates struct { CoverageThreshold int; TestsInStop bool; TypesInStop bool; Wiki Wiki }`
  - `type Wiki struct { Mode string; Bundle string }`
  - `type Policy struct { ProtectedPaths []string; ForbiddenCommands []string }`
  - `func Defaults(facts detect.Facts) Answers`
  - `func Load(data []byte) (Answers, error)`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`internal/answers/answers_test.go`:

```go
package answers

import (
	"testing"

	"github.com/xidus90/ultra-loom/internal/detect"
)

func TestDefaultsCarryTheDetectedStacks(t *testing.T) {
	got := Defaults(detect.Facts{Stacks: []string{"python", "uv"}})
	if len(got.Project.Stacks) != 2 {
		t.Fatalf("stacks = %v, want the two detected", got.Project.Stacks)
	}
	if got.Gates.CoverageThreshold != 100 {
		t.Fatalf("threshold = %d, want 100", got.Gates.CoverageThreshold)
	}
}

func TestLoadReadsTheDocumentedShape(t *testing.T) {
	got, err := Load([]byte(`
[project]
stacks          = ["godot"]
commit_language = "en"

[gates]
coverage_threshold = 90

[gates.wiki]
mode = "neighbour_repo"
`))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got.Project.CommitLanguage != "en" {
		t.Fatalf("commit language = %q", got.Project.CommitLanguage)
	}
	if got.Gates.Wiki.Mode != "neighbour_repo" {
		t.Fatalf("wiki mode = %q", got.Gates.Wiki.Mode)
	}
}

func TestLoadRefusesAnUnknownWikiMode(t *testing.T) {
	_, err := Load([]byte("[gates.wiki]\nmode = \"telepathy\"\n"))
	if err == nil {
		t.Fatal("want an error naming the valid modes")
	}
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `go test ./internal/answers/`
Expected: FAIL, `undefined: Defaults`

- [ ] **Step 3: Abhängigkeit holen**

```bash
go get github.com/BurntSushi/toml@latest
```

- [ ] **Step 4: Umsetzung schreiben**

`internal/answers/answers.go`:

```go
// Package answers holds the decisions of one project.
//
// Decisions, not output: everything else this tool writes is derived from
// this type. Changing a generated file is therefore always the wrong move,
// and the header of every generated file says so.
package answers

import (
	"fmt"

	"github.com/BurntSushi/toml"
	"github.com/xidus90/ultra-loom/internal/detect"
)

type Project struct {
	Stacks         []string `toml:"stacks"`
	DocsLanguage   string   `toml:"docs_language"`
	CommitLanguage string   `toml:"commit_language"`
}

type Wiki struct {
	Mode   string `toml:"mode"`
	Bundle string `toml:"bundle"`
}

type Gates struct {
	CoverageThreshold int  `toml:"coverage_threshold"`
	TestsInStop       bool `toml:"tests_in_stop"`
	TypesInStop       bool `toml:"types_in_stop"`
	Wiki              Wiki `toml:"wiki"`
}

type Policy struct {
	ProtectedPaths    []string `toml:"protected_paths"`
	ForbiddenCommands []string `toml:"forbidden_commands"`
}

type Answers struct {
	Project   Project             `toml:"project"`
	Gates     Gates               `toml:"gates"`
	Policy    Policy              `toml:"policy"`
	Relevance map[string][]string `toml:"relevance"`
}

// WikiModes is the whole set. A mode outside it is a typo, and a typo that
// silently disables the wiki gate is the expensive kind.
var WikiModes = []string{"brain", "neighbour_repo", "none"}

// Defaults is what the interview starts from: the facts, plus the
// conventions of this repo for everything a tree cannot say.
func Defaults(facts detect.Facts) Answers {
	return Answers{
		Project: Project{
			Stacks:         facts.Stacks,
			DocsLanguage:   "de",
			CommitLanguage: "en",
		},
		Gates: Gates{
			CoverageThreshold: 100,
			TestsInStop:       true,
			TypesInStop:       true,
			Wiki:              Wiki{Mode: modeOr(facts.WikiMode, "none"), Bundle: facts.WikiPath},
		},
		Relevance: map[string][]string{"*.md": {}},
	}
}

func Load(data []byte) (Answers, error) {
	var loaded Answers
	if _, err := toml.Decode(string(data), &loaded); err != nil {
		return Answers{}, fmt.Errorf("answers.toml: %w", err)
	}
	if loaded.Gates.Wiki.Mode != "" && !valid(loaded.Gates.Wiki.Mode) {
		return Answers{}, fmt.Errorf(
			"answers.toml: [gates.wiki].mode is %q, must be one of %v",
			loaded.Gates.Wiki.Mode, WikiModes)
	}
	return loaded, nil
}

func valid(mode string) bool {
	for _, known := range WikiModes {
		if known == mode {
			return true
		}
	}
	return false
}

func modeOr(detected, fallback string) string {
	if detected == "" {
		return fallback
	}
	return detected
}
```

- [ ] **Step 5: Test laufen lassen, Erfolg prüfen**

Run: `go test ./internal/answers/ -v`
Expected: alle drei PASS

- [ ] **Step 6: Commit**

```bash
git add go.mod go.sum internal/answers/
git commit -m "Separate the decisions of a project from their output"
```

---

### Task 4: Interview, Flags und das Verhalten ohne TTY

**Files:**
- Create: `internal/interview/interview.go`
- Create: `internal/interview/interview_test.go`

**Interfaces:**
- Consumes: `answers.Answers`, `answers.Defaults` aus Task 3
- Produces:
  - `type Question struct { Key string; Prompt string; Default string; Flag string }`
  - `func Missing(current answers.Answers) []Question`
  - `func Run(in io.Reader, out io.Writer, interactive bool, current answers.Answers) (answers.Answers, error)`
  - `var ErrNoTTY = errors.New("...")`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`internal/interview/interview_test.go`:

```go
package interview

import (
	"bytes"
	"errors"
	"strings"
	"testing"

	"github.com/xidus90/ultra-loom/internal/answers"
)

func TestWithoutATtyItRefusesInsteadOfPrompting(t *testing.T) {
	incomplete := answers.Answers{}
	_, err := Run(strings.NewReader(""), &bytes.Buffer{}, false, incomplete)
	if !errors.Is(err, ErrNoTTY) {
		t.Fatalf("err = %v, want ErrNoTTY", err)
	}
}

func TestTheRefusalNamesTheFlagThatWouldAnswer(t *testing.T) {
	var out bytes.Buffer
	_, err := Run(strings.NewReader(""), &out, false, answers.Answers{})
	if err == nil {
		t.Fatal("want an error")
	}
	if !strings.Contains(err.Error(), "--commit-language") {
		t.Fatalf("error = %q, want it to name the flag", err.Error())
	}
}

func TestEnterTakesTheDefault(t *testing.T) {
	start := answers.Answers{}
	start.Gates.CoverageThreshold = 100
	start.Project.DocsLanguage = "de"
	got, err := Run(strings.NewReader("\n"), &bytes.Buffer{}, true, start)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if got.Project.CommitLanguage != "en" {
		t.Fatalf("commit language = %q, want the default en", got.Project.CommitLanguage)
	}
}

func TestNothingIsAskedWhenEverythingIsAnswered(t *testing.T) {
	complete := answers.Answers{}
	complete.Project.CommitLanguage = "en"
	complete.Project.DocsLanguage = "de"
	complete.Gates.CoverageThreshold = 100
	complete.Gates.Wiki.Mode = "none"
	if got := Missing(complete); len(got) != 0 {
		t.Fatalf("missing = %v, want none", got)
	}
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `go test ./internal/interview/`
Expected: FAIL, `undefined: Run`

- [ ] **Step 3: Umsetzung schreiben**

`internal/interview/interview.go`:

```go
// Package interview fills the gaps a tree cannot fill.
//
// It never prompts into the dark. init is called by agents as well as by
// people, and there stdin is closed -- a prompt nobody sees would hang the
// caller and look like the tool doing nothing. The same lesson as the
// invisible uv failure in space's run.sh.
package interview

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"strings"

	"github.com/xidus90/ultra-loom/internal/answers"
)

var ErrNoTTY = errors.New("no terminal to ask on")

type Question struct {
	Key     string
	Prompt  string
	Default string
	Flag    string
	apply   func(*answers.Answers, string)
}

// Missing is the interview as data: what is still unanswered, in the order
// it will be asked.
func Missing(current answers.Answers) []Question {
	var open []Question
	if current.Project.CommitLanguage == "" {
		open = append(open, Question{
			Key: "commit_language", Prompt: "Language for commit messages",
			Default: "en", Flag: "--commit-language",
			apply: func(a *answers.Answers, v string) { a.Project.CommitLanguage = v },
		})
	}
	if current.Project.DocsLanguage == "" {
		open = append(open, Question{
			Key: "docs_language", Prompt: "Language for prose and documentation",
			Default: "de", Flag: "--docs-language",
			apply: func(a *answers.Answers, v string) { a.Project.DocsLanguage = v },
		})
	}
	if current.Gates.Wiki.Mode == "" {
		open = append(open, Question{
			Key: "wiki_mode", Prompt: fmt.Sprintf("Wiki mode %v", answers.WikiModes),
			Default: "none", Flag: "--wiki-mode",
			apply: func(a *answers.Answers, v string) { a.Gates.Wiki.Mode = v },
		})
	}
	return open
}

func Run(in io.Reader, out io.Writer, interactive bool, current answers.Answers) (answers.Answers, error) {
	open := Missing(current)
	if len(open) == 0 {
		return current, nil
	}
	if !interactive {
		var flags []string
		for _, question := range open {
			flags = append(flags, question.Flag)
		}
		return answers.Answers{}, fmt.Errorf(
			"%w: unanswered, pass %s", ErrNoTTY, strings.Join(flags, " "))
	}
	reader := bufio.NewReader(in)
	for _, question := range open {
		fmt.Fprintf(out, "%s [%s]: ", question.Prompt, question.Default)
		line, err := reader.ReadString('\n')
		if err != nil && line == "" {
			return answers.Answers{}, fmt.Errorf("reading the answer to %s: %w", question.Key, err)
		}
		given := strings.TrimSpace(line)
		if given == "" {
			given = question.Default
		}
		question.apply(&current, given)
	}
	return current, nil
}
```

- [ ] **Step 4: Test laufen lassen, Erfolg prüfen**

Run: `go test ./internal/interview/ -v`
Expected: alle vier PASS

- [ ] **Step 5: Commit**

```bash
git add internal/interview/
git commit -m "Ask only what the project cannot answer, and never into the dark"
```

---

### Task 5: Rendern über eingebettete Vorlagen

**Files:**
- Create: `internal/render/render.go`
- Create: `internal/render/templates/answers.toml.tmpl`
- Create: `internal/render/templates/policy.toml.tmpl`
- Create: `internal/render/templates/config.toml.tmpl`
- Create: `internal/render/render_test.go`
- Create: `internal/render/testdata/golden/` (vier Dateien, in Step 4 erzeugt)

**Interfaces:**
- Consumes: `answers.Answers` aus Task 3
- Produces: `func Render(a answers.Answers) (map[string]string, error)` — Schlüssel sind projektrelative Pfade

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`internal/render/render_test.go`:

```go
package render

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xidus90/ultra-loom/internal/answers"
)

func fixture() answers.Answers {
	a := answers.Answers{}
	a.Project = answers.Project{
		Stacks: []string{"python", "uv"}, DocsLanguage: "de", CommitLanguage: "en"}
	a.Gates = answers.Gates{CoverageThreshold: 100, TestsInStop: true, TypesInStop: true}
	a.Gates.Wiki = answers.Wiki{Mode: "none"}
	a.Policy = answers.Policy{ForbiddenCommands: []string{"git push"}}
	a.Relevance = map[string][]string{"*.md": {}, "*.py": {"lint", "types"}}
	return a
}

func TestEveryGeneratedFileSaysWhereItCameFrom(t *testing.T) {
	files, err := Render(fixture())
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	for name, body := range files {
		if name == ".ultraloom/answers.toml" {
			continue // the source itself does not point at itself
		}
		if !strings.Contains(body, "generated from .ultraloom/answers.toml") {
			t.Fatalf("%s has no provenance header", name)
		}
	}
}

func TestRenderMatchesTheGoldenFiles(t *testing.T) {
	files, err := Render(fixture())
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	for name, body := range files {
		golden := filepath.Join("testdata", "golden", strings.ReplaceAll(name, "/", "_"))
		want, err := os.ReadFile(golden)
		if err != nil {
			t.Fatalf("reading %s: %v -- run with -update to create it", golden, err)
		}
		if body != string(want) {
			t.Fatalf("%s differs from %s", name, golden)
		}
	}
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `go test ./internal/render/`
Expected: FAIL, `undefined: Render`

- [ ] **Step 3: Vorlagen und Renderer schreiben**

`internal/render/templates/answers.toml.tmpl`:

```
# .ultraloom/answers.toml -- written by `ultraloom init`, safe to edit by hand.
# Everything else under .ultraloom/ is generated from this file.
[project]
stacks          = [{{ range $i, $s := .Project.Stacks }}{{ if $i }}, {{ end }}"{{ $s }}"{{ end }}]
docs_language   = "{{ .Project.DocsLanguage }}"
commit_language = "{{ .Project.CommitLanguage }}"

[gates]
coverage_threshold = {{ .Gates.CoverageThreshold }}   # reported only; enforced by the tool's own fail_under
tests_in_stop      = {{ .Gates.TestsInStop }}
types_in_stop      = {{ .Gates.TypesInStop }}

[gates.wiki]
mode   = "{{ .Gates.Wiki.Mode }}"
bundle = "{{ .Gates.Wiki.Bundle }}"
```

`internal/render/templates/policy.toml.tmpl`:

```
# generated from .ultraloom/answers.toml -- edit that and re-run init
{{ range .Policy.ProtectedPaths }}[[policy.paths.rules]]
match  = "{{ . }}"
reason = "this file is written by a tool, not by hand"

{{ end }}{{ range .Policy.ForbiddenCommands }}[[policy.commands.rules]]
match  = "{{ . }}"
reason = "forbidden by this project's answers.toml"

{{ end }}
```

`internal/render/render.go`:

```go
// Package render turns decisions into files, in memory.
//
// Nothing here touches the disk. Writing is a separate step so a failure in
// the third template cannot leave a project half configured -- see
// internal/write.
package render

import (
	"embed"
	"fmt"
	"strings"
	"text/template"

	"github.com/xidus90/ultra-loom/internal/answers"
)

//go:embed templates/*.tmpl
var templates embed.FS

// targets maps a template to the path it lands on in the project.
var targets = map[string]string{
	"answers.toml.tmpl": ".ultraloom/answers.toml",
	"policy.toml.tmpl":  ".ultraloom/policy.toml",
	"config.toml.tmpl":  ".ultraloom/config.toml",
}

func Render(a answers.Answers) (map[string]string, error) {
	out := make(map[string]string, len(targets))
	for name, target := range targets {
		body, err := one(name, a)
		if err != nil {
			return nil, fmt.Errorf("rendering %s: %w", name, err)
		}
		out[target] = body
	}
	return out, nil
}

func one(name string, a answers.Answers) (string, error) {
	parsed, err := template.ParseFS(templates, "templates/"+name)
	if err != nil {
		return "", err
	}
	var buffer strings.Builder
	if err := parsed.Execute(&buffer, a); err != nil {
		return "", err
	}
	return buffer.String(), nil
}
```

`config.toml.tmpl` folgt demselben Muster und rendert `[verify]`, `[verify.profiles]` und die Relevanzabbildung.

- [ ] **Step 4: Golden Files erzeugen und lesen**

```bash
mkdir -p internal/render/testdata/golden && go run ./internal/render/cmd/gen
```

Existiert `cmd/gen` nicht, die Dateien einmal von Hand aus der Testausgabe erzeugen — **und dann lesen**. Ein Golden File, das niemand gelesen hat, friert einen Fehler ein statt ihn zu fangen.

- [ ] **Step 5: Test laufen lassen, Erfolg prüfen**

Run: `go test ./internal/render/ -v`
Expected: beide PASS

- [ ] **Step 6: Commit**

```bash
git add internal/render/
git commit -m "Turn decisions into files without touching the disk"
```

---

### Task 6: Der settings.json-Merge

**Files:**
- Create: `internal/settings/merge.go`
- Create: `internal/settings/merge_test.go`

**Interfaces:**
- Consumes: nichts aus früheren Tasks
- Produces:
  - `type Entry struct { Event string; Matcher string; Command string; Timeout int }`
  - `type Result struct { Merged []byte; Skipped []string }`
  - `func Merge(existing []byte, wanted []Entry) (Result, error)`
  - Konstante `OwnerKey = "ultraloomOwned"`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`internal/settings/merge_test.go`:

```go
package settings

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestAMissingEventIsAdded(t *testing.T) {
	got, err := Merge([]byte(`{}`), []Entry{{Event: "PreToolUse", Matcher: "Write", Command: "guard"}})
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if !strings.Contains(string(got.Merged), "PreToolUse") {
		t.Fatal("the entry was not added")
	}
}

func TestOurOwnEntryIsReplacedNotDuplicated(t *testing.T) {
	before := `{"hooks":{"PreToolUse":[{"matcher":"Write","ultraloomOwned":true,
	  "hooks":[{"type":"command","command":"old"}]}]}}`
	got, err := Merge([]byte(before), []Entry{{Event: "PreToolUse", Matcher: "Write", Command: "new"}})
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if strings.Count(string(got.Merged), "\"matcher\"") != 1 {
		t.Fatalf("want one entry, got %s", got.Merged)
	}
	if !strings.Contains(string(got.Merged), "new") {
		t.Fatal("the entry was not replaced")
	}
}

func TestAForeignEntryIsLeftAloneAndReported(t *testing.T) {
	before := `{"hooks":{"PostToolUse":[{"matcher":"Write|Edit",
	  "hooks":[{"type":"command","command":"bash run.sh post_edit.py"}]}]}}`
	got, err := Merge([]byte(before), []Entry{{Event: "PostToolUse", Matcher: "Write|Edit", Command: "ours"}})
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if strings.Contains(string(got.Merged), "ours") {
		t.Fatal("a second hook was added next to a foreign one")
	}
	if len(got.Skipped) != 1 {
		t.Fatalf("skipped = %v, want one report", got.Skipped)
	}
}

func TestForeignKeysSurvive(t *testing.T) {
	before := `{"permissions":{"defaultMode":"auto"},"model":"opus"}`
	got, err := Merge([]byte(before), nil)
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	var after map[string]any
	if err := json.Unmarshal(got.Merged, &after); err != nil {
		t.Fatalf("result is not JSON: %v", err)
	}
	if _, ok := after["permissions"]; !ok {
		t.Fatal("permissions were lost")
	}
	if after["model"] != "opus" {
		t.Fatal("model was lost")
	}
}

func TestBrokenJsonIsRefused(t *testing.T) {
	if _, err := Merge([]byte("{not json"), nil); err == nil {
		t.Fatal("want an error, not a repair")
	}
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `go test ./internal/settings/`
Expected: FAIL, `undefined: Merge`

- [ ] **Step 3: Umsetzung schreiben**

`internal/settings/merge.go`:

```go
// Package settings adds hook entries to a file that belongs to someone else.
//
// Identity is (event, matcher, owner), not the command line: a changed
// command is still the same entry, and adding a second one next to a
// project's own hook would make both fire. Two parallel quality.py runs hung
// overnight on 2026-08-27 for exactly that reason.
package settings

import (
	"encoding/json"
	"fmt"
)

// OwnerKey marks an entry as written by this tool. Its absence means the
// entry belongs to the project, and then it is never touched.
const OwnerKey = "ultraloomOwned"

type Entry struct {
	Event   string
	Matcher string
	Command string
	Timeout int
}

type Result struct {
	Merged  []byte
	Skipped []string
}

func Merge(existing []byte, wanted []Entry) (Result, error) {
	root := map[string]any{}
	if len(existing) > 0 {
		if err := json.Unmarshal(existing, &root); err != nil {
			return Result{}, fmt.Errorf("settings.json is not valid JSON: %w", err)
		}
	}
	hooks, _ := root["hooks"].(map[string]any)
	if hooks == nil {
		hooks = map[string]any{}
	}
	var skipped []string
	for _, entry := range wanted {
		list, _ := hooks[entry.Event].([]any)
		index, foreign := find(list, entry.Matcher)
		if foreign {
			skipped = append(skipped, fmt.Sprintf(
				"%s/%s: a hook of this project is already there", entry.Event, entry.Matcher))
			continue
		}
		block := blockFor(entry)
		if index >= 0 {
			list[index] = block
		} else {
			list = append(list, block)
		}
		hooks[entry.Event] = list
	}
	root["hooks"] = hooks
	out, err := json.MarshalIndent(root, "", "  ")
	if err != nil {
		return Result{}, err
	}
	return Result{Merged: append(out, '\n'), Skipped: skipped}, nil
}

// find returns the index of our own entry for this matcher, or -1; the
// second value says a foreign entry holds the slot.
func find(list []any, matcher string) (int, bool) {
	for index, raw := range list {
		item, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		if item["matcher"] != matcher && matcher != "" {
			continue
		}
		if owned, _ := item[OwnerKey].(bool); owned {
			return index, false
		}
		return -1, true
	}
	return -1, false
}

func blockFor(entry Entry) map[string]any {
	command := map[string]any{"type": "command", "command": entry.Command}
	if entry.Timeout > 0 {
		command["timeout"] = entry.Timeout
	}
	block := map[string]any{OwnerKey: true, "hooks": []any{command}}
	if entry.Matcher != "" {
		block["matcher"] = entry.Matcher
	}
	return block
}
```

**Bekannte Folge, bewusst in Kauf genommen:** `json.MarshalIndent` sortiert Schlüssel alphabetisch. Eine bestehende `settings.json` wird dadurch umsortiert — semantisch identisch, im Diff aber sichtbar. Der Test `TestForeignKeysSurvive` sichert das ab, was zählt: es geht nichts verloren. Eine ordnungserhaltende JSON-Bibliothek wäre die Alternative und ist es für P1 nicht wert.

- [ ] **Step 4: Test laufen lassen, Erfolg prüfen**

Run: `go test ./internal/settings/ -v`
Expected: alle fünf PASS

- [ ] **Step 5: Commit**

```bash
git add internal/settings/
git commit -m "Add hooks to a file that belongs to someone else"
```

---

### Task 7: Die Coverage-Schwelle prüfen, nie setzen

**Files:**
- Create: `internal/coverage/check.go`
- Create: `internal/coverage/check_test.go`

**Interfaces:**
- Consumes: nichts
- Produces: `func Enforced(pyproject []byte, coveragerc []byte) bool`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`internal/coverage/check_test.go`:

```go
package coverage

import "testing"

func TestFailUnderInPyprojectCounts(t *testing.T) {
	if !Enforced([]byte("[tool.coverage.report]\nfail_under = 100\n"), nil) {
		t.Fatal("fail_under in pyproject was not seen")
	}
}

func TestFailUnderInCoveragercCounts(t *testing.T) {
	if !Enforced(nil, []byte("[report]\nfail_under = 90\n")) {
		t.Fatal("fail_under in .coveragerc was not seen")
	}
}

func TestAThresholdNobodyEnforcesIsNotEnforced(t *testing.T) {
	if Enforced([]byte("[project]\nname = \"x\"\n"), nil) {
		t.Fatal("claimed enforcement where there is none")
	}
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `go test ./internal/coverage/`
Expected: FAIL, `undefined: Enforced`

- [ ] **Step 3: Umsetzung schreiben**

`internal/coverage/check.go`:

```go
// Package coverage answers one question: does anything actually enforce the
// threshold?
//
// It never writes. `coverage report` takes its exit code from fail_under and
// from nothing else -- a run at 83 % is green without that key. A tool that
// prints "coverage: ok" for a threshold nobody checks is the one failure in
// this system that does real damage, so the check is here and the setting
// stays where its owner put it.
package coverage

import (
	"regexp"
)

var failUnder = regexp.MustCompile(`(?m)^\s*fail_under\s*=`)

func Enforced(pyproject, coveragerc []byte) bool {
	return failUnder.Match(pyproject) || failUnder.Match(coveragerc)
}
```

- [ ] **Step 4: Test laufen lassen, Erfolg prüfen**

Run: `go test ./internal/coverage/ -v`
Expected: alle drei PASS

- [ ] **Step 5: Commit**

```bash
git add internal/coverage/
git commit -m "Refuse to claim a threshold nobody enforces"
```

---

### Task 8: Atomar schreiben

**Files:**
- Create: `internal/write/atomic.go`
- Create: `internal/write/atomic_test.go`

**Interfaces:**
- Consumes: die `map[string]string` aus Task 5
- Produces:
  - `type Plan struct { Create map[string]string; Skip []string }`
  - `func Prepare(root string, files map[string]string) (Plan, error)`
  - `func Commit(root string, plan Plan) error`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`internal/write/atomic_test.go`:

```go
package write

import (
	"os"
	"path/filepath"
	"testing"
)

func TestAnExistingFileIsSkippedNotOverwritten(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(root, "keep.txt")
	if err := os.WriteFile(target, []byte("mine"), 0o644); err != nil {
		t.Fatal(err)
	}
	plan, err := Prepare(root, map[string]string{"keep.txt": "theirs"})
	if err != nil {
		t.Fatalf("Prepare: %v", err)
	}
	if len(plan.Create) != 0 || len(plan.Skip) != 1 {
		t.Fatalf("plan = %+v, want one skip and no create", plan)
	}
	if err := Commit(root, plan); err != nil {
		t.Fatalf("Commit: %v", err)
	}
	body, _ := os.ReadFile(target)
	if string(body) != "mine" {
		t.Fatalf("file was overwritten: %q", body)
	}
}

func TestDirectoriesAreCreatedForNewFiles(t *testing.T) {
	root := t.TempDir()
	plan, err := Prepare(root, map[string]string{".ultraloom/policy.toml": "x"})
	if err != nil {
		t.Fatalf("Prepare: %v", err)
	}
	if err := Commit(root, plan); err != nil {
		t.Fatalf("Commit: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, ".ultraloom", "policy.toml")); err != nil {
		t.Fatalf("file missing: %v", err)
	}
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `go test ./internal/write/`
Expected: FAIL, `undefined: Prepare`

- [ ] **Step 3: Umsetzung schreiben**

`internal/write/atomic.go`:

```go
// Package write decides first and writes second.
//
// The split is the point: an error in the third file must not leave a
// project where two files are new and the hook entries are old. Prepare
// reads, Commit writes, and --dry-run is Prepare without Commit.
package write

import (
	"fmt"
	"os"
	"path/filepath"
)

type Plan struct {
	Create map[string]string
	Skip   []string
}

func Prepare(root string, files map[string]string) (Plan, error) {
	plan := Plan{Create: map[string]string{}}
	for name, body := range files {
		full := filepath.Join(root, filepath.FromSlash(name))
		switch _, err := os.Stat(full); {
		case err == nil:
			plan.Skip = append(plan.Skip, name)
		case os.IsNotExist(err):
			plan.Create[name] = body
		default:
			return Plan{}, fmt.Errorf("looking at %s: %w", name, err)
		}
	}
	return plan, nil
}

func Commit(root string, plan Plan) error {
	for name, body := range plan.Create {
		full := filepath.Join(root, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
			return fmt.Errorf("creating the directory for %s: %w", name, err)
		}
		if err := os.WriteFile(full, []byte(body), 0o644); err != nil {
			return fmt.Errorf("writing %s: %w", name, err)
		}
	}
	return nil
}
```

- [ ] **Step 4: Test laufen lassen, Erfolg prüfen**

Run: `go test ./internal/write/ -v`
Expected: beide PASS

- [ ] **Step 5: Commit**

```bash
git add internal/write/
git commit -m "Decide everything before writing anything"
```

---

### Task 9: Vendoring und installed.toml

**Files:**
- Create: `internal/vendoring/vendoring.go`
- Create: `internal/vendoring/vendoring_test.go`

**Interfaces:**
- Consumes: nichts
- Produces:
  - `type Runner func(dir string, argv ...string) (string, error)`
  - `func Clone(run Runner, root, url, ref string) (commit string, err error)`
  - `func InstalledTOML(ref, commit, answersHash string, created []string) string`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`internal/vendoring/vendoring_test.go`:

```go
package vendoring

import (
	"errors"
	"strings"
	"testing"
)

func TestCloneAsksGitForTheExactRef(t *testing.T) {
	var calls [][]string
	run := func(dir string, argv ...string) (string, error) {
		calls = append(calls, argv)
		if argv[0] == "rev-parse" {
			return "3198f55\n", nil
		}
		return "", nil
	}
	commit, err := Clone(run, "/p", "https://example/ultra-loom.git", "v0.4.1")
	if err != nil {
		t.Fatalf("Clone: %v", err)
	}
	if commit != "3198f55" {
		t.Fatalf("commit = %q", commit)
	}
	if !strings.Contains(strings.Join(calls[0], " "), "v0.4.1") {
		t.Fatalf("the ref was not passed: %v", calls[0])
	}
}

func TestAFailingCloneIsReportedNotSwallowed(t *testing.T) {
	run := func(dir string, argv ...string) (string, error) {
		return "", errors.New("network is unreachable")
	}
	if _, err := Clone(run, "/p", "https://example/x.git", "main"); err == nil {
		t.Fatal("want the error to surface")
	}
}

func TestInstalledTomlRecordsWhatSyncWillNeed(t *testing.T) {
	got := InstalledTOML("v0.4.1", "3198f55", "abc123", []string{".ultraloom/policy.toml"})
	for _, want := range []string{"v0.4.1", "3198f55", "abc123", "policy.toml"} {
		if !strings.Contains(got, want) {
			t.Fatalf("installed.toml lacks %q:\n%s", want, got)
		}
	}
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `go test ./internal/vendoring/`
Expected: FAIL, `undefined: Clone`

- [ ] **Step 3: Umsetzung schreiben**

`internal/vendoring/vendoring.go`:

```go
// Package vendoring puts a fixed version of the runtime into the project.
//
// A pinned clone rather than a machine path: the hooks call Python ultraloom,
// every project should say which version that is, and an upgrade should be a
// visible step. wiki_gate.py drifted in two of three repos because nothing
// wrote the version down.
package vendoring

import (
	"fmt"
	"path/filepath"
	"strings"
)

// Runner is git, injected. The tests need no network and no repository.
type Runner func(dir string, argv ...string) (string, error)

const VendorDir = ".ultraloom/vendor/ultraloom"

func Clone(run Runner, root, url, ref string) (string, error) {
	target := filepath.Join(root, filepath.FromSlash(VendorDir))
	if _, err := run(root, "clone", "--depth", "1", "--branch", ref, url, target); err != nil {
		return "", fmt.Errorf("cloning %s at %s: %w", url, ref, err)
	}
	commit, err := run(target, "rev-parse", "--short", "HEAD")
	if err != nil {
		return "", fmt.Errorf("reading the cloned commit: %w", err)
	}
	return strings.TrimSpace(commit), nil
}

func InstalledTOML(ref, commit, answersHash string, created []string) string {
	var body strings.Builder
	body.WriteString("# generated by `ultraloom init` -- do not edit\n[vendor]\n")
	fmt.Fprintf(&body, "ref    = %q\ncommit = %q\n\n[answers]\nsha256 = %q\n\n[created]\nfiles = [\n", ref, commit, answersHash)
	for _, name := range created {
		fmt.Fprintf(&body, "  %q,\n", name)
	}
	body.WriteString("]\n")
	return body.String()
}
```

- [ ] **Step 4: Test laufen lassen, Erfolg prüfen**

Run: `go test ./internal/vendoring/ -v`
Expected: alle drei PASS

- [ ] **Step 5: Commit**

```bash
git add internal/vendoring/
git commit -m "Pin the runtime a project talks to"
```

---

### Task 10: brain finden und `.mcp.json` schreiben

**Files:**
- Create: `internal/brainpath/find.go`
- Create: `internal/brainpath/find_test.go`

**Interfaces:**
- Consumes: nichts
- Produces:
  - `type Lookup func(name string) (string, error)`
  - `func Find(look Lookup, env func(string) string) (string, bool)`
  - `func MCPEntry(command string) string`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`internal/brainpath/find_test.go`:

```go
package brainpath

import (
	"errors"
	"strings"
	"testing"
)

func TestAShimOnPathWinsAndStaysAName(t *testing.T) {
	look := func(name string) (string, error) { return "C:/Users/x/.local/bin/brain.exe", nil }
	got, ok := Find(look, func(string) string { return "" })
	if !ok {
		t.Fatal("brain was not found")
	}
	if got != "brain" {
		t.Fatalf("command = %q, want the bare name so no machine path is committed", got)
	}
}

func TestTheEnvironmentVariableIsTheLastResort(t *testing.T) {
	look := func(name string) (string, error) { return "", errors.New("not found") }
	env := func(key string) string {
		if key == "ULTRA_BRAIN_DIR" {
			return "D:/brain"
		}
		return ""
	}
	got, ok := Find(look, env)
	if !ok || !strings.Contains(got, "D:/brain") {
		t.Fatalf("command = %q, ok = %v", got, ok)
	}
}

func TestNothingFoundMeansNoWikiHooks(t *testing.T) {
	look := func(name string) (string, error) { return "", errors.New("not found") }
	if _, ok := Find(look, func(string) string { return "" }); ok {
		t.Fatal("claimed to have found brain")
	}
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `go test ./internal/brainpath/`
Expected: FAIL, `undefined: Find`

- [ ] **Step 3: Umsetzung schreiben**

`internal/brainpath/find.go`:

```go
// Package brainpath finds ultra-brain, and refuses to guess.
//
// brain holds one index across all projects, so it is found rather than
// pinned -- a clone per project would make separate brains and take from
// `search` exactly what makes it useful. When it is not found, the wiki
// hooks are not installed: a gate that cannot run is worse than none.
package brainpath

import "fmt"

// Lookup is exec.LookPath, injected so the tests need no PATH.
type Lookup func(name string) (string, error)

func Find(look Lookup, env func(string) string) (string, bool) {
	// The bare name, not the resolved path: .mcp.json is versioned, and an
	// absolute path in it is a claim about one machine.
	if _, err := look("brain"); err == nil {
		return "brain", true
	}
	if dir := env("ULTRA_BRAIN_DIR"); dir != "" {
		return fmt.Sprintf("uv run --directory %s brain", dir), true
	}
	return "", false
}

func MCPEntry(command string) string {
	return fmt.Sprintf(`{
  "mcpServers": {
    "brain": {
      "command": %q,
      "args": ["mcp"]
    }
  }
}
`, command)
}
```

- [ ] **Step 4: Test laufen lassen, Erfolg prüfen**

Run: `go test ./internal/brainpath/ -v`
Expected: alle drei PASS

- [ ] **Step 5: Commit**

```bash
git add internal/brainpath/
git commit -m "Find brain instead of pinning it"
```

---

### Task 11: Verdrahtung, Exit-Codes und ein Lauf gegen ein echtes Repo

**Files:**
- Modify: `cmd/init/main.go`
- Create: `cmd/init/run.go`
- Create: `cmd/init/run_test.go`

**Interfaces:**
- Consumes: alles aus Task 2 bis 10
- Produces: `func run(opts Options) (code int, report string)`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`cmd/init/run_test.go`:

```go
package main

import (
	"strings"
	"testing"
)

func TestDryRunWritesNothingAndSaysWhatItWould(t *testing.T) {
	root := t.TempDir()
	code, report := run(Options{Root: root, DryRun: true, Yes: true,
		CommitLanguage: "en", DocsLanguage: "de", WikiMode: "none"})
	if code != 0 {
		t.Fatalf("code = %d, report = %s", code, report)
	}
	if !strings.Contains(report, ".ultraloom/policy.toml") {
		t.Fatalf("report does not name what it would write:\n%s", report)
	}
	if _, err := osStat(root, ".ultraloom/policy.toml"); err == nil {
		t.Fatal("dry run wrote a file")
	}
}

func TestAMissingAnswerWithoutATtyExitsTwo(t *testing.T) {
	code, report := run(Options{Root: t.TempDir(), Interactive: false})
	if code != 2 {
		t.Fatalf("code = %d, want 2", code)
	}
	if !strings.Contains(report, "--commit-language") {
		t.Fatalf("report does not name the flag:\n%s", report)
	}
}

func TestASecondRunSkipsWhatIsAlreadyThere(t *testing.T) {
	root := t.TempDir()
	opts := Options{Root: root, Yes: true, CommitLanguage: "en", DocsLanguage: "de", WikiMode: "none"}
	if code, report := run(opts); code != 0 {
		t.Fatalf("first run: %d %s", code, report)
	}
	code, report := run(opts)
	if code != 0 {
		t.Fatalf("second run: %d %s", code, report)
	}
	if !strings.Contains(report, "skipped") {
		t.Fatalf("second run does not report skipping:\n%s", report)
	}
}
```

`osStat` ist ein dreizeiliger Helfer in `run_test.go`, der `os.Stat(filepath.Join(root, name))` aufruft.

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `go test ./cmd/init/`
Expected: FAIL, `undefined: run`

- [ ] **Step 3: Verdrahtung schreiben**

`cmd/init/run.go` ruft in dieser Reihenfolge auf und gibt bei jedem Fehler den passenden Code zurück:

```go
// The order is the contract: detect, ask, render, check, then write. Nothing
// touches the disk before the last step.
func run(opts Options) (int, string) {
	facts := detect.Detect(os.DirFS(opts.Root))
	current := answers.Defaults(facts)
	current = applyFlags(current, opts)

	filled, err := interview.Run(os.Stdin, os.Stdout, opts.Interactive, current)
	if errors.Is(err, interview.ErrNoTTY) {
		return 2, err.Error()
	}
	if err != nil {
		return 1, err.Error()
	}

	files, err := render.Render(filled)
	if err != nil {
		return 1, err.Error()
	}
	if !coverage.Enforced(readOr(opts.Root, "pyproject.toml"), readOr(opts.Root, ".coveragerc")) {
		delete(files, ".ultraloom/coverage.toml")
		// Reported, never silently dropped: a missing check the user does
		// not know about is the same as a check that lies.
	}

	plan, err := write.Prepare(opts.Root, files)
	if err != nil {
		return 1, err.Error()
	}
	if opts.DryRun {
		return 0, describe(plan)
	}
	if err := write.Commit(opts.Root, plan); err != nil {
		return 1, err.Error()
	}
	return 0, describe(plan)
}
```

`main.go` reduziert sich auf Flags lesen, `run` aufrufen, `report` ausgeben, `os.Exit(code)`.

- [ ] **Step 4: Test laufen lassen, Erfolg prüfen**

Run: `go test ./cmd/init/ -v`
Expected: alle drei PASS

- [ ] **Step 5: Trockenlauf gegen ein echtes Repo**

```bash
go run ./cmd/init --root "C:/Users/micro/Documents/#GIT/space" --dry-run --yes --commit-language en --docs-language de --wiki-mode brain
```

Erwartet: eine Liste dessen, was angelegt würde, ein `skipped`-Eintrag für `.claude/settings.json`, und **keine Änderung** im Repo. Danach `git -C "C:/Users/micro/Documents/#GIT/space" status --porcelain` — muss unverändert sein.

- [ ] **Step 6: Cross-Compile für alle Zielplattformen prüfen**

```bash
for target in windows/amd64 darwin/arm64 linux/amd64 freebsd/amd64 openbsd/amd64 netbsd/amd64; do CGO_ENABLED=0 GOOS=${target%/*} GOARCH=${target#*/} go build -o /dev/null ./cmd/init || echo "FAILED $target"; done
```

Erwartet: keine Ausgabe.

- [ ] **Step 7: Volles Gate**

Run: `uv run --project . ultraloom check all --root .`
Expected: lint, types, test und coverage grün — beide Sprachen

- [ ] **Step 8: Commit**

```bash
git add cmd/init/
git commit -m "Wire the pieces into one command with honest exit codes"
```

---

## Selbstprüfung gegen die Spec

| Spec-Abschnitt | Task |
|---|---|
| Was gebaut wird (Go, Modul, Struktur) | 1 |
| Erkennung, Signaltabelle, überlagerte Stacks | 2 |
| Antworten, `answers.toml`-Gestalt | 3 |
| Interview, Flags, kein TTY | 4 |
| Rendering, Kopfzeile, Vorlagen | 5 |
| `settings.json`-Merge, drei Fälle | 6 |
| Coverage geprüft statt gesetzt | 7 |
| Ganz oder gar nicht, `--dry-run`, vorhandene Dateien | 8 |
| Vendoring, `installed.toml` | 9 |
| brain finden, `.mcp.json`, keine Maschinenpfade | 10 |
| Exit-Codes, Randfälle, Gesamtlauf | 11 |

**Zwei Spec-Punkte, die dieser Plan bewusst nicht abdeckt** und die vor der Umsetzung eine Entscheidung brauchen:

- **Die Relevanzabbildung wird gerendert, aber von niemandem gelesen.** Sie landet in `config.toml`; dass Python-ultraloom sie auswertet, ist eine Änderung an `src/ultraloom/` und gehört in einen eigenen Plan. Bis dahin ist die Abbildung Dokumentation.
- **Der minimale OKF-Richtlinienblock** aus der Spec ist eine Textvorlage ohne Logik. Er gehört in Task 5 als vierte Vorlage, sobald der Text existiert — und der Text ist P3.

## Execution Handoff

Plan gespeichert unter `docs/.superpowers/plans/2026-08-28-installer-kern.md`. Zwei Wege:

1. **Subagentengetrieben (empfohlen)** — ein frischer Subagent je Task, Prüfung dazwischen, schnelle Iteration
2. **Inline** — Ausführung in dieser Sitzung über executing-plans, stapelweise mit Kontrollpunkten
