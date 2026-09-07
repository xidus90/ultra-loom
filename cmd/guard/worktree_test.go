package main

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/xidus90/ultra-loom/internal/gitenv"
)

func requireWindows(t *testing.T) {
	t.Helper()
	if runtime.GOOS != "windows" {
		t.Skip("junctions exist only on windows")
	}
}

func git(t *testing.T, dir string, argv ...string) {
	t.Helper()
	command := exec.Command("git", argv...)
	command.Dir = dir
	// The same clean environment the code under test uses. Without it a
	// leaked GIT_DIR builds the fixture inside the repository whose hook is
	// running: on 2026-09-07 fixtures of this shape committed onto this
	// repository's own master that way.
	command.Env = gitenv.Environ()
	if out, err := command.CombinedOutput(); err != nil {
		t.Fatalf("git %v: %v (%s)", argv, err, out)
	}
}

// A main checkout with one committed file and one registered worktree, in the
// `.worktrees` convention worktreetopo scans.
func worktreeFixture(t *testing.T) (main string, worktree string) {
	t.Helper()
	main = t.TempDir()
	git(t, main, "init", "-q", "-b", "main")
	writeFile(t, filepath.Join(main, "a.txt"), "x\n")
	git(t, main, "add", "-A")
	git(t, main, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first")

	worktree = filepath.Join(main, ".worktrees", "one")
	git(t, main, "worktree", "add", "-q", worktree, "-b", "one")
	return main, worktree
}

func writeConfig(t *testing.T, main string, body string) {
	t.Helper()
	mkdirAll(t, filepath.Join(main, ".ultraloom"))
	writeFile(t, filepath.Join(main, ".ultraloom", "config.toml"), body)
}

func mkdirAll(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(path, 0o755); err != nil {
		t.Fatal(err)
	}
}

func writeFile(t *testing.T, path string, body string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

// unregister takes git's entry away and leaves the directory standing -- which
// is what git itself does when a junction is in the way. Measured on
// 2026-09-07: with a junction inside the worktree, `git worktree remove
// --force` exits 0, the registration is gone, and the directory with its
// junction is still there. Without one the same call deletes the directory,
// untracked files included, so the MkdirAll below puts it back.
func unregister(t *testing.T, main string, worktree string) {
	t.Helper()
	git(t, main, "worktree", "remove", "--force", worktree)
	mkdirAll(t, worktree)
}

// mklink makes a junction the way a hand at a prompt does. Its stored target
// carries no trailing separator, unlike the one junction.Create writes, and
// the links this repository's own worktrees already hold came from here.
func mklink(t *testing.T, link string, target string) {
	t.Helper()
	command := exec.Command("cmd", "/c", "mklink", "/J", link, target)
	if out, err := command.CombinedOutput(); err != nil {
		t.Fatalf("mklink /J %s %s: %v (%s)", link, target, err, out)
	}
}

// The case the whole mechanism is for: a fresh worktree without .tools and
// without .ultraloom/vendor, both configured, both put in place.
func TestWorktreeLinkPutsTheConfiguredDirectoriesInPlace(t *testing.T) {
	requireWindows(t)
	main, worktree := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools\", \".ultraloom/vendor\"]\n")
	mkdirAll(t, filepath.Join(main, ".tools", "godot"))
	mkdirAll(t, filepath.Join(main, ".ultraloom", "vendor", "ultraloom"))

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := runWorktreeLink(stdout, stderr, worktree); code != ExitOK {
		t.Fatalf("exit = %d, want 0 (stderr: %s)", code, stderr)
	}

	for _, relative := range []string{".tools/godot", ".ultraloom/vendor/ultraloom"} {
		if _, err := os.Stat(filepath.Join(worktree, filepath.FromSlash(relative))); err != nil {
			t.Fatalf("%s is not reachable from the worktree: %v", relative, err)
		}
	}
	if stdout.Len() != 0 || stderr.Len() != 0 {
		t.Fatalf("stdout = %q, stderr = %q; want silence", stdout, stderr)
	}
}

// A directory the worktree already has of its own is not touched: it may be a
// build output that belongs to this tree.
func TestWorktreeLinkLeavesARealDirectoryAlone(t *testing.T) {
	main, worktree := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools\"]\n")
	mkdirAll(t, filepath.Join(main, ".tools"))
	own := filepath.Join(worktree, ".tools", "mine.txt")
	mkdirAll(t, filepath.Dir(own))
	writeFile(t, own, "mine")

	assertSilentOK(t, worktree)
	if _, err := os.Stat(own); err != nil {
		t.Fatalf("the worktree's own directory was replaced: %v", err)
	}
}

