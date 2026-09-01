package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
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
	if code := cli([]string{"--version"}, nothing(), stdout, stderr); code != 0 {
		t.Fatalf("exit = %d, want 0", code)
	}
	if strings.TrimSpace(stdout.String()) != version {
		t.Fatalf("stdout = %q, want %q", stdout.String(), version)
	}
}

func TestDetectOnlyPrintsTheFactsAsJSON(t *testing.T) {
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "pyproject.toml"), "[project]\n")
	writeFile(t, filepath.Join(root, "uv.lock"), "")

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := cli([]string{"--detect-only", "--root", root}, nothing(), stdout, stderr); code != 0 {
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
	if code := cli([]string{"--detect-only", "--root", root}, nothing(), stdout, stderr); code != 0 {
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
	if code := cli([]string{"--detect-only", "--root", root}, nothing(), stdout, stderr); code != 0 {
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
	if code := cli([]string{"--nonsense"}, nothing(), stdout, stderr); code != 1 {
		t.Fatalf("exit = %d, want 1", code)
	}
}

// A buffer is not a terminal, so this is the agent case: unanswered questions
// and nothing to ask on. It must refuse rather than install silently.
func TestWithoutAnswersAndWithoutATerminalNothingIsInstalled(t *testing.T) {
	root := t.TempDir()
	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := cli([]string{"--root", root}, nothing(), stdout, stderr); code != 2 {
		t.Fatalf("exit = %d, want 2 (%s)", code, stdout)
	}
	if !strings.Contains(stdout.String(), "--commit-language") {
		t.Fatalf("stdout = %q, want the missing flags named", stdout)
	}
	if _, err := os.Stat(filepath.Join(root, ".ultraloom")); err == nil {
		t.Fatal("a refused run wrote something")
	}
}

// Asking for help is not a failure. flag.ContinueOnError makes it an error,
// and a wrapper script reads a non-zero exit as the tool being broken.
func TestHelpExitsZero(t *testing.T) {
	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := cli([]string{"--help"}, nothing(), stdout, stderr); code != 0 {
		t.Fatalf("exit = %d, want 0", code)
	}
	if !strings.Contains(stderr.String(), "-dry-run") {
		t.Fatalf("stderr = %q, want the flag list", stderr)
	}
}

// nothing is a stdin that is not a terminal and holds no input.
func nothing() io.Reader { return &bytes.Buffer{} }

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

func writeFile(t *testing.T, name, body string) {
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

// A file is not a terminal, and neither is a file that is already closed --
// the two ways stdin can fail to be a person to ask.
func TestNeitherAFileNorAClosedOneIsATerminal(t *testing.T) {
	name := filepath.Join(t.TempDir(), "stdin")
	writeFile(t, name, "")
	file, err := os.Open(name)
	if err != nil {
		t.Fatal(err)
	}
	if terminal(file) {
		t.Fatal("a regular file was taken for a terminal")
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	if terminal(file) {
		t.Fatal("a closed file was taken for a terminal")
	}
}

// The null device is the shape an agent or a CI job hands in -- `init < NUL`
// on Windows, `init < /dev/null` everywhere else. It is a character device,
// so the mode bit alone read it as a person: four prompts went to nobody, the
// defaults were taken, and a full install landed at exit 0.
func TestTheNullDeviceIsNobodyToAsk(t *testing.T) {
	file, err := os.Open(os.DevNull)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	if terminal(file) {
		t.Fatal("the null device was taken for a person")
	}
}

func TestCliCheckSubcommandsDetailed(t *testing.T) {
	tmpDir := t.TempDir()

	// 1. No subcommand
	var stdout, stderr bytes.Buffer
	if code := cli([]string{"check"}, nothing(), &stdout, &stderr); code != 1 {
		t.Fatalf("expected code 1 for bare check, got %d", code)
	}

	// 2. Unknown subcommand
	stderr.Reset()
	if code := cli([]string{"check", "unknown-sub"}, nothing(), &stdout, &stderr); code != 1 {
		t.Fatalf("expected code 1 for unknown check subcommand, got %d", code)
	}

	// 3. commit-msg missing arg
	stderr.Reset()
	if code := cli([]string{"check", "commit-msg"}, nothing(), &stdout, &stderr); code != 1 {
		t.Fatalf("expected code 1 for missing commit-msg path, got %d", code)
	}

	// 4. commit-msg non-existent file
	stderr.Reset()
	if code := cli([]string{"check", "commit-msg", filepath.Join(tmpDir, "missing.txt")}, nothing(), &stdout, &stderr); code != 1 {
		t.Fatalf("expected code 1 for missing file, got %d", code)
	}

	// 5. commit-msg valid
	validFile := filepath.Join(tmpDir, "valid_commit.txt")
	writeFile(t, validFile, "feat: add new feature\n\nExplain detail.")
	stderr.Reset()
	if code := cli([]string{"check", "commit-msg", validFile}, nothing(), &stdout, &stderr); code != 0 {
		t.Fatalf("expected code 0 for valid commit msg, got %d (%s)", code, stderr.String())
	}

	// 6. commit-msg invalid
	invalidFile := filepath.Join(tmpDir, "invalid_commit.txt")
	writeFile(t, invalidFile, "feat: behebe den fehler in der komponente")
	stderr.Reset()
	if code := cli([]string{"check", "commit-msg", invalidFile}, nothing(), &stdout, &stderr); code != 1 {
		t.Fatalf("expected code 1 for invalid commit msg, got %d", code)
	}

	// 7. gofmt clean & dirty
	cleanFile := filepath.Join(tmpDir, "clean.go")
	writeFile(t, cleanFile, "package main\n\nfunc main() {}\n")
	stderr.Reset()
	if code := cli([]string{"check", "gofmt", cleanFile}, nothing(), &stdout, &stderr); code != 0 {
		t.Fatalf("expected code 0 for clean gofmt, got %d (%s)", code, stderr.String())
	}

	// 7b. gofmt without paths defaults to "."
	stderr.Reset()
	_ = cli([]string{"check", "gofmt"}, nothing(), &stdout, &stderr)

	dirtyFile := filepath.Join(tmpDir, "dirty.go")
	writeFile(t, dirtyFile, "package main\nfunc  main( ) {}\n")
	stderr.Reset()
	if code := cli([]string{"check", "gofmt", dirtyFile}, nothing(), &stdout, &stderr); code != 1 {
		t.Fatalf("expected code 1 for dirty gofmt, got %d", code)
	}

	// 8. coverage check
	stdout.Reset()
	stderr.Reset()
	if code := cli([]string{"check", "coverage", "--summary", "total: (statements) 99.5%"}, nothing(), &stdout, &stderr); code != 0 {
		t.Fatalf("expected code 0 for passing coverage, got %d", code)
	}

	stderr.Reset()
	if code := cli([]string{"check", "coverage", "--summary", "total: (statements) 80.0%"}, nothing(), &stdout, &stderr); code != 1 {
		t.Fatalf("expected code 1 for failing coverage, got %d", code)
	}

	stderr.Reset()
	if code := cli([]string{"check", "coverage", "--summary", "not a summary"}, nothing(), &stdout, &stderr); code != 1 {
		t.Fatalf("expected code 1 for invalid summary, got %d", code)
	}

	stderr.Reset()
	if code := cli([]string{"check", "coverage", "--invalid-flag"}, nothing(), &stdout, &stderr); code != 1 {
		t.Fatalf("expected code 1 for invalid flag, got %d", code)
	}
}

func TestCliHelpFlag(t *testing.T) {
	var stdout, stderr bytes.Buffer
	if code := cli([]string{"--help"}, nothing(), &stdout, &stderr); code != 0 {
		t.Fatalf("expected code 0 for --help, got %d", code)
	}
}

func TestGatherHooksPathError(t *testing.T) {
	tmpDir := t.TempDir()
	mkdir(t, filepath.Join(tmpDir, ".git"))
	brokenRunner := func(string, ...string) (string, error) {
		return "", errors.New("git broken")
	}
	_, err := gather(tmpDir, brokenRunner)
	if err == nil {
		t.Fatal("expected error from broken HooksPath in gather, got nil")
	}
}

func TestGatherWithWikiMode(t *testing.T) {
	tmpDir := t.TempDir()
	writeFile(t, filepath.Join(tmpDir, ".brain.toml"), "[area]\nname=\"test\"\nwiki=true\n")
	facts, err := gather(tmpDir, nil)
	if err != nil {
		t.Fatalf("gather failed: %v", err)
	}
	if facts.WikiMode != "brain" {
		t.Fatalf("expected WikiMode=brain, got %q", facts.WikiMode)
	}
}
