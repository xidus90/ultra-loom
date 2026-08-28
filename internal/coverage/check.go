// Package coverage answers one question: does anything actually enforce the
// threshold?
//
// It never writes. `coverage report` takes its exit code from fail_under and
// from nothing else -- a run at 83 % is green without that key. A tool that
// prints "coverage: ok" for a threshold nobody checks is the one failure in
// this system that does real damage, so the check is here and the setting
// stays where its owner put it.
//
// Every doubt is resolved against enforcement: a file no tool can read, a
// value coverage.py would refuse, a key in the wrong table. Saying "not
// enforced" about a project that is costs a redundant question; the other
// mistake ships a promise nothing keeps.
package coverage

import (
	"strconv"
	"strings"

	"github.com/BurntSushi/toml"
)

// pyproject mirrors only the one path coverage.py reads. Decoding into a
// shape rather than scanning lines is what tells a threshold apart from the
// word fail_under in a docstring or under [tool.mypy].
type pyproject struct {
	Tool struct {
		Coverage struct {
			Report struct {
				FailUnder *float64 `toml:"fail_under"`
			} `toml:"report"`
		} `toml:"coverage"`
	} `toml:"tool"`
}

// Enforced reports whether either file makes a coverage run able to fail.
//
// Both arguments may be nil: a project that has neither file is the normal
// case at the moment this is asked.
func Enforced(pyprojectSrc, coveragerc []byte) bool {
	return tomlEnforces(pyprojectSrc) || iniEnforces(coveragerc)
}

func tomlEnforces(src []byte) bool {
	var file pyproject
	if _, err := toml.Decode(string(src), &file); err != nil {
		return false
	}
	threshold := file.Tool.Coverage.Report.FailUnder
	return threshold != nil && *threshold > 0
}

// iniEnforces reads .coveragerc, which is configparser rather than TOML: the
// indented continuation lines under exclude_lines are not valid TOML, so the
// parser above would call every real file unreadable.
func iniEnforces(src []byte) bool {
	section := ""
	for _, raw := range strings.Split(string(src), "\n") {
		// An indented line belongs to the value above it, so nothing on it
		// is an option -- exclude_lines may well list a threshold-shaped
		// pattern.
		if raw != strings.TrimLeft(raw, " 	") {
			continue
		}
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "#") || strings.HasPrefix(line, ";") {
			continue
		}
		if strings.HasPrefix(line, "[") {
			// A comment character before the closing bracket is part of the
			// section name, so the search for one starts behind the name.
			section = ""
			if end := strings.Index(line, "]"); end >= 0 {
				rest := strings.TrimSpace(line[end+1:])
				if rest == "" || strings.HasPrefix(rest, "#") || strings.HasPrefix(rest, ";") {
					section = strings.TrimSpace(line[1:end])
				}
			}
			continue
		}
		if section != "report" {
			continue
		}
		// configparser takes either character as the delimiter, and a file
		// that writes the colon enforces just as much as one that does not.
		cut := strings.IndexAny(line, "=:")
		// configparser folds option names to lower case before it looks
		// them up, so the spelling in the file decides nothing.
		if cut < 0 || !strings.EqualFold(strings.TrimSpace(line[:cut]), "fail_under") {
			continue
		}
		value, err := strconv.ParseFloat(strings.TrimSpace(line[cut+1:]), 64)
		if err == nil && value > 0 {
			return true
		}
	}
	return false
}
