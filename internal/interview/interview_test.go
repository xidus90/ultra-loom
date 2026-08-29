package interview

import (
	"bytes"
	"errors"
	"io"
	"reflect"
	"strings"
	"testing"

	"github.com/xidus90/ultra-loom/internal/answers"
	"github.com/xidus90/ultra-loom/internal/tooling"
)

func TestWithoutATtyItRefusesInsteadOfPrompting(t *testing.T) {
	incomplete := answers.Answers{}
	_, err := Run(strings.NewReader(""), &bytes.Buffer{}, false, incomplete)
	if !errors.Is(err, ErrNoTTY) {
		t.Fatalf("err = %v, want ErrNoTTY", err)
	}
}

func TestTheRefusalNamesTheFlagThatWouldAnswer(t *testing.T) {
	var out bytes.Buffer
	_, err := Run(strings.NewReader(""), &out, false, answers.Answers{})
	if err == nil {
		t.Fatal("want an error")
	}
	if !strings.Contains(err.Error(), "--commit-language") {
		t.Fatalf("error = %q, want it to name the flag", err.Error())
	}
}

func TestEnterTakesTheDefault(t *testing.T) {
	start := answers.Answers{}
	start.Gates.CoverageThreshold = 100
	start.Project.DocsLanguage = "de"
	got, err := Run(strings.NewReader("\n"), &bytes.Buffer{}, true, start)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if got.Project.CommitLanguage != "en" {
		t.Fatalf("commit language = %q, want the default en", got.Project.CommitLanguage)
	}
}

func TestNothingIsAskedWhenEverythingIsAnswered(t *testing.T) {
	complete := answers.Answers{}
	complete.Project.CommitLanguage = "en"
	complete.Project.DocsLanguage = "de"
	complete.Project.Agents = []string{"claude", "gemini"}
	complete.Gates.CoverageThreshold = 100
	complete.Gates.Wiki.Mode = "none"
	if got := Missing(complete); len(got) != 0 {
		t.Fatalf("missing = %v, want none", got)
	}
}

// answered is a complete answer sheet without stacks: the base every test
// below narrows to the one question it is about.
func answered() answers.Answers {
	var complete answers.Answers
	complete.Project.CommitLanguage = "en"
	complete.Project.DocsLanguage = "de"
	complete.Project.Agents = []string{"claude", "gemini"}
	complete.Gates.CoverageThreshold = 100
	complete.Gates.Wiki.Mode = "none"
	return complete
}

func keys(open []Question) []string {
	var all []string
	for _, question := range open {
		all = append(all, question.Key)
	}
	return all
}

func TestTheQuestionsComeInTheOrderOfTheAnswerFile(t *testing.T) {
	want := "commit_language docs_language agents coverage_threshold wiki_mode"
	if got := strings.Join(keys(Missing(answers.Answers{})), " "); got != want {
		t.Fatalf("questions = %q, want %q", got, want)
	}
}

func TestTheStackQuestionsComeAfterTheOnesEveryProjectGets(t *testing.T) {
	start := answers.Answers{}
	start.Project.Stacks = []string{"django", "python", "uv"}
	want := "commit_language docs_language agents coverage_threshold wiki_mode protect_migrations forbid_pip_install"
	if got := strings.Join(keys(Missing(start)), " "); got != want {
		t.Fatalf("questions = %q, want %q", got, want)
	}
}

func TestRunReturnsWhatItWasGivenWhenNothingIsOpen(t *testing.T) {
	var out bytes.Buffer
	got, err := Run(strings.NewReader(""), &out, false, answered())
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if !reflect.DeepEqual(got, answered()) {
		t.Fatalf("answers = %+v, want them unchanged", got)
	}
	if out.Len() != 0 {
		t.Fatalf("output = %q, want silence", out.String())
	}
}

func TestEveryAnswerGivenIsKept(t *testing.T) {
	given := "de\nen\nclaude\n90\nbrain\n"
	got, err := Run(strings.NewReader(given), &bytes.Buffer{}, true, answers.Answers{})
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if got.Project.CommitLanguage != "de" || got.Project.DocsLanguage != "en" {
		t.Fatalf("languages = %q/%q, want de/en", got.Project.CommitLanguage, got.Project.DocsLanguage)
	}
	if len(got.Project.Agents) != 1 || got.Project.Agents[0] != "claude" {
		t.Fatalf("agents = %v, want [claude]", got.Project.Agents)
	}
	if got.Gates.CoverageThreshold != 90 {
		t.Fatalf("coverage = %d, want 90", got.Gates.CoverageThreshold)
	}
	if got.Gates.Wiki.Mode != "brain" {
		t.Fatalf("wiki mode = %q, want brain", got.Gates.Wiki.Mode)
	}
}

