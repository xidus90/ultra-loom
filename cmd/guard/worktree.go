// The worktree side of the guard: what a working tree cannot own itself.
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/xidus90/ultra-loom/internal/junction"
	"github.com/xidus90/ultra-loom/internal/mirrorcfg"
	"github.com/xidus90/ultra-loom/internal/sessions"
	"github.com/xidus90/ultra-loom/internal/worktreetopo"
)

// The two prefixes a stored reparse target can start with. `\??\` is the NT
// object-manager form, it is not a path Go opens, and it is the only one
// measured here: on 2026-09-07 both junction.Create and `mklink /J` stored
// it. `\\?\` is taken off as well so that both forms compare alike -- and not
// because anything here was seen to store it. Neither prefix identifies
// anything: the reparse tag does that, and junction.Target has checked it.
var ntPrefixes = []string{`\??\`, `\\?\`}

// runWorktreeLink puts the configured directories in place and sweeps what is
// left of gone worktrees.
//
// Silent on success, because it runs at every session start in every project
// on the machine. The only thing it reports is a junction that was needed and
// could not be made -- and that one it reports loudly, since the directory it
// stands for may be the pinned runtime every other hook needs.
//
// stdout is taken and not written to: every answer this subcommand has is
// either silence or a fault, and a fault belongs on stderr.
func runWorktreeLink(stdout, stderr io.Writer, root string) int {
	topology, err := worktreetopo.Read(root)
	if err != nil {
		// Every failure of that call is the same answer, and the answer is
		// "nothing to do": worktreetopo.Read wraps ErrNoRepository around each
		// of its two error returns rather than telling a broken git from an
		// unrepositoried directory. Distinguishing them here would be a branch
		// nothing can enter.
		return ExitOK
	}
	mirror, err := mirrorcfg.Mirror(topology.Main)
	if err != nil {
		fmt.Fprintf(stderr, "ultraloom-guard worktree-link: %v\n", err)
		return ExitInternal
	}
	if len(mirror) == 0 {
		return ExitOK
	}

	code := ExitOK
	if topology.IsWorktree(root) {
		if err := link(root, topology.Main, mirror); err != nil {
			fmt.Fprintf(stderr, "ultraloom-guard worktree-link: %v\n", err)
			code = ExitInternal
		}
	}
	// The sweep runs whether or not this directory is a worktree: a session in
	// the main checkout is the ordinary way to notice that a worktree is gone.
	if err := sweep(topology, mirror); err != nil {
		fmt.Fprintf(stderr, "ultraloom-guard worktree-link: %v\n", err)
		code = ExitInternal
	}
	return code
}

// How long a session's state file counts for. Nothing deletes these files, so
// the mtime is the only liveness there is to read, and it is only as good as
// the writes: session_start.py writes the file at session start and stop.py
// rewrites it on every block and every pass, so in a project with the stop
// gate switched on the file is as young as the last turn that ended, and in
// one without it as old as the session itself.
//
// Twelve hours is the trade that follows. Shorter would take a junction out
// from under a long session in a project without the stop gate; longer would
// let yesterday's abandoned session keep one for another day.
const sessionStale = 12 * time.Hour

// runWorktreeUnlink takes the junctions back out -- but only if this was the
// last session on the tree.
//
// CLAUDE.md documents sessions that share a checkout. Unlinking
// unconditionally would pull `.tools` out from under a session still running,
// or under an open Godot editor, and the 4.2 GB behind it is exactly what that
// editor is reading from.
//
// stdout is taken and not written to, for worktree-link's reason: every answer
// this subcommand has is either silence or a fault.
func runWorktreeUnlink(stdout, stderr io.Writer, stdin io.Reader, root string) int {
	var payload struct {
		SessionID string `json:"session_id"`
	}
	// A payload we cannot read is not a reason to remove anything: without an
	// id there is no way to tell our own state file from somebody else's, so
	// the count would always say "somebody else is here" -- and Forget would
	// be worse than useless, since safeName turns an empty id into "unnamed"
	// and that may be the collapsed name of a session that is still running.
	if err := json.NewDecoder(stdin).Decode(&payload); err != nil || payload.SessionID == "" {
		return ExitOK
	}

	topology, err := worktreetopo.Read(root)
	if err != nil {
		// Nothing to do, and the same collapse worktree-link makes: Read wraps
		// ErrNoRepository around each of its two error returns, so telling them
		// apart here would be a branch nothing can enter.
		return ExitOK
	}
	if !topology.IsWorktree(root) {
		return ExitOK
	}
	mirror, err := mirrorcfg.Mirror(topology.Main)
	if err != nil {
		fmt.Fprintf(stderr, "ultraloom-guard worktree-unlink: %v\n", err)
		return ExitInternal
	}
	if len(mirror) == 0 {
		return ExitOK
	}

	// Our own file goes before the count and before the early return below: it
	// has to be gone whether or not this was the last session, or the next run
	// finds it and reads a session that has ended as one still standing.
	if err := sessions.Forget(root, payload.SessionID); err != nil {
		fmt.Fprintf(stderr, "ultraloom-guard worktree-unlink: %v\n", err)
		return ExitInternal
	}
	others, err := sessions.Others(root, payload.SessionID, sessionStale)
	if err != nil {
		fmt.Fprintf(stderr, "ultraloom-guard worktree-unlink: %v\n", err)
		return ExitInternal
	}
	if others > 0 {
		return ExitOK
	}
	if err := unlink(root, topology.Main, mirror); err != nil {
		fmt.Fprintf(stderr, "ultraloom-guard worktree-unlink: %v\n", err)
		return ExitInternal
	}
	return ExitOK
}

// unlink removes the configured junctions from one worktree.
//
// A configured path that is a real directory is left alone: it was never ours.
// The target is checked as well -- a junction pointing somewhere else is
// somebody's own arrangement, and removing it would be the same overreach as
// removing a real directory.
//
// standsInside first, for the reason written at that function: without it the
// candidate is inside the worktree by spelling only, and a junction at
// `<worktree>/.ultraloom` would make this remove the main checkout's own
// `.ultraloom/vendor` -- the pinned runtime every other hook needs, taken out
// at session end by the mechanism that exists to put it there.
func unlink(worktree, main string, mirror []string) error {
	for _, relative := range mirror {
		if !standsInside(worktree, relative) {
			continue
		}
		path := filepath.Join(worktree, filepath.FromSlash(relative))
		target, err := junction.Target(path)
		if err != nil {
			return err
		}
		if target == "" || !leadsInto(target, main) {
			continue
		}
		if err := junction.Remove(path); err != nil {
			return err
		}
	}
	return nil
}

// link makes every configured path in `worktree` lead into `main`.
//
// A path the worktree already owns is left alone, and so is one the main
// checkout does not have: the first may be this tree's own build output, and
// the second is nothing to mirror. Only an *absent* path here is ours to fill.
//
// An Lstat that fails for some other reason than absence is not caught, and
// the property that makes that safe is where such a path ends up: it goes on
// to junction.Create, whose os.Mkdir fails on it, so it is a reported fault
// and never a silent skip. Measured on 2026-09-07 with a worktree that may
// not gain a subdirectory -- os.Lstat of the absent child still answers
// IsNotExist there, and the Mkdir inside Create is what refuses. Mkdir
// refusing an occupied path is the same property from the other side: it is
// why nothing here can overwrite what already stands at the path.
func link(worktree, main string, mirror []string) error {
	for _, relative := range mirror {
		target := filepath.Join(main, filepath.FromSlash(relative))
		if info, err := os.Stat(target); err != nil || !info.IsDir() {
			continue
		}
		path := filepath.Join(worktree, filepath.FromSlash(relative))
		if _, err := os.Lstat(path); err == nil {
			continue
		}
		// The parent may be missing: a configured path can be more than one
		// level deep, and only its first level is necessarily something git
		// brought along.
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			return fmt.Errorf("making room for %s: %w", path, err)
		}
		if err := junction.Create(path, target); err != nil {
			return fmt.Errorf("%s: %w", relative, err)
		}
	}
	return nil
}

// sweep removes our junctions from directories git no longer holds.
//
// What makes a junction ours is where it is and what it points at: a reparse
// point at a configured path inside an unregistered worktree directory,
// leading into the main checkout. All three conditions are load-bearing.
// CLAUDE.md records directories under `.claude/worktrees/` that share the main
// index and are not worktrees, so Orphans names live work as well -- a real
// directory there is somebody's data, and a junction pointing anywhere else is
// somebody's own arrangement.
//
// No ledger -- a list of junctions we made would be a second state that can
// drift, and after a `Remove-Item -Recurse` on a worktree it would be wrong
// immediately. The price is that the hand-made junctions in this repository's
// worktrees are adopted, which is right: they are indistinguishable from ours
// by target and place, and they were made for the same reason.
func sweep(topology worktreetopo.Topology, mirror []string) error {
	orphans, err := topology.Orphans()
	if err != nil {
		return err
	}
	for _, orphan := range orphans {
		for _, relative := range mirror {
			if !standsInside(orphan, relative) {
				continue
			}
			path := filepath.Join(orphan, filepath.FromSlash(relative))
			target, err := junction.Target(path)
			if err != nil {
				return err
			}
			if target == "" {
				// Not a link: somebody's directory, and none of our business.
				continue
			}
			if !leadsInto(target, topology.Main) {
				continue
			}
			if err := junction.Remove(path); err != nil {
				return err
			}
		}
	}
	return nil
}

// standsInside says whether a configured path really lies where its spelling
// says: every component between the orphan and the candidate itself a plain
// directory, and none of them a link.
//
// Without this the sweep establishes "inside the orphan" by spelling alone,
// and a path's spelling does not decide where it goes: an open with
// FILE_FLAG_OPEN_REPARSE_POINT keeps the *final* component from being
// followed and nothing else, so a junction at `<orphan>/.ultraloom` makes
// `<orphan>/.ultraloom/vendor` read and remove the reparse point of
// `<main>/.ultraloom/vendor` -- the pinned runtime, taken out by the very
// mechanism that exists to put it there.
//
// Mode().IsDir() is the test, and it is false for a junction under both
// GODEBUG settings this module can be built with; the measurement behind that
// is recorded at junction.go's Target. The last component is left out because
// junction.Target is what decides about that one, and being a link is exactly
// what qualifies it.
//
// A component that cannot be stat'ed counts as not a plain directory. The safe
// direction is to leave a candidate alone: a junction skipped costs a stale
// directory nobody deletes, and the other way costs somebody's data.
func standsInside(orphan, relative string) bool {
	// mirrorcfg hands out cleaned, slash-separated paths, so this split has no
	// empty component and no trailing one.
	components := strings.Split(relative, "/")
	path := orphan
	for _, component := range components[:len(components)-1] {
		path = filepath.Join(path, component)
		info, err := os.Lstat(path)
		if err != nil || !info.Mode().IsDir() {
			return false
		}
	}
	return true
}

// leadsInto says whether a link target sits inside the main checkout.
//
// The comparison is by what the two paths open and never by how they are
// spelled. A stored target's trailing separator depends on who made the
// junction -- measured on 2026-09-07, junction.Create writes `\??\C:\dir\` and
// `mklink /J` writes `\??\C:\dir`, and both resolve -- so a text comparison
// against an absolute path would miss exactly the hand-made links this
// repository's worktrees already carry.
//
// Walking up rather than testing the directory itself, because a configured
// path is a path and not only a name: `.ultraloom/vendor` names a target two
// levels below the main checkout.
func leadsInto(target, main string) bool {
	for path := stripNTPrefix(target); ; path = filepath.Dir(path) {
		if sameDir(path, main) {
			return true
		}
		if parent := filepath.Dir(path); parent == path {
			return false
		}
	}
}

// stripNTPrefix turns a stored reparse target into a path Go can stat.
//
// One of the two prefixes comes off if it is there, and a target carrying
// neither passes through untouched -- junction.Target promises the substitute
// name as the filesystem stored it and nothing about which form that is. The
// Clean is what takes the trailing separator off, so no caller has to know
// whether one was stored.
func stripNTPrefix(target string) string {
	for _, prefix := range ntPrefixes {
		if rest, found := strings.CutPrefix(target, prefix); found {
			return filepath.Clean(rest)
		}
	}
	return filepath.Clean(target)
}

// sameDir compares two paths by what they open, not by how they are spelled.
// A path that cannot be stat'ed is not the directory in question: os.Stat
// fails on "" as it does on anything else absent, so nothing here needs a
// guard against the empty string.
func sameDir(a, b string) bool {
	left, err := os.Stat(a)
	if err != nil {
		return false
	}
	right, err := os.Stat(b)
	if err != nil {
		return false
	}
	return os.SameFile(left, right)
}
