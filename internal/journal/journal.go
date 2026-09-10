// Package journal reads the run journal: one JSONL line per node.
//
// The reading half only. `session-start` announces what is waiting and writes
// nothing, and the writer -- with the input hashing a resume depends on --
// belongs to the stages that walk a run.
package journal

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

// Entry is journal.py's Entry, field for field, in the JSON spelling on disk.
//
// Tools, Effort and Detail are pointers because the Python side writes
// `str | None` there and the difference carries a decision: `Pending` reads a
// nil Detail as "this pause asked nothing", which is not the same as an empty
// question.
type Entry struct {
	Node      string         `json:"node"`
	Kind      string         `json:"kind"`
	InputHash string         `json:"input_hash"`
	Delta     map[string]any `json:"delta"`
	Outcome   string         `json:"outcome"`
	Tools     *string        `json:"tools"`
	Effort    *string        `json:"effort"`
	Tokens    int            `json:"tokens"`
	Seconds   float64        `json:"seconds"`
	Detail    *string        `json:"detail"`
}

// Entries is journal.py's `entries`: every line, in order.
//
// An absent file is empty and not an error, and a line that cannot be decoded
// ends the read with its number named. Both are that module's decisions: a run
// that never started has no journal, and one unreadable line makes the whole
// journal unreadable rather than being skipped -- a journal read past its
// damage would answer about a run nobody can reconstruct. The caller decides
// what that costs; `session_start.py` prints the error and carries on with the
// other runs, so one damaged file hides its own lines and no others.
//
// The check is narrower than the Python one: `Entry(**json.loads(line))` there
// also refuses a well-formed object whose keys do not match the dataclass,
// while unmarshalling into a struct accepts a missing key as a zero value and
// ignores an unknown one. It is stricter about types in return -- Python takes
// a string for `tokens`, this does not.
//
// The whole file is read at once, as `read_text` does, and no line length is
// refused: nothing caps what `append` writes, since `delta` is a node's own
// output.
func Entries(path string) ([]Entry, error) {
	text, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("reading %s: %w", path, err)
	}

	var found []Entry
	// A blank line is skipped but still counted, so the number in an error is
	// the line a reader finds in the file.
	for number, line := range strings.Split(string(text), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		var entry Entry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			return nil, fmt.Errorf("%s: line %d is not a journal entry: %w", path, number+1, err)
		}
		found = append(found, entry)
	}
	return found, nil
}
