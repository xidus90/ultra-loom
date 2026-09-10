package journal_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xidus90/ultra-loom/internal/journal"
)

const pausedLine = `{"delta":{},"detail":"which colour?","effort":null,"input_hash":"h1","kind":"gate","node":"ask","outcome":"paused","seconds":0.1,"tokens":0,"tools":null}`

const okLine = `{"delta":{"n":1},"detail":null,"effort":"low","input_hash":"h0","kind":"work","node":"build","outcome":"ok","seconds":2.5,"tokens":12,"tools":"bash"}`

// An absent file reads as empty and is not an error: journal.py's `entries`
// decides this, and a session that never ran anything still starts.
func TestEntriesOfMissingFileIsEmpty(t *testing.T) {
	got, err := journal.Entries(filepath.Join(t.TempDir(), "nothing.jsonl"))
	if err != nil {
		t.Fatalf("an absent file is not an error: %v", err)
	}
	if len(got) != 0 {
		t.Fatalf("expected no entries, got %d", len(got))
	}
}

func TestEntriesReadsInOrderAndSkipsBlankLines(t *testing.T) {
	path := write(t, okLine+"\n\n"+pausedLine+"\n")

	got, err := journal.Entries(path)
	if err != nil {
		t.Fatal(err)
	}

	if len(got) != 2 {
		t.Fatalf("expected 2 entries, got %d", len(got))
	}
	if got[0].Node != "build" || got[1].Node != "ask" {
		t.Fatalf("order lost: %s then %s", got[0].Node, got[1].Node)
	}
	if got[0].Tools == nil || *got[0].Tools != "bash" {
		t.Fatalf("tools not read: %+v", got[0].Tools)
	}
	if got[1].Tools != nil {
		t.Fatalf("a null tools is absent, got %q", *got[1].Tools)
	}
	if got[0].Delta["n"] != float64(1) {
		t.Fatalf("delta not read: %+v", got[0].Delta)
	}
}

// A damaged line is named with its number and not swallowed. journal.py raises
// JournalError with exactly this shape, and session_start.py prints it and
// carries on with the other runs.
func TestEntriesNamesTheDamagedLine(t *testing.T) {
	path := write(t, okLine+"\n{not json\n")

	_, err := journal.Entries(path)

	if err == nil {
		t.Fatal("expected an error for a line that is not an entry")
	}
	if !strings.Contains(err.Error(), "line 2") {
		t.Fatalf("the error names the line number, got %v", err)
	}
}

// A blank line is skipped but still counted, so the number in an error is the
// line a human finds in the file. journal.py enumerates before it filters.
func TestEntriesCountsBlankLinesWhenNumbering(t *testing.T) {
	path := write(t, "\n\n{not json\n")

	_, err := journal.Entries(path)

	if err == nil {
		t.Fatal("expected an error for a line that is not an entry")
	}
	if !strings.Contains(err.Error(), "line 3") {
		t.Fatalf("blank lines count towards the number, got %v", err)
	}
}

// A line of arbitrary length is read, because nothing caps what `append`
// writes: `delta` is a node's own output. A reader with a ceiling the writer
// does not share would turn a legitimate run into one that cannot be
// announced, so there is no ceiling here either.
func TestEntriesReadsAVeryLongLine(t *testing.T) {
	node := strings.Repeat("x", 5*1024*1024)
	path := write(t, `{"node":"`+node+`","outcome":"ok"}`+"\n")

	got, err := journal.Entries(path)
	if err != nil {
		t.Fatalf("a long line is not damage: %v", err)
	}
	if len(got) != 1 || got[0].Node != node {
		t.Fatalf("expected the long node name back, got %d entries", len(got))
	}
}

// A path that exists but cannot be read is an error, not an empty journal: only
// absence means "this run wrote nothing yet".
func TestEntriesReportsAnUnreadablePath(t *testing.T) {
	if _, err := journal.Entries(t.TempDir()); err == nil {
		t.Fatal("a directory is not a readable journal")
	}
}

func write(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "run.jsonl")
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}
