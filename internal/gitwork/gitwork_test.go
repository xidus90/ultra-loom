package gitwork_test

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"github.com/xidus90/ultra-loom/internal/gitenv"
	"github.com/xidus90/ultra-loom/internal/gitwork"
)

func TestHeadCommitOfARepository(t *testing.T) {
	root := repo(t)
	commit(t, root, "first")

	got, err := gitwork.HeadCommit(root)
	if err != nil {
		t.Fatal(err)
	}

	// The full SHA and not --short: the answer travels in a run marker and is
	// read back rounds later, and an abbreviation is only unique for as long
	// as the repository stays the size it was.
	if len(got) != 40 {
		t.Fatalf("expected a full 40-character sha, got %q", got)
	}
	if got != revParse(t, root) {
		t.Fatalf("HeadCommit = %q, git says %q", got, revParse(t, root))
	}
}

// A detached HEAD is no special case: what a run records is a commit, not a
// branch, and rev-parse answers the same either way.
func TestHeadCommitReadsADetachedHead(t *testing.T) {
	root := repo(t)
	commit(t, root, "first")
	sha, err := gitwork.HeadCommit(root)
	if err != nil {
		t.Fatal(err)
	}
	run(t, root, "checkout", "-q", "--detach", sha)

	got, err := gitwork.HeadCommit(root)
	if err != nil {
		t.Fatal(err)
	}
	if got != sha {
		t.Fatalf("HeadCommit = %q after detaching, want %q", got, sha)
	}
}

func TestHeadCommitOutsideARepository(t *testing.T) {
	if _, err := gitwork.HeadCommit(t.TempDir()); err == nil {
		t.Fatal("a directory that is not a repository has no head")
	}
}

// A root that is not there never reaches an exit code: the spawn itself fails.
// Same answer as a non-zero one -- an error, never an empty string a caller
// could mistake for a commit.
func TestHeadCommitOfADirectoryThatIsNotThere(t *testing.T) {
	if _, err := gitwork.HeadCommit(filepath.Join(t.TempDir(), "nowhere")); err == nil {
		t.Fatal("a directory that is not there has no head")
	}
}

// `git init` leaves HEAD naming a branch that does not exist yet. That is a
// repository without an answer, not an answer.
func TestHeadCommitOfARepositoryWithoutACommit(t *testing.T) {
	if _, err := gitwork.HeadCommit(repo(t)); err == nil {
		t.Fatal("a repository with no commit has no head")
	}
}

// The one refusal that has to come first. An ignored directory *is* inside a
// repository, so rev-parse answers readily with the surrounding repository's
// HEAD -- and measuring against that is worse than not measuring, because
// every file of the parked copy then reads as somebody's change.
func TestHeadCommitRefusesAnIgnoredRoot(t *testing.T) {
	outer := repo(t)
	commit(t, outer, "first")
	parked := filepath.Join(outer, "parked")
	if err := os.MkdirAll(parked, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(outer, ".gitignore"), []byte("parked/\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	_, err := gitwork.HeadCommit(parked)

	if !errors.Is(err, gitwork.ErrIgnoredRoot) {
		t.Fatalf("expected ErrIgnoredRoot, got %v", err)
	}
}

func repo(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	run(t, root, "init")
	run(t, root, "config", "user.email", "t@example.invalid")
	run(t, root, "config", "user.name", "Test")
	return root
}

func commit(t *testing.T, root, message string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(root, "a.txt"), []byte(message), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, root, "add", "a.txt")
	run(t, root, "commit", "-m", message)
}

func revParse(t *testing.T, root string) string {
	t.Helper()
	command := exec.Command("git", "rev-parse", "HEAD")
	command.Dir = root
	command.Env = gitenv.Environ()
	out, err := command.Output()
	if err != nil {
		t.Fatal(err)
	}
	return string(out[:len(out)-1])
}

func run(t *testing.T, root string, args ...string) {
	t.Helper()
	command := exec.Command("git", args...)
	command.Dir = root
	// The same strip the package under test uses, and for a measured reason
	// rather than a hypothetical one: this project's `.githooks/pre-commit`
	// runs `go test ./...` through `ultraloom check all`, and git exports
	// GIT_DIR and GIT_INDEX_FILE to that hook. Both outrank command.Dir, so
	// unstripped these fixture calls would build their repository in, add to
	// and commit into the repository being committed -- see the comment on
	// gitenv.Location, where exactly that was measured on 2026-09-07.
	command.Env = gitenv.Environ()
	if out, err := command.CombinedOutput(); err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
}
