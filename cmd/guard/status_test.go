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
