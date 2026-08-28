package answers

import (
	"strings"
	"testing"

	"github.com/xidus90/ultra-loom/internal/detect"
)

func TestDefaultsCarryTheDetectedStacks(t *testing.T) {
	got := Defaults(detect.Facts{Stacks: []string{"python", "uv"}})
	if len(got.Project.Stacks) != 2 {
		t.Fatalf("stacks = %v, want the two detected", got.Project.Stacks)
	}
	if got.Gates.CoverageThreshold != 100 {
		t.Fatalf("threshold = %d, want 100", got.Gates.CoverageThreshold)
	}
	if got.Gates.Wiki.Mode != "none" {
		t.Fatalf("wiki mode = %q, want none without a detected bundle", got.Gates.Wiki.Mode)
	}
}

// A detected bundle survives into the answers, path and all: nothing else
// gets a second chance to look at the tree.
func TestDefaultsCarryADetectedWikiBundle(t *testing.T) {
	got := Defaults(detect.Facts{WikiMode: "brain", WikiPath: "wiki/"})
	if got.Gates.Wiki.Mode != "brain" || got.Gates.Wiki.Bundle != "wiki/" {
		t.Fatalf("wiki = %+v, want the detected brain bundle", got.Gates.Wiki)
	}
}

// The Django question stays open. Detection refused to answer it, and a
// default here would answer it without asking.
func TestDefaultsLeaveThePolicyToTheInterview(t *testing.T) {
	got := Defaults(detect.Facts{Stacks: []string{"python", "django"}, Ambiguous: []string{"migrations?"}})
	if got.Policy.ProtectedPaths != nil || got.Policy.ForbiddenCommands != nil {
		t.Fatalf("policy = %+v, want it empty", got.Policy)
	}
}

func TestLoadReadsTheDocumentedShape(t *testing.T) {
	got, err := Load([]byte(`
[project]
stacks          = ["godot"]
commit_language = "en"

[gates]
coverage_threshold = 90

[gates.wiki]
mode = "neighbour_repo"
`))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got.Project.CommitLanguage != "en" {
		t.Fatalf("commit language = %q", got.Project.CommitLanguage)
	}
	if got.Gates.Wiki.Mode != "neighbour_repo" {
		t.Fatalf("wiki mode = %q", got.Gates.Wiki.Mode)
	}
}

func TestLoadRefusesAnUnknownWikiMode(t *testing.T) {
	_, err := Load([]byte("[gates.wiki]\nmode = \"telepathy\"\n"))
	if err == nil {
		t.Fatal("want an error naming the valid modes")
	}
	if !strings.Contains(err.Error(), "neighbour_repo") {
		t.Fatalf("error = %v, want the valid modes named", err)
	}
}

// A hand-edited file that no longer parses names its own file: the message
// is read on a terminal, without the tool's source beside it.
func TestLoadNamesTheFileOnBrokenToml(t *testing.T) {
	_, err := Load([]byte("[project\nstacks = "))
	if err == nil {
		t.Fatal("want a parse error")
	}
	if !strings.HasPrefix(err.Error(), "answers.toml:") {
		t.Fatalf("error = %v, want it prefixed with the file", err)
	}
}

// The second run: what the first one did not write stays zero, and no
// missing section counts as an error.
func TestLoadAcceptsAPartialFile(t *testing.T) {
	got, err := Load([]byte("[project]\nstacks = [\"go\"]\n"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got.Gates.Wiki.Mode != "" || got.Gates.CoverageThreshold != 0 {
		t.Fatalf("gates = %+v, want them unset", got.Gates)
	}
}
