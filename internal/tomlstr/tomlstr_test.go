package tomlstr

import "testing"

// One case per branch, plus the two that are not escapes at all: a plain word,
// and a byte that is not UTF-8.
func TestEveryEscapeTomlKnows(t *testing.T) {
	cases := map[string]string{
		"plain":       `"plain"`,
		`wiki\bundle`: `"wiki\\bundle"`,
		`say "no"`:    `"say \"no\""`,
		"a\bb":        `"a\bb"`,
		"a\tb":        `"a\tb"`,
		"a\nb":        `"a\nb"`,
		"a\fb":        `"a\fb"`,
		"a\rb":        `"a\rb"`,
		"a\x01b":      `"a\u0001b"`,
		"a\x7fb":      `"a\u007Fb"`,
		"\xff":        "\"\uFFFD\"",
	}
	for value, want := range cases {
		if got := Quote(value); got != want {
			t.Errorf("Quote(%q) = %s, want %s", value, got, want)
		}
	}
}
