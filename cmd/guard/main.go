// Command ultraloom-guard is the fast policy hook for Claude Code / agents.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"

	"github.com/xidus90/ultra-loom/internal/hostio"
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

	// `hook` carries a second word, unlike every subcommand above. A mistyped
	// event is refused here rather than falling through to the write barrier
	// below: that barrier reads stdin and decides about a file, and answering
	// a hook call that way is a verdict about the wrong question.
	//
	// The event is checked before the flags are parsed and before the root is
	// resolved, so an unknown one is refused for what it is and not for
	// whichever directory the caller happened to stand in.
	if len(args) > 0 && args[0] == "hook" {
		if len(args) < 2 {
			fmt.Fprintln(stderr, "usage: ulguard hook <event> --host <host> [--root <dir>]")
			return ExitInternal
		}
		event := args[1]
		// One event so far, so one comparison. It becomes a set when the stop
		// gate and the subagent pair arrive at their own stages.
		if event != "session-start" {
			fmt.Fprintf(stderr, "ultraloom-guard hook: unknown event %q\n", event)
			return ExitInternal
		}
		flags := flag.NewFlagSet("ultraloom-guard hook "+event, flag.ContinueOnError)
		flags.SetOutput(stderr)
		root := flags.String("root", "", "path to the project root")
		// No default. internal/hostio refuses an unknown host rather than
		// guessing, because answering a hook in the wrong shape is worse than
		// refusing to answer, and a default here would have undone that for the
		// one case it was built for: a hooks.json entry that omits the flag would
		// have been handed a Claude envelope without a word. ulinit writes the
		// flag into every entry it generates, so nothing that this project
		// installs relies on a default.
		host := flags.String("host", "", "the harness calling: claude, antigravity or codex")
		if err := flags.Parse(args[2:]); err != nil {
			return ExitInternal
		}
		// Asked before the root is resolved, for the reason the event check
		// above gives: a call with no host is refused for that, and not for
		// whichever directory the caller happened to stand in.
		if *host == "" {
			fmt.Fprintf(stderr, "ultraloom-guard hook %s: --host is required: expected claude, antigravity or codex\n", event)
			return ExitInternal
		}
		// An empty --root is the Antigravity case: a hook there runs with its
		// working directory set to the one holding hooks.json, not the project
		// root, so the root is found by walking up. Measured 2026-09-10; see
		// docs/.superpowers/specs/2026-09-10-antigravity-hook-messung.md.
		// Whether that host sets CLAUDE_PROJECT_DIR is unmeasured and this
		// does not rely on it either way.
		resolved := *root
		if resolved == "" {
			found, err := hostio.FindRoot(".")
			if err != nil {
				fmt.Fprintf(stderr, "ultraloom-guard hook %s: %v\n", event, err)
				return ExitInternal
			}
			resolved = found
		}
		return runHookSessionStart(stdin, os.Stdout, stderr, resolved, *host)
	}

	flags := flag.NewFlagSet("ultraloom-guard", flag.ContinueOnError)
	flags.SetOutput(stderr)
	root := flags.String("root", ".", "path to the project root")
	if err := flags.Parse(args); err != nil {
		return ExitInternal
	}
	return runGuard(stdin, stderr, *root)
}
