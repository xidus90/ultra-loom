package vendoring

import (
	"errors"
	"strings"
	"testing"

	"github.com/BurntSushi/toml"
)

func TestCloneAsksGitForTheExactRef(t *testing.T) {
	var calls [][]string
	run := func(dir string, argv ...string) (string, error) {
		calls = append(calls, argv)
		if argv[0] == "rev-parse" {
			return "3198f55\n", nil
		}
		return "", nil
	}
	commit, err := Clone(run, "/p", "https://example/ultra-loom.git", "v0.4.1")
	if err != nil {
		t.Fatalf("Clone: %v", err)
	}
	if commit != "3198f55" {
		t.Fatalf("commit = %q", commit)
	}
	if !strings.Contains(strings.Join(calls[0], " "), "v0.4.1") {
		t.Fatalf("the ref was not passed: %v", calls[0])
	}
}

func TestAFailingCloneIsReportedNotSwallowed(t *testing.T) {
	run := func(dir string, argv ...string) (string, error) {
		return "", errors.New("network is unreachable")
	}
	if _, err := Clone(run, "/p", "https://example/x.git", "main"); err == nil {
		t.Fatal("want the error to surface")
	}
}

func TestInstalledTomlRecordsWhatSyncWillNeed(t *testing.T) {
	got := InstalledTOML("v0.4.1", "3198f55", "abc123", []string{".ultraloom/policy.toml"})
	for _, want := range []string{"v0.4.1", "3198f55", "abc123", "policy.toml"} {
		if !strings.Contains(got, want) {
			t.Fatalf("installed.toml lacks %q:\n%s", want, got)
		}
	}
}

// A branch pin is shallow; a commit pin cannot be, and the difference has to
// be visible in what git is asked to do.
func TestACommitShaIsCheckedOutRatherThanPassedToBranch(t *testing.T) {
	const sha = "3198f5591c0a0f0e3c1d9e4b7a2f8c6d5e4b3a21"
	var calls [][]string
	run := func(dir string, argv ...string) (string, error) {
		calls = append(calls, argv)
		return sha + "\n", nil
	}
	commit, err := Clone(run, "/p", "https://example/x.git", sha)
	if err != nil {
		t.Fatalf("Clone: %v", err)
	}
	if commit != sha {
		t.Fatalf("commit = %q", commit)
	}
	first := strings.Join(calls[0], " ")
	if strings.Contains(first, "--branch") || strings.Contains(first, "--depth") {
		t.Fatalf("a sha was passed to a shallow branch clone: %v", calls[0])
	}
	if len(calls) != 3 || calls[1][0] != "checkout" || calls[1][len(calls[1])-1] != sha {
		t.Fatalf("want a detached checkout of the sha, got %v", calls)
	}
}

func TestAFailingCheckoutIsReported(t *testing.T) {
	run := func(dir string, argv ...string) (string, error) {
		if argv[0] == "checkout" {
			return "", errors.New("no such commit")
		}
		return "", nil
	}
	_, err := Clone(run, "/p", "https://example/x.git", strings.Repeat("a", 40))
	if err == nil || !strings.Contains(err.Error(), "no such commit") {
		t.Fatalf("err = %v", err)
	}
}

func TestAFailingRevParseIsReported(t *testing.T) {
	run := func(dir string, argv ...string) (string, error) {
		if argv[0] == "rev-parse" {
			return "", errors.New("not a repository")
		}
		return "", nil
	}
	if _, err := Clone(run, "/p", "https://example/x.git", "main"); err == nil {
		t.Fatal("want the error to surface")
	}
}

// git reads a leading dash as an option wherever it stands, so a ref is not
// merely data by the time it reaches argv.
func TestARefThatWouldReadAsAnOptionIsRefused(t *testing.T) {
	run := func(dir string, argv ...string) (string, error) {
		t.Fatal("git must not be called at all")
		return "", nil
	}
	for _, ref := range []string{"", "--upload-pack=rm -rf /", "-x"} {
		if _, err := Clone(run, "/p", "https://example/x.git", ref); err == nil {
			t.Fatalf("ref %q was accepted", ref)
		}
	}
}

