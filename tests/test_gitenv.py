"""Tests for keeping git's own environment out of ultraloom's git calls."""

from __future__ import annotations

from ultraloom.gitenv import GIT_LOCATION_VARS, without_location


def test_without_location_drops_every_pointer_it_names() -> None:
    parent = {name: f"/repo/{name.lower()}" for name in GIT_LOCATION_VARS}
    assert without_location(parent | {"PATH": "/usr/bin"}) == {"PATH": "/usr/bin"}


def test_without_location_keeps_gits_other_variables() -> None:
    """Only what redirects git at a repository goes; the rest is the user's."""
    parent = {"GIT_AUTHOR_NAME": "Someone", "GIT_EDITOR": "vi", "GIT_TERMINAL_PROMPT": "0"}
    assert without_location(parent) == parent


def test_the_list_names_no_variable_twice() -> None:
    """Two copies of a name would hide a typo in one of them."""
    assert len(set(GIT_LOCATION_VARS)) == len(GIT_LOCATION_VARS)
