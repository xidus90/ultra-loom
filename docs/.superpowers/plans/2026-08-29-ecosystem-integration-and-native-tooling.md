# Ecosystem Integration & Go-Native Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate proven quality gates, language filters, multi-ecosystem presets, and write-barriers from sibling repositories (`space`, `iam_backend`, `ultra-brain`, `iam_frontend`) into UltraLoom's Go core and configuration engine.

**Architecture:** Implement fast, native Go packages under `internal/verify`, `internal/commit`, and `internal/detect` for zero-latency verification and hooks. Scaffolding in `cmd/init` (`ulinit`) sets up native Git hooks (`pre-commit`, `commit-msg`) and presets (TypeScript, GDScript, Django, Go, Python). `cmd/guard` (`ulguard`) enforces sub-millisecond write-barrier and command policies.

**Tech Stack:** Go 1.24+, Standard Library (`go/parser`, `go/format`, `os/exec`, `regexp`), TOML parsing (`pelletier/go-toml/v2`), Git CLI.

**Spec:** [2026-08-29-ecosystem-integration-and-native-tooling-design.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/specs/2026-08-29-ecosystem-integration-and-native-tooling-design.md)

## Global Constraints

- **Go Toolchain:** Go 1.24+, test coverage floor maintained at ≥ 98.0%.
- **Zero Python Runtime for Go Checks:** Go formatting, commit language checking, and policy evaluation must execute purely in Go without Python or WSL invocation.
- **Windows Path Cleanliness:** All filesystem operations must use `filepath.Clean` and handle `#` paths (such as `#GIT`) without URL truncation.
- **English-Only Commits & Messages:** All code, comments, docstrings, and commit messages must be in English.

---

### Task 1: Go-Native Format Checker (`internal/verify/gofmt.go`)

**Files:**
- Create: `internal/verify/gofmt.go`
- Test: `internal/verify/gofmt_test.go`

**Interfaces:**
- Produces: `CheckGoFormat(roots []string) ([]string, error)` returns list of unformatted `.go` file paths.

- [ ] **Step 1: Write failing test for `CheckGoFormat`**

```go
package verify_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/xidus90/ultra-loom/internal/verify"
)

func TestCheckGoFormat(t *testing.T) {
	tmpDir := t.TempDir()
	
	// Create formatted file
	formattedFile := filepath.Join(tmpDir, "clean.go")
	if err := os.WriteFile(formattedFile, []byte("package main\n\nfunc main() {}\n"), 0644); err != nil {
		t.Fatal(err)
	}

	// Create unformatted file
	unformattedFile := filepath.Join(tmpDir, "dirty.go")
	if err := os.WriteFile(unformattedFile, []byte("package main\nfunc  main( ) {}\n"), 0644); err != nil {
		t.Fatal(err)
	}

	unformatted, err := verify.CheckGoFormat([]string{tmpDir})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(unformatted) != 1 || filepath.Base(unformatted[0]) != "dirty.go" {
		t.Fatalf("expected dirty.go, got: %v", unformatted)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/verify/...`  
Expected: FAIL (package/function not declared).

- [ ] **Step 3: Implement `CheckGoFormat`**

