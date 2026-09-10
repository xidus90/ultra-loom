"""Which hook a call means, and where its streams come from."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Note the two spellings -- the subcommands have hyphens, the modules
# underscores -- and that they are never the same string.
from ultraloom.hooks import subagent_start, subagent_stop


def dispatch(args: argparse.Namespace, root: Path) -> int:
    """Run the named hook against the real streams."""
    if args.hook_name == "subagent-start":
        return subagent_start.run(sys.stdin, root, sys.stderr)
    if args.hook_name == "stop":
        # The one import still held back, and measured rather than assumed:
        # `stop.py` pulls in `ultraloom.checks`, so importing it here would
        # load the whole check chain for the two subagent hooks, which never
        # run it. `ultraloom.checks not in sys.modules` after a
        # `hook subagent-stop` is what tests/test_module_boundary.py asserts.
        from ultraloom.hooks import stop

        # Read off the namespace here and passed as a value, the way
        # `policy check` hands its arguments down: the hook's own signature
        # then says what it needs, and a test can call it without building an
        # argparse namespace.
        return stop.run(sys.stdin, root, sys.stderr, checks=args.checks)
    if args.hook_name == "subagent-stop":
        return subagent_stop.run(sys.stdin, root, sys.stdout, sys.stderr)
    # argparse limits the choice, so this is the "no subcommand" case. Said
    # here rather than made required: argparse would exit 2, and 2 is a
    # finding in this protocol, not a typo.
    print("ultraloom hook: say which hook to run", file=sys.stderr)
    return 1