func TestAnEmptyCommitIsRefusedRatherThanRecorded(t *testing.T) {
	run := func(dir string, argv ...string) (string, error) { return "  \n", nil }
	if _, err := Clone(run, "/p", "https://example/x.git", "main"); err == nil {
		t.Fatal("want an empty commit to be refused")
	}
}

// The file is committed and diffed, so the same install must render the same
// bytes whatever order the writer happened to finish its files in.
func TestInstalledTomlIsDeterministic(t *testing.T) {
	unsorted := []string{"z.toml", "a.toml", "z.toml", "m.toml"}
	got := InstalledTOML("v1", "c", "h", unsorted)
	want := InstalledTOML("v1", "c", "h", []string{"a.toml", "m.toml", "z.toml"})
	if got != want {
		t.Fatalf("order leaked into the output:\n%s\n%s", got, want)
	}
	if unsorted[0] != "z.toml" {
		t.Fatalf("the caller's slice was reordered: %v", unsorted)
	}
	if strings.Count(got, "z.toml") != 1 {
		t.Fatalf("a duplicate survived:\n%s", got)
	}
}

func TestInstalledTomlWithNothingCreated(t *testing.T) {
	got := InstalledTOML("v1", "c", "h", nil)
	if !strings.Contains(got, "files = []") {
		t.Fatalf("want an empty list:\n%s", got)
	}
}

// Go's %q is not TOML: `\v`, `\x01` and `\x7f` are escapes TOML 1.0 has no
// reading for, and a single bad one takes the whole file down.
func TestQuotingStaysInsideTomlsEscapes(t *testing.T) {
	cases := map[string]string{
		`C:\p\wiki`:                `"C:\\p\\wiki"`,
		"a\vb":                     `"a\u000Bb"`,
		"a\x01b":                   `"a\u0001b"`,
		"a\x7fb":                   `"a\u007Fb"`,
		"a\tb\nc\rd\be\ff\"g":      `"a\tb\nc\rd\be\ff\"g"`,
		"café":                     `"café"`,
		string([]byte{0x41, 0xff}): "\"A\uFFFD\"",
	}
	for in, want := range cases {
		if got := quote(in); got != want {
			t.Fatalf("quote(%q) = %s, want %s", in, got, want)
		}
	}
}

// git's own abbreviation minimum is four, and a name longer than a full id is
// not one either -- both are branch names, whatever characters they use.
func TestShortAndOverlongHexAreBranchNamesNotCommits(t *testing.T) {
	for _, ref := range []string{"abc", strings.Repeat("a", 41), "deadbeef"} {
		want := ref == "deadbeef"
		if got := isCommitID(ref); got != want {
			t.Fatalf("isCommitID(%q) = %v", ref, got)
		}
	}
}

func TestAFailingFullCloneIsReported(t *testing.T) {
	run := func(dir string, argv ...string) (string, error) {
		return "", errors.New("repository not found")
	}
	_, err := Clone(run, "/p", "https://example/x.git", strings.Repeat("b", 40))
	if err == nil || !strings.Contains(err.Error(), "repository not found") {
		t.Fatalf("err = %v", err)
	}
}

// The point of quoting is a file that parses; a Windows path is where it fails.
func TestTheRenderedFileParsesAsToml(t *testing.T) {
	body := InstalledTOML("v0.4.1", "3198f55", "abc123", []string{"C:\\p\\wiki\\policy.toml", "a\vb"})
	var got struct {
		Vendor  struct{ Ref, Commit string }
		Answers struct {
			SHA256 string `toml:"sha256"`
		}
		Created struct{ Files []string }
	}
	if _, err := toml.Decode(body, &got); err != nil {
		t.Fatalf("the generated file does not parse: %v\n%s", err, body)
	}
	if got.Vendor.Ref != "v0.4.1" || got.Created.Files[0] != "C:\\p\\wiki\\policy.toml" {
		t.Fatalf("values did not survive quoting: %+v", got)
	}
}
