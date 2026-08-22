"""Tests for resolving and running the check chain."""

import json
import shlex
import sys
import time
from pathlib import Path
from threading import Semaphore

import pytest

from ultraloom import checks, process
from ultraloom.checks import (
    BLOCKED,
    KINDS,
    PRESETS,
    UNREADY,
    CheckResult,
    CheckRunner,
    CheckUnavailableError,
    Command,
    Preset,
    _run_command,
    resolve_check,
    run_all,
    run_check,
    run_kinds,
)
from ultraloom.config import Config, load_config

# The interpreter path goes into a TOML string that is later split with shlex
# in POSIX mode, where a Windows backslash is an escape character. Forward
# slashes survive both, and Windows accepts them.
PYTHON = shlex.quote(Path(sys.executable).as_posix())


def py(code: str) -> str:
    """A command line running `code` in this very interpreter."""
    return f"{PYTHON} -c {shlex.quote(code)}"


def python_project(root: Path) -> Path:
    (root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    return root


def node_project(root: Path) -> Path:
    (root / "package.json").write_text('{"name": "x"}\n', encoding="utf-8")
    return root


def godot_project(root: Path) -> Path:
    (root / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return root


def write_config(root: Path, body: str) -> None:
    target = root / ".ultraloom" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def verify_config(root: Path, **commands: str) -> None:
    """Write a `[verify]` table, escaping each command as a TOML string."""
    lines = "\n".join(f"{kind} = {json.dumps(value)}" for kind, value in commands.items())
    write_config(root, f"[verify]\n{lines}\n")


def test_config_beats_everything(tmp_path: Path) -> None:
    python_project(tmp_path)
    write_config(tmp_path, '[verify]\nlint = "my-own-linter --strict"\n')

    command = resolve_check("lint", load_config(tmp_path))

    assert command.argvs[0] == ("my-own-linter", "--strict")
    assert command.source == "config"


def test_a_convention_script_beats_the_preset(tmp_path: Path) -> None:
    python_project(tmp_path)
    script = tmp_path / ".ultraloom" / "checks" / "lint.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('linted')\n", encoding="utf-8")

    command = resolve_check("lint", load_config(tmp_path))

    assert command.source == "script"
    assert str(script) in " ".join(command.argvs[0])
    assert command.argvs[0][0] == sys.executable


def test_a_script_in_another_language_is_run_directly(tmp_path: Path) -> None:
    """Only a .py script gets this interpreter put in front of it."""
    python_project(tmp_path)
    script = tmp_path / ".ultraloom" / "checks" / "lint.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/sh\n", encoding="utf-8")

    assert resolve_check("lint", load_config(tmp_path)).argvs[0] == (str(script),)


def test_an_empty_checks_directory_falls_through_to_the_preset(tmp_path: Path) -> None:
    python_project(tmp_path)
    (tmp_path / ".ultraloom" / "checks").mkdir(parents=True)

    assert resolve_check("lint", load_config(tmp_path)).source == "preset"


def test_the_python_preset_is_found_from_pyproject(tmp_path: Path) -> None:
    python_project(tmp_path)

    command = resolve_check("types", load_config(tmp_path))

    assert command.source == "preset"
    assert command.argvs[0][:2] == ("uvx", "mypy")


def test_the_node_preset_is_found_from_package_json(tmp_path: Path) -> None:
    node_project(tmp_path)

    assert resolve_check("types", load_config(tmp_path)).argvs[0] == ("tsc", "--noEmit")
    assert resolve_check("lint", load_config(tmp_path)).argvs[0] == ("eslint", ".")


def test_the_godot_preset_is_found_from_project_godot(tmp_path: Path) -> None:
    godot_project(tmp_path)

    assert resolve_check("lint", load_config(tmp_path)).argvs[0] == ("uvx", "gdlint", ".")


def test_gdscript_has_no_typechecker_and_says_so(tmp_path: Path) -> None:
    """A missing capability must be reported, never counted as passed."""
    godot_project(tmp_path)

    with pytest.raises(CheckUnavailableError, match="known limitation"):
        resolve_check("types", load_config(tmp_path))


def test_an_unrecognised_project_refuses_to_guess(tmp_path: Path) -> None:
    with pytest.raises(CheckUnavailableError, match="could not tell"):
        resolve_check("lint", load_config(tmp_path))


def test_an_unknown_check_kind_is_refused(tmp_path: Path) -> None:
    python_project(tmp_path)

    with pytest.raises(CheckUnavailableError, match="unknown check"):
        resolve_check("vibes", load_config(tmp_path))


def test_the_exec_prefix_is_put_in_front_of_a_preset(tmp_path: Path) -> None:
    node_project(tmp_path)
    write_config(tmp_path, '[exec]\nprefix = "docker compose exec -T frontend"\n')

    command = resolve_check("lint", load_config(tmp_path))

    assert command.argvs[0] == ("docker", "compose", "exec", "-T", "frontend", "eslint", ".")


def test_the_exec_prefix_is_put_in_front_of_a_configured_command(tmp_path: Path) -> None:
    node_project(tmp_path)
    write_config(
        tmp_path,
        '[exec]\nprefix = "docker compose exec -T web"\n[verify]\nlint = "biome check"\n',
    )

    assert resolve_check("lint", load_config(tmp_path)).argvs[0] == (
        "docker",
        "compose",
        "exec",
        "-T",
        "web",
        "biome",
        "check",
    )


def test_a_passing_command_reports_ok(tmp_path: Path) -> None:
    verify_config(tmp_path, lint=py("pass"))

    result = run_check("lint", load_config(tmp_path))

    assert result.ok is True
    assert result.kind == "lint"
    assert result.source == "config"


