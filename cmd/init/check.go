package main

import (
	"bytes"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"

	"github.com/xidus90/ultra-loom/internal/commit"
	"github.com/xidus90/ultra-loom/internal/verify"
)

// The flags the types lane hands mypy. They stood in .ultraloom/config.toml
// until the lane moved here; a report read by a repairer that pays per token
// wants findings and no ceremony.
var mypyArgs = []string{"--no-error-summary", "--no-pretty"}

// runDmypy is the subprocess `check types` starts. A variable so a test can put
// a fixed answer in its place -- nothing but a test assigns it.
var runDmypy verify.Runner = execRun

// execRun starts one command and reads both its streams to the end.
//
// A command that could not be started at all is not a verdict about the code
// and must never read as one, so it comes back non-zero with the reason on
// stderr rather than as the zero value of Run.
func execRun(argv ...string) verify.Run {
	command := exec.Command(argv[0], argv[1:]...)
	var out, errOut bytes.Buffer
	command.Stdout = &out
	command.Stderr = &errOut
	err := command.Run()
	done := verify.Run{Stdout: out.String(), Stderr: errOut.String()}
	var exit *exec.ExitError
	switch {
	case errors.As(err, &exit):
		done.ExitCode = exit.ExitCode()
	case err != nil:
		done.ExitCode = 1
		done.Stderr += fmt.Sprintf("%s could not be run: %v\n", strings.Join(argv, " "), err)
	}
	return done
}

func runCheck(args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		fmt.Fprintln(stderr, "usage: ulinit check <commit-msg|gofmt|coverage|types> [args...]")
		return 1
	}

	subcommand := args[0]
	switch subcommand {
	case "commit-msg":
		if len(args) < 2 {
			fmt.Fprintln(stderr, "usage: ulinit check commit-msg <msg-file>")
			return 1
		}
		msgPath := args[1]
		content, err := os.ReadFile(msgPath)
		if err != nil {
			fmt.Fprintf(stderr, "cannot read commit message file %s: %v\n", msgPath, err)
			return 1
		}
		if err := commit.ValidateCommitMessage(string(content)); err != nil {
			fmt.Fprintf(stderr, "commit message rejected: %v\n", err)
			return 1
		}
		return 0

	case "gofmt":
		paths := args[1:]
		if len(paths) == 0 {
			paths = []string{"."}
		}
		unformatted, err := verify.CheckGoFormat(paths)
		if err != nil {
			fmt.Fprintf(stderr, "gofmt check failed: %v\n", err)
			return 1
		}
		if len(unformatted) > 0 {
			fmt.Fprintf(stderr, "not gofmt-clean:\n%s\n", strings.Join(unformatted, "\n"))
			return 1
		}
		return 0

	case "coverage":
		flags := flag.NewFlagSet("check coverage", flag.ContinueOnError)
		flags.SetOutput(stderr)
		goFloor := flags.Float64("go-floor", 98.0, "required minimum statement coverage percentage for Go")
		summary := flags.String("summary", "", "summary output string from go tool cover -func")
		if err := flags.Parse(args[1:]); err != nil {
			return 1
		}

		if *summary != "" {
			pct, err := verify.ParseGoCoverage(*summary)
			if err != nil {
				fmt.Fprintf(stderr, "coverage parsing error: %v\n", err)
				return 1
			}
			if err := verify.CheckCoverageFloor(pct, *goFloor); err != nil {
				fmt.Fprintf(stderr, "coverage failure: %v\n", err)
				return 1
			}
			fmt.Fprintf(stdout, "go coverage %.1f%%\n", pct)
		}
		return 0

	case "types":
		flags := flag.NewFlagSet("check types", flag.ContinueOnError)
		flags.SetOutput(stderr)
		// Named rather than left to dmypy's default, so the file this may
		// remove is provably the file dmypy reads.
		statusFile := flags.String("status-file", ".dmypy.json", "dmypy's status file, the one a stale daemon leaves behind")
		if err := flags.Parse(args[1:]); err != nil {
			return 1
		}
		done, healed := verify.CheckTypes(runDmypy, os.Remove, *statusFile, mypyArgs)
		if healed != "" {
			fmt.Fprintln(stderr, healed)
		}
		fmt.Fprint(stdout, done.Stdout)
		fmt.Fprint(stderr, done.Stderr)
		if done.ExitCode != 0 {
			return 1
		}
		return 0

	default:
		fmt.Fprintf(stderr, "unknown check subcommand: %s\n", subcommand)
		return 1
	}
}
