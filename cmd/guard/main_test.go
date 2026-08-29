package main

import (
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
