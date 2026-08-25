"""The `policy` subcommand: which call shape ends in which exit code."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from ultraloom.cli import main


def _config(tmp_path: Path, body: str) -> Path:
    (tmp_path / ".ultraloom").mkdir()
    (tmp_path / ".ultraloom" / "config.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_check_allows_a_harmless_path(tmp_path: Path) -> None:
    assert main(["policy", "check", "paths", "src/a.py", "--root", str(tmp_path)]) == 0


def test_check_refuses_a_secret_and_names_the_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["policy", "check", "paths", ".env", "--root", str(tmp_path)]) == 2
    assert "secrets are not written by an agent" in capsys.readouterr().err


def test_check_passes_the_tool_name_on_to_the_rules(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A rule with `tools` must see the name the caller gave, not the default."""
    root = _config(
        tmp_path,
        """
[[policy.commands.rules]]
match = "git push*"
reason = "no pushing"
tools = ["Bash"]
""",
    )
    assert main(["policy", "check", "commands", "git push", "--root", str(root)]) == 0
    refused = main(
        ["policy", "check", "commands", "git push", "--tool", "Bash", "--root", str(root)]
    )
    assert refused == 2
    assert "no pushing" in capsys.readouterr().err


def test_check_reports_a_broken_config_and_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2, not 1: a policy that passes silently on a broken config is worse."""
    root = _config(tmp_path, "[policy.nonsense]\n")
    assert main(["policy", "check", "paths", "a.py", "--root", str(root)]) == 2
    assert "unknown policy kind" in capsys.readouterr().err


def test_hook_reads_the_payload_from_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / ".env")}}
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    assert main(["policy", "hook", "--root", str(tmp_path)]) == 2
    assert "secrets are not written by an agent" in capsys.readouterr().err


def test_policy_without_a_subcommand_says_what_to_type(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without this it would fall through to `hook` and sit on stdin forever."""
    assert main(["policy", "--root", str(tmp_path)]) == 1
    assert "hook" in capsys.readouterr().err


def test_a_broken_project_config_does_not_stop_the_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The policy reads [policy.*] itself; [verify] is none of its business."""
    root = _config(tmp_path, '[verify]\ncoverage = "uv run coverage report"\n')
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    assert main(["policy", "hook", "--root", str(root)]) == 1
