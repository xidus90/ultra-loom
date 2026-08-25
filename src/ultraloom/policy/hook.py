"""Claude Code's hook protocol, translated into subjects and exit codes.

The only place in this repo that knows how Claude Code speaks. A second
harness would get a second module beside this one, not an `if` inside it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TextIO

from ultraloom.config import ConfigError
from ultraloom.policy.config import load_ruleset
from ultraloom.policy.rules import Subject, evaluate

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_DENIED = 2

# Which tool touches which kinds. A tool that is not listed here ends the run
# before any configuration is read.
_PATH_TOOLS = ("Write", "Edit")
_CONTENT_KEYS = {"Write": "content", "Edit": "new_string"}
# Both shells run commands, and both carry the command line under `command`, so
# one rule of kind `commands` covers them. PowerShell used to be missing here,
# and on Windows -- where it is the shell Claude Code reaches for -- every
# command rule, `git push` included, was silently skipped.
_COMMAND_TOOLS = ("Bash", "PowerShell")


def subjects(tool: str, tool_input: Mapping[str, Any], root: Path) -> tuple[Subject, ...]:
    """What is to be checked about this tool call. Empty means nothing."""
    if tool in _COMMAND_TOOLS:
        command = tool_input.get("command")
        if not isinstance(command, str):
            return ()
        return (Subject("commands", command, tool),)

    if tool not in _PATH_TOOLS:
        return ()

    found: list[Subject] = []
    raw_path = tool_input.get("file_path")
    if isinstance(raw_path, str):
        found.append(Subject("paths", _relative(raw_path, root), tool))

    content = tool_input.get(_CONTENT_KEYS[tool])
    if isinstance(content, str):
        found.append(Subject("content", content, tool))
    return tuple(found)


def _relative(raw: str, root: Path) -> str:
    """The path the way a rule spells it: relative to the root, with `/`.

    Claude Code sends absolute paths, which a rule `.env` would never match,
    and a pattern should hit the same thing on Windows as on POSIX. Both sides
    are resolved, because on Windows one of them may arrive as a short 8.3 name
    or in another case than the other -- resolving only one would make the
    relative_to fail and quietly hand a rule an absolute path it cannot match.
    What lies outside the root stays absolute: a rule aiming there must say the
    whole path.
    """
    path = Path(raw)
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def run(stdin: TextIO, root: Path, stderr: TextIO) -> int:
    """Read one payload, check it, and answer with an exit code."""
    try:
        payload = json.loads(stdin.read())
        tool = payload["tool_name"]
        tool_input = payload.get("tool_input", {})
        if not isinstance(tool, str) or not isinstance(tool_input, dict):
            raise TypeError("tool_name must be a string and tool_input a table")
    except (json.JSONDecodeError, TypeError, KeyError, AttributeError) as error:
        # Exit 1 and not 2: a broken policy must not lock up a session.
        print(f"ultraloom policy: unreadable hook payload: {error}", file=stderr)
        return EXIT_INTERNAL

    to_check = subjects(tool, tool_input, root)
    if not to_check:
        return EXIT_OK

    try:
        ruleset = load_ruleset(root)
    except ConfigError as error:
        # Exit 2, not 1: a policy that passes silently on a broken config is
        # the one failure mode that does real damage.
        print(f"ultraloom policy: {error}", file=stderr)
        return EXIT_DENIED

    reasons = [reason for subject in to_check for reason in evaluate(ruleset, subject).reasons]
    if not reasons:
        return EXIT_OK

    print(f"ultraloom policy refused this {tool}:", file=stderr)
    for reason in reasons:
        print(f"  - {reason}", file=stderr)
    return EXIT_DENIED
