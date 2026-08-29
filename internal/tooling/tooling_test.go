package tooling

import (
	"errors"
	"testing"
)

func TestCheckToolsFindsPresentAndReportsMissing(t *testing.T) {
	fakePaths := map[string]string{
		"uv":   "/usr/local/bin/uv",
		"ruff": "/usr/local/bin/ruff",
	}
	lookup := func(name string) (string, error) {
		if path, ok := fakePaths[name]; ok {
			return path, nil
		}
		return "", errors.New("not found")
	}

	found, missing := CheckTools([]string{"python", "python", "unknown_stack"}, lookup)

	if len(found) != 2 || found["uv"] != "/usr/local/bin/uv" || found["ruff"] != "/usr/local/bin/ruff" {
		t.Fatalf("unexpected found tools: %v", found)
	}

	// dmypy is missing
	var missingNames []string
	for _, m := range missing {
		missingNames = append(missingNames, m.Name)
	}
	if len(missingNames) != 1 || missingNames[0] != "dmypy" {
		t.Fatalf("unexpected missing tools: %v", missingNames)
	}
}

func TestCheckToolsDefaultLookup(t *testing.T) {
	// Call CheckTools with nil to execute DefaultLookPath branch
	found, missing := CheckTools([]string{"go"}, nil)
	if found == nil && missing == nil {
		t.Fatal("expected maps/slices to be initialized")
	}
	// Direct call to DefaultLookPath
	_, _ = DefaultLookPath("go")
}

func TestCheckToolsCPP(t *testing.T) {
	fakePaths := map[string]string{
		"clang-format": "/usr/bin/clang-format",
		"clang-tidy":   "/usr/bin/clang-tidy",
		"cmake":        "/usr/bin/cmake",
		"ninja":        "/usr/bin/ninja",
	}
	lookup := func(name string) (string, error) {
		if path, ok := fakePaths[name]; ok {
			return path, nil
		}
		return "", errors.New("not found")
	}
	found, missing := CheckTools([]string{"cpp"}, lookup)
	if len(missing) != 0 {
		t.Fatalf("expected 0 missing cpp tools, got %v", missing)
	}
	if found["cmake"] != "/usr/bin/cmake" || found["clang-format"] != "/usr/bin/clang-format" {
		t.Fatalf("unexpected found tools: %v", found)
	}
}

func TestInstallTool(t *testing.T) {
	spec := ToolSpec{
		Name:       "ruff",
		Stack:      "python",
		InstallCmd: "uv tool install ruff",
	}

	var executed []string
	runner := func(dir string, argv ...string) (string, error) {
		executed = argv
		return "Installed ruff", nil
	}

	if err := InstallTool(spec, runner, "."); err != nil {
		t.Fatalf("InstallTool: %v", err)
	}

	if len(executed) != 4 || executed[0] != "uv" || executed[3] != "ruff" {
		t.Fatalf("unexpected execution argv: %v", executed)
	}

	// Error case: failing runner
	failRunner := func(dir string, argv ...string) (string, error) {
		return "", errors.New("network error")
	}
	if err := InstallTool(spec, failRunner, "."); err == nil {
		t.Fatal("want error when runner fails")
	}

	// Error case: empty install cmd
	emptySpec := ToolSpec{Name: "empty", InstallCmd: "   "}
	if err := InstallTool(emptySpec, runner, "."); err == nil {
		t.Fatal("want error on empty install command")
	}

	// Error case: no install cmd
	noCmdSpec := ToolSpec{Name: "no-cmd"}
	if err := InstallTool(noCmdSpec, runner, "."); err == nil {
		t.Fatal("want error on missing install command")
	}
}