```go
package verify

import (
	"bytes"
	"fmt"
	"go/format"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
)

// CheckGoFormat walks given directory roots and identifies any unformatted .go files.
func CheckGoFormat(roots []string) ([]string, error) {
	var unformatted []string
	fset := token.NewFileSet()

	for _, root := range roots {
		info, err := os.Stat(root)
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			return nil, fmt.Errorf("stat root %s: %w", root, err)
		}

		if !info.IsDir() {
			if filepath.Ext(root) == ".go" {
				dirty, err := isFileUnformatted(fset, root)
				if err != nil {
					return nil, err
				}
				if dirty {
					unformatted = append(unformatted, root)
				}
			}
			continue
		}

		err = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if d.IsDir() {
				name := d.Name()
				if name == "vendor" || name == ".git" || name == "node_modules" {
					return filepath.SkipDir
				}
				return nil
			}
			if filepath.Ext(path) != ".go" {
				return nil
			}

			dirty, err := isFileUnformatted(fset, path)
			if err != nil {
				return err
			}
			if dirty {
				unformatted = append(unformatted, path)
			}
			return nil
		})
		if err != nil {
			return nil, fmt.Errorf("walk root %s: %w", root, err)
		}
	}

	return unformatted, nil
}

func isFileUnformatted(fset *token.FileSet, path string) (bool, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return false, fmt.Errorf("read file %s: %w", path, err)
	}

	node, err := parser.ParseFile(fset, path, content, parser.ParseComments)
	if err != nil {
		return false, fmt.Errorf("parse %s: %w", path, err)
	}

	var buf bytes.Buffer
	if err := format.Node(&buf, fset, node); err != nil {
		return false, fmt.Errorf("format %s: %w", path, err)
	}

	return !bytes.Equal(content, buf.Bytes()), nil
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/verify/...`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/verify/
git commit -m "feat(verify): add native gofmt checker in Go"
```

---

### Task 2: Go-Native Dual-Coverage Floor Evaluator (`internal/verify/coverage.go`)

**Files:**
- Create: `internal/verify/coverage.go`
- Test: `internal/verify/coverage_test.go`

**Interfaces:**
- Produces: `ParseGoCoverage(summaryOutput string) (float64, error)`, `CheckCoverageFloor(percent float64, floor float64) error`

- [ ] **Step 1: Write failing test for coverage parsing & floor checking**

```go
package verify_test

import (
	"testing"

	"github.com/xidus90/ultra-loom/internal/verify"
)

