// Package hostio is the seam between a hook's work and the host that calls it.
//
// One normalised payload in, one normalised answer out. The core packages see
// these two types and never a JSON envelope, so a second host costs an adapter
// and not a second copy of the hook.
//
// The host arrives as a flag and is not guessed from the payload. Guessing was
// the first design -- `tool_input.file_path` for Claude against `TargetFile`
// for Antigravity, the way `brain guard` does it -- and it cannot work here:
// the four events these hooks answer are not tool events at all. SessionStart,
// Stop and the subagent pair carry no `tool_input`, so there is nothing to
// recognise. The flag is not a second place for the same truth either, because
// ulinit writes both host files from one table and knows the host as it builds
// the command.
package hostio

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// Host is which harness is calling.
type Host string

const (
	HostClaude      Host = "claude"
	HostAntigravity Host = "antigravity"
	HostCodex       Host = "codex"
)

// ErrNoRoot is returned when no `.ultraloom/config.toml` stands above the
// starting directory.
var ErrNoRoot = errors.New("no .ultraloom/config.toml above this directory")

// ParseHost turns the flag's value into a Host, or refuses it.
//
// Refused and not defaulted: the value is written by ulinit, so one nobody
// knows means the two have drifted apart. Answering a hook in the wrong shape
// is worse than refusing to answer.
func ParseHost(name string) (Host, error) {
	switch Host(name) {
	case HostClaude:
		return HostClaude, nil
	case HostAntigravity:
		return HostAntigravity, nil
	case HostCodex:
		return HostCodex, nil
	}
	return "", fmt.Errorf("unknown host %q: expected claude, antigravity or codex", name)
}

// Payload is what a hook needs to know, whichever host asked.
//
// Two fields, because session-start needs two. The tool and the paths a write
// barrier reads arrive when the stage that needs them does; a field nobody
// reads has no test holding it in place.
type Payload struct {
	Event     string
	SessionID string
}

// Read decodes the host's payload.
func Read(host Host, r io.Reader) (Payload, error) {
	switch host {
	case HostClaude:
		return readClaude(r)
	case HostAntigravity:
		return readAntigravity(r)
	case HostCodex:
		return readCodex(r)
	}
	return Payload{}, fmt.Errorf("unknown host %q", host)
}

// WriteContext hands lines back for the model to read.
func WriteContext(host Host, w io.Writer, lines []string) error {
	switch host {
	case HostClaude:
		return writeClaudeContext(w, lines)
	case HostAntigravity:
		return writeAntigravityContext(w, lines)
	case HostCodex:
		return writeCodexContext(w, lines)
	}
	return fmt.Errorf("unknown host %q", host)
}

// FindRoot walks up from `start` to the first directory holding
// `.ultraloom/config.toml`.
//
// Needed because an Antigravity hook runs with its working directory set to
// the directory holding `hooks.json`, which is `.agents/` and not the project
// root. Measured on 2026-09-10 against agy 1.1.24 -- see
// docs/.superpowers/specs/2026-09-10-antigravity-hook-messung.md, finding 2 --
// and stated the same way in the antigravity-for-claude-code plugin's
// docs/MIGRATION.md:157. Whether Antigravity sets `${CLAUDE_PROJECT_DIR}` is
// not part of either finding and is unmeasured here; the working directory
// alone is reason enough to walk. A `--root` given on the command line
// outranks this and is handled by the caller.
func FindRoot(start string) (string, error) {
	return findRoot(start, filepath.Abs)
}

// findRoot is FindRoot with its path resolver as a parameter.
//
// filepath.Abs fails only when os.Getwd does, which no test on the platforms
// this runs on can provoke -- so the resolver is injected here rather than
// leaving the refusal untested. The caller passes ".", so resolving is not
// optional: filepath.Dir would walk that to "." and stop there instead of
// climbing to the volume root.
func findRoot(start string, resolve func(string) (string, error)) (string, error) {
	current, err := resolve(start)
	if err != nil {
		return "", fmt.Errorf("resolving %s: %w", start, err)
	}
	for {
		candidate := filepath.Join(current, ".ultraloom", "config.toml")
		if _, err := os.Stat(candidate); err == nil {
			return current, nil
		}
		parent := filepath.Dir(current)
		if parent == current {
			return "", fmt.Errorf("%s: %w", start, ErrNoRoot)
		}
		current = parent
	}
}
