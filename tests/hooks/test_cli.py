"""The `hook` subcommand: which call shape ends in which exit code."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from ultraloom.cli import main


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
