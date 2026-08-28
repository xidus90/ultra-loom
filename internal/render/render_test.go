package render

import (
	"flag"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"testing"

	"github.com/BurntSushi/toml"
	"github.com/xidus90/ultra-loom/internal/answers"
)

// update writes the golden files instead of comparing against them. A golden
// file nobody read freezes a mistake rather than catching one, so the run that
// creates them is a deliberate one.
var update = flag.Bool("update", false, "rewrite the golden files")

func fixture() answers.Answers {
	a := answers.Answers{}
	a.Project = answers.Project{
		Stacks: []string{"python", "uv"}, DocsLanguage: "de", CommitLanguage: "en"}
	a.Gates = answers.Gates{CoverageThreshold: 100, TestsInStop: true, TypesInStop: true}
	a.Gates.Wiki = answers.Wiki{Mode: "none"}
	// An answered-with-no list beside an answered-with-yes one: the empty one
	// is what pins nil apart from empty through the whole round trip.
	a.Policy = answers.Policy{
		ProtectedPaths:    []string{},
		ForbiddenCommands: []string{"git push", "pip install"},
	}
	a.Relevance = map[string][]string{"*.md": {}, "*.py": {"lint", "types"}}
	return a
}

func TestEveryGeneratedFileSaysWhereItCameFrom(t *testing.T) {
	files, err := Render(fixture())
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	for name, body := range files {
		if name == ".ultraloom/answers.toml" {
			continue // the source itself does not point at itself
		}
		if !strings.Contains(body, "generated from .ultraloom/answers.toml") {
			t.Fatalf("%s has no provenance header", name)
		}
	}
}

func TestRenderMatchesTheGoldenFiles(t *testing.T) {
	files, err := Render(fixture())
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	for name, body := range files {
		golden := filepath.Join("testdata", "golden", strings.ReplaceAll(name, "/", "_"))
		if *update {
			if err := os.WriteFile(golden, []byte(body), 0o644); err != nil {
				t.Fatalf("writing %s: %v", golden, err)
			}
			continue
		}
		want, err := os.ReadFile(golden)
		if err != nil {
			t.Fatalf("reading %s: %v -- run with -update to create it", golden, err)
		}
		if body != string(want) {
			t.Fatalf("%s differs from %s:\n--- got ---\n%s\n--- want ---\n%s",
				name, golden, body, want)
		}
	}
}

// TestTheRenderedAnswersReadBackAsTheyWentIn is the seam the whole design
// rests on: answers.toml is the source, everything else is output. A struct
// tag changed without the template following would break the second run --
// silently, because the first run would still look right.
func TestTheRenderedAnswersReadBackAsTheyWentIn(t *testing.T) {
	files, err := Render(fixture())
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	back, err := answers.Load([]byte(files[".ultraloom/answers.toml"]))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if !reflect.DeepEqual(back, fixture()) {
		t.Fatalf("round trip changed the answers:\ngot  %+v\nwant %+v", back, fixture())
	}
}

// TestAQuestionNeverAskedStaysUnaskedAndOneDeclinedStaysAnswered is the same
// distinction from the other side: nil is a question the interview still owes,
// an empty list is one it already got a no to.
func TestAQuestionNeverAskedStaysUnaskedAndOneDeclinedStaysAnswered(t *testing.T) {
	unasked := fixture()
	unasked.Policy.ProtectedPaths = nil
	files, err := Render(unasked)
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	back, err := answers.Load([]byte(files[".ultraloom/answers.toml"]))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if back.Policy.ProtectedPaths != nil {
		t.Fatalf("protected_paths = %v, want it left out entirely", back.Policy.ProtectedPaths)
	}
	if back.Policy.ForbiddenCommands == nil {
		t.Fatal("forbidden_commands came back nil, and the question would be asked again")
	}
}

// TestAForbiddenCommandBecomesARuleThatBitesInTheMiddleOfALine carries over
// what ultraloom's own config.toml learned the hard way: an anchored `^git
// push` lets through exactly the form this is about, `git commit && git push`.
func TestAForbiddenCommandBecomesARuleThatBitesInTheMiddleOfALine(t *testing.T) {
	files, err := Render(fixture())
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	policy := files[".ultraloom/policy.toml"]
	if !strings.Contains(policy, `\s*pip\s+install(?![\w-])`) {
		t.Fatalf("policy.toml = %q, want a hardened pip rule", policy)
	}
}

