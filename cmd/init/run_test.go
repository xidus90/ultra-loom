package main

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/xidus90/ultra-loom/internal/detect"
	"github.com/xidus90/ultra-loom/internal/vendoring"
)

// osStat asks about a file by the same slash-separated name the report uses.
func osStat(root, name string) (os.FileInfo, error) {
	return os.Stat(filepath.Join(root, filepath.FromSlash(name)))
}

func TestDryRunWritesNothingAndSaysWhatItWould(t *testing.T) {
	root := t.TempDir()
	code, report := run(Options{Root: root, DryRun: true, Yes: true,
		CommitLanguage: "en", DocsLanguage: "de", WikiMode: "none"})
	if code != 0 {
		t.Fatalf("code = %d, report = %s", code, report)
	}
	if !strings.Contains(report, ".ultraloom/policy.toml") {
		t.Fatalf("report does not name what it would write:\n%s", report)
	}
	if _, err := osStat(root, ".ultraloom/policy.toml"); err == nil {
		t.Fatal("dry run wrote a file")
	}
}

func TestAMissingAnswerWithoutATtyExitsTwo(t *testing.T) {
	code, report := run(Options{Root: t.TempDir(), Interactive: false})
	if code != 2 {
		t.Fatalf("code = %d, want 2", code)
	}
	if !strings.Contains(report, "--commit-language") {
		t.Fatalf("report does not name the flag:\n%s", report)
	}
}

func TestASecondRunSkipsWhatIsAlreadyThere(t *testing.T) {
	root := t.TempDir()
	opts := Options{Root: root, Yes: true, CommitLanguage: "en", DocsLanguage: "de", WikiMode: "none"}
	if code, report := run(opts); code != 0 {
		t.Fatalf("first run: %d %s", code, report)
	}
	code, report := run(opts)
	if code != 0 {
		t.Fatalf("second run: %d %s", code, report)
	}
	if !strings.Contains(report, "skipped") {
		t.Fatalf("second run does not report skipping:\n%s", report)
	}
}

// The stubbed edges. Nothing below reads the real PATH, the real environment,
// the network, or any repository other than its own temporary directory.

func noGit(dir string, argv ...string) (string, error) {
	return "", fmt.Errorf("git is not here")
}

func quietGit(dir string, argv ...string) (string, error) { return "", nil }

func notOnPath(name string) (string, error) { return "", fmt.Errorf("not found") }

func onPathAt(name string) (string, error) { return "C:/tools/brain.exe", nil }

func noEnv(string) string { return "" }

func brainDir(name string) string {
	if name == "ULTRA_BRAIN_DIR" {
		return "C:/Program Files/brain"
	}
	return ""
}

// answered is a run with every question already settled, so a test that is
// about something else does not have to arrange an interview.
func answered(root string) Options {
	return Options{Root: root, Yes: true, CommitLanguage: "en",
		DocsLanguage: "de", Agents: "claude,gemini", WikiMode: "none"}
}

func mustRun(t *testing.T, opts Options) string {
	t.Helper()
	code, report := run(opts)
	if code != 0 {
		t.Fatalf("code = %d, report = %s", code, report)
	}
	return report
}

func makeFile(t *testing.T, root, name, body string) {
	t.Helper()
	full := filepath.Join(root, filepath.FromSlash(name))
	if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(full, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func read(t *testing.T, root, name string) string {
	t.Helper()
	body, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(name)))
	if err != nil {
		t.Fatal(err)
	}
	return string(body)
}

// The three rendered files plus the two this package adds are what a run
// installs, and installed.toml must name all of them, itself included.
func TestAFullRunWritesTheWholeSetAndSaysSo(t *testing.T) {
	root := t.TempDir()
	report := mustRun(t, answered(root))
	for _, name := range []string{".ultraloom/answers.toml", ".ultraloom/policy.toml",
		".ultraloom/config.toml", ".ultraloom/installed.toml", ".claude/settings.json"} {
		if _, err := osStat(root, name); err != nil {
			t.Fatalf("%s was not written: %v (report: %s)", name, err, report)
		}
		if !strings.Contains(report, name) {
			t.Fatalf("the report does not name %s:\n%s", name, report)
		}
	}
	installed := read(t, root, ".ultraloom/installed.toml")
	if !strings.Contains(installed, "\".ultraloom/installed.toml\"") {
		t.Fatalf("installed.toml does not name itself:\n%s", installed)
	}
	if !strings.Contains(installed, "commit = \"\"") {
		t.Fatalf("an unvendored run must pin no commit:\n%s", installed)
	}
}

// The hook commands land in a file the project commits, so none of them may
// carry a path that exists only on this machine.
func TestTheHookCommandsCarryNoMachinePath(t *testing.T) {
	root := t.TempDir()
	mustRun(t, answered(root))
	body := read(t, root, ".claude/settings.json")
	if !strings.Contains(body, ".ultraloom/vendor/ultraloom") {
		t.Fatalf("the hooks do not point at the vendored runtime:\n%s", body)
	}
	if strings.Contains(body, root) || strings.Contains(body, filepath.ToSlash(root)) {
		t.Fatalf("a machine path reached settings.json:\n%s", body)
	}
}

// Without a repository the hooks that read history are left out rather than
// installed broken -- and the report says so.
func TestWithoutGitTheHistoryHooksStayOut(t *testing.T) {
	root := t.TempDir()
	report := mustRun(t, answered(root))
	body := read(t, root, ".claude/settings.json")
	if strings.Contains(body, "hook stop") || strings.Contains(body, "subagent-start") {
		t.Fatalf("a history hook was installed without git:\n%s", body)
	}
	if !strings.Contains(report, "no git repository here") {
		t.Fatalf("the report does not say the hooks were left out:\n%s", report)
	}
}

func TestWithGitTheHistoryHooksAreInstalled(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	o := answered(root)
	o.Exec = quietGit
	mustRun(t, o)
	body := read(t, root, ".claude/settings.json")
	for _, want := range []string{"hook stop", "subagent-start", "subagent-stop"} {
		if !strings.Contains(body, want) {
			t.Fatalf("%s is missing from settings.json:\n%s", want, body)
		}
	}
}

// A failing git is this program's own error: nothing has been decided yet, and
// nothing is written.
func TestAFailingGitEndsTheRunBeforeAnythingIsWritten(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	o := answered(root)
	o.Exec = noGit
	code, report := run(o)
	if code != 1 {
		t.Fatalf("code = %d, want 1 (%s)", code, report)
	}
	if _, err := osStat(root, ".ultraloom/answers.toml"); err == nil {
		t.Fatal("a failed run wrote something")
	}
}

