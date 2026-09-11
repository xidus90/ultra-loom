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
def wrapper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    """The script as a module, under a name nothing else claims.

    Outside any pass and outside the repository: this suite itself runs as the
    `test` check, so without the delenv every test here would inherit a pass
    that holds `test` -- and without the chdir the script would remove the
    `.coverage` and `coverage.out` that very check is writing.
    """
    monkeypatch.delenv("ULTRALOOM_ALONGSIDE", raising=False)
    monkeypatch.chdir(tmp_path)
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
        words = list(argv[:3])
        if words:
            words[0] = Path(words[0]).stem.lower()
        key = " ".join(words)
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


def test_resolve_go_prefers_path(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wrapper.shutil, "which", lambda cmd: "/usr/bin/go")
    assert wrapper._resolve_go() == "/usr/bin/go"


def test_resolve_go_falls_back_on_windows(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_go = tmp_path / "go.exe"
    fake_go.write_text("")
    monkeypatch.setattr(wrapper.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(wrapper.sys, "platform", "win32")
    monkeypatch.setattr(wrapper, "_WINDOWS_GO", fake_go)
    assert wrapper._resolve_go() == str(fake_go)


def test_resolve_go_defaults_to_bare_name_when_not_found(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wrapper.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(wrapper.sys, "platform", "linux")
    assert wrapper._resolve_go() == "go"


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
        stem = Path(argv[0]).stem.lower() if argv else ""
        if argv[:4] == ["uv", "run", "coverage", "report"]:
            return subprocess.CompletedProcess(argv, 2, "TOTAL 83%\n", "")
        if stem == "go" and len(argv) >= 2 and argv[1] == "test":
            return subprocess.CompletedProcess(argv, 0, "ok\n", "")
        if stem == "go" and len(argv) >= 3 and argv[1:3] == ["tool", "cover"]:
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


def in_a_pass(
    monkeypatch: pytest.MonkeyPatch, root: Path, kinds: str, *, data: bool = True
) -> None:
    """Stand in a project root, inside a pass of `kinds`, with or without its data."""
    monkeypatch.chdir(root)
    monkeypatch.setenv("ULTRALOOM_ALONGSIDE", kinds)
    if data:
        (root / ".coverage").write_text("", encoding="utf-8")
        (root / "coverage.out").write_text("mode: set\n", encoding="utf-8")


def test_a_pass_that_ran_test_is_reported_not_measured_again(
    wrapper: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """The point of the whole branch: one suite run per pass, not two."""
    in_a_pass(monkeypatch, tmp_path, "coverage,lint,test,types")
    seen = answers(monkeypatch, wrapper, GREEN)
    assert wrapper.main(["98"]) == 0
    assert "go coverage 98.6%" in capsys.readouterr().out
    assert not [argv for argv in seen if argv[2:4] == ["coverage", "run"]]
    assert not [argv for argv in seen if argv[1:2] == ["test"]]
    assert [argv[1:] for argv in seen if argv[1:3] == ["tool", "cover"]] == [
        ["tool", "cover", "-func=coverage.out"]
    ]


def test_a_pass_without_test_measures_itself(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Data lying around from an earlier `test` is exactly the stale data to refuse."""
    in_a_pass(monkeypatch, tmp_path, "coverage")
    seen = answers(monkeypatch, wrapper, GREEN)
    assert wrapper.main(["98"]) == 0
    assert [argv for argv in seen if argv[2:4] == ["coverage", "run"]]
    assert [argv for argv in seen if argv[1:2] == ["test"]]


def test_a_pass_with_test_but_no_data_measures_itself(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `test` that measured nothing must not leave the report reading nothing."""
    in_a_pass(monkeypatch, tmp_path, "coverage,test", data=False)
    seen = answers(monkeypatch, wrapper, GREEN)
    assert wrapper.main(["98"]) == 0
    assert [argv for argv in seen if argv[2:4] == ["coverage", "run"]]
    assert [argv for argv in seen if argv[1:2] == ["test"]]


def test_a_kind_is_matched_whole_not_as_a_substring(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    in_a_pass(monkeypatch, tmp_path, "coverage,contest")
    seen = answers(monkeypatch, wrapper, GREEN)
    assert wrapper.main(["98"]) == 0
    assert [argv for argv in seen if argv[2:4] == ["coverage", "run"]]


def test_a_missing_toolchain_is_no_verdict_over_data_from_the_pass(
    wrapper: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Reading what `test` left behind still needs the tools that read it."""
    in_a_pass(monkeypatch, tmp_path, "coverage,test")
    answers(
        monkeypatch,
        wrapper,
        GREEN,
        raises={
            "uv run coverage": FileNotFoundError(2, "no uv"),
            "go tool cover": FileNotFoundError(2, "no go"),
        },
    )
    assert wrapper.main(["98"]) == 1
    said = capsys.readouterr().err
    assert "coverage could not be run:" in said
    assert "go could not be run:" in said


@pytest.mark.parametrize("kinds", ["coverage,test", "coverage"])
def test_a_measurement_is_read_once_and_then_forgotten(
    wrapper: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kinds: str
) -> None:
    """Data that outlives its pass is data the next pass could mistake for its own.

    A `[verify.test]` that stopped measuring would otherwise leave this check
    reading whatever the last measuring run wrote, for as long as nobody noticed.
    """
    in_a_pass(monkeypatch, tmp_path, kinds)
    answers(monkeypatch, wrapper, GREEN)
    assert wrapper.main(["98"]) == 0
    assert not (tmp_path / ".coverage").exists()
    assert not (tmp_path / "coverage.out").exists()


def test_an_unreadable_profile_from_the_pass_is_measured_again(
    wrapper: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Measured on 2026-09-11: two gates in one checkout wrote one coverage.out.

    `go tool cover` refused the interleaved file. That is no finding about the
    tree, so it must not end the arm red -- it ends the shortcut, and the arm
    measures the way it would have without one.
    """
    in_a_pass(monkeypatch, tmp_path, "coverage,test")
    seen: list[list[str]] = []

    def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        seen.append(list(argv))
        if argv[1:3] == ["tool", "cover"] and argv[3] == "-func=coverage.out":
            return subprocess.CompletedProcess(argv, 1, "", "no required module provides\n")
        if argv[1:3] == ["tool", "cover"]:
            return subprocess.CompletedProcess(argv, 0, GO_FUNC_OUTPUT, "")
        return subprocess.CompletedProcess(argv, 0, "ok\n", "")

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    assert wrapper.main(["98"]) == 0
    said = capsys.readouterr()
    assert "go coverage 98.6%" in said.out
    assert "measuring again" in said.err
    assert [argv for argv in seen if argv[1:2] == ["test"]]
