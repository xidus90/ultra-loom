package main

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestMainFunction(t *testing.T) {
	if os.Getenv("TEST_MAIN_GUARD") == "1" {
		main()
		return
	}
	cmd := exec.Command(os.Args[0], "-test.run=TestMainFunction")
	cmd.Env = append(os.Environ(), "TEST_MAIN_GUARD=1")
	cmd.Stdin = strings.NewReader(`{"tool_name": "Bash", "tool_input": {"command": "echo 1"}}`)
	_ = cmd.Run()
}

func TestCliPostEdit(t *testing.T) {
	input := `{"tool_name": "Edit", "tool_input": {"file_path": "README.md"}}`
	var stderr bytes.Buffer
	code := cli([]string{"post-edit", "--root", "."}, strings.NewReader(input), &stderr)
	if code != ExitOK {
		t.Fatalf("expected ExitOK for README.md, got %d", code)
	}

	// Error flag parse
	codeErr := cli([]string{"post-edit", "--invalid-flag"}, strings.NewReader(input), &stderr)
	if codeErr != ExitInternal {
		t.Fatalf("expected ExitInternal, got %d", codeErr)
	}
}

func TestCliStatusAndDoctor(t *testing.T) {
	subcommands := []string{"status", "explain", "doctor"}
	for _, sub := range subcommands {
		var stderr bytes.Buffer
		code := cli([]string{sub, "--root", "."}, strings.NewReader(""), &stderr)
		if code != ExitOK {
			t.Fatalf("expected ExitOK for %s, got %d", sub, code)
		}

		codeErr := cli([]string{sub, "--invalid-flag"}, strings.NewReader(""), &stderr)
		if codeErr != ExitInternal {
			t.Fatalf("expected ExitInternal on invalid flag for %s, got %d", sub, codeErr)
		}
	}
}

// `hook <event>` is a two-word subcommand, unlike the six single-word ones
// beside it, so a mistyped event must not fall through to the write barrier:
// the barrier reads stdin and decides about a file, and answering a hook call
// that way would be a verdict about the wrong question.
func TestCLIRefusesAnUnknownHookEvent(t *testing.T) {
	var stderr bytes.Buffer
	code := cli([]string{"hook", "no-such-event"}, strings.NewReader(""), &stderr)

	if code != ExitInternal {
		t.Fatalf("expected exit 1, got %d", code)
	}
	if !strings.Contains(stderr.String(), "no-such-event") {
		t.Fatalf("the refusal names the event, got %q", stderr.String())
	}
}

func TestCLIRefusesHookWithoutAnEvent(t *testing.T) {
	var stderr bytes.Buffer
	if code := cli([]string{"hook"}, strings.NewReader(""), &stderr); code != ExitInternal {
		t.Fatalf("expected exit 1, got %d", code)
	}
}

func TestCLIRefusesAnUnknownHookFlag(t *testing.T) {
	var stderr bytes.Buffer
	code := cli([]string{"hook", "session-start", "--invalid-flag"}, strings.NewReader(""), &stderr)
	if code != ExitInternal {
		t.Fatalf("expected exit 1, got %d", code)
	}
}

// A known event with an explicit root reaches the hook and comes back with its
// own exit code. The root is a project with no runs in it, so the hook writes
// nothing -- `cli` hands the hook os.Stdout, which no test can capture.
func TestCLIRunsTheSessionStartHook(t *testing.T) {
	var stderr bytes.Buffer
	code := cli([]string{"hook", "session-start", "--host", "claude", "--root", project(t)},
		strings.NewReader(`{"hook_event_name":"SessionStart","session_id":"s1"}`), &stderr)

	if code != ExitOK {
		t.Fatalf("expected exit 0, got %d (%s)", code, stderr.String())
	}
}

// Without `--root` the root is the first directory at or above the working
// one that holds `.ultraloom/config.toml`, and the hook runs against that.
func TestCLIWalksUpToTheRootWhenNoneIsGiven(t *testing.T) {
	root := project(t)
	gitInit(t, root)
	inside := filepath.Join(root, "deep", "deeper")
	if err := os.MkdirAll(inside, 0o755); err != nil {
		t.Fatal(err)
	}
	undo := chdir(t, inside)
	defer undo()

	var stderr bytes.Buffer
	code := cli([]string{"hook", "session-start", "--host", "claude"},
		strings.NewReader(`{"session_id":"s1"}`), &stderr)

	if code != ExitOK {
		t.Fatalf("expected exit 0, got %d (%s)", code, stderr.String())
	}
	// The walk decided which project the base was filed under, so the file is
	// the evidence that it found this one and not the checkout the test binary
	// happens to run in.
	if _, err := os.Stat(filepath.Join(root, ".ultraloom", "hooks", "s1.json")); err != nil {
		t.Fatalf("the base was not filed under the root that was walked to: %v", err)
	}
}

// chdir moves the process and hands back the way home. Go 1.22 has no
// t.Chdir, and nothing in this package runs in parallel, so a bare Chdir is
// safe here.
func chdir(t *testing.T, to string) func() {
	t.Helper()
	was, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(to); err != nil {
		t.Fatal(err)
	}
	return func() {
		if err := os.Chdir(was); err != nil {
			t.Fatal(err)
		}
	}
}

// Without `--root` the root is walked up to, and a directory with no
// `.ultraloom/config.toml` above it has none to find. Arranged by moving the
// process, because that walk starts at the working directory and nothing else.
func TestCLIRefusesAHookOutsideAProject(t *testing.T) {
	undo := chdir(t, t.TempDir())
	defer undo()

	var stderr bytes.Buffer
	code := cli([]string{"hook", "session-start"}, strings.NewReader(""), &stderr)

	if code != ExitInternal {
		t.Fatalf("expected exit 1, got %d", code)
	}
	if !strings.Contains(stderr.String(), "config.toml") {
		t.Fatalf("the refusal says what it looked for, got %q", stderr.String())
	}
}

func TestCliGuardRoot(t *testing.T) {
	input := `{"tool_name": "Bash", "tool_input": {"command": "echo 1"}}`
	var stderr bytes.Buffer
	code := cli([]string{"--root", "."}, strings.NewReader(input), &stderr)
	if code != ExitOK {
		t.Fatalf("expected ExitOK, got %d", code)
	}

	codeErr := cli([]string{"--invalid-flag"}, strings.NewReader(input), &stderr)
	if codeErr != ExitInternal {
		t.Fatalf("expected ExitInternal on invalid flag, got %d", codeErr)
	}
}
