"""Reading a project's .ultraloom/config.toml.

Configuration says two independent things: which tool runs a check, and where
it runs. Splitting those is what lets a project that checks through a container
boundary still profit from the language presets.
"""

from __future__ import annotations

import os
import shlex
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_NAME = ".ultraloom/config.toml"

_KINDS = ("lint", "types", "test")

# Everything the table form of a check kind understands. Also what
# [verify.coverage] must *not* carry, which is why it is named once.
_TABLE_KEYS = ("commands", "threaded")

# The check kinds a profile may name. Deliberately a copy of checks.KINDS and
# not an import: config sits below checks, and test_module_boundary keeps it
# there. test_config asserts the two lists stay equal.
_CHECK_KINDS = ("lint", "types", "test", "coverage")

# Seconds per check command. The order of magnitude space's headless Godot
# suite needs; a project that runs longer says so rather than inheriting a
# limit that was chosen for somebody else's tools.
DEFAULT_TIMEOUT = 600

# The machine's answer to where the Claude CLI is. It beats [agent].cli_path:
# whoever exports it does so *because* the project file is wrong for this
# machine, and the other way round the variable would be dead on every machine
# as soon as one project writes the key down.
CLI_PATH_ENV = "ULTRALOOM_CLI_PATH"


def _default_parallelism() -> int:
    # process_cpu_count honours a CPU affinity mask, which a build agent may
    # well set; cpu_count would promise cores this process cannot use.
    return os.process_cpu_count() or 1


class ConfigError(ValueError):
    """Raised for a config file that cannot be read or means two things."""


@dataclass(frozen=True, slots=True)
class Config:
    """What a project says about how it is checked."""

    root: Path
    commands: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    threaded: frozenset[str] = frozenset()
    exec_prefix: tuple[str, ...] = ()
    coverage_report: str | None = None
    coverage_threshold: int = 100
    mcp_servers: tuple[str, ...] = ()
    # Where the Claude CLI is, when the SDK's own search does not find it. None
    # is the normal case and means "let the SDK look".
    cli_path: Path | None = None
    test_paths: tuple[str, ...] = ()
    timeout: int = DEFAULT_TIMEOUT
    godot_import: bool = True
    # The cap on processes running at once, over the whole run: run_kinds
    # builds one semaphore and hands it down through the stages and the kinds
    # to the process itself, which is the only level that acquires it. A caller
    # that runs a single check on its own gets a cap of its own instead.
    max_parallel: int = field(default_factory=_default_parallelism)
    after: Mapping[str, str] = field(default_factory=dict)
    profiles: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """No check kind may carry a command that runs nothing, and the cap is real.

        Not only load_config's business: whoever builds a Config by hand gets
        the same assurance. An argv that is blank leaves nothing but the
        [exec].prefix, and a prefix that exits 0 reports a check nobody
        configured as passed -- the one failure in this system that actually
        does damage.

        A cap of zero is the quiet version of the same thing: run_kinds makes a
        BoundedSemaphore of it, and the first acquire against zero blocks in the
        pool forever -- no timeout, no message, a run that checks nothing and
        never comes back.
        """
        for kind, commands in self.commands.items():
            if not commands or any(not command.strip() for command in commands):
                raise ConfigError(f"check {kind!r} has an empty command")
        if self.max_parallel <= 0:
            raise ConfigError(f"max_parallel must be greater than zero, not {self.max_parallel}")
        if self.cli_path is not None and not self.cli_path.is_file():
            # Here and not in load_config, so a Config built by hand carries the
            # same assurance. The alternative is the failure this key exists to
            # remove: a run that starts, spends 3.4 seconds per agent node, and
            # reports a fault of the SDK's.
            raise ConfigError(f"cli_path is not a file: {self.cli_path}")


def load_config(root: Path) -> Config:
    """Read the project's configuration, or return empty defaults."""
    path = root / CONFIG_NAME
    # is_file() and not exists(): a *directory* of that name exists, and
    # read_text would raise IsADirectoryError past every ConfigError handler.
    if not path.is_file():
        # Still not empty defaults: the machine may name the CLI for a project
        # that configured nothing at all, which is the case the variable is for.
        return Config(root, cli_path=_cli_path(None, path))

    try:
        # tomllib returns nested tables of unknown shape; every field below is
        # narrowed explicitly, which is why the raw mapping is typed loosely.
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error

    verify = _table(raw, "verify", path)
    coverage = _table(verify, "coverage", path)
    agent = _table(raw, "agent", path)

    # [verify.coverage] has the shape of the new table form without being one:
    # coverage is configured through `report`, and swallowing `commands` here
    # would leave the check on its preset with nothing saying why.
    unhonoured = tuple(key for key in _TABLE_KEYS if key in coverage)
    if unhonoured:
        raise ConfigError(
            f"{path}: [verify.coverage] does not take "
            f"{', '.join(repr(key) for key in unhonoured)}; "
            f"name the command as [verify.coverage].report"
        )

    commands: dict[str, tuple[str, ...]] = {}
    threaded: set[str] = set()
    for kind in _KINDS:
        if kind not in verify:
            continue
        commands[kind], is_threaded = _commands_for(kind, verify[kind], path)
        if is_threaded:
            threaded.add(kind)

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

    # Spelling the default here too would give it two sources that can drift
    # apart unnoticed -- a file that omits the key would take the copy in this
    # line, never the field's. Absent means absent; the field decides.
    raw_max_parallel = verify.get("max_parallel")
    max_parallel = (
        _default_parallelism() if raw_max_parallel is None else _parallelism(raw_max_parallel, path)
    )

    after = _after_from(_table(verify, "after", path, "verify.after"), path)

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

    cli_path = _cli_path(agent.get("cli_path"), path)

    servers = agent.get("mcp_servers", [])
    if not isinstance(servers, list) or not all(isinstance(name, str) for name in servers):
        raise ConfigError(f"{path}: [agent].mcp_servers must be a list of strings")

    return Config(
        root=root,
        commands=commands,
        threaded=frozenset(threaded),
        exec_prefix=tuple(shlex.split(prefix)),
        coverage_report=report,
        coverage_threshold=threshold,
        mcp_servers=tuple(servers),
        cli_path=cli_path,
        test_paths=tuple(raw_tests),
        timeout=timeout,
        godot_import=godot_import,
        max_parallel=max_parallel,
        after=after,
        profiles=profiles,
    )


