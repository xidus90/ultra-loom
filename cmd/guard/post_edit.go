package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"

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
	".md":  "wiki",
}

func runPostEdit(stdin io.Reader, stderr io.Writer, root string) int {
	facts := detect.Detect(os.DirFS(root))
	wikiDir := facts.WikiPath
	if wikiDir == "" {
		wikiDir = resolveWikiDir(root)
	}
	return runPostEditWithContext(stdin, stderr, root, facts.Stacks, wikiDir, defaultCommandRunner)
}

func runPostEditWithStacks(stdin io.Reader, stderr io.Writer, root string, stacks []string, runner CommandRunner) int {
	return runPostEditWithContext(stdin, stderr, root, stacks, "wiki/", runner)
}

func runPostEditWithContext(stdin io.Reader, stderr io.Writer, root string, stacks []string, wikiDir string, runner CommandRunner) int {
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
	if targetStack == "wiki" && !isWikiPath(rawPath, root, wikiDir) {
		return ExitOK
	}
	commands := getCommandsForStacks(stacks, targetStack, hasTarget, rawPath)

	var wg sync.WaitGroup
	var mu sync.Mutex
	hasFailure := false

	for _, cmd := range commands {
		wg.Add(1)
		go func(c string) {
			defer wg.Done()
			out, err := runner(root, c)
			if err != nil {
				mu.Lock()
				defer mu.Unlock()
				hasFailure = true
				io.WriteString(stderr, out)
				if out == "" {
					io.WriteString(stderr, err.Error()+"\n")
				}
			}
		}(cmd)
	}
	wg.Wait()

	if hasFailure {
		return ExitDenied
	}
	return ExitOK
}

func getCommandsForStacks(stacks []string, targetStack string, hasTarget bool, targetPath string) []string {
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
		if hasTarget && targetPath != "" {
			cmds = append(cmds, fmt.Sprintf("gdlint %s", targetPath))
		} else {
			cmds = append(cmds, "gdlint .")
		}
	}
	if shouldRun("cpp") {
		if hasTarget && targetPath != "" {
			cmds = append(cmds, fmt.Sprintf("clang-format -i %s", targetPath), "cmake --build build --parallel")
		} else {
			cmds = append(cmds, "clang-format -i", "cmake --build build --parallel")
		}
	}
	if shouldRun("typescript") {
		targetDir := ""
		if hasTarget && targetPath != "" {
			norm := strings.TrimPrefix(filepath.ToSlash(targetPath), "./")
			parts := strings.Split(norm, "/")
			if len(parts) > 1 && parts[0] != "." && parts[0] != "" {
				targetDir = parts[0]
			}
		}
		if targetDir != "" {
			cmds = append(cmds,
				fmt.Sprintf("npm --prefix %s run lint", targetDir),
				fmt.Sprintf("npm --prefix %s run typecheck", targetDir),
			)
		} else {
			cmds = append(cmds, "npx eslint .", "npx tsc --noEmit")
		}
	}
	if shouldRun("rust") {
		cmds = append(cmds, "cargo clippy -- -D warnings", "cargo fmt --check")
	}
	if shouldRun("go") {
		cmds = append(cmds, "go vet ./...")
	}
	if shouldRun("wiki") {
		prefix := "brain lint"
		if has("uv") {
			prefix = "uv run brain lint"
		}
		if hasTarget && targetPath != "" {
			cmds = append(cmds, fmt.Sprintf("%s %s", prefix, targetPath))
		} else {
			cmds = append(cmds, prefix)
		}
	}

	return cmds
}

func resolveWikiDir(root string) string {
	if data, err := os.ReadFile(filepath.Join(root, ".ultraloom", "answers.toml")); err == nil {
		lines := strings.Split(string(data), "\n")
		for _, line := range lines {
			trimmed := strings.TrimSpace(line)
			if strings.HasPrefix(trimmed, "bundle") && strings.Contains(trimmed, "=") {
				parts := strings.SplitN(trimmed, "=", 2)
				val := strings.Trim(strings.TrimSpace(parts[1]), "\"'")
				if val != "" {
					return filepath.ToSlash(val)
				}
			}
		}
	}
	facts := detect.Detect(os.DirFS(root))
	if facts.WikiPath != "" {
		return filepath.ToSlash(facts.WikiPath)
	}
	return "wiki/"
}

func isWikiPath(rawPath, root, configuredWikiDir string) bool {
	wikiDir := strings.TrimSuffix(filepath.ToSlash(configuredWikiDir), "/")
	if wikiDir == "" {
		wikiDir = "wiki"
	}

	norm := strings.TrimPrefix(filepath.ToSlash(rawPath), "./")

	if strings.HasPrefix(norm, wikiDir+"/") || norm == wikiDir ||
		strings.Contains(norm, "/"+wikiDir+"/") ||
		strings.HasPrefix(norm, "docs/wiki/") || strings.HasPrefix(norm, "wiki/") {
		return true
	}

	if root != "" {
		rel, err := filepath.Rel(root, rawPath)
		if err == nil {
			relNorm := strings.TrimPrefix(filepath.ToSlash(rel), "./")
			if strings.HasPrefix(relNorm, wikiDir+"/") || relNorm == wikiDir ||
				strings.Contains(relNorm, "/"+wikiDir+"/") ||
				strings.HasPrefix(relNorm, "docs/wiki/") || strings.HasPrefix(relNorm, "wiki/") {
				return true
			}
		}
	}
	return false
}
