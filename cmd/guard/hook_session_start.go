package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/xidus90/ultra-loom/internal/gitwork"
	"github.com/xidus90/ultra-loom/internal/hostio"
	"github.com/xidus90/ultra-loom/internal/journal"
	"github.com/xidus90/ultra-loom/internal/sessions"
)

// runDir is worktree.py:24's RUN_DIR. Spelled here because one caller needs
// it; when the stop gate needs it too it moves to internal/gitwork, where the
// rest of the tree questions live.
const runDir = ".ultraloom/runs"

// runHookSessionStart tells a fresh session which runs are still waiting for
// an answer, and writes down the commit the session starts on.
//
// Never blocks. This is an announcement, so the only codes it can leave with
// are 0 and 1 -- exit 2 in payload.py's protocol (payload.py:13-15) means
// blocked, and there is nothing here to hold a turn over.
func runHookSessionStart(stdin io.Reader, stdout, stderr io.Writer, root, hostName string) int {
	host, err := hostio.ParseHost(hostName)
	if err != nil {
		fmt.Fprintf(stderr, "ulguard hook session-start: %v\n", err)
		return ExitInternal
	}
	payload, err := hostio.Read(host, stdin)
	if err != nil {
		fmt.Fprintf(stderr, "ulguard hook session-start: %v\n", err)
		return ExitInternal
	}

	if err := recordBase(payload.SessionID, root); err != nil {
		fmt.Fprintf(stderr, "ulguard hook session-start: %v\n", err)
		return ExitInternal
	}

	lines := waiting(root, stderr)
	if err := hostio.WriteContext(host, stdout, lines); err != nil {
		fmt.Fprintf(stderr, "ulguard hook session-start: %v\n", err)
		return ExitInternal
	}
	return ExitOK
}

// recordBase keeps the commit this session starts on, if there is one to keep.
//
// Here and nowhere else: by the time the first Stop fires, the turn has
// already run, and anything it committed would sit inside the baseline that is
// supposed to expose it.
//
// Silent in two of the three cases, which is _record_base's decision
// (session_start.py:43-59). Without a session id there is nowhere to file it,
// and outside a repository there is nothing to file -- neither is a defect of
// the project, and neither is worth a line in every session of every checkout
// that is not a git repository. The stop gate is where the absence matters,
// and that is where it is said out loud.
//
// A write that fails is the third case and it is *not* silent, because the
// Python original is not silent about it either: state.py's `write`
// (state.py:56-65) catches nothing, so an OSError there leaves `run` by
// itself. Swallowing it here would be a departure dressed up as parity.
func recordBase(sessionID, root string) error {
	if sessionID == "" {
		// hostio.Read hands a missing id and a wrongly typed one over as the
		// empty string alike -- the type assertion at
		// internal/hostio/claude.go:60, and its reasoning at :31-37. That is
		// the `isinstance(session_id, str)` test of session_start.py:52 with the
		// one divergence that a literal `"session_id": ""` files nothing here
		// while Python files it under `unnamed` (state.py:75).
		return nil
	}
	commit, err := gitwork.HeadCommit(root)
	if err != nil {
		return nil
	}
	state := sessions.ReadState(root, sessionID)
	state.Base = commit
	return sessions.WriteState(root, sessionID, state)
}

// waiting is one line per paused run, in run order.
func waiting(root string, stderr io.Writer) []string {
	dir := filepath.Join(root, filepath.FromSlash(runDir))
	entries, err := os.ReadDir(dir)
	if err != nil {
		// An absent runs directory means no runs, which is what
		// session_start.py:65 answers to the same question. Every other
		// failure to list the directory answers the same way, one step wider
		// than Python's `is_dir()`: a project whose journals cannot be read is
		// not a project with an open question to announce, and this hook has
		// no verdict to give either way.
		return nil
	}
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		if !entry.IsDir() && strings.HasSuffix(entry.Name(), ".jsonl") {
			names = append(names, entry.Name())
		}
	}
	// By name, as session_start.py:69's `sorted(directory.glob(...))` is: two
	// runs reported in directory order would read differently on two machines.
	sort.Strings(names)

	var lines []string
	for _, name := range names {
		path := filepath.Join(dir, name)
		gate, err := journal.Pending(path)
		if err != nil {
			// Named, not swallowed, and not fatal either: one damaged file is
			// a finding of its own, and hiding the other runs behind it would
			// turn a small defect into a silent one. session_start.py:74-78
			// says the same in the same place.
			fmt.Fprintf(stderr, "ulguard hook session-start: %v\n", err)
			continue
		}
		if gate == nil {
			continue
		}
		runID := strings.TrimSuffix(name, ".jsonl")
		// ASCII down to the placeholder, because session_start.py:86-89 words
		// it that way and both hooks run side by side until the Python one
		// goes. Its reason does not carry over: `print` there raises
		// UnicodeEncodeError on a cp1252 console, while json.Encoder here
		// writes UTF-8 and reports nothing. So this wording is parity and not
		// a safeguard.
		lines = append(lines, fmt.Sprintf(
			"run %s is waiting at %s: %s\n  answer it with: ultraloom resume %s --answer \"your answer\"",
			runID, gate.Node, gate.Question, runID))
	}
	return lines
}