def test_a_failing_command_reports_not_ok_and_keeps_its_output(tmp_path: Path) -> None:
    verify_config(tmp_path, lint=py('import sys; print("three problems"); sys.exit(1)'))

    result = run_check("lint", load_config(tmp_path))

    assert result.ok is False
    assert "three problems" in result.output


def test_a_missing_executable_reports_not_ok_rather_than_crashing(tmp_path: Path) -> None:
    """A tool that is not installed is a failure, never a skipped check."""
    write_config(tmp_path, '[verify]\nlint = "definitely-not-installed-anywhere"\n')

    result = run_check("lint", load_config(tmp_path))

    assert result.ok is False
    assert "definitely-not-installed-anywhere" in result.output


def test_run_all_reports_every_check_including_the_unresolvable_ones(tmp_path: Path) -> None:
    verify_config(tmp_path, lint=py("pass"), types=py("pass"))

    results = run_all(load_config(tmp_path))

    assert tuple(result.kind for result in results) == KINDS
    assert all(result.ok for result in results if result.kind in ("lint", "types"))


def test_run_all_keeps_a_fixed_order_whatever_finishes_first(tmp_path: Path) -> None:
    """A report whose line order depends on timing cannot be compared."""
    verify_config(tmp_path, lint=py("import time; time.sleep(0.4)"), types=py("pass"))

    order = tuple(result.kind for result in run_all(load_config(tmp_path)))

    assert order == KINDS, "output order must follow KINDS, not completion"


def test_run_all_skips_a_check_it_cannot_resolve_and_says_which(tmp_path: Path) -> None:
    """An unresolvable check is reported as unavailable, never as passed."""
    verify_config(tmp_path, lint=py("pass"))

    results = run_all(load_config(tmp_path))

    unavailable = [result for result in results if result.source == "unavailable"]
    assert unavailable, "the checks with no preset must appear, not vanish"
    assert all(result.ok is False for result in unavailable)
    assert all("could not tell" in result.output for result in unavailable)


def test_an_unresolvable_command_does_not_take_the_chain_down(tmp_path: Path) -> None:
    """A blank [verify] command never reaches here now -- load_config refuses the
    file. A blank coverage report is the one empty command left to the resolver,
    and it must be reported rather than stop every other check.
    """
    types = json.dumps(py("pass"))
    body = f"[verify]\ntypes = {types}\n[verify.coverage]\nreport = '   '\n"
    write_config(tmp_path, body)

    results = {result.kind: result for result in run_all(load_config(tmp_path))}

    assert results["coverage"].source == "unavailable"
    assert results["types"].ok is True


def test_an_unexpected_failure_in_one_check_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One check blowing up must not discard the results of the others."""
    verify_config(tmp_path, lint=py("pass"))

    def explode(*args: object, **kwargs: object) -> object:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "tool wrote binary")

    monkeypatch.setattr(process, "run", explode)
    results = {result.kind: result for result in run_all(load_config(tmp_path))}

    assert set(results) == set(KINDS), "the other checks must still be reported"
    assert results["lint"].source == "error"
    assert results["lint"].ok is False
    assert "tool wrote binary" in results["lint"].output


def test_run_all_is_not_ok_when_one_check_fails(tmp_path: Path) -> None:
    verify_config(tmp_path, lint=py("pass"), types=py("import sys; sys.exit(1)"))

    results = run_all(load_config(tmp_path))

    assert any(result.ok is False for result in results)


def test_run_all_actually_overlaps_the_waiting(tmp_path: Path) -> None:
    """Three identical slow checks must cost far less than three times one.

    Measured against one serial run of the same command rather than against a
    wall-clock constant: an absolute bound would encode this machine's process
    start-up cost, which on a loaded runner is the same order as the sleep.
    """
    slow = py("import time; time.sleep(0.4)")
    verify_config(tmp_path, lint=slow, types=slow, test=slow)
    config = load_config(tmp_path)

    started = time.perf_counter()
    run_check("lint", config)
    one = time.perf_counter() - started

    started = time.perf_counter()
    run_all(config)
    three = time.perf_counter() - started

    assert three < 2 * one + 0.3, (
        f"one check took {one:.2f}s, three concurrent took {three:.2f}s; they did not overlap"
    )


def test_a_directory_that_matches_the_script_glob_is_not_a_script(tmp_path: Path) -> None:
    """`lint.d` is a directory; handing it to subprocess would be nonsense."""
    python_project(tmp_path)
    (tmp_path / ".ultraloom" / "checks" / "lint.d").mkdir(parents=True)

    assert resolve_check("lint", load_config(tmp_path)).source == "preset"


def test_the_python_coverage_preset_measures_before_it_reports(tmp_path: Path) -> None:
    """`coverage report` reads a file it does not create.

    Without a measuring step the preset is red in every project that has not
    run coverage by some other route -- and `run_all` cannot supply one, since
    the four checks run at the same time and `test` measures nothing.
    """
    python_project(tmp_path)

    command = resolve_check("coverage", load_config(tmp_path))

    assert command.measure[:4] == ("uv", "run", "coverage", "run")
    assert command.argvs[0][:4] == ("uv", "run", "coverage", "report")


def test_the_exec_prefix_is_put_in_front_of_the_measuring_step_too(tmp_path: Path) -> None:
    """A check that runs through a boundary runs *both* its steps through it."""
    python_project(tmp_path)
    write_config(tmp_path, '[exec]\nprefix = "docker compose exec -T app"\n')

    command = resolve_check("coverage", load_config(tmp_path))

    assert command.measure[:5] == ("docker", "compose", "exec", "-T", "app")
    assert command.argvs[0][:5] == ("docker", "compose", "exec", "-T", "app")


def test_a_measuring_step_runs_before_the_check_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python_project(tmp_path)
    marker = tmp_path / "measured.txt"
    monkeypatch.setitem(
        PRESETS["pyproject.toml"],
        "coverage",
        Preset(
            tuple(shlex.split(py("import sys; print(open('measured.txt').read())"))),
            measure=tuple(shlex.split(py(f"open({str(marker)!r}, 'w').write('yes')"))),
        ),
    )

    result = run_check("coverage", load_config(tmp_path))

    assert result.ok
    assert "yes" in result.output, "the report's output is what the caller sees"


def test_a_failed_measuring_step_fails_the_check_and_stops_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The report would otherwise run on stale data and call it green."""
    python_project(tmp_path)
    ran = tmp_path / "reported.txt"
    monkeypatch.setitem(
        PRESETS["pyproject.toml"],
        "coverage",
        Preset(
            tuple(shlex.split(py(f"open({str(ran)!r}, 'w').write('x')"))),
            measure=tuple(shlex.split(py("import sys; print('the tests failed'); sys.exit(1)"))),
        ),
    )

    result = run_check("coverage", load_config(tmp_path))

    assert not result.ok
    assert "the tests failed" in result.output
    assert not ran.exists(), "a report on data nobody measured is worse than no report"


