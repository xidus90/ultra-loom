package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/xidus90/ultra-loom/internal/commit"
	"github.com/xidus90/ultra-loom/internal/verify"
)

func runCheck(args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		fmt.Fprintln(stderr, "usage: ulinit check <commit-msg|gofmt|coverage> [args...]")
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

	default:
		fmt.Fprintf(stderr, "unknown check subcommand: %s\n", subcommand)
		return 1
	}
}
