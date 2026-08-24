"""The command line. A paused run needs an address, and a check needs a caller.

The two halves of ultraloom meet here and nowhere else. Everything the harness
side needs is imported inside the functions that need it, so `ultraloom check`
runs in a project that never installed the optional agent extra (spec 15.2).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from ultraloom.checks import CheckResult, CheckUnavailableError, run_all, run_check
from ultraloom.config import Config, ConfigError, load_config
from ultraloom.worktree import RUN_DIR, WorktreeError, changed_files, head_commit

if TYPE_CHECKING:
    # Type-only, so the check side still imports nothing from the harness at
    # runtime — the boundary is about sys.modules, not about annotations.
    from ultraloom.discovery import Baseline
    from ultraloom.model.port import Model

_EXIT_OK = 0
_EXIT_FAIL = 1
# Not 2: argparse exits 2 on a usage error, and a caller scripting against the
# exit code must be able to tell "waiting at a gate" from "you typed it wrong".
_EXIT_PAUSED = 3

# checks.KINDS carries "coverage" but config's [verify] table does not, so the
# obvious spelling fails with an error about a table. Name the two real places.
_COVERAGE_HINT = (
    "hint: [verify] holds no `coverage` command — [verify.coverage] is the table for "
    "`threshold` and `report`. The coverage command comes from .ultraloom/checks/coverage.* "
    "or from the language preset."
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one subcommand. Returns the process exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_usage(sys.stderr)
        return _EXIT_FAIL

    root = Path(args.root).resolve()
    if args.command == "show":
        # Before the config is read at all: `show` touches only the journal, and
        # reading a past run is the command you most want working when the
        # project is broken -- which is often exactly why you are reading it.
        return _show(root, args.run_id)

    try:
        config = load_config(root)
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        if "[coverage] must be a table" in str(error):
            print(_COVERAGE_HINT, file=sys.stderr)
        return _EXIT_FAIL

    if args.command == "check":
        return _check(args.kind, config, args.threshold)
    return _flow_command(args, root, config)


def next_run_id(root: Path) -> str:
    """The next run's id: a counter over the run directory, never a clock."""
    directory = root / RUN_DIR
    stems = [path.stem for path in directory.glob("*.jsonl")] if directory.is_dir() else []
    highest = max((int(stem) for stem in stems if stem.isdigit()), default=0)
    return f"{highest + 1:04d}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ultraloom", description="Run checks and agent flows.")
    # On the subparsers rather than here: argparse hands everything after the
    # subcommand to the subparser, and `ultraloom run smoke --root .` is the
    # order people type.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=".", help="project root (default: the current directory)")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", parents=[common], help="run a flow from its start")
    run.add_argument("flow")
    run.add_argument("--no-model", action="store_true", help="run without a model, for diagnosis")
    run.add_argument(
        "--checks",
        default=None,
        help="which checks to run: a comma-separated list, or a profile from [verify.profiles]",
    )
    run.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="how many repair rounds a flow may take (default: the flow's own limit)",
    )

    show = subparsers.add_parser("show", parents=[common], help="print a run's journal")
    show.add_argument("run_id")

    for name, help_text in (
        ("resume", "carry a paused run onward"),
        ("replay", "re-derive a run from its journal, without a model call"),
    ):
        sub = subparsers.add_parser(name, parents=[common], help=help_text)
        sub.add_argument("run_id")
        # `replay` takes it too, only so it can be refused with a reason: a
        # replay that applied an answer would run the gate live.
        sub.add_argument("--answer", default=None, help="the answer to the run's open gate")

    check = subparsers.add_parser("check", parents=[common], help="run one or all of the checks")
    check.add_argument("kind", choices=("lint", "types", "test", "coverage", "all"))
    check.add_argument("--threshold", type=int, default=None, help="coverage threshold in percent")

    return parser


