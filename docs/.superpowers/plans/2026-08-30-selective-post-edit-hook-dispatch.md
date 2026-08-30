# Selective PostToolUse Hook Dispatching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a Go-native `ulguard post-edit` dispatcher that parses stdin tool payloads on file edits, selectively executes only relevant language stack checks (with zero latency for docs/assets and a full-chain fallback for unknown extensions), and consolidate `.claude/settings.json` PostToolUse hooks.

**Architecture:** Extend `cmd/guard` with a `post-edit` subcommand that inspects `tool_input.file_path`, maps the extension to configured stacks from `detect` / `answers.toml`, executes matching commands sequentially, and returns non-zero if any check fails. Update `cmd/init/run.go` to emit a single `ulguard post-edit` PostToolUse hook.

**Tech Stack:** Go 1.24+, Standard Library (`os/exec`, `path/filepath`, `encoding/json`), `.claude/settings.json`.

**Spec:** [docs/.superpowers/specs/2026-08-30-selective-post-edit-hook-dispatch-design.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/specs/2026-08-30-selective-post-edit-hook-dispatch-design.md)

## Global Constraints

- **Go Coverage Floor:** Maintain Go statement coverage at $\ge 98.0\%$.
- **Sub-Millisecond Dispatch Overhead:** Parsing and extension routing in `ulguard` must take $< 1\text{ ms}$.
- **Fail-Safe Fallback:** Unknown file extensions not in the explicit ignore list must execute all configured stack checks.
- **English-Only Code & Commits:** All code, comments, docstrings, error messages, and commit messages must be in English.

---

### Task 1: Post-Edit Payload Parser & Language Router in Go

**Files:**
- Create: `cmd/guard/post_edit.go`
- Test: `cmd/guard/post_edit_test.go`

**Interfaces:**
- Produces: `runPostEdit(stdin io.Reader, stderr io.Writer, root string, runner CommandRunner) int`

- [ ] **Step 1: Write failing test for `runPostEdit` in `post_edit_test.go`**

```go
package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestRunPostEdit(t *testing.T) {
	tests := []struct {
		name         string
		payload      string
		stacks       []string
		expectedCmds []string
		expectedExit int
	}{
		{
			name:         "Python file triggers only python tools",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "src/main.py"}}`,
			stacks:       []string{"python", "uv", "cpp", "gdscript"},
			expectedCmds: []string{"ruff check", "dmypy run"},
			expectedExit: 0,
		},
		{
			name:         "C++ file triggers only cpp tools",
			payload:      `{"tool_name": "Write", "tool_input": {"file_path": "core/engine.cpp"}}`,
			stacks:       []string{"python", "cpp", "cmake"},
			expectedCmds: []string{"clang-format -i", "cmake --build"},
			expectedExit: 0,
		},
		{
			name:         "Markdown file exits immediately with 0",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "docs/README.md"}}`,
			stacks:       []string{"python", "cpp", "gdscript"},
			expectedCmds: nil,
			expectedExit: 0,
		},
		{
			name:         "Unknown extension triggers fallback to all stacks",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "custom.xyz"}}`,
			stacks:       []string{"python", "cpp"},
			expectedCmds: []string{"ruff check", "dmypy run", "clang-format -i", "cmake --build"},
			expectedExit: 0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var ranCmds []string
			mockRunner := func(dir string, cmd string) (string, error) {
				ranCmds = append(ranCmds, cmd)
				return "", nil
			}

			var stderr bytes.Buffer
			exitCode := runPostEditWithStacks(strings.NewReader(tt.payload), &stderr, ".", tt.stacks, mockRunner)
			if exitCode != tt.expectedExit {
				t.Fatalf("expected exit %d, got %d", tt.expectedExit, exitCode)
			}
			if len(tt.expectedCmds) == 0 && len(ranCmds) != 0 {
				t.Fatalf("expected no commands, ran %v", ranCmds)
			}
			for _, exp := range tt.expectedCmds {
				found := false
				for _, ran := range ranCmds {
					if strings.Contains(ran, exp) {
						found = true
						break
					}
				}
				if !found {
					t.Fatalf("expected command containing %q in %v", exp, ranCmds)
				}
			}
		})
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./cmd/guard/... -run TestRunPostEdit`  
Expected: FAIL (function undefined).

- [ ] **Step 3: Implement `cmd/guard/post_edit.go`**

```go
package main

