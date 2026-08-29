package settings

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestAMissingEventIsAdded(t *testing.T) {
	got, err := Merge([]byte(`{}`), []Entry{{Event: "PreToolUse", Matcher: "Write", Command: "guard"}})
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if !strings.Contains(string(got.Merged), "PreToolUse") {
		t.Fatal("the entry was not added")
	}
}

func TestOurOwnEntryIsReplacedNotDuplicated(t *testing.T) {
	before := `{"hooks":{"PreToolUse":[{"matcher":"Write","ultraLoomOwned":true,
	  "hooks":[{"type":"command","command":"old"}]}]}}`
	got, err := Merge([]byte(before), []Entry{{Event: "PreToolUse", Matcher: "Write", Command: "new"}})
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if strings.Count(string(got.Merged), "\"matcher\"") != 1 {
		t.Fatalf("want one entry, got %s", got.Merged)
	}
	if !strings.Contains(string(got.Merged), "new") {
		t.Fatal("the entry was not replaced")
	}
}

func TestAForeignEntryIsLeftAloneAndReported(t *testing.T) {
	before := `{"hooks":{"PostToolUse":[{"matcher":"Write|Edit",
	  "hooks":[{"type":"command","command":"bash run.sh post_edit.py"}]}]}}`
	got, err := Merge([]byte(before), []Entry{{Event: "PostToolUse", Matcher: "Write|Edit", Command: "ours"}})
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if strings.Contains(string(got.Merged), "ours") {
		t.Fatal("a second hook was added next to a foreign one")
	}
	if len(got.Skipped) != 1 {
		t.Fatalf("skipped = %v, want one report", got.Skipped)
	}
}

func TestForeignKeysSurvive(t *testing.T) {
	before := `{"permissions":{"defaultMode":"auto"},"model":"opus"}`
	got, err := Merge([]byte(before), nil)
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	var after map[string]any
	if err := json.Unmarshal(got.Merged, &after); err != nil {
		t.Fatalf("result is not JSON: %v", err)
	}
	if _, ok := after["permissions"]; !ok {
		t.Fatal("permissions were lost")
	}
	if after["model"] != "opus" {
		t.Fatal("model was lost")
	}
}

func TestBrokenJsonIsRefused(t *testing.T) {
	if _, err := Merge([]byte("{not json"), nil); err == nil {
		t.Fatal("want an error, not a repair")
	}
}

// TestAMatcherlessEntryDoesNotClaimEveryEntry: Stop and SessionStart carry no
// matcher, and an entry that matches everything would report the first
// unrelated hook in the list as holding its slot.
func TestAMatcherlessEntryDoesNotClaimEveryEntry(t *testing.T) {
	before := `{"hooks":{"Stop":[{"matcher":"Write","hooks":[{"type":"command","command":"theirs"}]}]}}`
	got, err := Merge([]byte(before), []Entry{{Event: "Stop", Command: "ours"}})
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if len(got.Skipped) != 0 {
		t.Fatalf("skipped = %v, want the unrelated matcher left out of it", got.Skipped)
	}
	if !strings.Contains(string(got.Merged), "ours") {
		t.Fatalf("merged = %s, want our matcherless entry added", got.Merged)
	}
}

// TestOurOwnMatcherlessEntryIsStillReplaced is the same lookup from the other
// side: a missing matcher and an empty one are the same slot.
func TestOurOwnMatcherlessEntryIsStillReplaced(t *testing.T) {
	before := `{"hooks":{"Stop":[{"ultraLoomOwned":true,"hooks":[{"type":"command","command":"old"}]}]}}`
	got, err := Merge([]byte(before), []Entry{{Event: "Stop", Command: "new"}})
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if strings.Contains(string(got.Merged), "old") {
		t.Fatalf("merged = %s, want the old command gone", got.Merged)
	}
	if strings.Count(string(got.Merged), "command\":") != 1 {
		t.Fatalf("merged = %s, want one command", got.Merged)
	}
}

// TestHooksOfTheWrongShapeAreRefusedNotOverwritten: the file belongs to
// someone else. Reading `"hooks": []` as "nothing configured" and writing an
// object over it is the same silent repair TestBrokenJsonIsRefused forbids.
func TestHooksOfTheWrongShapeAreRefusedNotOverwritten(t *testing.T) {
	if _, err := Merge([]byte(`{"hooks":[]}`), nil); err == nil {
		t.Fatal("want an error, not a silent overwrite of [hooks]")
	}
}

