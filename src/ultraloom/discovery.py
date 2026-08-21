"""Finding the flows a project keeps beside its own code.

ultraloom loads them and knows nothing else about them: a project's flows carry
that project's world, and the core must not.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

from ultraloom.graph import Graph

FLOW_DIR = ".ultraloom/flows"


class FlowNotFoundError(LookupError):
    """Raised when no flow of that name exists in the project."""


class FlowLoadError(RuntimeError):
    """Raised when a flow module cannot be imported or holds no graph."""


def list_flows(root: Path) -> tuple[str, ...]:
    """The names of the project's flows, sorted."""
    directory = root / FLOW_DIR
    if not directory.is_dir():
        return ()
    names = (path.stem for path in directory.glob("*.py") if path.stem != "__init__")
    return tuple(sorted(names))


def find_flow(name: str, root: Path) -> Graph[object]:
    """Load one flow by name."""
    path = root / FLOW_DIR / f"{name}.py"
    if not path.is_file():
        available = ", ".join(list_flows(root)) or "none"
        raise FlowNotFoundError(f"no flow {name!r} in {root / FLOW_DIR}; available: {available}")

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
    # Deliberately not registered in sys.modules: a flow is loaded for one call,
    # and a project's module table is not ultraloom's to grow.
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise FlowLoadError(f"{path}: {error}") from error

    flow: object = getattr(module, "flow", None)
    if flow is None:
        raise FlowLoadError(f"{path}: defines no module-level `flow`")
    if not isinstance(flow, Graph):
        raise FlowLoadError(f"{path}: `flow` must be a Graph, got {type(flow).__name__}")
    return flow
