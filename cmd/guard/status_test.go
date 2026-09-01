package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRunStatus(t *testing.T) {
	tmp := t.TempDir()

	// 1. Create a dummy python + wiki project
	if err := os.WriteFile(filepath.Join(tmp, "pyproject.toml"), []byte("[project]\nname=\"test\"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(tmp, "uv.lock"), []byte(""), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(tmp, ".brain.toml"), []byte("[area]\nscope=\"test\"\nwiki=true\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(tmp, ".claude"), 0o755); err != nil {
		t.Fatal(err)
	}
	settingsJSON := `{
		"hooks": {
			"PreToolUse": [{"hooks": [{"command": "ulguard"}]}],
			"PostToolUse": [{"hooks": [{"command": "ulguard post-edit"}, {"command": "python format_on_edit.py"}]}]
		}
	}`
	if err := os.WriteFile(filepath.Join(tmp, ".claude", "settings.json"), []byte(settingsJSON), 0o644); err != nil {
		t.Fatal(err)
	}

	var stdout, stderr bytes.Buffer
	code := runStatus(&stdout, &stderr, tmp)
	if code != ExitOK {
		t.Fatalf("expected ExitOK (0), got %d", code)
	}

	out := stdout.String()
	if !strings.Contains(out, "UltraLoom Guard & Hook Inspection") {
		t.Fatalf("expected header, got %s", out)
	}
	if !strings.Contains(out, "ruff check") {
		t.Fatalf("expected ruff check in output, got %s", out)
	}
	if !strings.Contains(out, "brain lint") {
		t.Fatalf("expected brain lint in output, got %s", out)
	}
	if !strings.Contains(out, "format_on_edit.py") {
		t.Fatalf("expected legacy finding for format_on_edit.py, got %s", out)
	}
}

func TestRunStatusAllStacksAndNoLegacy(t *testing.T) {
	tmp := t.TempDir()

	// Add files for all stacks
	files := map[string]string{
		"project.godot":      "",
		"CMakeLists.txt":     "cmake_minimum_required(VERSION 3.20)",
		"tsconfig.json":      "{}",
		"package.json":       "{}",
		"App.vue":            "<template></template>",
		"App.svelte":         "<script></script>",
		"style.css":          "body {}",
		"index.html":         "<html></html>",
		"script.sh":          "#!/bin/sh",
		".sqlfluff":          "[sqlfluff]\ndialect = ansi\n",
		"query.sql":          "SELECT 1;",
		"Cargo.toml":         "[package]\nname=\"sample\"\nversion=\"0.1.0\"\n",
		"go.mod":             "module sample\ngo 1.24\n",
		".golangci.yml":      "",
		"pyrightconfig.json": "{}",
		"requirements.txt":   "pytest",
	}
	for name, content := range files {
		if err := os.WriteFile(filepath.Join(tmp, name), []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}

	// Clean settings without legacy hooks and with no Pre/Post
	if err := os.MkdirAll(filepath.Join(tmp, ".claude"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(tmp, ".claude", "settings.json"), []byte(`{"hooks":{}}`), 0o644); err != nil {
		t.Fatal(err)
	}

	var stdout, stderr bytes.Buffer
	code := runStatus(&stdout, &stderr, tmp)
	if code != ExitOK {
		t.Fatalf("expected ExitOK, got %d", code)
	}

	out := stdout.String()
	for _, expected := range []string{
		"gdlint",
		"clang-format",
		"npx eslint",
		"npx vue-tsc",
		"npx svelte-check",
		"npx stylelint",
		"npx htmlhint",
		"shellcheck",
		"sqlfluff",
		"cargo clippy",
		"go vet",
		"golangci-lint",
		"pyright",
		"No obsolete or redundant legacy hooks found",
		"UltraBrain Wiki: Inactive / Disabled",
	} {
		if !strings.Contains(out, expected) {
			t.Fatalf("expected output to contain %q, but got:\n%s", expected, out)
		}
	}
}

func TestAuditSettingsEdgeCases(t *testing.T) {
	tmp := t.TempDir()

	// 1. Missing settings file
	findings, pre, post := auditSettings(tmp)
	if len(findings) != 0 || pre || post {
		t.Fatalf("expected empty for missing settings, got findings=%v pre=%v post=%v", findings, pre, post)
	}

	// 2. Invalid JSON in settings file
	claudeDir := filepath.Join(tmp, ".claude")
	_ = os.MkdirAll(claudeDir, 0o755)
	_ = os.WriteFile(filepath.Join(claudeDir, "settings.json"), []byte("invalid json"), 0o644)
	findings, pre, post = auditSettings(tmp)
	if len(findings) != 0 || pre || post {
		t.Fatalf("expected empty for invalid json, got findings=%v pre=%v post=%v", findings, pre, post)
	}

	// 3. All legacy hooks in settings
	allLegacyJSON := `{
		"hooks": {
			"PreToolUse": [
				{"hooks": [{"command": "python guard_paths.py"}]}
			],
			"PostToolUse": [
				{"hooks": [{"command": "python post_edit.py"}, {"command": "python generate_index.py"}, {"command": "python lint.py"}]}
			],
			"Stop": [
				{"hooks": [{"command": "python wiki_gate.py"}]}
			]
		}
	}`
	_ = os.WriteFile(filepath.Join(claudeDir, "settings.json"), []byte(allLegacyJSON), 0o644)
	findings, pre, post = auditSettings(tmp)
	if len(findings) != 5 {
		t.Fatalf("expected 5 legacy findings, got %d", len(findings))
	}
	if pre || post {
		t.Fatalf("expected pre/post false, got pre=%v post=%v", pre, post)
	}
}

func TestRunStatusPlainPythonAndGo(t *testing.T) {
	tmp := t.TempDir()

	// Only requirements.txt (plain python) and go.mod (plain go)
	_ = os.WriteFile(filepath.Join(tmp, "requirements.txt"), []byte("requests"), 0o644)
	_ = os.WriteFile(filepath.Join(tmp, "go.mod"), []byte("module sample\ngo 1.24\n"), 0o644)

	// Settings with only PreToolUse
	claudeDir := filepath.Join(tmp, ".claude")
	_ = os.MkdirAll(claudeDir, 0o755)
	_ = os.WriteFile(filepath.Join(claudeDir, "settings.json"), []byte(`{"hooks":{"PreToolUse":[{"hooks":[{"command":"ulguard"}]}]}}`), 0o644)

	var stdout, stderr bytes.Buffer
	code := runStatus(&stdout, &stderr, tmp)
	if code != ExitOK {
		t.Fatalf("expected ExitOK, got %d", code)
	}

	out := stdout.String()
	if !strings.Contains(out, "mypy --no-error-summary --no-pretty") {
		t.Fatalf("expected plain mypy output, got:\n%s", out)
	}
	if !strings.Contains(out, "go vet ./...") {
		t.Fatalf("expected plain go vet output, got:\n%s", out)
	}
	if !strings.Contains(out, "[OK] PreToolUse:  'ulguard' installed") {
		t.Fatalf("expected pre installed, got:\n%s", out)
	}
	if !strings.Contains(out, "[INFO] PostToolUse: 'ulguard post-edit' not found") {
		t.Fatalf("expected post not found, got:\n%s", out)
	}
}

func TestRunStatusPyrightWithUV(t *testing.T) {
	tmp := t.TempDir()
	_ = os.WriteFile(filepath.Join(tmp, "pyproject.toml"), []byte("[project]\nname=\"p\"\n[tool.pyright]\n"), 0o644)
	_ = os.WriteFile(filepath.Join(tmp, "uv.lock"), []byte(""), 0o644)

	var stdout, stderr bytes.Buffer
	code := runStatus(&stdout, &stderr, tmp)
	if code != ExitOK {
		t.Fatalf("expected ExitOK, got %d", code)
	}
	out := stdout.String()
	if !strings.Contains(out, "uv run pyright") {
		t.Fatalf("expected uv run pyright in status output, got:\n%s", out)
	}
}
