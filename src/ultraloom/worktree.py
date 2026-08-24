"""What git says has changed below a directory.

Its own module because two callers need the *same* answer: the CLI takes a
run's baseline when the run starts, and the verify flow's guard reads the tree
again after a repair pass. A second implementation of the same git call would
drift in exactly the parsing details this file exists for, and the two answers
would then be compared against each other.

Below the harness on purpose: it raises its own error and knows nothing about
flows, exit codes or runs, so `ultraloom check` may import it (spec 15.2).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Where a run keeps its journal and its marker. Defined here and not in the CLI
# that writes them: this module has to know what to leave out of its answer, and
# it sits below the CLI, so the constant travels the other way round.
RUN_DIR = ".ultraloom/runs"


class WorktreeError(RuntimeError):
    """Raised when git cannot answer what changed. Never read as "nothing"."""


def changed_files(root: Path) -> tuple[str, ...]:
    """Every path git reports as changed, added or untracked below `root`.

    `status` and not `diff`, because a repairer may add a file, and an
    untracked file is invisible to `diff`. `-z` because a path holding
    non-ASCII comes back quoted otherwise, and `-uall` because the default
    collapses a whole untracked directory into one entry that is not a path to
    any file.

    Paths come back relative to `root`, which is not what git says: porcelain
    output is relative to the *repository* root whatever the working directory
    is, and there is no porcelain option that changes it. Where the two are the
    same directory the difference is invisible, which is why it went unnoticed
    -- but in a monorepo run with `--root package`, git answers
    "package/tests/test_x.py" while the project's own `[verify].tests` says
    "tests/", nothing a caller configured ever matches, and a guard built on
    this answer is silently off. Anything outside `root` is dropped for the
    same reason: it is not this project's change.

    A root git *ignores* is refused rather than answered. Such a directory is
    still inside the repository, so every call here succeeds and the arithmetic
    below is right -- but `status` never lists an ignored file, so the answer
    is empty however much changed. A copy of a project parked below an ignored
    path is the ordinary way to end up there, and read as "nothing changed" it
    switches the guard off while every run keeps reporting success.

    What `RUN_DIR` holds is dropped as well, and for a reason of its own: those
    files are ultraloom's, not the project's. Every run writes its journal and
    its marker while the repair agent works, so a guard reading this answer
    would report them as the agent's doing -- and a project that lists
    `.ultraloom/` among its protected paths would take exit 4 on every single
    run, named after files ultraloom wrote itself. The rest of `.ultraloom/`
    stays visible: `config.toml` holds the thresholds a check is measured
    against, and an agent editing that one is exactly what the guard is for.
    """
    # Before the question rather than after the answer: an ignored root is
    # wrong whatever comes back, and a change *elsewhere* in the repository
    # would otherwise carry the call past this point and be dropped by the
    # relocation below -- an empty answer again, and this time an unchecked one.
    _refuse_if_ignored(root)
    return _relocate(root, _parse_status(_status(root)))


def _relocate(root: Path, paths: tuple[str, ...]) -> tuple[str, ...]:
    """Repository-relative paths as a caller below `root` spells them.

    Anything outside `root` is dropped -- it is not this project's change --
    and so is everything below `RUN_DIR`, which is ultraloom's own doing and
    never the repairer's. Both callers go through here, because two spellings
    of the same path would end up being compared against each other.
    """
    if not paths:
        # Nothing to relocate, so the second git call is not worth its process.
        return paths
    prefix = _prefix(root)
    if prefix:
        paths = tuple(path[len(prefix) :] for path in paths if path.startswith(prefix))
    # After the relocation, so the comparison is against the spelling a caller
    # below `root` would use rather than the repository-relative one.
    return tuple(path for path in paths if not path.startswith(RUN_DIR + "/"))


def changed_since(root: Path, base: str) -> tuple[str, ...]:
    """Every path that differs between `base` and the working tree, below `root`.

    The union of two questions, because neither answers alone: `diff` sees what
    was committed since `base` but is blind to an untracked file, and `status`
    sees the untracked file but reads a committed change as a clean tree. That
    second blindness is why this function exists -- a repairer that commits its
    edit leaves `status` with nothing to report, and the guard built on it then
    lets an edited test file through.

    `--no-renames`, so a rename comes back as its old *and* its new path. Git
    would otherwise report the pair as one entry, and a test moved out of the
    way would be a path the guard never compares against its protected list.

    Content-based, so a `reset`, a `rebase` or an `amend` hides nothing: this
    compares the tree of `base` against the tree on disk, not two histories.

    An unresolvable `base` is a `WorktreeError` and never an empty answer, for
    the reason every refusal in this module has: a question git cannot answer
    must not be read as "nothing changed".
    """
    _refuse_if_ignored(root)
    diff = _git(root, "diff", "--name-only", "--no-renames", base)
    committed = tuple(line for line in diff.splitlines() if line)
    reported = _parse_status(_status(root))
    # One call over both answers rather than one per answer: `_relocate` asks
    # git for the prefix, and that process is the same for either spelling.
    return tuple(sorted(set(_relocate(root, committed + reported))))


def head_commit(root: Path) -> str:
    """The commit a run starts on, as git spells it.

    `rev-parse HEAD` and not `--short`: the answer travels in a run marker and
    is read back rounds later, and an abbreviated SHA is only unique for as
    long as the repository stays the size it was.

    Three ways of having no answer, all of them `WorktreeError`: no repository,
    a repository without a commit -- `git init` leaves HEAD naming a branch
    that does not exist yet -- and a root git ignores. The last one is why
    `_refuse_if_ignored` is asked here at all: such a directory *is* inside a
    repository, so `rev-parse` answers readily with the surrounding
    repository's HEAD. Measuring against that is worse than not measuring, as
    every file of the parked copy then reads as the repairer's doing.
    """
    _refuse_if_ignored(root)
    return _git(root, "rev-parse", "HEAD").strip()


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """One git call below `root`, for the callers that read the return code."""
    try:
        return subprocess.run(
            ("git", *arguments),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as error:
        # A directory that is not there never reaches a return code: the spawn
        # itself fails. Same answer as a non-zero one -- see `_git`.
        raise WorktreeError(f"cannot inspect the working tree in {root}: {error}") from error


def _refuse_if_ignored(root: Path) -> None:
    """Refuse a root git answers about but never answers with.

    `check-ignore` exits 1 for a path it does not ignore, which is the ordinary
    case and no failure at all -- so this call reads the return code itself
    rather than going through `_git`. Every other code is read as "not
    ignored" on purpose: the calls that follow refuse a directory git cannot
    answer about anyway, and turning the difference between exit 1 and exit 128
    into a second way of failing here would only make that refusal less clear.
    """
    if _run(root, "check-ignore", "-q", ".").returncode == 0:
        raise WorktreeError(
            f"git ignores {root}, so it can never report a change there -- "
            "run ultraloom in a working tree of its own"
        )


def _git(root: Path, *arguments: str) -> str:
    """One git call below `root`, with both ways of having no answer refused."""
    result = _run(root, *arguments)
    if result.returncode != 0:
        # A caller that cannot see the working tree must not carry on as if it
        # had seen an empty one. Reading an unanswerable question as "nothing
        # changed" would disable exactly the rules this answer feeds.
        raise WorktreeError(f"cannot inspect the working tree in {root}: {result.stderr.strip()}")
    return result.stdout


def _status(root: Path) -> str:
    return _git(root, "status", "--porcelain", "-z", "-uall")


def _prefix(root: Path) -> str:
    """How deep `root` sits below the repository root, as git spells it.

    Empty when the two are the same directory, and always slash-terminated
    otherwise -- so it is exactly the string to cut off the front of a
    repository-relative path.
    """
    return _git(root, "rev-parse", "--show-prefix").strip()


def _parse_status(output: str) -> tuple[str, ...]:
    """The paths out of a `--porcelain -z` answer, read field by field.

    Most fields are "XY path". A rename or a copy is the exception: git emits
    *two* fields for it, and only the first carries the three-character prefix
    -- the second is the original path, bare. Cutting three characters off that
    one too would turn "tests/test_cli.py" into "s/test_cli.py", and a test
    renamed out of the way would walk straight past the guard.
    """
    fields = [field for field in output.split("\0") if field]
    paths: list[str] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        paths.append(field[3:])
        index += 1
        if field[:1] in ("R", "C") and index < len(fields):
            paths.append(fields[index])
            index += 1
    return tuple(paths)