func TestAnEventOfTheWrongShapeIsRefusedNotOverwritten(t *testing.T) {
	before := `{"hooks":{"PreToolUse":{"matcher":"Write"}}}`
	_, err := Merge([]byte(before), []Entry{{Event: "PreToolUse", Matcher: "Write", Command: "ours"}})
	if err == nil {
		t.Fatal("want an error, not a silent overwrite of the event")
	}
	if !strings.Contains(err.Error(), "PreToolUse") {
		t.Fatalf("err = %v, want the event named", err)
	}
}

// TestAFileWithoutHooksStaysWithoutThem: init must not leave its fingerprint
// on a file it had nothing to add to.
func TestAFileWithoutHooksStaysWithoutThem(t *testing.T) {
	got, err := Merge([]byte(`{"model":"opus"}`), nil)
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if strings.Contains(string(got.Merged), "hooks") {
		t.Fatalf("merged = %s, want no empty hooks table", got.Merged)
	}
}

func TestAnEmptyFileBecomesOneWithJustOurHook(t *testing.T) {
	got, err := Merge(nil, []Entry{{Event: "Stop", Command: "ours", Timeout: 60}})
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	var after map[string]any
	if err := json.Unmarshal(got.Merged, &after); err != nil {
		t.Fatalf("result is not JSON: %v", err)
	}
	if !strings.Contains(string(got.Merged), `"timeout": 60`) {
		t.Fatalf("merged = %s, want the timeout carried", got.Merged)
	}
}

// TestATimeoutOfZeroIsLeftOut: absent means "the default", and writing a zero
// would mean "no time at all".
func TestATimeoutOfZeroIsLeftOut(t *testing.T) {
	got, err := Merge(nil, []Entry{{Event: "Stop", Command: "ours"}})
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if strings.Contains(string(got.Merged), "timeout") {
		t.Fatalf("merged = %s, want no timeout key", got.Merged)
	}
}

func TestANullFileIsTreatedAsAnEmptyOne(t *testing.T) {
	got, err := Merge([]byte("null"), []Entry{{Event: "Stop", Command: "ours"}})
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if !strings.Contains(string(got.Merged), "ours") {
		t.Fatalf("merged = %s, want the entry added", got.Merged)
	}
}

// TestAForeignEntryOfTheWrongShapeIsSkippedNotRead: a list holding a string
// is someone else's mistake, not ours to repair -- but it must not be read as
// an empty slot either.
func TestAnEntryThatIsNotAnObjectIsIgnoredForTheLookup(t *testing.T) {
	before := `{"hooks":{"Stop":["nonsense"]}}`
	got, err := Merge([]byte(before), []Entry{{Event: "Stop", Command: "ours"}})
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if !strings.Contains(string(got.Merged), "nonsense") {
		t.Fatalf("merged = %s, want the foreign item kept", got.Merged)
	}
	if !strings.Contains(string(got.Merged), "ours") {
		t.Fatalf("merged = %s, want our entry added beside it", got.Merged)
	}
}

// The rule this package exists for, in the one arrangement nothing tested:
// our entry and a foreign one on the same matcher. The first on the slot
// decides, so here ours is updated and the foreign one is left exactly where
// it is -- the mirror of the case where the foreign entry comes first and the
// slot is reported as taken.
func TestOursFirstOnASharedSlotKeepsTheSlot(t *testing.T) {
	existing := []byte(`{"hooks":{"PreToolUse":[
		{"matcher":"Bash","ultraLoomOwned":true,"hooks":[{"type":"command","command":"old"}]},
		{"matcher":"Bash","hooks":[{"type":"command","command":"theirs"}]}
	]}}`)
	result, err := Merge(existing, []Entry{{Event: "PreToolUse", Matcher: "Bash", Command: "new"}})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Skipped) != 0 {
		t.Fatalf("a slot we hold was reported as taken: %v", result.Skipped)
	}
	var root map[string]any
	if err := json.Unmarshal(result.Merged, &root); err != nil {
		t.Fatal(err)
	}
	list, ok := root["hooks"].(map[string]any)["PreToolUse"].([]any)
	if !ok || len(list) != 2 {
		t.Fatalf("the list lost or gained an entry: %s", result.Merged)
	}
	ours, _ := list[0].(map[string]any)
	if commandOf(t, ours) != "new" {
		t.Fatalf("our own entry was not updated: %s", result.Merged)
	}
	theirs, _ := list[1].(map[string]any)
	if _, owned := theirs[OwnerKey]; owned {
		t.Fatalf("the foreign entry was claimed: %s", result.Merged)
	}
	if commandOf(t, theirs) != "theirs" {
		t.Fatalf("the foreign entry was rewritten: %s", result.Merged)
	}
}