def _check(kind: str, config: Config, threshold: int | None) -> int:
    if threshold is not None:
        config = dataclasses.replace(config, coverage_threshold=threshold)

    if kind == "all":
        # One process pays the startup cost once and waits concurrently
        # (spec 9.4). Unresolvable checks come back as failures, not silence.
        try:
            results = run_all(config)
        except ConfigError as error:
            # The scheduler is the first reader of the *effective* check order,
            # so it is the first place a ring between the project's edges and
            # the preset's can show up -- long after load_config was happy.
            print(str(error), file=sys.stderr)
            return _EXIT_FAIL
        for result in results:
            _report(result)
        return _EXIT_OK if all(result.ok for result in results) else _EXIT_FAIL

    try:
        result = run_check(kind, config)
    except CheckUnavailableError as error:
        print(str(error), file=sys.stderr)
        return _EXIT_FAIL

    _report(result)
    if kind == "coverage":
        # Deliberately its own line, and never part of the verdict: nothing in
        # ultraloom folds the threshold into the coverage command, so a line
        # reading "ok (threshold 90%)" would claim a check that never happened.
        print(
            f"note: the configured coverage threshold is {config.coverage_threshold}%; "
            "ultraloom does not enforce it — the coverage tool's own settings decide"
        )
    return _EXIT_OK if result.ok else _EXIT_FAIL


def _report(result: CheckResult) -> None:
    """One line per check, with the source named.

    The source is on the line because "ok" from a preset and "ok" from a
    configured command are not the same claim — and because `unavailable` and
    `error` are red lines that a bare "failed" would hide.
    """
    verdict = "ok" if result.ok else "failed"
    print(f"{result.kind}: {verdict} [{result.source}]")
    if result.output:
        print(result.output.rstrip("\n"))


def _flow_options(args: argparse.Namespace) -> dict[str, str]:
    """The command line options a flow may read, as plain strings.

    Strings and not parsed values: the CLI has no business knowing what a flow
    means by "checks". Every flow narrows what it reads, and reports its own
    error when it cannot.
    """
    return {
        name: str(value)
        for name in ("checks", "max_rounds")
        if (value := getattr(args, name, None)) is not None
    }


def _flow_command(args: argparse.Namespace, root: Path, config: Config) -> int:
    # Local imports: `ultraloom check` must never pull the harness in, because
    # the harness needs the optional agent extra (spec 15.2). Task 13 pins this
    # with a child process that runs the check path and inspects sys.modules.
    from ultraloom.discovery import (
        FlowContext,
        FlowLoadError,
        FlowNotFoundError,
        find_flow,
    )
    from ultraloom.gate import pending_gate
    from ultraloom.journal import Journal
    from ultraloom.runner import Runner

    if args.command == "replay" and args.answer is not None:
        # Refused here because the runner never sees the combination from any
        # other caller: resume would call the gate's `apply` live, which is
        # exactly the model-free promise a replay makes.
        print("replay cannot take an answer; use `ultraloom resume`", file=sys.stderr)
        return _EXIT_FAIL

    if args.command == "run":
        run_id, flow_name = next_run_id(root), args.flow
        options: dict[str, str] = _flow_options(args)
        taken = _baseline(root)
        baseline: Baseline | None = taken
    else:
        run_id = args.run_id
        journal_path = root / RUN_DIR / f"{run_id}.jsonl"
        if not journal_path.exists():
            print(f"no run {run_id!r} under {root / RUN_DIR}", file=sys.stderr)
            return _EXIT_FAIL
        try:
            recorded = _recorded_run(root, run_id)
        except MarkerError as error:
            print(str(error), file=sys.stderr)
            return _EXIT_FAIL
        if recorded is None:
            print(f"run {run_id!r} does not say which flow it belongs to", file=sys.stderr)
            return _EXIT_FAIL
        flow_name, options, baseline = recorded
        if baseline is None:
            # Taking one now would measure the run against the tree the
            # repairer has meanwhile edited, so everything it had already
            # changed would count as untouched. Refuse rather than measure.
            print(
                f"run {run_id} was started before the guard measured against a "
                "commit, or outside a repository; start a new run with "
                "`ultraloom run`",
                file=sys.stderr,
            )
            return _EXIT_FAIL
        gate = pending_gate(Journal(journal_path))
        if args.command == "replay" and gate is not None:
            # Replaying would hit a ReplayGapError at the gate, because the
            # answer's `ok` entry does not exist. Say what is true — the run
            # never finished — instead of reporting a pause it cannot reach.
            print(
                f"run {run_id} never finished: it is waiting at gate {gate.node!r}; "
                "answer it with `ultraloom resume` before replaying",
                file=sys.stderr,
            )
            return _EXIT_FAIL
        if args.command == "resume" and gate is None:
            # The mirror image of the refusal above. A resume over a complete
            # journal executes no node at all and reports `done` — exit 0 for a
            # run nobody carried onward. For a flow with no gate anywhere,
            # verify-until-green among them, that is a green verdict over
            # checks that were never started, which is the one answer this tool
            # must never give.
            print(
                f"run {run_id} is not waiting at a gate; there is nothing to answer. "
                "Use `ultraloom replay` to re-derive it, or `ultraloom run` to start "
                "a new one",
                file=sys.stderr,
            )
            return _EXIT_FAIL

    context = FlowContext(
        root=root,
        config=config,
        options=options,
        baseline=baseline,
        run_files=_run_files(run_id),
    )
    try:
        loaded = find_flow(flow_name, root, context)
    except (FlowNotFoundError, FlowLoadError) as error:
        print(str(error), file=sys.stderr)
        return _EXIT_FAIL

    if args.command == "run":
        _remember_run(root, run_id, flow_name, options, taken)
    runner: Runner[object] = Runner(
        loaded.graph,
        Journal(root / RUN_DIR / f"{run_id}.jsonl"),
        model=None if getattr(args, "no_model", False) else _model(root, config),
        mcp_servers=config.mcp_servers,
        replay=args.command == "replay",
    )
    result = (
        runner.resume(loaded.initial, answer=args.answer)
        if args.command == "resume"
        else runner.run(loaded.initial)
    )

    print(f"run {run_id}: {result.status}")
    if result.question is not None:
        print(result.question)
    if result.detail is not None:
        print(result.detail)
    if result.status == "paused":
        return _EXIT_PAUSED
    if result.status == "done":
        return _EXIT_OK
    # A flow may name its own code; without one, a failure is a failure.
    return result.exit_code if result.exit_code is not None else _EXIT_FAIL


