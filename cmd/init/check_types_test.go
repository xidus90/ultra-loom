package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xidus90/ultra-loom/internal/verify"
)

// Puts a fixed answer in the subprocess's place for one test, and gives the
// real one back afterwards -- `check types` is the only caller, and a test that
// left the stub behind would make every later one measure the stub.
func stubDmypy(t *testing.T, answer func(argv ...string) verify.Run) *[][]string {
	t.Helper()
	previous := runDmypy
	calls := &[][]string{}
	runDmypy = func(argv ...string) verify.Run {
		*calls = append(*calls, argv)
		return answer(argv...)
	}
	t.Cleanup(func() { runDmypy = previous })
	return calls
}

func TestCheckTypesReportsWhatDmypySaid(t *testing.T) {
	stubDmypy(t, func(...string) verify.Run {
		return verify.Run{ExitCode: 0, Stdout: "Success: no issues found\n"}
	})
	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := cli([]string{"check", "types"}, nil, stdout, stderr); code != 0 {
		t.Fatalf("expected code 0, got %d (stderr: %s)", code, stderr.String())
	}
	if !strings.Contains(stdout.String(), "no issues found") {
		t.Fatalf("dmypy's own output must reach the caller, got %q", stdout.String())
	}
	if stderr.String() != "" {
		t.Fatalf("a green run says nothing on stderr, got %q", stderr.String())
	}
}

func TestCheckTypesFailsOnTypeErrors(t *testing.T) {
	stubDmypy(t, func(...string) verify.Run {
		return verify.Run{ExitCode: 1, Stdout: "cli.py:58: error: bad\n"}
	})
	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := cli([]string{"check", "types"}, nil, stdout, stderr); code != 1 {
		t.Fatalf("expected code 1, got %d", code)
	}
	if !strings.Contains(stdout.String(), "error: bad") {
		t.Fatalf("the finding must survive, got %q", stdout.String())
	}
}

func TestCheckTypesSaysWhatItHealed(t *testing.T) {
	first := true
	stubDmypy(t, func(argv ...string) verify.Run {
		if first && argv[len(argv)-1] == "--no-pretty" {
			first = false
			return verify.Run{ExitCode: 2, Stderr: "Daemon has died\n"}
		}
		return verify.Run{ExitCode: 0, Stdout: "Success: no issues found\n"}
	})
	statusFile := filepath.Join(t.TempDir(), "dmypy.json")
	if err := os.WriteFile(statusFile, []byte("{}"), 0o600); err != nil {
		t.Fatal(err)
	}
	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	code := cli([]string{"check", "types", "--status-file=" + statusFile}, nil, stdout, stderr)

	if code != 0 {
		t.Fatalf("a healed run is green, got %d (stderr: %s)", code, stderr.String())
	}
	if !strings.Contains(stderr.String(), "the dmypy daemon was gone") {
		t.Fatalf("healing must be loud, got %q", stderr.String())
	}
	if _, err := os.Stat(statusFile); !os.IsNotExist(err) {
		t.Fatalf("the stale status file is still there: %v", err)
	}
}

func TestCheckTypesRejectsAnUnknownFlag(t *testing.T) {
	stderr := &bytes.Buffer{}
	if code := cli([]string{"check", "types", "--nonsense"}, nil, &bytes.Buffer{}, stderr); code != 1 {
		t.Fatalf("expected code 1, got %d", code)
	}
}

func TestCheckUsageNamesTypes(t *testing.T) {
	stderr := &bytes.Buffer{}
	cli([]string{"check"}, nil, &bytes.Buffer{}, stderr)
	if !strings.Contains(stderr.String(), "types") {
		t.Fatalf("the usage line must name every subcommand, got %q", stderr.String())
	}
}

func TestExecRunReadsACommandsAnswer(t *testing.T) {
	// `go` is on the path of anything that can run this test at all.
	done := execRun("go", "version")
	if done.ExitCode != 0 {
		t.Fatalf("go version exited %d: %s", done.ExitCode, done.Stderr)
	}
	if !strings.Contains(done.Stdout, "go version") {
		t.Fatalf("stdout was not read: %q", done.Stdout)
	}
}

func TestExecRunReportsANonZeroExit(t *testing.T) {
	done := execRun("go", "vet", "--nonsense-flag")
	if done.ExitCode == 0 {
		t.Fatal("a failing command must not read as a green one")
	}
}

func TestExecRunDoesNotPassAMissingToolOffAsGreen(t *testing.T) {
	done := execRun("ultraloom-no-such-tool")
	if done.ExitCode == 0 {
		t.Fatal("a tool that cannot be started is not a verdict about the code")
	}
	if !strings.Contains(done.Stderr, "could not be run") {
		t.Fatalf("the reason must be said, got %q", done.Stderr)
	}
}