import (
	"encoding/json"
	"io"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/xidus90/ultra-loom/internal/detect"
)

type CommandRunner func(dir string, cmd string) (string, error)

func defaultCommandRunner(dir string, commandStr string) (string, error) {
	cmd := exec.Command("cmd", "/c", commandStr)
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	return string(out), err
}

var explicitIgnoredExtensions = map[string]bool{
	".md":     true,
	".txt":    true,
	".json":   true,
	".yaml":   true,
	".yml":    true,
	".toml":   true,
	".svg":    true,
	".png":    true,
	".jpg":    true,
	".jpeg":   true,
	".import": true,
	".lock":   true,
}

var extensionStackMap = map[string]string{
	".py":   "python",
	".gd":   "gdscript",
	".cpp":  "cpp",
	".hpp":  "cpp",
	".cc":   "cpp",
	".cxx":  "cpp",
	".c":    "cpp",
	".h":    "cpp",
	".ts":   "typescript",
	".tsx":  "typescript",
	".js":   "typescript",
	".jsx":  "typescript",
	".go":   "go",
	".rs":   "rust",
}

func runPostEdit(stdin io.Reader, stderr io.Writer, root string) int {
	facts, err := detect.Gather(root, nil)
	var stacks []string
	if err == nil {
		stacks = facts.Stacks
	}
	return runPostEditWithStacks(stdin, stderr, root, stacks, defaultCommandRunner)
}

func runPostEditWithStacks(stdin io.Reader, stderr io.Writer, root string, stacks []string, runner CommandRunner) int {
	var payload HookPayload
	if err := json.NewDecoder(stdin).Decode(&payload); err != nil {
		return ExitOK
	}

	rawPath, ok := payload.ToolInput["file_path"].(string)
	if !ok || rawPath == "" {
		rawPath, _ = payload.ToolInput["notebook_path"].(string)
	}
	if rawPath == "" {
		return ExitOK
	}

	ext := strings.ToLower(filepath.Ext(rawPath))
	if explicitIgnoredExtensions[ext] {
		return ExitOK
	}

	targetStack, hasTarget := extensionStackMap[ext]

	commands := getCommandsForStacks(stacks, targetStack, hasTarget)
	hasFailure := false
	for _, cmd := range commands {
		out, err := runner(root, cmd)
		if err != nil {
			hasFailure = true
			io.WriteString(stderr, out)
			if out == "" {
				io.WriteString(stderr, err.Error()+"\n")
			}
		}
	}

	if hasFailure {
		return ExitDenied
	}
	return ExitOK
}

func getCommandsForStacks(stacks []string, targetStack string, hasTarget bool) []string {
	var cmds []string
	has := func(s string) bool {
		for _, stack := range stacks {
			if stack == s {
				return true
			}
		}
		return false
	}

	shouldRun := func(s string) bool {
		if !has(s) {
			return false
		}
		if !hasTarget {
			return true // Fallback: run all stacks
		}
		return s == targetStack
	}

	if shouldRun("python") {
		if has("uv") {
			cmds = append(cmds, "ruff check --output-format=concise .", "dmypy run -- --no-error-summary --no-pretty")
		} else {
			cmds = append(cmds, "ruff check --output-format=concise .", "mypy --no-error-summary --no-pretty")
		}
	}
	if shouldRun("gdscript") {
		cmds = append(cmds, "gdlint .")
	}
	if shouldRun("cpp") {
		cmds = append(cmds, "clang-format -i", "cmake --build build --parallel")
	}
	if shouldRun("typescript") {
		cmds = append(cmds, "npx eslint .", "npx tsc --noEmit")
	}
	if shouldRun("rust") {
		cmds = append(cmds, "cargo clippy -- -D warnings", "cargo fmt --check")
	}
	if shouldRun("go") {
		cmds = append(cmds, "go vet ./...")
	}

	return cmds
}
```

- [ ] **Step 4: Run tests in `cmd/guard/...`**

Run: `go test -v -cover ./cmd/guard/...`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cmd/guard/
git commit -m "feat(guard): add selective post-edit hook dispatcher with fallback"
```