func TestThePromptShowsQuestionAndDefault(t *testing.T) {
	var out bytes.Buffer
	start := answered()
	start.Project.CommitLanguage = ""
	if _, err := Run(strings.NewReader("\n"), &out, true, start); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if got := out.String(); got != "Language for commit messages [en]: " {
		t.Fatalf("prompt = %q", got)
	}
}

func TestAnUnreadableNumberIsRejectedAndAskedAgain(t *testing.T) {
	var out bytes.Buffer
	start := answered()
	start.Gates.CoverageThreshold = 0
	got, err := Run(strings.NewReader("ninety\n90\n"), &out, true, start)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if got.Gates.CoverageThreshold != 90 {
		t.Fatalf("coverage = %d, want 90 from the second try", got.Gates.CoverageThreshold)
	}
	if !strings.Contains(out.String(), "not a whole number") {
		t.Fatalf("output = %q, want it to say what was wrong", out.String())
	}
}

func TestACoverageThresholdOutsideThePercentScaleIsRejected(t *testing.T) {
	var out bytes.Buffer
	start := answered()
	start.Gates.CoverageThreshold = 0
	if _, err := Run(strings.NewReader("101\n100\n"), &out, true, start); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if !strings.Contains(out.String(), "between 0 and 100") {
		t.Fatalf("output = %q, want the range named", out.String())
	}
}

func TestAWikiModeOutsideTheSetIsRejected(t *testing.T) {
	var out bytes.Buffer
	start := answered()
	start.Gates.Wiki.Mode = ""
	if _, err := Run(strings.NewReader("obsidian\nnone\n"), &out, true, start); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if !strings.Contains(out.String(), "neighbour_repo") {
		t.Fatalf("output = %q, want the known modes named", out.String())
	}
}

func TestABlankLineIsEnterAndTakesTheDefault(t *testing.T) {
	var out bytes.Buffer
	start := answered()
	start.Project.CommitLanguage = ""
	got, err := Run(strings.NewReader("   \n"), &out, true, start)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if got.Project.CommitLanguage != "en" {
		t.Fatalf("commit language = %q, want the default", got.Project.CommitLanguage)
	}
}

func TestAnAnswerStillWrongAtTheEndOfInputEndsTheRun(t *testing.T) {
	start := answered()
	start.Gates.CoverageThreshold = 0
	_, err := Run(strings.NewReader("ninety"), &bytes.Buffer{}, true, start)
	if err == nil {
		t.Fatal("want an error rather than an endless question")
	}
	if !strings.Contains(err.Error(), "coverage_threshold") {
		t.Fatalf("error = %q, want the question named", err.Error())
	}
}

func TestTheEndOfInputLeavesTheRemainingDefaults(t *testing.T) {
	got, err := Run(strings.NewReader(""), &bytes.Buffer{}, true, answers.Answers{})
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if got.Project.CommitLanguage != "en" || got.Gates.Wiki.Mode != "none" {
		t.Fatalf("answers = %+v, want the defaults throughout", got)
	}
}

// failingReader is stdin gone bad -- not the end of input, which is an
// answer of its own, but a read that cannot be retried.
type failingReader struct{}

func (failingReader) Read([]byte) (int, error) { return 0, errors.New("stdin broke") }

func TestAReadThatFailsIsReported(t *testing.T) {
	_, err := Run(failingReader{}, &bytes.Buffer{}, true, answers.Answers{})
	if err == nil || !strings.Contains(err.Error(), "stdin broke") {
		t.Fatalf("err = %v, want the read failure", err)
	}
}

func TestPythonBringsTheQuestionAboutPip(t *testing.T) {
	start := answered()
	start.Project.Stacks = []string{"python"}
	open := Missing(start)
	if got := strings.Join(keys(open), " "); got != "forbid_pip_install" {
		t.Fatalf("questions = %q, want the pip question alone", got)
	}
	if open[0].Default != "no" {
		t.Fatalf("default = %q, want no where nothing manages the environment", open[0].Default)
	}
}

func TestAUvProjectDefaultsToForbiddingPip(t *testing.T) {
	start := answered()
	start.Project.Stacks = []string{"python", "uv"}
	got, err := Run(strings.NewReader("\n"), &bytes.Buffer{}, true, start)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if len(got.Policy.ForbiddenCommands) != 1 || got.Policy.ForbiddenCommands[0] != "pip install" {
		t.Fatalf("forbidden = %v, want pip install", got.Policy.ForbiddenCommands)
	}
}