def _show(root: Path, run_id: str) -> int:
    # Local import for the same reason as in _flow_command (spec 15.2).
    from ultraloom.journal import Journal

    path = root / RUN_DIR / f"{run_id}.jsonl"
    if not path.exists():
        print(f"no run {run_id!r} under {root / RUN_DIR}", file=sys.stderr)
        return _EXIT_FAIL
    for entry in Journal(path).entries():
        print(
            f"{entry.node:<24} {entry.kind:<6} {entry.outcome:<7} "
            f"{entry.tokens:>7} tok {entry.seconds:>7.2f}s {entry.tools or '-'}"
        )
    return _EXIT_OK


class MarkerError(ValueError):
    """Raised for a run marker that cannot be read."""


# The marker keys the baseline travels under. Reserved: they are popped back
# out before the options reach a flow, so a flow never sees them among its own.
_BASELINE = "baseline"
_BASELINE_COMMIT = "baseline_commit"


def _recorded_run(root: Path, run_id: str) -> tuple[str, dict[str, str], Baseline | None] | None:
    """Which flow a run belongs to, and which options it was started with.

    The journal records what each node did, not which graph the nodes came
    from, so resume and replay would have nothing to load without this marker.
    The options belong to the same answer: a flow that builds itself from them
    would otherwise be rebuilt differently on every continuation, and a replay
    would re-derive a graph that is not the one the journal recorded.
    """
    marker = root / RUN_DIR / f"{run_id}.flow"
    if not marker.exists():
        return None
    flow_name, *rest = marker.read_text(encoding="utf-8").splitlines()
    options: dict[str, str] = {}
    for line in rest:
        if not line:
            continue
        name, separator, raw = line.partition("=")
        if not separator:
            # Said out loud rather than left to `dict()`, which answers a line
            # without a separator with a ValueError naming neither the file nor
            # the line -- a traceback where a sentence belongs.
            raise MarkerError(f"{marker}: option line without '=': {line!r}")
        options[name] = _decode_option(raw)
    # Local import for the same reason as in _flow_command (spec 15.2):
    # discovery belongs to the harness side and `ultraloom check` must not
    # pull it in, so the name exists at runtime only where it is used.
    from ultraloom.discovery import Baseline

    dirty = options.pop(_BASELINE, None)
    commit = options.pop(_BASELINE_COMMIT, None)
    # The commit decides alone. A marker holding only the path set was written
    # before the commit existed, and reading it as a baseline would measure the
    # run against a tree the repairer has already had its hands on -- so it is
    # no baseline at all. The other way round is not the same case: a missing
    # path set is an empty one, and the commit it comes with is a reference
    # point the guard can measure against.
    baseline = None if commit is None else Baseline(commit, _decode_baseline(dirty or ""))
    return flow_name.strip(), options, baseline


