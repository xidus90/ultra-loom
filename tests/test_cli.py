"""Tests for the command line."""

import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

from ultraloom.cli import main, next_run_id
from ultraloom.model.port import Reply

A_FLOW = '''
"""A flow that finishes on its own."""

from dataclasses import dataclass

from ultraloom.graph import END, CodeNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    note: str = ""


flow: Graph[Data] = Graph("smoke", start="mark")
flow.add(CodeNode("mark", lambda _d: {"note": "marked"}))
flow.edge("mark", END)

initial = Data()
'''

A_GATED_FLOW = '''
"""A flow that stops for an answer."""

from dataclasses import dataclass

from ultraloom.graph import END, CodeNode, GateNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    answer: str = ""


flow: Graph[Data] = Graph("gated", start="ask")
flow.add(GateNode("ask", lambda _d: "Proceed?", lambda _d, a: {"answer": a}))
flow.add(CodeNode("act", lambda d: {"answer": d.answer + "!"}))
flow.edge("ask", "act")
flow.edge("act", END)

initial = Data()
'''

A_MODEL_FLOW = '''
"""A flow whose only node needs a model."""

from dataclasses import dataclass

from ultraloom.graph import END, AgentNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    note: str = ""


flow: Graph[Data] = Graph("needs-model", start="ask")
flow.add(AgentNode("ask", lambda _d: "question", schema=Data, apply=lambda _d, _r: {}))
flow.edge("ask", END)

initial = Data()
'''


def write_flow(root: Path, name: str, body: str) -> None:
    target = root / ".ultraloom" / "flows" / f"{name}.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def write_config(root: Path, body: str) -> None:
    target = root / ".ultraloom" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def write_check_script(root: Path, kind: str, body: str) -> None:
    target = root / ".ultraloom" / "checks" / f"{kind}.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def python_command(code: str) -> str:
    """A `[verify]` command line running the test interpreter.

    `as_posix` on purpose: config.py splits with shlex in POSIX mode on every
    platform, so a Windows path with backslashes would lose them here.
    """
    return f'{Path(sys.executable).as_posix()} -c "{code}"'


def test_run_ids_count_up_and_are_zero_padded(tmp_path: Path) -> None:
    """Run ids come from the directory, not a clock — so tests stay deterministic."""
    assert next_run_id(tmp_path) == "0001"
    runs = tmp_path / ".ultraloom" / "runs"
    runs.mkdir(parents=True)
    (runs / "0001.jsonl").touch()
    (runs / "notes.jsonl").touch()

    assert next_run_id(tmp_path) == "0002"


def test_run_finishes_a_flow_and_reports_the_run_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_flow(tmp_path, "smoke", A_FLOW)

    code = main(["run", "smoke", "--root", str(tmp_path)])

    assert code == 0
    out = capsys.readouterr().out
    assert "done" in out
    assert "0001" in out
    assert (tmp_path / ".ultraloom" / "runs" / "0001.jsonl").exists()


