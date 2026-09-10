package verify

import (
	"errors"
	"io/fs"
	"strings"
	"testing"
)

// A run that says nothing, so a case can name only the field it is about.
func run(code int, stderr string) Run {
	return Run{ExitCode: code, Stderr: stderr}
}

// recorder answers each call from a queue and keeps every argv it was given.
type recorder struct {
	replies []Run
	calls   [][]string
}

func (r *recorder) run(argv ...string) Run {
	r.calls = append(r.calls, argv)
	if len(r.replies) == 0 {
		return Run{}
	}
	reply := r.replies[0]
	r.replies = r.replies[1:]
	return reply
}

func TestStaleDaemon(t *testing.T) {
	cases := []struct {
		name string
		in   Run
		want bool
	}{
		{"a clean run is not a stale daemon", run(0, ""), false},
		{"type errors exit 1 and are a verdict", run(1, "cli.py:58: error: bad"), false},
		{"a blocking error exits 2 without a daemon marker", run(2, "cli.py:1: error: syntax"), false},
		{"the status file names a pid that is gone", run(2, "Daemon has died"), true},
		{"the status file has no pid at all", run(2, "Invalid status file (no pid field)"), true},
		{"the pipe the status file points at is gone", run(2, `The NamedPipe at \\.\pipe\dmypy-x.pipe was not found.`), true},
		{"a marker without the exit code is not enough", run(1, "Daemon has died"), false},
	}
	for _, one := range cases {
		t.Run(one.name, func(t *testing.T) {
			if got := StaleDaemon(one.in); got != one.want {
				t.Fatalf("StaleDaemon(%+v) = %v, want %v", one.in, got, one.want)
			}
		})
	}
}

func TestCheckTypesPassesAVerdictThrough(t *testing.T) {
	for _, one := range []struct {
		name string
		in   Run
	}{
		{"green", run(0, "")},
		{"type errors", run(1, "cli.py:58: error: bad")},
		{"a blocking error with no daemon marker", run(2, "cli.py:1: error: syntax")},
	} {
		t.Run(one.name, func(t *testing.T) {
			asked := &recorder{replies: []Run{one.in}}
			removed := []string{}
			result, note := CheckTypes(asked.run, func(path string) error {
				removed = append(removed, path)
				return nil
			}, ".dmypy.json", []string{"--no-pretty"})

			if result.ExitCode != one.in.ExitCode {
				t.Fatalf("exit code %d, want %d", result.ExitCode, one.in.ExitCode)
			}
			if note != "" {
				t.Fatalf("nothing was healed, but the note says %q", note)
			}
			if len(asked.calls) != 1 {
				t.Fatalf("expected one call, got %v", asked.calls)
			}
			if len(removed) != 0 {
				t.Fatalf("a verdict must not remove anything, removed %v", removed)
			}
			want := "uv run dmypy --status-file .dmypy.json run -- --no-pretty"
			if got := strings.Join(asked.calls[0], " "); got != want {
				t.Fatalf("called %q, want %q", got, want)
			}
		})
	}
}

func TestCheckTypesHealsAStaleDaemonOnce(t *testing.T) {
	asked := &recorder{replies: []Run{
		run(2, "Daemon has died"),
		{ExitCode: 0, Stdout: "no issues found\n"},
	}}
	removed := []string{}
	result, note := CheckTypes(asked.run, func(path string) error {
		removed = append(removed, path)
		return nil
	}, "state.json", nil)

	if result.ExitCode != 0 || result.Stdout != "no issues found\n" {
		t.Fatalf("expected the second run's result, got %+v", result)
	}
	if !strings.Contains(note, "state.json") {
		t.Fatalf("the note must name the file it removed, got %q", note)
	}
	if len(removed) != 1 || removed[0] != "state.json" {
		t.Fatalf("removed %v, want [state.json]", removed)
	}
	if len(asked.calls) != 2 {
		t.Fatalf("expected the run and its retry, got %v", asked.calls)
	}
	if strings.Join(asked.calls[0], " ") != strings.Join(asked.calls[1], " ") {
		t.Fatalf("the retry must be the same command: %v then %v", asked.calls[0], asked.calls[1])
	}
	// The pid in a stale status file is a live process that is almost never the
	// daemon. Killing it takes a stranger down -- measured on 2026-09-10, a
	// sleeping shell whose pid stood in the file did not survive the heal.
	for _, call := range asked.calls {
		for _, word := range call {
			if word == "kill" {
				t.Fatalf("the heal must not kill anything: %v", call)
			}
		}
	}
}

func TestCheckTypesHealsWhenTheStatusFileIsAlreadyGone(t *testing.T) {
	asked := &recorder{replies: []Run{
		run(2, "Daemon has died"),
		{ExitCode: 0},
	}}
	result, note := CheckTypes(asked.run, func(string) error {
		return fs.ErrNotExist
	}, ".dmypy.json", nil)

	if result.ExitCode != 0 {
		t.Fatalf("a file that is already gone is not a failure, got %+v", result)
	}
	if note == "" {
		t.Fatal("the retry still happened and must be reported")
	}
	if len(asked.calls) != 2 {
		t.Fatalf("expected the retry to happen, got %v", asked.calls)
	}
}

func TestCheckTypesReportsAStatusFileItCannotRemove(t *testing.T) {
	asked := &recorder{replies: []Run{run(2, "Daemon has died")}}
	result, note := CheckTypes(asked.run, func(string) error {
		return errors.New("permission denied")
	}, ".dmypy.json", nil)

	if result.ExitCode != 2 {
		t.Fatalf("without the removal there is no retry, so the first result stands: %+v", result)
	}
	if !strings.Contains(note, "permission denied") {
		t.Fatalf("the note must carry the reason, got %q", note)
	}
	if len(asked.calls) != 1 {
		t.Fatalf("no retry may happen after a failed removal, got %v", asked.calls)
	}
}
