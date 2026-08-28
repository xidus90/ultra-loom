// Command ultraloom-init installs the enforcement of one project.
//
// Everything it decides lives under internal/; this file is only the edge:
// flags in, exit code out. A hook that cannot be tested without a process
// is a hook nobody tests.
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"golang.org/x/term"

	"github.com/xidus90/ultra-loom/internal/detect"
)

const version = "0.1.0"

// Uncovered on purpose, and the one place that may be: it is the process
// edge -- os.Exit ends the test binary along with everything else. `cli` below
// is the same program without that, and it is covered.
func main() {
	os.Exit(cli(os.Args[1:], os.Stdin, os.Stdout, os.Stderr))
}

// cli is main without the process, so the tests can drive it.
func cli(args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	flags := flag.NewFlagSet("ultraloom-init", flag.ContinueOnError)
	flags.SetOutput(stderr)
	showVersion := flags.Bool("version", false, "print the version and exit")
	detectOnly := flags.Bool("detect-only", false, "print the detected facts as JSON and exit")
	root := flags.String("root", ".", "the project directory to read")
	dryRun := flags.Bool("dry-run", false, "decide everything and write nothing")
	yes := flags.Bool("yes", false, "take the default for every open question")
	commitLanguage := flags.String("commit-language", "", "language for commit messages")
	docsLanguage := flags.String("docs-language", "", "language for prose and documentation")
	agents := flags.String("agents", "", "agent platforms: claude, gemini, all or none")
	wikiMode := flags.String("wiki-mode", "", "brain, neighbour_repo or none")
	threshold := flags.Int("coverage-threshold", 0, "coverage threshold in percent")
	protect := flags.String("protect-migrations", "", "yes or no: protect Django migrations")
	forbidPip := flags.String("forbid-pip-install", "", "yes or no: forbid pip install")
	vendorURL := flags.String("vendor-url", "", "clone the runtime from this git url")
	vendorRef := flags.String("vendor-ref", "", "the branch, tag or commit to pin the runtime to")
	if err := flags.Parse(args); err != nil {
		// Asking for help is not a failure. flag.ContinueOnError hands the
		// request back as an error like any other, and an exit code of 1 for
		// `--help` makes every wrapper script think the tool broke.
		if errors.Is(err, flag.ErrHelp) {
			return 0
		}
		return 1
	}
	if *showVersion {
		fmt.Fprintln(stdout, version)
		return 0
	}
	if *detectOnly {
		// Detection writes nothing, so this stays a report of its own beside
		// --dry-run: it answers what init read, not what init would do.
		return report(*root, git, stdout, stderr)
	}
	code, out := run(Options{
		Root: *root, DryRun: *dryRun, Yes: *yes,
		Interactive:       terminal(stdin),
		CommitLanguage:    *commitLanguage,
		DocsLanguage:      *docsLanguage,
		Agents:            *agents,
		WikiMode:          *wikiMode,
		CoverageThreshold: *threshold,
		ProtectMigrations: *protect,
		ForbidPipInstall:  *forbidPip,
		VendorURL:         *vendorURL,
		VendorRef:         *vendorRef,
		In:                stdin,
		Out:               stdout,
		Exec:              git,
		Look:              exec.LookPath,
		Getenv:            os.Getenv,
	})
	fmt.Fprint(stdout, out)
	if !strings.HasSuffix(out, "\n") {
		fmt.Fprintln(stdout)
	}
	return code
}

// terminal answers whether there is someone to ask.
//
// A pipe, a closed stdin and a test buffer all say no, and then an unanswered
// question ends the run instead of waiting for input that never comes -- the
// same lesson as space's invisible uv failure, which read as "nothing to
// report" for a whole session.
//
// The question the operating system answers is the one that has to be asked:
// term.IsTerminal is an ioctl on Unix and GetConsoleMode on Windows, and both
// speak about a console rather than about a file type. The mode bit that
// stood here until 2026-08-28 asked something else -- os.ModeCharDevice is
// true of the null device too, so `init < /dev/null` (and `init < NUL`) read
// as a person, printed four prompts to nobody, took every default and
// installed. That is precisely the agent and CI shape the no-TTY rule is for.
func terminal(stdin io.Reader) bool {
	file, ok := stdin.(*os.File)
	if !ok {
		return false
	}
	return term.IsTerminal(int(file.Fd()))
}

// report takes the runner rather than reaching for git itself, so a failing
// git is a test case instead of a thing that has to be arranged on disk.
func report(root string, run detect.Runner, stdout, stderr io.Writer) int {
	facts, err := gather(root, run)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	rendered, _ := json.MarshalIndent(facts, "", "  ")
	fmt.Fprintln(stdout, string(rendered))
	return 0
}

// gather joins the pure detection to the two facts it cannot reach: git's
// configured hooks path, and a wiki that lives beside the project rather than
// inside it.
func gather(root string, run detect.Runner) (detect.Facts, error) {
	facts := detect.Detect(os.DirFS(root))
	if facts.HasGit {
		hooks, err := detect.HooksPath(run, root)
		if err != nil {
			return facts, err
		}
		facts.HooksPath = hooks
	}
	if facts.WikiMode != "" {
		return facts, nil
	}
	// Abs fails only when the working directory itself cannot be read, which
	// no test can arrange from inside the process; the branch is uncovered
	// for that reason and handled anyway.
	absolute, err := filepath.Abs(root)
	if err != nil {
		return facts, err
	}
	facts.WikiMode, facts.WikiPath = detect.NeighbourWiki(
		os.DirFS(filepath.Dir(absolute)), filepath.Base(absolute))
	return facts, nil
}

// git runs one command and reads its output, and is the only subprocess this
// program starts.
//
// An exit status of 1 with nothing printed is git's way of saying a setting is
// unset; that is an answer, not a failure, and it becomes an empty string.
func git(dir string, argv ...string) (string, error) {
	command := exec.Command(argv[0], argv[1:]...)
	command.Dir = dir
	out, err := command.Output()
	var exit *exec.ExitError
	if errors.As(err, &exit) && exit.ExitCode() == 1 && len(out) == 0 {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("%s: %w", strings.Join(argv, " "), err)
	}
	return string(out), nil
}
