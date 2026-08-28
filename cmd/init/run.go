package main

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/xidus90/ultra-loom/internal/answers"
	"github.com/xidus90/ultra-loom/internal/brainpath"
	"github.com/xidus90/ultra-loom/internal/coverage"
	"github.com/xidus90/ultra-loom/internal/detect"
	"github.com/xidus90/ultra-loom/internal/interview"
	"github.com/xidus90/ultra-loom/internal/render"
	"github.com/xidus90/ultra-loom/internal/settings"
	"github.com/xidus90/ultra-loom/internal/vendoring"
	"github.com/xidus90/ultra-loom/internal/write"
)

// Exit codes. This is the whole contract towards a caller that is not a
// person: a run that changed nothing must never look like one that did.
const (
	exitDone    = 0
	exitOwn     = 1
	exitRefused = 2
)

// settingsPath is the one file init merges into instead of leaving alone, and
// therefore the one that does not travel through internal/write.
const settingsPath = ".claude/settings.json"

const mcpPath = ".mcp.json"

const installedPath = ".ultraloom/installed.toml"

// answersPath names the file the installed hash is taken over: the hash
// answers "did somebody edit the output instead of the source?", and the
// source is this file.
const answersPath = ".ultraloom/answers.toml"

// onPath is what brainpath.Find returns when brain is an entry on PATH -- the
// bare name, the only form that may go into a committed file. Anything else it
// returns carries a directory of this machine.
const onPath = "brain"

// Options is everything the process edge hands in: the flags, and the three
// pieces of the outside world this program is allowed to touch. Those are
// injected rather than reached for, so a test needs no PATH, no environment,
// no network and no repository.
type Options struct {
	Root        string
	DryRun      bool
	Yes         bool
	Interactive bool

	CommitLanguage    string
	DocsLanguage      string
	WikiMode          string
	CoverageThreshold int
	// The two policy answers are strings rather than bools because they have
	// three states: yes, no, and not given -- and only the third may reach the
	// interview. A bool flag would answer "no" for a question nobody asked.
	ProtectMigrations string
	ForbidPipInstall  string

	VendorURL string
	VendorRef string

	In  io.Reader
	Out io.Writer

	// Exec runs one command in one directory, the word of the executable
	// included; git is the only one this program ever starts.
	Exec   detect.Runner
	Look   brainpath.Lookup
	Getenv func(string) string
}

// run is the whole program without the process: everything it decides comes
// from Options, and everything it says comes back as one report.
//
// The order is the contract -- detect, ask, render, check, then write. Nothing
// touches the disk before the writing step, which is what makes --dry-run the
// same run minus its last part rather than a second code path.
func run(opts Options) (int, string) {
	facts, err := gather(opts.Root, opts.Exec)
	if err != nil {
		return exitOwn, err.Error()
	}

	current, err := decisions(opts.Root, facts)
	if err != nil {
		return exitOwn, err.Error()
	}
	filled, err := ask(opts, applyFlags(current, opts))
	if errors.Is(err, interview.ErrNoTTY) {
		return exitRefused, err.Error()
	}
	if err != nil {
		return exitOwn, err.Error()
	}

	files, err := render.Render(filled)
	// Unreachable while the embedded templates parse and execute, which the
	// build settles rather than the run. Handled anyway: a swallowed template
	// error would write half a configuration.
	if err != nil {
		return exitOwn, err.Error()
	}

	var notes []string
	notes = append(notes, coverageNote(filled, opts.Root)...)
	mcp, wikiHooks, brainNote := brainEntry(filled, opts)
	if mcp != "" {
		files[mcpPath] = mcp
	}
	notes = append(notes, brainNote)
	if !facts.HasGit {
		notes = append(notes, "no git repository here: the hooks that need one "+
			"(stop gate, subagent reports) were left out")
	}

	// The vendored runtime has to stand before installed.toml can name the
	// commit it pinned, so the clone is the one write that goes first -- and it
	// goes into a directory of ours, never over somebody's file.
	ref, commit := opts.VendorRef, ""
	if opts.VendorURL != "" && !opts.DryRun {
		commit, err = vendoring.Clone(gitOnly(opts.Exec), opts.Root, opts.VendorURL, ref)
		if err != nil {
			return exitOwn, err.Error()
		}
	}

	// The list names what init owns in this project, not what this one run
	// happened to create: a second run finds most of it already there, and a
	// later sync needs the whole inventory to compare against, not the
	// remainder of it.
	files[installedPath] = vendoring.InstalledTOML(ref, commit,
		hashOf(files[answersPath]), append(names(files), installedPath))

	plan, err := write.Prepare(opts.Root, files)
	// Unreachable for these names: they are constants of this package and of
	// internal/render, and every refusal Prepare has is about a name that
	// could leave the project. Handled because a Plan is also built by hand.
	if err != nil {
		return exitOwn, err.Error()
	}

	merged, code, note := mergeSettings(opts, facts, wikiHooks)
	if code != exitDone {
		return code, note
	}
	notes = append(notes, note)

	if opts.DryRun {
		return exitDone, describe(plan, merged.what, notes, true)
	}
	if err := write.Commit(opts.Root, plan); err != nil {
		return exitOwn, err.Error()
	}
	if err := merged.apply(); err != nil {
		return exitOwn, err.Error()
	}
	return exitDone, describe(plan, merged.what, notes, false)
}

