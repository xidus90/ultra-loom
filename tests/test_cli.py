"""Tests for the command line."""

import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

from ultraloom.cli import (
    MarkerError,
    _decode_baseline,
    _model,
    _recorded_run,
    _remember_run,
    _run_files,
    main,
    next_run_id,
)
from ultraloom.config import Config
from ultraloom.discovery import Baseline
from ultraloom.model.port import Reply
from ultraloom.worktree import head_commit

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


A_FLOW_THAT_EXITS_WITH_4 = '''
"""A flow that refuses with an exit code of its own."""

from dataclasses import dataclass

from ultraloom.graph import END, CodeNode, Graph
from ultraloom.runner import FlowExit


@dataclass(frozen=True, slots=True)
class Data:
    note: str = ""


def refuse(_data):
    raise FlowExit(4, "refused on purpose")


flow: Graph[Data] = Graph("stopper", start="refuse")
flow.add(CodeNode("refuse", refuse))
flow.edge("refuse", END)

initial = Data()
'''


def init_repo(root: Path) -> None:
    """A repository with one commit, which is what a baseline needs to exist.

    `git init` alone leaves HEAD naming a branch that has no commit yet, and
    a run started there records no baseline at all.
    """
    subprocess.run(("git", "init", "-q"), cwd=root, check=True)
    (root / "seed.py").write_text("x = 0\n", encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=root, check=True)
    subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first"),
        cwd=root,
        check=True,
    )


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
    init_repo(tmp_path)
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
    init_repo(tmp_path)
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
    init_repo(tmp_path)
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
    # Spelled out rather than inherited: max_parallel defaults to the machine's
    # cpu count and caps the *processes*, so on a one- or two-core runner these
    # three sleeps would be serialised by the cap and the bound below would fail
    # for a reason that has nothing to do with what is being tested.
    write_config(
        tmp_path,
        f"[verify]\nmax_parallel = 3\nlint = '{slow}'\ntypes = '{slow}'\ntest = '{slow}'\n",
    )
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

    built: list[tuple[Path, Path | None]] = []

    class StandInModel:
        def __init__(
            self,
            cwd: Path,
            cli_path: Path | None = None,
            setting_sources: tuple[str, ...] = ("project",),
            settings_file: Path | None = None,
        ) -> None:
            self.cwd = cwd
            built.append((cwd, cli_path))

        def ask(self, request: object) -> Reply:
            asked.append(request)
            return Reply(value=None, tokens=7)

    module = ModuleType("ultraloom.model.agent_sdk")
    # A stand-in for the optional extra, which this subproject does not ship.
    module.AgentSdkModel = StandInModel  # type: ignore[attr-defined]  # a stub module grows its attributes
    # The stand-in replaces the whole module, so it also answers the start-up
    # question the CLI asks before it builds the model.
    module.find_cli = lambda _cli_path=None: Path("claude.exe")  # type: ignore[attr-defined]  # a stub module grows its attributes
    monkeypatch.setitem(sys.modules, "ultraloom.model.agent_sdk", module)
    write_flow(tmp_path, "needs_model", A_MODEL_FLOW)

    code = main(["run", "needs_model", "--root", str(tmp_path)])

    assert code == 0
    assert len(asked) == 1
    assert built == [(tmp_path, None)], "nothing configured, so the SDK does its own looking"
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


def test_the_cli_returns_the_code_the_flow_named(tmp_path: Path) -> None:
    write_flow(tmp_path, "stopper", A_FLOW_THAT_EXITS_WITH_4)

    assert main(["run", "stopper", "--root", str(tmp_path), "--no-model"]) == 4


A_BUILT_FLOW = '''
"""A flow that is built from the run's context."""

from dataclasses import dataclass

from ultraloom.discovery import LoadedFlow
from ultraloom.graph import END, CodeNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    root: str = ""


def build(context):
    flow = Graph("built", start="mark")
    flow.add(CodeNode("mark", lambda _d: {"root": str(context.root)}))
    flow.edge("mark", END)
    return LoadedFlow(flow, Data(root=str(context.config.root)))
'''