func TestAnUnreadableAnswerFileIsOurOwnError(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, ".ultraloom/answers.toml", "[gates.wiki]\nmode = \"nonsense\"\n")
	code, report := run(answered(root))
	if code != 1 {
		t.Fatalf("code = %d, want 1", code)
	}
	if !strings.Contains(report, "nonsense") {
		t.Fatalf("the report does not name the bad value:\n%s", report)
	}
}

// A second run reads the answers of the first, so nothing is asked again --
// even where no flag carries the answer any more.
func TestTheAnswerFileIsWhatASecondRunReads(t *testing.T) {
	root := t.TempDir()
	mustRun(t, answered(root))
	if err := os.Remove(filepath.Join(root, ".ultraloom", "policy.toml")); err != nil {
		t.Fatal(err)
	}
	report := mustRun(t, Options{Root: root, Interactive: false})
	if !strings.Contains(report, "policy.toml") {
		t.Fatalf("the missing file was not written again:\n%s", report)
	}
}

func TestFlagsAnswerEveryQuestionAStackRaises(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "pyproject.toml", "[project]\n")
	makeFile(t, root, "uv.lock", "")
	makeFile(t, root, "manage.py", "django")
	makeFile(t, root, "requirements.txt", "Django==5.0\n")
	report := mustRun(t, Options{Root: root, Interactive: false,
		CommitLanguage: "en", DocsLanguage: "de", Agents: "claude,gemini", WikiMode: "none",
		CoverageThreshold: 90, ProtectMigrations: "yes", ForbidPipInstall: "no"})
	answersFile := read(t, root, ".ultraloom/answers.toml")
	if !strings.Contains(answersFile, "coverage_threshold = 90") {
		t.Fatalf("the threshold flag did not reach the file:\n%s", answersFile)
	}
	if !strings.Contains(answersFile, "protected_paths") {
		t.Fatalf("yes did not become a rule:\n%s", answersFile)
	}
	if !strings.Contains(answersFile, "forbidden_commands = []") {
		t.Fatalf("no did not become an empty list:\n%s", answersFile)
	}
	if !strings.Contains(report, "no coverage check was installed") ||
		!strings.Contains(report, "threshold of 90%") {
		t.Fatalf("the missing coverage lane was not reported:\n%s", report)
	}
	// The report is read once; this file is read on every run. A project whose
	// coverage cannot fail must not carry a check that says it can.
	config := read(t, root, ".ultraloom/config.toml")
	if strings.Contains(config, "\n[verify.coverage]\n") ||
		strings.Contains(config, `"coverage"`) {
		t.Fatalf("a coverage lane was installed that nothing can fail:\n%s", config)
	}
}

// A project whose own configuration enforces the threshold keeps its lane.
func TestAnEnforcedThresholdKeepsTheCoverageLane(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "pyproject.toml", "[tool.coverage.report]\nfail_under = 100\n")
	makeFile(t, root, "uv.lock", "")
	mustRun(t, answered(root))
	config := read(t, root, ".ultraloom/config.toml")
	if !strings.Contains(config, "\n[verify.coverage]\n") {
		t.Fatalf("the coverage lane was dropped from a project that enforces it:\n%s", config)
	}
}

// Only Python can be judged here: coverage.Enforced reads pyproject.toml and
// .coveragerc and nothing else, so a project it cannot speak for keeps its
// lane rather than losing it on a guess.
func TestAProjectThisCannotJudgeKeepsItsCoverageLane(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "package.json", "{}")
	report := mustRun(t, answered(root))
	config := read(t, root, ".ultraloom/config.toml")
	if !strings.Contains(config, "\n[verify.coverage]\n") {
		t.Fatalf("a Node project lost its coverage lane on a guess:\n%s", config)
	}
	if strings.Contains(report, "no coverage check was installed") {
		t.Fatalf("a project this cannot judge was told it was judged:\n%s", report)
	}
}

// A project whose own configuration enforces the threshold hears nothing: the
// note is about a promise nobody keeps, not about the number.
func TestAnEnforcedThresholdIsNotReported(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "pyproject.toml", "[tool.coverage.report]\nfail_under = 100\n")
	report := mustRun(t, answered(root))
	if strings.Contains(report, "nothing enforces") {
		t.Fatalf("an enforced threshold was reported as missing:\n%s", report)
	}
}

func TestBrainOnPathIsWrittenIntoTheProject(t *testing.T) {
	root := t.TempDir()
	o := answered(root)
	o.WikiMode, o.Look, o.Getenv = "brain", onPathAt, noEnv
	mustRun(t, o)
	mcp := read(t, root, ".mcp.json")
	if !strings.Contains(mcp, "\"command\": \"brain\"") {
		t.Fatalf(".mcp.json does not call brain by its bare name:\n%s", mcp)
	}
	if strings.Contains(mcp, "C:/tools") {
		t.Fatalf("the resolved path reached the committed file:\n%s", mcp)
	}
	if !strings.Contains(read(t, root, ".claude/settings.json"), "brain lint") {
		t.Fatal("the wiki hook was not installed although brain was found")
	}
}

// The whole point of the middle branch: a directory out of ULTRA_BRAIN_DIR is
// a claim about one machine, and both files it would land in are committed.
func TestBrainFoundOnlyByTheVariableIsReportedAndNotWritten(t *testing.T) {
	root := t.TempDir()
	o := answered(root)
	o.WikiMode, o.Look, o.Getenv = "brain", notOnPath, brainDir
	report := mustRun(t, o)
	if _, err := osStat(root, ".mcp.json"); err == nil {
		t.Fatal("a machine path was written into a versioned file")
	}
	if !strings.Contains(report, "ULTRA_BRAIN_DIR") ||
		!strings.Contains(report, "C:/Program Files/brain") {
		t.Fatalf("the entry was not offered for the user to add:\n%s", report)
	}
	if strings.Contains(read(t, root, ".claude/settings.json"), "brain lint") {
		t.Fatal("the wiki hook carried the machine path into settings.json")
	}
}

func TestBrainNotFoundInstallsNoGateAtAll(t *testing.T) {
	root := t.TempDir()
	o := answered(root)
	o.WikiMode, o.Look, o.Getenv = "brain", notOnPath, noEnv
	report := mustRun(t, o)
	if _, err := osStat(root, ".mcp.json"); err == nil {
		t.Fatal("an entry was written for a brain nobody can call")
	}
	if strings.Contains(read(t, root, ".claude/settings.json"), "brain lint") {
		t.Fatal("a gate was installed that cannot run")
	}
	if !strings.Contains(report, "worse than none") {
		t.Fatalf("the report does not say why nothing was installed:\n%s", report)
	}
}

