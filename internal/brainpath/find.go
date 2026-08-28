// Package brainpath finds ultra-brain, and refuses to guess.
//
// brain holds one index across all projects, so it is found rather than
// pinned -- a clone per project would make separate brains and take from
// `search` exactly what makes it useful. When it is not found, the wiki
// hooks are not installed: a gate that cannot run is worse than none.
package brainpath

import (
	"bytes"
	"encoding/json"
	"strings"
)

// Lookup is exec.LookPath, injected so the tests need no PATH.
//
// Any non-nil error means "not on PATH". No distinction is drawn between the
// kinds -- exec.ErrDot included -- because a brain the installer would have to
// resolve through a relative path is not one a generated project can call.
type Lookup func(name string) (string, error)

// dirPrefix and dirSuffix bracket the directory in the command string that
// Find returns for the ULTRA_BRAIN_DIR case. Find is the only producer of
// that string and MCPEntry the only reader, so the two shapes below are the
// whole contract: either the bare name or exactly this frame. Reading the
// directory back by the frame rather than by splitting on spaces is what
// keeps `C:/Program Files/brain` one argument.
const (
	dirPrefix = "uv run --directory "
	dirSuffix = " brain"
)

// Find answers what a generated project should call to reach brain.
//
// env is os.Getenv: an empty string means unset or empty, and the two are not
// told apart. A `uv tool` shim is itself an entry on PATH, so one lookup
// answers for both -- and it answers first, because a machine that has brain
// installed properly should not be overridden by a stale variable.
func Find(look Lookup, env func(string) string) (string, bool) {
	// The bare name, not the resolved path: .mcp.json is versioned, and an
	// absolute path in it is a claim about one machine.
	if _, err := look("brain"); err == nil {
		return "brain", true
	}
	// A variable holding only spaces is a mistake, not a location.
	if dir := strings.TrimSpace(env("ULTRA_BRAIN_DIR")); dir != "" {
		return dirPrefix + dir + dirSuffix, true
	}
	return "", false
}

// MCPEntry renders the .mcp.json document a generated project uses.
//
// An MCP client executes "command" directly -- there is no shell -- so a
// command line has to arrive split, with everything after the executable in
// "args". The document is marshalled rather than formatted because Go's %q is
// not a JSON string escape: a backslash or an ESC in a Windows path would come
// out as source that reads right and does not parse.
func MCPEntry(command string) string {
	exe, args := command, []string{"mcp"}
	if strings.HasPrefix(command, dirPrefix) && strings.HasSuffix(command, dirSuffix) {
		dir := strings.TrimSuffix(strings.TrimPrefix(command, dirPrefix), dirSuffix)
		exe, args = "uv", []string{"run", "--directory", dir, "brain", "mcp"}
	}
	type server struct {
		Command string   `json:"command"`
		Args    []string `json:"args"`
	}
	doc := struct {
		MCPServers map[string]server `json:"mcpServers"`
	}{MCPServers: map[string]server{"brain": {Command: exe, Args: args}}}

	var out bytes.Buffer
	enc := json.NewEncoder(&out)
	// A path is not HTML; escaping < and > would only make the file harder to read.
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	// Strings and slices of strings have no unmarshalable case; the error can
	// only report a channel, a func or a cycle, none of which this document has.
	_ = enc.Encode(doc)
	return out.String()
}
