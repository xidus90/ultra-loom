// Package answers holds the decisions of one project.
//
// Decisions, not output: everything else this tool writes is derived from
// this type. Changing a generated file is therefore always the wrong move,
// and the header of every generated file says so.
package answers

import (
	"fmt"

	"github.com/BurntSushi/toml"
	"github.com/xidus90/ultra-loom/internal/detect"
)

type Project struct {
	Stacks         []string `toml:"stacks"`
	Agents         []string `toml:"agents"`
	DocsLanguage   string   `toml:"docs_language"`
	CommitLanguage string   `toml:"commit_language"`
}

// KnownAgents names the agent platforms ultraloom can configure.
var KnownAgents = []string{"claude", "gemini"}

type Wiki struct {
	Mode   string `toml:"mode"`
	Bundle string `toml:"bundle"`
}

// Gates carries CoverageThreshold as a number nothing here reads: the
// threshold is reported, and enforced by the project's own fail_under.
type Gates struct {
	CoverageThreshold int  `toml:"coverage_threshold"`
	TestsInStop       bool `toml:"tests_in_stop"`
	TypesInStop       bool `toml:"types_in_stop"`
	Wiki              Wiki `toml:"wiki"`
}

type Policy struct {
	ProtectedPaths    []string `toml:"protected_paths"`
	ForbiddenCommands []string `toml:"forbidden_commands"`
}

type Answers struct {
	Project   Project             `toml:"project"`
	Gates     Gates               `toml:"gates"`
	Policy    Policy              `toml:"policy"`
	Relevance map[string][]string `toml:"relevance"`
}

// WikiModes is the whole set. A mode outside it is a typo, and a typo that
// silently disables the wiki gate is the expensive kind.
var WikiModes = []string{"brain", "neighbour_repo", "none"}

// Defaults is what the interview starts from: the facts, plus the
// conventions of this repo for everything a tree cannot say.
//
// Policy stays empty on purpose. Its entries answer what detection left
// ambiguous -- the Django migrations question above all -- and prefilling
// them here would decide silently what the interview is there to ask.
func Defaults(facts detect.Facts) Answers {
	return Answers{
		Project: Project{
			Stacks:         facts.Stacks,
			Agents:         []string{"claude", "gemini"},
			DocsLanguage:   "de",
			CommitLanguage: "en",
		},
		Gates: Gates{
			CoverageThreshold: 100,
			TestsInStop:       true,
			TypesInStop:       true,
			Wiki:              Wiki{Mode: modeOr(facts.WikiMode, "none"), Bundle: facts.WikiPath},
		},
		// Two rows, and the second one only earns its place for a brain
		// project: a wiki page that changed has to be reindexed, or search
		// answers from yesterday's text. The rows that map to nothing --
		// docs/** and *.txt -- are pure cost and stay out.
		Relevance: map[string][]string{
			"*.md":    {},
			"wiki/**": {"brain reindex"},
		},
	}
}

// Load reads an answers.toml as it stands, partial runs included: a second
// run finds only what the first one wrote, and the interview fills the rest.
func Load(data []byte) (Answers, error) {
	var loaded Answers
	if _, err := toml.Decode(string(data), &loaded); err != nil {
		return Answers{}, fmt.Errorf("answers.toml: %w", err)
	}
	if loaded.Gates.Wiki.Mode != "" && !valid(loaded.Gates.Wiki.Mode) {
		return Answers{}, fmt.Errorf(
			"answers.toml: [gates.wiki].mode is %q, must be one of %v",
			loaded.Gates.Wiki.Mode, WikiModes)
	}
	return loaded, nil
}

func valid(mode string) bool {
	for _, known := range WikiModes {
		if known == mode {
			return true
		}
	}
	return false
}

func modeOr(detected, fallback string) string {
	if detected == "" {
		return fallback
	}
	return detected
}