// The third merge case, and the expensive one: a hook of the project keeps its
// slot, and no second one is put beside it.
func TestAForeignHookKeepsItsSlotAndIsReported(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "pyproject.toml", "[project]\nname=\"test\"\n")
	makeFile(t, root, ".claude/settings.json",
		"{\"hooks\":{\"PostToolUse\":[{\"matcher\":\"Write|Edit|NotebookEdit\","+
			"\"hooks\":[{\"type\":\"command\",\"command\":\"theirs\"}]}]}}")
	report := mustRun(t, answered(root))
	body := read(t, root, ".claude/settings.json")
	if !strings.Contains(body, "theirs") {
		t.Fatalf("the project's own hook was not left alone:\n%s", body)
	}
	if !strings.Contains(report, "left to the project") {
		t.Fatalf("the skip was not reported:\n%s", report)
	}
}

// Broken JSON is the project saying no. Not repaired, not overwritten.
func TestABrokenSettingsFileEndsTheRunWithTwo(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, ".claude/settings.json", "{not json")
	code, report := run(answered(root))
	if code != 2 {
		t.Fatalf("code = %d, want 2 (%s)", code, report)
	}
	if read(t, root, ".claude/settings.json") != "{not json" {
		t.Fatal("the broken file was rewritten")
	}
	if _, err := osStat(root, ".ultraloom/answers.toml"); err == nil {
		t.Fatal("a refused run wrote something")
	}
}

// A settings file that already holds exactly these entries comes back
// unchanged, and then it is not something this run created.
func TestSettingsAlreadyInPlaceAreNotClaimedAsCreated(t *testing.T) {
	root := t.TempDir()
	mustRun(t, answered(root))
	before := read(t, root, ".claude/settings.json")
	report := mustRun(t, answered(root))
	if read(t, root, ".claude/settings.json") != before {
		t.Fatal("a second run rewrote settings.json")
	}
	if strings.Contains(report, ".claude/settings.json") {
		t.Fatalf("an unchanged file was named as created:\n%s", report)
	}
}

func TestAFileWhereTheConfigDirectoryBelongsEndsTheRunWithOne(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, ".ultraloom", "not a directory")
	code, report := run(answered(root))
	if code != 1 {
		t.Fatalf("code = %d, want 1 (%s)", code, report)
	}
}

func TestSettingsThatCannotBeWrittenEndTheRunWithOne(t *testing.T) {
	root := t.TempDir()
	// A directory under the file's name: the merge reads nothing, decides to
	// write, and the disk says no at the last moment.
	if err := os.MkdirAll(filepath.Join(root, ".claude", "settings.json"), 0o755); err != nil {
		t.Fatal(err)
	}
	code, report := run(answered(root))
	if code != 1 {
		t.Fatalf("code = %d, want 1 (%s)", code, report)
	}
	if !strings.Contains(report, settingsPath) {
		t.Fatalf("the report does not name the file that could not be written:\n%s", report)
	}
}

func TestSettingsWhoseDirectoryCannotBeMadeEndTheRunWithOne(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, ".claude", "a file where a directory belongs")
	code, report := run(answered(root))
	if code != 1 {
		t.Fatalf("code = %d, want 1 (%s)", code, report)
	}
}

// The dry run of a vendored install clones nothing: the clone is a write like
// any other, and --dry-run is the run without the writing.
func TestADryRunClonesNothing(t *testing.T) {
	root := t.TempDir()
	o := answered(root)
	o.DryRun, o.VendorURL, o.VendorRef = true, "https://example.invalid/x.git", "v1"
	o.Exec = func(dir string, argv ...string) (string, error) {
		t.Fatalf("a dry run started %v", argv)
		return "", nil
	}
	report := mustRun(t, o)
	if !strings.Contains(report, "would clone https://example.invalid/x.git at v1") {
		t.Fatalf("the dry run kept the largest step to itself:\n%s", report)
	}
}

func TestVendoringPinsTheCommitItGot(t *testing.T) {
	root := t.TempDir()
	var calls [][]string
	o := answered(root)
	o.VendorURL, o.VendorRef = "https://example.invalid/x.git", "v1"
	o.Exec = func(dir string, argv ...string) (string, error) {
		calls = append(calls, argv)
		return "cafebabecafebabecafebabecafebabecafebabe\n", nil
	}
	mustRun(t, o)
	if len(calls) == 0 || calls[0][0] != "git" || calls[0][1] != "clone" {
		t.Fatalf("git was not called as git clone: %v", calls)
	}
	installed := read(t, root, ".ultraloom/installed.toml")
	if !strings.Contains(installed, "cafebabecafebabecafebabecafebabecafebabe") {
		t.Fatalf("the commit was not pinned:\n%s", installed)
	}
}

func TestAFailingCloneEndsTheRunWithOne(t *testing.T) {
	root := t.TempDir()
	o := answered(root)
	o.VendorURL, o.VendorRef = "https://example.invalid/x.git", "v1"
	o.Exec = noGit
	code, report := run(o)
	if code != 1 {
		t.Fatalf("code = %d, want 1 (%s)", code, report)
	}
	if _, err := osStat(root, ".ultraloom/answers.toml"); err == nil {
		t.Fatal("a failed clone left a configured project behind")
	}
}

// The interview is the other road to the same file: what a person types stands
// in answers.toml exactly where a flag would have put it.
func TestATypedAnswerLandsInTheFile(t *testing.T) {
	root := t.TempDir()
	out := &bytes.Buffer{}
	report := mustRun(t, Options{Root: root, Interactive: true,
		In: strings.NewReader("fr\nde\n100\nnone\n"), Out: out})
	if !strings.Contains(read(t, root, ".ultraloom/answers.toml"), "commit_language = \"fr\"") {
		t.Fatalf("the typed answer did not land in the file (report: %s)", report)
	}
	if !strings.Contains(out.String(), "Language for commit messages") {
		t.Fatalf("nothing was asked:\n%s", out)
	}
}

// An answer the interview refuses, with nothing behind it, ends the run -- and
// that is this program's own error, not the project saying no.
func TestAnUnusableTypedAnswerEndsTheRunWithOne(t *testing.T) {
	root := t.TempDir()
	code, report := run(Options{Root: root, Interactive: true,
		In: strings.NewReader("en\nde\nnot a number\n")})
	if code != 1 {
		t.Fatalf("code = %d, want 1 (%s)", code, report)
	}
}

// A brain bundle inside the project answers the wiki question by itself, so
// the interview never asks it -- and the mode reaches the answer file.
func TestAWikiInTheProjectAnswersTheWikiQuestion(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "wiki/index.md", "---\nokf_version: 1\n---\n")
	o := Options{Root: root, Yes: true, CommitLanguage: "en", DocsLanguage: "de",
		Look: notOnPath, Getenv: noEnv}
	mustRun(t, o)
	answersFile := read(t, root, ".ultraloom/answers.toml")
	if !strings.Contains(answersFile, "mode   = \"brain\"") {
		t.Fatalf("the detected wiki did not reach the answers:\n%s", answersFile)
	}
}