def test_a_relative_command_that_cannot_be_found_says_why(tmp_path: Path) -> None:
    """The obvious config entry for a project-local venv, and it cannot work.

    The OS resolves a command against the calling process and PATH, never
    against `cwd`, so a path that is correct from the project root still fails
    -- and a bare "file not found" sends its author looking for a typo.
    """
    python_project(tmp_path)
    verify_config(tmp_path, test=".venv/bin/pytest -q")

    result = run_check("test", load_config(tmp_path))

    assert not result.ok
    assert "relative path" in result.output
    assert "uv run" in result.output


def test_a_bare_command_that_is_not_installed_does_not_get_the_relative_path_hint(
    tmp_path: Path,
) -> None:
    """`no-such-tool` is looked up on PATH, so the hint would misdiagnose it."""
    python_project(tmp_path)
    verify_config(tmp_path, test="ultraloom-no-such-tool --version")

    result = run_check("test", load_config(tmp_path))

    assert not result.ok
    assert "relative path" not in result.output


def _sleep_command(seconds: float) -> str:
    """A command line that does nothing for `seconds`, in this interpreter.

    Built from sys.executable rather than a shell's `sleep`, which Windows
    does not have.
    """
    return py(f"import time; time.sleep({seconds})")


def _argv(command: str) -> tuple[str, ...]:
    return tuple(shlex.split(command))


def test_a_command_that_overruns_is_a_red_result(tmp_path: Path) -> None:
    config = Config(root=tmp_path, commands={"lint": (_sleep_command(5),)}, timeout=1)

    result = run_check("lint", config)

    assert not result.ok
    assert "timed out after 1s" in result.output
    assert result.kind == "lint"


def test_a_command_within_the_limit_is_untouched(tmp_path: Path) -> None:
    config = Config(root=tmp_path, commands={"lint": (_sleep_command(0),)}, timeout=30)

    assert run_check("lint", config).ok


def test_the_measuring_step_gets_the_limit_too(tmp_path: Path) -> None:
    # The measure step is a second process, so a shared budget would make its
    # limit depend on how long the first one took.
    command = Command(
        "coverage", (_argv(_sleep_command(0)),), "test", measure=_argv(_sleep_command(5))
    )
    config = Config(root=tmp_path, timeout=1)

    result = _run_command(command, config)

    assert not result.ok
    assert "timed out after 1s" in result.output


