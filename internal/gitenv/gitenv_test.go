package gitenv

import (
	"os"
	"slices"
	"testing"
)

func TestCleanDropsGitsRepositoryPointers(t *testing.T) {
	parent := []string{
		"PATH=/usr/bin",
		"GIT_DIR=/repo/.git/worktrees/feature",
		"GIT_WORK_TREE=/repo",
		"GIT_COMMON_DIR=/repo/.git",
		"GIT_INDEX_FILE=/repo/.git/index",
		"GIT_PREFIX=sub/dir/",
		"GIT_OBJECT_DIRECTORY=/repo/.git/objects",
		"GIT_ALTERNATE_OBJECT_DIRECTORIES=/other/.git/objects",
	}
	if got := Clean(parent); !slices.Equal(got, []string{"PATH=/usr/bin"}) {
		t.Fatalf("Clean = %q, want only PATH", got)
	}
}

// Only what redirects git at a repository goes; the rest is the user's.
func TestCleanKeepsGitsOtherVariables(t *testing.T) {
	parent := []string{"GIT_AUTHOR_NAME=Someone", "GIT_EDITOR=vi", "GIT_TERMINAL_PROMPT=0"}
	if got := Clean(parent); !slices.Equal(got, parent) {
		t.Fatalf("Clean = %q, want the input unchanged", got)
	}
}

// An entry without a separator is not a name we can match, so it stays.
func TestCleanPassesThroughAnEntryWithoutAValue(t *testing.T) {
	parent := []string{"GIT_DIR", "PATH=/usr/bin"}
	if got := Clean(parent); !slices.Equal(got, parent) {
		t.Fatalf("Clean = %q, want the input unchanged", got)
	}
}

func TestEnvironReadsThisProcess(t *testing.T) {
	t.Setenv("GIT_DIR", "/repo/.git")
	t.Setenv("ULTRALOOM_GITENV_PROBE", "1")

	environ := Environ()
	if slices.Contains(environ, "GIT_DIR=/repo/.git") {
		t.Fatal("Environ kept GIT_DIR")
	}
	if !slices.Contains(environ, "ULTRALOOM_GITENV_PROBE=1") {
		t.Fatal("Environ dropped a variable that is not git's")
	}
	if len(environ) >= len(os.Environ()) {
		t.Fatalf("Environ = %d entries, os.Environ = %d; want fewer", len(environ), len(os.Environ()))
	}
}
