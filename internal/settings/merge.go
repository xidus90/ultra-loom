// Package settings adds hook entries to a file that belongs to someone else.
//
// Identity is (event, matcher, owner), not the command line: a changed
// command is still the same entry, and adding a second one next to a
// project's own hook would make both fire. Two parallel quality.py runs hung
// overnight on 2026-08-27 for exactly that reason.
//
// The JSON is carried as map[string]any throughout, and that is the reason
// this package may use it at all: settings.json belongs to the project, and
// everything in it that is not one of our own hook entries has to come back
// out byte for byte the way it went in. A typed struct would model the keys
// this tool knows about and drop the rest on the next encode -- somebody's
// permissions, somebody's env, somebody's model setting, gone without a word.
// The untyped map is the round trip.
//
// Where the file is not shaped the way this expects, nothing is repaired.
// A `"hooks": []` is someone's decision or someone's mistake; writing an
// object over it would take their configuration with it, and a settings.json
// silently rewritten is worse than an init that stops and says so.
package settings

import (
	"encoding/json"
	"fmt"
)

// OwnerKey marks an entry as written by this tool. Its absence means the
// entry belongs to the project, and then it is never touched.
const OwnerKey = "ultraloomOwned"

type Entry struct {
	Event   string
	Matcher string
	Command string
	Timeout int
}

type Result struct {
	Merged  []byte
	Skipped []string
}

func Merge(existing []byte, wanted []Entry) (Result, error) {
	root := map[string]any{}
	if len(existing) > 0 {
		if err := json.Unmarshal(existing, &root); err != nil {
			return Result{}, fmt.Errorf("settings.json is not valid JSON: %w", err)
		}
	}
	// A JSON null is valid and decodes to a nil map -- not to an empty one.
	// Every write below would panic on it, and a file holding `null` is the
	// same starting point as no file at all.
	if root == nil {
		root = map[string]any{}
	}
	raw, present := root["hooks"]
	hooks, ok := raw.(map[string]any)
	if present && !ok {
		return Result{}, fmt.Errorf("settings.json: [hooks] is not a table")
	}
	if hooks == nil {
		hooks = map[string]any{}
	}
	var skipped []string
	for _, entry := range wanted {
		rawList, listed := hooks[entry.Event]
		list, ok := rawList.([]any)
		if listed && !ok {
			return Result{}, fmt.Errorf("settings.json: [hooks].%s is not a list", entry.Event)
		}
		index, foreign := find(list, entry.Matcher)
		if foreign {
			skipped = append(skipped, fmt.Sprintf(
				"%s/%s: a hook of this project is already there", entry.Event, entry.Matcher))
			continue
		}
		block := blockFor(entry)
		if index >= 0 {
			list[index] = block
		} else {
			list = append(list, block)
		}
		hooks[entry.Event] = list
	}
	// Only when there is something to say: a file that had no hooks and got
	// none must not come back carrying an empty table this tool put there.
	if present || len(hooks) > 0 {
		root["hooks"] = hooks
	}
	out, err := json.MarshalIndent(root, "", "  ")
	// Unreachable, and kept for the day that stops being true: root holds only
	// what json.Unmarshal produced and what blockFor built, and neither can put
	// a value in there that the encoder refuses. No test can force this branch.
	if err != nil {
		return Result{}, err
	}
	return Result{Merged: append(out, '\n'), Skipped: skipped}, nil
}

// find returns the index of our own entry for this matcher, or -1; the
// second value says a foreign entry holds the slot.
//
// The first entry on the slot decides, ours or not. Where a project has both
// -- its own hook and one of ours under the same matcher -- replacing ours
// would leave two hooks firing, which is what the package comment is about.
// Reporting the slot as taken is the safer of the two.
func find(list []any, matcher string) (int, bool) {
	for index, raw := range list {
		item, ok := raw.(map[string]any)
		if !ok {
			// Not an entry at all. Left where it is, and read as nothing:
			// guessing at its matcher would be repairing someone else's file.
			continue
		}
		if matcherOf(item) != matcher {
			continue
		}
		if owned, _ := item[OwnerKey].(bool); owned {
			return index, false
		}
		return -1, true
	}
	return -1, false
}

// matcherOf reads a missing matcher as an empty one: Stop and SessionStart
// carry none, and the two spellings are the same slot.
func matcherOf(item map[string]any) string {
	matcher, _ := item["matcher"].(string)
	return matcher
}

func blockFor(entry Entry) map[string]any {
	command := map[string]any{"type": "command", "command": entry.Command}
	if entry.Timeout > 0 {
		command["timeout"] = entry.Timeout
	}
	block := map[string]any{OwnerKey: true, "hooks": []any{command}}
	if entry.Matcher != "" {
		block["matcher"] = entry.Matcher
	}
	return block
}