def _cli_path(configured: object, path: Path) -> Path | None:
    """What the machine says, else what the file says, else nothing.

    Blank counts as unset on both sides. That is how a machine that exports
    CLI_PATH_ENV switches it off again for one run -- and it keeps an empty
    string from being read as a path, which would be the current directory and
    would come back refused as "not a file", indistinguishable from a typo.
    """
    if configured is not None and not isinstance(configured, str):
        raise ConfigError(f"{path}: [agent].cli_path must be a string")
    for candidate in (os.environ.get(CLI_PATH_ENV), configured):
        if candidate is not None and candidate.strip():
            return Path(candidate.strip())
    return None


def _parallelism(value: object, path: Path) -> int:
    """What the file says about the cap, or a refusal."""
    # Booleans are ints in TOML, the same trap the timeout key has.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{path}: [verify].max_parallel must be an integer")
    if value <= 0:
        raise ConfigError(f"{path}: [verify].max_parallel must be greater than zero")
    return value


def _after_from(raw: Mapping[str, Any], path: Path) -> Mapping[str, str]:
    """The dependency edges, validated so a bad one cannot become a run that hangs."""
    edges: dict[str, str] = {}
    for kind, predecessor in raw.items():
        if not isinstance(predecessor, str):
            raise ConfigError(f"{path}: [verify.after].{kind} must be a string")
        for name in (kind, predecessor):
            if name not in _CHECK_KINDS:
                raise ConfigError(f"{path}: [verify.after] names unknown check {name!r}")
        edges[kind] = predecessor

    # Each kind names at most one predecessor, so following the chain from every
    # kind is enough: a cycle is a walk that returns to something already seen.
    # Refused here rather than in the scheduler, where it would be a run that
    # waits for itself and never ends.
    for kind in edges:
        # Kept as a path rather than a set so the refusal can name the edges
        # that form the ring; a single node leaves the reader to find them.
        walked = [kind]
        current = kind
        while current in edges:
            current = edges[current]
            if current in walked:
                ring = " -> ".join([*walked[walked.index(current) :], current])
                raise ConfigError(f"{path}: [verify.after] has a cycle: {ring}")
            walked.append(current)
    return edges


def _commands_for(kind: str, value: object, path: Path) -> tuple[tuple[str, ...], bool]:
    """One kind's commands, from any of its three shapes.

    A string is one command, a list is several, a table is several plus the
    switches. TOML itself rules out the string-and-table collision: a key
    cannot be both, and the parser refuses the file before it reaches here.
    """
    if isinstance(value, str):
        return _checked((value,), kind, path), False
    if isinstance(value, list):
        return _checked(tuple(value), kind, path), False
    if isinstance(value, dict):
        # A typo such as `thread = true` would otherwise leave the check
        # unthreaded with nothing to read the mistake off.
        unknown = sorted(set(value) - set(_TABLE_KEYS))
        if unknown:
            raise ConfigError(
                f"{path}: [verify.{kind}] does not know "
                f"{', '.join(repr(key) for key in unknown)}; "
                f"it takes {', '.join(repr(key) for key in _TABLE_KEYS)}"
            )
        raw = value.get("commands")
        if raw is None:
            raise ConfigError(f"{path}: [verify.{kind}] must name `commands`")
        if not isinstance(raw, list):
            raise ConfigError(f"{path}: [verify.{kind}].commands must be a list of strings")
        is_threaded = value.get("threaded", False)
        # Booleans are ints in TOML, so `threaded = 1` is refused rather than
        # read as "on" -- the same trap the timeout and godot_import keys have.
        if not isinstance(is_threaded, bool):
            raise ConfigError(f"{path}: [verify.{kind}].threaded must be true or false")
        return _checked(tuple(raw), kind, path), is_threaded
    raise ConfigError(f"{path}: [verify.{kind}] must be a string, a list of strings, or a table")


def _checked(commands: tuple[object, ...], kind: str, path: Path) -> tuple[str, ...]:
    """Every command is a non-blank string, checked before any prefix is prepended.

    With an [exec].prefix configured, a blank command line leaves the bare
    prefix, and a prefix that exits 0 turns a check nobody configured into a
    green line -- the one failure in this system that actually does damage.
    """
    if not commands:
        raise ConfigError(f"{path}: [verify.{kind}] names an empty list of commands")
    for command in commands:
        if not isinstance(command, str):
            raise ConfigError(f"{path}: [verify.{kind}] must hold strings")
        if not command.strip():
            raise ConfigError(f"{path}: [verify.{kind}] holds an empty command")
    # The isinstance check above is per item; str() only tells mypy that.
    return tuple(str(command) for command in commands)


def _table(
    raw: Mapping[str, Any], name: str, path: Path, label: str | None = None
) -> Mapping[str, Any]:
    """One nested table, or a refusal that names it as the file spells it.

    A nested table's key is only its leaf, so `label` carries the full heading
    -- otherwise `after = "test"` under [verify] is refused as `[after]`, which
    appears nowhere in the file.
    """
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: [{label or name}] must be a table")
    return value
