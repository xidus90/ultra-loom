"""What a subagent changed, whether or not its report says so.

The incident in CLAUDE.md had this shape: an implementer subagent pushed
`master` to `origin`, and its report did not mention it. So this hook compares
the remote's refs and the local HEAD against a snapshot taken when the subagent
started, and names every difference.

Never exit 2. By the time this runs the push has happened; stopping the
subagent from stopping does not undo it. The value is in being told, and being
told needs no blocking.
"""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from ultraloom import process
from ultraloom.hooks.payload import EXIT_INTERNAL, EXIT_OK, PayloadError
from ultraloom.hooks.payload import read as read_payload
from ultraloom.hooks.state import read as read_state

# A remote that does not answer must not hold a subagent's exit open. Ten
# seconds is long for `ls-remote` against a reachable host and short enough
# that a dead one costs nothing anybody notices.
TIMEOUT = 10.0

# Marks the local HEAD inside a snapshot. Everything without it is a remote
# ref, which keeps an older snapshot -- remote refs and nothing more -- a
# snapshot that still compares, just with less to say.
_HEAD_MARKER = "HEAD\t"


def remote_refs(root: Path) -> str:
    """What `origin` currently points at, or an empty string.

    Every failure -- no remote, no network, a timeout, no git at all -- is an
    empty string rather than a raise: an unreachable remote is a fact about
    the machine, not a finding about the subagent.
    """
    completed = _git(root, "ls-remote", "origin")
    return "" if completed is None else completed


def head(root: Path) -> str:
    """The commit HEAD points at, or an empty string outside a repository."""
    completed = _git(root, "rev-parse", "HEAD")
    return "" if completed is None else completed.strip()


def snapshot(root: Path) -> str:
    """Where the remote and the local HEAD stood, as one storable string."""
    where = head(root)
    return remote_refs(root) + (f"{_HEAD_MARKER}{where}\n" if where else "")


def differences(before: str, after: str) -> tuple[str, ...]:
    """Every ref that moved, appeared, or vanished, in that order of reading.

    Both directions: a branch deleted on the remote is as much a push as a
    branch created there, and a comparison that only looked for new lines
    would report the deletion as nothing at all.
    """
    old, new = _refs(before), _refs(after)
    lines: list[str] = []
    for ref in sorted(set(old) | set(new)):
        was, now = old.get(ref), new.get(ref)
        if was == now:
            continue
        if was is None:
            lines.append(f"origin {ref} is new at {now}")
        elif now is None:
            lines.append(f"origin {ref} is gone; it was {was}")
        else:
            lines.append(f"origin {ref} moved {was} -> {now}")
    return tuple(lines)


def new_commits(root: Path, since: str) -> tuple[str, ...]:
    """The commits HEAD gained since that commit, one short line each."""
    listed = _git(root, "log", "--oneline", f"{since}..HEAD")
    if listed is None:
        return ()
    return tuple(line for line in listed.splitlines() if line)


def run(stdin: TextIO, root: Path, stdout: TextIO, stderr: TextIO) -> int:
    """Report what changed under this subagent. Never blocks."""
    try:
        payload = read_payload(stdin)
    except PayloadError as error:
        print(f"ultraloom hook subagent-stop: {error}", file=stderr)
        return EXIT_INTERNAL

    agent_id = payload.get("agent_id")
    session_id = payload.get("session_id")
    if not isinstance(agent_id, str) or not isinstance(session_id, str):
        print("ultraloom hook subagent-stop: payload carries no agent_id", file=stderr)
        return EXIT_INTERNAL

    before = read_state(root, session_id).snapshots.get(agent_id)
    if before is None:
        # Said, not swallowed: this hook may have been switched on midway
        # through the session, and silence here would read as "nothing
        # happened" -- a claim nobody checked.
        print(
            f"subagent {agent_id}: no snapshot for this subagent; nothing to compare",
            file=stdout,
        )
        return EXIT_OK

    for line in _findings(root, before):
        print(f"subagent {agent_id}: {line}", file=stdout)
    return EXIT_OK


def _findings(root: Path, before: str) -> tuple[str, ...]:
    """Everything worth naming about the difference to that snapshot."""
    old_refs, old_head = _split(before)
    lines = list(differences(old_refs, remote_refs(root)))
    if old_head and old_head != head(root):
        lines.extend(f"new commit {commit}" for commit in new_commits(root, old_head))
    return tuple(lines)


def _split(stored: str) -> tuple[str, str]:
    """A snapshot's remote part and the HEAD it recorded, if it recorded one."""
    refs = [line for line in stored.splitlines() if not line.startswith(_HEAD_MARKER)]
    marked = [line for line in stored.splitlines() if line.startswith(_HEAD_MARKER)]
    where = marked[0].removeprefix(_HEAD_MARKER) if marked else ""
    return "".join(f"{line}\n" for line in refs), where


def _git(root: Path, *arguments: str) -> str | None:
    """One git command's stdout, or None if it did not produce an answer.

    Through `process.run` like every other child in this project, so a hung
    grandchild costs its timeout and no more.
    """
    try:
        completed = process.run(("git", *arguments), cwd=root, timeout=TIMEOUT)
    except OSError:
        return None
    if completed.timed_out or completed.returncode != 0:
        return None
    return completed.stdout


def _refs(text: str) -> dict[str, str]:
    """A `ls-remote` listing read as ref -> hash."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        hash_and_ref = line.split("\t", 1)
        if len(hash_and_ref) == 2:
            found[hash_and_ref[1]] = hash_and_ref[0]
    return found
