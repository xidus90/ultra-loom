// Package junction makes one directory point at another on Windows.
//
// A junction and not a symlink: `os.Symlink` creates a symbolic link, which
// needs a privilege or Developer Mode, and `ln -s` under MSYS silently copies
// instead -- that mistake cost 3.7 GB of Godot editor once. A junction needs
// no privilege and is what the hand-made links in this repository's worktrees
// already are.
package junction

import (
	"errors"
	"fmt"
	"os"
)

// ErrUnsupported is the answer everywhere but Windows. Named rather than
// generic, so a caller can tell "cannot here" from "went wrong".
var ErrUnsupported = errors.New("junctions exist only on windows")

// Target is the directory `link` points at, or "" when it points at nothing.
//
// A path that is not a link, and a path that is not there at all, are both the
// empty answer with no error: the sweep asks this about every candidate it
// scans, and neither case is a fault. Anything else is a fault and says so.
//
// The answer is the target as Windows stores it, `\??\C:\dir\` and not the
// path a caller could open: normalising it here would throw away the one form
// that says for certain which reparse point this is, and a caller that wants
// to open it strips the prefix itself.
//
// The reparse-point ioctl and not `os.Lstat` plus `os.Readlink`, measured on
// 2026-09-07 with go1.27.0 windows/amd64: by default Lstat reports a junction
// as `Lrw-rw-rw-` and Readlink answers it, but under
// `GODEBUG=winsymlink=1,winreadlinkvolume=1` -- which is the default for every
// `go` directive from 1.23 on -- the mode is `?rw-rw-rw-` instead:
// ModeIrregular, no ModeSymlink. That path would answer "" for a real
// junction, which is not an error a caller could notice; bumping this module's
// `go 1.22` line would silently turn the sweep blind. Widening the test to
// ModeIrregular is no answer either, since it covers every other reparse tag
// as well and Readlink faults on those.
func Target(link string) (string, error) {
	if _, err := os.Lstat(link); err != nil {
		if os.IsNotExist(err) {
			return "", nil
		}
		return "", fmt.Errorf("inspecting %s: %w", link, err)
	}
	return reparseTarget(link)
}

// Remove takes the link and never what it points at.
//
// `os.Remove` and not `os.RemoveAll`: on a reparse point the first removes the
// point itself, and the second is the call that would walk into 4.2 GB of
// somebody else's directory. Measured on 2026-09-07 for the three ordinary
// delete paths -- none of them reached through the junction -- and this is the
// one place in ultraloom's own code that could.
func Remove(link string) error {
	target, err := Target(link)
	if err != nil {
		return err
	}
	if target == "" {
		return fmt.Errorf("%s is not a link; refusing to remove it", link)
	}
	if err := os.Remove(link); err != nil {
		return fmt.Errorf("removing the link %s: %w", link, err)
	}
	return nil
}
