"""Remembers where the remote stood before a subagent ran.

Its own event and its own module, because SubagentStop has no "before" of its
own: without a snapshot taken here it could only say that it cannot tell.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TextIO

from ultraloom.hooks.payload import EXIT_INTERNAL, EXIT_OK, PayloadError
from ultraloom.hooks.payload import read as read_payload
from ultraloom.hooks.state import read as read_state
from ultraloom.hooks.state import write as write_state
from ultraloom.hooks.subagent_stop import snapshot


def run(stdin: TextIO, root: Path, stderr: TextIO) -> int:
    """Store the remote's refs and HEAD under this subagent's id. Never blocks."""
    try:
        payload = read_payload(stdin)
    except PayloadError as error:
        print(f"ultraloom hook subagent-start: {error}", file=stderr)
        return EXIT_INTERNAL

    agent_id = payload.get("agent_id")
    session_id = payload.get("session_id")
    if not isinstance(agent_id, str) or not isinstance(session_id, str):
        # Without both there is nothing to file the snapshot under. Saying so
        # beats writing it somewhere it will never be looked for.
        print("ultraloom hook subagent-start: payload carries no agent_id", file=stderr)
        return EXIT_INTERNAL

    state = read_state(root, session_id)
    snapshots = {**state.snapshots, agent_id: snapshot(root)}
    write_state(root, session_id, replace(state, snapshots=snapshots))
    return EXIT_OK
