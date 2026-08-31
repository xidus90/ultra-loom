package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/xidus90/ultra-loom/internal/detect"
)

var knownLegacyHooks = []struct {
	scriptName string
	reason     string
}{
	{"guard_paths.py", "superseded by native Go 'ulguard' in PreToolUse (<5ms)"},
	{"format_on_edit.py", "superseded by native Go 'ulguard post-edit' in PostToolUse"},
	{"post_edit.py", "superseded by native Go 'ulguard post-edit' in PostToolUse"},
	{"wiki_gate.py", "superseded by 'brain wiki-gate' in Stop hook"},
	{"generate_index.py", "superseded by ultra-brain catalog/reindex and wiki-gate"},
	{"lint.py", "superseded by 'brain lint' and 'ulguard post-edit'"},
}

type LegacyFinding struct {
	Event   string
	Command string
	Reason  string
}

func auditSettings(root string) ([]LegacyFinding, bool, bool) {
	settingsPath := filepath.Join(root, ".claude", "settings.json")
	data, err := os.ReadFile(settingsPath)
	if err != nil {
		return nil, false, false
	}

	var parsed struct {
		Hooks map[string][]struct {
			Matcher string `json:"matcher"`
			Hooks   []struct {
				Command string `json:"command"`
			} `json:"hooks"`
		} `json:"hooks"`
	}
	if err := json.Unmarshal(data, &parsed); err != nil {
		return nil, false, false
	}

	hasPreGuard := false
	hasPostEdit := false
	var findings []LegacyFinding

	for event, entries := range parsed.Hooks {
		for _, entry := range entries {
			for _, h := range entry.Hooks {
				cmd := h.Command
				if strings.Contains(cmd, "ulguard") && !strings.Contains(cmd, "post-edit") {
					hasPreGuard = true
				}
				if strings.Contains(cmd, "ulguard post-edit") {
					hasPostEdit = true
				}
				for _, leg := range knownLegacyHooks {
					if strings.Contains(cmd, leg.scriptName) {
						findings = append(findings, LegacyFinding{
							Event:   event,
							Command: cmd,
							Reason:  leg.reason,
						})
					}
				}
			}
		}
	}

	return findings, hasPreGuard, hasPostEdit
}

