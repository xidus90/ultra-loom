"""Tests for the tool profiles that bound what an AgentNode can touch."""

import pytest

from ultraloom.tools import PROFILES, UnknownProfileError, resolve_tools


def test_the_default_profile_cannot_write() -> None:
    """A node that only reads must be unable to write, not merely willing."""
    assert resolve_tools("read_only") == ("Glob", "Grep", "Read")
    assert "Edit" not in resolve_tools("read_only")
    assert "Write" not in resolve_tools("read_only")
    assert "Bash" not in resolve_tools("read_only")


def test_the_edit_profile_adds_writing_to_reading() -> None:
    assert resolve_tools("edit") == ("Edit", "Glob", "Grep", "Read", "Write")


def test_the_shell_profile_adds_bash_but_not_writing() -> None:
    tools = resolve_tools("shell")

    assert "Bash" in tools
    assert "Edit" not in tools, "a shell profile must not smuggle in an edit tool"


def test_the_mcp_profile_adds_the_configured_servers() -> None:
    assert resolve_tools("mcp", ["ultra-brain"]) == ("Glob", "Grep", "Read", "mcp__ultra-brain")


def test_the_mcp_profile_without_servers_is_just_reading() -> None:
    assert resolve_tools("mcp") == ("Glob", "Grep", "Read")


def test_servers_are_ignored_by_profiles_that_do_not_ask_for_them() -> None:
    assert resolve_tools("read_only", ["ultra-brain"]) == ("Glob", "Grep", "Read")


def test_an_unknown_profile_is_refused_with_the_known_ones_named() -> None:
    with pytest.raises(UnknownProfileError, match="read_only"):
        resolve_tools("everything")


def test_every_profile_is_sorted_and_free_of_duplicates() -> None:
    """The tool list feeds a prompt cache prefix; unstable order would break it."""
    for name, tools in PROFILES.items():
        assert list(tools) == sorted(set(tools)), f"profile {name} is unsorted or repeats a tool"


def test_the_profile_table_cannot_be_widened_at_runtime() -> None:
    """With `dontAsk`, these profiles are the only ceiling an agent node has."""
    with pytest.raises(TypeError):
        PROFILES["read_only"] = ("Bash",)  # type: ignore[index]  # the point of the test
