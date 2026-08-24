"""Finding the flows a project keeps beside its own code.

ultraloom loads them and knows nothing else about them: a project's flows carry
that project's world, and the core must not.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from ultraloom.config import Config
from ultraloom.graph import Graph

FLOW_DIR = ".ultraloom/flows"
BUNDLED_PACKAGE = "ultraloom.flows"

# A module may legitimately bind `flow = None`; `None` is therefore not the
# same answer as "the module never bound it".
_ABSENT: Final = object()


@dataclass(frozen=True, slots=True)
class Baseline:
    """What the working tree looked like when a run started.

    Two halves, and neither stands in for the other. `commit` is what a change
    is measured *against*, so a repairer that commits its edit stays as visible
    as one that leaves it unstaged. `dirty` is what was already changed at that
    moment and must not be laid at the repairer's door.

    Frozen and carried in the run marker, because the question "what did this
    run start from" has one right answer and it comes into being at the start.
    """

    commit: str
    dirty: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class FlowContext:
    """What a flow needs to know about the run it is being built for.

    A bundled flow lives in ultraloom and knows nothing about the project it
    runs in: which tools check it, where its tests are, what the caller asked
    for on the command line. All three arrive here rather than through import
    time magic, so a flow stays a function of its inputs.

    `baseline` is the fourth: where this *run* started from, in both halves --
    the commit a change is measured against, and what was already changed in
    the working tree at that moment. Beside `options` rather than inside it,
    because it is not something a caller asked for and a flow that validates
    its options should not have to know about it. `None` means the run recorded
    none -- older runs did not -- which is a different answer from "the tree
    was clean".

    `run_files` is the fifth: the paths, as `root` spells them, that this run
    writes itself -- its journal and its marker. They come into being while the
    repair agent works, so a guard that counted them would report ultraloom's
    own doing as the agent's. Named one by one rather than by their directory,
    because every *other* run's marker in that directory is something the agent
    can write and nobody else did. Empty means a caller that has no run id, and
    then nothing is subtracted, which is the safe direction.
    """

    root: Path
    config: Config
    options: Mapping[str, str] = field(default_factory=dict)
    baseline: Baseline | None = None
    run_files: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class LoadedFlow:
    """A flow's graph together with the state it starts from."""

    graph: Graph[object]
    initial: object
    # Declared by the flow at load time, not guessed by the CLI: whether its
    # nodes measure repairs against the commit the run started on. Such a
    # flow is refused where git gives no commit, because a run begun without
    # one would pause and then refuse every resume.
    needs_baseline: bool = False


class FlowNotFoundError(LookupError):
    """Raised when no flow of that name exists in the project."""


class FlowLoadError(RuntimeError):
    """Raised when a flow module cannot be imported or holds no graph."""


@dataclass(frozen=True, slots=True)
class FlowEntry:
    """A flow the project could run, or a file that wanted to be one.

    A file with a `problem` is listed rather than hidden: silence about
    `my-flow.py` sends its author looking for a typo in the command line.
    """

    name: str
    origin: str
    problem: str | None = None


def _bundled_dir() -> Path:
    # importlib.resources would be the portable answer for a zipped install;
    # ultraloom is installed from source and `find_flow` needs a real path to
    # hand to spec_from_file_location either way.
    return Path(__file__).resolve().parent / BUNDLED_PACKAGE.rsplit(".", 1)[-1]


def _entries_in(directory: Path, origin: str) -> list[FlowEntry]:
    if not directory.is_dir():
        return []
    entries = []
    for path in sorted(directory.glob("*.py")):
        if path.stem == "__init__":
            continue
        problem = (
            None
            if path.stem.isidentifier()
            else f"{path.name} cannot be loaded: a flow name must be a Python identifier"
        )
        entries.append(FlowEntry(path.stem, origin, problem))
    return entries


def list_flows(root: Path) -> tuple[FlowEntry, ...]:
    """Every flow this project could run, project ones first, sorted by name."""
    project = _entries_in(root / FLOW_DIR, "project")
    taken = {entry.name for entry in project}
    # A project may replace a bundled flow by name. That is the whole mechanism
    # for "ultraloom's version is nearly right"; there is no override syntax.
    bundled = [entry for entry in _entries_in(_bundled_dir(), "bundled") if entry.name not in taken]
    return tuple(sorted(project + bundled, key=lambda entry: entry.name))