---

### Task 2: CLI Wiring for `ulguard post-edit`

**Files:**
- Modify: `cmd/guard/main.go`
- Test: `cmd/guard/main_test.go`

- [ ] **Step 1: Write failing test in `main_test.go` for `post-edit` subcommand**

```go
func TestCliPostEdit(t *testing.T) {
	input := `{"tool_name": "Edit", "tool_input": {"file_path": "README.md"}}`
	var stderr bytes.Buffer
	code := cli([]string{"post-edit", "--root", "."}, strings.NewReader(input), &stderr)
	if code != ExitOK {
		t.Fatalf("expected ExitOK for README.md, got %d", code)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./cmd/guard/... -run TestCliPostEdit`  
Expected: FAIL

- [ ] **Step 3: Update `cmd/guard/main.go` to support subcommands**

```go
func cli(args []string, stdin io.Reader, stderr io.Writer) int {
	if len(args) > 0 && args[0] == "post-edit" {
		flags := flag.NewFlagSet("ultraloom-guard post-edit", flag.ContinueOnError)
		flags.SetOutput(stderr)
		root := flags.String("root", ".", "path to the project root")
		if err := flags.Parse(args[1:]); err != nil {
			return ExitInternal
		}
		return runPostEdit(stdin, stderr, *root)
	}

	flags := flag.NewFlagSet("ultraloom-guard", flag.ContinueOnError)
	flags.SetOutput(stderr)
	root := flags.String("root", ".", "path to the project root")
	if err := flags.Parse(args); err != nil {
		return ExitInternal
	}
	return runGuard(stdin, stderr, *root)
}
```

- [ ] **Step 4: Run all tests in `cmd/guard`**

Run: `go test -v -cover ./cmd/guard/...`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cmd/guard/
git commit -m "feat(guard): wire post-edit subcommand into ulguard CLI"
```

---

### Task 3: Consolidated PostToolUse Hook Generation in `ulinit`

**Files:**
- Modify: `cmd/init/run.go`
- Test: `cmd/init/run_test.go`

- [ ] **Step 1: Update `cmd/init/run.go` to emit `ulguard post-edit` instead of per-stack hooks**

```go
func postEditEntries(stacks []string) []settings.Entry {
	if len(stacks) == 0 {
		return nil
	}
	return []settings.Entry{
		{
			Event:   "PostToolUse",
			Matcher: "Write|Edit|NotebookEdit",
			Command: `ulguard post-edit --root "${CLAUDE_PROJECT_DIR}"`,
			Timeout: 60,
		},
	}
}
```

- [ ] **Step 2: Update assertions in `cmd/init/run_test.go`**

- [ ] **Step 3: Run all Go unit tests**

Run: `go test ./...`  
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add cmd/init/
git commit -m "feat(init): emit consolidated ulguard post-edit hook in settings.json"
```

---

### Task 4: Worktree E2E Benchmark & Latency Verification

- [ ] **Step 1: Build `ulguard.exe` and `ulinit.exe`**
- [ ] **Step 2: Run benchmark script in a multi-stack worktree testing `.py`, `.cpp`, `.md`, and `.custom` edits**
- [ ] **Step 3: Verify that `.md` takes < 1ms, `.py` triggers only Python checks, and `.custom` triggers the fallback**
- [ ] **Step 4: Run full verification suite (`uv run ultraloom check all`)**
