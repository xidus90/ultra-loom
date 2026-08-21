"""Tests for resolving and running the check chain."""

import json
import shlex
import sys
import time
from pathlib import Path

import pytest

from ultraloom.checks import KINDS, CheckUnavailableError, resolve_check, run_all, run_check
from ultraloom.config import load_config

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

    assert command.argv == ("my-own-linter", "--strict")
    assert command.source == "config"


def test_a_convention_script_beats_the_preset(tmp_path: Path) -> None:
    python_project(tmp_path)
    script = tmp_path / ".ultraloom" / "checks" / "lint.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('linted')\n", encoding="utf-8")

    command = resolve_check("lint", load_config(tmp_path))

    assert command.source == "script"
    assert str(script) in " ".join(command.argv)
    assert command.argv[0] == sys.executable


def test_a_script_in_another_language_is_run_directly(tmp_path: Path) -> None:
    """Only a .py script gets this interpreter put in front of it."""
    python_project(tmp_path)
    script = tmp_path / ".ultraloom" / "checks" / "lint.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/sh\n", encoding="utf-8")

    assert resolve_check("lint", load_config(tmp_path)).argv == (str(script),)


def test_an_empty_checks_directory_falls_through_to_the_preset(tmp_path: Path) -> None:
    python_project(tmp_path)
    (tmp_path / ".ultraloom" / "checks").mkdir(parents=True)

    assert resolve_check("lint", load_config(tmp_path)).source == "preset"


def test_the_python_preset_is_found_from_pyproject(tmp_path: Path) -> None:
    python_project(tmp_path)

    command = resolve_check("types", load_config(tmp_path))

    assert command.source == "preset"
    assert command.argv[:2] == ("uvx", "mypy")


def test_the_node_preset_is_found_from_package_json(tmp_path: Path) -> None:
    node_project(tmp_path)

    assert resolve_check("types", load_config(tmp_path)).argv == ("tsc", "--noEmit")
    assert resolve_check("lint", load_config(tmp_path)).argv == ("eslint", ".")


def test_the_godot_preset_is_found_from_project_godot(tmp_path: Path) -> None:
    godot_project(tmp_path)

    assert resolve_check("lint", load_config(tmp_path)).argv == ("uvx", "gdlint", ".")


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

    assert command.argv == ("docker", "compose", "exec", "-T", "frontend", "eslint", ".")


def test_the_exec_prefix_is_put_in_front_of_a_configured_command(tmp_path: Path) -> None:
    node_project(tmp_path)
    write_config(
        tmp_path,
        '[exec]\nprefix = "docker compose exec -T web"\n[verify]\nlint = "biome check"\n',
    )

    assert resolve_check("lint", load_config(tmp_path)).argv == (
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


def test_run_all_is_not_ok_when_one_check_fails(tmp_path: Path) -> None:
    verify_config(tmp_path, lint=py("pass"), types=py("import sys; sys.exit(1)"))

    results = run_all(load_config(tmp_path))

    assert any(result.ok is False for result in results)


def test_run_all_actually_overlaps_the_waiting(tmp_path: Path) -> None:
    """The whole point: three 400 ms checks must not take 1.2 s."""
    slow = py("import time; time.sleep(0.4)")
    verify_config(tmp_path, lint=slow, types=slow, test=slow)
    started = time.perf_counter()

    run_all(load_config(tmp_path))

    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"three 0.4 s checks took {elapsed:.2f}s; they did not overlap"


def test_the_checks_module_does_not_import_the_harness() -> None:
    """Spec 15.2: the check side must stay installable without the agent extra."""
    import ultraloom.checks as module

    assert module.__file__ is not None
    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("from ultraloom.graph", "from ultraloom.runner", "from ultraloom.model"):
        assert forbidden not in source
