package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCheckSubcommands(t *testing.T) {
	t.Run("Usage on empty args", func(t *testing.T) {
		stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
		code := cli([]string{"check"}, nil, stdout, stderr)
		if code != 1 {
			t.Fatalf("expected exit code 1, got %d", code)
		}
		if !strings.Contains(stderr.String(), "usage: ulinit check") {
			t.Fatalf("expected usage message, got %s", stderr.String())
		}
	})

	t.Run("Unknown subcommand", func(t *testing.T) {
		stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
		code := cli([]string{"check", "unknown"}, nil, stdout, stderr)
		if code != 1 {
			t.Fatalf("expected exit code 1, got %d", code)
		}
		if !strings.Contains(stderr.String(), "unknown check subcommand") {
			t.Fatalf("expected unknown subcommand error, got %s", stderr.String())
		}
	})

	t.Run("Check commit-msg valid and invalid", func(t *testing.T) {
		tmpDir := t.TempDir()

		// Missing arg
		stderr := &bytes.Buffer{}
		if code := cli([]string{"check", "commit-msg"}, nil, &bytes.Buffer{}, stderr); code != 1 {
			t.Fatalf("expected code 1 on missing file, got %d", code)
		}

		// Non-existent file
		stderr.Reset()
		if code := cli([]string{"check", "commit-msg", filepath.Join(tmpDir, "missing.txt")}, nil, &bytes.Buffer{}, stderr); code != 1 {
			t.Fatalf("expected code 1 on nonexistent file, got %d", code)
		}

		// Valid English message
		validFile := filepath.Join(tmpDir, "valid.txt")
		os.WriteFile(validFile, []byte("feat(init): wire commit-msg language gate in ulinit\n"), 0644)
		if code := cli([]string{"check", "commit-msg", validFile}, nil, &bytes.Buffer{}, &bytes.Buffer{}); code != 0 {
			t.Fatalf("expected code 0 for valid commit message, got %d", code)
		}

		// Invalid German message
		invalidFile := filepath.Join(tmpDir, "invalid.txt")
		os.WriteFile(invalidFile, []byte("feat: füge neue sprachprüfung hinzu\n"), 0644)
		stderr.Reset()
		if code := cli([]string{"check", "commit-msg", invalidFile}, nil, &bytes.Buffer{}, stderr); code != 1 {
			t.Fatalf("expected code 1 for German message, got %d", code)
		}
	})

	t.Run("Check gofmt", func(t *testing.T) {
		tmpDir := t.TempDir()

		// Formatted file
		cleanFile := filepath.Join(tmpDir, "clean.go")
		os.WriteFile(cleanFile, []byte("package main\n\nfunc main() {}\n"), 0644)
		if code := cli([]string{"check", "gofmt", cleanFile}, nil, &bytes.Buffer{}, &bytes.Buffer{}); code != 0 {
			t.Fatalf("expected code 0 for clean file, got %d", code)
		}

		// Clean directory path
		cleanDir := t.TempDir()
		os.WriteFile(filepath.Join(cleanDir, "clean.go"), []byte("package main\n\nfunc main() {}\n"), 0644)
		if code := cli([]string{"check", "gofmt", cleanDir}, nil, &bytes.Buffer{}, &bytes.Buffer{}); code != 0 {
			t.Fatalf("expected code 0 for clean dir, got %d", code)
		}

		// Unformatted file
		dirtyFile := filepath.Join(tmpDir, "dirty.go")
		os.WriteFile(dirtyFile, []byte("package main\nfunc  main( ) {}\n"), 0644)
		stderr := &bytes.Buffer{}
		if code := cli([]string{"check", "gofmt", dirtyFile}, nil, &bytes.Buffer{}, stderr); code != 1 {
			t.Fatalf("expected code 1 for dirty file, got %d", code)
		}
		if !strings.Contains(stderr.String(), "not gofmt-clean:") {
			t.Fatalf("expected unformatted notice, got %s", stderr.String())
		}

		// Syntax error file
		brokenFile := filepath.Join(tmpDir, "broken.go")
		os.WriteFile(brokenFile, []byte("package main\nfunc broken( {"), 0644)
		stderr.Reset()
		if code := cli([]string{"check", "gofmt", brokenFile}, nil, &bytes.Buffer{}, stderr); code != 1 {
			t.Fatalf("expected code 1 for broken file, got %d", code)
		}
	})

	t.Run("Check coverage", func(t *testing.T) {
		stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
		summaryPassing := "total:\t(statements)\t98.5%\n"
		if code := cli([]string{"check", "coverage", "--go-floor=98.0", "--summary=" + summaryPassing}, nil, stdout, stderr); code != 0 {
			t.Fatalf("expected code 0 for passing coverage, got %d (stderr: %s)", code, stderr.String())
		}
		if !strings.Contains(stdout.String(), "go coverage 98.5%") {
			t.Fatalf("expected output, got: %s", stdout.String())
		}

		// Empty summary
		if code := cli([]string{"check", "coverage"}, nil, &bytes.Buffer{}, &bytes.Buffer{}); code != 0 {
			t.Fatalf("expected code 0 for empty summary, got %d", code)
		}

		// Bad flag
		stderr.Reset()
		if code := cli([]string{"check", "coverage", "--invalid-flag"}, nil, &bytes.Buffer{}, stderr); code != 1 {
			t.Fatalf("expected code 1 for invalid flag, got %d", code)
		}

		// Below floor
		stderr.Reset()
		if code := cli([]string{"check", "coverage", "--go-floor=99.0", "--summary=" + summaryPassing}, nil, &bytes.Buffer{}, stderr); code != 1 {
			t.Fatalf("expected code 1 for below floor, got %d", code)
		}

		// Invalid summary
		stderr.Reset()
		if code := cli([]string{"check", "coverage", "--go-floor=98.0", "--summary=bad"}, nil, &bytes.Buffer{}, stderr); code != 1 {
			t.Fatalf("expected code 1 for bad summary, got %d", code)
		}
	})
}