// A project that says no must not first get a runtime cloned into it: the
// merge is the last step that can refuse, so it decides before the clone.
func TestARefusedProjectIsNotClonedInto(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, ".claude/settings.json", "{not json")
	o := answered(root)
	o.VendorURL, o.VendorRef = "https://example.invalid/x.git", "v1"
	o.Exec = func(dir string, argv ...string) (string, error) {
		t.Fatalf("a refused run started %v", argv)
		return "", nil
	}
	if code, report := run(o); code != 2 {
		t.Fatalf("code = %d, want 2 (%s)", code, report)
	}
}

// vendoring.Clone leaves whatever git left and hands the cleanup to its
// caller. Without it, an exit that says "nothing written" would be a lie.
func TestAFailedCloneLeavesNoHalfClone(t *testing.T) {
	root := t.TempDir()
	o := answered(root)
	o.VendorURL, o.VendorRef = "https://example.invalid/x.git", "v1"
	o.Exec = func(dir string, argv ...string) (string, error) {
		makeFile(t, root, ".ultraloom/vendor/ultraloom/README.md", "half a clone")
		return "", fmt.Errorf("the remote hung up")
	}
	code, report := run(o)
	if code != 1 {
		t.Fatalf("code = %d, want 1 (%s)", code, report)
	}
	if _, err := osStat(root, ".ultraloom/vendor/ultraloom"); err == nil {
		t.Fatal("the half-written clone was left behind")
	}
}

// A flag that goes straight to a field skips the validator the interview owns
// for the same answer. Each of these wrote or discarded silently before.
func TestABadFlagIsRefusedBeforeAnythingIsWritten(t *testing.T) {
	for _, bad := range []struct {
		name  string
		set   func(*Options)
		names string
	}{
		{"wiki mode", func(o *Options) { o.WikiMode = "nonsense" }, "--wiki-mode"},
		{"agents invalid", func(o *Options) { o.Agents = "gpt5" }, "--agents"},
		{"threshold above a hundred", func(o *Options) { o.CoverageThreshold = 150 }, "--coverage-threshold"},
		{"negative threshold", func(o *Options) { o.CoverageThreshold = -5 }, "--coverage-threshold"},
		{"neither yes nor no", func(o *Options) { o.ProtectMigrations = "maybe" }, "--protect-migrations"},
		{"pip answer that is neither", func(o *Options) { o.ForbidPipInstall = "perhaps" }, "--forbid-pip-install"},
	} {
		t.Run(bad.name, func(t *testing.T) {
			root := t.TempDir()
			o := answered(root)
			bad.set(&o)
			code, report := run(o)
			if code != 1 {
				t.Fatalf("code = %d, want 1 (%s)", code, report)
			}
			if !strings.Contains(report, bad.names) {
				t.Fatalf("the report does not name %s:\n%s", bad.names, report)
			}
			if _, err := osStat(root, ".ultraloom/answers.toml"); err == nil {
				t.Fatal("a refused flag still wrote a file")
			}
		})
	}
}

// The bug this closes end to end: a run that succeeded and left an answer file
// its own next run could not read.
func TestNoRunLeavesAnAnswerFileItCannotReadAgain(t *testing.T) {
	root := t.TempDir()
	o := answered(root)
	o.WikiMode = "nonsense"
	if code, _ := run(o); code == 0 {
		t.Fatal("a bad wiki mode was installed")
	}
	if code, report := run(answered(root)); code != 0 {
		t.Fatalf("the second run cannot read what the first left: %d %s", code, report)
	}
}

// A url without a ref is not a pin, and a dry run promised the clone anyway --
// "would clone <url> at  into ..." -- for a clone vendoring would have refused.
func TestAVendorUrlWithoutARefIsRefused(t *testing.T) {
	for _, dry := range []bool{true, false} {
		root := t.TempDir()
		o := answered(root)
		o.DryRun, o.VendorURL = dry, "https://example.invalid/x.git"
		o.Exec = func(dir string, argv ...string) (string, error) {
			t.Fatalf("an unpinned run started %v", argv)
			return "", nil
		}
		code, report := run(o)
		if code != 1 {
			t.Fatalf("dry = %v: code = %d, want 1 (%s)", dry, code, report)
		}
		if !strings.Contains(report, "--vendor-ref") {
			t.Fatalf("the report does not name the missing flag:\n%s", report)
		}
	}
}

// The mirror of the url-without-ref case: a ref names a version of something
// nobody asked to fetch. Silently ignoring it leaves the caller believing
// their project is pinned.
func TestAVendorRefWithoutAUrlIsRefused(t *testing.T) {
	root := t.TempDir()
	o := answered(root)
	o.VendorRef = "v1"
	code, report := run(o)
	if code != 1 {
		t.Fatalf("code = %d, want 1 (%s)", code, report)
	}
	if !strings.Contains(report, "--vendor-url") {
		t.Fatalf("the report does not name the missing flag:\n%s", report)
	}
}

// The same answer must mean the same thing typed at the prompt and passed as
// a flag. interview.applyChoice takes y and n; the flag path did not.
func TestTheShortYesAndNoAreTheSameAnswerAsTheLongOnes(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "pyproject.toml", "[project]\n")
	makeFile(t, root, "manage.py", "django")
	makeFile(t, root, "requirements.txt", "Django==5.0\n")
	mustRun(t, Options{Root: root, Interactive: false,
		CommitLanguage: "en", DocsLanguage: "de", Agents: "claude,gemini", WikiMode: "none",
		CoverageThreshold: 100, ProtectMigrations: "y", ForbidPipInstall: "n"})
	answersFile := read(t, root, ".ultraloom/answers.toml")
	// The value, not the key: `protected_paths = []` carries the key too, so
	// the substring this regression is named after matched even when y had
	// been read as no.
	if !strings.Contains(answersFile, migrationGlob) {
		t.Fatalf("y was not read as yes:\n%s", answersFile)
	}
	if !strings.Contains(answersFile, "forbidden_commands = []") {
		t.Fatalf("n was not read as no:\n%s", answersFile)
	}
}

// The reviewer's reproduction: a project that already carries a vendored
// runtime, run again with --vendor-url. The clone git refuses on an occupied
// destination used to take the previous run's work down with it, under an exit
// code whose documented meaning is "nothing written".
func TestAVendoredRuntimeAlreadyThereIsNeverTouched(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, ".ultraloom/vendor/ultraloom/keepme.txt", "PRECIOUS")
	o := answered(root)
	o.VendorURL, o.VendorRef = "https://example.invalid/x.git", "v1"
	o.Exec = func(dir string, argv ...string) (string, error) {
		t.Fatalf("a project that already has a runtime was cloned into: %v", argv)
		return "", nil
	}
	report := mustRun(t, o)
	if got := read(t, root, ".ultraloom/vendor/ultraloom/keepme.txt"); got != "PRECIOUS" {
		t.Fatalf("the pre-existing runtime was destroyed: %q", got)
	}
	if !strings.Contains(report, vendoring.VendorDir+" is already there") {
		t.Fatalf("the untouched runtime was not reported:\n%s", report)
	}
}

