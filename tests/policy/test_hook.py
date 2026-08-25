"""The adapter: payload in, exit code out. Rules are test_rules' business."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from ultraloom.policy.hook import run, subjects


def _payload(tool: str, tool_input: dict[str, Any]) -> io.StringIO:
    return io.StringIO(json.dumps({"tool_name": tool, "tool_input": tool_input}))


def _config(tmp_path: Path, body: str) -> Path:
    (tmp_path / ".ultraloom").mkdir()
    (tmp_path / ".ultraloom" / "config.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_an_unrelated_tool_yields_nothing(tmp_path: Path) -> None:
    """Short circuit before everything else: no kind touched, no config read."""
    assert subjects("WebFetch", {"url": "https://x"}, tmp_path) == ()


def test_write_yields_a_path_and_a_content_subject(tmp_path: Path) -> None:
    found = subjects("Write", {"file_path": str(tmp_path / "a.py"), "content": "x"}, tmp_path)
    assert [(s.kind, s.value) for s in found] == [("paths", "a.py"), ("content", "x")]


def test_edit_reads_the_new_string(tmp_path: Path) -> None:
    found = subjects("Edit", {"file_path": str(tmp_path / "a.py"), "new_string": "new"}, tmp_path)
    assert [(s.kind, s.value) for s in found] == [("paths", "a.py"), ("content", "new")]


def test_multiedit_reads_every_edit(tmp_path: Path) -> None:
    """The real payload carries the replacements in `edits`, not flat."""
    found = subjects(
        "MultiEdit",
        {
            "file_path": str(tmp_path / "a.py"),
            "edits": [
                {"old_string": "a", "new_string": "one"},
                {"old_string": "b", "new_string": "two"},
            ],
        },
        tmp_path,
    )
    assert [(s.kind, s.value) for s in found] == [
        ("paths", "a.py"),
        ("content", "one"),
        ("content", "two"),
    ]


def test_multiedit_refuses_a_pattern_in_a_later_edit(tmp_path: Path) -> None:
    root = _config(
        tmp_path,
        """
[[policy.content.rules]]
match = "*secret*"
reason = "no secrets"
""",
    )
    errors = io.StringIO()
    payload = _payload(
        "MultiEdit",
        {
            "file_path": str(root / "a.py"),
            "edits": [
                {"old_string": "a", "new_string": "harmless"},
                {"old_string": "b", "new_string": "a secret here"},
            ],
        },
    )
    assert run(payload, root, errors) == 2
    assert "no secrets" in errors.getvalue()


@pytest.mark.parametrize(
    "edits",
    [
        None,
        "new_string",
        [["old", "new"]],
        [{"old_string": "a"}],
        [{"new_string": 7}],
    ],
    ids=["missing", "not-a-list", "not-a-table", "no-new-string", "not-a-string"],
)
def test_multiedit_survives_an_unexpected_edits_shape(tmp_path: Path, edits: Any) -> None:
    """A shape we do not recognise yields no content -- but the path still counts."""
    tool_input: dict[str, Any] = {"file_path": str(tmp_path / "a.py")}
    if edits is not None:
        tool_input["edits"] = edits
    found = subjects("MultiEdit", tool_input, tmp_path)
    assert [(s.kind, s.value) for s in found] == [("paths", "a.py")]


def test_bash_yields_a_command_subject(tmp_path: Path) -> None:
    found = subjects("Bash", {"command": "git push"}, tmp_path)
    assert [(s.kind, s.value) for s in found] == [("commands", "git push")]


def test_an_absolute_path_is_made_relative_to_the_project(tmp_path: Path) -> None:
    """Claude Code sends absolute paths; a rule `.env` would never match one.

    tmp_path lives under AppData\\Local\\Temp on Windows, which is exactly where
    short 8.3 names and a differing case show up -- so this is also the test
    that `resolve()` on both sides really cancels out.
    """
    found = subjects("Write", {"file_path": str(tmp_path / "sub" / ".env")}, tmp_path)
    assert found[0].value == "sub/.env"


def test_a_path_outside_the_project_stays_absolute(tmp_path: Path) -> None:
    outside = tmp_path.parent / "elsewhere.txt"
    found = subjects("Write", {"file_path": str(outside)}, tmp_path)
    assert found[0].value == outside.as_posix()


def test_a_tool_input_without_the_expected_keys_yields_nothing(tmp_path: Path) -> None:
    """A payload shape we do not recognise is not a reason to block."""
    assert subjects("Bash", {}, tmp_path) == ()
    assert subjects("Write", {}, tmp_path) == ()


def test_an_allowed_write_exits_zero(tmp_path: Path) -> None:
    errors = io.StringIO()
    payload = _payload("Write", {"file_path": str(tmp_path / "src" / "a.py"), "content": "x"})
    assert run(payload, tmp_path, errors) == 0
    assert errors.getvalue() == ""


def test_an_untouched_tool_exits_zero_without_reading_the_config(tmp_path: Path) -> None:
    """A broken config must not block what no rule could ever concern."""
    root = _config(tmp_path, "[policy.nonsense]\n")
    assert run(_payload("WebFetch", {"url": "https://x"}), root, io.StringIO()) == 0


def test_a_denied_write_exits_two_and_says_why(tmp_path: Path) -> None:
    root = _config(
        tmp_path,
        """
[[policy.paths.rules]]
match = "secrets/**"
reason = "not in here"
""",
    )
    errors = io.StringIO()
    payload = _payload("Write", {"file_path": str(root / "secrets" / "a"), "content": "x"})
    assert run(payload, root, errors) == 2
    assert "not in here" in errors.getvalue()


def test_every_reason_is_reported_not_only_the_first(tmp_path: Path) -> None:
    root = _config(
        tmp_path,
        """
[[policy.paths.rules]]
match = ".env"
reason = "first reason"
""",
    )
    errors = io.StringIO()
    payload = _payload("Write", {"file_path": str(root / ".env"), "content": "x"})
    assert run(payload, root, errors) == 2
    assert "secrets are not written by an agent" in errors.getvalue()
    assert "first reason" in errors.getvalue()


def test_a_broken_config_blocks_rather_than_letting_through(tmp_path: Path) -> None:
    """The one failure mode that does real damage: passing silently."""
    root = _config(tmp_path, '[[policy.paths.rules]]\nmatch = 1\nreason = "x"')
    errors = io.StringIO()
    payload = _payload("Write", {"file_path": str(root / "a")})
    assert run(payload, root, errors) == 2
    assert "must be a string or a list" in errors.getvalue()


@pytest.mark.parametrize("raw", ["", "no json", "[]", '{"tool_name": 5}', "{}"])
def test_an_unreadable_payload_is_an_internal_error(tmp_path: Path, raw: str) -> None:
    """Exit 1, never 2: a broken policy must not lock up a session."""
    errors = io.StringIO()
    assert run(io.StringIO(raw), tmp_path, errors) == 1
    assert "unreadable hook payload" in errors.getvalue()


def test_a_tool_input_that_is_not_a_table_is_an_internal_error(tmp_path: Path) -> None:
    errors = io.StringIO()
    raw = json.dumps({"tool_name": "Write", "tool_input": []})
    assert run(io.StringIO(raw), tmp_path, errors) == 1
    assert "unreadable hook payload" in errors.getvalue()
