"""The `hook` subcommand: which call shape ends in which exit code."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from ultraloom.cli import main
from ultraloom.hooks.stop import MARKER


def test_session_start_reads_the_payload_from_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = json.dumps({"session_id": "s1", "hook_event_name": "SessionStart"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    assert main(["hook", "session-start", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""


def test_hook_without_a_name_says_what_to_type(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without this it would fall through to a hook and sit on stdin forever."""
    assert main(["hook", "--root", str(tmp_path)]) == 1
    assert "which hook" in capsys.readouterr().err


def test_stop_reads_the_payload_from_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With the marker in place, so the wiring is tested and not the chain."""
    marker = tmp_path / MARKER
    marker.parent.mkdir(parents=True)
    marker.write_text("", encoding="utf-8")
    payload = json.dumps({"session_id": "s1", "hook_event_name": "Stop"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    assert main(["hook", "stop", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().err == ""


def test_subagent_start_reads_the_payload_from_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = json.dumps({"session_id": "s1", "hook_event_name": "SubagentStart", "agent_id": "a1"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    assert main(["hook", "subagent-start", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().err == ""


def test_subagent_stop_reads_the_payload_from_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Straight after subagent-start, so the snapshot is there and nothing moved."""
    payload = json.dumps({"session_id": "s1", "hook_event_name": "SubagentStop", "agent_id": "a1"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    assert main(["hook", "subagent-stop", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out.startswith("subagent a1: no snapshot")


def test_stop_takes_a_check_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The argument reaches the hook; the marker keeps the chain out of it."""
    marker = tmp_path / MARKER
    marker.parent.mkdir(parents=True)
    marker.write_text("", encoding="utf-8")
    payload = json.dumps({"session_id": "s1", "hook_event_name": "Stop"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    assert main(["hook", "stop", "--root", str(tmp_path), "--checks", "lint"]) == 0
    assert capsys.readouterr().err == ""
