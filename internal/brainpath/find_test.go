package brainpath

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

func TestAShimOnPathWinsAndStaysAName(t *testing.T) {
	look := func(name string) (string, error) { return "C:/Users/x/.local/bin/brain.exe", nil }
	got, ok := Find(look, func(string) string { return "" })
	if !ok {
		t.Fatal("brain was not found")
	}
	if got != "brain" {
		t.Fatalf("command = %q, want the bare name so no machine path is committed", got)
	}
}

func TestTheEnvironmentVariableIsTheLastResort(t *testing.T) {
	look := func(name string) (string, error) { return "", errors.New("not found") }
	env := func(key string) string {
		if key == "ULTRA_BRAIN_DIR" {
			return "D:/brain"
		}
		return ""
	}
	got, ok := Find(look, env)
	if !ok || !strings.Contains(got, "D:/brain") {
		t.Fatalf("command = %q, ok = %v", got, ok)
	}
}

func TestNothingFoundMeansNoWikiHooks(t *testing.T) {
	look := func(name string) (string, error) { return "", errors.New("not found") }
	if _, ok := Find(look, func(string) string { return "" }); ok {
		t.Fatal("claimed to have found brain")
	}
}

func TestPathBeatsTheEnvironmentWhenBothAnswer(t *testing.T) {
	look := func(name string) (string, error) { return "/usr/local/bin/brain", nil }
	env := func(string) string { return "D:/brain" }
	got, ok := Find(look, env)
	if !ok || got != "brain" {
		t.Fatalf("command = %q, ok = %v, want the bare name", got, ok)
	}
}

func TestAWhitespaceOnlyDirectoryIsNotSet(t *testing.T) {
	look := func(name string) (string, error) { return "", errors.New("not found") }
	env := func(string) string { return "  \t " }
	if got, ok := Find(look, env); ok {
		t.Fatalf("claimed to have found brain at %q", got)
	}
}

func TestTheDirectoryIsTrimmedBeforeItIsUsed(t *testing.T) {
	look := func(name string) (string, error) { return "", errors.New("not found") }
	env := func(string) string { return "  D:/brain\n" }
	got, _ := Find(look, env)
	if strings.ContainsAny(got, "\n") || !strings.HasSuffix(got, "D:/brain brain") {
		t.Fatalf("command = %q, want the trimmed directory", got)
	}
}

// decode is what an MCP client does with the file: it parses it. A test that
// only compares text would pass on a document no client can read.
func decode(t *testing.T, doc string) (command string, args []string) {
	t.Helper()
	var parsed struct {
		MCPServers map[string]struct {
			Command string   `json:"command"`
			Args    []string `json:"args"`
		} `json:"mcpServers"`
	}
	if err := json.Unmarshal([]byte(doc), &parsed); err != nil {
		t.Fatalf("MCPEntry produced invalid JSON: %v\n%s", err, doc)
	}
	server, ok := parsed.MCPServers["brain"]
	if !ok {
		t.Fatalf("no brain server in %s", doc)
	}
	return server.Command, server.Args
}

func TestABareNameBecomesTheExecutable(t *testing.T) {
	command, args := decode(t, MCPEntry("brain"))
	if command != "brain" {
		t.Fatalf("command = %q, want brain", command)
	}
	if len(args) != 1 || args[0] != "mcp" {
		t.Fatalf("args = %q, want [mcp]", args)
	}
}

func TestTheDirectoryFormBecomesUvAndItsArguments(t *testing.T) {
	command, args := decode(t, MCPEntry("uv run --directory D:/brain brain"))
	if command != "uv" {
		t.Fatalf("command = %q, want uv -- a command is an executable, not a shell line", command)
	}
	want := []string{"run", "--directory", "D:/brain", "brain", "mcp"}
	if strings.Join(args, "\x00") != strings.Join(want, "\x00") {
		t.Fatalf("args = %q, want %q", args, want)
	}
}

func TestADirectoryWithASpaceStaysOneArgument(t *testing.T) {
	dir := "C:/Program Files/brain"
	look := func(name string) (string, error) { return "", errors.New("not found") }
	got, _ := Find(look, func(string) string { return dir })
	command, args := decode(t, MCPEntry(got))
	if command != "uv" {
		t.Fatalf("command = %q, want uv", command)
	}
	if len(args) != 5 || args[2] != dir {
		t.Fatalf("args = %q, want the directory as one argument", args)
	}
}

// A quote or a backslash is where a %q format string stops being JSON.
func TestQuotesAndBackslashesSurviveTheRoundTrip(t *testing.T) {
	dir := `C:\brain\"odd"` + "\x1b"
	look := func(name string) (string, error) { return "", errors.New("not found") }
	got, _ := Find(look, func(string) string { return dir })
	_, args := decode(t, MCPEntry(got))
	if len(args) != 5 || args[2] != dir {
		t.Fatalf("args = %q, want the directory unchanged", args)
	}
}