def _decode_option(raw: str) -> str:
    """One option value, as JSON when it is JSON.

    Values are written with `json.dumps` so that one holding a newline stays on
    one line -- a run's baseline is a list of paths, so that is the normal case
    and not an exotic one. Read tolerantly, because markers written before this
    encoding existed carry the value bare, and a run of ultraloom that is
    already on disk should not stop being resumable.
    """
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    # Only a string is this encoding's own work; `checks=123` from an older
    # marker parses as JSON too and means the text "123".
    return value if isinstance(value, str) else raw


def _remember_run(
    root: Path,
    run_id: str,
    flow_name: str,
    options: dict[str, str],
    baseline: Baseline | None,
) -> None:
    """Write the run marker, with the baseline when there is one.

    The marker is written even without a baseline: without it `resume` would
    not find the flow at all, and the refusal a run without a baseline earns
    should come from the missing baseline and not from a missing file.
    """
    marker = root / RUN_DIR / f"{run_id}.flow"
    marker.parent.mkdir(parents=True, exist_ok=True)
    if baseline is not None:
        options = options | {
            _BASELINE: "\n".join(sorted(baseline.dirty)),
            _BASELINE_COMMIT: baseline.commit,
        }
    # One line each, not one JSON document: the file is read by eye as often as
    # by code, and the first line means what it always meant. Only the values
    # are JSON, which is what keeps a multi-line one on its own single line.
    lines = [flow_name, *(f"{name}={json.dumps(value)}" for name, value in options.items())]
    marker.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_files(run_id: str) -> frozenset[str]:
    """The two files this run writes itself, as `root` spells them.

    Handed to the flow because a guard must not report ultraloom's own doing as
    the repair agent's. Named one by one and not by their directory: every
    other run's marker lives there too, and that one the agent can write -- the
    `edit` profile needs no shell for it -- while nobody is watching.
    """
    return frozenset({f"{RUN_DIR}/{run_id}.jsonl", f"{RUN_DIR}/{run_id}.flow"})


def _decode_baseline(recorded: str) -> frozenset[str]:
    """The recorded baseline, one path per line.

    A path holding a literal newline -- git allows it -- is split into pieces
    here and then matches nothing, so a guard reading this treats it as the
    repairer's doing. That is the safe direction: a false accusation about a
    pathological path, never a blind spot.
    """
    return frozenset(line for line in recorded.split("\n") if line)


def _baseline(root: Path) -> Baseline | None:
    """What a run starts from, or None where git cannot say.

    Taken once, at the start, and carried in the run marker from there on. The
    question "what did this run start from" has exactly one right answer and it
    comes into being at the start; asking git again on `resume` would answer it
    with the tree the repairer has meanwhile edited, and every file it had
    already touched -- a test file included -- would be excused.

    The dirty set is only worth taking once a commit stands behind it: without
    one there is nothing to measure a change against, and half a baseline reads
    like a whole one at every later call site. The flow that needs one refuses
    the run; a flow that does not never needed git at all.
    """
    # Local import for the same reason as in _flow_command (spec 15.2).
    from ultraloom.discovery import Baseline

    try:
        return Baseline(head_commit(root), frozenset(changed_files(root)))
    except WorktreeError:
        return None


def _model(root: Path, config: Config) -> Model:
    """The real model. A missing agent extra shows up the first time it is asked."""
    # Local import: the adapter lives on the harness side, and `ultraloom
    # check` must not pull it in (spec 15.2). The adapter itself imports the
    # optional extra only inside `ask`, so a project without the extra still
    # gets this far and then reads the install hint as a failed run -- never as
    # an ImportError from a command that had already started.
    from ultraloom.model.agent_sdk import AgentSdkModel

    return AgentSdkModel(cwd=root, cli_path=config.cli_path)