// Running twice must be the same as running once: this fires at every session
// start.
func TestWorktreeLinkIsIdempotent(t *testing.T) {
	requireWindows(t)
	main, worktree := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools\"]\n")
	mkdirAll(t, filepath.Join(main, ".tools", "godot"))

	for round := 1; round <= 2; round++ {
		stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
		if code := runWorktreeLink(stdout, stderr, worktree); code != ExitOK {
			t.Fatalf("round %d: exit = %d (stderr: %s)", round, code, stderr)
		}
	}
	if _, err := os.Stat(filepath.Join(worktree, ".tools", "godot")); err != nil {
		t.Fatalf("the junction did not survive the second round: %v", err)
	}
}

// A configured path that is not in the main checkout either is nothing to
// mirror -- and nothing to complain about.
func TestWorktreeLinkSkipsAPathTheMainCheckoutDoesNotHave(t *testing.T) {
	main, worktree := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools\"]\n")

	assertSilentOK(t, worktree)
	if _, err := os.Lstat(filepath.Join(worktree, ".tools")); !os.IsNotExist(err) {
		t.Fatalf("something was created for a path that does not exist: %v", err)
	}
}

// A configured path the main checkout holds as a file is not a directory to
// mirror either.
func TestWorktreeLinkSkipsAPathThatIsNotADirectory(t *testing.T) {
	main, worktree := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools\"]\n")
	writeFile(t, filepath.Join(main, ".tools"), "not a directory")

	assertSilentOK(t, worktree)
	if _, err := os.Lstat(filepath.Join(worktree, ".tools")); !os.IsNotExist(err) {
		t.Fatalf("something was created for a file: %v", err)
	}
}

// In the main checkout there is nothing to mirror: the directories are there.
func TestWorktreeLinkDoesNothingInTheMainCheckout(t *testing.T) {
	main, _ := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools\"]\n")
	mkdirAll(t, filepath.Join(main, ".tools"))

	assertSilentOK(t, main)
}

// The three no-op cases, exit 0 and silent. This hook fires in every project
// on the machine.
func TestTheNoOpCasesAreSilentAndSuccessful(t *testing.T) {
	t.Run("no repository", func(t *testing.T) {
		assertSilentOK(t, t.TempDir())
	})
	t.Run("no config", func(t *testing.T) {
		_, worktree := worktreeFixture(t)
		assertSilentOK(t, worktree)
	})
	t.Run("config without the section", func(t *testing.T) {
		main, worktree := worktreeFixture(t)
		writeConfig(t, main, "[verify]\nlint = \"ruff check .\"\n")
		assertSilentOK(t, worktree)
	})
}

func assertSilentOK(t *testing.T, root string) {
	t.Helper()
	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := runWorktreeLink(stdout, stderr, root); code != ExitOK {
		t.Fatalf("exit = %d, want 0 (stderr: %s)", code, stderr)
	}
	if stdout.Len() != 0 || stderr.Len() != 0 {
		t.Fatalf("stdout = %q, stderr = %q; want silence", stdout, stderr)
	}
}

