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

// The relevance table the spec gives has a second row, and it is the one that
// matters for a brain project: a wiki page that changed has to be reindexed,
// or search answers out of yesterday's text.
func TestTheSeededRelevanceReindexesTheWiki(t *testing.T) {
	got := Defaults(detect.Facts{}).Relevance
	commands, listed := got["wiki/**"]
	if !listed {
		t.Fatalf("wiki/** is not in the seeded relevance: %v", got)
	}
	if len(commands) != 1 || commands[0] != "brain reindex" {
		t.Fatalf("wiki/** maps to %v, want [brain reindex]", commands)
	}
	if _, listed := got["*.md"]; !listed {
		t.Fatalf("the row that was already there is gone: %v", got)
	}
}

func TestLoadReadsTheBrainDecisions(t *testing.T) {
	loaded, err := Load([]byte("[gates.wiki]\nmode    = \"brain\"\nbundle  = \"docs/wiki/\"\n" +
		"scope   = \"project/x\"\nsources = \"docs\"\nprivacy = \"local_only\"\n"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	want := Wiki{Mode: "brain", Bundle: "docs/wiki/", Scope: "project/x", Sources: "docs", Privacy: "local_only"}
	if loaded.Gates.Wiki != want {
		t.Fatalf("wiki = %+v, want %+v", loaded.Gates.Wiki, want)
	}
}

// vault is the fourth kind of wiki: the project's wiki lives in the vault, and
// the area is registered read-only. Stage 1 only has to accept the answer.
func TestLoadAcceptsTheVaultMode(t *testing.T) {
	if _, err := Load([]byte("[gates.wiki]\nmode = \"vault\"\n")); err != nil {
		t.Fatalf("Load refused vault: %v", err)
	}
}

// brain refuses a privacy mode outside its set when it reads the manifest.
// Refused here, the typo is reported where it was made.
func TestLoadRefusesAPrivacyModeBrainWouldRefuse(t *testing.T) {
	_, err := Load([]byte("[gates.wiki]\nmode = \"brain\"\nprivacy = \"public\"\n"))
	if err == nil || !strings.Contains(err.Error(), "privacy") {
		t.Fatalf("err = %v, want a refusal that names privacy", err)
	}
}

func TestBrainDefaultsFollowBrainInitWithADocsFolder(t *testing.T) {
	got := Wiki{Mode: "brain"}.WithBrainDefaults("ultraloom", true)
	want := Wiki{Mode: "brain", Bundle: "docs/wiki/", Scope: "project/ultraloom", Sources: "docs", Privacy: "manual_cloud"}
	if got != want {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

func TestBrainDefaultsFollowBrainInitWithoutADocsFolder(t *testing.T) {
	got := Wiki{Mode: "brain"}.WithBrainDefaults("tool", false)
	want := Wiki{Mode: "brain", Bundle: "wiki/", Scope: "project/tool", Sources: ".", Privacy: "manual_cloud"}
	if got != want {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

func TestBrainDefaultsKeepEveryRecordedAnswer(t *testing.T) {
	recorded := Wiki{Mode: "brain", Bundle: "notes/", Scope: "project/other", Sources: "src", Privacy: "local_only"}
	if got := recorded.WithBrainDefaults("ultraloom", true); got != recorded {
		t.Fatalf("got %+v, want the recorded answers unchanged", got)
	}
}

func TestBrainDefaultsLeaveEveryOtherModeAlone(t *testing.T) {
	for _, mode := range []string{"none", "neighbour_repo", "vault"} {
		w := Wiki{Mode: mode, Bundle: "iam_wiki/"}
		if got := w.WithBrainDefaults("iam_backend", true); got != w {
			t.Fatalf("mode %s: got %+v, want %+v", mode, got, w)
		}
	}
}
