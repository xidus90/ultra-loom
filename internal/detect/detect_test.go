package detect

import (
	"io/fs"
	"strings"
	"testing"
	"testing/fstest"
)

func TestUvManagedPythonIsDetected(t *testing.T) {
	tree := fstest.MapFS{
		"pyproject.toml": {Data: []byte("[project]\nname = \"x\"\n")},
		"uv.lock":        {Data: []byte("")},
	}
	facts := Detect(tree)
	if !has(facts.Stacks, "python") {
		t.Fatalf("stacks = %v, want python", facts.Stacks)
	}
	if !has(facts.Stacks, "uv") {
		t.Fatalf("stacks = %v, want uv", facts.Stacks)
	}
}

func TestGodotWithDotnetKeepsBothStacks(t *testing.T) {
	tree := fstest.MapFS{
		"project.godot": {Data: []byte("config_version=5\n\n[dotnet]\n\nproject/assembly_name=\"space\"\n")},
		"space.csproj":  {Data: []byte("<Project/>")},
	}
	facts := Detect(tree)
	for _, want := range []string{"godot", "gdscript", "csharp"} {
		if !has(facts.Stacks, want) {
			t.Fatalf("stacks = %v, want %s", facts.Stacks, want)
		}
	}
}

func TestAnEmptyTreeDetectsNothingAndSaysSo(t *testing.T) {
	facts := Detect(fstest.MapFS{})
	if len(facts.Stacks) != 0 {
		t.Fatalf("stacks = %v, want none", facts.Stacks)
	}
}

// A Godot project without the C# section is the false alarm this must not
// raise: separating the two is the whole reason `contains` exists.
func TestGodotWithoutDotnetStaysGdscript(t *testing.T) {
	tree := fstest.MapFS{
		"project.godot": {Data: []byte("config_version=5\n")},
	}
	facts := Detect(tree)
	if !has(facts.Stacks, "gdscript") {
		t.Fatalf("stacks = %v, want gdscript", facts.Stacks)
	}
	if has(facts.Stacks, "csharp") {
		t.Fatalf("stacks = %v, want no csharp", facts.Stacks)
	}
}

func TestAWorkspaceMemberIsSeenOneLevelDown(t *testing.T) {
	tree := fstest.MapFS{
		"README.md":               {Data: []byte("workspace\n")},
		"services/api/Cargo.toml": {Data: []byte("[package]\n")},
		"backend/pyproject.toml":  {Data: []byte("[project]\n")},
		"frontend/tsconfig.json":  {Data: []byte("{}")},
		"frontend/package.json":   {Data: []byte("{}")},
		"game/project.godot":      {Data: []byte("config_version=5\n\n[dotnet]\n")},
		"game/game.csproj":        {Data: []byte("<Project/>")},
	}
	facts := Detect(tree)
	for _, want := range []string{"python", "typescript", "godot", "gdscript", "csharp"} {
		if !has(facts.Stacks, want) {
			t.Fatalf("stacks = %v, want %s", facts.Stacks, want)
		}
	}
	// Two levels down is a member's own layout, not a member.
	if has(facts.Stacks, "rust") {
		t.Fatalf("stacks = %v, want no rust from two levels down", facts.Stacks)
	}
}

// Dot directories carry tooling, not workspace members -- `.godot/` alone
// holds an import cache wide enough to make several rows fire on it.
func TestDotDirectoriesAreNotWorkspaceMembers(t *testing.T) {
	tree := fstest.MapFS{
		".cache/Cargo.toml": {Data: []byte("[package]\n")},
	}
	facts := Detect(tree)
	if len(facts.Stacks) != 0 {
		t.Fatalf("stacks = %v, want none", facts.Stacks)
	}
}