// Damage is the one case that is a failure: read as "nothing to mirror", it
// would switch the mechanism off without a word.
func TestBrokenConfigIsAFailure(t *testing.T) {
	main, worktree := worktreeFixture(t)
	writeConfig(t, main, "[worktree\n")

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := runWorktreeLink(stdout, stderr, worktree); code != ExitInternal {
		t.Fatalf("exit = %d, want ExitInternal (stderr: %s)", code, stderr)
	}
	if stderr.Len() == 0 {
		t.Fatal("a failure said nothing")
	}
}

// A configured path that cannot be made is the one thing this reports, because
// the directory behind it may be the pinned runtime every other hook needs.
// Here the worktree holds `.tools` as a file, so there is no room for
// `.tools/sub` -- measured on 2026-09-07: Lstat of the child under a file
// answers IsNotExist, and the MkdirAll of the parent is what fails.
func TestWorktreeLinkReportsAPathItCannotMakeRoomFor(t *testing.T) {
	main, worktree := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools/sub\"]\n")
	mkdirAll(t, filepath.Join(main, ".tools", "sub"))
	writeFile(t, filepath.Join(worktree, ".tools"), "not a directory")

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := runWorktreeLink(stdout, stderr, worktree); code != ExitInternal {
		t.Fatalf("exit = %d, want ExitInternal (stderr: %s)", code, stderr)
	}
	if !strings.Contains(stderr.String(), "worktree-link") {
		t.Fatalf("stderr = %q, want the subcommand's name in it", stderr)
	}
}

// The sweep: a directory git no longer knows, with our junction still in it.
func TestWorktreeLinkSweepsAnOrphanedJunction(t *testing.T) {
	requireWindows(t)
	main, worktree := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools\"]\n")
	mkdirAll(t, filepath.Join(main, ".tools", "godot"))
	if code := runWorktreeLink(&bytes.Buffer{}, &bytes.Buffer{}, worktree); code != ExitOK {
		t.Fatal("the fixture's own link was not created")
	}
	unregister(t, main, worktree)
	// The junction is what stopped git from deleting the directory, so it has
	// to be standing before the sweep is asked about it.
	if _, err := os.Lstat(filepath.Join(worktree, ".tools")); err != nil {
		t.Fatalf("git took the junction with it, so this tests nothing: %v", err)
	}

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := runWorktreeLink(stdout, stderr, main); code != ExitOK {
		t.Fatalf("exit = %d, want 0 (stderr: %s)", code, stderr)
	}
	if _, err := os.Lstat(filepath.Join(worktree, ".tools")); !os.IsNotExist(err) {
		t.Fatalf("the orphaned junction survived: %v", err)
	}
	if _, err := os.Stat(filepath.Join(main, ".tools", "godot")); err != nil {
		t.Fatalf("the sweep reached through the junction: %v", err)
	}
	if stdout.Len() != 0 || stderr.Len() != 0 {
		t.Fatalf("stdout = %q, stderr = %q; want silence", stdout, stderr)
	}
}

// A hand-made junction is swept too, and it is the spelling that matters: its
// stored target has no trailing separator, so a comparison made as text
// against an absolute path would miss exactly the links this repository's own
// worktrees already carry.
func TestTheSweepTakesAHandMadeJunctionAsWell(t *testing.T) {
	requireWindows(t)
	main, worktree := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools\"]\n")
	mkdirAll(t, filepath.Join(main, ".tools", "godot"))
	mklink(t, filepath.Join(worktree, ".tools"), filepath.Join(main, ".tools"))
	unregister(t, main, worktree)

	if code := runWorktreeLink(&bytes.Buffer{}, &bytes.Buffer{}, main); code != ExitOK {
		t.Fatal("the sweep failed")
	}
	if _, err := os.Lstat(filepath.Join(worktree, ".tools")); !os.IsNotExist(err) {
		t.Fatalf("the hand-made junction survived: %v", err)
	}
}

