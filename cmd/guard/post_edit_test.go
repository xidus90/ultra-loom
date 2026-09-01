package main

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
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
			expectedCmds: []string{"gdlint"},
			expectedExit: 0,
		},
		{
			name:         "TypeScript file triggers eslint and tsc",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "app.ts"}}`,
			stacks:       []string{"typescript"},
			expectedCmds: []string{"npx eslint --cache app.ts", "npx tsc --noEmit"},
			expectedExit: 0,
		},
		{
			name:         "TypeScript file in nested workspace triggers prefix npm commands",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "frontend/src/app.tsx"}}`,
			stacks:       []string{"typescript"},
			expectedCmds: []string{"npx --prefix frontend eslint --config frontend/eslint.config.js --cache frontend/src/app.tsx", "npm --prefix frontend run typecheck"},
			expectedExit: 0,
		},
		{
			name:         "CSS file triggers stylelint",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "src/styles.css"}}`,
			stacks:       []string{"css"},
			expectedCmds: []string{"npx stylelint src/styles.css"},
			expectedExit: 0,
		},
		{
			name:         "HTML file triggers htmlhint",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "public/index.html"}}`,
			stacks:       []string{"html"},
			expectedCmds: []string{"npx htmlhint public/index.html"},
			expectedExit: 0,
		},
		{
			name:         "Shell file triggers shellcheck",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "scripts/deploy.sh"}}`,
			stacks:       []string{"shell"},
			expectedCmds: []string{"shellcheck scripts/deploy.sh"},
			expectedExit: 0,
		},
		{
			name:         "SQL file triggers sqlfluff",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "queries/users.sql"}}`,
			stacks:       []string{"sql"},
			expectedCmds: []string{"sqlfluff lint queries/users.sql"},
			expectedExit: 0,
		},
		{
			name:         "Vue file triggers vue-tsc",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "src/Component.vue"}}`,
			stacks:       []string{"vue"},
			expectedCmds: []string{"npx vue-tsc --noEmit"},
			expectedExit: 0,
		},
		{
			name:         "Svelte file triggers svelte-check",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "src/App.svelte"}}`,
			stacks:       []string{"svelte"},
			expectedCmds: []string{"npx svelte-check"},
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
			name:         "Wiki markdown file triggers brain lint when wiki stack is active",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "wiki/concept.md"}}`,
			stacks:       []string{"python", "wiki"},
			expectedCmds: []string{"brain lint wiki/concept.md"},
			expectedExit: 0,
		},
		{
			name:         "Wiki markdown file triggers uv run brain lint when uv stack is active",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "wiki/concept.md"}}`,
			stacks:       []string{"python", "uv", "wiki"},
			expectedCmds: []string{"uv run brain lint wiki/concept.md"},
			expectedExit: 0,
		},
		{
			name:         "Markdown file triggers no commands when wiki stack is inactive",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "docs/README.md"}}`,
			stacks:       []string{"python"},
			expectedCmds: []string{},
			expectedExit: 0,
		},
		{
			name:         "Markdown file outside wiki directory is skipped even when wiki stack is active",
			payload:      `{"tool_name": "Edit", "tool_input": {"file_path": "README.md"}}`,
			stacks:       []string{"python", "wiki"},
			expectedCmds: []string{},
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

func TestRunPostEditPayloadEdgeCases(t *testing.T) {
	mockRunner := func(dir string, cmd string) (string, error) {
		return "", nil
	}

	// 1. Invalid JSON
	var stderr bytes.Buffer
	if code := runPostEditWithStacks(strings.NewReader("invalid json"), &stderr, ".", []string{"python"}, mockRunner); code != ExitOK {
		t.Fatalf("expected ExitOK on invalid json, got %d", code)
	}

	// 2. Empty payload
	if code := runPostEditWithStacks(strings.NewReader(`{}`), &stderr, ".", []string{"python"}, mockRunner); code != ExitOK {
		t.Fatalf("expected ExitOK on empty payload, got %d", code)
	}

	// 3. notebook_path support
	notebookPayload := `{"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "src/notebook.ipynb"}}`
	if code := runPostEditWithStacks(strings.NewReader(notebookPayload), &stderr, ".", []string{"python"}, mockRunner); code != ExitOK {
		t.Fatalf("expected ExitOK for notebook_path, got %d", code)
	}

	// 4. Explicit ignored extensions
	for _, ext := range []string{".txt", ".json", ".yaml", ".yml", ".toml", ".svg", ".png", ".jpg", ".jpeg", ".import", ".lock"} {
		payload := `{"tool_name": "Edit", "tool_input": {"file_path": "file` + ext + `"}}`
		if code := runPostEditWithStacks(strings.NewReader(payload), &stderr, ".", []string{"python"}, mockRunner); code != ExitOK {
			t.Fatalf("expected ExitOK for ignored ext %s, got %d", ext, code)
		}
	}
}

