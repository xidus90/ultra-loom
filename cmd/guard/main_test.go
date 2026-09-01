package main

import (
	"bytes"
	"os"
	"os/exec"
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
