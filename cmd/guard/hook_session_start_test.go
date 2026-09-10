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

	"github.com/xidus90/ultra-loom/internal/sessions"
)

// A journal line carrying all ten of Entry's keys, because internal/journal
// reads a missing or an unknown key as damage (internal/journal/journal.go:45-48).
const waitingRun = `{"delta":{},"detail":"which colour?","effort":null,"input_hash":"h1","kind":"gate","node":"ask","outcome":"paused","seconds":0.1,"tokens":0,"tools":null}`

const finishedRun = `{"delta":{},"detail":null,"effort":null,"input_hash":"h1","kind":"node","node":"work","outcome":"ok","seconds":0.1,"tokens":0,"tools":null}`

// One line per paused run, in run order, and the resume command spelled out --
// a paused run has an address but no voice, and this hook is where the id
// comes from.
func TestHookSessionStartReportsAPausedRun(t *testing.T) {
	root := project(t)
	writeRun(t, root, "run-b", waitingRun)
	writeRun(t, root, "run-a", waitingRun)

	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(
		strings.NewReader(`{"hook_event_name":"SessionStart","session_id":"s1"}`),
		&stdout, &stderr, root, "claude")

	if code != ExitOK {
		t.Fatalf("session-start never blocks, got exit %d (%s)", code, stderr.String())
	}
	context := additionalContext(t, stdout.Bytes())
	if !strings.Contains(context, "run run-a is waiting at ask: which colour?") {
		t.Fatalf("the paused run is named: %q", context)
	}
	if !strings.Contains(context, `ultraloom resume run-a --answer "your answer"`) {
		t.Fatalf("the answer command is spelled out: %q", context)
	}
	// Sorted by file name, as session_start.py (fa3dd38):69's
	// sorted(directory.glob(...)) was: two runs reported in directory order
	// would read differently on two machines.
	if strings.Index(context, "run-a") > strings.Index(context, "run-b") {
		t.Fatalf("runs come in name order: %q", context)
	}
}

// The wording stays ASCII because that is how session_start.py (fa3dd38):81-89
// worded the line this replaces, and a session's announcement should not change
// spelling with the port. Nothing here claims Go would fail on a wider rune --
// json.Encoder writes UTF-8 without complaint; the claim is only that the Go
// hook says what the Python one said.
func TestHookSessionStartSaysNothingNonASCII(t *testing.T) {
	root := project(t)
	writeRun(t, root, "run-a", waitingRun)

	var stdout, stderr bytes.Buffer
	runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, root, "claude")

	for _, b := range stdout.Bytes() {
		if b > 0x7f {
			t.Fatalf("non-ASCII byte %#x in the answer: %q", b, stdout.String())
		}
	}
}

// Nothing waiting writes no envelope at all, rather than one carrying an empty
// additionalContext -- hostio.WriteContext makes that decision in its Claude
// arm, and this only shows it reaching the hook's own output. Named rather
// than cited by line: the decision has already moved between files once.
func TestHookSessionStartIsSilentWithNothingWaiting(t *testing.T) {
	root := project(t)

	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, root, "claude")

	if code != ExitOK || stdout.Len() != 0 {
		t.Fatalf("expected exit 0 and no output, got %d and %q", code, stdout.String())
	}
}

// Only the run files, and only those that are files: a directory whose name
// ends in .jsonl and a note lying beside the journals are both passed over.
func TestHookSessionStartReadsOnlyRunFiles(t *testing.T) {
	root := project(t)
	dir := filepath.Join(root, ".ultraloom", "runs")
	if err := os.MkdirAll(filepath.Join(dir, "a-directory.jsonl"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "notes.txt"), []byte("{not json\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, root, "claude")

	if code != ExitOK || stdout.Len() != 0 || stderr.Len() != 0 {
		t.Fatalf("expected exit 0 and silence, got %d, %q and %q", code, stdout.String(), stderr.String())
	}
}

// A run whose last line is not a pause is not waiting for anybody, so it gets
// no line -- journal.Pending answers nil for it.
func TestHookSessionStartSaysNothingAboutAFinishedRun(t *testing.T) {
	root := project(t)
	writeRun(t, root, "run-done", finishedRun)

	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, root, "claude")

	if code != ExitOK || stdout.Len() != 0 {
		t.Fatalf("expected exit 0 and no output, got %d and %q", code, stdout.String())
	}
}

// The base commit is written here and nowhere else: by the time the first Stop
// fires, the turn has already run, and anything it committed would sit inside
// the baseline that is supposed to expose it.
//
// Read back through the package's own door rather than by parsing the file
// again: a second reader here would pass while ReadState was broken.
func TestHookSessionStartRecordsTheBaseCommit(t *testing.T) {
	root := project(t)
	gitInit(t, root)

	var stdout, stderr bytes.Buffer
	runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, root, "claude")

	if state := sessions.ReadState(root, "s1"); len(state.Base) != 40 {
		t.Fatalf("expected a full sha as the base, got %q", state.Base)
	}
}

// Silent in both failure cases, as session_start.py (fa3dd38):43-59's
// _record_base was:
// without a session id there is nowhere to file it, and outside a repository
// there is nothing to file. Neither is a defect of the project, and neither is
// worth a line in every session of every checkout that is not a repository.
// The stop gate is where the absence matters and where it is said out loud.
func TestHookSessionStartRecordsNoBaseWithoutARepository(t *testing.T) {
	root := project(t)

	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, root, "claude")

	if code != ExitOK {
		t.Fatalf("a checkout that is not a repository is not a failure, got %d", code)
	}
	if stderr.Len() != 0 {
		t.Fatalf("and it is not worth a word, got %q", stderr.String())
	}
}

