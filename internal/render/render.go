// Package render turns decisions into files, in memory.
//
// Nothing here touches the disk. Writing is a separate step so a failure in
// the third template cannot leave a project half configured -- see
// internal/write.
package render

import (
	"embed"
	"fmt"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"text/template"

	"github.com/xidus90/ultra-loom/internal/answers"
	"github.com/xidus90/ultra-loom/internal/tomlstr"
)

//go:embed templates/*.tmpl templates/skills/*.tmpl
var templates embed.FS

// targets maps a template to the path it lands on in the project.
var targets = map[string]string{
	"answers.toml.tmpl": ".ultraloom/answers.toml",
	"policy.toml.tmpl":  ".ultraloom/policy.toml",
	"config.toml.tmpl":  ".ultraloom/config.toml",
}

// pushRule is built in rather than asked. `git push` means the same thing in
// every repository -- whether commits reach the remote is a person's call --
// and a project that answered nothing would otherwise get an empty policy as
// the only file init wrote for it.
const pushCommand = "git push"

const pushReason = "Whether commits reach the remote is a human's decision."

// answeredReason belongs only to rules that really came from the answer file.
// The built-in rule above carries its own, because a reason is what an agent
// reads when it is refused, and pointing it at a file that does not hold the
// rule would send it looking in the wrong place.
const answeredReason = "forbidden by this project's answers.toml"

const generatedPathReason = "this file is written by a tool, not by hand"

type pathRule struct {
	Match  string
	Reason string
}

type commandRule struct {
	Regex  string
	Reason string
}

// view is what the templates see: the answers as they stand, plus everything
// that would otherwise be logic inside a template.
type view struct {
	Answers        answers.Answers
	Paths          []pathRule
	Commands       []commandRule
	EditKinds      []string
	PrecommitKinds []string
	// CoverageLane says whether this project gets a coverage check at all.
	// False is not a smaller configuration but the honest one: where nothing
	// can turn that check red, a lane that only ever reports green is the one
	// failure this whole tool exists to prevent.
	CoverageLane bool
}

// Render turns the answers into files.
//
// coverageLane says whether the generated project gets a coverage check at
// all -- no more than that. It is not a claim that anything enforces the
// threshold: the caller decides, and for a language it cannot read the
// configuration of it keeps the lane rather than dropping one that may well
// be enforced. Where that decision is argued is the caller's business; this
// package only installs what it is told to. Nothing here touches the disk.
func Render(a answers.Answers, coverageLane bool) (map[string]string, error) {
	data := newView(a, coverageLane)
	type fileTarget struct {
		tmpl   string
		target string
	}
	var targetsList = []fileTarget{
		{"answers.toml.tmpl", ".ultraloom/answers.toml"},
		{"policy.toml.tmpl", ".ultraloom/policy.toml"},
		{"config.toml.tmpl", ".ultraloom/config.toml"},
		{"AGENTS.md.tmpl", "AGENTS.md"},
	}

	if has(a.Project.Agents, "claude") {
		targetsList = append(targetsList,
			fileTarget{"CLAUDE.md.tmpl", "CLAUDE.md"},
			fileTarget{"skills/verify-until-green.SKILL.md.tmpl", ".claude/skills/verify-until-green/SKILL.md"},
			fileTarget{"skills/session-handover.SKILL.md.tmpl", ".claude/skills/session-handover/SKILL.md"},
		)
	}

	if has(a.Project.Agents, "gemini") {
		targetsList = append(targetsList,
			fileTarget{"GEMINI.md.tmpl", "GEMINI.md"},
			fileTarget{"skills/verify-until-green.SKILL.md.tmpl", ".agents/skills/verify-until-green/SKILL.md"},
			fileTarget{"skills/session-handover.SKILL.md.tmpl", ".agents/skills/session-handover/SKILL.md"},
		)
	}

	out := make(map[string]string, len(targetsList))
	for _, item := range targetsList {
		body, err := one(item.tmpl, data)
		if err != nil {
			return nil, fmt.Errorf("rendering %s: %w", item.tmpl, err)
		}
		out[item.target] = body
	}

	return out, nil
}