// The pin belongs to whoever cloned it. A run that cloned nothing must not
// record a ref it never fetched.
func TestASkippedCloneRecordsNoPin(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, ".ultraloom/vendor/ultraloom/keepme.txt", "PRECIOUS")
	o := answered(root)
	o.VendorURL, o.VendorRef = "https://example.invalid/x.git", "v1"
	o.Exec = quietGit
	mustRun(t, o)
	if strings.Contains(read(t, root, ".ultraloom/installed.toml"), `ref    = "v1"`) {
		t.Fatal("a run that cloned nothing wrote the pin anyway")
	}
}

// A vendor directory that cannot even be looked at is this program's own
// error, not a free name: reading "not there" out of it would start a clone
// into whatever is standing in the way. Driven directly, because a root this
// broken never reaches the clone -- gather stops on it first.
func TestAnUnreadableVendorNameIsReported(t *testing.T) {
	// A NUL byte in the root never reaches the OS: Go's own string conversion
	// rejects it, on every platform, with something that is not "not found".
	occupied, usable, err := vendorPresent("bad" + string(rune(0)) + "root")
	if err == nil {
		t.Fatalf("an unstattable name came back as occupied = %v, usable = %v", occupied, usable)
	}
	if !strings.Contains(err.Error(), "looking at "+vendoring.VendorDir) {
		t.Fatalf("the unreadable name was not named: %v", err)
	}
}

// A plain run installs hooks that all point into the vendored runtime, and
// clones nothing. Without a word about it the project gets a settings.json
// whose PreToolUse hook fails on every Write, Edit and Bash, reported as
// success.
func TestARunWithoutARuntimeSaysTheHooksCannotRunYet(t *testing.T) {
	report := mustRun(t, answered(t.TempDir()))
	if !strings.Contains(report, "no runtime is vendored") {
		t.Fatalf("the missing runtime was not reported:\n%s", report)
	}
	for _, flag := range []string{"--vendor-url", "--vendor-ref"} {
		if !strings.Contains(report, flag) {
			t.Fatalf("%s was not named as the way out:\n%s", flag, report)
		}
	}
}

// Once the runtime stands, the hooks can run and there is nothing to warn
// about -- a note that never goes away is a note nobody reads.
func TestARuntimeInPlaceIsNotWarnedAbout(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, ".ultraloom/vendor/ultraloom/pyproject.toml", "")
	if report := mustRun(t, answered(root)); strings.Contains(report, "no runtime is vendored") {
		t.Fatalf("a project with a runtime was told it has none:\n%s", report)
	}
}

// Keeping the lane for a stack this cannot judge is the safe half. The other
// half is saying so: the reasoning lived in a Go comment the user never reads,
// while `vitest run --coverage` exits 0 at any number unless the project
// configured thresholds of its own.
func TestALaneThisCannotVerifyIsNamedAsUnverified(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "package.json", "{}")
	report := mustRun(t, answered(root))
	if !strings.Contains(report, "the coverage lane was kept but not verified") {
		t.Fatalf("the unverified lane was not reported:\n%s", report)
	}
}

// internal/write is not a transaction and says so, while the spec asks for
// all or nothing. What can still be made true is the report: a run that
// stopped after the five files were on disk must not exit under a code whose
// meaning is "nothing written" and name none of them.
func TestAFailureAfterTheFilesLandedNamesWhatItLeft(t *testing.T) {
	root := t.TempDir()
	// A directory under the settings file's name: every rendered file is
	// written, and only the merge at the very end cannot land.
	if err := os.MkdirAll(filepath.Join(root, ".claude", "settings.json"), 0o755); err != nil {
		t.Fatal(err)
	}
	code, report := run(answered(root))
	if code != 1 {
		t.Fatalf("code = %d, want 1 (%s)", code, report)
	}
	if !strings.Contains(report, "left standing") {
		t.Fatalf("a run that wrote five files claimed it wrote nothing:\n%s", report)
	}
	for _, name := range []string{answersPath, installedPath, ".ultraloom/policy.toml"} {
		if !strings.Contains(report, name) {
			t.Fatalf("%s landed and was not named:\n%s", name, report)
		}
	}
}

// A second run leaves every existing file alone, which is the spec's rule.
// The report has to match it: a flag that names another answer than the one
// answers.toml holds is ignored, and quoting the ignored value made the report
// assert a threshold that exists nowhere.
func TestAFlagAgainstARecordedAnswerIsReportedAsIgnored(t *testing.T) {
	root := t.TempDir()
	mustRun(t, answered(root))
	second := answered(root)
	second.CoverageThreshold = 55
	report := mustRun(t, second)
	if strings.Contains(report, "threshold of 55%") {
		t.Fatalf("the report quotes a threshold that is nowhere on disk:\n%s", report)
	}
	if !strings.Contains(report, "--coverage-threshold was ignored") ||
		!strings.Contains(report, "[gates].coverage_threshold already answers 100") {
		t.Fatalf("the overruled flag was not named with the answer that won:\n%s", report)
	}
	if !strings.Contains(read(t, root, ".ultraloom/answers.toml"), "coverage_threshold = 100") {
		t.Fatal("the recorded answer was changed after all")
	}
}

// A flag that agrees with the file is not a conflict, and a first run has no
// file to disagree with.
func TestAFlagThatChangesNothingIsNotReported(t *testing.T) {
	root := t.TempDir()
	if report := mustRun(t, answered(root)); strings.Contains(report, "was ignored") {
		t.Fatalf("a first run reported its own flags as ignored:\n%s", report)
	}
	if report := mustRun(t, answered(root)); strings.Contains(report, "was ignored") {
		t.Fatalf("flags repeating what the file says were reported:\n%s", report)
	}
}

// The other five answers take the same road, lists included.
func TestEveryOverruledFlagIsNamed(t *testing.T) {
	root := t.TempDir()
	first := answered(root)
	first.ProtectMigrations, first.ForbidPipInstall = "no", "no"
	mustRun(t, first)
	second := answered(root)
	second.CommitLanguage, second.DocsLanguage, second.WikiMode = "fr", "fr", "brain"
	second.ProtectMigrations, second.ForbidPipInstall = "yes", "yes"
	second.Look, second.Getenv = notOnPath, noEnv
	report := mustRun(t, second)
	for _, flag := range []string{"--commit-language", "--docs-language", "--wiki-mode",
		"--protect-migrations", "--forbid-pip-install"} {
		if !strings.Contains(report, flag+" was ignored") {
			t.Fatalf("%s was dropped without a word:\n%s", flag, report)
		}
	}
}

