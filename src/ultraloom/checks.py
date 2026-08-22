"""Resolving and running a project's checks.

Four stages, first hit wins: explicit configuration, a script at a named path,
the language preset, then refusal. Detection saves work; guessing would cost
reliability — and a missing tool is a failure, never a skipped check.
"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from threading import BoundedSemaphore, Semaphore

from ultraloom import process
from ultraloom.config import Config

KINDS = ("lint", "types", "test", "coverage")

# marker file -> check kind -> the tool's argv
# A preset is a *sequence* of commands, because not every tool measures what
# it reports. The last one is the check; anything before it prepares the data
# the check reads. Only Python's coverage needs the distinction today, and it
# is spelled out for every preset rather than special-cased at the one place
# that has it.
PRESETS: Mapping[str, Mapping[str, tuple[tuple[str, ...], ...]]] = {
    "pyproject.toml": {
        "lint": (("uvx", "ruff", "check", "."),),
        "types": (("uvx", "mypy"),),
        "test": (("uv", "run", "pytest"),),
        # Two steps: `coverage report` reads .coverage and never writes it. A
        # single-step preset is therefore red in every project that has not
        # measured by some other route -- and `run_all` cannot supply one,
        # because the four checks run at the same time and `test` measures
        # nothing. The tests run twice, once here and once under `test`; that
        # is the price of checks that stay independent of each other (spec 9.4).
        "coverage": (
            ("uv", "run", "coverage", "run", "-m", "pytest"),
            ("uv", "run", "coverage", "report"),
        ),
    },
    "package.json": {
        "lint": (("eslint", "."),),
        "types": (("tsc", "--noEmit"),),
        "test": (("vitest", "run"),),
        # One step: vitest measures and reports in the same run.
        "coverage": (("vitest", "run", "--coverage"),),
    },
    "project.godot": {
        "lint": (("uvx", "gdlint", "."),),
        "test": (("godot", "--headless", "--quit"),),
    },
}

# A red result whose cause is the project's state, not a missing tool: reported
# with a source of its own, because "unavailable" would say a tool is missing
# when the tool is there and the project is not ready for it.
UNREADY = "unready"

# What a Godot import writes, and the only file here that an *empty* `.godot/`
# does not have -- the directory itself appears long before the import fills it.
# `.godot/` is gitignored, so every fresh checkout and every new worktree starts
# without it, not just a new project.
_GODOT_IMPORT_MARKER = Path(".godot") / "global_script_class_cache.cfg"

# The checks that mean nothing before the import. `lint` is deliberately absent:
# gdlint reads source text and needs no `.godot/`, so gating it would block a
# check that would have worked.
_NEEDS_GODOT_IMPORT = ("test", "coverage")

_LANGUAGE_NAMES: Mapping[str, str] = {
    "pyproject.toml": "Python",
    "package.json": "Node",
    "project.godot": "GDScript",
}


class CheckUnavailableError(RuntimeError):
    """Raised when a check cannot be resolved. Never a reason to skip it."""


@dataclass(frozen=True, slots=True)
class Command:
    """A resolved check: what to run, and where the decision came from.

    `argvs` is a *sequence* because a kind may name several equal-ranking
    commands -- two linters that check different things. They all run, even
    after a red one: the point of the chain is a complete list of findings, and
    half a list costs the repairer a whole extra round.

    `measure` is the step that prepares what `argvs` then reads, and it is not
    equal-ranking: a report over data nobody measured is meaningless, so its
    failure stops the check. It is empty for every check that measures and
    reports in one go, which is all of them except Python's coverage.
    """

    kind: str
    argvs: tuple[tuple[str, ...], ...]
    source: str
    measure: tuple[str, ...] = ()
    threaded: bool = False
    # Prepended to the output when this check reads something no command in
    # this run produced. A warning and never a verdict -- see spec 8.
    warning: str = ""

    def __post_init__(self) -> None:
        """A check must name at least one command.

        `all(())` is True, so a Command with no argvs would merge into a green
        result over an empty report -- a passed check that ran nothing, which
        is the one failure Grundsatz 4 rules out. `resolve_check` cannot build
        one today, but a Command is also built by hand, and the guard belongs
        where the invariant is, not where one caller happens to hold it.
        """
        if not self.argvs:
            raise CheckUnavailableError(f"check {self.kind!r} resolved to no command at all")


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

    if kind == "coverage" and config.coverage_report is not None:
        # The one check whose command does not live in [verify]: coverage has
        # its own table, because a threshold belongs next to the command that
        # reports against it. Space measures through Nano Coverage into LCOV
        # and enforces the threshold in a script of its own -- neither a
        # preset nor a [verify] key could name that.
        words = tuple(shlex.split(config.coverage_report))
        if not words:
            raise CheckUnavailableError("empty command configured for [verify.coverage].report")
        return Command(kind, (config.exec_prefix + words,), "config")

    if kind in config.commands:
        # Config itself refuses an empty list and a blank command, so every
        # argv here exists and none is a bare [exec].prefix.
        argvs = tuple(
            config.exec_prefix + tuple(shlex.split(line)) for line in config.commands[kind]
        )
        return Command(kind, argvs, "config", threaded=kind in config.threaded)

    script = _script_for(kind, config.root)
    if script is not None:
        return Command(kind, (config.exec_prefix + script,), "script")

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
    steps = tuple(config.exec_prefix + step for step in preset[kind])
    # A preset with more than two steps has no meaning here: the last one is
    # the check, the one before it prepares its data, and a third would have
    # nowhere to be reported from.
    if len(steps) > 2:  # pragma: no cover  # guards the preset table, not any input
        raise CheckUnavailableError(f"the {kind!r} preset has more than two steps")
    return Command(kind, (steps[-1],), "preset", measure=steps[0] if len(steps) == 2 else ())


def run_check(kind: str, config: Config) -> CheckResult:
    """Run the check and report what it said.

    A check with a measuring step runs that first. Its failure is the check's
    failure and stops the check there: a report over data nobody measured --
    or over data left behind by an earlier run -- would be green for reasons
    that have nothing to do with this one.
    """
    command = resolve_check(kind, config)
    unready = _unready(command, config)
    if unready is not None:
        return unready
    return _run_command(command, config)


def _unready(command: Command, config: Config) -> CheckResult | None:
    """The project's own precondition, checked before any engine is started.

    A Godot project must have been imported once: the import builds `.godot/`,
    and without it a suite fails on things that are not broken -- or measures
    nothing and looks green doing it. ultraloom reports that and does *not* run
    the import itself: a checking tool that starts an editor unasked and changes
    the tree has stopped being a check.
    """
    if command.kind not in _NEEDS_GODOT_IMPORT:
        return None
    if not config.godot_import:
        # The project says it prepares its own suite. Without this valve a
        # project whose test command runs the import itself would be red on
        # every run and out of the repairer's reach besides -- it could never
        # heal itself. A key and not a guess from the command's source: the
        # project this precondition came from configures its own test command,
        # so deriving the answer would switch the gate off exactly where it was
        # measured to be needed.
        return None
    if _marker(config.root) != "project.godot":
        return None
    if (config.root / _GODOT_IMPORT_MARKER).exists():
        return None
    return CheckResult(command.kind, False, _import_message(config), UNREADY)


def _import_message(config: Config) -> str:
    """Why the check is red, and both ways out of it.

    The engine is named only where the preset would have run it. A project that
    configured `test` itself runs some other binary, and naming a path that may
    not exist is worse than saying less.

    The valve is named too: whoever is blocked by this gate should not have to
    already know the key that opens it.
    """
    engine = _preset_godot_binary(config)
    handle = "--headless --path . --import"
    run = (
        f"{engine} {handle}" if engine is not None else f"the project's Godot binary with {handle}"
    )
    return (
        "this Godot project has never been imported, "
        "so nothing measured here would mean anything\n"
        f"run: {run}\n"
        "a project whose own check command runs the import "
        "sets [verify].godot_import = false"
    )


def _preset_godot_binary(config: Config) -> str | None:
    """The engine the `test` preset would start, or None if the project names its own."""
    if "test" in config.commands or _script_for("test", config.root) is not None:
        return None
    return shlex.join((*config.exec_prefix, PRESETS["project.godot"]["test"][0][0]))


def _run_command(command: Command, config: Config, gate: Semaphore | None = None) -> CheckResult:
    """Every command of one kind, and one verdict out of them.

    `gate` is the cap on running *processes*. It is passed in rather than made
    here so that the levels above -- stages, and the kinds within a stage --
    can share one instead of each handing out the whole budget again.

    The contract that comes with it: the cap is acquired at the process and
    nowhere else. Whoever passes this cap on does not acquire it -- the levels
    above are thread pools, and a pool that held a permit while waiting for the
    work below it to take one would deadlock. Held that way the semaphore never
    has to be reentrant, and the deadlock is ruled out structurally instead of
    by counting.
    """
    if gate is None:
        # `is None` and not `or`: a Semaphore is always truthy, so `or` would
        # work by an accident of a class this module does not own.
        gate = BoundedSemaphore(config.max_parallel)
    if command.measure:
        measured = _run(command.measure, command.kind, config, command.source, gate)
        if not measured.ok:
            # Through _warned rather than returned bare: this is the path where
            # the output most needs the warning that explains it.
            return _warned(command, measured)

    if command.threaded and len(command.argvs) > 1:
        # Capped too: threads past the cap would only queue at the gate, so a
        # kind with ten commands under max_parallel = 2 would spend eight
        # threads on waiting.
        workers = min(len(command.argvs), config.max_parallel)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = tuple(
                pool.map(
                    lambda argv: _run(argv, command.kind, config, command.source, gate),
                    command.argvs,
                )
            )
    else:
        results = tuple(
            _run(argv, command.kind, config, command.source, gate) for argv in command.argvs
        )
    return _merged(command, results)


def _merged(command: Command, results: tuple[CheckResult, ...]) -> CheckResult:
    """One verdict and one report out of however many commands ran.

    With a single command the report is byte for byte what it always was: a
    heading over a lone command would change every existing output for nothing.
    The order is the configured one, never the order they finished in -- a
    report whose lines move between runs cannot be compared.
    """
    if len(results) == 1:
        output = results[0].output
    else:
        # The verdict rides on the heading because a command can fail without
        # writing a word. Without it such a run shows the *other* command's
        # findings and nothing else, and the report of a red check would name
        # no reason for being red.
        headed = (
            f"$ {shlex.join(argv)}{'' if result.ok else ' (failed)'}\n{result.output.rstrip()}"
            for argv, result in zip(command.argvs, results, strict=True)
        )
        # The trailing newline is what a single command's report ends in, from
        # the tool's own output. Without it here there would be two shapes of
        # report, and every reader downstream would have to know both.
        output = "\n\n".join(headed) + "\n"
    return _warned(
        command,
        CheckResult(
            command.kind,
            all(result.ok for result in results),
            output,
            command.source,
        ),
    )


def _warned(command: Command, result: CheckResult) -> CheckResult:
    """The result with the check's warning in front of it, if it has one.

    A line above the report and never a change to `ok`: a warning says the
    numbers may be reading something this run did not produce, which is worth
    knowing and is not a finding.
    """
    if not command.warning:
        return result
    return replace(result, output=f"{command.warning}\n{result.output}")


def _run(
    argv: tuple[str, ...], kind: str, config: Config, source: str, gate: Semaphore
) -> CheckResult:
    try:
        with gate:
            completed = process.run(argv, cwd=config.root, timeout=config.timeout)
    except OSError as error:
        # A tool that is not installed must read as a failed check, not as a
        # traceback that takes the whole chain down with it.
        # shlex.join rather than argv[0]: the handler must survive any argv,
        # including one this module never expected to build.
        detail = f"could not run {shlex.join(argv)!r}: {error}"
        if not Path(argv[0]).is_absolute() and len(Path(argv[0]).parts) > 1:
            # A relative path to an executable is not resolved against `cwd`:
            # the OS looks it up against the *calling* process's directory and
            # along PATH. `.venv/bin/pytest` therefore fails here however
            # correct it looks from the project root -- which is nobody's guess
            # to make from a bare "file not found".
            detail += (
                f"\nhint: {argv[0]!r} is a relative path, and a command is not looked up "
                f"relative to the project root. Use `uv run` (or an absolute path)."
            )
        return CheckResult(kind, False, detail, source)

    output = completed.stdout + completed.stderr
    if completed.timed_out:
        # A red result and not an exception: a check that never finished is a
        # check that failed, and giving it its own exception would buy the flow
        # a special path that ends in exactly the same place.
        detail = f"{shlex.join(argv)!r} timed out after {config.timeout}s"
        return CheckResult(kind, False, _with(detail, completed, output), source)
    if completed.output_abandoned:
        # Red although the tool may well have exited 0: what came back is a
        # prefix, and a threshold or a failure count could be in the part that
        # did not. Grundsatz 4 -- a check nobody could read is not a passed
        # check.
        detail = f"{shlex.join(argv)!r} exited {completed.returncode}"
        return CheckResult(kind, False, _with(detail, completed, output), source)
    return CheckResult(kind, completed.returncode == 0, output, source)


def _with(detail: str, completed: process.Completed, output: str) -> str:
    """The reason, what arrived, and -- if it is a prefix -- that it is one."""
    if completed.output_abandoned:
        # Said out loud: a descendant still holds the pipe, so what follows is
        # what had arrived by then and not everything the tool wrote.
        detail += " (output incomplete: a reader had to be given up on)"
    return f"{detail}\n{output}".rstrip()


def run_all(config: Config) -> tuple[CheckResult, ...]:
    """Run every resolvable check at once, and report them in a fixed order.

    Concurrent with plain threads: process.run spends its time waiting on a
    child, with the GIL released, so parallel waiting reaches most of its
    ceiling without a special interpreter (spec 9.4). The order of the result is
    KINDS, never the order in which the checks happened to finish — a report whose lines move around
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
