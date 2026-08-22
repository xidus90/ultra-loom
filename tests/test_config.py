"""Tests for reading .ultraloom/config.toml."""

import textwrap
from pathlib import Path

import pytest

from ultraloom.config import CONFIG_NAME, Config, ConfigError, load_config


def write_config(root: Path, body: str) -> None:
    target = root / ".ultraloom" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(body), encoding="utf-8")


def test_a_project_without_a_config_gets_empty_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config.root == tmp_path
    assert config.commands == {}
    assert config.threaded == frozenset()
    assert config.exec_prefix == ()
    assert config.coverage_report is None
    assert config.coverage_threshold == 100
    assert config.mcp_servers == ()


def test_check_commands_are_read(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify]\nlint = "uvx gdlint ."\ntest = "godot --headless"\n')

    config = load_config(tmp_path)

    assert config.commands["lint"] == ("uvx gdlint .",)
    assert config.commands["test"] == ("godot --headless",)


def test_a_string_command_stays_one_command(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify]\nlint = "gdlint ."\n')

    assert load_config(tmp_path).commands["lint"] == ("gdlint .",)


def test_a_list_holds_several_commands_in_order(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify]\nlint = ["gdlint .", "gdformat --check ."]\n')

    assert load_config(tmp_path).commands["lint"] == ("gdlint .", "gdformat --check .")


def test_the_table_form_carries_commands_and_the_switch(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        '[verify.lint]\ncommands = ["gdlint .", "gdformat --check ."]\nthreaded = true\n',
    )

    config = load_config(tmp_path)

    assert config.commands["lint"] == ("gdlint .", "gdformat --check .")
    assert "lint" in config.threaded


def test_threaded_defaults_to_off(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify.lint]\ncommands = ["gdlint ."]\n')

    assert load_config(tmp_path).threaded == frozenset()


def test_the_table_form_needs_commands(tmp_path: Path) -> None:
    write_config(tmp_path, "[verify.lint]\nthreaded = true\n")

    with pytest.raises(ConfigError, match="commands"):
        load_config(tmp_path)


def test_the_table_form_wants_a_list_of_commands(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify.lint]\ncommands = "gdlint ."\n')

    with pytest.raises(ConfigError, match="list of strings"):
        load_config(tmp_path)


def test_an_empty_command_list_is_refused(tmp_path: Path) -> None:
    """A kind that names no command is a check nobody runs -- and it must not look green."""
    write_config(tmp_path, "[verify.lint]\ncommands = []\n")

    with pytest.raises(ConfigError, match="empty"):
        load_config(tmp_path)


def test_a_blank_command_is_refused(tmp_path: Path) -> None:
    """Moved here from resolve_check: the file is refused before anything runs."""
    write_config(tmp_path, '[verify]\nlint = ""\n')

    with pytest.raises(ConfigError, match="empty"):
        load_config(tmp_path)


def test_a_blank_command_is_refused_even_with_an_exec_prefix(tmp_path: Path) -> None:
    """Otherwise the bare prefix runs, and a prefix that exits 0 reports green.

    Checked at load time, before the prefix can be prepended: with a prefix
    configured, a blank command line leaves the bare prefix to run.
    """
    write_config(
        tmp_path,
        '[exec]\nprefix = "docker compose exec -T web"\n[verify]\nlint = ""\n',
    )

    with pytest.raises(ConfigError, match="empty"):
        load_config(tmp_path)


def test_a_blank_command_in_a_list_is_refused(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify]\nlint = ["gdlint .", "  "]\n')

    with pytest.raises(ConfigError, match="empty"):
        load_config(tmp_path)


def test_a_command_that_is_not_a_string_is_refused(tmp_path: Path) -> None:
    write_config(tmp_path, "[verify]\nlint = [7]\n")

    with pytest.raises(ConfigError, match="strings"):
        load_config(tmp_path)