// A real directory in an orphaned worktree is somebody's data, not our link.
//
// Written after `unregister`, not before: measured on 2026-09-07, `git
// worktree remove --force` deletes the whole directory including untracked
// files when no reparse point blocks it, so a file put there first would be
// gone before the sweep ever ran.
func TestTheSweepLeavesARealDirectoryInAnOrphanAlone(t *testing.T) {
	main, worktree := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools\"]\n")
	mkdirAll(t, filepath.Join(main, ".tools"))
	unregister(t, main, worktree)
	keep := filepath.Join(worktree, ".tools", "mine.txt")
	mkdirAll(t, filepath.Dir(keep))
	writeFile(t, keep, "mine")

	if code := runWorktreeLink(&bytes.Buffer{}, &bytes.Buffer{}, main); code != ExitOK {
		t.Fatal("the sweep failed")
	}
	if _, err := os.Stat(keep); err != nil {
		t.Fatalf("the sweep removed a real directory: %v", err)
	}
}

// A junction pointing somewhere else is somebody's own arrangement. Being a
// reparse point at a configured path is not enough to make it ours.
func TestTheSweepLeavesAJunctionPointingElsewhereAlone(t *testing.T) {
	requireWindows(t)
	main, worktree := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools\"]\n")
	mkdirAll(t, filepath.Join(main, ".tools"))
	elsewhere := t.TempDir()
	unregister(t, main, worktree)
	mklink(t, filepath.Join(worktree, ".tools"), elsewhere)

	if code := runWorktreeLink(&bytes.Buffer{}, &bytes.Buffer{}, main); code != ExitOK {
		t.Fatal("the sweep failed")
	}
	if _, err := os.Lstat(filepath.Join(worktree, ".tools")); err != nil {
		t.Fatalf("a junction into another directory was removed: %v", err)
	}
}

// A junction at a path nobody configured is not ours either, wherever it
// points. The configuration is what says which paths this mechanism owns.
func TestTheSweepLeavesAJunctionAtAnUnconfiguredPathAlone(t *testing.T) {
	requireWindows(t)
	main, worktree := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools\"]\n")
	mkdirAll(t, filepath.Join(main, ".tools"))
	mkdirAll(t, filepath.Join(main, "somewhere"))
	unregister(t, main, worktree)
	mklink(t, filepath.Join(worktree, "somewhere"), filepath.Join(main, "somewhere"))

	if code := runWorktreeLink(&bytes.Buffer{}, &bytes.Buffer{}, main); code != ExitOK {
		t.Fatal("the sweep failed")
	}
	if _, err := os.Lstat(filepath.Join(worktree, "somewhere")); err != nil {
		t.Fatalf("a junction at an unconfigured path was removed: %v", err)
	}
}

// The other side of the containment check: a nested configured path whose
// intermediate directories are real is still swept. Without this, a check
// that skipped one component too many would stop cleaning
// `.ultraloom/vendor` and nothing would say so.
func TestTheSweepReachesANestedPathThroughRealDirectories(t *testing.T) {
	requireWindows(t)
	main, _ := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".ultraloom/vendor\"]\n")
	mkdirAll(t, filepath.Join(main, ".ultraloom", "vendor", "ultraloom"))

	orphan := filepath.Join(main, ".worktrees", "gone")
	mkdirAll(t, filepath.Join(orphan, ".ultraloom"))
	link := filepath.Join(orphan, ".ultraloom", "vendor")
	mklink(t, link, filepath.Join(main, ".ultraloom", "vendor"))

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := runWorktreeLink(stdout, stderr, main); code != ExitOK {
		t.Fatalf("exit = %d, want 0 (stderr: %s)", code, stderr)
	}
	if _, err := os.Lstat(link); !os.IsNotExist(err) {
		t.Fatalf("the nested orphaned junction survived: %v", err)
	}
	if _, err := os.Stat(filepath.Join(main, ".ultraloom", "vendor", "ultraloom")); err != nil {
		t.Fatalf("the sweep reached through the junction: %v", err)
	}
	if stdout.Len() != 0 || stderr.Len() != 0 {
		t.Fatalf("stdout = %q, stderr = %q; want silence", stdout, stderr)
	}
}

