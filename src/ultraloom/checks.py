"""Resolving and running a project's checks.

Four stages, first hit wins: explicit configuration, a script at a named path,
the language preset, then refusal. Detection saves work; guessing would cost
reliability — and a missing tool is a failure, never a skipped check.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ultraloom.config import Config

KINDS = ("lint", "types", "test", "coverage")

# marker file -> check kind -> the tool's argv
PRESETS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "pyproject.toml": {
        "lint": ("uvx", "ruff", "check", "."),
        "types": ("uvx", "mypy"),
        "test": ("uv", "run", "pytest"),
        "coverage": ("uv", "run", "coverage", "report"),
    },
    "package.json": {
        "lint": ("eslint", "."),
        "types": ("tsc", "--noEmit"),
        "test": ("vitest", "run"),
        "coverage": ("vitest", "run", "--coverage"),
    },
    "project.godot": {
        "lint": ("uvx", "gdlint", "."),
        "test": ("godot", "--headless", "--quit"),
    },
}

_LANGUAGE_NAMES: Mapping[str, str] = {
    "pyproject.toml": "Python",
    "package.json": "Node",
    "project.godot": "GDScript",
}


class CheckUnavailableError(RuntimeError):
    """Raised when a check cannot be resolved. Never a reason to skip it."""


@dataclass(frozen=True, slots=True)
class Command:
    """A resolved check: what to run, and where the decision came from."""

    kind: str
    argv: tuple[str, ...]
    source: str


@dataclass(frozen=True, slots=True)
class CheckResult:
    """What a check said."""

    kind: str
    ok: bool
    output: str
    source: str


def resolve_check(kind: str, config: Config) -> Command:
    """Find the command for this check, or refuse to guess."""
    if kind not in KINDS:
        raise CheckUnavailableError(f"unknown check {kind!r}; known: {', '.join(KINDS)}")

    if kind in config.commands:
        words = tuple(shlex.split(config.commands[kind]))
        if not words:
            # Checked before the prefix is prepended, not after: with a prefix
            # configured, a blank command line leaves the bare prefix, and
            # ultraloom would run *that* and report its exit code as the
            # check's. A prefix that exits 0 would turn a check nobody
            # configured into a green line -- the one failure in this system
            # that actually does damage.
            raise CheckUnavailableError(f"empty command configured for check {kind!r}")
        return Command(kind, config.exec_prefix + words, "config")

    script = _script_for(kind, config.root)
    if script is not None:
        return Command(kind, config.exec_prefix + script, "script")

    marker = _marker(config.root)
    if marker is None:
        raise CheckUnavailableError(
            f"could not tell what kind of project {config.root} is; "
            f"set [verify].{kind} in {config.root / '.ultraloom' / 'config.toml'}"
        )

    preset = PRESETS[marker]
    if kind not in preset:
        raise CheckUnavailableError(
            f"{_LANGUAGE_NAMES[marker]} has no {kind} tool — a known limitation, not a passed check"
        )
    return Command(kind, config.exec_prefix + preset[kind], "preset")


def run_check(kind: str, config: Config) -> CheckResult:
    """Run the check and report what it said."""
    command = resolve_check(kind, config)
    try:
        completed = subprocess.run(
            command.argv,
            cwd=config.root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        # A tool that is not installed must read as a failed check, not as a
        # traceback that takes the whole chain down with it.
        # shlex.join rather than argv[0]: the handler must survive any argv,
        # including one this module never expected to build.
        detail = f"could not run {shlex.join(command.argv)!r}: {error}"
        return CheckResult(kind, False, detail, command.source)
    output = completed.stdout + completed.stderr
    return CheckResult(kind, completed.returncode == 0, output, command.source)


def run_all(config: Config) -> tuple[CheckResult, ...]:
    """Run every resolvable check at once, and report them in a fixed order.

    Concurrent with plain threads: subprocess.run releases the GIL while it
    waits, so parallel waiting reaches most of its ceiling without a special
    interpreter (spec 9.4). The order of the result is KINDS, never the order
    in which the checks happened to finish — a report whose lines move around
    between runs cannot be compared.
    """
    with ThreadPoolExecutor(max_workers=len(KINDS)) as pool:
        return tuple(pool.map(lambda kind: _run_or_report(kind, config), KINDS))


def _run_or_report(kind: str, config: Config) -> CheckResult:
    """One check, with any failure of its own turned into a visible result.

    Broad on purpose. `pool.map` re-raises the first exception when the tuple
    is built, so one check blowing up would discard the results of every check
    that already succeeded. `Exception`, deliberately not `BaseException`:
    KeyboardInterrupt and SystemExit must still stop the run.
    """
    try:
        return run_check(kind, config)
    except CheckUnavailableError as error:
        # Reported, not skipped: a run that looks green because nothing ran is
        # the one failure in this system that actually does damage.
        return CheckResult(kind, False, str(error), "unavailable")
    except Exception as error:
        return CheckResult(kind, False, f"{type(error).__name__}: {error}", "error")


def _script_for(kind: str, root: Path) -> tuple[str, ...] | None:
    """A check script at the conventional path, if the project put one there.

    A named path, deliberately not a search for anything that looks like a
    check script — that would be guessing.

    The extension is free, so `lint.py` and `lint.bat` can both exist. The
    tie-break is the first by name, which puts `.bat` before `.py`; a project
    that cares should keep one script per check rather than rely on that.
    A `.py` script is run with the interpreter ultraloom itself runs under.
    """
    directory = root / ".ultraloom" / "checks"
    if not directory.is_dir():
        return None
    # is_file(), because a directory called `lint.d` matches the glob and would
    # otherwise be handed to subprocess as a command.
    candidates = sorted(path for path in directory.glob(f"{kind}.*") if path.is_file())
    if not candidates:
        return None
    script = candidates[0]
    if script.suffix == ".py":
        return (sys.executable, str(script))
    return (str(script),)


def _marker(root: Path) -> str | None:
    for name in PRESETS:
        if (root / name).exists():
            return name
    return None
