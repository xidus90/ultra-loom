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
	flags := flag.NewFlagSet("ultraloom-guard", flag.ContinueOnError)
	flags.SetOutput(stderr)
	root := flags.String("root", ".", "path to the project root")
	if err := flags.Parse(args); err != nil {
		return ExitInternal
	}
	return runGuard(stdin, stderr, *root)
}
