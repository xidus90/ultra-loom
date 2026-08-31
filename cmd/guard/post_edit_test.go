package main

import (
	"bytes"
	"errors"
	"strings"
	"sync"
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
			name:         "Python plain without uv triggers mypy",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "src/main.py"}}`,
			stacks:       []string{"python"},
			expectedCmds: []string{"ruff check", "mypy"},
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
			name:         "GDScript file triggers only gdlint",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "player.gd"}}`,
			stacks:       []string{"gdscript", "cpp"},
			expectedCmds: []string{"gdlint ."},
			expectedExit: 0,
		},
		{
			name:         "TypeScript file triggers eslint and tsc",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "app.ts"}}`,
			stacks:       []string{"typescript"},
			expectedCmds: []string{"npx eslint .", "npx tsc --noEmit"},
			expectedExit: 0,
		},
		{
			name:         "Rust file triggers clippy and fmt",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "src/lib.rs"}}`,
			stacks:       []string{"rust"},
			expectedCmds: []string{"cargo clippy", "cargo fmt"},
			expectedExit: 0,
		},
		{
			name:         "Go file triggers go vet",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "cmd/main.go"}}`,
			stacks:       []string{"go"},
			expectedCmds: []string{"go vet ./..."},
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
			stacks:       []string{"python", "uv", "cpp"},
			expectedCmds: []string{"ruff check", "dmypy run", "clang-format -i", "cmake --build"},
			expectedExit: 0,
		},
		{
			name:         "NotebookEdit with notebook_path",
			payload:      `{"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "analysis.py"}}`,
			stacks:       []string{"python"},
			expectedCmds: []string{"ruff check"},
			expectedExit: 0,
		},
		{
			name:         "Invalid json exits 0",
			payload:      `invalid json`,
			stacks:       []string{"python"},
			expectedCmds: nil,
			expectedExit: 0,
		},
		{
			name:         "Empty path exits 0",
			payload:      `{"tool_name": "Edit", "tool_input": {}}`,
			stacks:       []string{"python"},
			expectedCmds: nil,
			expectedExit: 0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var ranCmds []string
			var mu sync.Mutex
			mockRunner := func(dir string, cmd string) (string, error) {
				mu.Lock()
				defer mu.Unlock()
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

func TestRunPostEditFailure(t *testing.T) {
	payload := `{"tool_name": "Edit", "tool_input": {"file_path": "src/main.py"}}`
	mockFailRunner := func(dir string, cmd string) (string, error) {
		return "syntax error in file\n", errors.New("exit 1")
	}

	var stderr bytes.Buffer
	exitCode := runPostEditWithStacks(strings.NewReader(payload), &stderr, ".", []string{"python"}, mockFailRunner)
	if exitCode != ExitDenied {
		t.Fatalf("expected ExitDenied (2), got %d", exitCode)
	}
	if !strings.Contains(stderr.String(), "syntax error") {
		t.Fatalf("expected stderr output, got %q", stderr.String())
	}

	// Failure with empty out string
	mockEmptyFail := func(dir string, cmd string) (string, error) {
		return "", errors.New("generic error")
	}
	var stderr2 bytes.Buffer
	exitCode2 := runPostEditWithStacks(strings.NewReader(payload), &stderr2, ".", []string{"python"}, mockEmptyFail)
	if exitCode2 != ExitDenied {
		t.Fatalf("expected ExitDenied (2), got %d", exitCode2)
	}
}

func TestDefaultCommandRunner(t *testing.T) {
	out, err := defaultCommandRunner(".", "echo test_runner")
	if err != nil {
		t.Fatalf("expected nil error, got %v", err)
	}
	if !strings.Contains(out, "test_runner") {
		t.Fatalf("expected output with test_runner, got %q", out)
	}
}

func TestRunPostEditReal(t *testing.T) {
	payload := `{"tool_name": "Edit", "tool_input": {"file_path": "README.md"}}`
	var stderr bytes.Buffer
	code := runPostEdit(strings.NewReader(payload), &stderr, ".")
	if code != ExitOK {
		t.Fatalf("expected ExitOK for markdown file, got %d", code)
	}
}
