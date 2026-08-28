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

	"github.com/xidus90/ultra-loom/internal/detect"
)

const version = "0.1.0"

// Uncovered on purpose, and the one place that may be: it is the process
// edge -- os.Exit ends the test binary along with everything else. `run` below
// is the same program without that, and it is covered.
func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

// run is main without the process, so the tests can drive it.
func run(args []string, stdout, stderr io.Writer) int {
	flags := flag.NewFlagSet("ultraloom-init", flag.ContinueOnError)
	flags.SetOutput(stderr)
	showVersion := flags.Bool("version", false, "print the version and exit")
	detectOnly := flags.Bool("detect-only", false, "print the detected facts as JSON and exit")
	root := flags.String("root", ".", "the project directory to read")
	if err := flags.Parse(args); err != nil {
		return 1
	}
	if *showVersion {
		fmt.Fprintln(stdout, version)
		return 0
	}
	if *detectOnly {
		// Detection writes nothing, so this path is the whole of --dry-run
		// for the part of init that has been built.
		return report(*root, git, stdout, stderr)
	}
	fmt.Fprintln(stderr, "not implemented yet")
	return 1
}

// report takes the runner rather than reaching for git itself, so a failing
// git is a test case instead of a thing that has to be arranged on disk.
func report(root string, run detect.Runner, stdout, stderr io.Writer) int {
	facts, err := gather(root, run)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	// Cannot fail for this struct -- strings, bools and string slices only.
	// The branch is unreachable and therefore uncovered, which is the
	// justification for that exclusion: an ignored error would be worse than
	// an untaken branch, and asserting `_` here would be the ignoring.
	rendered, err := json.MarshalIndent(facts, "", "  ")
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
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
