// Package tooling discovers, checks, and installs CLI tools required by detected stacks.
package tooling

import (
	"fmt"
	"os/exec"
	"strings"
)

type ToolSpec struct {
	Name       string
	Stack      string
	InstallCmd string
}

var StackTools = map[string][]ToolSpec{
	"python": {
		{Name: "uv", Stack: "python", InstallCmd: "curl -LsSf https://astral.sh/uv/install.sh | sh"},
		{Name: "ruff", Stack: "python", InstallCmd: "uv tool install ruff"},
		{Name: "dmypy", Stack: "python", InstallCmd: "uv tool install mypy"},
	},
	"gdscript": {
		{Name: "gdlint", Stack: "gdscript", InstallCmd: "uv tool install gdtoolkit==4.3.3"},
	},
	"cpp": {
		{Name: "clang-format", Stack: "cpp", InstallCmd: "winget install LLVM.LLVM"},
		{Name: "clang-tidy", Stack: "cpp", InstallCmd: "winget install LLVM.LLVM"},
		{Name: "cmake", Stack: "cpp", InstallCmd: "winget install Kitware.CMake"},
		{Name: "ninja", Stack: "cpp", InstallCmd: "winget install Ninja-build.Ninja"},
	},
	"typescript": {
		{Name: "npx", Stack: "typescript", InstallCmd: "npm install -g npx"},
		{Name: "eslint", Stack: "typescript", InstallCmd: "npm install -g eslint"},
		{Name: "tsc", Stack: "typescript", InstallCmd: "npm install -g typescript"},
	},
	"rust": {
		{Name: "cargo", Stack: "rust", InstallCmd: "rustup default stable"},
	},
	"go": {
		{Name: "go", Stack: "go", InstallCmd: "winget install GoLang.Go"},
		{Name: "gofmt", Stack: "go", InstallCmd: "winget install GoLang.Go"},
	},
}

// LookPathFunc abstracts os/exec.LookPath for deterministic testing.
type LookPathFunc func(file string) (string, error)

func DefaultLookPath(file string) (string, error) {
	return exec.LookPath(file)
}

// CheckTools inspects which tools for the given stacks are found on PATH.
func CheckTools(stacks []string, lookup LookPathFunc) (found map[string]string, missing []ToolSpec) {
	if lookup == nil {
		lookup = DefaultLookPath
	}
	found = make(map[string]string)
	seen := make(map[string]bool)

	for _, stack := range stacks {
		tools, ok := StackTools[stack]
		if !ok {
			continue
		}
		for _, tool := range tools {
			if seen[tool.Name] {
				continue
			}
			seen[tool.Name] = true
			path, err := lookup(tool.Name)
			if err == nil && path != "" {
				found[tool.Name] = path
			} else {
				missing = append(missing, tool)
			}
		}
	}
	return found, missing
}

// Runner executes commands in a directory.
type Runner func(dir string, argv ...string) (string, error)

// InstallTool runs the tool's installation command using the provided runner.
func InstallTool(spec ToolSpec, run Runner, dir string) error {
	if spec.InstallCmd == "" {
		return fmt.Errorf("no installation command defined for %s", spec.Name)
	}
	parts := strings.Fields(spec.InstallCmd)
	if len(parts) == 0 {
		return fmt.Errorf("empty installation command for %s", spec.Name)
	}
	_, err := run(dir, parts...)
	if err != nil {
		return fmt.Errorf("installing %s via %q: %w", spec.Name, spec.InstallCmd, err)
	}
	return nil
}
