"""The two-language coverage lane, driven without a suite and without Go.

Loaded by path for the same reason as the gofmt wrapper: `coverage-check.py`
carries a hyphen and a PEP-723 header, so it is no importable module -- and it
has to stay a script, because that is how `.ultraloom/config.toml` calls it.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "hooks" / "coverage-check.py"

GO_FUNC_OUTPUT = "cmd/init/run.go:90:\trun\t97.5%\ntotal:\t\t(statements)\t98.6%\n"


@pytest.fixture
def wrapper() -> ModuleType:
    """The script as a module, under a name nothing else claims."""
    spec = importlib.util.spec_from_file_location("ultraloom_coverage_check", SCRIPT)
    # A readable .py file always yields a spec with a loader.
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def answers(
    monkeypatch: pytest.MonkeyPatch,
    wrapper: ModuleType,
    replies: dict[str, tuple[int, str]],
    *,
    raises: dict[str, OSError] | None = None,
) -> list[list[str]]:
    """Put fixed tools in the wrapper's way, keyed by the first two words.

    Keyed rather than ordered: the two arms run one after the other, and a test
    that had to count calls would break every time one of them gained a step.
    """
    seen: list[list[str]] = []

    def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        seen.append(list(argv))
        key = " ".join(argv[:3])
        for prefix, error in (raises or {}).items():
            if key.startswith(prefix):
                raise error
        for prefix, (code, out) in replies.items():
            if key.startswith(prefix):
                return subprocess.CompletedProcess(argv, code, out, "")
        raise AssertionError(f"nothing was arranged for {argv}")

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    return seen


GREEN = {
    "uv run coverage": (0, "TOTAL 100%\n"),
    "go test": (0, "ok\n"),
    "go tool cover": (0, GO_FUNC_OUTPUT),
}


def test_both_arms_green_passes(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = answers(monkeypatch, wrapper, GREEN)
    assert wrapper.main(["98"]) == 0
    out = capsys.readouterr().out
    assert "go coverage 98.6%" in out
    assert [
        "uv",
        "run",
        "coverage",
        "run",
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "--no-header",
    ] in seen


def test_a_floor_above_the_measurement_fails(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reason the Go arm exists: `go test` has no fail_under of its own."""
    answers(monkeypatch, wrapper, GREEN)
    assert wrapper.main(["99"]) == 1
    assert "below the floor of 99.0%" in capsys.readouterr().err


def test_a_red_python_report_fails(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    replies = dict(GREEN)
    replies["uv run coverage"] = (0, "")

    def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if argv[:4] == ["uv", "run", "coverage", "report"]:
            return subprocess.CompletedProcess(argv, 2, "TOTAL 83%\n", "")
        if argv[:2] == ["go", "test"]:
            return subprocess.CompletedProcess(argv, 0, "ok\n", "")
        if argv[:3] == ["go", "tool", "cover"]:
            return subprocess.CompletedProcess(argv, 0, GO_FUNC_OUTPUT, "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    assert wrapper.main(["98"]) == 1
    said = capsys.readouterr()
    # Both arms are reported even when one of them failed: a repairer that only
    # ever hears about the first failure spends one round per language.
    assert "TOTAL 83%" in said.err
    assert "go coverage 98.6%" in said.out


def test_a_red_suite_is_not_reported_over(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A partial measurement names files nobody reached, not files nobody covered."""
    replies = dict(GREEN)
    replies["uv run coverage"] = (1, "2 failed\n")
    answers(monkeypatch, wrapper, replies)
    assert wrapper.main(["98"]) == 1
    assert "the suite failed under measurement" in capsys.readouterr().err


def test_a_red_go_suite_fails(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    replies = dict(GREEN)
    replies["go test"] = (1, "FAIL\n")
    answers(monkeypatch, wrapper, replies)
    assert wrapper.main(["98"]) == 1
    assert "go test failed" in capsys.readouterr().err


def test_a_failing_cover_tool_fails(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    replies = dict(GREEN)
    replies["go tool cover"] = (1, "cannot open profile\n")
    answers(monkeypatch, wrapper, replies)
    assert wrapper.main(["98"]) == 1
    assert "go tool cover failed" in capsys.readouterr().err


def test_a_missing_total_is_not_a_hundred_percent(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unmeasured tree must not read as a measured one."""
    replies = dict(GREEN)
    replies["go tool cover"] = (0, "no packages\n")
    answers(monkeypatch, wrapper, replies)
    assert wrapper.main(["98"]) == 1
    assert "named no total" in capsys.readouterr().err


def test_a_missing_python_toolchain_is_not_a_verdict(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers(monkeypatch, wrapper, GREEN, raises={"uv run coverage": FileNotFoundError(2, "no uv")})
    assert wrapper.main(["98"]) == 1
    assert "coverage could not be run:" in capsys.readouterr().err


def test_a_missing_go_toolchain_is_not_a_verdict(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers(monkeypatch, wrapper, GREEN, raises={"go test": FileNotFoundError(2, "no go")})
    assert wrapper.main(["98"]) == 1
    assert "go could not be run:" in capsys.readouterr().err


def test_without_a_floor_it_refuses(
    wrapper: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert wrapper.main([]) == 1
    assert "usage:" in capsys.readouterr().err


def test_a_floor_that_is_not_a_number_is_refused(
    wrapper: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert wrapper.main(["a lot"]) == 1
    assert "is not a percentage" in capsys.readouterr().err