// A candidate whose path runs through a link is not in the orphan at all, and
// the one thing behind such a path may be the main checkout's own junction.
//
// Windows opens the final component of a path with
// FILE_FLAG_OPEN_REPARSE_POINT and follows every earlier one, so
// `<orphan>/.ultraloom/vendor` with a junction at `<orphan>/.ultraloom` reads
// the reparse point of `<main>/.ultraloom/vendor`. Before the containment
// check that junction satisfied all three conditions and was removed -- the
// pinned runtime every other ultraloom hook needs, gone silently, and `link`
// cannot put it back because IsWorktree says false about the main checkout.
func TestTheSweepDoesNotReachThroughAnIntermediateLink(t *testing.T) {
	requireWindows(t)
	main, _ := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".ultraloom/vendor\"]\n")

	// The main checkout's own mirror path is a junction here as well, which is
	// what makes it look like a candidate once an earlier component leads to
	// it.
	runtimeDir := filepath.Join(main, "runtime")
	mkdirAll(t, runtimeDir)
	mainVendor := filepath.Join(main, ".ultraloom", "vendor")
	mklink(t, mainVendor, runtimeDir)

	orphan := filepath.Join(main, ".worktrees", "gone")
	mkdirAll(t, orphan)
	mklink(t, filepath.Join(orphan, ".ultraloom"), filepath.Join(main, ".ultraloom"))

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := runWorktreeLink(stdout, stderr, main); code != ExitOK {
		t.Fatalf("exit = %d, want 0 (stderr: %s)", code, stderr)
	}
	if _, err := os.Lstat(mainVendor); err != nil {
		t.Fatalf("the main checkout's own junction was removed: %v", err)
	}
	if _, err := os.Stat(runtimeDir); err != nil {
		t.Fatalf("what the main checkout's junction pointed at is gone: %v", err)
	}
	if stdout.Len() != 0 || stderr.Len() != 0 {
		t.Fatalf("stdout = %q, stderr = %q; want silence", stdout, stderr)
	}
}

// A candidate the sweep cannot even look at is a failure and not a skip: the
// sweep must not go quiet about a path it could not decide. `?` is legal in a
// configured path -- filepath.IsLocal accepts it, measured on 2026-09-07 --
// and illegal in a Windows filename, so Lstat answers with something other
// than IsNotExist.
func TestTheSweepReportsAPathItCannotInspect(t *testing.T) {
	requireWindows(t)
	main, _ := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = ['bad?name']\n")
	mkdirAll(t, filepath.Join(main, ".worktrees", "gone"))

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := runWorktreeLink(stdout, stderr, main); code != ExitInternal {
		t.Fatalf("exit = %d, want ExitInternal (stderr: %s)", code, stderr)
	}
	if stderr.Len() == 0 {
		t.Fatal("a failure said nothing")
	}
}

// And a convention directory the sweep cannot read is a failure for the same
// reason.
func TestTheSweepReportsADirectoryItCannotScan(t *testing.T) {
	requireWindows(t)
	main, _ := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools\"]\n")
	mkdirAll(t, filepath.Join(main, ".tools"))

	// RD: reading the entries of the directory the orphan scan walks.
	denyRight(t, filepath.Join(main, ".worktrees"), "RD")

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := runWorktreeLink(stdout, stderr, main); code != ExitInternal {
		t.Fatalf("exit = %d, want ExitInternal (stderr: %s)", code, stderr)
	}
	if stderr.Len() == 0 {
		t.Fatal("a failure said nothing")
	}
}

