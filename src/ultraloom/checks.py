"""Resolving and running a project's checks.

Four stages, first hit wins: explicit configuration, a script at a named path,
the language preset, then refusal. Detection saves work; guessing would cost
reliability — and a missing tool is a failure, never a skipped check.

Two languages on purpose, and the line runs along the reader: what lands in a
`CheckResult.output` speaks German, because it is read by a person and by the
repairing model (the spec prescribes those strings word for word), while every
tool-facing message — argv, exceptions, log lines — stays English.
"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from threading import BoundedSemaphore, Semaphore

from ultraloom import process
from ultraloom.config import Config, ConfigError

KINDS = ("lint", "types", "test", "coverage")


@dataclass(frozen=True, slots=True)
class Preset:
    """What a language's tool for one check kind looks like.

    Three fields with distinct jobs, and the distinction is the whole point:

    `measuring` -- this check can measure as a by-product, if somebody needs it
    `after`     -- this check reads what another one leaves behind
    `measure`   -- if nobody measures for me, I measure myself

    Which of them applies follows from the set of kinds requested in one pass,
    never from the table alone: `measuring` is taken up only when something in
    that pass reads what this check leaves behind, and `measure` is skipped only
    when the check named by `after` did the measuring instead.
    """

    argv: tuple[str, ...]
    measuring: tuple[str, ...] = ()
    measure: tuple[str, ...] = ()
    after: str = ""


# The tools are asked to be terse wherever a flag says so: a check report is
# read by a repairer that pays for every token of it, on every round. Each of
# these flags was run against a failing project first -- one that turned a red
# check green would be worse than any amount of noise.
# Shared rather than spelled out twice: `test` and test-under-measurement run
# the same suite, and a flag that reached only one of them would make the two
# modes report in different shapes -- the one property that makes them
# incomparable.
_TERSE_PYTEST = ("-q", "--tb=short", "--no-header")
_PYTEST = ("uv", "run", "pytest", *_TERSE_PYTEST)
_COVERAGE_RUN = ("uv", "run", "coverage", "run", "-m", "pytest", *_TERSE_PYTEST)

# marker file -> check kind -> the preset for it
PRESETS: Mapping[str, Mapping[str, Preset]] = {
    "pyproject.toml": {
        "lint": Preset(("uvx", "ruff", "check", ".", "--output-format=concise")),
        "types": Preset(("uvx", "mypy", "--no-error-summary", "--no-pretty")),
        # `measuring` rather than a second suite run: with coverage in the same
        # run, `test` measures as it goes and the report reads what it wrote.
        # Alone, `test` stays the fast path and pays no measuring overhead.
        "test": Preset(_PYTEST, measuring=_COVERAGE_RUN),
        # `--skip-covered --skip-empty`: the files at 100% are the ones nobody
        # needs to read, and in a project that holds the line they are almost
        # all of them. `-m` pulls the other way and is worth it: without it the
        # report names the file that is at 83% but not the line that is
        # missing, and the repairer spends a whole round only looking it up.
        # Not left to the project's own config -- `show_missing` is off by
        # default, and ultraloom setting it in its own pyproject.toml says
        # nothing about anybody else's.
        "coverage": Preset(
            ("uv", "run", "coverage", "report", "--skip-covered", "--skip-empty", "-m"),
            measure=_COVERAGE_RUN,
            after="test",
        ),
    },
    "package.json": {
        "lint": Preset(("eslint", ".")),
        "types": Preset(("tsc", "--noEmit")),
        "test": Preset(("vitest", "run")),
        # One stage: vitest measures and reports in the same run, so there is
        # nothing for coverage to wait on.
        "coverage": Preset(("vitest", "run", "--coverage")),
    },
    "project.godot": {
        "lint": Preset(("uvx", "gdlint", ".")),
        "test": Preset(("godot", "--headless", "--quit")),
        # No coverage preset, deliberately. GDScript coverage in the project
        # this came from is the Nano Coverage *editor addon*: it instruments the
        # sources in place and writes lcov.info as a by-product of the suite,
        # and the threshold over that file is enforced by a project-owned
        # script. Neither half is a command a second Godot project could run, so
        # there is nothing general to name here. A guessed command would be the
        # worse outcome: it would look like a check and be none. Such a project
        # configures its report under [verify.coverage] and its order under
        # [verify.after].
    },
}

# A red result whose cause is a tool that could not be resolved at all. A
# constant and not a literal at its one raising site: the flow reads this value
# to decide what no repair pass can close, and across a module boundary a
# literal on one side and a constant on the other is a coupling that a rename
# would break silently.
UNAVAILABLE = "unavailable"

# A red result whose cause is the project's state, not a missing tool: reported
# with a source of its own, because "unavailable" would say a tool is missing
# when the tool is there and the project is not ready for it.
UNREADY = "unready"

# A red result whose cause is another check: reported with a source of its own,
# because neither "failed" nor "unavailable" says that this check never ran and
# will run fine as soon as its predecessor is green.
BLOCKED = "blocked"

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


def resolve_check(
    kind: str,
    config: Config,
    *,
    alongside: frozenset[str] = frozenset(),
) -> Command:
    """Find the command for this check, or refuse to guess.

    `alongside` names the kinds running in this same pass. It decides who
    measures: a check that can measure as a by-product does so when something
    depends on it, and a check that depends on it then skips its own measuring
    step. Empty by default, so a caller that resolves one kind on its own gets
    a check that stands alone -- correct, and possibly slower than what the
    scheduler would have built. That silent precedence is the price of a
    signature that does not force every caller to know about the others.
    """
    if kind not in KINDS:
        raise CheckUnavailableError(f"unknown check {kind!r}; known: {', '.join(KINDS)}")

    # Read up front rather than in the preset branch alone: the language also
    # answers who measures, and that question is asked of a project-configured
    # report too.
    marker = _marker(config.root)

    if kind == "coverage" and config.coverage_report is not None:
        # The one check whose command does not live in [verify]: coverage has
        # its own table, because a threshold belongs next to the command that
        # reports against it. Space measures through Nano Coverage into LCOV
        # and enforces the threshold in a script of its own -- neither a
        # preset nor a [verify] key could name that.
        words = tuple(shlex.split(config.coverage_report))
        if not words:
            raise CheckUnavailableError("empty command configured for [verify.coverage].report")
        _, warning = _measuring_state(kind, marker, config, alongside, ())
        return Command(kind, (config.exec_prefix + words,), "config", warning=warning)

    if kind in config.commands:
        # Config itself refuses an empty list and a blank command, so every
        # argv here exists and none is a bare [exec].prefix.
        argvs = tuple(
            config.exec_prefix + tuple(shlex.split(line)) for line in config.commands[kind]
        )
        _, warning = _measuring_state(kind, marker, config, alongside, ())
        return Command(kind, argvs, "config", threaded=kind in config.threaded, warning=warning)

    script = _script_for(kind, config.root)
    if script is not None:
        _, warning = _measuring_state(kind, marker, config, alongside, ())
        return Command(kind, (config.exec_prefix + script,), "script", warning=warning)

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
    entry = preset[kind]
    argv = entry.argv
    if entry.measuring and _has_dependant(kind, marker, config, alongside):
        # Something in this pass reads what this check leaves behind, so it
        # measures as it goes -- and that dependant drops its own measuring
        # step below. One suite run instead of two.
        argv = entry.measuring

    measure, warning = _measuring_state(kind, marker, config, alongside, entry.measure)
    return Command(
        kind,
        (config.exec_prefix + argv,),
        "preset",
        measure=(config.exec_prefix + measure) if measure else (),
        warning=warning,
    )


def _measuring_state(
    kind: str,
    marker: str | None,
    config: Config,
    alongside: frozenset[str],
    measure: tuple[str, ...],
) -> tuple[tuple[str, ...], str]:
    """What this check still has to measure itself, and what to say if nobody did.

    The middle outcome is the whole point of the pass: somebody else measures
    for this check, so it drops its own step and the suite runs once instead of
    twice. Otherwise it falls back on its own measuring step.

    The warning is the last resort and its condition is narrow on purpose (spec
    8): `after` is named, the predecessor does *not* run in this pass, and there
    is no measuring step to fall back on. A predecessor that runs silences it,
    even where ultraloom cannot tell whether it measured anything -- that is
    precisely what ultraloom cannot know, and warning about it would put the
    line on every Godot run. A warning that always comes stops being read.

    `[verify.after]` is an ordering statement over all four kinds, not a claim
    about data: `test` after `types` is a perfectly ordinary line to write, and
    it must not make every test report carry a warning about `types`.
    """
    after = _predecessor_of(kind, marker, config)
    if not after:
        return measure, ""
    if _measures_for(after, marker, config, alongside):
        return (), ""
    if measure or after in alongside:
        return measure, ""
    return (), (
        f"Achtung: `{after}` lief in diesem Lauf nicht; "
        "dieser Bericht kann von einem älteren Lauf stammen."
    )


def _measures_for(kind: str, marker: str | None, config: Config, alongside: frozenset[str]) -> bool:
    """Whether `kind` runs in this pass *and* measures while it does.

    A kind the project configured itself never counts: ultraloom cannot know
    whether a foreign test command measures, and guessing here would produce a
    coverage report over data nobody wrote. The refusal runs one way only --
    about *another* check's command. What this check's own configured command
    measures is not asked either, so a project that measures inside its own
    `[verify.coverage].report` still keeps its `measure` empty. That direction
    is the safe one: it can cost a warning, never a report over nothing.

    `kind in alongside` means *requested*, not *finished*, and nothing here can
    upgrade it: this runs while the pass is being planned, before any command
    started. So a predecessor that is asked for and then dies -- timed out and
    killed with its tree, or never started at all -- has already caused this
    check to drop its own measuring step, and the report would read whatever an
    earlier run left behind. The only thing standing between that and a green
    report over stale data is the scheduler refusing to run a check whose
    predecessor went red (`blocked`). Whoever changes that, or this, must change
    the other.
    """
    if kind not in alongside or kind in config.commands:
        return False
    if _script_for(kind, config.root) is not None:
        return False
    if marker is None:
        return False
    entry = PRESETS[marker].get(kind)
    return entry is not None and bool(entry.measuring)


def _has_dependant(kind: str, marker: str, config: Config, alongside: frozenset[str]) -> bool:
    """Whether some kind in this pass waits for `kind`, and can actually run.

    A dependant that does not resolve is no dependant: switching to the
    measuring command for a check that will leave the pass with
    CheckUnavailableError would be measuring work done for nobody. Resolved with
    the default empty `alongside`, which is both enough for the question --
    availability does not depend on who else runs -- and what keeps this from
    recursing back into itself.
    """
    for other in alongside:
        if other == kind or _predecessor_of(other, marker, config) != kind:
            continue
        try:
            resolve_check(other, config)
        except CheckUnavailableError:
            continue
        return True
    return False


def _predecessor_of(kind: str, marker: str | None, config: Config) -> str:
    """What this kind waits for: the project's answer first, then the language's.

    A project of no recognisable language has no language answer to fall back
    on -- handled here rather than at each caller, so that "no marker" cannot
    turn into an order nobody configured.
    """
    if kind in config.after:
        return config.after[kind]
    if marker is None:
        return ""
    entry = PRESETS[marker].get(kind)
    return entry.after if entry is not None else ""


def run_check(
    kind: str,
    config: Config,
    alongside: frozenset[str] = frozenset(),
    gate: Semaphore | None = None,
) -> CheckResult:
    """Run the check and report what it said.

    A check with a measuring step runs that first. Its failure is the check's
    failure and stops the check there: a report over data nobody measured --
    or over data left behind by an earlier run -- would be green for reasons
    that have nothing to do with this one.

    `gate` is the run's cap on processes, handed down from the scheduler. A
    caller that runs one check on its own leaves it out and gets a cap of its
    own -- correct for a lone check, and the reason the scheduler does not let
    every kind build one.
    """
    command = resolve_check(kind, config, alongside=alongside)
    unready = _unready(command, config)
    if unready is not None:
        return unready
    return _run_command(command, config, gate)


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
    return shlex.join((*config.exec_prefix, PRESETS["project.godot"]["test"].argv[0]))


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


type CheckRunner = Callable[[str, Config, frozenset[str]], CheckResult]


def run_kinds(
    kinds: Sequence[str],
    config: Config,
    runner: CheckRunner | None = None,
) -> tuple[CheckResult, ...]:
    """Run these checks in dependency order and report them in the order asked.

    Concurrent within a stage with plain threads: subprocess waiting releases
    the GIL, so parallel waiting reaches most of its ceiling without a special
    interpreter (spec 9.4). Sequential *between* stages, because a check that
    reads what another one writes cannot start at the same time as it.

    The one scheduler both callers use. `ultraloom check all` and the
    verify_until_green flow ran a pool each, and a stage built into only one of
    them would leave the flow -- the reason this exists -- running unordered.

    `runner` defaults to None rather than to `run_check` so that the default
    path can carry the run's process cap: it is built here, once, and handed
    down. An injected runner starts no processes worth capping -- that
    parameter is where the flow tests hang.
    """
    if not kinds:
        raise ValueError(
            "run_kinds needs at least one check; a run that checks nothing is not a pass"
        )

    # Deduplicated, not run twice: two `test` entries in one profile would put
    # two `coverage run -m pytest` on the same .coverage file at the same time.
    # A repeated kind means the same check, and a check runs once per run.
    kinds = tuple(dict.fromkeys(kinds))
    alongside = frozenset(kinds)
    marker = _marker(config.root)
    results: dict[str, CheckResult] = {}
    run = _gated(BoundedSemaphore(config.max_parallel)) if runner is None else runner

    for stage in _stages(kinds, marker, config):
        pending: list[str] = []
        for kind in stage:
            blocker = _blocker(kind, marker, config, results)
            if blocker is None:
                pending.append(kind)
            else:
                results[kind] = CheckResult(
                    kind, False, f"läuft nicht, weil `{blocker}` rot war", BLOCKED
                )
        if not pending:
            continue
        with ThreadPoolExecutor(max_workers=len(pending)) as pool:
            reported = pool.map(lambda kind: _run_or_report(kind, config, alongside, run), pending)
            # Filed under the kind that was asked for, never under the kind the
            # result names itself: an injected runner that answers about
            # something else would otherwise leave a KeyError at the end of the
            # run instead of a result nobody can miss.
            for kind, result in zip(pending, reported, strict=True):
                results[kind] = result

    return tuple(results[kind] for kind in kinds)


def _gated(gate: Semaphore) -> CheckRunner:
    """The real runner, carrying this run's one process cap.

    A closure and not a partial over `run_check` bound at definition time: the
    name is looked up when the check runs, so a test that replaces `run_check`
    on the module is seen.
    """

    def run(kind: str, config: Config, alongside: frozenset[str]) -> CheckResult:
        return run_check(kind, config, alongside, gate)

    return run


def _stages(
    kinds: Sequence[str], marker: str | None, config: Config
) -> tuple[tuple[str, ...], ...]:
    """The requested kinds, grouped so that nothing runs before what it reads.

    A kind whose predecessor was not requested lands in the first stage: it has
    nothing to wait for in *this* run, and holding it behind an empty stage
    would be waiting for something that is never going to come. Whether it then
    reads a stale report is a question ultraloom cannot answer, and
    `resolve_check` says so in a warning rather than guessing.

    The ring is caught here and not at load time, because here is where the
    edges actually are. `[verify.after]` is checked against itself by the config
    loader, but an order is only half configured: the project names some edges
    and the preset supplies the rest, and half a ring from each side passes both
    halves of the check. A single line `test = "coverage"` against Python's
    `coverage after test` is exactly that -- accepted by the loader, and a walk
    with no end for whoever follows the effective edges.
    """
    requested = set(kinds)
    depth: dict[str, int] = {}

    def level(kind: str, walked: tuple[str, ...]) -> int:
        if kind in depth:
            return depth[kind]
        if kind in walked:
            # Named as a path and not as a node: a ring the reader has to find
            # for themselves is a refusal that does not help.
            ring = " -> ".join((*walked[walked.index(kind) :], kind))
            raise ConfigError(f"the check order has a cycle: {ring}")
        predecessor = _predecessor_of(kind, marker, config)
        # Only an edge into this run can hold anything up, so only those are
        # walked -- a ring whose other half was not requested is not a ring
        # anybody waits in.
        depth[kind] = level(predecessor, (*walked, kind)) + 1 if predecessor in requested else 0
        return depth[kind]

    ordered: dict[int, list[str]] = {}
    for kind in kinds:
        ordered.setdefault(level(kind, ()), []).append(kind)
    return tuple(tuple(ordered[key]) for key in sorted(ordered))


def _blocker(
    kind: str, marker: str | None, config: Config, results: Mapping[str, CheckResult]
) -> str | None:
    """The predecessor that failed, if there is one.

    Any red result blocks, `unavailable` and `unready` included: a report over a
    suite that never ran is worth exactly as much as one over a suite that
    failed -- and by then the report has already dropped its own measuring step
    (see `_measures_for`), so what it would read is an earlier run's data.
    Transitive by construction -- a blocked check is itself red, so whatever
    waits on it is blocked in turn.
    """
    predecessor = _predecessor_of(kind, marker, config)
    if not predecessor:
        return None
    result = results.get(predecessor)
    if result is None or result.ok:
        return None
    return predecessor


def _run_or_report(
    kind: str, config: Config, alongside: frozenset[str], runner: CheckRunner
) -> CheckResult:
    """One check, with any failure of its own turned into a visible result.

    Broad on purpose. `pool.map` re-raises the first exception when the tuple
    is built, so one check blowing up would discard the results of every check
    that already succeeded. `Exception`, deliberately not `BaseException`:
    KeyboardInterrupt and SystemExit must still stop the run.
    """
    try:
        return runner(kind, config, alongside)
    except CheckUnavailableError as error:
        # Reported, not skipped: a run that looks green because nothing ran is
        # the one failure in this system that actually does damage.
        return CheckResult(kind, False, str(error), UNAVAILABLE)
    except Exception as error:
        return CheckResult(kind, False, f"{type(error).__name__}: {error}", "error")


def run_all(config: Config) -> tuple[CheckResult, ...]:
    """Every check this project has, in the fixed order of KINDS."""
    return run_kinds(KINDS, config)


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
