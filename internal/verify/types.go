package verify

import (
	"errors"
	"io/fs"
	"strings"
)

// Run is what one command said: the exit status apart from the two streams,
// because the verdict is in the status and the reason for it is in stderr.
type Run struct {
	ExitCode int
	Stdout   string
	Stderr   string
}

// Runner starts one command and reports what it said. A function and not an
// interface: there is one operation, and a test wants to hand over a closure.
type Runner func(argv ...string) Run

// What dmypy prints when its status file describes a daemon that is not there,
// read out of mypy's own source rather than out of a session's scrollback.
//
// Only the third one is reachable through `dmypy run`, measured on 2026-09-10:
// do_run asks is_running() first, and that swallows every BadStatus and starts
// a fresh daemon -- a status file naming a dead pid heals itself, printing
// "Daemon started". The failure that takes the lane down is the other shape: a
// pid that is alive and a pipe that is gone. is_running says yes, and request()
// then raises IPCException from mypy/ipc.py.
//
// The first two stay because they belong to the same condition, arrive the same
// way for the other dmypy actions, and cost a string comparison. They are not
// what this was built for.
//
// All three are Windows text, and the third one is Windows-only by
// construction: mypy/ipc.py raises it from inside `if sys.platform ==
// "win32"`. On POSIX the same IPC is an AF_UNIX socket and connect() raises a
// bare FileNotFoundError, which mypy's main() catches as any other exception --
// traceback printed, exit 2, none of these strings in it. So the heal does not
// fire on POSIX, and it is not repaired by guessing: the marker there would be
// a traceback's last line, and nothing on this machine can run the branch to
// find out which. Recorded rather than invented; the same gap this repository
// already tracks for process.py's POSIX arm.
var daemonGone = []string{
	"Daemon has died",
	"Invalid status file",
	"was not found.",
}

// StaleDaemon says whether a failed run is about the daemon rather than about
// the code.
//
// Both conditions are needed. dmypy hands mypy's own status through for a
// verdict and reaches exit 2 only from fail(), so no ordinary type error can
// arrive here -- but 2 is also mypy's code for a blocking error, and that is a
// finding about the code which a restart must not swallow. The marker is what
// tells those two apart.
func StaleDaemon(result Run) bool {
	if result.ExitCode != 2 {
		return false
	}
	for _, marker := range daemonGone {
		if strings.Contains(result.Stderr, marker) {
			return true
		}
	}
	return false
}

// CheckTypes runs dmypy and, when its daemon turns out to be gone, clears the
// state that says otherwise and runs it once more.
//
// Once, not until it works: a second failure of the same shape is a fault this
// cannot repair, and a loop would buy a cold start per round to hide it.
//
// It does not kill anything first, and that is the whole point of the shape
// this has. `dmypy kill` was in here and was measured out on 2026-09-10: the
// pid in a stale status file is by definition a live process -- that is why
// is_running was fooled -- and it is almost never the daemon, it is whoever
// the operating system handed the recycled number to. On Windows dmypy kills
// through `taskkill /pid <n> /f /t`, so the run took an unrelated process and
// its whole tree with it; the test that proved it started a sleeping shell and
// found it gone afterwards. It also never helped: on 2026-09-10 `dmypy kill`
// reported success and the next run died all the same. Removing the file is
// the step that works, and `dmypy run` starts its own daemon after it.
//
// A status file that is already gone is the state this wants, not a failure.
// Any other removal error ends the attempt: without the removal a retry would
// meet the same stale state and cost a full run to learn nothing.
func CheckTypes(run Runner, remove func(string) error, statusFile string, mypyArgs []string) (Run, string) {
	argv := append([]string{"uv", "run", "dmypy", "--status-file", statusFile, "run", "--"}, mypyArgs...)
	first := run(argv...)
	if !StaleDaemon(first) {
		return first, ""
	}
	if err := remove(statusFile); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return first, "the dmypy daemon was gone and " + statusFile + " could not be removed: " + err.Error()
	}
	return run(argv...), "the dmypy daemon was gone; removed " + statusFile + " and ran the check again"
}