func TestDecliningIsAnAnswerAndIsNotAskedAgain(t *testing.T) {
	start := answered()
	start.Project.Stacks = []string{"python", "uv"}
	got, err := Run(strings.NewReader("n\n"), &bytes.Buffer{}, true, start)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if len(got.Policy.ForbiddenCommands) != 0 {
		t.Fatalf("forbidden = %v, want nothing forbidden", got.Policy.ForbiddenCommands)
	}
	if open := Missing(got); len(open) != 0 {
		t.Fatalf("missing = %v, want the declined question to stay answered", keys(open))
	}
}

// The refusal above survives a round trip only if the rendered file writes
// the empty list rather than leaving the key out.
func TestAnEmptyListInTheFileCountsAsAnswered(t *testing.T) {
	loaded, err := answers.Load([]byte("[policy]\nprotected_paths = []\nforbidden_commands = []\n"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if loaded.Policy.ForbiddenCommands == nil || loaded.Policy.ProtectedPaths == nil {
		t.Fatal("an empty list read back as nil, and the question would be asked again")
	}
}

func TestAnAnswerThatIsNeitherYesNorNoIsRejected(t *testing.T) {
	var out bytes.Buffer
	start := answered()
	start.Project.Stacks = []string{"python"}
	if _, err := Run(strings.NewReader("maybe\nyes\n"), &out, true, start); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if !strings.Contains(out.String(), "yes or no") {
		t.Fatalf("output = %q", out.String())
	}
}

func TestDjangoBringsTheQuestionAboutMigrations(t *testing.T) {
	start := answered()
	start.Project.Stacks = []string{"django", "python"}
	got, err := Run(strings.NewReader("yes\nno\n"), &bytes.Buffer{}, true, start)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	want := "migrations/[0-9][0-9][0-9][0-9]_*.py"
	if len(got.Policy.ProtectedPaths) != 1 || got.Policy.ProtectedPaths[0] != want {
		t.Fatalf("protected = %v, want %q", got.Policy.ProtectedPaths, want)
	}
	if len(got.Policy.ForbiddenCommands) != 0 {
		t.Fatalf("forbidden = %v, want the declined answer respected", got.Policy.ForbiddenCommands)
	}
}

func TestAPolicyAlreadyWrittenIsNotAskedAboutAgain(t *testing.T) {
	start := answered()
	start.Project.Stacks = []string{"django", "python", "uv"}
	start.Policy.ProtectedPaths = []string{"migrations/"}
	start.Policy.ForbiddenCommands = []string{"pip install"}
	if got := Missing(start); len(got) != 0 {
		t.Fatalf("missing = %v, want none on a second run", keys(got))
	}
}

func TestAProjectWithoutPythonIsNotAskedAboutPip(t *testing.T) {
	start := answered()
	start.Project.Stacks = []string{"go", "rust"}
	if got := Missing(start); len(got) != 0 {
		t.Fatalf("missing = %v, want none", keys(got))
	}
}

func TestApplyAgents(t *testing.T) {
	var target []string
	if err := applyAgents("claude, gemini", &target); err != nil {
		t.Fatal(err)
	}
	if len(target) != 2 || target[0] != "claude" || target[1] != "gemini" {
		t.Fatalf("target = %v, want [claude gemini]", target)
	}

	if err := applyAgents("all", &target); err != nil {
		t.Fatal(err)
	}
	if len(target) != 2 || target[0] != "claude" || target[1] != "gemini" {
		t.Fatalf("target = %v, want [claude gemini]", target)
	}

	if err := applyAgents("none", &target); err != nil {
		t.Fatal(err)
	}
	if len(target) != 0 {
		t.Fatalf("target = %v, want empty", target)
	}

	if err := applyAgents("claude", &target); err != nil {
		t.Fatal(err)
	}
	if len(target) != 1 || target[0] != "claude" {
		t.Fatalf("target = %v, want [claude]", target)
	}

	if err := applyAgents("claude, , gemini", &target); err != nil || len(target) != 2 {
		t.Fatalf("target = %v, want [claude gemini]", target)
	}

	if err := applyAgents("unknown", &target); err == nil {
		t.Fatal("want error for unknown agent")
	}
}

func TestAskToolsNonInteractiveOrEmpty(t *testing.T) {
	tools := []tooling.ToolSpec{{Name: "ruff", Stack: "python", InstallCmd: "uv tool install ruff"}}
	res, err := AskTools(strings.NewReader(""), &bytes.Buffer{}, false, tools)
	if err != nil || len(res) != 0 {
		t.Fatalf("res = %v, err = %v, want nil/empty when non-interactive", res, err)
	}

	res, err = AskTools(strings.NewReader(""), &bytes.Buffer{}, true, nil)
	if err != nil || len(res) != 0 {
		t.Fatalf("res = %v, err = %v, want nil/empty when missing is empty", res, err)
	}
}

func TestAskToolsInstallDefaultAndExplicitYes(t *testing.T) {
	tools := []tooling.ToolSpec{
		{Name: "ruff", Stack: "python", InstallCmd: "uv tool install ruff"},
		{Name: "dmypy", Stack: "python", InstallCmd: "uv tool install mypy"},
	}
	// First tool default (empty line/enter), second tool explicit "yes"
	input := "\nyes\n"
	var out bytes.Buffer
	res, err := AskTools(strings.NewReader(input), &out, true, tools)
	if err != nil {
		t.Fatalf("AskTools: %v", err)
	}
	if len(res) != 2 {
		t.Fatalf("res count = %d, want 2", len(res))
	}
	if res[0].Action != ToolInstall || res[1].Action != ToolInstall {
		t.Fatalf("expected both ToolInstall, got %+v", res)
	}
}

func TestAskToolsSkip(t *testing.T) {
	tools := []tooling.ToolSpec{
		{Name: "ruff", Stack: "python", InstallCmd: "uv tool install ruff"},
	}
	input := "no\n"
	var out bytes.Buffer
	res, err := AskTools(strings.NewReader(input), &out, true, tools)
	if err != nil {
		t.Fatalf("AskTools: %v", err)
	}
	if len(res) != 1 || res[0].Action != ToolSkip {
		t.Fatalf("expected ToolSkip, got %+v", res)
	}
}

func TestAskToolsProvidePath(t *testing.T) {
	tools := []tooling.ToolSpec{
		{Name: "custom", Stack: "csharp", InstallCmd: ""},
		{Name: "ruff", Stack: "python", InstallCmd: "uv tool install ruff"},
	}
	// First tool: enter "path", then empty path (retry), then "/opt/bin/custom"
	// Second tool: direct path entry "/usr/local/bin/ruff"
	input := "path\n\n/opt/bin/custom\n/usr/local/bin/ruff\n"
	var out bytes.Buffer
	res, err := AskTools(strings.NewReader(input), &out, true, tools)
	if err != nil {
		t.Fatalf("AskTools: %v", err)
	}
	if len(res) != 2 {
		t.Fatalf("res count = %d, want 2", len(res))
	}
	if res[0].Action != ToolPath || res[0].CustomPath != "/opt/bin/custom" {
		t.Fatalf("expected ToolPath with /opt/bin/custom, got %+v", res[0])
	}
	if res[1].Action != ToolPath || res[1].CustomPath != "/usr/local/bin/ruff" {
		t.Fatalf("expected ToolPath with /usr/local/bin/ruff, got %+v", res[1])
	}
}

func TestAskToolsNoInstallCommandAndInvalidInput(t *testing.T) {
	tools := []tooling.ToolSpec{
		{Name: "no-install", Stack: "custom"},
	}
	// "yes" (rejected because no install cmd), "invalid", then default (empty = skip)
	input := "yes\ninvalid\n\n"
	var out bytes.Buffer
	res, err := AskTools(strings.NewReader(input), &out, true, tools)
	if err != nil {
		t.Fatalf("AskTools: %v", err)
	}
	if len(res) != 1 || res[0].Action != ToolSkip {
		t.Fatalf("expected ToolSkip for default without install cmd, got %+v", res)
	}
}

type errReader struct{}

func (errReader) Read(p []byte) (n int, err error) {
	return 0, errors.New("read error")
}

func TestAskToolsReaderError(t *testing.T) {
	tools := []tooling.ToolSpec{{Name: "ruff", Stack: "python", InstallCmd: "uv tool install ruff"}}
	var out bytes.Buffer
	_, err := AskTools(errReader{}, &out, true, tools)
	if err == nil {
		t.Fatal("expected error on broken reader")
	}

	// Broken path reader
	pathErrReader := io.MultiReader(strings.NewReader("path\n"), errReader{})
	_, err = AskTools(pathErrReader, &out, true, tools)
	if err == nil {
		t.Fatal("expected error on broken path reader")
	}
}
