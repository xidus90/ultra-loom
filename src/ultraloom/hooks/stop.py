"""Holds a turn until the chain is green.

The one hook here that can stop a session, and every decision in it is bent
towards letting go rather than holding on: three blocks per session and then
it gives up, a marker that switches it off, and exit 1 -- never exit 2 -- for
every failure that is ultraloom's own rather than the work's.

The question it answers is deliberately narrower than "is this project
green". It is: *is everything green that arrived since the last green pass?*
That is what can be answered without spending forty-five seconds on every
turn, and it is why the base commit below moves forward when the chain
passes and stays put when it does not.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TextIO

from ultraloom.checks import KINDS, UNAVAILABLE, CheckResult, run_kinds
from ultraloom.config import Config, ConfigError, kinds_for, load_config
from ultraloom.hooks.payload import EXIT_BLOCKED, EXIT_INTERNAL, EXIT_OK, PayloadError
from ultraloom.hooks.payload import read as read_payload
from ultraloom.hooks.state import STATE_DIR, SessionState
from ultraloom.hooks.state import read as read_state
from ultraloom.hooks.state import write as write_state
from ultraloom.worktree import WorktreeError, changed_files, changed_since, head_commit

# How often one session may be held before the gate hands the decision back to
# the human. A cap and not a rule of thumb: a gate that never yields locks the
# session it was meant to protect, and there is no way out of that from inside
# the session.
MAX_BLOCKS = 3

# The file that switches the gate off while it exists, for a turn somebody
# wants to end red on purpose.
MARKER = ".claude/.no-verify"

# What reads the working tree, and what runs the chain. Both are parameters of
# `run` with these as defaults, following `checks._run` and `process.run`: the
# syscalls come from outside so a test can put a red chain in front of the
# decision without waiting forty-five seconds for a real one.
type Differ = Callable[[Path, str | None], tuple[str, ...]]
type Chain = Callable[[Sequence[str], Config], tuple[CheckResult, ...]]


def changed(root: Path, base: str | None) -> tuple[str, ...]:
    """What this session has to answer for, measured against `base`.

    `changed_since` and not `changed_files`, the same way the verify flow's
    guard measures and for the same reason (spec 2026-08-23): a turn that
    *commits* its work leaves `git status` with nothing to report, and a gate
    built on the working tree alone would go quiet at exactly the moment
    somebody committed something unverified.

    Without a base there is nothing to measure against, and the working tree
    is all that is left. `run` says so on stderr rather than letting that read
    as a full answer.
    """
    if base is None:
        return changed_files(root)
    return changed_since(root, base)


def run(
    stdin: TextIO,
    root: Path,
    stderr: TextIO,
    differ: Differ = changed,
    chain: Chain = run_kinds,
    checks: str | None = None,
) -> int:
    """Whether this turn may end. Exit 2 holds it, everything else lets it go.

    `checks` is a profile name from [verify.profiles] or a comma-separated
    list of check kinds, spelled exactly as `ultraloom run --checks` spells
    it. It is a plain parameter and not an injected one like `differ` and
    `chain`: those two exist so a test can put a syscall-free answer in front
    of the decision, while this is what the caller *asked for*, and it stays a
    string until `_verify` has the config -- resolving it earlier would mean
    reading [verify.profiles] a second time, before the load that reports a
    broken table.

    The order of the five stages below is not free:

    1. The payload, because without a session id nothing can be counted.
    2. The marker, before anything is read or run: the human already decided.
    3. The counter, *before* the chain rather than after it -- forty-five
       seconds spent on a verdict that will not hold anybody up anyway are
       forty-five seconds wasted.
    4. The short circuit, so a turn that only read and answered is free.
    5. The chain.
    """
    try:
        payload = read_payload(stdin)
    except PayloadError as error:
        print(f"ultraloom hook stop: {error}", file=stderr)
        return EXIT_INTERNAL

    session_id = payload.get("session_id")
    if not isinstance(session_id, str):
        # Exit 1 and not a fixed fallback key: a counter shared by every
        # session without an id would give up on one session because another
        # had been blocked three times. Exit 1 never holds the turn, so the
        # cost of refusing here is a line on stderr.
        print("ultraloom hook stop: payload carries no session_id", file=stderr)
        return EXIT_INTERNAL

    # `stop_hook_active` is in the payload -- Task 1 measured it: false on the
    # first call, true on the one a block forced. It is deliberately *not*
    # read. It says "this turn was already blocked once" and never how often,
    # so it cannot carry the cap; and a second source that can disagree with
    # the counter would make the gate's behaviour unexplainable at the moment
    # somebody is trying to get out of it. The counter below is bounded on its
    # own: even a state file that was wiped costs at most MAX_BLOCKS rounds.
    if _switched_off(root):
        return EXIT_OK

    state = read_state(root, session_id)
    if state.blocks >= MAX_BLOCKS:
        print(
            f"ultraloom hook stop: gave up after {state.blocks} blocks in this session; "
            "the chain was still red the last time it ran. Run `ultraloom check all` "
            "by hand, or remove .claude/.no-verify once the gate should count again.",
            file=stderr,
        )
        return EXIT_OK

    if state.base is None:
        print(
            "ultraloom hook stop: no base commit for this session, so only the working "
            "tree is measured -- anything this session committed is invisible here. "
            "Start a session with the session-start hook wired up to close that gap.",
            file=stderr,
        )

    try:
        touched = differ(root, state.base)
    except WorktreeError as error:
        # Never read as "nothing changed", which is this module's rule as much
        # as worktree's own: a question git could not answer must not end a
        # turn as if the answer had been "clean".
        print(f"ultraloom hook stop: {error}", file=stderr)
        return EXIT_INTERNAL

    touched = _not_our_own(touched)
    if not touched:
        return EXIT_OK

    return _verify(root, session_id, state, chain, checks, stderr)


def _not_our_own(touched: tuple[str, ...]) -> tuple[str, ...]:
    """Everything except this hook's own bookkeeping.

    The gate writes a state file on every block and every pass, and that file
    lives in the working tree. Left in the answer it would make every turn
    look changed for the rest of the session -- including the turn right after
    a green one, whose only difference from its predecessor is the file the
    green one wrote. The same subtraction the verify flow's guard does for a
    run's journal, and for the same reason: what ultraloom writes is not what
    the session did.

    `.gitignore` covers the directory in this repository, so in practice git
    never reports it -- but a project that adopts the hooks without that line
    would otherwise get a gate that never short-circuits, and the failure
    would look like the gate being broken rather than like a missing line.
    """
    prefix = f"{STATE_DIR}/"
    return tuple(path for path in touched if not path.startswith(prefix))


def _switched_off(root: Path) -> bool:
    """Whether the marker file is there.

    `exists()` answers False for a missing `.claude/` without raising, so the
    ordinary case of a project that has no such directory needs no special
    handling. The OSError arm is for the rest: a path too long, a permission
    that says no, a name the filesystem refuses. Any of them would otherwise
    end the turn with a traceback, and a gate that crashes on the way to
    asking whether it is switched on is worse than one that is switched off.
    """
    try:
        return (root / MARKER).exists()
    except OSError:
        return False


def _verify(
    root: Path,
    session_id: str,
    state: SessionState,
    chain: Chain,
    checks: str | None,
    stderr: TextIO,
) -> int:
    """Run the chain and turn what it said into an exit code."""
    try:
        config = load_config(root)
    except ConfigError as error:
        # Exit 1 like every ultraloom-side failure here: a broken [verify]
        # table is not a finding about the work, and holding a turn over one
        # would leave nobody able to fix it from inside the session.
        print(f"ultraloom hook stop: {error}", file=stderr)
        return EXIT_INTERNAL

    try:
        kinds = KINDS if checks is None else kinds_for(config, checks)
    except ConfigError as error:
        # Exit 1, like every other ultraloom-side failure here: a profile name
        # nobody configured is not a finding about the work, and a turn held
        # over one could not be repaired from inside the session. The message
        # is `kinds_for`'s own, so a mistyped profile reads the same here as it
        # does at `ultraloom run --checks`.
        print(f"ultraloom hook stop: {error}", file=stderr)
        return EXIT_INTERNAL

    try:
        results = chain(kinds, config)
    except ConfigError as error:
        # The scheduler is the first reader of the effective check order, so a
        # ring between the project's edges and the preset's surfaces here and
        # not in load_config.
        print(f"ultraloom hook stop: {error}", file=stderr)
        return EXIT_INTERNAL

    red = tuple(result for result in results if not result.ok)
    if not red:
        if checks is None:
            _advance(root, session_id, state)
        return EXIT_OK

    for result in red:
        print(f"{result.kind}: {result.output}", file=stderr)

    if all(result.source == UNAVAILABLE for result in red):
        # `all`, not `any`: only a chain that said nothing usable at all is no
        # verdict about the work, and so neither a block nor something to
        # count. One unavailable check beside a real finding must not swallow
        # it -- a project that legitimately has no such check (GDScript has no
        # typechecker, so `types` resolves to nothing on every single run)
        # would otherwise never be able to block, paying for the whole chain
        # and enforcing nothing. Reported with the rest above either way,
        # because the agent still has to see which check is missing.
        print("ultraloom hook stop: the chain could not run; nothing was verified", file=stderr)
        return EXIT_INTERNAL

    write_state(root, session_id, replace(state, blocks=state.blocks + 1))
    return EXIT_BLOCKED


def _advance(root: Path, session_id: str, state: SessionState) -> None:
    """Move the base to what was just verified, and leave the counter alone.

    Called only when the whole chain ran. A pass under `--checks` says less
    than the base means: the base is this hook's word for "everything up to
    here has been verified", and a profile that skips the suite has not
    verified it. Moving the base after a narrowed pass would hide every
    untested change from the *next* turn as well, so a project running the
    static profile at the gate would end up with a chain of turns none of which
    ever ran the suite and none of which could still see the work. Left where
    it was, the range only grows, and the profile is cheap by construction --
    that is why somebody chose it.

    The base moves only here, on a pass. Moving it after a block would leave
    the next turn with nothing to measure and the gate would have switched
    itself off after a single finding.

    The counter is deliberately *not* cleared. A session that alternates red
    and green would otherwise never reach the cap, and the cap is what keeps a
    disagreement between agent and gate from running forever.

    A root with no commit -- or no repository at all -- simply keeps the base
    it had. The turn passed; refusing to end it over a bookkeeping detail
    would be the one thing this hook must never do.
    """
    try:
        commit = head_commit(root)
    except WorktreeError:
        return
    write_state(root, session_id, replace(state, base=commit))
