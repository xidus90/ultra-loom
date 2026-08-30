package main

import (
	"encoding/json"
	"io"
	"os"
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
	".py":  "python",
	".gd":  "gdscript",
	".cpp": "cpp",
	".hpp": "cpp",
	".cc":  "cpp",
	".cxx": "cpp",
	".c":   "cpp",
	".h":   "cpp",
	".ts":  "typescript",
	".tsx": "typescript",
	".js":  "typescript",
	".jsx": "typescript",
	".go":  "go",
	".rs":  "rust",
}

func runPostEdit(stdin io.Reader, stderr io.Writer, root string) int {
	facts := detect.Detect(os.DirFS(root))
	return runPostEditWithStacks(stdin, stderr, root, facts.Stacks, defaultCommandRunner)
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
