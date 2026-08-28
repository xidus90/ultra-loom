package detect

import (
	"errors"
	"strings"
	"testing"
	"testing/fstest"
)

func TestHooksPathReportsWhatGitHasSet(t *testing.T) {
	var asked []string
	run := func(dir string, argv ...string) (string, error) {
		asked = append(asked, dir+": "+strings.Join(argv, " "))
		return ".githooks\n", nil
	}
	got, err := HooksPath(run, "/project")
	if err != nil {
		t.Fatalf("err = %v, want nil", err)
	}
	if got != ".githooks" {
		t.Fatalf("hooks path = %q, want %q", got, ".githooks")
	}
	want := "/project: git config --get core.hooksPath"
	if len(asked) != 1 || asked[0] != want {
		t.Fatalf("asked = %v, want [%q]", asked, want)
	}
}

// The common case: nothing is set, and that is an answer rather than a fault.
func TestHooksPathIsEmptyWhenUnset(t *testing.T) {
	got, err := HooksPath(func(string, ...string) (string, error) { return "", nil }, ".")
	if err != nil || got != "" {
		t.Fatalf("hooks path = %q, err = %v, want empty and nil", got, err)
	}
}

func TestHooksPathPassesGitsFailureOn(t *testing.T) {
	broken := errors.New("git not found")
	got, err := HooksPath(func(string, ...string) (string, error) { return "", broken }, ".")
	if !errors.Is(err, broken) {
		t.Fatalf("err = %v, want %v", err, broken)
	}
	if got != "" {
		t.Fatalf("hooks path = %q, want empty", got)
	}
}

func TestNeighbourWikiFindsTheSiblingRepository(t *testing.T) {
	parent := fstest.MapFS{
		"iam_backend/go.mod":         {Data: []byte("module x\n")},
		"iam_backend_wiki/.git/HEAD": {Data: []byte("ref: refs/heads/master\n")},
		"iam_backend_wiki/index.md":  {Data: []byte("# wiki\n")},
	}
	mode, wikiPath := NeighbourWiki(parent, "iam_backend")
	if mode != "neighbour_repo" || wikiPath != "iam_backend_wiki/" {
		t.Fatalf("got %q %q, want \"neighbour_repo\" \"iam_backend_wiki/\"", mode, wikiPath)
	}
}

// A folder of notes is not a repository, and the project must not find itself.
func TestNeighbourWikiDeclinesWhatIsNotARepository(t *testing.T) {
	cases := map[string]fstest.MapFS{
		"no .git":                 {"notes_wiki/index.md": {Data: []byte("# notes\n")}},
		"wrong name":              {"docs/.git/HEAD": {Data: []byte("ref\n")}},
		"a file, not a directory": {"stray_wiki": {Data: []byte("not a directory\n")}},
	}
	for name, parent := range cases {
		t.Run(name, func(t *testing.T) {
			if mode, wikiPath := NeighbourWiki(parent, "project"); mode != "" || wikiPath != "" {
				t.Fatalf("got %q %q, want empty", mode, wikiPath)
			}
		})
	}
}

func TestNeighbourWikiDoesNotFindTheProjectItself(t *testing.T) {
	parent := fstest.MapFS{"space_wiki/.git/HEAD": {Data: []byte("ref\n")}}
	if mode, _ := NeighbourWiki(parent, "space_wiki"); mode != "" {
		t.Fatalf("mode = %q, want empty", mode)
	}
}

func TestNeighbourWikiSaysNothingAboutAnUnreadableParent(t *testing.T) {
	if mode, wikiPath := NeighbourWiki(closedFS{}, "project"); mode != "" || wikiPath != "" {
		t.Fatalf("got %q %q, want empty", mode, wikiPath)
	}
}