def test_a_truncated_capture_is_never_a_passed_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit code 0 over a prefix of the output is not evidence of anything.

    Faked rather than provoked: a reader is abandoned only when a descendant
    outlives its parent *and* the command still exits by itself, which no real
    command can be made to do reliably.
    """
    truncated = process.Completed(
        returncode=0, stdout="ran 3 of ", stderr="", output_abandoned=True
    )
    monkeypatch.setattr(process, "run", lambda *args, **kwargs: truncated)
    config = Config(root=tmp_path, commands={"lint": (_sleep_command(0),)}, timeout=30)

    result = run_check("lint", config)

    assert not result.ok
    assert "output incomplete" in result.output
    assert "ran 3 of" in result.output


def test_a_configured_coverage_report_is_the_coverage_command(tmp_path: Path) -> None:
    """Found in space: Nano Coverage's gate is neither a preset nor a script.

    `[verify.coverage].report` was read, validated and documented as the
    coverage check's command, and then no code path ever ran it -- a Godot
    project could not configure coverage at all.
    """
    config = Config(root=tmp_path, coverage_report="uv run --script gate.py")

    command = resolve_check("coverage", config)

    assert command.argvs[0] == ("uv", "run", "--script", "gate.py")
    assert command.source == "config"
    assert command.measure == ()


def test_a_blank_coverage_report_command_is_refused(tmp_path: Path) -> None:
    """The same trap as a blank [verify] command: with an [exec] prefix set,
    what is left to run is the bare prefix, and a prefix that exits 0 turns a
    check nobody configured into a green line."""
    config = Config(root=tmp_path, coverage_report="   ")

    with pytest.raises(CheckUnavailableError, match="empty command"):
        resolve_check("coverage", config)


def imported_godot_project(root: Path) -> Path:
    """A Godot project that has been through an editor import once."""
    godot_project(root)
    cache = root / ".godot" / "global_script_class_cache.cfg"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("list=[]\n", encoding="utf-8")
    return root


def test_an_unimported_godot_project_fails_test_before_an_engine_starts(tmp_path: Path) -> None:
    """No engine is started: the result comes back red without any subprocess.

    The preset command is `godot`, which is not installed on the machine this
    test runs on -- so a result that is red for the *right* reason is the only
    way this can pass.
    """
    godot_project(tmp_path)

    result = run_check("test", load_config(tmp_path))

    assert not result.ok
    assert result.source == "unready"
    assert "never been imported" in result.output
    assert "godot --headless --path . --import" in result.output


def test_an_unimported_godot_project_fails_coverage_too(tmp_path: Path) -> None:
    godot_project(tmp_path)
    config = Config(root=tmp_path, coverage_report=py("print('measured')"))

    result = run_check("coverage", config)

    assert not result.ok
    assert result.source == "unready"


def test_an_unimported_godot_project_still_lints(tmp_path: Path) -> None:
    """gdlint reads source text; blocking it would stop a check that works."""
    godot_project(tmp_path)
    verify_config(tmp_path, lint=py("print('linted')"))

    result = run_check("lint", load_config(tmp_path))

    assert result.ok
    assert result.source == "config"


def test_an_imported_godot_project_runs_its_tests(tmp_path: Path) -> None:
    imported_godot_project(tmp_path)
    verify_config(tmp_path, test=py("print('ran')"))

    result = run_check("test", load_config(tmp_path))

    assert result.ok
    assert result.source == "config"


def test_an_empty_godot_cache_directory_is_not_an_import(tmp_path: Path) -> None:
    """The directory exists long before the import that fills it."""
    godot_project(tmp_path)
    (tmp_path / ".godot").mkdir()

    assert run_check("test", load_config(tmp_path)).source == "unready"


def test_a_project_that_configures_test_itself_gets_no_invented_binary(tmp_path: Path) -> None:
    """The preset's `godot` is not this project's engine, so it is not named."""
    godot_project(tmp_path)
    verify_config(tmp_path, test=py("print('ran')"))

    result = run_check("test", load_config(tmp_path))

    assert result.source == "unready"
    assert "godot --headless" not in result.output
    assert "--headless --path . --import" in result.output


def test_the_import_precondition_only_applies_to_godot(tmp_path: Path) -> None:
    python_project(tmp_path)
    verify_config(tmp_path, test=py("print('ran')"))

    assert run_check("test", load_config(tmp_path)).ok


def test_an_unimported_godot_project_reports_unready_from_run_all(tmp_path: Path) -> None:
    godot_project(tmp_path)
    verify_config(tmp_path, lint=py("print('linted')"), test=py("print('ran')"))

    results = {result.kind: result for result in run_all(load_config(tmp_path))}

    assert results["test"].source == "unready"
    assert results["lint"].ok


def test_a_project_that_prepares_its_own_suite_can_turn_the_precondition_off(
    tmp_path: Path,
) -> None:
    """The valve: a Godot project whose own test command runs the import.

    Without it such a project is red on every run and out of the repairer's
    reach as well -- it could never heal itself.
    """
    godot_project(tmp_path)
    write_config(
        tmp_path,
        "[verify]\ngodot_import = false\ntest = " + json.dumps(py("print('ran')")) + "\n",
    )

    result = run_check("test", load_config(tmp_path))

    assert result.ok
    assert result.source == "config"


def test_the_precondition_names_the_key_that_turns_it_off(tmp_path: Path) -> None:
    """Whoever is blocked reads how to unblock themselves."""
    godot_project(tmp_path)

    output = run_check("test", load_config(tmp_path)).output

    assert "godot_import = false" in output


def test_the_coverage_message_does_not_speak_only_of_tests(tmp_path: Path) -> None:
    godot_project(tmp_path)
    config = Config(root=tmp_path, coverage_report=py("print('measured')"))

    assert "no test result" not in run_check("coverage", config).output


def check_script(root: Path, kind: str, code: str) -> None:
    """A check script at the conventional path, in this very interpreter."""
    directory = root / ".ultraloom" / "checks"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{kind}.py").write_text(code, encoding="utf-8")


def test_the_precondition_holds_for_a_project_that_tests_through_a_script(
    tmp_path: Path,
) -> None:
    """The third resolution path, exercised rather than merely covered."""
    godot_project(tmp_path)
    check_script(tmp_path, "test", "print('ran')")

    result = run_check("test", load_config(tmp_path))

    assert not result.ok
    assert result.source == "unready"


def test_a_script_project_gets_no_invented_binary_either(tmp_path: Path) -> None:
    godot_project(tmp_path)
    check_script(tmp_path, "test", "print('ran')")

    output = run_check("test", load_config(tmp_path)).output

    assert "godot --headless" not in output
    assert "--headless --path . --import" in output


def test_a_timed_out_check_names_its_partial_output(tmp_path: Path) -> None:
    """The timeout costs its limit even when a grandchild keeps the pipe open.

    The shape every real check command has: `uv run pytest` is a chain of at
    least two processes. subprocess.run kills the direct child and then waits
    for the pipes, which the surviving grandchild still holds -- so the run
    hangs for as long as the grandchild lives, and the partial output arrives
    only after it dies.
    """
    python_project(tmp_path)
    linger = py("import time; time.sleep(20)")
    config = Config(
        root=tmp_path,
        commands={
            "lint": (
                py(
                    "import shlex, subprocess, sys, time; "
                    "print('half done', flush=True); "
                    f"subprocess.Popen(shlex.split({linger!r})); "
                    "time.sleep(20)"
                ),
            )
        },
        timeout=1,
    )

    started = time.monotonic()
    result = run_check("lint", config)
    elapsed = time.monotonic() - started

    assert not result.ok
    assert "timed out after 1s" in result.output
    assert "half done" in result.output
    assert elapsed < 12, "the run waited for the grandchild instead of for its own limit"


def test_a_configured_kind_resolves_all_its_commands(tmp_path: Path) -> None:
    config = Config(root=tmp_path, commands={"lint": ("first .", "second .")})
    command = resolve_check("lint", config)
    assert command.argvs == (("first", "."), ("second", "."))


def test_every_command_gets_the_exec_prefix(tmp_path: Path) -> None:
    config = Config(
        root=tmp_path,
        commands={"lint": ("first", "second")},
        exec_prefix=("docker", "compose", "exec", "-T", "app"),
    )
    command = resolve_check("lint", config)
    assert all(argv[:5] == ("docker", "compose", "exec", "-T", "app") for argv in command.argvs)


def test_the_threaded_switch_reaches_the_command(tmp_path: Path) -> None:
    config = Config(root=tmp_path, commands={"lint": ("a", "b")}, threaded=frozenset({"lint"}))
    assert resolve_check("lint", config).threaded


def test_every_command_runs_even_after_a_red_one(tmp_path: Path) -> None:
    """A half list of findings costs the repairer a whole extra round."""
    python_project(tmp_path)
    config = Config(
        root=tmp_path,
        commands={
            "lint": (
                py("import sys; print('first says no'); sys.exit(1)"),
                py("print('second still ran')"),
            )
        },
    )

    result = run_check("lint", config)

    assert not result.ok
    assert "first says no" in result.output
    assert "second still ran" in result.output


def test_several_commands_are_labelled_in_the_report(tmp_path: Path) -> None:
    python_project(tmp_path)
    config = Config(root=tmp_path, commands={"lint": (py("print('a')"), py("print('b')"))})

    output = run_check("lint", config).output

    assert output.count("$ ") == 2, "each command names itself, or the report cannot be read"


def test_a_single_command_keeps_the_report_it_always_had(tmp_path: Path) -> None:
    python_project(tmp_path)
    config = Config(root=tmp_path, commands={"lint": (py("print('only')"),)})
    assert run_check("lint", config).output == "only\n"


def test_a_threaded_kind_runs_its_commands_at_the_same_time(tmp_path: Path) -> None:
    python_project(tmp_path)
    sleeper = py("import time; time.sleep(2)")
    config = Config(
        root=tmp_path,
        commands={"lint": (sleeper, sleeper)},
        threaded=frozenset({"lint"}),
        max_parallel=4,
    )

    started = time.monotonic()
    run_check("lint", config)
    elapsed = time.monotonic() - started

    # Two two-second sleeps: sequential is 4s, concurrent is 2s. The bound sits
    # between them with room for a loaded machine, which is why it is 3.5 and
    # not 2.5. Relative and generous on purpose -- this is the suite's second
    # wall-clock test.
    assert elapsed < 3.5, f"the two commands took {elapsed:.1f}s; they did not overlap"


def test_the_report_order_is_the_configured_one_even_when_threaded(tmp_path: Path) -> None:
    """The order commands finish in is noise; a report that reorders cannot be diffed."""
    python_project(tmp_path)
    config = Config(
        root=tmp_path,
        commands={
            "lint": (
                py("import time; time.sleep(1); print('slow first')"),
                py("print('fast second')"),
            )
        },
        threaded=frozenset({"lint"}),
        max_parallel=4,
    )

    output = run_check("lint", config).output

    assert output.index("slow first") < output.index("fast second")


def test_a_warning_rides_in_front_of_the_report_without_being_a_verdict(tmp_path: Path) -> None:
    """Spec 8: reading something no command in this run produced is worth saying,
    but it is never the reason a check is red."""
    python_project(tmp_path)
    command = Command("lint", (_argv(py("print('clean')")),), "config", warning="stale data")

    result = _run_command(command, Config(root=tmp_path))

    assert result.ok
    assert result.output == "stale data\nclean\n"


class _CountingGate(Semaphore):
    """A cap that records how often it was taken."""

    def __init__(self) -> None:
        super().__init__(4)
        self.acquired = 0

    def acquire(self, blocking: bool = True, timeout: float | None = None) -> bool:
        self.acquired += 1
        return super().acquire(blocking, timeout)

    # Semaphore binds __enter__ to acquire at class creation, so an override of
    # acquire alone is never seen by a `with` statement.
    def __enter__(self, blocking: bool = True, timeout: float | None = None) -> bool:
        return self.acquire(blocking, timeout)


def test_a_cap_handed_in_is_the_one_that_is_used(tmp_path: Path) -> None:
    """Task 9 hands one cap down through stages and kinds; a call that quietly
    made its own would let every level spend the whole budget again."""
    python_project(tmp_path)
    command = Command("lint", (_argv(py("print('a')")), _argv(py("print('b')"))), "config")
    gate = _CountingGate()

    _run_command(command, Config(root=tmp_path), gate)

    assert gate.acquired == 2


def test_a_red_command_names_itself_in_the_heading(tmp_path: Path) -> None:
    """A command that fails without a word would otherwise leave a red check
    whose report holds nothing but the green command's findings."""
    python_project(tmp_path)
    config = Config(
        root=tmp_path,
        commands={"lint": (py("print('a')"), py("import sys; sys.exit(1)"))},
    )

    result = run_check("lint", config)

    assert not result.ok
    assert "(failed)" in result.output