// The loud case itself: a junction that was needed and did not come about.
// The worktree may not gain a subdirectory, so the path is absent, there is
// room to be made and the junction still cannot be created -- which is what
// the missing directory being the pinned runtime would look like.
func TestWorktreeLinkReportsAJunctionItCouldNotMake(t *testing.T) {
	requireWindows(t)
	main, worktree := worktreeFixture(t)
	writeConfig(t, main, "[worktree]\nmirror = [\".tools\"]\n")
	mkdirAll(t, filepath.Join(main, ".tools"))

	// AD: adding a subdirectory. Measured on 2026-09-07: an Lstat of the
	// child still answers IsNotExist under this deny, so the run gets all the
	// way to the junction before it fails.
	denyRight(t, worktree, "AD")

	stdout, stderr := &bytes.Buffer{}, &bytes.Buffer{}
	if code := runWorktreeLink(stdout, stderr, worktree); code != ExitInternal {
		t.Fatalf("exit = %d, want ExitInternal (stderr: %s)", code, stderr)
	}
	if !strings.Contains(stderr.String(), ".tools") {
		t.Fatalf("stderr = %q, want the configured path named in it", stderr)
	}
}

// denyRight takes one Windows right away from the user running the test and
// gives it back afterwards. icacls and not a mode bit: measured on
// 2026-09-07, `os.Chmod(dir, 0)` on a Windows directory returns nil and the
// next os.ReadDir of it still succeeds, so there is no mode here that takes
// access away.
//
// The right has to come back before the fixture's own cleanup runs, or
// t.TempDir cannot delete the tree it made. t.Cleanup is LIFO and the fixture
// registered its own first, so this one goes first.
func denyRight(t *testing.T, path string, right string) {
	t.Helper()
	if _, err := exec.LookPath("icacls"); err != nil {
		t.Skip("icacls is not on PATH")
	}
	user := os.Getenv("USERNAME")
	icacls(t, path, "/deny", user+":("+right+")")
	t.Cleanup(func() { icacls(t, path, "/remove:d", user) })
}

func icacls(t *testing.T, path string, argv ...string) {
	t.Helper()
	command := exec.Command("icacls", append([]string{path}, argv...)...)
	if out, err := command.CombinedOutput(); err != nil {
		t.Fatalf("icacls %s %v: %v (%s)", path, argv, err, out)
	}
}

// leadsInto has to answer about a stored target, and a stored target comes in
// more than one spelling: the trailing separator depends on who made the
// junction, and the prefix on what wrote it. Measured on 2026-09-07:
// junction.Create stores `\??\C:\dir\`, `mklink /J` stores `\??\C:\dir`, and
// both resolve.
func TestLeadsIntoReadsEverySpellingOfAStoredTarget(t *testing.T) {
	main := t.TempDir()
	inside := filepath.Join(main, "vendor")
	mkdirAll(t, inside)

	for _, stored := range []string{
		`\??\` + inside + `\`,
		`\??\` + inside,
		`\\?\` + inside,
		inside,
		filepath.Join(inside, "gone"),
	} {
		if !leadsInto(stored, main) {
			t.Fatalf("leadsInto(%q, %q) = false, want true", stored, main)
		}
	}

	for _, stored := range []string{t.TempDir(), inside} {
		outside := t.TempDir()
		if leadsInto(stored, outside) {
			t.Fatalf("leadsInto(%q, %q) = true, want false", stored, outside)
		}
	}
	if leadsInto(inside, filepath.Join(main, "not-there")) {
		t.Fatal("a main checkout that is not there was accepted")
	}
}

func TestCliDispatchesWorktreeLink(t *testing.T) {
	var stderr bytes.Buffer
	if code := cli([]string{"worktree-link", "--root", t.TempDir()}, strings.NewReader(""), &stderr); code != ExitOK {
		t.Fatalf("exit = %d, want 0 (stderr: %s)", code, &stderr)
	}
	if stderr.Len() != 0 {
		t.Fatalf("stderr = %q, want silence", &stderr)
	}
	if code := cli([]string{"worktree-link", "--invalid-flag"}, strings.NewReader(""), &stderr); code != ExitInternal {
		t.Fatalf("exit = %d on an invalid flag, want ExitInternal", code)
	}
}
