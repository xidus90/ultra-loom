// Package render turns decisions into files, in memory.
//
// Nothing here touches the disk. Writing is a separate step so a failure in
// the third template cannot leave a project half configured -- see
// internal/write.
package render

import (
	"embed"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"text/template"

	"github.com/xidus90/ultra-loom/internal/answers"
)

//go:embed templates/*.tmpl
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
}

func Render(a answers.Answers) (map[string]string, error) {
	data := newView(a)
	out := make(map[string]string, len(targets))
	for name, target := range targets {
		body, err := one(name, data)
		// Unreachable while the embedded templates parse and execute -- which a
		// build settles, not a run. Kept because an edit to templates/ could
		// change that, and a swallowed template error would ship broken files.
		if err != nil {
			return nil, fmt.Errorf("rendering %s: %w", name, err)
		}
		out[target] = body
	}
	return out, nil
}

func newView(a answers.Answers) view {
	data := view{Answers: a, EditKinds: []string{"lint", "types"}}
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
	data.PrecommitKinds = []string{"lint"}
	if a.Gates.TypesInStop {
		data.PrecommitKinds = append(data.PrecommitKinds, "types")
	}
	if a.Gates.TestsInStop {
		data.PrecommitKinds = append(data.PrecommitKinds, "test", "coverage")
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
// interpolates a raw string: a wiki bundle is a path, and on Windows a path
// carries backslashes -- written raw, `wiki\bundle` is an invalid escape that
// takes the whole file down while the answers still look right. One class
// further in, this writes a TOML basic string, which is not what Go's %q
// writes: TOML 1.0 knows \b \t \n \f \r \" \\ and the \u escapes and nothing
// else, while %q reaches for \v and \x for the same characters. Ranging over
// a string already turns invalid UTF-8 into the replacement character, which
// the default branch writes like any other rune, so nothing is refused here.
func tomlString(value string) string {
	var out strings.Builder
	out.WriteByte('"')
	for _, r := range value {
		switch r {
		case '"':
			out.WriteString(`\"`)
		case '\\':
			out.WriteString(`\\`)
		case '\b':
			out.WriteString(`\b`)
		case '\t':
			out.WriteString(`\t`)
		case '\n':
			out.WriteString(`\n`)
		case '\f':
			out.WriteString(`\f`)
		case '\r':
			out.WriteString(`\r`)
		default:
			// U+007F is a control character too, and TOML bars it from a basic
			// string just as it bars the C0 range.
			if r < 0x20 || r == 0x7f {
				fmt.Fprintf(&out, `\u%04X`, r)
				continue
			}
			out.WriteRune(r)
		}
	}
	out.WriteByte('"')
	return out.String()
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
	parsed, err := template.New(name).Funcs(helpers).ParseFS(templates, "templates/"+name)
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
