// The worktree side of the guard: what a working tree cannot own itself.
package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/xidus90/ultra-loom/internal/junction"
	"github.com/xidus90/ultra-loom/internal/mirrorcfg"
	"github.com/xidus90/ultra-loom/internal/worktreetopo"
)

// The two prefixes a stored reparse target can start with. `\??\` is the NT
// object-manager form, and it is the only one measured here: on 2026-09-07
// both junction.Create and `mklink /J` stored it. `\\?\` is taken off as well
// because the two forms are written the same way round and stripping a prefix
// that never appears costs nothing -- not because anything here was seen to
// store it. Neither is part of a path a Go call opens, and neither identifies
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

// link makes every configured path in `worktree` lead into `main`.
//
// A path the worktree already owns is left alone, and so is one the main
// checkout does not have: the first may be this tree's own build output, and
// the second is nothing to mirror. Only an *absent* path here is ours to fill.
//
// An Lstat that fails for some other reason than absence is not caught: the
// path goes on to junction.Create, and its os.Mkdir is what fails instead, so
// such a path still ends as a reported fault and never as a silent skip.
// Measured on 2026-09-07 for the two ways to arrange it: a configured name
// Windows will not spell (`bad?name`) and a worktree that may not gain a
// subdirectory both come back from that Mkdir as an error. Mkdir refusing an
// occupied path is the same property from the other side -- it is why nothing
// here can overwrite what already stands at the path.
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
