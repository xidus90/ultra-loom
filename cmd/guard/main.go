// Command ultraloom-guard is the fast policy hook for Claude Code / agents.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
)

func main() {
	os.Exit(cli(os.Args[1:], os.Stdin, os.Stderr))
}

func cli(args []string, stdin io.Reader, stderr io.Writer) int {
	if len(args) > 0 && (args[0] == "status" || args[0] == "explain" || args[0] == "doctor") {
		flags := flag.NewFlagSet("ultraloom-guard status", flag.ContinueOnError)
		flags.SetOutput(stderr)
		root := flags.String("root", ".", "path to the project root")
		if err := flags.Parse(args[1:]); err != nil {
			return ExitInternal
		}
		return runStatus(os.Stdout, stderr, *root)
	}

	if len(args) > 0 && args[0] == "post-edit" {
		flags := flag.NewFlagSet("ultraloom-guard post-edit", flag.ContinueOnError)
		flags.SetOutput(stderr)
		root := flags.String("root", ".", "path to the project root")
		if err := flags.Parse(args[1:]); err != nil {
			return ExitInternal
		}
		return runPostEdit(stdin, stderr, *root)
	}

	if len(args) > 0 && args[0] == "worktree-link" {
		flags := flag.NewFlagSet("ultraloom-guard worktree-link", flag.ContinueOnError)
		flags.SetOutput(stderr)
		root := flags.String("root", ".", "path to the project root")
		if err := flags.Parse(args[1:]); err != nil {
			return ExitInternal
		}
		return runWorktreeLink(os.Stdout, stderr, *root)
	}

	if len(args) > 0 && args[0] == "worktree-unlink" {
		flags := flag.NewFlagSet("ultraloom-guard worktree-unlink", flag.ContinueOnError)
		flags.SetOutput(stderr)
		root := flags.String("root", ".", "path to the project root")
		if err := flags.Parse(args[1:]); err != nil {
			return ExitInternal
		}
		return runWorktreeUnlink(os.Stdout, stderr, stdin, *root)
	}

	// The worktree comes as an argument and not as `--root`: this one is run by
	// hand, and the caller is not standing in the directory that is about to
	// disappear. The arity is checked because that argument is the whole
	// instruction -- a mistyped call must not fall through to the guard below.
	// The empty string is turned away here as well: it is a path nothing can
	// stat, so every identity check downstream answers "no" about it and it
	// would reach the wrong refusal with no path in the message.
	if len(args) > 0 && args[0] == "worktree-remove" {
		if len(args) != 2 || args[1] == "" {
			fmt.Fprintln(stderr, "usage: ulguard worktree-remove <worktree path>")
			return ExitInternal
		}
		return runWorktreeRemove(os.Stdout, stderr, args[1])
	}

	flags := flag.NewFlagSet("ultraloom-guard", flag.ContinueOnError)
	flags.SetOutput(stderr)
	root := flags.String("root", ".", "path to the project root")
	if err := flags.Parse(args); err != nil {
		return ExitInternal
	}
	return runGuard(stdin, stderr, *root)
}
