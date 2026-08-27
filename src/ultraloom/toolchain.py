"""Where a check's tool comes from on *this* machine.

The presets name their tools bare -- `godot`, `eslint`, `vitest` -- and that
only works while every one of them is on PATH. For the Python presets `uv`
takes care of it; for the others nobody does, and a Godot lies on no Windows
machine's PATH.

The failure this module exists to end was measured in a neighbouring repo: two
absolute Godot paths lived in `.claude/settings.json`, and one machine change
turned every check that needs the engine silently, misleadingly red. A path in
a configuration file is a claim about a machine; a resolution in code is a
claim about the project.

This module downloads nothing. What fills `.ultraloom/tools/` is not ultraloom.

Only the standard library is imported here, and deliberately so: this answers a
question about the file system and needs no Config to be asked.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# Where a project keeps the tools it ships to itself.
LOCAL_DIR: Final = ".ultraloom/tools"


def env_var(name: str) -> str:
    """The variable this machine sets to override one tool's location."""
    return "ULTRALOOM_TOOL_" + name.upper().replace("-", "_")


def local_names(name: str, platform: str) -> tuple[str, ...]:
    """The file names a project-local tool may carry, best first.

    A pure function over a platform string rather than a branch inside the
    walk, for the same reason as `spawn_kwargs` in process.py: otherwise the
    Windows half stays unexercised on every POSIX machine that runs the suite.
    """
    if platform == "win32":
        return (name, f"{name}.exe", f"{name}.cmd", f"{name}.bat")
    return (name,)


@dataclass(frozen=True)
class Tool:
    """A tool that exists here, and whether its location had to be named.

    `pinned` separates the two answers a caller has to act on differently. PATH
    answered means the bare name already reaches this file, and a command that
    keeps its bare name stays readable in a report; the machine or the project
    answered means the bare name would reach something else, or nothing, and
    the path has to go into the argv.
    """

    path: Path
    pinned: bool


def resolve(
    name: str,
    root: Path,
    env: Mapping[str, str],
    *,
    platform: str = sys.platform,
) -> Tool | None:
    """The executable behind `name`, or None if this machine has none.

    Three candidates, each *checked* rather than believed: the machine's own
    answer, then the project-local directory, then PATH. A variable pointing at
    nothing falls through instead of being handed on -- handing it on is how
    the original failure produced a red check no source change could close.
    """
    override = env.get(env_var(name))
    if override is not None and override.strip():
        candidate = Path(override.strip())
        if candidate.is_file():
            return Tool(candidate, pinned=True)

    local = root / LOCAL_DIR
    for filename in local_names(name, platform):
        candidate = local / filename
        if candidate.is_file():
            return Tool(candidate, pinned=True)

    # The handed-in mapping and not os.environ: a caller that passes an env
    # without PATH means "this machine has no PATH", and `path=None` would
    # quietly consult the real one instead -- which is exactly the kind of
    # believed-rather-than-checked answer this module is about.
    found = shutil.which(name, path=env.get("PATH", ""))
    return Tool(Path(found), pinned=False) if found else None
