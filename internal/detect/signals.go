package detect

// A signal is a file that means something, plus what it means.
//
// Data rather than a chain of ifs: the table is what a reader of the spec
// compares against, and a new stack is a row instead of a branch.
type signal struct {
	// path is matched literally; glob is matched with path.Match. Exactly
	// one of them is set.
	path   string
	glob   string
	stacks []string
	// contains, when set, must appear in the file for the signal to count.
	// That is what separates a Godot project with C# from one without.
	contains string
}

var signals = []signal{
	{path: "pyproject.toml", stacks: []string{"python"}},
	{path: "uv.lock", stacks: []string{"python", "uv"}},
	{path: "requirements.txt", stacks: []string{"python"}},
	{path: "manage.py", stacks: []string{"python", "django"}},
	{path: "project.godot", stacks: []string{"godot", "gdscript"}},
	{path: "project.godot", stacks: []string{"csharp"}, contains: "[dotnet]"},
	{glob: "*.csproj", stacks: []string{"csharp"}},
	{glob: "*.sln", stacks: []string{"csharp"}},
	{path: "tsconfig.json", stacks: []string{"typescript"}},
	{path: "package.json", stacks: []string{"node"}},
	{path: "Cargo.toml", stacks: []string{"rust"}},
	{path: "go.mod", stacks: []string{"go"}},
}