def test_a_check_with_no_command_at_all_is_refused(tmp_path: Path) -> None:
    """all(()) is True: nothing run would otherwise be a passed check."""
    with pytest.raises(CheckUnavailableError, match="no command"):
        Command("lint", (), "config")


def test_the_warning_survives_a_failing_measure_step(tmp_path: Path) -> None:
    """The path where the output needs the explanation most is the one that
    used to drop it."""
    python_project(tmp_path)
    command = Command(
        "coverage",
        (_argv(py("print('report')")),),
        "preset",
        measure=_argv(py("import sys; print('measure broke'); sys.exit(1)")),
        warning="stale data",
    )

    result = _run_command(command, Config(root=tmp_path))

    assert not result.ok
    assert result.output.startswith("stale data\n")
    assert "measure broke" in result.output


def test_the_merged_report_ends_in_a_newline_like_a_single_one(tmp_path: Path) -> None:
    """Two shapes of report would make every reader downstream handle both."""
    python_project(tmp_path)
    config = Config(root=tmp_path, commands={"lint": (py("print('a')"), py("print('b')"))})

    assert run_check("lint", config).output.endswith("\n")


def test_the_python_test_preset_can_measure_when_asked() -> None:
    """`measuring` is the second face of `test`: the same suite, counting as it goes.

    Carried here, read by the scheduler later -- nothing in this task acts on it.
    """
    assert PRESETS["pyproject.toml"]["test"].measuring[:4] == ("uv", "run", "coverage", "run")


