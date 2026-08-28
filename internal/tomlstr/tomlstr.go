// Package tomlstr writes one TOML basic string, for everyone who writes TOML
// by hand here.
//
// It exists because there were two of these, rune for rune the same, in
// internal/render and internal/vendoring -- and their comments had already
// drifted apart: one had learned about Windows paths, the other had not, and
// the fix to the backspace escape reached only one side. Two copies of an
// escape table are two answers to "is this file still valid TOML?", and the
// day they disagree is the day one of them writes a file nobody can read.
package tomlstr

import (
	"fmt"
	"strings"
)

// Quote writes value as a TOML basic string, quotes included.
//
// Not what Go's %q writes. TOML 1.0 knows the seven single-letter escapes and
// the \u escapes and nothing else, while %q reaches for \v and \x for the
// same characters -- one of those in a path or a branch name is an invalid
// escape that takes the whole file down while the value still looks right in
// the source. And nothing that reaches a generated file may be interpolated
// raw: a wiki bundle is a path, and on Windows a path carries backslashes, so
// `wiki\bundle` written as it stands is that same invalid escape.
//
// There is no input this refuses. Ranging over a string already turns invalid
// UTF-8 into the replacement character, which the default branch writes out
// like any other rune.
func Quote(value string) string {
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
