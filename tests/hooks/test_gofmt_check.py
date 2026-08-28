"""The gofmt wrapper, driven without a Go toolchain in reach.

The script is loaded by path rather than imported: `hooks/gofmt-check.py`
carries a hyphen and a PEP-723 header, so it is no importable module -- and it
has to stay a script, because that is how the gate calls it. Loading the very
file named in `.ultraloom/config.toml` is the point; a copy would prove nothing
about the command that actually runs.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "hooks" / "gofmt-check.py"


@pytest.fixture
def wrapper() -> ModuleType:
    """The script as a module, under a name nothing else claims."""
    spec = importlib.util.spec_from_file_location("ultraloom_gofmt_check", SCRIPT)
    # A readable .py file always yields a spec with a loader.
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def answer(
    monkeypatch: pytest.MonkeyPatch,
    wrapper: ModuleType,
    *,
    stdout: str = "",
    stderr: str = "",
    code: int = 0,
    raises: OSError | None = None,
) -> list[list[str]]:
    """Put a fixed gofmt in the wrapper's way and record what it was asked."""
    seen: list[list[str]] = []

    def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        seen.append(list(argv))
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(argv, code, stdout, stderr)

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    return seen


def test_no_paths_is_refused(wrapper: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    """A wrapper that was given nothing to check has not checked anything."""
    assert wrapper.main([]) == 1
    assert "usage:" in capsys.readouterr().err


def test_clean_tree_passes(wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = answer(monkeypatch, wrapper, stdout="\n")
    assert wrapper.main(["cmd"]) == 0
    assert seen == [["gofmt", "-l", "cmd"]]


def test_unformatted_files_fail(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole reason this file exists: gofmt names files and still exits 0."""
    answer(monkeypatch, wrapper, stdout="cmd/init/main.go\n")
    assert wrapper.main(["cmd"]) == 1
    assert "not gofmt-clean:\ncmd/init/main.go" in capsys.readouterr().err


def test_gofmt_own_failure_is_reported(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing directory is gofmt's exit 2 -- a broken call, not a clean tree."""
    answer(monkeypatch, wrapper, stderr="stat internal: no such file\n", code=2)
    assert wrapper.main(["cmd", "internal"]) == 1
    assert "stat internal: no such file" in capsys.readouterr().err


def test_silent_failure_still_names_the_code(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty stderr must not turn the report into a blank line."""
    answer(monkeypatch, wrapper, code=3)
    assert wrapper.main(["cmd"]) == 1
    assert "gofmt exited 3" in capsys.readouterr().err


def test_missing_toolchain_is_not_a_verdict(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No gofmt on PATH is the case this repository actually runs into."""
    answer(monkeypatch, wrapper, raises=FileNotFoundError(2, "gofmt not found"))
    assert wrapper.main(["cmd"]) == 1
    assert "gofmt could not be run:" in capsys.readouterr().err
