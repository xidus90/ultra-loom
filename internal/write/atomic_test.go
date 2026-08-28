package write

import (
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

func TestAnExistingFileIsSkippedNotOverwritten(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(root, "keep.txt")
	if err := os.WriteFile(target, []byte("mine"), 0o644); err != nil {
		t.Fatal(err)
	}
	plan, err := Prepare(root, map[string]string{"keep.txt": "theirs"})
	if err != nil {
		t.Fatalf("Prepare: %v", err)
	}
	if len(plan.Create) != 0 || len(plan.Skip) != 1 {
		t.Fatalf("plan = %+v, want one skip and no create", plan)
	}
	if _, err := Commit(root, plan); err != nil {
		t.Fatalf("Commit: %v", err)
	}
	body, _ := os.ReadFile(target)
	if string(body) != "mine" {
		t.Fatalf("file was overwritten: %q", body)
	}
}

func TestDirectoriesAreCreatedForNewFiles(t *testing.T) {
	root := t.TempDir()
	plan, err := Prepare(root, map[string]string{".ultraloom/policy.toml": "x"})
	if err != nil {
		t.Fatalf("Prepare: %v", err)
	}
	if _, err := Commit(root, plan); err != nil {
		t.Fatalf("Commit: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, ".ultraloom", "policy.toml")); err != nil {
		t.Fatalf("file missing: %v", err)
	}
}

func TestSkipIsSortedRegardlessOfMapOrder(t *testing.T) {
	root := t.TempDir()
	files := map[string]string{}
	for _, name := range []string{"e.txt", "b.txt", "d.txt", "a.txt", "c.txt", "f.txt"} {
		if err := os.WriteFile(filepath.Join(root, name), []byte("mine"), 0o644); err != nil {
			t.Fatal(err)
		}
		files[name] = "theirs"
	}
	plan, err := Prepare(root, files)
	if err != nil {
		t.Fatalf("Prepare: %v", err)
	}
	want := []string{"a.txt", "b.txt", "c.txt", "d.txt", "e.txt", "f.txt"}
	if !slices.Equal(plan.Skip, want) {
		t.Fatalf("Skip = %v, want %v", plan.Skip, want)
	}
}

func TestHostileNamesAreRefused(t *testing.T) {
	root := t.TempDir()
	for _, name := range []string{
		"",
		".",
		"..",
		"../escape.txt",
		"a/../../escape.txt",
		"/etc/passwd",
		"C:/Windows/system32/x",
		`..\escape.txt`,
		"a//b",
		"a/",
	} {
		if _, err := Prepare(root, map[string]string{name: "x"}); err == nil {
			t.Errorf("Prepare accepted %q", name)
		}
	}
}

func TestAFileAppearingAfterPrepareIsNotOverwritten(t *testing.T) {
	root := t.TempDir()
	plan, err := Prepare(root, map[string]string{"late.txt": "theirs"})
	if err != nil {
		t.Fatalf("Prepare: %v", err)
	}
	target := filepath.Join(root, "late.txt")
	if err := os.WriteFile(target, []byte("mine"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := Commit(root, plan); err == nil {
		t.Fatal("Commit overwrote a file that appeared after Prepare")
	}
	body, _ := os.ReadFile(target)
	if string(body) != "mine" {
		t.Fatalf("file was overwritten: %q", body)
	}
}

func TestAnUnreadableNameIsReported(t *testing.T) {
	// A NUL byte in the root never reaches the OS: Go's own string conversion
	// rejects it, on every platform, with something that is not "not found".
	if _, err := Prepare("bad\x00root", map[string]string{"a.txt": "x"}); err == nil {
		t.Fatal("Prepare accepted a root it cannot stat")
	}
}

func TestADirectoryThatCannotBeCreatedIsReported(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "a"), []byte("file"), 0o644); err != nil {
		t.Fatal(err)
	}
	plan := Plan{Create: map[string]string{"a/b.txt": "x"}}
	if _, err := Commit(root, plan); err == nil {
		t.Fatal("Commit created a directory where a file stands")
	}
}

func TestCommitRefusesAHostileNameInAHandBuiltPlan(t *testing.T) {
	root := filepath.Join(t.TempDir(), "project")
	if err := os.Mkdir(root, 0o755); err != nil {
		t.Fatal(err)
	}
	plan := Plan{Create: map[string]string{"../escape.txt": "x"}}
	if _, err := Commit(root, plan); err == nil {
		t.Fatal("Commit accepted a name that leaves the project")
	}
	if _, err := os.Stat(filepath.Join(root, "..", "escape.txt")); !os.IsNotExist(err) {
		t.Fatalf("Commit wrote outside root: %v", err)
	}
}

func TestTheRaceIsExplainedNotJustReported(t *testing.T) {
	root := t.TempDir()
	plan, err := Prepare(root, map[string]string{"late.txt": "theirs"})
	if err != nil {
		t.Fatalf("Prepare: %v", err)
	}
	if err := os.WriteFile(filepath.Join(root, "late.txt"), []byte("mine"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err = Commit(root, plan)
	if err == nil {
		t.Fatal("Commit did not report the race")
	}
	if !strings.Contains(err.Error(), "the plan had it as new, but it exists") {
		t.Fatalf("error does not explain itself: %v", err)
	}
}

func TestNamesGivesCallersTheCommitOrder(t *testing.T) {
	plan := Plan{Create: map[string]string{"e": "", "b": "", "d": "", "a": "", "c": "", "f": ""}}
	want := []string{"a", "b", "c", "d", "e", "f"}
	if !slices.Equal(plan.Names(), want) {
		t.Fatalf("Names() = %v, want %v", plan.Names(), want)
	}
}

func TestAFailureThatIsNotARaceReadsAsAFailure(t *testing.T) {
	// The distinction is what the package owes its callers, so it is a named
	// function and gets asked on its own rather than through a staged disk.
	err := commitFailure("a.txt", errors.New("disk on fire"))
	if !strings.Contains(err.Error(), "writing a.txt") || strings.Contains(err.Error(), "the plan had it as new") {
		t.Fatalf("wrong wording: %v", err)
	}
}

func TestADanglingSymlinkIsSkippedNotWritten(t *testing.T) {
	root := t.TempDir()
	link := filepath.Join(root, "dangling.txt")
	if err := os.Symlink(filepath.Join(root, "nowhere.txt"), link); err != nil {
		// Creating a link is a privilege on Windows, not a given.
		t.Skipf("cannot create a symlink here: %v", err)
	}
	plan, err := Prepare(root, map[string]string{"dangling.txt": "theirs"})
	if err != nil {
		t.Fatalf("Prepare: %v", err)
	}
	if len(plan.Create) != 0 || !slices.Equal(plan.Skip, []string{"dangling.txt"}) {
		t.Fatalf("plan = %+v, want the link skipped", plan)
	}
	if _, err := Commit(root, plan); err != nil {
		t.Fatalf("Commit: %v", err)
	}
	if _, err := os.Lstat(link); err != nil {
		t.Fatalf("the link is gone: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "nowhere.txt")); !os.IsNotExist(err) {
		t.Fatalf("Commit wrote through the link: %v", err)
	}
}

// A Commit that stops halfway has still written: the names of what landed are
// the caller's only way to report the truth about it.
func TestCommitNamesWhatItWroteBeforeItFailed(t *testing.T) {
	root := t.TempDir()
	plan, err := Prepare(root, map[string]string{"a.txt": "1", "b.txt": "2", "c.txt": "3"})
	if err != nil {
		t.Fatal(err)
	}
	// Planned as new, and there by the time Commit arrives -- the race the
	// exclusive create is for, arranged on purpose in the middle of the order.
	if err := os.WriteFile(filepath.Join(root, "b.txt"), []byte("theirs"), 0o644); err != nil {
		t.Fatal(err)
	}
	written, err := Commit(root, plan)
	if err == nil {
		t.Fatal("Commit overwrote a file that appeared after Prepare")
	}
	if len(written) != 1 || written[0] != "a.txt" {
		t.Fatalf("written = %v, want [a.txt]", written)
	}
}

// Nothing written is the other half, and the one a caller may report as
// "nothing happened".
func TestCommitNamesNothingWhenTheFirstFileFails(t *testing.T) {
	root := t.TempDir()
	written, err := Commit(root, Plan{Create: map[string]string{"../escape.txt": "x"}})
	if err == nil {
		t.Fatal("Commit accepted a name that leaves the project")
	}
	if len(written) != 0 {
		t.Fatalf("written = %v, want none", written)
	}
}