// decisions is what this run starts from: the answer file a previous run left,
// and the conventions of this tool where there is none.
func decisions(root string, facts detect.Facts) (answers.Answers, error) {
	raw, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(answersPath)))
	if err != nil {
		return seed(facts), nil
	}
	loaded, err := answers.Load(raw)
	if err != nil {
		return answers.Answers{}, err
	}
	// Stacks are a fact, not a decision: they are re-read on every run, so a
	// project that grew a second language gets its checks without an edit.
	loaded.Project.Stacks = facts.Stacks
	return loaded, nil
}

// seed is answers.Defaults minus the answers the interview owns.
//
// Defaults fills every field, the questions included, which would leave
// interview.Missing nothing to ask and a caller without a TTY nothing to be
// told. The values are not lost: every question carries the same default, so
// an unattended run lands on exactly what Defaults would have set -- the only
// difference is that a missing answer can now be named.
func seed(facts detect.Facts) answers.Answers {
	a := answers.Defaults(facts)
	a.Project.CommitLanguage, a.Project.DocsLanguage = "", ""
	a.Gates.CoverageThreshold = 0
	a.Gates.Wiki.Mode = facts.WikiMode
	return a
}

// applyFlags is where a flag becomes an answer. interview.Question keeps its
// setter unexported, so the mapping lives here rather than being driven from
// the question list -- and a flag that is set is simply an answer already
// given, which is what makes an unattended run possible at all.
func applyFlags(current answers.Answers, opts Options) answers.Answers {
	if opts.CommitLanguage != "" {
		current.Project.CommitLanguage = opts.CommitLanguage
	}
	if opts.DocsLanguage != "" {
		current.Project.DocsLanguage = opts.DocsLanguage
	}
	if opts.WikiMode != "" {
		current.Gates.Wiki.Mode = opts.WikiMode
	}
	if opts.CoverageThreshold != 0 {
		current.Gates.CoverageThreshold = opts.CoverageThreshold
	}
	current.Policy.ProtectedPaths = choice(opts.ProtectMigrations,
		current.Policy.ProtectedPaths, migrationGlob)
	current.Policy.ForbiddenCommands = choice(opts.ForbidPipInstall,
		current.Policy.ForbiddenCommands, pipInstall)
	return current
}

// migrationGlob repeats internal/interview's own constant rather than
// importing it: that one is unexported, and a rule this specific belongs
// written out where a reader of the flag can see what the flag protects.
const migrationGlob = "migrations/[0-9][0-9][0-9][0-9]_*.py"

const pipInstall = "pip install"

// choice turns a three-state flag into the list shape the renderer reads: the
// list holding the entry for yes, an empty one for no -- which is an answer of
// its own -- and whatever stood there for a flag nobody passed.
func choice(given string, current []string, entry string) []string {
	switch strings.ToLower(given) {
	case "yes":
		return []string{entry}
	case "no":
		return []string{}
	}
	return current
}

