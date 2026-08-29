# C++ Stack Integration & Multi-Language Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace legacy C# tooling with a modern C++ stack (CMake/Ninja, Clang tools, CTest), implement automatic test framework scanning from `CMakeLists.txt` (GoogleTest, Catch2, doctest), configure C++ PostToolUse hooks, and integrate Python check presets.

**Architecture:** Update Go core detection (`internal/detect`), tooling management (`internal/tooling`), and initialization scaffolding (`cmd/init`) to recognize C++ projects and configure clang-format/clang-tidy and build hooks. In Python (`src/ultraloom/checks.py`), register CMakePresets for linting, testing, and coverage.

**Tech Stack:** Go 1.24+, Python 3.13+, CMake, Ninja, LLVM/Clang (`clang-format`, `clang-tidy`), CTest, GoogleTest, Catch2, doctest, `gcovr`.

**Spec:** [docs/.superpowers/specs/2026-08-30-cpp-stack-and-multi-tooling-design.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/specs/2026-08-30-cpp-stack-and-multi-tooling-design.md)

## Global Constraints

- **Zero C# Artifacts:** Remove all references to `csharp`, `dotnet`, `*.csproj`, `*.sln` from signals, tooling, tests, and hooks.
- **Go Coverage Floor:** Maintain Go statement coverage at $\ge 98.0\%$ across all packages.
- **Python Coverage Floor:** Maintain Python coverage at $100\%$.
- **Direct Pinned Shims & Direct Executables:** PostToolUse hooks and tool commands must run direct native binaries (e.g. `clang-format`, `cmake`) without shell wrappers or WSL translations.
- **English-Only Prose & Code:** All code, comments, docstrings, error messages, and commit messages must be in English.

---

### Task 1: C# Signal Deprecation & C++ Detection in Go Engine

**Files:**
- Modify: `internal/detect/signals.go:20-45`
- Test: `internal/detect/detect_test.go`

**Interfaces:**
- Produces: Updated `signals` table recognizing `cpp`, `cmake`, `meson`, `clang-tidy`, `clang-format` and omitting `csharp`.

- [ ] **Step 1: Write failing test in `detect_test.go` for C++ signals and C# absence**

```go
func TestDetectCPPStacks(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "CMakeLists.txt"), []byte("cmake_minimum_required(VERSION 3.20)\nproject(sample)\n"), 0644); err != nil {
		t.Fatal(err)
	}
	facts, err := detect.Gather(dir, nil)
	if err != nil {
		t.Fatalf("Gather failed: %v", err)
	}
	if !has(facts.Stacks, "cpp") || !has(facts.Stacks, "cmake") {
		t.Fatalf("expected cpp and cmake stacks, got %v", facts.Stacks)
	}
	if has(facts.Stacks, "csharp") {
		t.Fatalf("did not expect csharp stack, got %v", facts.Stacks)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/detect/... -run TestDetectCPPStacks`  
Expected: FAIL (missing `cpp` and `cmake` stacks).

- [ ] **Step 3: Update `signals.go` to remove C# and add C++ signals**

```go
// In internal/detect/signals.go
var signals = []signal{
	{path: "pyproject.toml", stacks: []string{"python"}},
	{path: "uv.lock", stacks: []string{"python", "uv"}},
	{path: "requirements.txt", stacks: []string{"python"}},
	{path: "manage.py", stacks: []string{"python", "django"}},
	{path: "project.godot", stacks: []string{"godot", "gdscript"}},
	{path: "CMakeLists.txt", stacks: []string{"cpp", "cmake"}},
	{path: "CMakePresets.json", stacks: []string{"cpp", "cmake"}},
	{path: "meson.build", stacks: []string{"cpp", "meson"}},
	{path: ".clang-tidy", stacks: []string{"cpp", "clang-tidy"}},
	{path: ".clang-format", stacks: []string{"cpp", "clang-format"}},
	{path: "tsconfig.json", besides: "package.json", stacks: []string{"typescript"}},
	{path: "biome.json", stacks: []string{"biome", "typescript"}},
	{path: "pnpm-workspace.yaml", stacks: []string{"pnpm"}},
	{path: ".gdlintrc", stacks: []string{"gdlint", "gdscript"}},
	{path: "docker-compose.yml", stacks: []string{"docker"}},
	{path: "compose.yaml", stacks: []string{"docker"}},
	{path: "Cargo.toml", stacks: []string{"rust"}},
	{path: "go.mod", stacks: []string{"go"}},
}
```