func commandOf(t *testing.T, block map[string]any) string {
	t.Helper()
	hooks, ok := block["hooks"].([]any)
	if !ok || len(hooks) != 1 {
		t.Fatalf("not one hook in %v", block)
	}
	command, _ := hooks[0].(map[string]any)
	text, _ := command["command"].(string)
	return text
}

func TestMultipleOurOwnEntriesUnderSameEventAndMatcherAreAddedAndReplaced(t *testing.T) {
	wanted := []Entry{
		{Event: "PostToolUse", Matcher: "Write|Edit", Command: "uv run ruff check .", Timeout: 15},
		{Event: "PostToolUse", Matcher: "Write|Edit", Command: "uv run dmypy run", Timeout: 30},
	}
	got, err := Merge([]byte(`{}`), wanted)
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	var root map[string]any
	if err := json.Unmarshal(got.Merged, &root); err != nil {
		t.Fatal(err)
	}
	list := root["hooks"].(map[string]any)["PostToolUse"].([]any)
	if len(list) != 2 {
		t.Fatalf("want 2 entries in list, got %d: %s", len(list), got.Merged)
	}

	// Re-merge with updated command for ruff
	updated := []Entry{
		{Event: "PostToolUse", Matcher: "Write|Edit", Command: "uv run ruff check --fix .", Timeout: 15},
		{Event: "PostToolUse", Matcher: "Write|Edit", Command: "uv run dmypy run", Timeout: 30},
	}
	got2, err := Merge(got.Merged, updated)
	if err != nil {
		t.Fatalf("Merge updated: %v", err)
	}
	var root2 map[string]any
	if err := json.Unmarshal(got2.Merged, &root2); err != nil {
		t.Fatal(err)
	}
	list2 := root2["hooks"].(map[string]any)["PostToolUse"].([]any)
	if len(list2) != 2 {
		t.Fatalf("want 2 entries in list after update, got %d: %s", len(list2), got2.Merged)
	}
	if !strings.Contains(string(got2.Merged), "ruff check --fix .") {
		t.Fatalf("updated command missing: %s", got2.Merged)
	}
}

func TestToolKeyExtraction(t *testing.T) {
	cases := map[string]string{
		"uv run ruff check .":               "ruff",
		"uv run dmypy run -- --no-pretty":   "dmypy",
		"uvx gdlint .":                      "gdlint",
		"dotnet format --verify-no-changes": "dotnet_format",
		"dotnet build":                      "dotnet_build",
		"cargo clippy -- -D warnings":       "cargo_clippy",
		"cargo fmt --check":                 "cargo_fmt",
		"npx eslint .":                      "eslint",
		"npx tsc --noEmit":                  "tsc",
		"go vet ./...":                      "go_vet",
		`uv run --project "vendor/ultraloom" ultraloom hook post-edit`: "hook_post-edit",
		`ultraloom policy hook`: "policy_hook",
		`ultraloom sync`:        "sync",
		"":                      "",
	}
	for cmd, want := range cases {
		if got := toolKey(cmd); got != want {
			t.Errorf("toolKey(%q) = %q, want %q", cmd, got, want)
		}
	}
}

func TestFirstCommandEdgeCases(t *testing.T) {
	if firstCommand(nil) != "" {
		t.Fatal("want empty string for nil")
	}
	if firstCommand(map[string]any{"hooks": "not a list"}) != "" {
		t.Fatal("want empty string for invalid hooks")
	}
	if firstCommand(map[string]any{"hooks": []any{"not a map"}}) != "" {
		t.Fatal("want empty string for non-map hook")
	}
}

func TestMergePreservesExactLifecycleOrder(t *testing.T) {
	entries := []Entry{
		{Event: "Stop", Command: "stop-cmd"},
		{Event: "SessionStart", Command: "session-cmd"},
		{Event: "SubagentStop", Command: "sub-stop-cmd"},
		{Event: "PreToolUse", Command: "pre-cmd"},
		{Event: "SubagentStart", Command: "sub-start-cmd"},
		{Event: "PostToolUse", Command: "post-cmd"},
	}
	res, err := Merge(nil, entries)
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	merged := string(res.Merged)

	// Check order of occurrences in JSON
	posSessionStart := strings.Index(merged, `"SessionStart"`)
	posPreToolUse := strings.Index(merged, `"PreToolUse"`)
	posPostToolUse := strings.Index(merged, `"PostToolUse"`)
	posSubagentStart := strings.Index(merged, `"SubagentStart"`)
	posSubagentStop := strings.Index(merged, `"SubagentStop"`)
	posStop := strings.Index(merged, `"Stop"`)

	if !(posSessionStart < posPreToolUse &&
		posPreToolUse < posPostToolUse &&
		posPostToolUse < posSubagentStart &&
		posSubagentStart < posSubagentStop &&
		posSubagentStop < posStop) {
		t.Fatalf("Hook lifecycle order violated in settings JSON:\n%s", merged)
	}
}

