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
	"strconv"
	"strings"

	"github.com/xidus90/ultra-loom/internal/answers"
	"github.com/xidus90/ultra-loom/internal/brainpath"
	"github.com/xidus90/ultra-loom/internal/coverage"
	"github.com/xidus90/ultra-loom/internal/detect"
	"github.com/xidus90/ultra-loom/internal/interview"
	"github.com/xidus90/ultra-loom/internal/render"
	"github.com/xidus90/ultra-loom/internal/settings"
	"github.com/xidus90/ultra-loom/internal/tooling"
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

const preCommitHook = `#!/usr/bin/env bash
# ultraloom pre-commit quality gate
set -euo pipefail

uv run ultraloom check all
`

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
	Agents            string
	WikiMode          string
	CoverageThreshold int
	// The two policy answers are strings rather than bools because they have
	// three states: yes, no, and not given -- and only the third may reach the
	// interview. A bool flag would answer "no" for a question nobody asked.
	ProtectMigrations string
	ForbidPipInstall  string

	InstallTools bool
	ToolPaths    string

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

	current, recorded, err := decisions(opts.Root, facts)
	if err != nil {
		return exitOwn, err.Error()
	}
	chosen, ignored, err := applyFlags(current, opts, recorded)
	if err != nil {
		return exitOwn, err.Error()
	}
	filled, err := ask(opts, chosen)
	if errors.Is(err, interview.ErrNoTTY) {
		return exitRefused, err.Error()
	}
	if err != nil {
		return exitOwn, err.Error()
	}

	// Read once and used twice: it decides whether a coverage check is
	// installed, and it decides what the user is told about why.
	enforced := coverage.Enforced(
		readOr(opts.Root, "pyproject.toml"), readOr(opts.Root, ".coveragerc"))
	files, err := render.Render(filled, coverageLane(filled, enforced))
	// Unreachable while the embedded templates parse and execute, which the
	// build settles rather than the run. Handled anyway: a swallowed template
	// error would write half a configuration.
	if err != nil {
		return exitOwn, err.Error()
	}

	var notes []string
	notes = append(notes, ignored...)
	notes = append(notes, coverageNote(filled, enforced)...)
	mcp, wikiHooks, brainNote := brainEntry(filled, opts)
	if mcp != "" {
		files[mcpPath] = mcp
	}
	notes = append(notes, brainNote)
	if !facts.HasGit {
		notes = append(notes, "no git repository here: the hooks that need one "+
			"(stop gate, subagent reports) were left out")
	} else {
		files[".githooks/pre-commit"] = preCommitHook
	}

	look := tooling.LookPathFunc(opts.Look)
	_, missing := tooling.CheckTools(facts.Stacks, look)
	if opts.ToolPaths != "" {
		explicitPaths := make(map[string]string)
		for _, part := range strings.Split(opts.ToolPaths, ",") {
			part = strings.TrimSpace(part)
			if kv := strings.SplitN(part, "=", 2); len(kv) == 2 {
				explicitPaths[strings.TrimSpace(kv[0])] = strings.TrimSpace(kv[1])
			}
		}
		var remaining []tooling.ToolSpec
		for _, m := range missing {
			if explicitPaths[m.Name] == "" {
				remaining = append(remaining, m)
			}
		}
		missing = remaining
	}

	if opts.InstallTools && opts.Exec != nil {
		var stillMissing []tooling.ToolSpec
		for _, m := range missing {
			if m.InstallCmd != "" {
				err := tooling.InstallTool(m, tooling.Runner(opts.Exec), opts.Root)
				if err != nil {
					notes = append(notes, fmt.Sprintf("failed to install %s: %v", m.Name, err))
					stillMissing = append(stillMissing, m)
				} else {
					notes = append(notes, fmt.Sprintf("installed %s via %s", m.Name, m.InstallCmd))
				}
			} else {
				stillMissing = append(stillMissing, m)
			}
		}
		missing = stillMissing
	} else if opts.Interactive && !opts.Yes && len(missing) > 0 {
		resolutions, err := interview.AskTools(opts.In, opts.Out, true, missing)
		if err == nil {
			var stillMissing []tooling.ToolSpec
			for _, res := range resolutions {
				switch res.Action {
				case interview.ToolInstall:
					if opts.Exec != nil && res.Spec.InstallCmd != "" {
						err := tooling.InstallTool(res.Spec, tooling.Runner(opts.Exec), opts.Root)
						if err != nil {
							notes = append(notes, fmt.Sprintf("failed to install %s: %v", res.Spec.Name, err))
							stillMissing = append(stillMissing, res.Spec)
						} else {
							notes = append(notes, fmt.Sprintf("installed %s via %s", res.Spec.Name, res.Spec.InstallCmd))
						}
					} else {
						stillMissing = append(stillMissing, res.Spec)
					}
				case interview.ToolPath:
					// Custom path provided by user
				case interview.ToolSkip:
					stillMissing = append(stillMissing, res.Spec)
				}
			}
			missing = stillMissing
		}
	}

	if len(missing) > 0 {
		var missingList []string
		for _, m := range missing {
			missingList = append(missingList, fmt.Sprintf("%s (%s)", m.Name, m.InstallCmd))
		}
		notes = append(notes, "missing tooling on PATH: "+strings.Join(missingList, ", "))
	}

	// Decided before the clone, although it is applied last: the merge is the
	// step that can still say no, and a project refused for a settings.json
	// nobody may touch must not first get a runtime cloned into it.
	merged, code, note := mergeSettings(opts, facts, filled, wikiHooks)
	if code != exitDone {
		return code, note
	}
	notes = append(notes, note)

	// The vendored runtime has to stand before installed.toml can name the
	// commit it pinned, so the clone is the one write that goes first -- and it
	// goes into a directory of ours, never over somebody's file.
	ref, commit := opts.VendorRef, ""
	occupied, usable, err := vendorPresent(opts.Root)
	if err != nil {
		return exitOwn, err.Error()
	}
	if opts.VendorURL != "" {
		switch {
		case occupied:
			// Not an error: a project that already carries a runtime is the
			// normal second run, and the same rule holds here as for every
			// other file -- what is already there belongs to the project.
			// The pin goes with it: this run fetched nothing, so it records
			// nothing.
			ref = ""
			notes = append(notes, vendoring.VendorDir+" is already there: "+
				"nothing was cloned and the runtime standing in this project "+
				"was left untouched -- replacing a pinned runtime is an "+
				"upgrade, not an install")
		case opts.DryRun:
			// Named, because a clone is the largest thing this run would do
			// and a dry run that stayed silent about it would promise the
			// smaller run.
			notes = append(notes, fmt.Sprintf("would clone %s at %s into %s",
				opts.VendorURL, ref, vendoring.VendorDir))
		default:
			commit, err = vendoring.Clone(gitOnly(opts.Exec), opts.Root, opts.VendorURL, ref)
			if err != nil {
				return exitOwn, discardClone(opts.Root, err)
			}
		}
	}
	if opts.VendorURL == "" && !usable {
		// Every generated hook points at the vendored runtime, and there is no
		// second road: a project without one has a settings.json whose
		// PreToolUse hook fails on every Write, Edit and Bash. Reported rather
		// than filled in from a default url -- a plain init would then reach
		// the network on a machine that may have none, and this tool has no
		// version of itself it can honestly pin a stranger's project to.
		notes = append(notes, "no runtime is vendored: every generated hook "+
			"runs the ultraloom in "+vendoring.VendorDir+", and nothing is "+
			"there yet -- pass --vendor-url and --vendor-ref to clone it, or "+
			"the hooks fail on every edit")
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

	if opts.DryRun {
		return exitDone, describe(plan, merged.what, notes, true)
	}
	written, err := write.Commit(opts.Root, plan)
	if err != nil {
		return exitOwn, landed(err.Error(), written)
	}
	if err := merged.apply(); err != nil {
		// Everything write.Commit had to do is done by now, so the whole plan
		// is what this run left standing.
		return exitOwn, landed(err.Error(), written)
	}
	if facts.HasGit && facts.HooksPath == "" && opts.Exec != nil {
		_, _ = opts.Exec(opts.Root, "git", "config", "core.hooksPath", ".githooks")
	}
	return exitDone, describe(plan, merged.what, notes, false)
}