- [ ] **Step 4: Update all existing C# tests in `detect_test.go` and run tests**

Run: `go test ./internal/detect/...`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add internal/detect/
git commit -m "feat(detect): replace csharp signals with cpp and cmake stack detection"
```

---

### Task 2: C++ Tooling Definitions & Installation Shims

**Files:**
- Modify: `internal/tooling/tooling.go:17-41`
- Test: `internal/tooling/tooling_test.go`

**Interfaces:**
- Produces: `StackTools["cpp"]` defining `clang-format`, `clang-tidy`, `cmake`, and `ninja`.

- [ ] **Step 1: Write failing test in `tooling_test.go` for C++ tools**

```go
func TestCheckToolsCPP(t *testing.T) {
	lookup := func(file string) (string, error) {
		if file == "cmake" || file == "ninja" || file == "clang-format" || file == "clang-tidy" {
			return "/usr/bin/" + file, nil
		}
		return "", errors.New("not found")
	}
	found, missing := tooling.CheckTools([]string{"cpp"}, lookup)
	if len(missing) != 0 {
		t.Fatalf("expected 0 missing cpp tools, got %v", missing)
	}
	if found["cmake"] != "/usr/bin/cmake" || found["clang-format"] != "/usr/bin/clang-format" {
		t.Fatalf("expected found tools, got %v", found)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/tooling/... -run TestCheckToolsCPP`  
Expected: FAIL (missing `cpp` in `StackTools`).

- [ ] **Step 3: Update `tooling.go` to replace `csharp` with `cpp`**

```go
// In internal/tooling/tooling.go
var StackTools = map[string][]ToolSpec{
	"python": {
		{Name: "uv", Stack: "python", InstallCmd: "curl -LsSf https://astral.sh/uv/install.sh | sh", Description: "Python package and tool manager"},
		{Name: "ruff", Stack: "python", InstallCmd: "uv tool install ruff", Description: "Fast Python linter and formatter"},
		{Name: "dmypy", Stack: "python", InstallCmd: "uv tool install mypy", Description: "Daemonized fast Python type checker"},
	},
	"gdscript": {
		{Name: "gdlint", Stack: "gdscript", InstallCmd: "uv tool install gdtoolkit==4.3.3", Description: "GDScript linter and code quality checker"},
	},
	"cpp": {
		{Name: "clang-format", Stack: "cpp", InstallCmd: "winget install LLVM.LLVM", Description: "Clang code formatter for C++"},
		{Name: "clang-tidy", Stack: "cpp", InstallCmd: "winget install LLVM.LLVM", Description: "Clang static analyzer and linter for C++"},
		{Name: "cmake", Stack: "cpp", InstallCmd: "winget install Kitware.CMake", Description: "Cross-platform build system generator"},
		{Name: "ninja", Stack: "cpp", InstallCmd: "winget install Ninja-build.Ninja", Description: "Fast build executor"},
	},
	"typescript": {
		{Name: "npx", Stack: "typescript", InstallCmd: "npm install -g npx", Description: "Node package runner"},
		{Name: "eslint", Stack: "typescript", InstallCmd: "npm install -g eslint", Description: "TypeScript/JavaScript linter"},
		{Name: "tsc", Stack: "typescript", InstallCmd: "npm install -g typescript", Description: "TypeScript compiler for type checking"},
	},
	"rust": {
		{Name: "cargo", Stack: "rust", InstallCmd: "rustup default stable", Description: "Rust package manager and build tool"},
	},
	"go": {
		{Name: "go", Stack: "go", InstallCmd: "winget install GoLang.Go", Description: "Go compiler and toolchain"},
		{Name: "gofmt", Stack: "go", InstallCmd: "winget install GoLang.Go", Description: "Go code formatter"},
	},
}
```

- [ ] **Step 4: Update test assertions in `tooling_test.go` and run suite**

Run: `go test ./internal/tooling/...`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add internal/tooling/
git commit -m "feat(tooling): replace csharp tools with clang, cmake and ninja for cpp"
```

---

### Task 3: C++ Test Framework Scanning in CMakeLists.txt

**Files:**
- Create: `internal/detect/cpp_tests.go`
- Test: `internal/detect/cpp_tests_test.go`

**Interfaces:**
- Produces: `DetectCPPTestFramework(root string) string` returning `"gtest"`, `"catch2"`, `"doctest"`, `"boost.test"`, or `""`.

- [ ] **Step 1: Write failing tests for C++ test framework scanner**

```go
package detect_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/xidus90/ultra-loom/internal/detect"
)

func TestDetectCPPTestFramework(t *testing.T) {
	tests := []struct {
		name     string
		content  string
		expected string
	}{
		{
			name:     "Catch2 v3 find_package",
			content:  "cmake_minimum_required(VERSION 3.20)\nfind_package(Catch2 3 REQUIRED)\ntarget_link_libraries(mytest PRIVATE Catch2::Catch2WithMain)",
			expected: "catch2",
		},
		{
			name:     "GoogleTest find_package",
			content:  "cmake_minimum_required(VERSION 3.20)\nfind_package(GTest REQUIRED)\ntarget_link_libraries(mytest PRIVATE GTest::gtest_main)",
			expected: "gtest",
		},
		{
			name:     "doctest find_package",
			content:  "cmake_minimum_required(VERSION 3.20)\nfind_package(doctest REQUIRED)\ntarget_link_libraries(mytest PRIVATE doctest::doctest)",
			expected: "doctest",
		},
		{
			name:     "No test framework",
			content:  "cmake_minimum_required(VERSION 3.20)\nadd_executable(app main.cpp)",
			expected: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dir := t.TempDir()
			if err := os.WriteFile(filepath.Join(dir, "CMakeLists.txt"), []byte(tt.content), 0644); err != nil {
				t.Fatal(err)
			}
			got := detect.DetectCPPTestFramework(dir)
			if got != tt.expected {
				t.Fatalf("expected %q, got %q", tt.expected, got)
			}
		})
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/detect/... -run TestDetectCPPTestFramework`  
Expected: FAIL (function undefined).

- [ ] **Step 3: Implement `internal/detect/cpp_tests.go`**

```go
package detect

import (
	"os"
	"path/filepath"
	"strings"
)

// DetectCPPTestFramework inspects CMakeLists.txt and package files for known test frameworks.
func DetectCPPTestFramework(root string) string {
	cmakePath := filepath.Join(root, "CMakeLists.txt")
	data, err := os.ReadFile(cmakePath)
	if err != nil {
		return ""
	}
	content := string(data)

	// Check Catch2
	if strings.Contains(content, "Catch2") || strings.Contains(content, "catch2") {
		return "catch2"
	}
	// Check GoogleTest
	if strings.Contains(content, "GTest") || strings.Contains(content, "gtest") || strings.Contains(content, "GoogleTest") {
		return "gtest"
	}
	// Check doctest
	if strings.Contains(content, "doctest") {
		return "doctest"
	}
	// Check Boost.Test
	if strings.Contains(content, "unit_test_framework") || strings.Contains(content, "boost::ut") {
		return "boost.test"
	}

	return ""
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/detect/... -run TestDetectCPPTestFramework`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add internal/detect/
git commit -m "feat(detect): add C++ test framework detection for CMakeLists.txt"
```

---

### Task 4: C++ PostToolUse Hooks & Init Pipeline in Go

**Files:**
- Modify: `cmd/init/run.go:810-845`
- Test: `cmd/init/run_test.go`

**Interfaces:**
- Produces: `postEditEntries` generating `clang-format` and `cmake --build` PostToolUse hooks for `cpp` stack.

- [ ] **Step 1: Write failing test in `run_test.go` for C++ PostToolUse hook configuration**

```go
func TestPostEditEntriesCPP(t *testing.T) {
	entries := postEditEntries([]string{"cpp", "cmake"})
	if len(entries) < 2 {
		t.Fatalf("expected at least 2 entries for cpp, got %d", len(entries))
	}
	hasFormat := false
	hasBuild := false
	for _, e := range entries {
		if strings.Contains(e.Command, "clang-format") {
			hasFormat = true
		}
		if strings.Contains(e.Command, "cmake --build") {
			hasBuild = true
		}
	}
	if !hasFormat || !hasBuild {
		t.Fatalf("expected clang-format and cmake --build hooks, got %v", entries)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./cmd/init/... -run TestPostEditEntriesCPP`  
Expected: FAIL

- [ ] **Step 3: Update `cmd/init/run.go` to replace `csharp` hooks with `cpp` hooks**

```go
// In cmd/init/run.go postEditEntries()
if hasStack("cpp") {
	entries = append(entries,
		settings.Entry{Event: "PostToolUse", Matcher: "Write|Edit",
			Command: "clang-format -i", Timeout: 15},
		settings.Entry{Event: "PostToolUse", Matcher: "Write|Edit",
			Command: "cmake --build build --parallel", Timeout: 45},
	)
}
```

- [ ] **Step 4: Update all existing C# tests in `run_test.go` and run tests**

Run: `go test ./cmd/init/...`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cmd/init/
git commit -m "feat(init): replace csharp post-edit hooks with clang-format and cmake build hooks"
```

---

### Task 5: C++ Presets in Python Check Engine

**Files:**
- Modify: `src/ultraloom/checks.py:65-115`
- Test: `tests/test_checks.py`

**Interfaces:**
- Produces: `PRESETS["CMakeLists.txt"]` providing `lint`, `test`, and `coverage` commands.

- [ ] **Step 1: Write failing test in `test_checks.py` for `CMakeLists.txt` preset**

```python
def test_cmake_preset_resolution(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n")
    resolved = resolve_checks(tmp_path, Config.load(tmp_path))
    assert "lint" in resolved
    assert "test" in resolved
    assert resolved["test"].argv == ("ctest", "--test-dir", "build", "--output-on-failure")
    assert resolved["lint"].argv == ("clang-tidy", "-p", "build")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_checks.py -k test_cmake_preset`  
Expected: FAIL

- [ ] **Step 3: Update `PRESETS` in `src/ultraloom/checks.py`**

```python
# In src/ultraloom/checks.py PRESETS dictionary
PRESETS: Mapping[str, Mapping[str, Preset]] = {
    "pyproject.toml": {
        "lint": Preset(("uvx", "ruff", "check", ".", "--output-format=concise")),
        "types": Preset(("uv", "run", "mypy", "--no-error-summary", "--no-pretty")),
        "test": Preset(_PYTEST, measuring=_COVERAGE_RUN),
        "coverage": Preset(
            ("uv", "run", "coverage", "report", "--skip-covered", "--skip-empty", "-m"),
            measure=_COVERAGE_RUN,
            after="test",
        ),
    },
    "CMakeLists.txt": {
        "lint": Preset(("clang-tidy", "-p", "build")),
        "test": Preset(("ctest", "--test-dir", "build", "--output-on-failure")),
        "coverage": Preset(("gcovr", "--cobertura", "coverage.xml")),
    },
    "package.json": {
        "lint": Preset(("eslint", ".")),
        "types": Preset(("tsc", "--noEmit")),
        "test": Preset(("vitest", "run")),
        "coverage": Preset(("vitest", "run", "--coverage")),
    },
    "project.godot": {
        "lint": Preset(("uvx", "gdlint", ".")),
        "test": Preset(("godot", "--headless", "--quit")),
    },
}
```

- [ ] **Step 4: Run Python test suite and coverage**

Run: `uv run pytest tests/test_checks.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ultraloom/checks.py tests/test_checks.py
git commit -m "feat(checks): add CMakeLists.txt presets for ctest, clang-tidy and gcovr"
```

---

### Task 6: Worktree E2E Integration & Verification Gate

**Files:**
- Test: Isolated Git Worktree validation

- [ ] **Step 1: Create isolated worktree**

Run: `git worktree add .worktrees/cpp-stack-verify -b feat/cpp-stack-verify`

- [ ] **Step 2: Build `ulinit` binary and run in test C++ workspace**

```bash
go build -o .worktrees/cpp-stack-verify/ulinit.exe ./cmd/init
cd .worktrees/cpp-stack-verify
```

- [ ] **Step 3: Initialize sample C++ CMake repository**

Create `CMakeLists.txt`, run `./ulinit.exe --yes`, and inspect `.claude/settings.json` and `.ultraloom/config.toml`.

- [ ] **Step 4: Execute quality check loop**

Run: `uv run ultraloom check all` and `go test ./...` in the workspace. Verify 100% green exit codes.

- [ ] **Step 5: Clean up verification worktree and merge**

```bash
git worktree remove .worktrees/cpp-stack-verify --force
git branch -D feat/cpp-stack-verify
```
