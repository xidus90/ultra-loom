// Command ultraloom-guard is the fast policy hook for Claude Code / agents.
package main

import (
	"flag"
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

	flags := flag.NewFlagSet("ultraloom-guard", flag.ContinueOnError)
	flags.SetOutput(stderr)
	root := flags.String("root", ".", "path to the project root")
	if err := flags.Parse(args); err != nil {
		return ExitInternal
	}
	return runGuard(stdin, stderr, *root)
}
