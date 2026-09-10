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

// journal.py's Entry is a dataclass with no defaults, so a line missing any of
// the ten keys raises TypeError there and comes back as a JournalError naming
// the line. Accepting it as a zero value would let a paused run whose last line
// lost its `outcome` read as "nothing waiting" -- unannounced, and silently.
func TestEntriesNamesALineMissingAKey(t *testing.T) {
	short := `{"delta":{},"detail":null,"effort":null,"input_hash":"h1","kind":"gate","node":"ask","seconds":0.1,"tokens":0,"tools":null}`
	path := write(t, okLine+"\n"+short+"\n")

	_, err := journal.Entries(path)

	if err == nil {
		t.Fatal("a line missing a key is not an entry")
	}
	if !strings.Contains(err.Error(), "line 2") {
		t.Fatalf("the error names the line number, got %v", err)
	}
	if !strings.Contains(err.Error(), "outcome") {
		t.Fatalf("the error names the missing key, got %v", err)
	}
}

// A key nobody reads means the writer and this reader disagree about the
// format, which journal.py also refuses -- `Entry(**...)` raises TypeError on an
// unexpected keyword.
func TestEntriesNamesALineWithAnUnknownKey(t *testing.T) {
	extra := strings.Replace(okLine, `{"delta"`, `{"mood":"brisk","delta"`, 1)
	path := write(t, extra+"\n")

	_, err := journal.Entries(path)

	if err == nil {
		t.Fatal("an unknown key is a disagreement about the format")
	}
	if !strings.Contains(err.Error(), "line 1") || !strings.Contains(err.Error(), "mood") {
		t.Fatalf("the error names the line and the key, got %v", err)
	}
}

// `null` is a value and absence is damage: the Python side writes `str | None`,
// so the key is always there and only its value says "nothing".
func TestEntriesReadsANullValueAsAbsent(t *testing.T) {
	got, err := journal.Entries(write(t, pausedLine+"\n"))
	if err != nil {
		t.Fatalf("a null value is not damage: %v", err)
	}
	if len(got) != 1 {
		t.Fatalf("expected one entry, got %d", len(got))
	}
	if got[0].Tools != nil || got[0].Effort != nil {
		t.Fatalf("a null reads as absent, got %+v", got[0])
	}
	if got[0].Detail == nil || *got[0].Detail != "which colour?" {
		t.Fatalf("the question next to those nulls is lost: %+v", got[0])
	}
}

// The one place this reader is stricter than journal.py: Python accepts a
// string in `tokens` because it never checks the annotation.
func TestEntriesNamesALineWithAMistypedValue(t *testing.T) {
	wrong := strings.Replace(okLine, `"tokens":12`, `"tokens":"twelve"`, 1)

	_, err := journal.Entries(write(t, wrong+"\n"))

	if err == nil {
		t.Fatal("a string where a count belongs is not an entry")
	}
	if !strings.Contains(err.Error(), "line 1") {
		t.Fatalf("the error names the line number, got %v", err)
	}
}

// A line of arbitrary length is read, because nothing caps what `append`
// writes: `delta` is a node's own output. A reader with a ceiling the writer
// does not share would turn a legitimate run into one that cannot be
// announced, so there is no ceiling here either.
func TestEntriesReadsAVeryLongLine(t *testing.T) {
	// A whole entry, not a partial one: this test is about the line's length,
	// and a line missing keys would also fail a reader that checked for them.
	node := strings.Repeat("x", 5*1024*1024)
	line := `{"delta":{},"detail":null,"effort":"low","input_hash":"h0","kind":"work","node":"` +
		node + `","outcome":"ok","seconds":2.5,"tokens":12,"tools":"bash"}`
	path := write(t, line+"\n")

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