func TestHookSessionStartRecordsNoBaseWithoutASessionID(t *testing.T) {
	root := project(t)
	gitInit(t, root)

	var stdout, stderr bytes.Buffer
	runHookSessionStart(strings.NewReader(`{"hook_event_name":"SessionStart"}`), &stdout, &stderr, root, "claude")

	dir := filepath.Join(root, ".ultraloom", "hooks")
	if entries, err := os.ReadDir(dir); err == nil && len(entries) > 0 {
		t.Fatalf("no session id means nowhere to file it, got %d files", len(entries))
	}
}

// A base that cannot be written is said out loud and ends the call with exit
// 1, unlike the two absences above. state.py:56-65's `write` catches nothing,
// so an OSError there leaves the Python `run` by itself; keeping quiet here
// would be a departure from the original rather than the parity the two
// silences are.
func TestHookSessionStartReportsABaseItCannotWrite(t *testing.T) {
	root := project(t)
	gitInit(t, root)
	// A file where the state directory belongs, so creating it must fail.
	if err := os.WriteFile(filepath.Join(root, ".ultraloom", "hooks"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}

	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, root, "claude")

	if code != ExitInternal {
		t.Fatalf("expected exit 1, got %d", code)
	}
	if !strings.Contains(stderr.String(), "hooks") {
		t.Fatalf("the refusal names the path it could not write, got %q", stderr.String())
	}
}

// A damaged journal is named and not swallowed, and it does not hide the other
// runs behind it: one damaged file is a finding of its own, and hiding the rest
// would turn a small defect into a silent one.
func TestHookSessionStartNamesADamagedJournalAndCarriesOn(t *testing.T) {
	root := project(t)
	writeRun(t, root, "run-broken", "{not json")
	writeRun(t, root, "run-ok", waitingRun)

	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, root, "claude")

	if code != ExitOK {
		t.Fatalf("a damaged journal does not end a session, got %d", code)
	}
	if !strings.Contains(stderr.String(), "run-broken") {
		t.Fatalf("the damaged file is named: %q", stderr.String())
	}
	if !strings.Contains(additionalContext(t, stdout.Bytes()), "run-ok") {
		t.Fatalf("the other runs are still reported: %q", stdout.String())
	}
}

// payload.py's exit protocol: 1 for an internal failure, and never 2 -- this
// hook is an announcement and has nothing to block.
func TestHookSessionStartOnABadPayload(t *testing.T) {
	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader("{not json"), &stdout, &stderr, project(t), "claude")

	if code != ExitInternal {
		t.Fatalf("expected exit 1, got %d", code)
	}
	if strings.TrimSpace(stderr.String()) == "" {
		t.Fatal("a refusal says why")
	}
}

func TestHookSessionStartOnAnUnknownHost(t *testing.T) {
	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, project(t), "gemini-cli")

	if code != ExitInternal {
		t.Fatalf("an unknown host is refused, got %d", code)
	}
}

// An output that cannot be written is the same exit 1 as a payload that cannot
// be read, and it says which of the two happened. Nothing else in this hook
// can make hostio.WriteContext fail for the claude host -- the document holds
// nothing but strings -- so the failure is arranged in the writer.
func TestHookSessionStartOnAnUnwritableOutput(t *testing.T) {
	root := project(t)
	writeRun(t, root, "run-a", waitingRun)

	var stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`),
		refusingWriter{}, &stderr, root, "claude")

	if code != ExitInternal {
		t.Fatalf("expected exit 1, got %d", code)
	}
	if !strings.Contains(stderr.String(), "no room") {
		t.Fatalf("the refusal carries the writer's own words, got %q", stderr.String())
	}
}

// refusingWriter is a stdout that refuses everything.
type refusingWriter struct{}

func (refusingWriter) Write([]byte) (int, error) { return 0, errors.New("no room") }

// project is a directory ultraloom recognises as a root.
func project(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".ultraloom"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".ultraloom", "config.toml"), []byte("[verify]\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	return root
}

func writeRun(t *testing.T, root, runID, body string) {
	t.Helper()
	dir := filepath.Join(root, ".ultraloom", "runs")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, runID+".jsonl"), []byte(body+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func gitInit(t *testing.T, root string) {
	t.Helper()
	for _, args := range [][]string{
		{"init"},
		{"config", "user.email", "t@example.invalid"},
		{"config", "user.name", "Test"},
	} {
		command := exec.Command("git", args...)
		command.Dir = root
		if out, err := command.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	if err := os.WriteFile(filepath.Join(root, "a.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{{"add", "a.txt"}, {"commit", "-m", "first"}} {
		command := exec.Command("git", args...)
		command.Dir = root
		if out, err := command.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
}

func additionalContext(t *testing.T, body []byte) string {
	t.Helper()
	var envelope struct {
		HookSpecificOutput struct {
			AdditionalContext string `json:"additionalContext"`
		} `json:"hookSpecificOutput"`
	}
	if err := json.Unmarshal(body, &envelope); err != nil {
		t.Fatalf("the answer is not an envelope: %s", body)
	}
	return envelope.HookSpecificOutput.AdditionalContext
}