def test_run_builds_a_flow_that_defines_build(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_flow(tmp_path, "built", A_BUILT_FLOW)

    code = main(["run", "built", "--root", str(tmp_path)])

    assert code == 0
    assert "done" in capsys.readouterr().out


A_GUARDED_FLOW = '''
"""A flow that measures its repairs against the commit it starts from."""

from dataclasses import dataclass

from ultraloom.discovery import LoadedFlow
from ultraloom.graph import END, CodeNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    root: str = ""


def build(context):
    flow = Graph("guarded", start="mark")
    flow.add(CodeNode("mark", lambda _d: {"root": str(context.root)}))
    flow.edge("mark", END)
    return LoadedFlow(flow, Data(root=str(context.config.root)), needs_baseline=True)
'''


def test_a_guarded_flow_refuses_to_start_outside_a_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A run that every resume would refuse must not be allowed to begin.

    Started outside a repository there is no commit to measure against, so
    the pause at a gate would succeed and every later answer would fail --
    begun only to be unfinishable.
    """
    write_flow(tmp_path, "guarded", A_GUARDED_FLOW)

    exit_code = main(["run", "guarded", "--root", str(tmp_path), "--no-model"])

    assert exit_code == 1
    assert "repository" in capsys.readouterr().err
    # Refusing the start leaves none of the run behind.
    for name in _run_files("0001"):
        assert not (tmp_path / name).exists()


def test_an_unguarded_flow_still_starts_outside_a_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No baseline, no need: a plain flow outside a repository runs as before."""
    write_flow(tmp_path, "plain", A_FLOW)

    exit_code = main(["run", "plain", "--root", str(tmp_path), "--no-model"])

    assert exit_code == 0
    assert "done" in capsys.readouterr().out


A_FLOW_THAT_ECHOES_ITS_OPTIONS = '''
"""A flow that asserts what the command line handed it."""

from dataclasses import dataclass

from ultraloom.discovery import LoadedFlow
from ultraloom.graph import END, CodeNode, Graph


@dataclass(frozen=True, slots=True)
class Payload:
    note: str = ""


def build(context):
    assert context.options["checks"] == "lint,types"
    assert context.options["max_rounds"] == "2", repr(context.options["max_rounds"])
    flow = Graph("echo_options", start="only")
    flow.add(CodeNode("only", lambda _data: {"note": "seen"}))
    flow.edge("only", END)
    return LoadedFlow(flow, Payload())
'''


A_FLOW_THAT_ECHOES_NOTHING = '''
"""A flow that asserts the options are absent when nobody passed any."""

from dataclasses import dataclass

from ultraloom.discovery import LoadedFlow
from ultraloom.graph import END, CodeNode, Graph


@dataclass(frozen=True, slots=True)
class Payload:
    note: str = ""


def build(context):
    assert context.options == {}, repr(context.options)
    flow = Graph("plain_options", start="only")
    flow.add(CodeNode("only", lambda _data: {"note": "seen"}))
    flow.edge("only", END)
    return LoadedFlow(flow, Payload())
'''


def test_the_options_reach_the_flow_as_strings(tmp_path: Path) -> None:
    """`--max-rounds 2` must arrive as "2", not as the int argparse parsed."""
    write_flow(tmp_path, "echo_options", A_FLOW_THAT_ECHOES_ITS_OPTIONS)

    code = main(
        [
            "run",
            "echo_options",
            "--root",
            str(tmp_path),
            "--no-model",
            "--checks",
            "lint,types",
            "--max-rounds",
            "2",
        ]
    )

    assert code == 0


def test_a_flow_without_the_options_is_unaffected(tmp_path: Path) -> None:
    write_flow(tmp_path, "plain_options", A_FLOW_THAT_ECHOES_NOTHING)

    assert main(["run", "plain_options", "--root", str(tmp_path), "--no-model"]) == 0


def test_max_rounds_must_be_a_number(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["run", "anything", "--root", str(tmp_path), "--max-rounds", "soon"])

    assert raised.value.code == 2, "argparse's own usage error"
    # The message, not just the code: an unknown flag would exit 2 as well, and
    # then the test would pass without the option existing at all.
    assert "invalid int value" in capsys.readouterr().err


A_GATED_FLOW_THAT_ECHOES_ITS_OPTIONS = '''
"""A gated flow that asserts its options on every load, start or continuation."""

from dataclasses import dataclass

from ultraloom.discovery import LoadedFlow
from ultraloom.graph import END, GateNode, Graph


@dataclass(frozen=True, slots=True)
class Payload:
    answer: str = ""


def build(context):
    expected = {"checks": "lint,types", "max_rounds": "2"}
    assert context.options == expected, repr(context.options)
    flow = Graph("gated_options", start="ask")
    flow.add(GateNode("ask", lambda _d: "Proceed?", lambda _d, a: {"answer": a}))
    flow.edge("ask", END)
    return LoadedFlow(flow, Payload())
'''


A_GATED_FLOW_WITHOUT_OPTIONS = '''
"""A gated flow that asserts it never sees options it was not given."""

from dataclasses import dataclass

from ultraloom.discovery import LoadedFlow
from ultraloom.graph import END, GateNode, Graph


@dataclass(frozen=True, slots=True)
class Payload:
    answer: str = ""


def build(context):
    assert context.options == {}, repr(context.options)
    flow = Graph("gated_plain", start="ask")
    flow.add(GateNode("ask", lambda _d: "Proceed?", lambda _d, a: {"answer": a}))
    flow.edge("ask", END)
    return LoadedFlow(flow, Payload())
'''


def _start_with_options(root: Path, name: str, body: str) -> None:
    write_flow(root, name, body)
    assert (
        main(
            [
                "run",
                name,
                "--root",
                str(root),
                "--no-model",
                "--checks",
                "lint,types",
                "--max-rounds",
                "2",
            ]
        )
        == 3
    )


def test_resume_sees_the_options_the_run_was_started_with(tmp_path: Path) -> None:
    """Otherwise a continuation would rebuild a different graph than it continues."""
    init_repo(tmp_path)
    _start_with_options(tmp_path, "gated_options", A_GATED_FLOW_THAT_ECHOES_ITS_OPTIONS)

    code = main(["resume", "0001", "--answer", "yes", "--root", str(tmp_path)])

    assert code == 0


def test_replay_sees_the_options_the_run_was_started_with(tmp_path: Path) -> None:
    """A replay that rebuilt the graph from different options would not be a replay."""
    init_repo(tmp_path)
    _start_with_options(tmp_path, "gated_options", A_GATED_FLOW_THAT_ECHOES_ITS_OPTIONS)
    assert main(["resume", "0001", "--answer", "yes", "--root", str(tmp_path)]) == 0

    assert main(["replay", "0001", "--root", str(tmp_path)]) == 0


def test_a_run_started_without_options_is_continued_without_them(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_flow(tmp_path, "gated_plain", A_GATED_FLOW_WITHOUT_OPTIONS)
    assert main(["run", "gated_plain", "--root", str(tmp_path), "--no-model"]) == 3

    code = main(["resume", "0001", "--answer", "yes", "--root", str(tmp_path)])

    assert code == 0


def _marker(root: Path, run_id: str = "0001") -> Path:
    return root / ".ultraloom" / "runs" / f"{run_id}.flow"


def test_a_run_records_what_was_already_dirty(tmp_path: Path) -> None:
    """The baseline belongs to the run, so it has to survive the process."""
    init_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("x = 1\n", encoding="utf-8")
    write_flow(tmp_path, "plain", A_FLOW)

    main(["run", "plain", "--root", str(tmp_path), "--no-model"])

    recorded = _recorded_run(tmp_path, "0001")
    assert recorded is not None
    _, options, baseline = recorded
    assert baseline is not None and "dirty.py" in baseline.dirty
    # And not among the options: a flow validates those, and this is not one.
    assert "baseline" not in options


def test_a_run_records_the_commit_it_started_on(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("y = 2\n", encoding="utf-8")
    write_flow(tmp_path, "plain", A_FLOW)

    main(["run", "plain", "--root", str(tmp_path), "--no-model"])

    recorded = _recorded_run(tmp_path, "0001")
    assert recorded is not None
    _, options, baseline = recorded
    assert baseline is not None
    assert baseline.commit == head_commit(tmp_path)
    assert "dirty.py" in baseline.dirty
    # Neither half is an option a flow validates.
    assert "baseline" not in options
    assert "baseline_commit" not in options


def test_a_marker_without_a_baseline_commit_records_no_baseline(tmp_path: Path) -> None:
    """A run started before this rule existed. The commit decides, and it is missing."""
    marker = _marker(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('plain\nbaseline="tests/a.py"\n', encoding="utf-8")

    recorded = _recorded_run(tmp_path, "0001")

    assert recorded == ("plain", {}, None)


def test_a_marker_with_a_commit_and_no_dirty_paths_is_a_baseline(tmp_path: Path) -> None:
    """The commit decides alone, so the two halves are not symmetric.

    `_remember_run` always writes both lines -- on a clean tree the `baseline=`
    one is empty rather than absent -- so this marker is a hand-written or
    hand-edited one. It is read all the same: the commit is a reference point
    the guard can measure against, and an absent dirty set means the same as an
    empty one. Nothing else covers this arm; `dirty or ""` is no branch to
    coverage.py.
    """
    marker = _marker(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('plain\nbaseline_commit="abc123"\n', encoding="utf-8")

    recorded = _recorded_run(tmp_path, "0001")

    assert recorded == ("plain", {}, Baseline("abc123", frozenset()))


A_GUARDED_GATED_FLOW = '''
"""A guarded flow that pauses, so a resume has something to answer."""

from dataclasses import dataclass

from ultraloom.discovery import LoadedFlow
from ultraloom.graph import END, GateNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    answer: str = ""


def build(context):
    flow = Graph("guarded_gated", start="ask")
    flow.add(GateNode("ask", lambda _d: "Proceed?", lambda _d, a: {"answer": a}))
    flow.edge("ask", END)
    return LoadedFlow(flow, Data(), needs_baseline=True)
'''


def test_resume_refuses_a_guarded_run_that_recorded_no_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A run that recorded no commit is refused rather than measured by half.

    Filling the commit in now would hand the repairer everything it
    committed before the pause as its starting state. The marker is stripped
    afterwards because that is the only way such a run can exist now: started
    before the guard measured against a commit at all.
    """
    init_repo(tmp_path)
    write_flow(tmp_path, "guarded_gated", A_GUARDED_GATED_FLOW)
    main(["run", "guarded_gated", "--root", str(tmp_path), "--no-model"])
    capsys.readouterr()
    _marker(tmp_path).write_text("guarded_gated\n", encoding="utf-8")

    code = main(["resume", "0001", "--answer", "yes", "--root", str(tmp_path)])

    assert code == 1
    assert "started before" in capsys.readouterr().err


def test_resume_carries_an_unguarded_run_that_recorded_no_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No commit to measure against is only a problem for a flow that measures.

    A plain flow paused outside a repository was refused every answer before
    `needs_baseline` existed -- unfinishable for a reason that was never its
    own.
    """
    write_flow(tmp_path, "gated", A_GATED_FLOW)
    main(["run", "gated", "--root", str(tmp_path)])
    capsys.readouterr()

    code = main(["resume", "0001", "--answer", "yes", "--root", str(tmp_path)])

    assert code == 0
    assert "done" in capsys.readouterr().out


def test_a_run_outside_a_repository_records_no_baseline(tmp_path: Path) -> None:
    """No commit, no baseline -- and the flow that needs one says so itself."""
    write_flow(tmp_path, "plain", A_FLOW)

    main(["run", "plain", "--root", str(tmp_path), "--no-model"])

    recorded = _recorded_run(tmp_path, "0001")
    assert recorded is not None and recorded[2] is None


def test_a_resumed_run_keeps_the_baseline_of_its_first_start(tmp_path: Path) -> None:
    """Read back, never taken again -- the whole point of recording it."""
    _remember_run(
        tmp_path,
        "0001",
        "plain",
        {"checks": "edit"},
        Baseline("abc", frozenset({"tests/a.py"})),
    )
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    # Something the repairer could have done after the pause. Taking a fresh
    # baseline here would swallow it; reading the recorded one must not.
    (tmp_path / "later.py").write_text("y = 2\n", encoding="utf-8")

    recorded = _recorded_run(tmp_path, "0001")

    assert recorded == (
        "plain",
        {"checks": "edit"},
        Baseline("abc", frozenset({"tests/a.py"})),
    )


def test_a_baseline_of_many_paths_stays_one_marker_line(tmp_path: Path) -> None:
    """A value holding newlines is exactly why the values are encoded."""
    paths = frozenset({"a.py", "b/c.py", "tests/d.py"})
    _remember_run(tmp_path, "0001", "plain", {}, Baseline("abc", paths))

    assert len(_marker(tmp_path).read_text(encoding="utf-8").splitlines()) == 3
    recorded = _recorded_run(tmp_path, "0001")
    assert recorded is not None and recorded[2] == Baseline("abc", paths)


def test_a_clean_tree_is_recorded_as_an_empty_baseline_not_as_none(tmp_path: Path) -> None:
    """ "Nothing was dirty" and "the run recorded nothing" are different answers."""
    _remember_run(tmp_path, "0001", "plain", {}, Baseline("abc", frozenset()))

    recorded = _recorded_run(tmp_path, "0001")

    assert recorded is not None and recorded[2] == Baseline("abc", frozenset())


def test_a_marker_from_before_the_baseline_existed_still_reads(tmp_path: Path) -> None:
    """Bare values and no baseline line: a run already on disk stays resumable."""
    marker = _marker(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("plain\nchecks=edit\nmax_rounds=3\n", encoding="utf-8")

    assert _recorded_run(tmp_path, "0001") == (
        "plain",
        {"checks": "edit", "max_rounds": "3"},
        None,
    )


def test_a_marker_line_without_a_separator_is_named_not_traced(tmp_path: Path) -> None:
    marker = _marker(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("plain\nthis line lost its equals sign\n", encoding="utf-8")

    with pytest.raises(MarkerError) as raised:
        _recorded_run(tmp_path, "0001")

    assert "0001.flow" in str(raised.value)
    assert "this line lost its equals sign" in str(raised.value)


def test_resume_says_which_marker_it_could_not_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A sentence on stderr and exit 1, not a traceback out of `dict()`."""
    write_flow(tmp_path, "plain", A_FLOW)
    main(["run", "plain", "--root", str(tmp_path), "--no-model"])
    _marker(tmp_path).write_text("plain\nbroken line\n", encoding="utf-8")

    assert main(["resume", "0001", "--root", str(tmp_path)]) == 1
    assert "broken line" in capsys.readouterr().err


def test_an_empty_marker_is_refused_by_name(tmp_path: Path) -> None:
    """An empty marker cannot say which flow a run belongs to.

    Tuple unpacking would end the command in a bare ValueError naming neither
    the file nor the problem -- the same reason a lost separator raises.
    """
    marker = _marker(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8")

    with pytest.raises(MarkerError) as raised:
        _recorded_run(tmp_path, "0001")

    assert "0001.flow" in str(raised.value)


def test_a_marker_whose_first_line_is_blank_is_refused_too(tmp_path: Path) -> None:
    """A leading blank line still leaves the file saying nothing about its flow."""
    marker = _marker(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("\nchecks=edit\n", encoding="utf-8")

    with pytest.raises(MarkerError):
        _recorded_run(tmp_path, "0001")


def test_resume_of_a_run_with_an_empty_marker_names_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A sentence on stderr and exit 1, not a traceback out of unpacking."""
    write_flow(tmp_path, "plain", A_FLOW)
    main(["run", "plain", "--root", str(tmp_path), "--no-model"])
    _marker(tmp_path).write_text("", encoding="utf-8")

    assert main(["resume", "0001", "--root", str(tmp_path)]) == 1
    assert "0001.flow" in capsys.readouterr().err


def test_a_blank_line_in_a_marker_is_not_a_broken_option(tmp_path: Path) -> None:
    """A trailing newline, an editor's blank line: neither says anything is wrong."""
    marker = _marker(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('plain\n\nchecks="edit"\n\n', encoding="utf-8")

    assert _recorded_run(tmp_path, "0001") == ("plain", {"checks": "edit"}, None)


def test_resume_of_a_run_that_is_not_waiting_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A finished run has no gate, so resuming it executes nothing and reports green.

    The symmetry to `replay` on a paused run: neither is the operation the
    caller meant, and answering with a false verdict is worse than refusing.
    A flow without any gate at all -- verify-until-green is one -- would
    otherwise report exit 0 having verified nothing.
    """
    init_repo(tmp_path)
    write_flow(tmp_path, "smoke", A_FLOW)
    main(["run", "smoke", "--root", str(tmp_path)])
    capsys.readouterr()

    code = main(["resume", "0001", "--root", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 1, "a run with nothing to answer must not come back green"
    assert "not waiting" in captured.err
    assert "replay" in captured.err
    assert "done" not in captured.out


def test_an_empty_recorded_baseline_holds_no_path(tmp_path: Path) -> None:
    """An empty line is not a path: splitting "" must not yield one.

    A "" in the baseline would be a recorded path that matches nothing, which
    is harmless -- but "the tree was clean" and "the tree held one nameless
    file" are different answers, and only one of them is true.
    """
    assert _decode_baseline("") == frozenset()
    assert _decode_baseline("a.py\n\ntests/b.py") == frozenset({"a.py", "tests/b.py"})


def test_check_all_refuses_a_ring_in_the_effective_check_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """load_config takes the single edge; the preset closes the ring behind it."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    config = tmp_path / ".ultraloom" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('[verify.after]\ntest = "coverage"\n', encoding="utf-8")

    code = main(["check", "all", "--root", str(tmp_path)])

    assert code == 1
    assert "has a cycle" in capsys.readouterr().err


def test_check_all_reports_a_blocked_check_as_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Never green, never silent: the line is there and the exit code is red."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    write_config(
        tmp_path,
        f"[verify]\ntest = '{python_command('raise SystemExit(1)')}'\n\n"
        '[verify.after]\ncoverage = "test"\n',
    )

    code = main(["check", "all", "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 1
    assert "coverage: failed [blocked]" in out
    assert "läuft nicht, weil `test` rot war" in out


def test_check_prints_the_heading_of_every_command_of_one_kind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """_report passes the output through, so a multi-command report arrives whole."""
    # The markers are computed, never spelled out in the command line: a marker
    # that appears in argv would already be matched by the heading, and the
    # assertion would pass over a _report that dropped the output entirely.
    first = python_command("print(chr(102) + str(11 * 2 + 1))")
    second = python_command("print(chr(115) + str(11 * 2 + 2)); raise SystemExit(1)")
    write_config(tmp_path, f"[verify]\nlint = ['{first}', '{second}']\n")

    code = main(["check", "lint", "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 1
    assert "lint: failed" in out
    assert "f23" in out, "the first command's own output must survive"
    assert "s24" in out, "and so must the second's"
    assert "(failed)" in out, "the heading carries the verdict of its own command"


def test_the_configured_cli_path_reaches_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What [agent].cli_path is for: the SDK is told where the CLI is.

    Read from the config the run already loaded rather than from the
    environment a second time, so the answer the run acts on is the one
    load_config validated.
    """
    built: list[Path | None] = []

    class StandInModel:
        def __init__(
            self,
            cwd: Path,
            cli_path: Path | None = None,
            setting_sources: tuple[str, ...] = ("project",),
            settings_file: Path | None = None,
        ) -> None:
            built.append(cli_path)

        def ask(self, request: object) -> Reply:
            return Reply(value=None, tokens=7)

    module = ModuleType("ultraloom.model.agent_sdk")
    module.AgentSdkModel = StandInModel  # type: ignore[attr-defined]  # a stub module grows its attributes
    # The stand-in replaces the whole module, so it also answers the start-up
    # question the CLI asks before it builds the model.
    module.find_cli = lambda _cli_path=None: Path("claude.exe")  # type: ignore[attr-defined]  # a stub module grows its attributes
    monkeypatch.setitem(sys.modules, "ultraloom.model.agent_sdk", module)
    monkeypatch.delenv("ULTRALOOM_CLI_PATH", raising=False)
    cli = tmp_path / "claude.exe"
    cli.write_text("", encoding="utf-8")
    config = tmp_path / ".ultraloom" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f'[agent]\ncli_path = "{cli.as_posix()}"\n', encoding="utf-8")
    write_flow(tmp_path, "needs_model", A_MODEL_FLOW)

    assert main(["run", "needs_model", "--root", str(tmp_path)]) == 0
    assert built == [cli]


def test_a_run_names_the_two_files_it_writes_itself() -> None:
    """What the guard subtracts, spelled as the answer about the tree spells it.

    Relative to `root` and forward-slashed, because that is what `changed_since`
    returns -- a mismatch here would not fail loudly, it would quietly charge
    ultraloom's own journal to the repair agent.
    """
    assert _run_files("0001") == frozenset(
        {".ultraloom/runs/0001.jsonl", ".ultraloom/runs/0001.flow"}
    )


def _no_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine on which no startable Claude CLI can be reached."""
    from ultraloom.model import agent_sdk
    from ultraloom.model.port import ModelError

    def refuse(_cli_path: Path | None = None) -> Path:
        raise ModelError("no Claude CLI to start: export ULTRALOOM_CLI_PATH")

    monkeypatch.setattr(agent_sdk, "find_cli", refuse)


def test_a_run_needing_the_model_stops_before_it_starts_when_no_cli_is_reachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The finding this closes: without a startable CLI every agent node died
    after 3.4 seconds, once per node, naming a fault of the SDK's. Nothing of
    the run may exist afterwards -- no journal, no marker, no run id spent."""
    _no_cli(monkeypatch)
    write_flow(tmp_path, "needs_model", A_MODEL_FLOW)

    code = main(["run", "needs_model", "--root", str(tmp_path)])

    assert code == 1
    assert "ULTRALOOM_CLI_PATH" in capsys.readouterr().err
    assert not (tmp_path / ".ultraloom" / "runs").exists()


def test_a_flow_without_agent_nodes_runs_on_a_machine_without_a_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check is about what the flow will actually do, not about the machine."""
    _no_cli(monkeypatch)
    write_flow(tmp_path, "smoke", A_FLOW)

    assert main(["run", "smoke", "--root", str(tmp_path)]) == 0


def test_no_model_runs_on_a_machine_without_a_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--no-model` says the run will not ask a model; then no CLI is needed."""
    _no_cli(monkeypatch)
    write_flow(tmp_path, "needs_model", A_MODEL_FLOW)

    code = main(["run", "needs_model", "--root", str(tmp_path), "--no-model"])

    # Exit 1 for the node that has no model to ask -- but from the runner, and
    # only after the run existed, which is the difference being asserted.
    assert code == 1
    assert (tmp_path / ".ultraloom" / "runs" / "0001.jsonl").exists()


def test_the_model_is_built_from_what_the_project_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring, not the adapter: _model must not drop what config read."""
    seen: dict[str, object] = {}

    class _Spy:
        def __init__(self, **kwargs: object) -> None:
            seen.update(kwargs)

    monkeypatch.setattr("ultraloom.model.agent_sdk.AgentSdkModel", _Spy)
    named = tmp_path / "repair.json"
    config = Config(root=tmp_path, setting_sources=("local",), settings_file=named)

    _model(tmp_path, config)

    assert seen["setting_sources"] == ("local",)
    assert seen["settings_file"] == named


def test_commit_msg_reaches_the_gate_and_returns_its_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The wiring only: what counts as the wrong language is tested next door."""
    write_config(tmp_path, '[commit]\nlanguage = "en"\n')
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("Das Ergebnis und der Bericht fehlen\n", encoding="utf-8")

    code = main(["commit-msg", str(message), "--root", str(tmp_path)])

    assert code == 2
    assert "line 1" in capsys.readouterr().err


def test_commit_msg_without_a_file_or_calibrate_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """argparse cannot: the argument is required for one mode and not the other."""
    write_config(tmp_path, '[commit]\nlanguage = "en"\n')

    code = main(["commit-msg", "--root", str(tmp_path)])

    assert code == 1
    assert "--calibrate" in capsys.readouterr().err


def test_commit_msg_calibrate_reaches_the_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(tmp_path, '[commit]\nlanguage = "en"\n')
    monkeypatch.setattr(
        "ultraloom.commit.calibrate.read_messages",
        lambda _root, _count: ("Das Ergebnis und der Bericht fehlen",),
    )

    code = main(["commit-msg", "--calibrate", "5", "--root", str(tmp_path)])

    assert code == 0
    assert "threshold 2: 1 refused" in capsys.readouterr().out