// The fifth file took its own road to the disk. CheckParents guards the four
// that go through write.Commit; settingsWrite.apply did its own MkdirAll and
// WriteFile, so a .claude that is a link to somewhere else put settings.json
// outside the project, at exit 0, reported as created.
func TestSettingsAreNotWrittenThroughALinkedDirectory(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	linkDir(t, outside, filepath.Join(root, ".claude"))
	code, report := run(answered(root))
	if code == 0 {
		t.Fatalf("a write outside the project was reported as success:\n%s", report)
	}
	if _, err := os.Stat(filepath.Join(outside, "settings.json")); !os.IsNotExist(err) {
		t.Fatalf("settings.json landed outside the project: %v", err)
	}
}

// linkDir points one name at another directory, by whichever of the two
// mechanisms this machine allows -- a symlink where the account may make one,
// a directory junction otherwise. internal/write has the same helper for the
// same reason; both are three lines, and a shared test helper would need a
// package of its own.
func linkDir(t *testing.T, target, link string) {
	t.Helper()
	err := os.Symlink(target, link)
	if err == nil {
		return
	}
	if runtime.GOOS != "windows" {
		if errors.Is(err, errors.ErrUnsupported) || errors.Is(err, os.ErrPermission) {
			t.Skipf("cannot create a symlink here: %v", err)
		}
		t.Fatalf("creating a symlink failed for a reason this platform allows: %v", err)
	}
	if out, jerr := exec.Command("cmd", "/c", "mklink", "/J", link, target).CombinedOutput(); jerr != nil {
		t.Skipf("neither a symlink (%v) nor a junction (%v: %s) can be made here", err, jerr, out)
	}
}

// A file is not a runtime. It still blocks the clone -- git would refuse it
// and C1 is about what happens next -- but the hooks cannot run through it, so
// the note that says so must not fall silent.
func TestAFileWhereTheRuntimeBelongsIsNotARuntime(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, ".ultraloom/vendor/ultraloom", "not a clone")
	if report := mustRun(t, answered(root)); !strings.Contains(report, "no runtime is vendored") {
		t.Fatalf("a file was taken for a vendored runtime:\n%s", report)
	}
}

func TestPostEditEntriesPerStack(t *testing.T) {
	cases := []struct {
		name     string
		stacks   []string
		commands []string
	}{
		{
			name:     "python with uv",
			stacks:   []string{"python", "uv"},
			commands: []string{"ruff check --output-format=concise .", "dmypy run -- --no-error-summary --no-pretty"},
		},
		{
			name:     "python plain",
			stacks:   []string{"python"},
			commands: []string{"ruff check --output-format=concise .", "mypy --no-error-summary --no-pretty"},
		},
		{
			name:     "gdscript",
			stacks:   []string{"gdscript", "godot"},
			commands: []string{"gdlint ."},
		},
		{
			name:     "csharp",
			stacks:   []string{"csharp"},
			commands: []string{"dotnet format --verify-no-changes", "dotnet build --no-restore"},
		},
		{
			name:     "typescript",
			stacks:   []string{"typescript"},
			commands: []string{"npx eslint .", "npx tsc --noEmit"},
		},
		{
			name:     "rust",
			stacks:   []string{"rust"},
			commands: []string{"cargo clippy -- -D warnings", "cargo fmt --check"},
		},
		{
			name:     "go",
			stacks:   []string{"go"},
			commands: []string{"go vet ./..."},
		},
		{
			name:     "multi-stack csharp and godot",
			stacks:   []string{"csharp", "gdscript", "godot"},
			commands: []string{"gdlint .", "dotnet format --verify-no-changes", "dotnet build --no-restore"},
		},
		{
			name:     "unknown stack fallback",
			stacks:   []string{"other"},
			commands: nil,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			entries := postEditEntries(tc.stacks)
			var gotCommands []string
			for _, e := range entries {
				gotCommands = append(gotCommands, e.Command)
			}
			if tc.commands == nil {
				if len(entries) != 0 {
					t.Fatalf("want 0 entries for unknown stack, got %v", gotCommands)
				}
				return
			}
			if len(gotCommands) != len(tc.commands) {
				t.Fatalf("got %d commands %v, want %d %v", len(gotCommands), gotCommands, len(tc.commands), tc.commands)
			}
			for i, cmd := range tc.commands {
				if gotCommands[i] != cmd {
					t.Errorf("[%d] got %q, want %q", i, gotCommands[i], cmd)
				}
			}
		})
	}
}

func TestLifecycleHookOrder(t *testing.T) {
	facts := detect.Facts{
		Stacks: []string{"python", "uv"},
		HasGit: true,
	}
	entries := hookEntries(facts, true)
	var events []string
	for _, e := range entries {
		events = append(events, e.Event)
	}
	wantOrder := []string{"SessionStart", "PreToolUse", "PostToolUse", "PostToolUse", "SubagentStart", "SubagentStop", "Stop", "Stop"}
	if len(events) != len(wantOrder) {
		t.Fatalf("got %d events %v, want %d %v", len(events), events, len(wantOrder), wantOrder)
	}
	for i, ev := range wantOrder {
		if events[i] != ev {
			t.Errorf("[%d] got %q, want %q", i, events[i], ev)
		}
	}

	root := t.TempDir()
	o := answered(root)
	o.Agents = "claude,gemini"
	mustRun(t, o)

	settingsContent := read(t, root, ".claude/settings.json")
	keys := []string{"SessionStart", "PreToolUse", "PostToolUse", "SubagentStart", "SubagentStop", "Stop"}
	var positions []int
	for _, k := range keys {
		pos := strings.Index(settingsContent, `"`+k+`"`)
		if pos >= 0 {
			positions = append(positions, pos)
		}
	}
	for i := 1; i < len(positions); i++ {
		if positions[i] <= positions[i-1] {
			t.Fatalf("settings.json keys not in lifecycle order:\n%s", settingsContent)
		}
	}
}

func TestAgentsWithoutClaudeSkipsClaudeSettings(t *testing.T) {
	root := t.TempDir()
	o := answered(root)
	o.Agents = "gemini"
	mustRun(t, o)
	if _, err := osStat(root, ".claude/settings.json"); err == nil {
		t.Fatal("want .claude/settings.json skipped when claude is not in agents")
	}
	answersFile := read(t, root, ".ultraloom/answers.toml")
	if !strings.Contains(answersFile, `agents          = ["gemini"]`) {
		t.Fatalf("agents not in answers.toml:\n%s", answersFile)
	}
}

