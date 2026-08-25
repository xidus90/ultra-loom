"""What a fresh session is told about the runs it inherited."""

from __future__ import annotations

import io
import json
from pathlib import Path

from ultraloom.hooks.session_start import run


def _journal(root: Path, run_id: str, *lines: dict[str, object]) -> None:
    directory = root / ".ultraloom" / "runs"
    directory.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(line, sort_keys=True) for line in lines)
    (directory / f"{run_id}.jsonl").write_text(body + "\n", encoding="utf-8")


def _entry(node: str, outcome: str, detail: str | None = None) -> dict[str, object]:
    """A journal line with every field `journal.Entry` really has.

    Spelled out rather than trimmed: `entries()` builds `Entry(**line)`, so a
    line missing one field raises a JournalError about a damaged journal --
    which is exactly the state two of these tests must not be in.
    """
    return {
        "node": node,
        "kind": "gate",
        "input_hash": "abc123",
        "delta": {},
        "outcome": outcome,
        "tools": None,
        "effort": None,
        "tokens": 0,
        "seconds": 0.0,
        "detail": detail,
    }


def _payload() -> io.StringIO:
    return io.StringIO(json.dumps({"session_id": "s1", "hook_event_name": "SessionStart"}))


def test_a_project_without_runs_says_nothing(tmp_path: Path) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), tmp_path, out, err) == 0
    assert out.getvalue() == ""


def test_a_finished_run_is_not_reported(tmp_path: Path) -> None:
    _journal(tmp_path, "0001", _entry("verify", "ok"))
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), tmp_path, out, err) == 0
    assert out.getvalue() == ""


def test_a_run_that_paused_and_carried_on_is_not_reported(tmp_path: Path) -> None:
    """`pending_gate` reads the *last* line; an answered gate is not open."""
    _journal(
        tmp_path,
        "0007",
        _entry("approve", "paused", "May I merge?"),
        _entry("approve", "ok", "yes"),
    )
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), tmp_path, out, err) == 0
    assert out.getvalue() == ""


def test_a_paused_run_is_reported_with_its_question(tmp_path: Path) -> None:
    _journal(tmp_path, "0002", _entry("approve", "paused", "May I merge?"))
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), tmp_path, out, err) == 0
    said = out.getvalue()
    assert "0002" in said
    assert "May I merge?" in said
    assert "ultraloom resume 0002 --answer" in said


def test_every_paused_run_is_reported(tmp_path: Path) -> None:
    _journal(tmp_path, "0003", _entry("approve", "paused", "First?"))
    _journal(tmp_path, "0004", _entry("approve", "paused", "Second?"))
    out, err = io.StringIO(), io.StringIO()
    run(_payload(), tmp_path, out, err)
    assert "0003" in out.getvalue()
    assert "0004" in out.getvalue()


def test_a_damaged_journal_does_not_hide_the_others(tmp_path: Path) -> None:
    """One unreadable file is a finding, not a reason to say nothing at all."""
    _journal(tmp_path, "0005", _entry("approve", "paused", "Still open?"))
    directory = tmp_path / ".ultraloom" / "runs"
    (directory / "0006.jsonl").write_text("not a journal\n", encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), tmp_path, out, err) == 0
    assert "0005" in out.getvalue()
    assert "0006" in err.getvalue()


def test_an_unreadable_payload_is_an_internal_error(tmp_path: Path) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert run(io.StringIO("nonsense"), tmp_path, out, err) == 1