def test_the_python_coverage_preset_waits_for_test() -> None:
    assert PRESETS["pyproject.toml"]["coverage"].after == "test"


def test_the_python_coverage_preset_can_still_measure_alone() -> None:
    assert PRESETS["pyproject.toml"]["coverage"].measure[:4] == ("uv", "run", "coverage", "run")


def test_godot_has_no_coverage_preset_at_all(tmp_path: Path) -> None:
    """There is no general GDScript coverage command to name, so none is invented.

    Space measures with the Nano Coverage editor addon, which writes lcov.info
    as a by-product of the suite, and enforces the threshold from a script of
    its own. Neither half is a command another Godot project could run.
    """
    assert "coverage" not in PRESETS["project.godot"]

    godot_project(tmp_path)
    with pytest.raises(CheckUnavailableError, match="known limitation"):
        resolve_check("coverage", load_config(tmp_path))


def test_the_node_preset_stays_one_stage() -> None:
    assert PRESETS["package.json"]["coverage"].after == ""


def test_the_presets_ask_their_tools_to_be_terse() -> None:
    """Every token of a check report is a token the repairer pays for, every round."""
    assert "--output-format=concise" in PRESETS["pyproject.toml"]["lint"].argv
    assert "--tb=short" in PRESETS["pyproject.toml"]["test"].argv
    assert "--skip-covered" in PRESETS["pyproject.toml"]["coverage"].argv
    assert "--no-error-summary" in PRESETS["pyproject.toml"]["types"].argv


def test_the_coverage_preset_still_names_the_missing_lines() -> None:
    """The one place where terseness would hide what the repairer needs.

    `--skip-covered` drops the files at 100%; without `-m` what is left names
    the file at 83% and not the line that is missing, and looking it up costs a
    whole round. `show_missing` is off by default, so the project cannot be
    assumed to have set it.
    """
    assert "-m" in PRESETS["pyproject.toml"]["coverage"].argv


def test_both_pytest_modes_are_asked_for_the_same_terseness() -> None:
    """`test` and test-under-measurement must report in the same shape.

    A flag that reached only one of them would make the two modes incomparable,
    which is the whole reason the scheduler may swap one for the other.
    """
    presets = PRESETS["pyproject.toml"]
    terse = ("-q", "--tb=short", "--no-header")
    assert presets["test"].argv[-len(terse) :] == terse
    assert presets["test"].measuring[-len(terse) :] == terse
    assert presets["coverage"].measure[-len(terse) :] == terse


def test_a_preset_resolves_to_one_command(tmp_path: Path) -> None:
    python_project(tmp_path)

    command = resolve_check("lint", load_config(tmp_path))

    assert command.source == "preset"
    assert len(command.argvs) == 1


def test_test_measures_when_coverage_runs_too(tmp_path: Path) -> None:
    python_project(tmp_path)
    command = resolve_check(
        "test", Config(root=tmp_path), alongside=frozenset({"test", "coverage"})
    )
    assert command.argvs[0][:4] == ("uv", "run", "coverage", "run")


def test_test_alone_stays_the_fast_path(tmp_path: Path) -> None:
    python_project(tmp_path)
    command = resolve_check("test", Config(root=tmp_path), alongside=frozenset({"test"}))
    assert command.argvs[0][:3] == ("uv", "run", "pytest")


def test_coverage_drops_its_own_measuring_when_test_measures_for_it(tmp_path: Path) -> None:
    python_project(tmp_path)
    command = resolve_check(
        "coverage", Config(root=tmp_path), alongside=frozenset({"test", "coverage"})
    )
    assert command.measure == (), "the suite must not run twice in one pass"


def test_coverage_alone_measures_for_itself(tmp_path: Path) -> None:
    python_project(tmp_path)
    command = resolve_check("coverage", Config(root=tmp_path), alongside=frozenset({"coverage"}))
    assert command.measure[:4] == ("uv", "run", "coverage", "run")