func TestDocumentTemplatesCreatedAndProtected(t *testing.T) {
	root := t.TempDir()
	os.MkdirAll(filepath.Join(root, ".git"), 0o755)
	// Pre-exist an existing custom AGENTS.md
	existingAgents := "# My Custom Agents Doc\n"
	makeFile(t, root, "AGENTS.md", existingAgents)

	o := answered(root)
	o.Agents = "claude,gemini"
	report := mustRun(t, o)

	// 1. AGENTS.md was skipped / protected
	if !strings.Contains(report, "skipped, already there:") || !strings.Contains(report, "AGENTS.md") {
		t.Fatalf("report does not list AGENTS.md under skipped:\n%s", report)
	}
	if got := read(t, root, "AGENTS.md"); got != existingAgents {
		t.Fatalf("AGENTS.md was modified:\n%s", got)
	}

	// 2. CLAUDE.md, GEMINI.md, and skills were created
	if !strings.Contains(report, "CLAUDE.md") || !strings.Contains(report, "GEMINI.md") {
		t.Fatalf("report does not list CLAUDE.md or GEMINI.md under created:\n%s", report)
	}
	if !strings.Contains(report, ".claude/skills/verify-until-green/SKILL.md") {
		t.Fatalf("report does not list claude skill under created:\n%s", report)
	}
	if !strings.Contains(report, ".agents/skills/verify-until-green/SKILL.md") {
		t.Fatalf("report does not list agents skill under created:\n%s", report)
	}
	claudeContent := read(t, root, "CLAUDE.md")
	if !strings.Contains(claudeContent, "@AGENTS.md") {
		t.Fatalf("CLAUDE.md does not reference @AGENTS.md:\n%s", claudeContent)
	}
	geminiContent := read(t, root, "GEMINI.md")
	if !strings.Contains(geminiContent, "Antigravity") {
		t.Fatalf("GEMINI.md missing Antigravity text:\n%s", geminiContent)
	}
	skillContent := read(t, root, ".claude/skills/verify-until-green/SKILL.md")
	if !strings.Contains(skillContent, "verify-until-green") {
		t.Fatalf("skill file missing content:\n%s", skillContent)
	}
	if !strings.Contains(report, ".githooks/pre-commit") {
		t.Fatalf("report does not list .githooks/pre-commit under created:\n%s", report)
	}
	precommitContent := read(t, root, ".githooks/pre-commit")
	if !strings.Contains(precommitContent, "ultraloom check all") {
		t.Fatalf(".githooks/pre-commit missing command:\n%s", precommitContent)
	}
}

func TestApplyAgentsFlag(t *testing.T) {
	var target []string
	if err := applyAgentsFlag("all", &target); err != nil || len(target) != 2 {
		t.Fatalf("all failed: %v, %v", err, target)
	}
	if err := applyAgentsFlag("none", &target); err != nil || len(target) != 0 {
		t.Fatalf("none failed: %v, %v", err, target)
	}
	if err := applyAgentsFlag("claude, gemini, claude, ", &target); err != nil || len(target) != 2 {
		t.Fatalf("comma list failed: %v, %v", err, target)
	}
	if err := applyAgentsFlag("invalid", &target); err == nil {
		t.Fatal("want error for invalid agent")
	}
}

func TestLandedWithWrittenFiles(t *testing.T) {
	out := landed("something failed", []string{".ultraloom/answers.toml", ".ultraloom/config.toml"})
	if !strings.Contains(out, "something failed") || !strings.Contains(out, "answers.toml") {
		t.Fatalf("landed output unexpected:\n%s", out)
	}
	if got := landed("only error", nil); got != "only error" {
		t.Fatalf("landed empty list got %q", got)
	}
}

func TestRunToolPathsFlagResolvesMissingTools(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "main.py", "print('hello')\n")
	makeFile(t, root, "uv.lock", "")

	opts := Options{
		Root:      root,
		Yes:       true,
		ToolPaths: "uv=/custom/bin/uv, ruff=/custom/bin/ruff, dmypy=/custom/bin/dmypy",
		Look:      func(name string) (string, error) { return "", errors.New("not found") },
	}
	code, report := run(opts)
	if code != exitDone {
		t.Fatalf("run = %d, report:\n%s", code, report)
	}
	if strings.Contains(report, "missing tooling on PATH") {
		t.Fatalf("report should not complain about missing tools when resolved via ToolPaths:\n%s", report)
	}
}

func TestRunInstallToolsFlagInstallsMissingTools(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "main.py", "print('hello')\n")
	makeFile(t, root, "uv.lock", "")

	var installed []string
	execRunner := func(dir string, argv ...string) (string, error) {
		installed = append(installed, strings.Join(argv, " "))
		return "ok", nil
	}

	opts := Options{
		Root:         root,
		Yes:          true,
		InstallTools: true,
		Look:         func(name string) (string, error) { return "", errors.New("not found") },
		Exec:         execRunner,
	}
	code, report := run(opts)
	if code != exitDone {
		t.Fatalf("run = %d, report:\n%s", code, report)
	}
	if !strings.Contains(report, "installed ruff via") || !strings.Contains(report, "installed dmypy via") {
		t.Fatalf("report missing installation notes:\n%s", report)
	}
	if len(installed) < 2 {
		t.Fatalf("expected at least 2 install commands, got: %v", installed)
	}
}

func TestRunInstallToolsFailureReportsError(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "main.py", "print('hello')\n")
	makeFile(t, root, "uv.lock", "")

	failRunner := func(dir string, argv ...string) (string, error) {
		return "", errors.New("network down")
	}

	opts := Options{
		Root:         root,
		Yes:          true,
		InstallTools: true,
		Look:         func(name string) (string, error) { return "", errors.New("not found") },
		Exec:         failRunner,
	}
	code, report := run(opts)
	if code != exitDone {
		t.Fatalf("run = %d, report:\n%s", code, report)
	}
	if !strings.Contains(report, "failed to install ruff") {
		t.Fatalf("report missing failure note:\n%s", report)
	}
}

func TestRunInteractiveToolResolution(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "main.py", "print('hello')\n")
	makeFile(t, root, "uv.lock", "")

	// Answer: default (install), skip ("no"), path ("/usr/bin/dmypy")
	var stdout bytes.Buffer
	stdin := strings.NewReader("\nno\n/usr/bin/dmypy\n")

	var installed []string
	execRunner := func(dir string, argv ...string) (string, error) {
		installed = append(installed, strings.Join(argv, " "))
		return "ok", nil
	}

	opts := Options{
		Root:              root,
		Interactive:       true,
		CommitLanguage:    "en",
		DocsLanguage:      "de",
		Agents:            "all",
		CoverageThreshold: 100,
		WikiMode:          "none",
		In:                stdin,
		Out:               &stdout,
		Look:              func(name string) (string, error) { return "", errors.New("not found") },
		Exec:              execRunner,
	}
	code, report := run(opts)
	if code != exitDone {
		t.Fatalf("run = %d, report:\n%s", code, report)
	}
	if !strings.Contains(report, "installed uv via") {
		t.Fatalf("report missing installed note:\n%s", report)
	}
}