def test_run_names_the_available_flows_when_the_name_is_wrong(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_flow(tmp_path, "smoke", A_FLOW)

    code = main(["run", "nope", "--root", str(tmp_path)])

    assert code == 1
    assert "smoke" in capsys.readouterr().err


def test_run_reports_a_pause_and_the_question(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_flow(tmp_path, "gated", A_GATED_FLOW)

    code = main(["run", "gated", "--root", str(tmp_path)])

    assert code == 3, "a pause is neither success nor failure — nor a usage error"
    assert "Proceed?" in capsys.readouterr().out


def test_resume_with_an_answer_finishes_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_flow(tmp_path, "gated", A_GATED_FLOW)
    main(["run", "gated", "--root", str(tmp_path)])
    capsys.readouterr()

    code = main(["resume", "0001", "--answer", "yes", "--root", str(tmp_path)])

    assert code == 0
    assert "done" in capsys.readouterr().out


def test_resume_of_an_unknown_run_id_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_flow(tmp_path, "gated", A_GATED_FLOW)

    code = main(["resume", "9999", "--answer", "yes", "--root", str(tmp_path)])

    assert code == 1
    assert "9999" in capsys.readouterr().err


def test_resume_of_a_run_whose_flow_is_not_recorded_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A journal alone does not say which flow it belongs to; the marker beside it does."""
    write_flow(tmp_path, "gated", A_GATED_FLOW)
    main(["run", "gated", "--root", str(tmp_path)])
    (tmp_path / ".ultraloom" / "runs" / "0001.flow").unlink()
    capsys.readouterr()

    code = main(["resume", "0001", "--answer", "yes", "--root", str(tmp_path)])

    assert code == 1
    assert "which flow" in capsys.readouterr().err


def test_show_prints_a_line_per_node_with_tokens_and_seconds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_flow(tmp_path, "smoke", A_FLOW)
    main(["run", "smoke", "--root", str(tmp_path)])
    capsys.readouterr()

    code = main(["show", "0001", "--root", str(tmp_path)])

    assert code == 0
    out = capsys.readouterr().out
    assert "mark" in out
    assert "code" in out
    assert "ok" in out


def test_show_of_an_unknown_run_id_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["show", "0001", "--root", str(tmp_path)])

    assert code == 1
    assert "0001" in capsys.readouterr().err


def test_replay_reaches_the_same_end_without_running_a_node(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_flow(tmp_path, "smoke", A_FLOW)
    main(["run", "smoke", "--root", str(tmp_path)])
    before = (tmp_path / ".ultraloom" / "runs" / "0001.jsonl").read_text(encoding="utf-8")
    capsys.readouterr()

    code = main(["replay", "0001", "--root", str(tmp_path)])

    assert code == 0
    assert "done" in capsys.readouterr().out
    after = (tmp_path / ".ultraloom" / "runs" / "0001.jsonl").read_text(encoding="utf-8")
    assert after == before, "replay must not append to the journal it reads"


def test_replay_of_a_paused_run_reports_that_it_never_finished(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate has no `ok` entry yet, so there is nothing to re-derive."""
    write_flow(tmp_path, "gated", A_GATED_FLOW)
    main(["run", "gated", "--root", str(tmp_path)])
    capsys.readouterr()

    code = main(["replay", "0001", "--root", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 1, "an unfinished run is not a pause a replay may report"
    assert "never finished" in captured.err
    assert "Proceed?" not in captured.out


def test_replay_with_an_answer_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Applying an answer would run the gate live, which is the opposite of a replay."""
    code = main(["replay", "0001", "--answer", "yes", "--root", str(tmp_path)])

    assert code == 1
    assert "resume" in capsys.readouterr().err


def test_check_reports_zero_when_the_command_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(tmp_path, f"[verify]\nlint = '{python_command('pass')}'\n")

    code = main(["check", "lint", "--root", str(tmp_path)])

    assert code == 0
    assert "lint" in capsys.readouterr().out


def test_check_reports_one_and_the_output_when_the_command_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(tmp_path, f"[verify]\nlint = '{python_command('print(1 / 0)')}'\n")

    code = main(["check", "lint", "--root", str(tmp_path)])

    assert code == 1
    assert "ZeroDivisionError" in capsys.readouterr().out


def test_check_reports_an_unresolvable_check_as_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unresolvable check must never look like a passed one."""
    code = main(["check", "lint", "--root", str(tmp_path)])

    assert code == 1
    assert "could not tell" in capsys.readouterr().err


def test_the_coverage_threshold_is_reported_as_configuration_not_as_a_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing folds the threshold into the command, so no verdict may carry it."""
    write_check_script(tmp_path, "coverage", "pass\n")

    code = main(["check", "coverage", "--threshold", "90", "--root", str(tmp_path)])

    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    assert lines[0] == "coverage: ok [script]", "a verdict naming the threshold would claim it"
    assert "90" in lines[1]
    assert "does not enforce" in lines[1]


def test_a_coverage_command_under_verify_is_explained_not_just_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`[verify].coverage` is the spelling everyone tries; the error must name the real ones."""
    write_config(tmp_path, f"[verify]\ncoverage = '{python_command('pass')}'\n")

    code = main(["check", "coverage", "--root", str(tmp_path)])

    err = capsys.readouterr().err
    assert code == 1
    assert "[verify.coverage]" in err
    assert ".ultraloom/checks/coverage" in err


def test_a_broken_config_is_reported_without_the_coverage_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(tmp_path, "[verify\n")

    code = main(["check", "lint", "--root", str(tmp_path)])

    err = capsys.readouterr().err
    assert code == 1
    assert "[verify.coverage]" not in err


def test_a_broken_config_stops_a_flow_command_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_flow(tmp_path, "smoke", A_FLOW)
    write_config(tmp_path, "[verify\n")

    code = main(["run", "smoke", "--root", str(tmp_path)])

    assert code == 1
    assert "config.toml" in capsys.readouterr().err


def test_check_all_reports_the_resolvable_and_the_unavailable_alike(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    command = python_command("pass")
    write_config(tmp_path, f"[verify]\nlint = '{command}'\ntypes = '{command}'\n")

    code = main(["check", "all", "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 1, "the unresolvable checks must keep the exit code non-zero"
    assert "lint: ok" in out
    assert "types: ok" in out
    assert "unavailable" in out, "a check that cannot run must be visible, not silent"


def test_check_all_waits_for_the_checks_at_the_same_time(tmp_path: Path) -> None:
    """The reason `all` exists: one startup cost, and the waiting overlaps."""
    slow = python_command("import time; time.sleep(0.5)")
    write_config(tmp_path, f"[verify]\nlint = '{slow}'\ntypes = '{slow}'\ntest = '{slow}'\n")
    started = time.perf_counter()

    main(["check", "all", "--root", str(tmp_path)])

    assert time.perf_counter() - started < 1.2, "three half-second waits did not overlap"


def test_no_subcommand_prints_usage_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([])

    assert code == 1
    assert "usage" in capsys.readouterr().err.lower()


def test_run_of_a_flow_that_needs_a_model_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without the agent extra the message must name the install, not raise ImportError."""
    write_flow(tmp_path, "needs_model", A_MODEL_FLOW)

    code = main(["run", "needs_model", "--root", str(tmp_path), "--no-model"])

    assert code == 1
    assert "ultraloom[agent]" in capsys.readouterr().out


def test_the_agent_extra_is_used_when_it_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With the extra present the CLI must hand the runner the real model."""
    asked: list[object] = []

    class StandInModel:
        def __init__(self, cwd: Path) -> None:
            self.cwd = cwd

        def ask(self, request: object) -> Reply:
            asked.append(request)
            return Reply(value=None, tokens=7)

    module = ModuleType("ultraloom.model.agent_sdk")
    # A stand-in for the optional extra, which this subproject does not ship.
    module.AgentSdkModel = StandInModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ultraloom.model.agent_sdk", module)
    write_flow(tmp_path, "needs_model", A_MODEL_FLOW)

    code = main(["run", "needs_model", "--root", str(tmp_path)])

    assert code == 0
    assert len(asked) == 1
    assert "done" in capsys.readouterr().out


def test_the_pause_code_does_not_collide_with_argparses_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A script reading the exit code must tell a gate from a typo."""
    write_flow(tmp_path, "gated", A_GATED_FLOW)
    paused = main(["run", "gated", "--root", str(tmp_path)])

    with pytest.raises(SystemExit) as raised:
        main(["run", "--root", str(tmp_path)])

    assert paused != raised.value.code
    assert raised.value.code == 2, "argparse's own convention, left alone"


def test_show_works_when_the_config_is_unreadable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reading a past run is what you want most when the project is broken."""
    write_flow(tmp_path, "plain", A_FLOW)
    main(["run", "plain", "--root", str(tmp_path)])
    config = tmp_path / ".ultraloom" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("this is not = = toml\n", encoding="utf-8")
    capsys.readouterr()

    code = main(["show", "0001", "--root", str(tmp_path)])

    assert code == 0
    assert "mark" in capsys.readouterr().out
