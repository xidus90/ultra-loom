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
	"slices"
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
// A well-formed object whose keys do not match `Entry` is damage too, the same
// way `Entry(**json.loads(line))` raises TypeError for a missing or an
// unexpected keyword. It is stricter about types on top of that -- Python never
// checks its annotations and takes a string for `tokens`, this does not.
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
		entry, err := decode(line)
		if err != nil {
			return nil, fmt.Errorf("%s: line %d is not a journal entry: %w", path, number+1, err)
		}
		found = append(found, entry)
	}
	return found, nil
}

// entryKeys are the ten keys `Entry` is written from, in the order journal.py
// declares its fields.
//
// The list is spelled out rather than derived from the struct tags because it
// is the contract with the Python writer, not a restatement of this file: a
// field added here without a writer that writes it should read as a
// disagreement, which a derived list would hide.
var entryKeys = []string{
	"node", "kind", "input_hash", "delta", "outcome",
	"tools", "effort", "tokens", "seconds", "detail",
}

// decode turns one line into an Entry, or says why it is not one.
//
// The object is read twice on purpose: the first pass sees which keys are
// *present*, which unmarshalling into a struct cannot tell apart from absent.
// The difference matters because `tools`, `effort` and `detail` are `str | None`
// on the Python side -- a `null` there is a written value and its key is always
// there, so absence is damage and `null` is not.
func decode(line string) (Entry, error) {
	var keyed map[string]json.RawMessage
	if err := json.Unmarshal([]byte(line), &keyed); err != nil {
		return Entry{}, err
	}

	var missing []string
	for _, key := range entryKeys {
		if _, ok := keyed[key]; !ok {
			missing = append(missing, key)
		}
	}
	if len(missing) > 0 {
		return Entry{}, fmt.Errorf("no value for %s", strings.Join(missing, ", "))
	}

	var unknown []string
	for key := range keyed {
		if !slices.Contains(entryKeys, key) {
			unknown = append(unknown, key)
		}
	}
	if len(unknown) > 0 {
		// Sorted, because a map's order is not stable and an error message that
		// changed between runs would be one no test could name.
		slices.Sort(unknown)
		return Entry{}, fmt.Errorf("unknown key %s", strings.Join(unknown, ", "))
	}

	var entry Entry
	if err := json.Unmarshal([]byte(line), &entry); err != nil {
		return Entry{}, err
	}
	return entry, nil
}