// TypeScript is a conjunction in the spec, and each half alone says something
// else: a lone tsconfig.json is a configuration file, a lone package.json is
// the question below.
func TestTypescriptNeedsBothHalves(t *testing.T) {
	lone := Detect(fstest.MapFS{"tsconfig.json": {Data: []byte("{}")}})
	if has(lone.Stacks, "typescript") {
		t.Fatalf("stacks = %v, want no typescript without package.json", lone.Stacks)
	}
	both := Detect(fstest.MapFS{
		"tsconfig.json": {Data: []byte("{}")},
		"package.json":  {Data: []byte("{}")},
	})
	if !has(both.Stacks, "typescript") {
		t.Fatalf("stacks = %v, want typescript", both.Stacks)
	}
	if len(both.Ambiguous) != 0 {
		t.Fatalf("ambiguous = %v, want none once tsconfig.json answers it", both.Ambiguous)
	}
}

// A lone package.json is not a stack but a question: it is as often tooling
// for another language as it is a project of its own.
func TestALonePackageJsonIsAskedAboutRatherThanDecided(t *testing.T) {
	facts := Detect(fstest.MapFS{"package.json": {Data: []byte("{}")}})
	if len(facts.Stacks) != 0 {
		t.Fatalf("stacks = %v, want none", facts.Stacks)
	}
	if len(facts.Ambiguous) != 1 || !strings.Contains(facts.Ambiguous[0], "package.json") {
		t.Fatalf("ambiguous = %v, want the package.json question", facts.Ambiguous)
	}
}

// Django is detected, and what it means for migrations is asked.
func TestDjangoAsksAboutMigrations(t *testing.T) {
	facts := Detect(fstest.MapFS{"manage.py": {Data: []byte("import django\n")}})
	if !has(facts.Stacks, "django") {
		t.Fatalf("stacks = %v, want django", facts.Stacks)
	}
	if len(facts.Ambiguous) != 1 || !strings.Contains(facts.Ambiguous[0], "migrations") {
		t.Fatalf("ambiguous = %v, want the migrations question", facts.Ambiguous)
	}
}

func TestGdUnit4IsSeenInTheCsproj(t *testing.T) {
	for _, reference := range []string{"gdUnit4.api", "gdUnit4.test.adapter"} {
		t.Run(reference, func(t *testing.T) {
			facts := Detect(fstest.MapFS{
				"game.csproj": {Data: []byte("<Project><PackageReference Include=\"" + reference + "\" /></Project>")},
			})
			if !has(facts.Stacks, "gdunit4") {
				t.Fatalf("stacks = %v, want gdunit4", facts.Stacks)
			}
		})
	}
	plain := Detect(fstest.MapFS{"game.csproj": {Data: []byte("<Project/>")}})
	if has(plain.Stacks, "gdunit4") {
		t.Fatalf("stacks = %v, want no gdunit4", plain.Stacks)
	}
}

func TestGitAndWikiAreFacts(t *testing.T) {
	tree := fstest.MapFS{
		".git/HEAD":     {Data: []byte("ref: refs/heads/master\n")},
		"wiki/index.md": {Data: []byte("---\nokf_version: \"0.2\"\n---\n# Concepts\n")},
	}
	facts := Detect(tree)
	if !facts.HasGit {
		t.Fatal("HasGit = false, want true")
	}
	if facts.WikiMode != "brain" || facts.WikiPath != "wiki/" {
		t.Fatalf("wiki = %q %q, want \"brain\" \"wiki/\"", facts.WikiMode, facts.WikiPath)
	}
}

func TestATreeWithoutGitOrWikiSaysNeither(t *testing.T) {
	facts := Detect(fstest.MapFS{"README.md": {Data: []byte("nothing here\n")}})
	if facts.HasGit {
		t.Fatal("HasGit = true, want false")
	}
	if facts.WikiMode != "" || facts.WikiPath != "" {
		t.Fatalf("wiki = %q %q, want empty", facts.WikiMode, facts.WikiPath)
	}
}

