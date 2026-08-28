package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xidus90/ultra-loom/internal/detect"
)

// The version is the one thing a user can ask for before anything is
// configured, so it is also the first thing that must exist.
func TestVersionIsNotEmpty(t *testing.T) {
	if version == "" {
		t.Fatal("version must not be empty")
	}
}

func TestVersionIsPrintedAndNothingElseHappens(t *testing.T) {
	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := run([]string{"--version"}, stdout, stderr); code != 0 {
		t.Fatalf("exit = %d, want 0", code)
	}
	if strings.TrimSpace(stdout.String()) != version {
		t.Fatalf("stdout = %q, want %q", stdout.String(), version)
	}
}

func TestDetectOnlyPrintsTheFactsAsJSON(t *testing.T) {
	root := t.TempDir()
	write(t, filepath.Join(root, "pyproject.toml"), "[project]\n")
	write(t, filepath.Join(root, "uv.lock"), "")

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := run([]string{"--detect-only", "--root", root}, stdout, stderr); code != 0 {
		t.Fatalf("exit = %d, want 0 (stderr: %s)", code, stderr)
	}
	var facts detect.Facts
	if err := json.Unmarshal(stdout.Bytes(), &facts); err != nil {
		t.Fatalf("stdout is not JSON: %v (%s)", err, stdout)
	}
	if len(facts.Stacks) != 2 || facts.Stacks[0] != "python" || facts.Stacks[1] != "uv" {
		t.Fatalf("stacks = %v, want [python uv]", facts.Stacks)
	}
}

// The neighbour wiki is only reachable from outside the root, so this is the
// test that proves cmd/init joins that fact to the pure detection.
func TestDetectOnlyFindsTheNeighbourWiki(t *testing.T) {
	parent := t.TempDir()
	root := filepath.Join(parent, "iam_backend")
	mkdir(t, root)
	mkdir(t, filepath.Join(parent, "iam_backend_wiki", ".git"))

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := run([]string{"--detect-only", "--root", root}, stdout, stderr); code != 0 {
		t.Fatalf("exit = %d, want 0 (stderr: %s)", code, stderr)
	}
	var facts detect.Facts
	if err := json.Unmarshal(stdout.Bytes(), &facts); err != nil {
		t.Fatalf("stdout is not JSON: %v", err)
	}
	if facts.WikiMode != "neighbour_repo" || facts.WikiPath != "iam_backend_wiki/" {
		t.Fatalf("wiki = %q %q, want the neighbour repository", facts.WikiMode, facts.WikiPath)
	}
}

// A tree with a .git in it reaches the one subprocess this program starts.
func TestDetectOnlyAsksGitAboutItsHooksPath(t *testing.T) {
	requireGit(t)
	root := t.TempDir()
	run3(t, root, "git", "init")
	run3(t, root, "git", "config", "core.hooksPath", ".githooks")

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := run([]string{"--detect-only", "--root", root}, stdout, stderr); code != 0 {
		t.Fatalf("exit = %d, want 0 (stderr: %s)", code, stderr)
	}
	var facts detect.Facts
	if err := json.Unmarshal(stdout.Bytes(), &facts); err != nil {
		t.Fatalf("stdout is not JSON: %v", err)
	}
	if !facts.HasGit || facts.HooksPath != ".githooks" {
		t.Fatalf("hooks path = %q (git: %v), want .githooks", facts.HooksPath, facts.HasGit)
	}
}

// Unset is the common case, and it must not read as a failure.
func TestAnUnsetHooksPathIsNotAnError(t *testing.T) {
	requireGit(t)
	root := t.TempDir()
	run3(t, root, "git", "init")
	got, err := git(root, "git", "config", "--get", "core.hooksPath")
	if err != nil || got != "" {
		t.Fatalf("git said %q, %v; want empty and nil", got, err)
	}
}

func TestAFailingCommandIsReported(t *testing.T) {
	requireGit(t)
	if _, err := git(t.TempDir(), "git", "rev-parse", "--absurd-flag"); err == nil {
		t.Fatal("err = nil, want git's failure")
	}
}

// A git that refuses must stop the report rather than print half the truth.
func TestAFailingGitStopsTheReport(t *testing.T) {
	root := t.TempDir()
	mkdir(t, filepath.Join(root, ".git"))
	refuse := func(string, ...string) (string, error) { return "", errors.New("git is broken") }

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := report(root, refuse, stdout, stderr); code != 1 {
		t.Fatalf("exit = %d, want 1 (stdout: %s)", code, stdout)
	}
	if !strings.Contains(stderr.String(), "git is broken") {
		t.Fatalf("stderr = %q, want git's complaint", stderr)
	}
	if stdout.Len() != 0 {
		t.Fatalf("stdout = %q, want nothing printed", stdout)
	}
}

func TestAnUnknownFlagFails(t *testing.T) {
	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := run([]string{"--nonsense"}, stdout, stderr); code != 1 {
		t.Fatalf("exit = %d, want 1", code)
	}
}

func TestWithoutAFlagNothingIsInstalledYet(t *testing.T) {
	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := run(nil, stdout, stderr); code != 1 {
		t.Fatalf("exit = %d, want 1", code)
	}
	if !strings.Contains(stderr.String(), "not implemented") {
		t.Fatalf("stderr = %q, want the not-implemented note", stderr)
	}
}

func requireGit(t *testing.T) {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git is not on PATH; the subprocess edge cannot be exercised")
	}
}

func run3(t *testing.T, dir string, argv ...string) {
	t.Helper()
	command := exec.Command(argv[0], argv[1:]...)
	command.Dir = dir
	if out, err := command.CombinedOutput(); err != nil {
		t.Fatalf("%s: %v (%s)", strings.Join(argv, " "), err, out)
	}
}

func write(t *testing.T, name, body string) {
	t.Helper()
	if err := os.WriteFile(name, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func mkdir(t *testing.T, name string) {
	t.Helper()
	if err := os.MkdirAll(name, 0o755); err != nil {
		t.Fatal(err)
	}
}
