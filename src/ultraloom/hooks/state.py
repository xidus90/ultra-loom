"""What one session remembers between two hook calls.

One file per session, not one per checkout: two sessions in the same working
copy would otherwise reset each other's block counter, and a gate that counts
somebody else's rounds is no gate.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

STATE_DIR = ".ultraloom/hooks"


@dataclass(frozen=True, slots=True)
class SessionState:
    """The counter and the snapshots one session carries."""

    blocks: int = 0
    snapshots: Mapping[str, str] = field(default_factory=dict)


def read(root: Path, session_id: str) -> SessionState:
    """What this session left behind, or an empty state.

    A file that cannot be read counts as empty. Raising instead would end
    every turn with an internal error over a counter whose worst case is three
    extra rounds.
    """
    path = _path(root, session_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        blocks = raw["blocks"]
        snapshots = raw["snapshots"]
        if not isinstance(blocks, int) or not isinstance(snapshots, dict):
            raise TypeError("state file has the wrong shape")
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return SessionState()
    return SessionState(blocks=blocks, snapshots=snapshots)


def write(root: Path, session_id: str, state: SessionState) -> None:
    """Keep this state for the next call."""
    path = _path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"blocks": state.blocks, "snapshots": dict(state.snapshots)}
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _path(root: Path, session_id: str) -> Path:
    """Where this session's file lives.

    The id arrives from outside, so it may not decide where the file lands:
    only the name's own last part is used, and a separator in it collapses to
    something harmless rather than climbing out of the directory.
    """
    safe = "".join(char for char in session_id if char.isalnum() or char in "-_") or "unnamed"
    return root / STATE_DIR / f"{safe}.json"