func TestCliFlagsForTooling(t *testing.T) {
	root := t.TempDir()
	var stdout, stderr bytes.Buffer
	code := cli([]string{"--root", root, "--install-tools", "--tool-path", "uv=/bin/uv", "--yes"}, strings.NewReader(""), &stdout, &stderr)
	if code != exitDone {
		t.Fatalf("cli exit = %d, stderr: %s", code, stderr.String())
	}
}

func TestCliVersionAndDetectOnly(t *testing.T) {
	var stdout, stderr bytes.Buffer
	if code := cli([]string{"--version"}, strings.NewReader(""), &stdout, &stderr); code != 0 {
		t.Fatalf("version code = %d", code)
	}
	if !strings.Contains(stdout.String(), version) {
		t.Fatalf("version output = %q", stdout.String())
	}

	stdout.Reset()
	if code := cli([]string{"--help"}, strings.NewReader(""), &stdout, &stderr); code != 0 {
		t.Fatalf("help code = %d", code)
	}

	stdout.Reset()
	root := t.TempDir()
	if code := cli([]string{"--detect-only", "--root", root}, strings.NewReader(""), &stdout, &stderr); code != 0 {
		t.Fatalf("detect-only code = %d", code)
	}
	if !strings.Contains(stdout.String(), `"Stacks"`) {
		t.Fatalf("detect-only output = %q", stdout.String())
	}
}

func TestRunInteractiveToolInstallFailure(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "main.py", "print('hello')\n")
	makeFile(t, root, "uv.lock", "")

	var stdout bytes.Buffer
	stdin := strings.NewReader("yes\n")

	failRunner := func(dir string, argv ...string) (string, error) {
		return "", errors.New("network error")
	}

	opts := Options{
		Root:              root,
		Interactive:       true,
		CommitLanguage:    "en",
		DocsLanguage:      "de",
		Agents:            "all",
		CoverageThreshold: 100,
		WikiMode:          "none",
		In:                stdin,
		Out:               &stdout,
		Look:              func(name string) (string, error) { return "", errors.New("not found") },
		Exec:              failRunner,
	}
	code, report := run(opts)
	if code != exitDone {
		t.Fatalf("run = %d, report:\n%s", code, report)
	}
	if !strings.Contains(report, "failed to install uv") {
		t.Fatalf("report missing failure note:\n%s", report)
	}
}

func TestRunInteractiveInstallNoExec(t *testing.T) {
	root := t.TempDir()
	makeFile(t, root, "main.py", "print('hello')\n")
	makeFile(t, root, "uv.lock", "")

	var stdout bytes.Buffer
	stdin := strings.NewReader("yes\n")

	opts := Options{
		Root:              root,
		Interactive:       true,
		CommitLanguage:    "en",
		DocsLanguage:      "de",
		Agents:            "all",
		CoverageThreshold: 100,
		WikiMode:          "none",
		In:                stdin,
		Out:               &stdout,
		Look:              func(name string) (string, error) { return "", errors.New("not found") },
		Exec:              nil, // No exec runner
	}
	code, report := run(opts)
	if code != exitDone {
		t.Fatalf("run = %d, report:\n%s", code, report)
	}
	if !strings.Contains(report, "missing tooling on PATH") {
		t.Fatalf("report should list missing tools when Exec is nil:\n%s", report)
	}
}

func TestGatherWithExistingWiki(t *testing.T) {
	root := t.TempDir()
	os.MkdirAll(filepath.Join(root, "wiki"), 0o755)
	makeFile(t, root, "wiki/index.md", "---\nokf_version: 1\n---\n# Wiki\n")

	facts, err := gather(root, nil)
	if err != nil {
		t.Fatalf("gather: %v", err)
	}
	if facts.WikiMode != "brain" {
		t.Fatalf("WikiMode = %q, want 'brain'", facts.WikiMode)
	}
}

func TestPostEditEntriesAllStacks(t *testing.T) {
	// 1. Python with uv
	pyUV := postEditEntries([]string{"python", "uv"})
	if len(pyUV) != 2 || !strings.Contains(pyUV[0].Command, "ruff check") || !strings.Contains(pyUV[1].Command, "dmypy run") {
		t.Fatalf("pyUV = %+v", pyUV)
	}

	// 2. Python without uv
	pyPlain := postEditEntries([]string{"python"})
	if len(pyPlain) != 2 || !strings.Contains(pyPlain[0].Command, "ruff check") || !strings.Contains(pyPlain[1].Command, "mypy") {
		t.Fatalf("pyPlain = %+v", pyPlain)
	}

	// 3. GDScript
	gd := postEditEntries([]string{"gdscript"})
	if len(gd) != 1 || !strings.Contains(gd[0].Command, "gdlint .") {
		t.Fatalf("gd = %+v", gd)
	}

	// 4. C#
	cs := postEditEntries([]string{"csharp"})
	if len(cs) != 2 || !strings.Contains(cs[0].Command, "dotnet format") || !strings.Contains(cs[1].Command, "dotnet build") {
		t.Fatalf("cs = %+v", cs)
	}

	// 5. TypeScript
	ts := postEditEntries([]string{"typescript"})
	if len(ts) != 2 || !strings.Contains(ts[0].Command, "npx eslint") || !strings.Contains(ts[1].Command, "npx tsc") {
		t.Fatalf("ts = %+v", ts)
	}

	// 6. Rust
	rs := postEditEntries([]string{"rust"})
	if len(rs) != 2 || !strings.Contains(rs[0].Command, "cargo clippy") || !strings.Contains(rs[1].Command, "cargo fmt") {
		t.Fatalf("rs = %+v", rs)
	}

	// 7. Go
	goEntries := postEditEntries([]string{"go"})
	if len(goEntries) != 1 || !strings.Contains(goEntries[0].Command, "go vet") {
		t.Fatalf("goEntries = %+v", goEntries)
	}

	// 8. Python stack in hookEntries
	pyHookEntries := hookEntries(detect.Facts{Stacks: []string{"python"}}, false)
	foundRuff := false
	for _, e := range pyHookEntries {
		if e.Event == "PostToolUse" && strings.Contains(e.Command, "ruff check") {
			foundRuff = true
			break
		}
	}
	if !foundRuff {
		t.Fatalf("ruff check not found in pyHookEntries: %+v", pyHookEntries)
	}
}