def test_a_command_of_an_unusable_shape_is_refused(tmp_path: Path) -> None:
    """A number is neither of the three shapes, and must not read as no config at all."""
    write_config(tmp_path, "[verify]\nlint = 7\n")

    with pytest.raises(ConfigError, match="must be a string, a list of strings, or a table"):
        load_config(tmp_path)


def test_threaded_must_be_a_boolean(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify.lint]\ncommands = ["x"]\nthreaded = 1\n')

    with pytest.raises(ConfigError, match="true or false"):
        load_config(tmp_path)


def test_a_command_of_an_unknown_kind_is_ignored(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify]\nlint = "ruff check ."\ndeploy = "ship it"\n')

    assert load_config(tmp_path).commands == {"lint": ("ruff check .",)}


def test_the_exec_prefix_is_split_into_argv(tmp_path: Path) -> None:
    write_config(tmp_path, '[exec]\nprefix = "docker compose exec -T frontend"\n')

    assert load_config(tmp_path).exec_prefix == ("docker", "compose", "exec", "-T", "frontend")


def test_coverage_report_and_threshold_are_read(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        '[verify]\n[verify.coverage]\nreport = "coverage-report/lcov.info"\nthreshold = 90\n',
    )

    config = load_config(tmp_path)

    assert config.coverage_report == "coverage-report/lcov.info"
    assert config.coverage_threshold == 90


def test_mcp_servers_are_read(tmp_path: Path) -> None:
    write_config(tmp_path, '[agent]\nmcp_servers = ["ultra-brain"]\n')

    assert load_config(tmp_path).mcp_servers == ("ultra-brain",)


def test_broken_toml_is_reported_with_the_path(tmp_path: Path) -> None:
    write_config(tmp_path, "this is not toml =\n")

    with pytest.raises(ConfigError, match=r"config\.toml"):
        load_config(tmp_path)


def test_a_non_string_command_is_refused(tmp_path: Path) -> None:
    write_config(tmp_path, "[verify]\nlint = 7\n")

    with pytest.raises(ConfigError, match="lint"):
        load_config(tmp_path)


def test_a_non_integer_threshold_is_refused(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify]\n[verify.coverage]\nthreshold = "all of it"\n')

    with pytest.raises(ConfigError, match="threshold"):
        load_config(tmp_path)


def test_a_boolean_threshold_is_refused(tmp_path: Path) -> None:
    """TOML's true is an int to Python, and a threshold of one percent is nobody's intent."""
    write_config(tmp_path, "[verify]\n[verify.coverage]\nthreshold = true\n")

    with pytest.raises(ConfigError, match="threshold"):
        load_config(tmp_path)


def test_a_non_string_coverage_report_is_refused(tmp_path: Path) -> None:
    write_config(tmp_path, "[verify]\n[verify.coverage]\nreport = 3\n")

    with pytest.raises(ConfigError, match="report"):
        load_config(tmp_path)


def test_a_non_string_exec_prefix_is_refused(tmp_path: Path) -> None:
    write_config(tmp_path, '[exec]\nprefix = ["docker", "compose"]\n')

    with pytest.raises(ConfigError, match="prefix"):
        load_config(tmp_path)


def test_mcp_servers_that_are_not_a_list_of_strings_are_refused(tmp_path: Path) -> None:
    write_config(tmp_path, "[agent]\nmcp_servers = [1]\n")

    with pytest.raises(ConfigError, match="mcp_servers"):
        load_config(tmp_path)


def test_mcp_servers_given_as_a_bare_string_are_refused(tmp_path: Path) -> None:
    write_config(tmp_path, '[agent]\nmcp_servers = "ultra-brain"\n')

    with pytest.raises(ConfigError, match="mcp_servers"):
        load_config(tmp_path)


def test_a_section_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    write_config(tmp_path, 'verify = "everything"\n')

    with pytest.raises(ConfigError, match=r"\[verify\]"):
        load_config(tmp_path)