func TestParseGoCoverage(t *testing.T) {
	output := "total:\t(statements)\t98.5%\n"
	pct, err := verify.ParseGoCoverage(output)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if pct != 98.5 {
		t.Fatalf("expected 98.5, got %v", pct)
	}

	if err := verify.CheckCoverageFloor(pct, 98.0); err != nil {
		t.Fatalf("expected pass, got %v", err)
	}

	if err := verify.CheckCoverageFloor(pct, 99.0); err == nil {
		t.Fatal("expected failure when below floor, got nil")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/verify/...`  
Expected: FAIL.

- [ ] **Step 3: Implement coverage parsing & evaluation**

```go
package verify

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

var goCoverTotalRegex = regexp.MustCompile(`(?m)^total:\s+\(statements\)\s+([0-9.]+)%`)

// ParseGoCoverage extracts total percentage from `go tool cover -func` output.
func ParseGoCoverage(output string) (float64, error) {
	matches := goCoverTotalRegex.FindStringSubmatch(output)
	if len(matches) < 2 {
		return 0, fmt.Errorf("go tool cover output did not contain total percentage: %s", strings.TrimSpace(output))
	}
	pct, err := strconv.ParseFloat(matches[1], 64)
	if err != nil {
		return 0, fmt.Errorf("parse coverage percentage %q: %w", matches[1], err)
	}
	return pct, nil
}

// CheckCoverageFloor validates that the measured coverage satisfies the minimum floor.
func CheckCoverageFloor(measured, floor float64) error {
	if measured < floor {
		return fmt.Errorf("coverage %.1f%% is below required floor of %.1f%%", measured, floor)
	}
	return nil
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/verify/...`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/verify/coverage*
git commit -m "feat(verify): add go coverage parser and floor evaluator"
```

---

### Task 3: Go-Native Commit Message Language & Quality Gate (`internal/commit/language.go`)

**Files:**
- Create: `internal/commit/language.go`
- Test: `internal/commit/language_test.go`

**Interfaces:**
- Produces: `ValidateCommitMessage(msg string) error` returns nil if valid English commit, or error explaining German/invalid content.

- [ ] **Step 1: Write failing test for commit language validation**

```go
package commit_test

import (
	"testing"

	"github.com/xidus90/ultra-loom/internal/commit"
)

func TestValidateCommitMessage(t *testing.T) {
	validMessages := []string{
		"feat(verify): add native gofmt checker in Go",
		"fix: resolve null pointer dereference in runner",
		"docs: update readme with bilingual details",
	}

	for _, msg := range validMessages {
		if err := commit.ValidateCommitMessage(msg); err != nil {
			t.Errorf("expected valid for %q, got error: %v", msg, err)
		}
	}

	invalidMessages := []string{
		"feat: füge neue sprachprüfung hinzu",
		"korrigiere fehler in der verifikation",
		"aktualisiere dokumentation und beispiele",
		"WIP: ändere dateien",
	}

	for _, msg := range invalidMessages {
		if err := commit.ValidateCommitMessage(msg); err == nil {
			t.Errorf("expected error for German message %q, got nil", msg)
		}
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/commit/...`  
Expected: FAIL.

- [ ] **Step 3: Implement `ValidateCommitMessage`**

```go
package commit

import (
	"fmt"
	"regexp"
	"strings"
)

var germanStopWords = map[string]bool{
	"der": true, "die": true, "das": true, "und": true, "oder": true,
	"nicht": true, "für": true, "mit": true, "auf": true, "von": true,
	"ein": true, "eine": true, "einer": true, "eines": true, "einem": true,
	"füge": true, "hinzu": true, "aktualisiere": true, "korrigiere": true,
	"entferne": true, "behebe": true, "ändere": true, "erweitere": true,
	"überarbeite": true, "verbessere": true, "erstelle": true,
}

var umlautRegex = regexp.MustCompile(`[äöüÄÖÜß]`)

// ValidateCommitMessage checks that a commit message is written in English.
func ValidateCommitMessage(msg string) error {
	trimmed := strings.TrimSpace(msg)
	if trimmed == "" {
		return fmt.Errorf("commit message cannot be empty")
	}

	firstLine := strings.Split(trimmed, "\n")[0]

	// 1. Direct Umlaut Check
	if umlautRegex.MatchString(firstLine) {
		return fmt.Errorf("commit message contains German umlauts/characters. All commit messages must be in English (AGENTS.md)")
	}

	// 2. Tokenize words
	words := strings.Fields(strings.ToLower(firstLine))
	germanHits := 0
	for _, w := range words {
		cleaned := strings.Trim(w, ":,().'\"`")
		if germanStopWords[cleaned] {
			germanHits++
		}
	}

	if germanHits > 0 {
		return fmt.Errorf("commit message appears to be in German (%d German keywords detected). All commit messages must be in English (AGENTS.md)", germanHits)
	}

	return nil
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/commit/...`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/commit/
git commit -m "feat(commit): add commit message language validation gate"
```

---

### Task 4: Multi-Language & Web/GDScript Presets (`internal/detect/web.go`, `internal/detect/godot.go`)

**Files:**
- Create: `internal/detect/web.go`
- Create: `internal/detect/godot.go`
- Modify: `internal/detect/detect.go`
- Test: `internal/detect/detect_test.go`

**Interfaces:**
- Extends: `DetectFacts(dir string) (*Facts, error)` to detect Web/TypeScript stacks (`Biome`, `ESLint`, `Vitest`) and Godot stacks (`GDScript`, `gdlint`, `project.godot`).

- [ ] **Step 1: Write failing test for Web & Godot detection**

```go
package detect_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/xidus90/ultra-loom/internal/detect"
)

func TestDetectWebAndGodot(t *testing.T) {
	// 1. Web / TypeScript test
	webDir := t.TempDir()
	os.WriteFile(filepath.Join(webDir, "package.json"), []byte(`{"devDependencies":{"biome":"1.0","vitest":"1.0"}}`), 0644)
	facts, err := detect.DetectFacts(webDir)
	if err != nil {
		t.Fatal(err)
	}
	if !facts.HasTypeScript && !facts.HasNode {
		t.Errorf("expected HasTypeScript or HasNode, got: %+v", facts)
	}

	// 2. Godot test
	godotDir := t.TempDir()
	os.WriteFile(filepath.Join(godotDir, "project.godot"), []byte(`config_version=5`), 0644)
	factsGodot, err := detect.DetectFacts(godotDir)
	if err != nil {
		t.Fatal(err)
	}
	if !factsGodot.HasGodot {
		t.Errorf("expected HasGodot, got: %+v", factsGodot)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/detect/...`  
Expected: FAIL.

- [ ] **Step 3: Implement Web & Godot detection extensions**

Add fields to `Facts` struct in `internal/detect/detect.go`:
```go
type Facts struct {
	// ... existing fields ...
	HasTypeScript bool
	HasNode       bool
	HasGodot      bool
	HasBiome      bool
}
```
Implement detection helpers in `internal/detect/web.go` and `internal/detect/godot.go`.

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/detect/...`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/detect/
git commit -m "feat(detect): support TypeScript, Biome, Vitest, and Godot detection"
```

---

### Task 5: Ulinit Wiring for Commit-Msg Hook & Presets (`cmd/init`)

**Files:**
- Modify: `cmd/init/run.go`
- Test: `cmd/init/run_test.go`

**Interfaces:**
- `runInit` writes `.githooks/commit-msg` executing `ulinit hook commit-msg "$1"` or native check, and configures `.githooks/pre-commit`.

- [ ] **Step 1: Write test for commit-msg hook installation**

In `cmd/init/run_test.go`, assert `.githooks/commit-msg` is generated when hooks are initialized.

- [ ] **Step 2: Implement hook generation in `cmd/init/run.go`**

Generate `.githooks/commit-msg`:
```bash
#!/usr/bin/env bash
# UltraLoom commit message quality gate
set -euo pipefail

ulinit check commit-msg "$1"
```

- [ ] **Step 3: Run test to verify it passes**

Run: `go test ./cmd/init/...`  
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add cmd/init/
git commit -m "feat(init): wire commit-msg language gate in ulinit"
```

---

### Task 6: Ulguard Policy Engine & Write Barrier Expansion (`cmd/guard`)

**Files:**
- Modify: `cmd/guard/guard.go`
- Test: `cmd/guard/guard_test.go`

**Interfaces:**
- Evaluates `[policy.paths.rules]` for write tool calls (`Write`, `Edit`, `MultiEdit`) to block modification of protected external bundles or cited references.

- [ ] **Step 1: Write test for write-barrier rule enforcement**

In `cmd/guard/guard_test.go`, test path rules matching `docs/reference/*` or external bundles.

- [ ] **Step 2: Implement write-barrier verification in `cmd/guard/guard.go`**

Support `isWriteTool` detection and rule validation against target paths.

- [ ] **Step 3: Run test to verify it passes**

Run: `go test ./cmd/guard/...`  
Expected: PASS (Coverage maintained ≥ 98%).

- [ ] **Step 4: Commit**

```bash
git add cmd/guard/
git commit -m "feat(guard): add write-barrier path protection to ulguard"
```

---

### Task 7: Full Integration Verification & Deprecation of Legacy Scripts

**Files:**
- Modify: `.ultraloom/config.toml`
- Deprecate / Replace: `hooks/gofmt-check.py`, `hooks/coverage-check.py`

- [ ] **Step 1: Update `.ultraloom/config.toml` to use native Go verifiers**

Configure:
```toml
[verify.lint]
commands = [
  "uv run ruff check .",
  "ulinit check gofmt cmd internal",
  "go vet ./...",
]
threaded = true

[verify.coverage]
threshold = 100
report    = "ulinit check coverage --go-floor=98"
```

- [ ] **Step 2: Run complete project quality verification**

Run: `uv run ultraloom check all` and `go test ./... -cover`  
Expected: 100% green on all gates with statement coverage ≥ 98%.

- [ ] **Step 3: Commit final integration**

```bash
git add .
git commit -m "feat(core): switch ultraloom self-check to native Go verifiers"
```

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-29-ecosystem-integration-and-native-tooling.md`.

Two execution options:
1. **Subagent-Driven (recommended)** - Fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach would you like to use?