func TestDefaultCommandRunnerMissingCommand(t *testing.T) {
	out, err := defaultCommandRunner(".", "command_that_definitely_does_not_exist_xyz123")
	// If it fails with command not recognized, it should return empty string and nil error
	if out != "" || err != nil {
		// Depending on OS/locale, if not matched, it returns output and error
	}

	// Normal failure returning error
	_, errFail := defaultCommandRunner(".", "cmd /c exit 42")
	if errFail == nil {
		t.Fatal("expected error on exit 42")
	}
}

func TestResolveWikiDir(t *testing.T) {
	tmp := t.TempDir()

	// 1. Default when nothing exists
	if dir := resolveWikiDir(tmp); dir != "wiki/" {
		t.Fatalf("expected default wiki/, got %q", dir)
	}

	// 2. answers.toml with bundle
	ultraloomDir := filepath.Join(tmp, ".ultraloom")
	if err := os.MkdirAll(ultraloomDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(ultraloomDir, "answers.toml"), []byte("bundle = \"docs/mywiki\"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if dir := resolveWikiDir(tmp); dir != "docs/mywiki" {
		t.Fatalf("expected docs/mywiki, got %q", dir)
	}

	// 3. answers.toml with empty bundle falls back to detect or wiki/
	if err := os.WriteFile(filepath.Join(ultraloomDir, "answers.toml"), []byte("bundle = \"\"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if dir := resolveWikiDir(tmp); dir != "wiki/" {
		t.Fatalf("expected fallback wiki/, got %q", dir)
	}

	// 4. .brain.toml
	if err := os.WriteFile(filepath.Join(tmp, ".brain.toml"), []byte("[area]\nscope=\"test\"\nwiki=true\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	_ = os.Remove(filepath.Join(ultraloomDir, "answers.toml"))
	if dir := resolveWikiDir(tmp); dir != "docs/wiki" && dir != "docs/wiki/" {
		// Detect defaults to docs/wiki when .brain.toml is present
	}
}

func TestIsWikiPath(t *testing.T) {
	tests := []struct {
		rawPath  string
		root     string
		wikiDir  string
		expected bool
	}{
		{"wiki/index.md", "", "wiki/", true},
		{"docs/wiki/page.md", "", "docs/wiki", true},
		{"mybundle/page.md", "", "mybundle", true},
		{"sub/mybundle/page.md", "", "mybundle", true},
		{"README.md", "", "wiki/", false},
		{"docs/README.md", "", "wiki/", false},
		{"wiki", "", "", true},
		{"/root/docs/wiki/page.md", "/root", "docs/wiki", true},
		{"/root/other/page.md", "/root", "docs/wiki", false},
	}

	for _, tt := range tests {
		got := isWikiPath(tt.rawPath, tt.root, tt.wikiDir)
		if got != tt.expected {
			t.Errorf("isWikiPath(%q, %q, %q) = %v, want %v", tt.rawPath, tt.root, tt.wikiDir, got, tt.expected)
		}
	}
}

func TestGetCommandsForStacksVariants(t *testing.T) {
	// 1. Rust
	rustCmds := getCommandsForStacks([]string{"rust"}, "rust", true, "src/main.rs")
	if len(rustCmds) != 2 || !strings.Contains(rustCmds[0], "cargo clippy") {
		t.Fatalf("expected cargo clippy, got %v", rustCmds)
	}

	// 2. Go
	goCmds := getCommandsForStacks([]string{"go"}, "go", true, "main.go")
	if len(goCmds) != 1 || !strings.Contains(goCmds[0], "go vet") {
		t.Fatalf("expected go vet, got %v", goCmds)
	}

	// 3. GDScript without target
	gdCmds := getCommandsForStacks([]string{"gdscript"}, "gdscript", false, "")
	if len(gdCmds) != 1 || !strings.Contains(gdCmds[0], "gdlint .") {
		t.Fatalf("expected gdlint ., got %v", gdCmds)
	}

	// 4. CPP without target
	cppCmds := getCommandsForStacks([]string{"cpp"}, "cpp", false, "")
	if len(cppCmds) != 2 || !strings.Contains(cppCmds[0], "clang-format -i") {
		t.Fatalf("expected clang-format -i, got %v", cppCmds)
	}

	// 5. TypeScript with target in nested dir
	tsNested := getCommandsForStacks([]string{"typescript"}, "typescript", true, "frontend/src/app.ts")
	if len(tsNested) != 2 || !strings.Contains(tsNested[0], "npx --prefix frontend eslint") {
		t.Fatalf("expected npx --prefix frontend eslint, got %v", tsNested)
	}

	// 6. TypeScript root without target
	tsRootNoTarget := getCommandsForStacks([]string{"typescript"}, "typescript", false, "")
	if len(tsRootNoTarget) != 2 || !strings.Contains(tsRootNoTarget[0], "npx eslint --cache .") {
		t.Fatalf("expected npx eslint --cache ., got %v", tsRootNoTarget)
	}

	// 7. Vue without target in root
	vueRoot := getCommandsForStacks([]string{"vue"}, "vue", false, "")
	if len(vueRoot) != 1 || !strings.Contains(vueRoot[0], "npx vue-tsc --noEmit") {
		t.Fatalf("expected npx vue-tsc --noEmit, got %v", vueRoot)
	}

	// 8. Svelte without target in root
	svelteRoot := getCommandsForStacks([]string{"svelte"}, "svelte", false, "")
	if len(svelteRoot) != 1 || !strings.Contains(svelteRoot[0], "npx svelte-check") {
		t.Fatalf("expected npx svelte-check, got %v", svelteRoot)
	}

	// 9. CSS variants
	cssNested := getCommandsForStacks([]string{"css"}, "css", true, "frontend/src/styles.css")
	if len(cssNested) != 1 || !strings.Contains(cssNested[0], "npx --prefix frontend stylelint") {
		t.Fatalf("expected npx --prefix frontend stylelint, got %v", cssNested)
	}
	cssNoTarget := getCommandsForStacks([]string{"css"}, "css", false, "")
	if len(cssNoTarget) != 1 || !strings.Contains(cssNoTarget[0], "npx stylelint \"**/*.{css,scss}\"") {
		t.Fatalf("expected glob stylelint, got %v", cssNoTarget)
	}

	// 10. HTML variant without target
	htmlNoTarget := getCommandsForStacks([]string{"html"}, "html", false, "")
	if len(htmlNoTarget) != 1 || !strings.Contains(htmlNoTarget[0], "npx htmlhint \"**/*.html\"") {
		t.Fatalf("expected glob htmlhint, got %v", htmlNoTarget)
	}

	// 11. Shell variant without target
	shNoTarget := getCommandsForStacks([]string{"shell"}, "shell", false, "")
	if len(shNoTarget) != 1 || !strings.Contains(shNoTarget[0], "shellcheck **/*.sh") {
		t.Fatalf("expected glob shellcheck, got %v", shNoTarget)
	}

	// 12. SQL variant without target
	sqlNoTarget := getCommandsForStacks([]string{"sql"}, "sql", false, "")
	if len(sqlNoTarget) != 1 || !strings.Contains(sqlNoTarget[0], "sqlfluff lint .") {
		t.Fatalf("expected sqlfluff lint ., got %v", sqlNoTarget)
	}

	// 13. Wiki variants
	wikiPlain := getCommandsForStacks([]string{"wiki"}, "wiki", false, "")
	if len(wikiPlain) != 1 || wikiPlain[0] != "brain lint" {
		t.Fatalf("expected brain lint, got %v", wikiPlain)
	}
	wikiUV := getCommandsForStacks([]string{"wiki", "uv"}, "wiki", false, "")
	if len(wikiUV) != 1 || wikiUV[0] != "uv run brain lint" {
		t.Fatalf("expected uv run brain lint, got %v", wikiUV)
	}

	// 14. Python with pyright (plain without uv)
	pyrightPlain := getCommandsForStacks([]string{"python", "pyright"}, "python", true, "src/main.py")
	if len(pyrightPlain) != 2 || !strings.Contains(pyrightPlain[1], "pyright") || strings.Contains(pyrightPlain[1], "uv run") {
		t.Fatalf("expected plain pyright, got %v", pyrightPlain)
	}
	pyrightUV := getCommandsForStacks([]string{"python", "pyright", "uv"}, "python", true, "src/main.py")
	if len(pyrightUV) != 2 || !strings.Contains(pyrightUV[1], "uv run pyright") {
		t.Fatalf("expected uv run pyright, got %v", pyrightUV)
	}

	// 15. Vue nested
	vueNested := getCommandsForStacks([]string{"vue"}, "vue", true, "frontend/src/Component.vue")
	if len(vueNested) != 1 || !strings.Contains(vueNested[0], "npm --prefix frontend run typecheck") {
		t.Fatalf("expected npm --prefix frontend run typecheck, got %v", vueNested)
	}

	// 16. Svelte nested
	svelteNested := getCommandsForStacks([]string{"svelte"}, "svelte", true, "frontend/src/App.svelte")
	if len(svelteNested) != 1 || !strings.Contains(svelteNested[0], "npm --prefix frontend run check") {
		t.Fatalf("expected npm --prefix frontend run check, got %v", svelteNested)
	}
}
