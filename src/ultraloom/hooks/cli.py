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
    # argparse limits the choice, so this is the "no subcommand" case. Said
    # here rather than made required: argparse would exit 2, and 2 is a
    # finding in this protocol, not a typo.
    print("ultraloom hook: say which hook to run", file=sys.stderr)
    return 1