// decisions is what this run starts from: the answer file a previous run left,
// and the conventions of this tool where there is none. The second value says
// which of the two it was -- a recorded answer outranks a flag, and only a
// caller that knows the difference can say so.
func decisions(root string, facts detect.Facts) (answers.Answers, bool, error) {
	raw, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(answersPath)))
	if err != nil {
		return seed(facts), false, nil
	}
	loaded, err := answers.Load(raw)
	if err != nil {
		return answers.Answers{}, false, err
	}
	// Stacks are a fact, not a decision: they are re-read on every run, so a
	// project that grew a second language gets its checks without an edit.
	loaded.Project.Stacks = facts.Stacks
	return loaded, true, nil
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
	a.Project.Agents = nil
	a.Gates.CoverageThreshold = 0
	a.Gates.Wiki.Mode = facts.WikiMode
	return a
}

// applyFlags is where a flag becomes an answer, and where it is judged.
//
// interview.Question keeps its setter unexported, so the mapping lives here
// rather than being driven from the question list. That costs the validation
// the interview would have done: a flag that is set answers the question, and
// the question -- with its check -- is then never asked. So the check stands
// here instead. Without it `--wiki-mode nonsense` was a run that reported
// success and left an answers.toml that its own next run could not read.
//
// A bad flag is the caller's error, and it is caught before anything is
// written: exit 1, the flag named, and the accepted values with it.
//
// Where answers.toml already holds an answer, that answer wins and the flag is
// reported as ignored. The recorded value is the one on disk and the one the
// generated files were made from, and that file is skipped like every other
// existing one, so letting the flag through would render a project against a
// number its own answers.toml does not contain. Until 2026-08-28 it did
// exactly that: `--coverage-threshold 55` over a project recorded at 100
// printed "nothing here enforces the threshold of 55%" while the file said 100
// and every file was listed as skipped. Changing a recorded answer is an edit
// of answers.toml, not a flag.
func applyFlags(current answers.Answers, opts Options, recorded bool) (answers.Answers, []string, error) {
	// Vendoring takes both flags or neither, and each half alone is refused
	// rather than read as an intention. A url with no ref is not a pin --
	// vendoring.Clone refuses the empty ref, but only once a run reaches it,
	// and a dry run never does, so it promised a clone that could not have
	// happened. A ref with no url is the same mistake from the other side: it
	// names a version of something nobody asked to fetch, and quietly ignoring
	// it leaves the caller believing their project is pinned.
	if opts.VendorURL != "" && opts.VendorRef == "" {
		return current, nil, fmt.Errorf(
			"--vendor-url without --vendor-ref: name the branch, tag or commit to pin")
	}
	if opts.VendorRef != "" && opts.VendorURL == "" {
		return current, nil, fmt.Errorf(
			"--vendor-ref without --vendor-url: name the repository to clone")
	}
	kept := keeper{recorded: recorded}
	if opts.CommitLanguage != "" && !kept.text("--commit-language",
		"[project].commit_language", current.Project.CommitLanguage, opts.CommitLanguage) {
		current.Project.CommitLanguage = opts.CommitLanguage
	}
	if opts.DocsLanguage != "" && !kept.text("--docs-language",
		"[project].docs_language", current.Project.DocsLanguage, opts.DocsLanguage) {
		current.Project.DocsLanguage = opts.DocsLanguage
	}
	if opts.Agents != "" {
		var parsed []string
		if err := applyAgentsFlag(opts.Agents, &parsed); err != nil {
			return current, nil, fmt.Errorf("--agents %w", err)
		}
		if !kept.list("--agents", "[project].agents", current.Project.Agents, parsed) {
			current.Project.Agents = parsed
		}
	}
	if opts.WikiMode != "" {
		if !has(answers.WikiModes, opts.WikiMode) {
			return current, nil, fmt.Errorf("--wiki-mode %q: it must be one of %v",
				opts.WikiMode, answers.WikiModes)
		}
		if !kept.text("--wiki-mode", "[gates.wiki].mode",
			current.Gates.Wiki.Mode, opts.WikiMode) {
			current.Gates.Wiki.Mode = opts.WikiMode
		}
	}
	if opts.CoverageThreshold != 0 {
		// Zero is the unset flag rather than a threshold of nothing: a project
		// that really wants no floor says so by leaving the coverage tool
		// unconfigured, which is what coverageNote then reports.
		if opts.CoverageThreshold < 0 || opts.CoverageThreshold > 100 {
			return current, nil, fmt.Errorf(
				"--coverage-threshold %d: it must be between 0 and 100",
				opts.CoverageThreshold)
		}
		if !kept.text("--coverage-threshold", "[gates].coverage_threshold",
			number(current.Gates.CoverageThreshold), number(opts.CoverageThreshold)) {
			current.Gates.CoverageThreshold = opts.CoverageThreshold
		}
	}
	protected, err := choice("--protect-migrations", opts.ProtectMigrations,
		current.Policy.ProtectedPaths, migrationGlob)
	if err != nil {
		return current, nil, err
	}
	if opts.ProtectMigrations != "" && !kept.list("--protect-migrations",
		"[policy].protected_paths", current.Policy.ProtectedPaths, protected) {
		current.Policy.ProtectedPaths = protected
	}
	forbidden, err := choice("--forbid-pip-install", opts.ForbidPipInstall,
		current.Policy.ForbiddenCommands, pipInstall)
	if err != nil {
		return current, nil, err
	}
	if opts.ForbidPipInstall != "" && !kept.list("--forbid-pip-install",
		"[policy].forbidden_commands", current.Policy.ForbiddenCommands, forbidden) {
		current.Policy.ForbiddenCommands = forbidden
	}
	return current, kept.notes, nil
}