// TestTheGitPushRuleCarriesItsOwnReason: the rule is built in rather than
// answered, so the reason answers.toml gives would be a false one.
func TestTheGitPushRuleCarriesItsOwnReason(t *testing.T) {
	bare := fixture()
	bare.Policy.ForbiddenCommands = []string{}
	files, err := Render(bare)
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	policy := files[".ultraloom/policy.toml"]
	if strings.Count(policy, `git\s+push`) != 1 {
		t.Fatalf("policy.toml = %q, want the git push rule exactly once", policy)
	}
	if !strings.Contains(policy, "a human's decision") {
		t.Fatalf("policy.toml = %q, want the built-in reason", policy)
	}
	if strings.Contains(policy, "answers.toml\"") {
		t.Fatalf("policy.toml = %q, want no answered-reason on a built-in rule", policy)
	}
}

// TestTheGitPushAnswerDoesNotDuplicateTheBuiltInRule: a project that names it
// anyway must not end up with the rule twice.
func TestTheGitPushAnswerDoesNotDuplicateTheBuiltInRule(t *testing.T) {
	files, err := Render(fixture())
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	if got := strings.Count(files[".ultraloom/policy.toml"], `git\s+push`); got != 1 {
		t.Fatalf("git push rule appears %d times, want once", got)
	}
}

func TestTheStopProfileFollowsTheGates(t *testing.T) {
	lean := fixture()
	lean.Gates.TestsInStop = false
	lean.Gates.TypesInStop = false
	files, err := Render(lean)
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	config := files[".ultraloom/config.toml"]
	if !strings.Contains(config, `precommit = ["lint"]`) {
		t.Fatalf("config.toml = %q, want precommit down to lint", config)
	}
}

func TestRenderNamesEveryFileItWrites(t *testing.T) {
	files, err := Render(fixture())
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	want := []string{".ultraloom/answers.toml", ".ultraloom/config.toml", ".ultraloom/policy.toml"}
	var got []string
	for name := range files {
		got = append(got, name)
	}
	sort.Strings(got)
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("files = %v, want %v", got, want)
	}
}

// TestEveryRenderedFileIsValidToml is the check the golden files cannot make:
// they only say the output did not change, not that it can be read at all.
func TestEveryRenderedFileIsValidToml(t *testing.T) {
	files, err := Render(fixture())
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	for name, body := range files {
		var parsed map[string]any
		if _, err := toml.Decode(body, &parsed); err != nil {
			t.Fatalf("%s is not valid TOML: %v\n%s", name, err, body)
		}
	}
}

// TestAWindowsPathSurvivesTheRender: a wiki bundle is a path, and on Windows
// a path carries backslashes. Written raw, `wiki\bundle` is an invalid escape
// and takes the whole file down -- with the answers still looking right.
func TestAWindowsPathSurvivesTheRender(t *testing.T) {
	windows := fixture()
	windows.Gates.Wiki.Bundle = `C:\projects\wiki`
	files, err := Render(windows)
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	back, err := answers.Load([]byte(files[".ultraloom/answers.toml"]))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if back.Gates.Wiki.Bundle != windows.Gates.Wiki.Bundle {
		t.Fatalf("bundle = %q, want %q", back.Gates.Wiki.Bundle, windows.Gates.Wiki.Bundle)
	}
}

// TestAQuoteInAnAnswerDoesNotBreakTheFile is the same class from the other
// side, and the reason nothing here interpolates a string unquoted.
func TestAQuoteInAnAnswerDoesNotBreakTheFile(t *testing.T) {
	odd := fixture()
	odd.Policy.ProtectedPaths = []string{`say "no"`}
	files, err := Render(odd)
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	back, err := answers.Load([]byte(files[".ultraloom/answers.toml"]))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if len(back.Policy.ProtectedPaths) != 1 || back.Policy.ProtectedPaths[0] != `say "no"` {
		t.Fatalf("protected = %q, want the answer intact", back.Policy.ProtectedPaths)
	}
	var parsed map[string]any
	if _, err := toml.Decode(files[".ultraloom/policy.toml"], &parsed); err != nil {
		t.Fatalf("policy.toml is not valid TOML: %v\n%s", err, files[".ultraloom/policy.toml"])
	}
}

