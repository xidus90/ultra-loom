// Package write decides first and writes second.
//
// The split is what makes --dry-run honest: Prepare answers "what would
// change?" by reading only, and Commit is the same answer applied. Nothing
// Commit does can change an answer Prepare gave, because every decision was
// taken before the first byte landed.
//
// It does not make the write a transaction. A failure on the third file
// leaves the first two on disk, and this package offers no undo. What it
// does guarantee is that init only ever adds: anything already standing under
// a name -- file, directory, symlink, even one pointing nowhere -- is skipped,
// and Commit refuses rather than overwrites whatever is there when it arrives.
// Whatever a failed run leaves behind, none of it is somebody else's content.
package write

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Plan is what Prepare decided, in the same slash-separated names the
// renderer used: Create maps each new file to its body, Skip names the files
// left alone.
//
// A dry-run summary prints both halves, and two runs over an unchanged
// project should read alike, so both halves come with an order: Skip is
// sorted, and Names gives the sorted Create keys. Ranging over Create
// directly gives a different order every time -- use Names.
type Plan struct {
	Create map[string]string
	Skip   []string
}

// Names is the order Commit works in, so what a caller printed beforehand and
// what a failed run left behind line up.
func (p Plan) Names() []string {
	names := make([]string, 0, len(p.Create))
	for name := range p.Create {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// Prepare sorts the rendered files into those that would be written and those
// that already exist. It touches nothing.
func Prepare(root string, files map[string]string) (Plan, error) {
	plan := Plan{Create: map[string]string{}}
	for name, body := range files {
		if err := checkName(name); err != nil {
			return Plan{}, err
		}
		full := filepath.Join(root, filepath.FromSlash(name))
		// Lstat, not Stat: a symlink pointing nowhere is still somebody's
		// property. Stat would follow it, report "not found" and put the name
		// up for creation, and the exclusive create would then fail on a link
		// that had been there all along. Anything present under the name is
		// something this run did not put there.
		switch _, err := os.Lstat(full); {
		case err == nil:
			plan.Skip = append(plan.Skip, name)
		case os.IsNotExist(err):
			plan.Create[name] = body
		default:
			return Plan{}, fmt.Errorf("looking at %s: %w", name, err)
		}
	}
	sort.Strings(plan.Skip)
	return plan, nil
}

// checkName refuses anything that could land outside root. The renderer is
// the only caller today, but a tool that writes into a stranger's project
// earns its trust by not needing any: a name that escapes is a bug wherever
// it came from, and the safe answer to a bug is to stop.
func checkName(name string) error {
	// fs.ValidPath is the slash-world rule: no empty name, no leading slash,
	// no "." or ".." element, no doubled or trailing separator.
	if !fs.ValidPath(name) || name == "." {
		return fmt.Errorf("refusing the file name %q: it is not a relative path inside the project", name)
	}
	// Windows reads two more characters as structure that fs.ValidPath, which
	// knows only slashes, hands through as ordinary letters: a backslash
	// separates, and a colon opens a drive or an alternate data stream.
	if strings.ContainsAny(name, `\:`) {
		return fmt.Errorf("refusing the file name %q: it contains a separator or a drive letter", name)
	}
	return nil
}

// Commit writes the files Prepare chose. A Plan can also be built by hand, so
// the names are checked again here: the promise not to write outside root
// belongs to the package, not to one of its two entry points.
func Commit(root string, plan Plan) error {
	for _, name := range plan.Names() {
		if err := checkName(name); err != nil {
			return err
		}
		full := filepath.Join(root, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
			return fmt.Errorf("creating the directory for %s: %w", name, err)
		}
		if err := writeNew(full, plan.Create[name]); err != nil {
			return commitFailure(name, err)
		}
	}
	return nil
}

// commitFailure tells the two ways a planned file can fail to appear apart.
// A refusal is the package working as designed and reads as such; anything
// else is the disk saying no. Callers are owed that distinction by name --
// one is a project to leave alone, the other is a run to retry.
func commitFailure(name string, err error) error {
	if errors.Is(err, fs.ErrExist) {
		// Worded so it cannot be wrong: the plan listed the name as new, and
		// the disk disagrees. Who put it there and when is not knowable here.
		return fmt.Errorf("refusing to overwrite %s: the plan had it as new, but it exists: %w", name, err)
	}
	return fmt.Errorf("writing %s: %w", name, err)
}

// writeNew creates a file that must not exist yet. O_EXCL is the skip
// decision enforced at the last moment: between Prepare and here somebody may
// have created the file, and this run has no claim on what they wrote.
func writeNew(full, body string) error {
	f, err := os.OpenFile(full, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if err != nil {
		return err
	}
	_, werr := f.WriteString(body)
	return errors.Join(werr, f.Close())
}