func TestHookBlockAndCommandKeyOrder(t *testing.T) {
	entries := []Entry{
		{Event: "PostToolUse", Matcher: "Write|Edit", Command: "run.sh", Timeout: 180},
	}
	res, err := Merge(nil, entries)
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	merged := string(res.Merged)

	// 1. In outer block: "matcher" must be before "hooks"
	posMatcher := strings.Index(merged, `"matcher"`)
	posHooks := strings.Index(merged, `"hooks": [`)
	if !(posMatcher >= 0 && posHooks >= 0 && posMatcher < posHooks) {
		t.Fatalf("want matcher before hooks:\n%s", merged)
	}

	// 2. In command block: "type" before "command" before "timeout"
	posType := strings.Index(merged, `"type"`)
	posCommand := strings.Index(merged, `"command"`)
	posTimeout := strings.Index(merged, `"timeout"`)
	if !(posType >= 0 && posCommand >= 0 && posTimeout >= 0 &&
		posType < posCommand && posCommand < posTimeout) {
		t.Fatalf("want type < command < timeout:\n%s", merged)
	}
}

func TestFormatBlockAndCommandFallbacks(t *testing.T) {
	// 1. Existing block that is a string instead of map
	rawJSON := `{"hooks":{"CustomEvent":["not-a-map", {"hooks": "not-a-list"}, {"hooks": ["not-a-cmd-map"]}]}}`
	res, err := Merge([]byte(rawJSON), nil)
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if !strings.Contains(string(res.Merged), "not-a-map") {
		t.Fatalf("fallback failed:\n%s", res.Merged)
	}
}

func TestEmptyHooksObject(t *testing.T) {
	res, err := Merge([]byte(`{"hooks":{}}`), nil)
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	if !strings.Contains(string(res.Merged), `"hooks": {}`) {
		t.Fatalf("want empty hooks object, got:\n%s", res.Merged)
	}
}

func TestTopLevelKeyOrderPreserved(t *testing.T) {
	before := `{"enabledPlugins":{"test":true},"permissions":{"allow":["bash"]},"hooks":{}}`
	res, err := Merge([]byte(before), []Entry{{Event: "SessionStart", Command: "session_start"}})
	if err != nil {
		t.Fatalf("Merge: %v", err)
	}
	merged := string(res.Merged)
	posPlugins := strings.Index(merged, `"enabledPlugins"`)
	posPerms := strings.Index(merged, `"permissions"`)
	posHooks := strings.Index(merged, `"hooks"`)

	if !(posPlugins >= 0 && posPerms >= 0 && posHooks >= 0 &&
		posPlugins < posPerms && posPerms < posHooks) {
		t.Fatalf("top-level key order was changed:\n%s", merged)
	}
}

func TestExtractTopEntriesAndFormatRootEdgeCases(t *testing.T) {
	// 1. Empty and non-object inputs
	if entries := extractTopEntries(nil); entries != nil {
		t.Fatalf("want nil for nil input, got %v", entries)
	}
	if entries := extractTopEntries([]byte("[1,2,3]")); entries != nil {
		t.Fatalf("want nil for array input, got %v", entries)
	}
	if entries := extractTopEntries([]byte("{broken")); len(entries) != 0 {
		t.Fatalf("want 0 entries for broken json, got %v", entries)
	}

	// 2. formatRoot with completely empty inputs
	out, err := formatRoot(nil, nil)
	if err != nil || string(out) != "{}\n" {
		t.Fatalf("formatRoot empty: out=%q, err=%v", string(out), err)
	}

	// 3. formatRoot with unindented / raw unformattable text
	entries := []topEntry{{key: "raw", raw: json.RawMessage(`"simple"`)}}
	out2, err := formatRoot(entries, map[string]any{"other": 123})
	if err != nil || !strings.Contains(string(out2), `"raw": "simple"`) || !strings.Contains(string(out2), `"other": 123`) {
		t.Fatalf("formatRoot raw text failed: out=%q, err=%v", string(out2), err)
	}
}