// TestAPatternCarryingAnApostropheLeavesTheLiteralForm: TOML's literal string
// has no escape at all, so an apostrophe inside one is not a quoting mistake
// but an unclosed string -- the pattern has to change form instead.
func TestAPatternCarryingAnApostropheLeavesTheLiteralForm(t *testing.T) {
	odd := fixture()
	odd.Policy.ForbiddenCommands = []string{"rm dont's"}
	files, err := Render(odd)
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	policy := files[".ultraloom/policy.toml"]
	var parsed map[string]any
	if _, err := toml.Decode(policy, &parsed); err != nil {
		t.Fatalf("policy.toml is not valid TOML: %v\n%s", err, policy)
	}
	// The built-in git-push rule carries `\s+` verbatim in its literal string,
	// so only this rule's own escaped form tells the two branches apart.
	escaped := strconv.Quote(commandPattern("rm dont's"))
	if !strings.Contains(policy, escaped) {
		t.Fatalf("policy.toml = %q, want the rule as %s", policy, escaped)
	}
}

// TestAControlCharacterIsEscapedTheWayTomlAllows is the Windows-path lesson
// one class further in: Go's %q knows escapes TOML does not, and a value
// carrying U+000B renders as `\v` -- an invalid escape that takes the file
// down while the answer still reads plainly.
func TestAControlCharacterIsEscapedTheWayTomlAllows(t *testing.T) {
	odd := fixture()
	odd.Gates.Wiki.Bundle = "wiki\vbundle"
	files, err := Render(odd)
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	body := files[".ultraloom/answers.toml"]
	if !strings.Contains(body, `\u000B`) {
		t.Fatalf("answers.toml = %q, want the bundle escaped as %s", body, `\u000B`)
	}
	var parsed map[string]any
	if _, err := toml.Decode(body, &parsed); err != nil {
		t.Fatalf("answers.toml is not valid TOML: %v\n%s", err, body)
	}
}

// TestTomlStringEscapesOnlyWhatTomlKnows walks every arm of the quoter: the
// listed escapes, the two control ranges TOML bars from a basic string, and
// the runes that pass through untouched.
func TestTomlStringEscapesOnlyWhatTomlKnows(t *testing.T) {
	cases := []struct{ in, want string }{
		{`say "no"`, `"say \"no\""`},
		{`C:\wiki`, `"C:\\wiki"`},
		{"\b\t\n\f\r", `"\b\t\n\f\r"`},
		{"\x01", `"\u0001"`},
		{"\x7f", `"\u007F"`},
		{"grüß", `"grüß"`},
		// Outside the BMP TOML would want \U0001F600; the literal rune says
		// the same thing and needs no second escape form.
		{"\U0001F600", "\"\U0001F600\""},
		// Ranging over a string already turns invalid UTF-8 into U+FFFD, and
		// that is a printable rune like any other.
		{"\xff", "\"\uFFFD\""},
	}
	for _, c := range cases {
		if got := tomlString(c.in); got != c.want {
			t.Fatalf("tomlString(%q) = %s, want %s", c.in, got, c.want)
		}
	}
}

// TestARegexCarryingAControlCharacterLeavesTheLiteralForm: TOML's literal
// string has no escape at all, so a control character inside one is as fatal
// as an apostrophe -- both have to send the pattern to the basic string.
func TestARegexCarryingAControlCharacterLeavesTheLiteralForm(t *testing.T) {
	if got, want := tomlRegex("a\vb"), `"a\u000Bb"`; got != want {
		t.Fatalf("tomlRegex = %s, want %s", got, want)
	}
	if got, want := tomlRegex(`\s+x`), `'\s+x'`; got != want {
		t.Fatalf("tomlRegex = %s, want %s", got, want)
	}
}
