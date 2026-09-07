// Package gitenv keeps git's own environment out of ultraloom's git calls.
//
// Its own package because two programs need the same answer: ulinit reads
// facts about a project, and ulguard will do the same for a worktree. A second
// copy of the list would drift in exactly the entry that matters.
package gitenv

import (
	"os"
	"strings"
)

// Location is what git exports to every hook it runs, and what has to be taken
// back out before a child of ours starts.
//
// Each entry names a repository, an index or an object store, and each of them
// *outranks* the directory a command is given to work in: a git call with its
// working directory set to one repository still answers about the one these
// point at. Measured on 2026-09-07 out of a worktree, where GIT_DIR is
// absolute: `git rev-parse --absurd-flag` in a scratch directory came back a
// success, and reading an unset setting answered `.githooks`. In the main
// checkout the exported value is the relative `.git`, which resolves inside
// the scratch repository by luck and hides the whole effect.
//
// A named list rather than a GIT_ prefix cut: GIT_AUTHOR_NAME, GIT_EDITOR and
// GIT_TERMINAL_PROMPT are the user's settings and none of our business.
var Location = []string{
	"GIT_DIR",
	"GIT_WORK_TREE",
	"GIT_COMMON_DIR",
	"GIT_INDEX_FILE",
	"GIT_PREFIX",
	"GIT_OBJECT_DIRECTORY",
	"GIT_ALTERNATE_OBJECT_DIRECTORIES",
}

// Clean returns parent without the variables in Location.
//
// Takes the parent environment rather than reading it, so the decision is
// testable without a process to inherit from. Entries are "NAME=value" as
// os.Environ spells them; anything without a separator is passed through
// untouched, because a name we cannot read is not a name we can match.
func Clean(parent []string) []string {
	cleaned := make([]string, 0, len(parent))
	for _, entry := range parent {
		name, _, found := strings.Cut(entry, "=")
		if found && contains(Location, name) {
			continue
		}
		cleaned = append(cleaned, entry)
	}
	return cleaned
}

// Environ is Clean over this process's own environment.
func Environ() []string {
	return Clean(os.Environ())
}

func contains(names []string, name string) bool {
	for _, candidate := range names {
		if candidate == name {
			return true
		}
	}
	return false
}
