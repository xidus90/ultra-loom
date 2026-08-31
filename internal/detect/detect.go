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

// okfMarker is what separates a brain bundle from a docs folder that happens
// to be called wiki. It stands in the front matter of the bundle's index.
const okfMarker = "okf_version"

// Facts is what a tree says about itself.
type Facts struct {
	Stacks    []string
	HasGit    bool
	HooksPath string
	WikiMode  string
	WikiPath  string
	// Ambiguous carries findings that must not be decided here -- a Django
	// project whose migrations may be generated or wanted, a package.json
	// that may be tooling only. The interview resolves them.
	Ambiguous []string
}

// Detect reads the root and one level below it, for workspaces.
//
// Two facts are missing from what it can return: HooksPath lives in git's
// config and the neighbour wiki lies outside the root. Both have their own
// function in this package, and cmd/init joins them to these facts.
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
	facts := Facts{Stacks: sorted(found), Ambiguous: doubts(root, areas)}
	if _, err := fs.Stat(root, ".git"); err == nil {
		facts.HasGit = true
	}
	facts.readWiki(root)
	if facts.WikiMode != "" && facts.WikiMode != "none" {
		found["wiki"] = true
		facts.Stacks = sorted(found)
	}
	return facts
}

// readWiki decides between the two things a wiki/ directory can be.
//
// The marker rather than the mere directory: a repository that keeps plain
// documentation under wiki/ would otherwise be told it has a brain bundle,
// and everything downstream would act on it.
func (facts *Facts) readWiki(root fs.FS) {
	entries, err := fs.ReadDir(root, "wiki")
	if err != nil || len(entries) == 0 {
		return
	}
	index, err := fs.ReadFile(root, "wiki/index.md")
	if err == nil && strings.Contains(string(index), okfMarker) {
		facts.WikiMode, facts.WikiPath = "brain", "wiki/"
		return
	}
	facts.Ambiguous = append(facts.Ambiguous, wikiNote)
}

// doubts collects the questions the tree raises without answering.
func doubts(root fs.FS, areas []string) []string {
	var notes []string
	for _, doubt := range ambiguities {
		for _, area := range areas {
			if !exists(root, path.Join(area, doubt.path)) {
				continue
			}
			if doubt.unless != "" && exists(root, path.Join(area, doubt.unless)) {
				continue
			}
			notes = append(notes, doubt.note)
			break
		}
	}
	return notes
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
	if sig.besides != "" && !exists(root, path.Join(area, sig.besides)) {
		return false
	}
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
		if exists(root, full) {
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

func exists(root fs.FS, name string) bool {
	_, err := fs.Stat(root, name)
	return err == nil
}

func sorted(set map[string]bool) []string {
	var all []string
	for key := range set {
		all = append(all, key)
	}
	sort.Strings(all)
	return all
}