func has(all []string, wanted string) bool {
	for _, one := range all {
		if one == wanted {
			return true
		}
	}
	return false
}

func newView(a answers.Answers, coverageLane bool) view {
	data := view{Answers: a, EditKinds: []string{"lint", "types"},
		CoverageLane: coverageLane}
	for _, path := range a.Policy.ProtectedPaths {
		data.Paths = append(data.Paths, pathRule{Match: path, Reason: generatedPathReason})
	}
	data.Commands = append(data.Commands, commandRule{
		Regex: commandPattern(pushCommand), Reason: pushReason})
	for _, command := range a.Policy.ForbiddenCommands {
		// The built-in rule is already there; a project that named it anyway
		// must not end up refused twice for the same reach.
		if command == pushCommand {
			continue
		}
		data.Commands = append(data.Commands, commandRule{
			Regex: commandPattern(command), Reason: answeredReason})
	}
	data.PrecommitKinds = []string{"lint", "types", "test"}
	if coverageLane {
		data.PrecommitKinds = append(data.PrecommitKinds, "coverage")
	}
	return data
}

// commandPattern turns a command into a rule that bites where it is meant to.
// Not anchored with `^`: the whole command line is checked without MULTILINE,
// so `^git push` would let through precisely the form this is about --
// `git commit -m … && git push`. The lesson is ultraloom's own config.toml.
func commandPattern(command string) string {
	var quoted []string
	for _, word := range strings.Fields(command) {
		quoted = append(quoted, regexp.QuoteMeta(word))
	}
	return `(^|[\n;&|(` + "`" + `])\s*` + strings.Join(quoted, `\s+`) + `(?![\w-])`
}

// tomlString is the one way a value reaches a rendered file. Nothing here
// interpolates a raw string, and the escape table itself lives in
// internal/tomlstr: internal/vendoring writes TOML by hand too, and one table
// written twice is two answers to "is this file still valid TOML?".
func tomlString(value string) string {
	return tomlstr.Quote(value)
}

// tomlRegex prefers TOML's literal string, where a backslash is a backslash
// and the pattern reads as it was written. It has no escape at all, so
// whatever it cannot carry raw -- the apostrophe that would close it, and the
// control characters TOML bars outright -- sends the pattern to the basic
// string and its doubled backslashes instead.
func tomlRegex(pattern string) string {
	if strings.ContainsFunc(pattern, literalUnsafe) {
		return tomlString(pattern)
	}
	return "'" + pattern + "'"
}

// literalUnsafe names what a TOML literal string cannot hold. Tab is the one
// control character it may, and it is the one this leaves alone.
func literalUnsafe(r rune) bool {
	return r == '\'' || (r != '\t' && (r < 0x20 || r == 0x7f))
}

var helpers = template.FuncMap{
	// asked separates a question answered with no -- an empty list -- from one
	// the interview still owes, which is nil. Truthiness collapses the two.
	"asked": func(all []string) bool { return all != nil },
	"list":  tomlList,
	"quote": tomlString,
	"regex": tomlRegex,
	"keys": func(all map[string][]string) []string {
		var names []string
		for name := range all {
			names = append(names, name)
		}
		sort.Strings(names)
		return names
	},
}

func tomlList(all []string) string {
	var quoted []string
	for _, one := range all {
		quoted = append(quoted, tomlString(one))
	}
	return "[" + strings.Join(quoted, ", ") + "]"
}

func one(name string, data view) (string, error) {
	base := filepath.Base(name)
	parsed, err := template.New(base).Funcs(helpers).ParseFS(templates, "templates/"+name)
	// Both returns are unreachable for the templates this binary carries: the
	// names come from targets, the files are embedded, and the helpers cannot
	// fail. Only a broken template would reach them, and then it must be loud.
	if err != nil {
		return "", err
	}
	var buffer strings.Builder
	if err := parsed.Execute(&buffer, data); err != nil {
		return "", err
	}
	return buffer.String(), nil
}