// ask runs the interview, and reads --yes as an interview nobody types into:
// the end of input is an answer there, and it takes every default. One
// mechanism instead of two, so an unattended run and a person pressing return
// land on the same file.
func ask(opts Options, current answers.Answers) (answers.Answers, error) {
	in, out, interactive := opts.In, opts.Out, opts.Interactive
	if opts.Yes {
		in, out, interactive = strings.NewReader(""), io.Discard, true
	}
	if in == nil {
		in = strings.NewReader("")
	}
	if out == nil {
		out = io.Discard
	}
	return interview.Run(in, out, interactive, current)
}

// coverageNote reports rather than repairs. The threshold is enforced by the
// coverage tool's own fail_under and by nothing else, and pyproject.toml is
// somebody else's file: a green line for a threshold nobody checks is the one
// failure of this system that does real damage.
//
// Python only, because those two files are the only ones Enforced can read. A
// project without that stack would be warned about a setting it has no place
// to put.
func coverageNote(filled answers.Answers, root string) []string {
	if !has(filled.Project.Stacks, "python") {
		return nil
	}
	if coverage.Enforced(readOr(root, "pyproject.toml"), readOr(root, ".coveragerc")) {
		return nil
	}
	return []string{fmt.Sprintf(
		"nothing enforces the coverage threshold of %d%%: add fail_under to "+
			"[tool.coverage.report] in pyproject.toml, or the coverage check "+
			"reports a number it can never fail on",
		filled.Gates.CoverageThreshold)}
}

// brainEntry decides what a found brain may put into a versioned file.
//
// Three outcomes, and the middle one is why this is a function of its own:
// brain reached through ULTRA_BRAIN_DIR is a path on one machine, while both
// .mcp.json and settings.json are committed. Such an entry is reported for the
// user to add rather than written, and the wiki hook stays out with it --
// it would carry the same path. Not found at all installs neither, because a
// gate that cannot run is worse than none.
func brainEntry(filled answers.Answers, opts Options) (mcp string, wikiHooks bool, note string) {
	if filled.Gates.Wiki.Mode != "brain" {
		return "", false, ""
	}
	command, found := brainpath.Find(opts.Look, opts.Getenv)
	if !found {
		return "", false, "brain is neither on PATH nor named by " +
			"ULTRA_BRAIN_DIR: no " + mcpPath + " entry and no wiki hook, " +
			"because a gate that cannot run is worse than none"
	}
	if command != onPath {
		return "", false, "brain was found only through ULTRA_BRAIN_DIR, which " +
			"is a path on this machine and must not go into a committed file. " +
			"Add this to " + mcpPath + " yourself, and the wiki hook with it:\n" +
			brainpath.MCPEntry(command)
	}
	return brainpath.MCPEntry(command), true, ""
}

// settingsWrite is the merge decided and not yet applied, so the settings file
// obeys the same rule as every other one: decide first, write last.
type settingsWrite struct {
	root    string
	body    []byte
	changed bool
	what    string
}

func (s settingsWrite) apply() error {
	if !s.changed {
		return nil
	}
	full := filepath.Join(s.root, filepath.FromSlash(settingsPath))
	if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
		return fmt.Errorf("creating the directory for %s: %w", settingsPath, err)
	}
	// The one write that may land on a file that is already there, and the
	// reason the merge above refuses to touch an entry it does not own.
	if err := os.WriteFile(full, s.body, 0o644); err != nil {
		return fmt.Errorf("writing %s: %w", settingsPath, err)
	}
	return nil
}

// mergeSettings folds this tool's hook entries into a file that belongs to
// someone else. A file that is not JSON is the project saying no rather than
// this program failing: exit 2, and nothing repaired.
func mergeSettings(opts Options, facts detect.Facts, wikiHooks bool) (settingsWrite, int, string) {
	existing := readOr(opts.Root, settingsPath)
	result, err := settings.Merge(existing, hookEntries(facts, wikiHooks))
	if err != nil {
		return settingsWrite{}, exitRefused, err.Error()
	}
	out := settingsWrite{root: opts.Root, body: result.Merged, what: settingsPath,
		changed: string(existing) != string(result.Merged)}
	// A file that comes back as it went in is nothing this run created, and
	// naming it under "created" would be the report lying by one line.
	if !out.changed {
		out.what = ""
	}
	note := ""
	if len(result.Skipped) > 0 {
		note = settingsPath + ": left to the project -- " + strings.Join(result.Skipped, "; ")
	}
	return out, exitDone, note
}

