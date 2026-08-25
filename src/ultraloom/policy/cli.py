"""The two call shapes, kept apart from the payload handling."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ultraloom.config import ConfigError
from ultraloom.policy.config import load_ruleset
from ultraloom.policy.hook import EXIT_DENIED, EXIT_INTERNAL, EXIT_OK, run
from ultraloom.policy.rules import KINDS, Subject, evaluate


def dispatch(args: argparse.Namespace, root: Path) -> int:
    """`policy hook` reads stdin, `policy check` takes the value as an argument."""
    if args.policy_command == "check":
        return _manual(args.kind, args.value, args.tool, root)
    if args.policy_command is None:
        # Said here rather than made required in argparse: argparse would exit
        # 2, and 2 is this command's word for "refused". Falling through to the
        # hook would be worse still -- it would sit on a terminal's stdin.
        print("ultraloom policy: say which: `hook` or `check`", file=sys.stderr)
        return EXIT_INTERNAL
    return run(sys.stdin, root, sys.stderr)


def _manual(kind: str, value: str, tool: str, root: Path) -> int:
    """By hand: the same decision, without a payload around it."""
    try:
        ruleset = load_ruleset(root)
    except ConfigError as error:
        print(f"ultraloom policy: {error}", file=sys.stderr)
        return EXIT_DENIED

    # argparse limited the choice to KINDS, so the index is safe; going through
    # the tuple is how mypy learns the same thing.
    subject = Subject(KINDS[KINDS.index(kind)], value, tool)
    verdict = evaluate(ruleset, subject)
    if verdict.allowed:
        return EXIT_OK
    for reason in verdict.reasons:
        print(f"  - {reason}", file=sys.stderr)
    return EXIT_DENIED