def test_a_coverage_key_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    write_config(tmp_path, '[verify]\ncoverage = "yes please"\n')

    with pytest.raises(ConfigError, match=r"\[coverage\]"):
        load_config(tmp_path)


def test_the_config_module_does_not_import_the_harness() -> None:
    """Spec 15.2: the check side must stay installable without the agent extra."""
    import ultraloom.config as module

    assert module.__file__ is not None
    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("from ultraloom.graph", "from ultraloom.runner", "from ultraloom.model"):
        assert forbidden not in source


def test_a_config_path_that_is_a_directory_is_not_a_config(tmp_path: Path) -> None:
    """`exists()` is true for a directory, and read_text would raise past every handler."""
    (tmp_path / CONFIG_NAME).mkdir(parents=True)

    assert load_config(tmp_path) == Config(tmp_path)


def test_reads_test_paths_timeout_and_profiles(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        """
        [verify]
        tests = ["tests/", "conftest.py"]
        timeout = 90

        [verify.profiles]
        edit = ["lint", "types"]
        precommit = ["lint", "types", "test", "coverage"]
        """,
    )

    config = load_config(tmp_path)

    assert config.test_paths == ("tests/", "conftest.py")
    assert config.timeout == 90
    assert config.profiles["edit"] == ("lint", "types")
    assert config.profiles["precommit"] == ("lint", "types", "test", "coverage")


def test_defaults_when_the_keys_are_absent(tmp_path: Path) -> None:
    write_config(tmp_path, "[verify]\nlint = 'uvx ruff check .'\n")

    config = load_config(tmp_path)

    assert config.test_paths == ()
    assert config.timeout == 600
    assert config.profiles == {}


def test_rejects_a_profile_naming_an_unknown_check(tmp_path: Path) -> None:
    write_config(tmp_path, "[verify.profiles]\nedit = ['lint', 'spelling']\n")

    with pytest.raises(ConfigError, match="unknown check 'spelling'"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("[verify]\ntests = 'tests/'\n", r"\[verify\].tests must be a list of strings"),
        # The right half of each `or`: a list whose elements are not all
        # strings. The `not isinstance(..., list)` case above short-circuits
        # before `all(...)` ever sees an element.
        ("[verify]\ntests = ['tests/', 1]\n", r"\[verify\].tests must be a list of strings"),
        ("[verify]\ntimeout = '90'\n", r"\[verify\].timeout must be an integer"),
        ("[verify]\ntimeout = 0\n", r"\[verify\].timeout must be greater than zero"),
        ("[verify]\ntimeout = true\n", r"\[verify\].timeout must be an integer"),
        ("[verify]\ngodot_import = 'yes'\n", r"\[verify\].godot_import must be true or false"),
        ("[verify]\ngodot_import = 1\n", r"\[verify\].godot_import must be true or false"),
        ("[verify.profiles]\nedit = 'lint'\n", r"\[verify.profiles\].edit must be a list"),
        ("[verify.profiles]\nedit = ['lint', 2]\n", r"\[verify.profiles\].edit must be a list"),
    ],
)
def test_refuses_a_malformed_value(tmp_path: Path, body: str, message: str) -> None:
    write_config(tmp_path, body)

    with pytest.raises(ConfigError, match=message):
        load_config(tmp_path)


def test_the_profile_kinds_match_the_check_kinds() -> None:
    # The copy in config._CHECK_KINDS exists to keep the dependency direction;
    # this is what stops it from drifting away from the original. The import is
    # local because a module-level import of checks would put the check side
    # into this module's import graph ahead of the boundary it guards.
    import ultraloom.config as config_module
    from ultraloom.checks import KINDS

    assert config_module._CHECK_KINDS == KINDS


def test_the_godot_import_precondition_is_on_unless_a_project_turns_it_off(
    tmp_path: Path,
) -> None:
    """A project that prepares its own suite says so; nobody else has to."""
    assert load_config(tmp_path).godot_import is True

    write_config(tmp_path, "[verify]\ngodot_import = false\n")

    assert load_config(tmp_path).godot_import is False