// keeper collects the flags a recorded answer overruled.
//
// One place rather than six, because the sentence has to read the same every
// time: which field decided, what it says, and which flag was dropped. A
// caller told only "ignored" would have to go and read the file to learn what
// won.
type keeper struct {
	recorded bool
	notes    []string
}

// text reports whether the recorded answer stands. It does for a run that read
// an answers.toml and found something under the field: an empty field is a
// question that file never answered, and a flag may still answer it. An
// identical value is no conflict and stays silent.
func (k *keeper) text(flag, field, was, wanted string) bool {
	if !k.recorded || was == "" || was == wanted {
		return false
	}
	k.notes = append(k.notes, fmt.Sprintf(
		"%s was ignored: %s already answers %s in %s, and a recorded answer is "+
			"changed by editing that file, not by a flag", flag, field, was, answersPath))
	return true
}

// list is text for the two answers that are lists. Empty cannot be told from
// "answered no" here -- both are an empty list -- so a file that was read
// speaks for both, and only a flag that would change the list is reported.
func (k *keeper) list(flag, field string, was, wanted []string) bool {
	if !k.recorded || same(was, wanted) {
		return false
	}
	k.notes = append(k.notes, fmt.Sprintf(
		"%s was ignored: %s already answers %v in %s, and a recorded answer is "+
			"changed by editing that file, not by a flag", flag, field, was, answersPath))
	return true
}

