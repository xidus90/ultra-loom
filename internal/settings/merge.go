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
	"strings"
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
	claimed := map[string]map[int]bool{}

	for _, entry := range wanted {
		rawList, listed := hooks[entry.Event]
		list, ok := rawList.([]any)
		if listed && !ok {
			return Result{}, fmt.Errorf("settings.json: [hooks].%s is not a list", entry.Event)
		}
		if claimed[entry.Event] == nil {
			claimed[entry.Event] = map[int]bool{}
		}
		index, foreign := find(list, entry.Matcher, entry.Command, claimed[entry.Event])
		if foreign {
			skipped = append(skipped, fmt.Sprintf(
				"%s/%s: a hook of this project is already there", entry.Event, entry.Matcher))
			continue
		}
		block := blockFor(entry)
		if index >= 0 {
			list[index] = block
			claimed[entry.Event][index] = true
		} else {
			list = append(list, block)
			claimed[entry.Event][len(list)-1] = true
		}
		hooks[entry.Event] = list
	}
	if present || len(hooks) > 0 {
		root["hooks"] = hooks
	}
	out, err := json.MarshalIndent(root, "", "  ")
	if err != nil {
		return Result{}, err
	}
	return Result{Merged: append(out, '\n'), Skipped: skipped}, nil
}

func find(list []any, matcher, cmd string, claimed map[int]bool) (int, bool) {
	targetTool := toolKey(cmd)
	firstOwnedIndex := -1

	for index, raw := range list {
		item, ok := raw.(map[string]any)
		if !ok || matcherOf(item) != matcher {
			continue
		}
		owned, _ := item[OwnerKey].(bool)
		if owned {
			if !claimed[index] {
				if toolKey(firstCommand(item)) == targetTool {
					return index, false
				}
				if firstOwnedIndex == -1 {
					firstOwnedIndex = index
				}
			}
		} else {
			if firstOwnedIndex == -1 {
				// Foreign entry appeared before any of our own entries
				return -1, true
			}
		}
	}

	if firstOwnedIndex >= 0 {
		return firstOwnedIndex, false
	}

	return -1, false
}

func firstCommand(item map[string]any) string {
	hooks, ok := item["hooks"].([]any)
	if !ok || len(hooks) == 0 {
		return ""
	}
	first, ok := hooks[0].(map[string]any)
	if !ok {
		return ""
	}
	cmd, _ := first["command"].(string)
	return cmd
}

func toolKey(cmd string) string {
	words := strings.Fields(cmd)
	for i := 0; i < len(words); i++ {
		w := words[i]
		clean := strings.ToLower(strings.Trim(w, `"'`))
		clean = strings.TrimSuffix(clean, ".exe")
		if clean == "--project" || clean == "--script" {
			i++
			continue
		}
		if clean == "uv" || clean == "uvx" || clean == "npx" || clean == "bash" || clean == "sh" ||
			clean == "run" {
			continue
		}
		if clean == "ultraloom" && i+1 < len(words) {
			sub := strings.ToLower(strings.Trim(words[i+1], `"'`))
			if (sub == "hook" || sub == "policy") && i+2 < len(words) {
				return sub + "_" + strings.ToLower(strings.Trim(words[i+2], `"'`))
			}
			return sub
		}
		if clean == "dotnet" && i+1 < len(words) {
			sub := strings.ToLower(strings.Trim(words[i+1], `"'`))
			return "dotnet_" + sub
		}
		if clean == "cargo" && i+1 < len(words) {
			sub := strings.ToLower(strings.Trim(words[i+1], `"'`))
			return "cargo_" + sub
		}
		return clean
	}
	return cmd
}

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
