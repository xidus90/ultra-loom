// Package detect answers what a project is, and nothing else.
//
// It takes an fs.FS rather than a path so the tests need no directories on
// disk, and it writes nothing: every decision that follows from these facts
// is made elsewhere. `--dry-run` is free because of that.
package detect

import (
	"io/fs"
	"path"
	"sort"
	"strings"
)

// Facts is what a tree says about itself.
type Facts struct {
	Stacks    []string
	HasGit    bool
	HooksPath string
	WikiMode  string
	WikiPath  string
	// Ambiguous carries findings that must not be decided here -- two
	// stacks that rarely coexist, a package.json that may be tooling only.
	// The interview resolves them.
	Ambiguous []string
}

// Detect reads the root and one level below it, for workspaces.
func Detect(root fs.FS) Facts {
	areas := searchAreas(root)
	found := map[string]bool{}
	for _, sig := range signals {
		for _, area := range areas {
			if matches(root, area, sig) {
				for _, stack := range sig.stacks {
					found[stack] = true
				}
				break
			}
		}
	}
	facts := Facts{Stacks: sorted(found)}
	if _, err := fs.Stat(root, ".git"); err == nil {
		facts.HasGit = true
	}
	if entries, err := fs.ReadDir(root, "wiki"); err == nil && len(entries) > 0 {
		facts.WikiMode, facts.WikiPath = "brain", "wiki/"
	}
	return facts
}

// searchAreas names the root and the directories a workspace member could be.
//
// One level and no further: below that, a directory belongs to a member's own
// layout, and a rule fired from there says something about the wrong project.
// Dot directories are skipped for the same reason -- `.godot/` and `.venv/`
// carry caches, not projects, and a false alarm costs more than a missing rule.
func searchAreas(root fs.FS) []string {
	areas := []string{"."}
	entries, err := fs.ReadDir(root, ".")
	if err != nil {
		return areas
	}
	for _, entry := range entries {
		if entry.IsDir() && !strings.HasPrefix(entry.Name(), ".") {
			areas = append(areas, entry.Name())
		}
	}
	return areas
}

func matches(root fs.FS, area string, sig signal) bool {
	for _, name := range candidates(root, area, sig) {
		if sig.contains == "" {
			return true
		}
		body, err := fs.ReadFile(root, name)
		if err == nil && strings.Contains(string(body), sig.contains) {
			return true
		}
	}
	return false
}

func candidates(root fs.FS, area string, sig signal) []string {
	if sig.path != "" {
		full := path.Join(area, sig.path)
		if _, err := fs.Stat(root, full); err == nil {
			return []string{full}
		}
		return nil
	}
	entries, err := fs.ReadDir(root, area)
	if err != nil {
		return nil
	}
	var hits []string
	for _, entry := range entries {
		if ok, _ := path.Match(sig.glob, entry.Name()); ok {
			hits = append(hits, path.Join(area, entry.Name()))
		}
	}
	return hits
}

func sorted(set map[string]bool) []string {
	var all []string
	for key := range set {
		all = append(all, key)
	}
	sort.Strings(all)
	return all
}