def test_the_empty_default_behaves_like_running_alone(tmp_path: Path) -> None:
    """Every existing caller keeps the behaviour it had."""
    python_project(tmp_path)
    assert resolve_check("coverage", Config(root=tmp_path)).measure[:4] == (
        "uv",
        "run",
        "coverage",
        "run",
    )


def test_a_configured_test_command_never_counts_as_measuring(tmp_path: Path) -> None:
    """ultraloom cannot know whether a foreign test command measures, so it does not guess."""
    python_project(tmp_path)
    config = Config(root=tmp_path, commands={"test": ("my-own-suite",)})
    command = resolve_check("coverage", config, alongside=frozenset({"test", "coverage"}))
    assert command.measure[:4] == ("uv", "run", "coverage", "run")


def test_a_test_script_never_counts_as_measuring(tmp_path: Path) -> None:
    """Same reason as a configured command: a project's own script may measure nothing."""
    python_project(tmp_path)
    scripts = tmp_path / ".ultraloom" / "checks"
    scripts.mkdir(parents=True)
    (scripts / "test.bat").write_text("echo hi\n", encoding="utf-8")
    command = resolve_check(
        "coverage", Config(root=tmp_path), alongside=frozenset({"test", "coverage"})
    )
    assert command.measure[:4] == ("uv", "run", "coverage", "run")


def test_a_configured_report_warns_when_what_it_reads_never_ran(tmp_path: Path) -> None:
    """A report with no measuring step of its own, and no measurer in this pass."""
    godot_project(tmp_path)
    config = Config(root=tmp_path, coverage_report="check-lcov", after={"coverage": "test"})
    command = resolve_check("coverage", config, alongside=frozenset({"coverage"}))
    assert "lief in diesem Lauf nicht" in command.warning


def test_a_predecessor_that_runs_silences_the_warning(tmp_path: Path) -> None:
    """GDScript's `test` has no measuring mode, and ultraloom still does not warn.

    Whether a run of `test` left anything behind is what ultraloom structurally
    cannot know. Warning about it would put the line on every Godot run, and a
    warning that always comes stops being read.
    """
    godot_project(tmp_path)
    config = Config(root=tmp_path, coverage_report="check-lcov", after={"coverage": "test"})
    command = resolve_check("coverage", config, alongside=frozenset({"test", "coverage"}))
    assert command.warning == ""


def test_a_plain_ordering_edge_never_warns(tmp_path: Path) -> None:
    """`[verify.after]` orders all four kinds; `test` after `types` carries no data."""
    python_project(tmp_path)
    config = Config(root=tmp_path, after={"test": "types"})
    command = resolve_check("test", config, alongside=frozenset({"types", "test"}))
    assert command.warning == ""


def test_measuring_is_not_switched_on_for_a_dependant_that_cannot_run(tmp_path: Path) -> None:
    """Measuring for a check that leaves the pass unresolved would be work for nobody."""
    python_project(tmp_path)
    # An empty report command: `coverage` depends on `test` and is unavailable.
    config = Config(root=tmp_path, coverage_report="")
    with pytest.raises(CheckUnavailableError):
        resolve_check("coverage", config)
    command = resolve_check("test", config, alongside=frozenset({"test", "coverage"}))
    assert command.argvs[0][:3] == ("uv", "run", "pytest")


def test_a_configured_report_is_quiet_when_test_measures_for_it(tmp_path: Path) -> None:
    python_project(tmp_path)
    config = Config(root=tmp_path, coverage_report="coverage report", after={"coverage": "test"})
    command = resolve_check("coverage", config, alongside=frozenset({"test", "coverage"}))
    assert command.warning == ""


def test_a_report_in_a_project_of_no_known_language_warns_too(tmp_path: Path) -> None:
    """No marker file, so the predecessor can only come from the project's own [verify.after]."""
    config = Config(root=tmp_path, coverage_report="check-lcov", after={"coverage": "test"})
    command = resolve_check("coverage", config, alongside=frozenset({"coverage"}))
    assert "lief in diesem Lauf nicht" in command.warning


def test_run_check_takes_the_pass_along(tmp_path: Path) -> None:
    """The warning reaches the report, not just the Command."""
    config = Config(
        root=tmp_path,
        coverage_report=py("print('report')"),
        after={"coverage": "test"},
    )
    result = run_check("coverage", config, frozenset({"coverage"}))
    assert result.output.startswith("Achtung:")
    assert result.ok


def test_no_known_language_means_no_language_measurer(tmp_path: Path) -> None:
    """Without a marker there is no preset to ask whether the predecessor measures."""
    config = Config(root=tmp_path, coverage_report="check-lcov", after={"coverage": "test"})
    command = resolve_check("coverage", config, alongside=frozenset({"test", "coverage"}))
    assert command.measure == ()
    assert command.warning == ""


def _fake(record: list[str], red: set[str] | None = None) -> CheckRunner:
    """A runner that records what it was asked to run and never starts a process."""
    failing = red or set()

    def runner(kind: str, config: Config, alongside: frozenset[str]) -> CheckResult:
        record.append(kind)
        return CheckResult(kind, kind not in failing, "", "fake")

    return runner


def test_coverage_runs_after_test(tmp_path: Path) -> None:
    python_project(tmp_path)
    record: list[str] = []

    run_kinds(("lint", "types", "test", "coverage"), Config(root=tmp_path), _fake(record))

    assert record.index("coverage") > record.index("test")


def test_a_red_predecessor_blocks_its_dependant(tmp_path: Path) -> None:
    python_project(tmp_path)

    results = run_kinds(("test", "coverage"), Config(root=tmp_path), _fake([], red={"test"}))

    coverage = next(result for result in results if result.kind == "coverage")
    assert not coverage.ok
    assert coverage.source == BLOCKED
    assert "test" in coverage.output