// A docs folder called wiki is the false alarm that must not become brain
// mode: the marker decides, and without it the interview does.
func TestAPlainWikiFolderIsAskedAboutRatherThanAsserted(t *testing.T) {
	facts := Detect(fstest.MapFS{"wiki/notes.md": {Data: []byte("# notes\n")}})
	if facts.WikiMode != "" || facts.WikiPath != "" {
		t.Fatalf("wiki = %q %q, want empty", facts.WikiMode, facts.WikiPath)
	}
	if len(facts.Ambiguous) != 1 || !strings.Contains(facts.Ambiguous[0], "wiki/") {
		t.Fatalf("ambiguous = %v, want the wiki question", facts.Ambiguous)
	}
}

// An index without the marker is the same case as no index at all.
func TestAWikiIndexWithoutTheMarkerIsNotABundle(t *testing.T) {
	facts := Detect(fstest.MapFS{"wiki/index.md": {Data: []byte("# just an index\n")}})
	if facts.WikiMode != "" {
		t.Fatalf("wiki mode = %q, want empty", facts.WikiMode)
	}
	if len(facts.Ambiguous) != 1 {
		t.Fatalf("ambiguous = %v, want the wiki question", facts.Ambiguous)
	}
}

// An unreadable tree is a fact, not an error: what cannot be read carries no
// signal, and detection reports what is left of the tree.
func TestAnUnlistableTreeYieldsNoStacks(t *testing.T) {
	facts := Detect(closedFS{})
	if len(facts.Stacks) != 0 {
		t.Fatalf("stacks = %v, want none", facts.Stacks)
	}
	if facts.HasGit {
		t.Fatal("HasGit = true, want false")
	}
}

// The narrower failure: the names are there, the contents are not. A row that
// needs to look inside must then decline rather than guess.
func TestAnUnreadableFileDoesNotSatisfyContains(t *testing.T) {
	facts := Detect(listableFS{fstest.MapFS{
		"project.godot": {Data: []byte("config_version=5\n\n[dotnet]\n")},
	}})
	if !has(facts.Stacks, "gdscript") {
		t.Fatalf("stacks = %v, want gdscript", facts.Stacks)
	}
	if has(facts.Stacks, "csharp") {
		t.Fatalf("stacks = %v, want no csharp", facts.Stacks)
	}
}

// closedFS refuses every access, which is what an unreadable root looks like
// from here: no listing, no stat, no content.
type closedFS struct{}

func (closedFS) Open(name string) (fs.File, error) {
	return nil, &fs.PathError{Op: "open", Path: name, Err: fs.ErrPermission}
}

// listableFS answers about names and refuses their contents. Stat and ReadDir
// are delegated; Open, which is all that is left for reading a file, is not.
type listableFS struct {
	tree fstest.MapFS
}

func (f listableFS) Open(name string) (fs.File, error) {
	return nil, &fs.PathError{Op: "open", Path: name, Err: fs.ErrPermission}
}

func (f listableFS) Stat(name string) (fs.FileInfo, error) {
	return fs.Stat(f.tree, name)
}

func (f listableFS) ReadDir(name string) ([]fs.DirEntry, error) {
	return fs.ReadDir(f.tree, name)
}

func TestEcosystemToolingDetection(t *testing.T) {
	tree := fstest.MapFS{
		"biome.json":          {Data: []byte("{}")},
		"pnpm-workspace.yaml": {Data: []byte("packages:\n  - 'apps/*'")},
		".gdlintrc":           {Data: []byte("")},
		"docker-compose.yml":  {Data: []byte("version: '3'")},
	}
	facts := Detect(tree)
	for _, want := range []string{"biome", "typescript", "pnpm", "gdlint", "gdscript", "docker"} {
		if !has(facts.Stacks, want) {
			t.Errorf("stacks = %v, want %s", facts.Stacks, want)
		}
	}
}

func has(all []string, one string) bool {
	for _, candidate := range all {
		if candidate == one {
			return true
		}
	}
	return false
}