func runStatus(stdout io.Writer, stderr io.Writer, root string) int {
	absRoot, err := filepath.Abs(root)
	if err != nil {
		absRoot = root
	}

	facts := detect.Detect(os.DirFS(root))
	wikiDir := facts.WikiPath
	if wikiDir == "" {
		wikiDir = resolveWikiDir(root)
	}

	fmt.Fprintln(stdout, "================================================================================")
	fmt.Fprintln(stdout, " UltraLoom Guard & Hook Inspection")
	fmt.Fprintln(stdout, "================================================================================")
	fmt.Fprintf(stdout, "Project Root:    %s\n", absRoot)
	fmt.Fprintf(stdout, "Detected Stacks: %v\n", facts.Stacks)

	if facts.WikiMode != "" && facts.WikiMode != "none" {
		fmt.Fprintf(stdout, "UltraBrain Wiki: Active (Mode: %s, Bundle Directory: '%s')\n", facts.WikiMode, wikiDir)
	} else {
		fmt.Fprintln(stdout, "UltraBrain Wiki: Inactive / Disabled (default)")
	}

	fmt.Fprintln(stdout, "\n--------------------------------------------------------------------------------")
	fmt.Fprintln(stdout, " Configured Lifecycle Hooks & Concurrent Tools")
	fmt.Fprintln(stdout, "--------------------------------------------------------------------------------")

	fmt.Fprintln(stdout, "[PreToolUse] (Matcher: Write|Edit|NotebookEdit|Bash|PowerShell)")
	fmt.Fprintln(stdout, "  -> ulguard (Path-Jail, Protected Files & Size Limit in <5ms)")

	fmt.Fprintln(stdout, "\n[PostToolUse] (Matcher: Write|Edit|NotebookEdit)")
	fmt.Fprintln(stdout, "  -> ulguard post-edit (Concurrent Goroutines per file type):")

	hasStack := func(s string) bool {
		for _, stack := range facts.Stacks {
			if stack == s {
				return true
			}
		}
		return false
	}

	if hasStack("python") {
		if hasStack("pyright") {
			if hasStack("uv") {
				fmt.Fprintln(stdout, "     * *.py:           ruff check --output-format=concise . [parallel]")
				fmt.Fprintln(stdout, "                       uv run pyright [parallel]")
			} else {
				fmt.Fprintln(stdout, "     * *.py:           ruff check --output-format=concise . [parallel]")
				fmt.Fprintln(stdout, "                       pyright [parallel]")
			}
		} else if hasStack("uv") {
			fmt.Fprintln(stdout, "     * *.py:           ruff check --output-format=concise . [parallel]")
			fmt.Fprintln(stdout, "                       dmypy run -- --no-error-summary --no-pretty [parallel]")
		} else {
			fmt.Fprintln(stdout, "     * *.py:           ruff check --output-format=concise . [parallel]")
			fmt.Fprintln(stdout, "                       mypy --no-error-summary --no-pretty [parallel]")
		}
	}
	if hasStack("gdscript") {
		fmt.Fprintln(stdout, "     * *.gd:           gdlint <target-file>")
	}
	if hasStack("cpp") {
		fmt.Fprintln(stdout, "     * *.cpp, *.hpp:   clang-format -i <target-file> [parallel]")
		fmt.Fprintln(stdout, "                       cmake --build build --parallel [parallel]")
	}
	if hasStack("typescript") {
		fmt.Fprintln(stdout, "     * *.ts, *.tsx:    npx eslint . [parallel]")
		fmt.Fprintln(stdout, "                       npx tsc --noEmit [parallel]")
	}
	if hasStack("vue") {
		fmt.Fprintln(stdout, "     * *.vue:          npx vue-tsc --noEmit")
	}
	if hasStack("svelte") {
		fmt.Fprintln(stdout, "     * *.svelte:       npx svelte-check")
	}
	if hasStack("css") {
		fmt.Fprintln(stdout, "     * *.css, *.scss:  npx stylelint <target-file>")
	}
	if hasStack("html") {
		fmt.Fprintln(stdout, "     * *.html:         npx htmlhint <target-file>")
	}
	if hasStack("shell") {
		fmt.Fprintln(stdout, "     * *.sh, *.bash:   shellcheck <target-file>")
	}
	if hasStack("sql") {
		fmt.Fprintln(stdout, "     * *.sql:          sqlfluff lint <target-file>")
	}
	if hasStack("rust") {
		fmt.Fprintln(stdout, "     * *.rs:           cargo clippy -- -D warnings [parallel]")
		fmt.Fprintln(stdout, "                       cargo fmt --check [parallel]")
	}
	if hasStack("go") {
		if hasStack("golangci-lint") {
			fmt.Fprintln(stdout, "     * *.go:           golangci-lint run --fast [parallel]")
			fmt.Fprintln(stdout, "                       go vet ./... [parallel]")
		} else {
			fmt.Fprintln(stdout, "     * *.go:           go vet ./...")
		}
	}
	if hasStack("wiki") {
		fmt.Fprintf(stdout, "     * *.md (in %s): brain lint <target-file>\n", wikiDir)
		fmt.Fprintln(stdout, "     * *.md (outside): [SKIPPED] Instant 0ms exit")
	} else {
		fmt.Fprintln(stdout, "     * *.md:           [SKIPPED] Instant 0ms exit (Wiki disabled)")
	}
	fmt.Fprintln(stdout, "     * non-code files: [SKIPPED] Instant 0ms exit (.json, .yaml, .toml, images, ...)")

	fmt.Fprintln(stdout, "\n[Stop] (Session End Gate)")
	if hasStack("wiki") {
		fmt.Fprintln(stdout, "  -> brain wiki-gate --root \"${CLAUDE_PROJECT_DIR}\" (Git-Drift & OKF Bundle Validation)")
	} else {
		fmt.Fprintln(stdout, "  -> No Stop-Hook configured (Wiki disabled)")
	}

	fmt.Fprintln(stdout, "\n--------------------------------------------------------------------------------")
	fmt.Fprintln(stdout, " Hook Audit & Redundancy Check (.claude/settings.json)")
	fmt.Fprintln(stdout, "--------------------------------------------------------------------------------")

	findings, hasPre, hasPost := auditSettings(root)
	if hasPre {
		fmt.Fprintln(stdout, " [OK] PreToolUse:  'ulguard' installed")
	} else {
		fmt.Fprintln(stdout, " [INFO] PreToolUse: 'ulguard' not found in .claude/settings.json")
	}

	if hasPost {
		fmt.Fprintln(stdout, " [OK] PostToolUse: 'ulguard post-edit' installed")
	} else {
		fmt.Fprintln(stdout, " [INFO] PostToolUse: 'ulguard post-edit' not found in .claude/settings.json")
	}

	if len(findings) == 0 {
		fmt.Fprintln(stdout, " [OK] No obsolete or redundant legacy hooks found.")
	} else {
		fmt.Fprintln(stdout, " [WARNING] Redundant or obsolete legacy hooks detected in .claude/settings.json:")
		for _, f := range findings {
			fmt.Fprintf(stdout, "   • [%s] %s\n     Reason: %s\n", f.Event, f.Command, f.Reason)
		}
	}
	fmt.Fprintln(stdout, "================================================================================")

	return ExitOK
}