def test_a_blocked_check_never_starts_its_tool(tmp_path: Path) -> None:
    python_project(tmp_path)
    record: list[str] = []

    run_kinds(("test", "coverage"), Config(root=tmp_path), _fake(record, red={"test"}))

    assert "coverage" not in record


def test_blocking_is_transitive(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify.after]\ncoverage = "test"\ntest = "lint"\n')
    python_project(tmp_path)

    results = run_kinds(
        ("lint", "test", "coverage"), load_config(tmp_path), _fake([], red={"lint"})
    )

    assert [result.source for result in results if result.kind != "lint"] == [BLOCKED, BLOCKED]


def test_an_unavailable_predecessor_blocks_too(tmp_path: Path) -> None:
    """Red is red: a missing tool leaves nothing for the dependant to read either."""

    def runner(kind: str, config: Config, alongside: frozenset[str]) -> CheckResult:
        if kind == "test":
            raise CheckUnavailableError("no suite here")
        return CheckResult(kind, True, "", "fake")

    python_project(tmp_path)

    results = run_kinds(("test", "coverage"), Config(root=tmp_path), runner)

    assert [result.source for result in results] == ["unavailable", BLOCKED]


def test_an_unready_predecessor_blocks_too(tmp_path: Path) -> None:
    """The stale-report coupling in _measures_for: `coverage` already dropped its
    own measuring step because `test` was asked for, so a `test` that never ran
    must not leave `coverage` reading whatever an earlier run wrote."""

    def runner(kind: str, config: Config, alongside: frozenset[str]) -> CheckResult:
        return CheckResult(kind, kind != "test", "never imported", UNREADY)

    python_project(tmp_path)

    results = run_kinds(("test", "coverage"), Config(root=tmp_path), runner)

    assert [result.source for result in results] == [UNREADY, BLOCKED]


def test_a_kind_whose_predecessor_was_not_asked_for_runs_at_once(tmp_path: Path) -> None:
    python_project(tmp_path)
    record: list[str] = []

    run_kinds(("coverage",), Config(root=tmp_path), _fake(record))

    assert record == ["coverage"]


def test_an_after_edge_onto_a_kind_outside_the_run_is_dropped(tmp_path: Path) -> None:
    """The last way [verify.after] could hang: waiting for something never asked for."""
    write_config(tmp_path, '[verify.after]\ncoverage = "test"\n')
    python_project(tmp_path)
    record: list[str] = []

    results = run_kinds(("lint", "coverage"), load_config(tmp_path), _fake(record))

    assert record == ["lint", "coverage"] or record == ["coverage", "lint"]
    assert all(result.ok for result in results)


def test_the_results_keep_the_order_they_were_asked_in(tmp_path: Path) -> None:
    python_project(tmp_path)

    results = run_kinds(("coverage", "lint", "test"), Config(root=tmp_path), _fake([]))

    assert [result.kind for result in results] == ["coverage", "lint", "test"]


def test_every_check_learns_who_else_is_running(tmp_path: Path) -> None:
    seen: list[frozenset[str]] = []

    def runner(kind: str, config: Config, alongside: frozenset[str]) -> CheckResult:
        seen.append(alongside)
        return CheckResult(kind, True, "", "fake")

    python_project(tmp_path)
    run_kinds(("test", "coverage"), Config(root=tmp_path), runner)

    assert all(group == frozenset({"test", "coverage"}) for group in seen)


def test_a_check_that_blows_up_does_not_discard_the_others(tmp_path: Path) -> None:
    def runner(kind: str, config: Config, alongside: frozenset[str]) -> CheckResult:
        if kind == "lint":
            raise RuntimeError("boom")
        return CheckResult(kind, True, "", "fake")

    python_project(tmp_path)

    results = run_kinds(("lint", "types"), Config(root=tmp_path), runner)

    assert [result.source for result in results] == ["error", "fake"]


def test_a_run_that_checks_nothing_is_refused(tmp_path: Path) -> None:
    """An empty run would report `all(())` -- a pass over nothing."""
    with pytest.raises(ValueError, match="at least one check"):
        run_kinds((), Config(root=tmp_path))


def test_one_cap_covers_the_whole_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """max_parallel is a cap per run, not per check kind.

    Each kind used to build its own, so four kinds under max_parallel = 2 could
    be eight processes at once.
    """
    seen: list[Semaphore | None] = []

    def spy(
        kind: str,
        config: Config,
        alongside: frozenset[str] = frozenset(),
        gate: Semaphore | None = None,
    ) -> CheckResult:
        seen.append(gate)
        return CheckResult(kind, True, "", "fake")

    python_project(tmp_path)
    monkeypatch.setattr(checks, "run_check", spy)
    run_kinds(("lint", "types", "test", "coverage"), Config(root=tmp_path))

    assert len(seen) == 4
    assert all(gate is seen[0] for gate in seen)
    assert seen[0] is not None


def test_run_check_hands_the_cap_it_was_given_down(tmp_path: Path) -> None:
    python_project(tmp_path)
    config = Config(root=tmp_path, commands={"lint": (py("print('a')"), py("print('b')"))})
    gate = _CountingGate()

    run_check("lint", config, frozenset({"lint"}), gate)

    assert gate.acquired == 2


def test_run_all_still_runs_every_kind(tmp_path: Path) -> None:
    python_project(tmp_path)

    assert tuple(result.kind for result in run_all(Config(root=tmp_path))) == KINDS