// same compares two answer lists as one word each. The separator is the one
// byte neither a path glob nor a command line can hold, so joining cannot make
// two different lists look alike -- and it is one expression rather than a
// loop whose body no caller here can reach: choice only ever returns the fixed
// entry or nothing.
func same(left, right []string) bool {
	const sep = "\x00"
	return strings.Join(left, sep) == strings.Join(right, sep)
}

// number puts an int where keeper.text wants a word, so the six answers are
// reported by one sentence rather than by two that drift apart.
func number(value int) string { return strconv.Itoa(value) }

// migrationGlob repeats internal/interview's own constant rather than
// importing it: that one is unexported, and a rule this specific belongs
// written out where a reader of the flag can see what the flag protects.
const migrationGlob = "migrations/[0-9][0-9][0-9][0-9]_*.py"

const pipInstall = "pip install"

// choice turns a three-state flag into the list shape the renderer reads: the
// list holding the entry for yes, an empty one for no -- which is an answer of
// its own -- and whatever stood there for a flag nobody passed.
//
// A fourth thing is not a state. Anything but yes, no and nothing is refused
// rather than dropped: dropping it would run the whole install under an answer
// the caller believes they gave.
//
// The short forms are here because interview.applyChoice takes them. Two roads
// to one answer file, so the same word has to mean the same thing on both --
// a `y` that the prompt accepts and the flag rejects makes the flag a
// different question wearing the same name. The interview is the reference:
// narrowing it instead would take a spelling away from people who already
// type it.
func choice(flag, given string, current []string, entry string) ([]string, error) {
	switch strings.ToLower(given) {
	case "":
		return current, nil
	case "yes", "y":
		return []string{entry}, nil
	case "no", "n":
		return []string{}, nil
	}
	return current, fmt.Errorf("%s %q: answer yes or no", flag, given)
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

// coverageLane says whether the generated project gets a coverage check.
//
// Dropped only where the answer is known. coverage.Enforced reads
// pyproject.toml and .coveragerc, so it can speak for Python and for nothing
// else: a Node project keeps its thresholds where this cannot see them, and
// removing its check on a guess would open the same silent gap in the other
// direction. Unknown therefore keeps the lane, which is the rule the whole
// relevance mapping follows.
//
// The residual, so nobody has to work it out from the return line: a Node
// project gets a coverage lane whose enforcement was never established. Its
// vitest thresholds live in the vitest configuration, which nothing here
// reads. That is unverified, not verified-absent -- the fail-safe of the two
// -- and closing it means teaching this to read a second language's
// configuration, not narrowing what it drops. coverageNote says so in the
// report, which is where the person who can close it will see it.
func coverageLane(filled answers.Answers, enforced bool) bool {
	return enforced || !has(filled.Project.Stacks, "python")
}

// coverageNote reports what the generated files no longer claim, and what
// they claim without having checked.
//
// Two different answers, and neither of them is silence. For Python the
// threshold is enforced by the coverage tool's own fail_under and by nothing
// else, and pyproject.toml is somebody else's file -- init does not write
// there. So the check is left out instead, and this says why and what brings
// it back.
//
// Everywhere else the lane is kept, because dropping a lane a project may
// well enforce opens the same silent gap from the other side. But kept is not
// verified: the Node preset is `vitest run --coverage`, which exits 0 at any
// number unless the project configured coverage.thresholds where nothing here
// looks. Until this fix the reasoning lived only in a Go comment, so the one
// person who could close the gap never heard about it.
func coverageNote(filled answers.Answers, enforced bool) []string {
	if enforced {
		return nil
	}
	if !has(filled.Project.Stacks, "python") {
		return []string{fmt.Sprintf(
			"the coverage lane was kept but not verified: nothing outside "+
				"Python's own pyproject.toml and .coveragerc is read here, so "+
				"whether the threshold of %d%% is enforced at all is unknown -- "+
				"check that your test runner fails below it, or the lane "+
				"reports a number it can never fail on",
			filled.Gates.CoverageThreshold)}
	}
	return []string{fmt.Sprintf(
		"no coverage check was installed: nothing here enforces the threshold "+
			"of %d%% -- add fail_under to [tool.coverage.report] in "+
			"pyproject.toml and run init again, or the lane would report a "+
			"number it can never fail on",
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
	// The same guard the other four files get. This one write does its own
	// MkdirAll and OpenFile, and until 2026-08-28 that meant a .claude that is
	// a link put settings.json outside the project, at exit 0, reported as
	// created.
	if err := write.CheckParents(s.root, settingsPath); err != nil {
		return err
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
func mergeSettings(opts Options, facts detect.Facts, filled answers.Answers, wikiHooks bool) (settingsWrite, int, string) {
	if !has(filled.Project.Agents, "claude") {
		return settingsWrite{}, exitDone, ""
	}
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
		{Event: "SessionStart", Command: hookCommand("hook session-start"), Timeout: 20},
		{Event: "PreToolUse", Matcher: "Write|Edit|NotebookEdit|Bash|PowerShell",
			Command: `ulguard --root "${CLAUDE_PROJECT_DIR}"`, Timeout: 10},
	}

	postEdit := postEditEntries(facts.Stacks)
	if len(postEdit) > 0 {
		entries = append(entries, postEdit...)
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

func applyAgentsFlag(given string, target *[]string) error {
	trimmed := strings.TrimSpace(given)
	if strings.EqualFold(trimmed, "all") {
		*target = []string{"claude", "gemini"}
		return nil
	}
	if strings.EqualFold(trimmed, "none") {
		*target = []string{}
		return nil
	}
	parts := strings.Split(trimmed, ",")
	var result []string
	seen := map[string]bool{}
	for _, p := range parts {
		name := strings.ToLower(strings.TrimSpace(p))
		if name == "" {
			continue
		}
		if name != "claude" && name != "gemini" {
			return fmt.Errorf("%q: it must be one of [claude, gemini, all, none]", name)
		}
		if !seen[name] {
			seen[name] = true
			result = append(result, name)
		}
	}
	*target = result
	return nil
}

func postEditEntries(stacks []string) []settings.Entry {
	var entries []settings.Entry
	hasStack := func(name string) bool {
		return has(stacks, name)
	}

	if hasStack("python") {
		if hasStack("uv") {
			entries = append(entries,
				settings.Entry{Event: "PostToolUse", Matcher: "Write|Edit|NotebookEdit",
					Command: "ruff check --output-format=concise .", Timeout: 15},
				settings.Entry{Event: "PostToolUse", Matcher: "Write|Edit|NotebookEdit",
					Command: "dmypy run -- --no-error-summary --no-pretty", Timeout: 30},
			)
		} else {
			entries = append(entries,
				settings.Entry{Event: "PostToolUse", Matcher: "Write|Edit|NotebookEdit",
					Command: "ruff check --output-format=concise .", Timeout: 15},
				settings.Entry{Event: "PostToolUse", Matcher: "Write|Edit|NotebookEdit",
					Command: "mypy --no-error-summary --no-pretty", Timeout: 30},
			)
		}
	}
	if hasStack("gdscript") {
		entries = append(entries, settings.Entry{
			Event: "PostToolUse", Matcher: "Write|Edit|NotebookEdit",
			Command: "gdlint .", Timeout: 15,
		})
	}
	if hasStack("csharp") {
		entries = append(entries,
			settings.Entry{Event: "PostToolUse", Matcher: "Write|Edit|NotebookEdit",
				Command: "dotnet format --verify-no-changes", Timeout: 30},
			settings.Entry{Event: "PostToolUse", Matcher: "Write|Edit|NotebookEdit",
				Command: "dotnet build --no-restore", Timeout: 45},
		)
	}
	if hasStack("typescript") {
		entries = append(entries,
			settings.Entry{Event: "PostToolUse", Matcher: "Write|Edit|NotebookEdit",
				Command: "npx eslint .", Timeout: 20},
			settings.Entry{Event: "PostToolUse", Matcher: "Write|Edit|NotebookEdit",
				Command: "npx tsc --noEmit", Timeout: 30},
		)
	}
	if hasStack("rust") {
		entries = append(entries,
			settings.Entry{Event: "PostToolUse", Matcher: "Write|Edit|NotebookEdit",
				Command: "cargo clippy -- -D warnings", Timeout: 30},
			settings.Entry{Event: "PostToolUse", Matcher: "Write|Edit|NotebookEdit",
				Command: "cargo fmt --check", Timeout: 15},
		)
	}
	if hasStack("go") {
		entries = append(entries, settings.Entry{
			Event: "PostToolUse", Matcher: "Write|Edit|NotebookEdit",
			Command: "go vet ./...", Timeout: 20,
		})
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

// landed says what a failed run left behind.
//
// internal/write is honest about not being a transaction, and the spec asks
// for all-or-nothing; between the two the report is what can still be made
// true. An exit 1 whose documented meaning is "own error, nothing written"
// over three files on disk is the same lie C1 was, one step further in, and
// the names come in write.Commit's own order so a person can read this list
// against the directory.
func landed(cause string, written []string) string {
	if len(written) == 0 {
		return cause
	}
	var out strings.Builder
	out.WriteString(cause)
	out.WriteString("\nthis run had already written, and left standing:\n")
	for _, name := range written {
		fmt.Fprintf(&out, "  %s\n", name)
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

// discardClone takes back what a failed clone left standing.
//
// vendoring.Clone holds nothing but a Runner, so it can neither see nor remove
// a half-written clone; its doc comment hands that to the caller, and this is
// the caller. What makes the removal safe is not git's refusal of an occupied
// destination -- that refusal is precisely the common failure, and until
// 2026-08-28 this took the previous run's clone down with it under an exit
// code that says "nothing written". It is safe because vendorPresent ran
// first: the clone is only ever started into a name that did not exist, so
// everything under it was put there by this run.
//
// A removal that fails is reported beside the clone's own error rather than
// instead of it: the reason the run stopped is the first one. That branch is
// uncovered -- making os.RemoveAll fail portably needs a locked handle on
// Windows and a permission on Unix, and a test that only passes on one of them
// says less than the code it guards. It is handled rather than ignored,
// because a directory left standing under a message that says nothing was
// written is exactly the lie this function exists to prevent.
func discardClone(root string, cause error) string {
	full := filepath.Join(root, filepath.FromSlash(vendoring.VendorDir))
	if err := os.RemoveAll(full); err != nil {
		return fmt.Sprintf("%v\nand %s could not be cleaned up: %v",
			cause, vendoring.VendorDir, err)
	}
	return cause.Error()
}

// vendorPresent answers two different questions about the same name, because
// two different decisions need two different answers.
//
// occupied is "may this run clone here?" and is true of anything at all -- a
// file, a directory, a link pointing nowhere. That is the C1 rule: git refuses
// an occupied destination, and whatever stands there is not ours to clear.
//
// usable is "can a hook run through this?" and wants a directory. A file under
// that name is not a vendored runtime, and reading it as one silenced the very
// note that would have told somebody why their hooks fail.
//
// Lstat rather than Stat, for internal/write's reason: a symlink pointing
// nowhere is still somebody's property, and following it would report a free
// name over a link that has been there all along.
func vendorPresent(root string) (occupied, usable bool, err error) {
	full := filepath.Join(root, filepath.FromSlash(vendoring.VendorDir))
	switch info, err := os.Lstat(full); {
	case err == nil:
		return true, info.IsDir(), nil
	case os.IsNotExist(err):
		return false, false, nil
	default:
		return false, false, fmt.Errorf("looking at %s: %w", vendoring.VendorDir, err)
	}
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