// hookCommand builds what a generated hook runs. It points at the vendored
// runtime relative to the project and never at a directory on this machine:
// the file it lands in is committed.
func hookCommand(argv string) string {
	return `uv run --project "${CLAUDE_PROJECT_DIR}/` + vendoring.VendorDir +
		`" ultraloom ` + argv + ` --root "${CLAUDE_PROJECT_DIR}"`
}

// hookEntries is the minimal set that makes a fresh project work. Which
// version of each hook finally wins is a question for the consolidation of the
// six repositories, not for the installer.
//
// Without git the hooks that read history stay out rather than being installed
// broken: each of them answers "what changed since the base commit?", and
// without a repository that question has no answer at all.
func hookEntries(facts detect.Facts, wikiHooks bool) []settings.Entry {
	entries := []settings.Entry{
		{Event: "PreToolUse", Matcher: "Write|Edit|NotebookEdit|Bash|PowerShell",
			Command: hookCommand("policy hook"), Timeout: 10},
		{Event: "PostToolUse", Matcher: "Write|Edit|NotebookEdit",
			Command: hookCommand("hook post-edit"), Timeout: 60},
		{Event: "SessionStart", Command: hookCommand("hook session-start"), Timeout: 20},
	}
	if facts.HasGit {
		entries = append(entries,
			settings.Entry{Event: "SubagentStart",
				Command: hookCommand("hook subagent-start"), Timeout: 30},
			settings.Entry{Event: "SubagentStop",
				Command: hookCommand("hook subagent-stop"), Timeout: 30},
			settings.Entry{Event: "Stop", Command: hookCommand("hook stop"), Timeout: 300})
	}
	if wikiHooks {
		// A matcher on Stop, which the client ignores, so that the merge sees a
		// slot of its own: identity there is (event, matcher), and an empty one
		// would make this entry replace the stop gate above.
		entries = append(entries, settings.Entry{Event: "Stop", Matcher: "wiki",
			Command: "brain lint", Timeout: 120})
	}
	return entries
}

// describe is the whole output of a run, in the order write.Commit works in,
// so what a dry run promised and what a failed run left behind line up.
func describe(plan write.Plan, settingsWhat string, notes []string, dry bool) string {
	var out strings.Builder
	verb := "created"
	if dry {
		verb = "would create"
	}
	names := plan.Names()
	if settingsWhat != "" {
		names = append(names, settingsWhat+" (merged)")
		sort.Strings(names)
	}
	if len(names) > 0 {
		fmt.Fprintf(&out, "%s:\n", verb)
		for _, name := range names {
			fmt.Fprintf(&out, "  %s\n", name)
		}
	}
	if len(plan.Skip) > 0 {
		out.WriteString("skipped, already there:\n")
		for _, name := range plan.Skip {
			fmt.Fprintf(&out, "  %s\n", name)
		}
	}
	for _, note := range notes {
		if note != "" {
			fmt.Fprintf(&out, "note: %s\n", note)
		}
	}
	return out.String()
}

// names is every file init owns, in one order, so installed.toml is a
// function of what was installed rather than of map iteration.
func names(files map[string]string) []string {
	all := make([]string, 0, len(files))
	for name := range files {
		all = append(all, name)
	}
	sort.Strings(all)
	return all
}

// gitOnly adapts the one command runner this program has to vendoring, whose
// Runner takes argv without the word git. Two contracts for the same
// executable: detect.HooksPath names it in argv, vendoring does not.
func gitOnly(exec detect.Runner) vendoring.Runner {
	return func(dir string, argv ...string) (string, error) {
		return exec(dir, append([]string{"git"}, argv...)...)
	}
}

// readOr reads a file the project may or may not have. Every caller here asks
// about one whose absence is the normal case, and an unreadable file is the
// same answer as a missing one: nothing to go on.
func readOr(root, name string) []byte {
	body, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(name)))
	if err != nil {
		return nil
	}
	return body
}

// hashOf is what tells an edited output from an edited source apart later: a
// sync run compares this against the answer file it finds.
func hashOf(body string) string {
	sum := sha256.Sum256([]byte(body))
	return hex.EncodeToString(sum[:])
}

func has(all []string, wanted string) bool {
	for _, one := range all {
		if one == wanted {
			return true
		}
	}
	return false
}
