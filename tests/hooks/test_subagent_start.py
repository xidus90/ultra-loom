"""Where the remote stood before a subagent ran."""

from __future__ import annotations

import io
import json
from pathlib import Path

from ultraloom.hooks.state import SessionState
from ultraloom.hooks.state import read as read_state
from ultraloom.hooks.state import write as write_state
from ultraloom.hooks.subagent_start import run


def _payload(agent_id: str = "a1") -> io.StringIO:
    return io.StringIO(
        json.dumps(
            {
                "session_id": "s1",
                "hook_event_name": "SubagentStart",
                "agent_id": agent_id,
                "agent_type": "general-purpose",
            }
        )
    )


def test_the_snapshot_lands_under_the_agent_id(tmp_path: Path) -> None:
    err = io.StringIO()
    assert run(_payload(), tmp_path, err) == 0
    assert "a1" in read_state(tmp_path, "s1").snapshots


def test_a_second_subagent_does_not_overwrite_the_first(tmp_path: Path) -> None:
    write_state(tmp_path, "s1", SessionState(blocks=2, snapshots={"a1": "aaa\trefs/heads/x\n"}))
    err = io.StringIO()
    assert run(_payload("a2"), tmp_path, err) == 0

    state = read_state(tmp_path, "s1")
    assert state.snapshots["a1"] == "aaa\trefs/heads/x\n"
    assert "a2" in state.snapshots
    assert state.blocks == 2


def test_a_payload_without_an_agent_id_is_an_internal_error(tmp_path: Path) -> None:
    payload = io.StringIO(json.dumps({"session_id": "s1", "hook_event_name": "SubagentStart"}))
    err = io.StringIO()
    assert run(payload, tmp_path, err) == 1
    assert "agent_id" in err.getvalue()


def test_an_unreadable_payload_is_an_internal_error(tmp_path: Path) -> None:
    err = io.StringIO()
    assert run(io.StringIO("nonsense"), tmp_path, err) == 1
    assert "stdin is not JSON" in err.getvalue()
