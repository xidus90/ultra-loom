"""Which hook a call means, and where its streams come from."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ultraloom.hooks import session_start


def dispatch(args: argparse.Namespace, root: Path) -> int:
    """Run the named hook against the real streams."""
    if args.hook_name == "session-start":
        return session_start.run(sys.stdin, root, sys.stdout, sys.stderr)
    if args.hook_name == "post-edit":
        # Imported here and not at the top: post_edit pulls in the check chain,
        # and session-start -- which only reads a directory -- must not pay for
        # it. tests/test_module_boundary.py holds that.
        from ultraloom.hooks import post_edit

        return post_edit.run(sys.stdin, root, sys.stderr)
    if args.hook_name == "subagent-start":
        # Local for the same reason: these two reach git through `process`,
        # and session-start must not pay for an import it never uses. Note
        # the two spellings -- the subcommand has a hyphen, the module an
        # underscore -- and that they are never the same string.
        from ultraloom.hooks import subagent_start

        return subagent_start.run(sys.stdin, root, sys.stderr)
    if args.hook_name == "stop":
        # Local like the others, and this one carries the check chain: a
        # session-start that only reads a directory must not import it.
        from ultraloom.hooks import stop

        # Read off the namespace here and passed as a value, the way
        # `policy check` hands its arguments down: the hook's own signature
        # then says what it needs, and a test can call it without building an
        # argparse namespace.
        return stop.run(sys.stdin, root, sys.stderr, checks=args.checks)
    if args.hook_name == "subagent-stop":
        from ultraloom.hooks import subagent_stop

        return subagent_stop.run(sys.stdin, root, sys.stdout, sys.stderr)
    # argparse limits the choice, so this is the "no subcommand" case. Said
    # here rather than made required: argparse would exit 2, and 2 is a
    # finding in this protocol, not a typo.
    print("ultraloom hook: say which hook to run", file=sys.stderr)
    return 1