def _path_of(name: str, root: Path) -> Path | None:
    for directory in (root / FLOW_DIR, _bundled_dir()):
        candidate = directory / f"{name}.py"
        if candidate.is_file():
            return candidate
    return None


def find_flow(name: str, root: Path, context: FlowContext | None = None) -> LoadedFlow:
    """Load one flow by name, with the state it starts from."""
    # The name is interpolated into a path that is then executed, and it reaches
    # here from the command line and from a run's `.flow` marker file alike.
    # A flow is a module, so an identifier is exactly what it may be -- which
    # also happens to be what "../../evil" is not.
    if not name.isidentifier():
        raise FlowNotFoundError(f"{name!r} is not a valid flow name; a flow name is an identifier")

    path = _path_of(name, root)
    if path is None:
        available = (
            ", ".join(f"{entry.name} ({entry.origin})" for entry in list_flows(root)) or "none"
        )
        raise FlowNotFoundError(f"no flow {name!r}; available: {available}")

    # The module name carries a digest of the project path so two projects can
    # each have a flow called "verify" without one shadowing the other. The
    # digest is content-addressed rather than hash()-based: hash() is salted per
    # process, and a name that changes between runs is a name nothing can match.
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(f"ultraloom_flow_{digest}_{name}", path)
    # A readable .py file always yields a spec with a loader; there is no input
    # to this function that reaches the other branch.
    if spec is None or spec.loader is None:  # pragma: no cover  # unreachable for a .py file
        raise FlowLoadError(f"{path}: cannot be loaded as a module")

    module = importlib.util.module_from_spec(spec)
    # Registered only for the duration of the exec, and removed again after: a
    # flow is loaded for one call, and a project's module table is not
    # ultraloom's to grow. It cannot simply stay out, though -- `dataclasses`
    # resolves a postponed annotation through `sys.modules[cls.__module__]`, so
    # a module that is absent from it cannot define a dataclass at all, and
    # every flow ultraloom ships does. The lookup happens while the decorator
    # runs, which is inside this block.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise FlowLoadError(f"{path}: {error}") from error
    finally:
        # pop and not del: a flow that loads the same flow again during its own
        # exec, or a second thread doing it, removes the entry first, and `del`
        # would then raise a KeyError over a cleanup that already happened.
        sys.modules.pop(spec.name, None)

    builder = getattr(module, "build", _ABSENT)
    has_flow = getattr(module, "flow", _ABSENT) is not _ABSENT
    if builder is not _ABSENT:
        if has_flow:
            # Both would leave the reader guessing which one runs, and the
            # answer would be an implementation detail of this function.
            raise FlowLoadError(f"{path}: defines both `build` and `flow`; keep one")
        if context is None:
            raise FlowLoadError(
                f"{path}: defines `build`, so it needs a context; "
                f"this caller loaded the flow without one"
            )
        if not callable(builder):
            raise FlowLoadError(f"{path}: `build` must be callable, got {type(builder).__name__}")
        try:
            built = builder(context)
        except Exception as error:
            raise FlowLoadError(f"{path}: build failed: {error}") from error
        if not isinstance(built, LoadedFlow):
            raise FlowLoadError(
                f"{path}: `build` must return a LoadedFlow, got {type(built).__name__}"
            )
        return built

    # A sentinel and not None: a module that binds `flow = None` defines one,
    # and telling its author it defines none sends them to look in the wrong
    # place. The type error below is the honest report.
    flow: object = getattr(module, "flow", _ABSENT)
    if flow is _ABSENT:
        raise FlowLoadError(f"{path}: defines no module-level `flow`")
    if not isinstance(flow, Graph):
        raise FlowLoadError(f"{path}: `flow` must be a Graph, got {type(flow).__name__}")

    # An executor needs both halves: a graph says what to do, the initial state
    # says what it starts from, and only the flow's own module knows the latter.
    initial = getattr(module, "initial", _ABSENT)
    if initial is _ABSENT:
        raise FlowLoadError(f"{path}: defines no module-level `initial` state")
    # `flow` has a type check below the sentinel; `initial` has none, and a
    # payload of None would only surface inside the first node as whatever
    # AttributeError that node happens to raise.
    if initial is None:
        raise FlowLoadError(f"{path}: `initial` must be the flow's starting state, not None")
    return LoadedFlow(flow, initial)
