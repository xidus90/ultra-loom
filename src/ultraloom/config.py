"""Reading a project's .ultraloom/config.toml.

Configuration says two independent things: which tool runs a check, and where
it runs. Splitting those is what lets a project that checks through a container
boundary still profit from the language presets.
"""

from __future__ import annotations

import shlex
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_NAME = ".ultraloom/config.toml"

_KINDS = ("lint", "types", "test")

# The check kinds a profile may name. Deliberately a copy of checks.KINDS and
# not an import: config sits below checks, and test_module_boundary keeps it
# there. test_config asserts the two lists stay equal.
_CHECK_KINDS = ("lint", "types", "test", "coverage")

# Seconds per check command. The order of magnitude space's headless Godot
# suite needs; a project that runs longer says so rather than inheriting a
# limit that was chosen for somebody else's tools.
DEFAULT_TIMEOUT = 600


class ConfigError(ValueError):
    """Raised for a config file that cannot be read or means two things."""


@dataclass(frozen=True, slots=True)
class Config:
    """What a project says about how it is checked."""

    root: Path
    commands: Mapping[str, str] = field(default_factory=dict)
    exec_prefix: tuple[str, ...] = ()
    coverage_report: str | None = None
    coverage_threshold: int = 100
    mcp_servers: tuple[str, ...] = ()
    test_paths: tuple[str, ...] = ()
    timeout: int = DEFAULT_TIMEOUT
    godot_import: bool = True
    profiles: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def load_config(root: Path) -> Config:
    """Read the project's configuration, or return empty defaults."""
    path = root / CONFIG_NAME
    # is_file() and not exists(): a *directory* of that name exists, and
    # read_text would raise IsADirectoryError past every ConfigError handler.
    if not path.is_file():
        return Config(root)

    try:
        # tomllib returns nested tables of unknown shape; every field below is
        # narrowed explicitly, which is why the raw mapping is typed loosely.
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error

    verify = _table(raw, "verify", path)
    coverage = _table(verify, "coverage", path)
    agent = _table(raw, "agent", path)

    commands: dict[str, str] = {}
    for kind in _KINDS:
        if kind not in verify:
            continue
        value = verify[kind]
        if not isinstance(value, str):
            raise ConfigError(f"{path}: [verify].{kind} must be a string")
        commands[kind] = value

    raw_tests = verify.get("tests", [])
    if not isinstance(raw_tests, list) or not all(isinstance(item, str) for item in raw_tests):
        raise ConfigError(f"{path}: [verify].tests must be a list of strings")

    timeout = verify.get("timeout", DEFAULT_TIMEOUT)
    # TOML's booleans are Python ints, and `timeout = true` is nobody's intent.
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        raise ConfigError(f"{path}: [verify].timeout must be an integer")
    if timeout <= 0:
        raise ConfigError(f"{path}: [verify].timeout must be greater than zero")

    godot_import = verify.get("godot_import", True)
    # A valve, not a switch anybody has to find: the import precondition holds
    # for every Godot project, and only a project whose own test command runs
    # the import turns it off. Booleans are ints in TOML, so `1` is refused
    # rather than silently read as "on".
    if not isinstance(godot_import, bool):
        raise ConfigError(f"{path}: [verify].godot_import must be true or false")

    profiles: dict[str, tuple[str, ...]] = {}
    for name, kinds in _table(verify, "profiles", path).items():
        if not isinstance(kinds, list) or not all(isinstance(kind, str) for kind in kinds):
            raise ConfigError(f"{path}: [verify.profiles].{name} must be a list of strings")
        for kind in kinds:
            # Caught here rather than at run time: a profile is read once, at
            # the start of a run, and a typo that only surfaces as a red check
            # halfway through looks like a finding rather than a mistake.
            if kind not in _CHECK_KINDS:
                raise ConfigError(f"{path}: [verify.profiles].{name} names unknown check {kind!r}")
        profiles[name] = tuple(kinds)

    threshold = coverage.get("threshold", 100)
    # TOML's booleans are Python ints, and a threshold of one percent is nobody's intent.
    if not isinstance(threshold, int) or isinstance(threshold, bool):
        raise ConfigError(f"{path}: [verify.coverage].threshold must be an integer")

    report = coverage.get("report")
    if report is not None and not isinstance(report, str):
        raise ConfigError(f"{path}: [verify.coverage].report must be a string")

    prefix = _table(raw, "exec", path).get("prefix", "")
    if not isinstance(prefix, str):
        raise ConfigError(f"{path}: [exec].prefix must be a string")

    servers = agent.get("mcp_servers", [])
    if not isinstance(servers, list) or not all(isinstance(name, str) for name in servers):
        raise ConfigError(f"{path}: [agent].mcp_servers must be a list of strings")

    return Config(
        root=root,
        commands=commands,
        exec_prefix=tuple(shlex.split(prefix)),
        coverage_report=report,
        coverage_threshold=threshold,
        mcp_servers=tuple(servers),
        test_paths=tuple(raw_tests),
        timeout=timeout,
        godot_import=godot_import,
        profiles=profiles,
    )


def _table(raw: Mapping[str, Any], name: str, path: Path) -> Mapping[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: [{name}] must be a table")
    return value
