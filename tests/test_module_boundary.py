"""The test that keeps the promise "the harness is optional" honest.

A promise without a test decays. These run the check chain in a child process
where the Claude Agent SDK cannot be imported at all, and then read that
process's own `sys.modules` back: nothing from the harness may be in it.

A child process, deliberately — the boundary is about what an import pulls in,
and inside the pytest process every harness module is loaded long before this
file runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# checks.run_all uses a *thread* pool, so every check resolves and runs inside
# this one process. That is what makes a single sys.modules snapshot after
# `check all` a complete answer rather than a sample of one worker.
_FORBIDDEN = (
    "ultraloom.graph",
    "ultraloom.state",
    "ultraloom.runner",
    "ultraloom.journal",
    "ultraloom.gate",
    "ultraloom.model",
    "ultraloom.discovery",
)

_PREAMBLE = f'''
import sys

FORBIDDEN = {_FORBIDDEN!r}


class Blocker:
    """Makes claude_agent_sdk unimportable, whatever is installed."""

    def find_spec(self, name, path=None, target=None):
        if name == "claude_agent_sdk" or name.startswith("claude_agent_sdk."):
            raise ImportError("blocked for this test")
        return None


sys.meta_path.insert(0, Blocker())


def report():
    leaked = sorted(
        name
        for name in sys.modules
        if any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN)
    )
    print("LEAKED:", leaked)
'''

# Runs the real command line, then reports what the process ended up holding.
RUN_CHECK = (
    _PREAMBLE
    + """
from ultraloom.cli import main

code = main(sys.argv[1:])
print("EXIT:", code)
report()
"""
)

# The same probe with a harness import in front of it: proof that the probe
# actually notices. If a later edit hoists cli.py's local imports to the top of
# the file, RUN_CHECK reports exactly what this test reports here.
HOIST_CHECK = (
    _PREAMBLE
    + """
import ultraloom.runner  # stands in for a local import someone moved to the top

from ultraloom.cli import main

code = main(sys.argv[1:])
print("EXIT:", code)
report()
"""
)

IMPORT_CHECK_SIDE = (
    _PREAMBLE
    + """
import ultraloom.checks
import ultraloom.cli
import ultraloom.config

print("EXIT: 0")
report()
"""
)


def _probe(script: str, *args: str) -> tuple[int, list[str], str]:
    """Run one probe and read back its exit code and its leaked modules."""
    completed = subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    combined = completed.stdout + completed.stderr
    assert completed.returncode == 0, combined
    exit_line = next(line for line in completed.stdout.splitlines() if line.startswith("EXIT:"))
    leaked_line = next(line for line in completed.stdout.splitlines() if line.startswith("LEAKED:"))
    return int(exit_line.removeprefix("EXIT:")), _parse(leaked_line), combined


def _parse(leaked_line: str) -> list[str]:
    inner = leaked_line.removeprefix("LEAKED:").strip().strip("[]")
    return [name.strip().strip("'") for name in inner.split(",") if name.strip()]


def _project(tmp_path: Path) -> Path:
    """A project whose four checks all resolve and all pass."""
    ultraloom_dir = tmp_path / ".ultraloom"
    (ultraloom_dir / "checks").mkdir(parents=True)
    # as_posix, because config.py splits the exec prefix and the commands with
    # shlex in POSIX mode: a Windows path's backslashes would be eaten.
    python = Path(sys.executable).as_posix()
    (ultraloom_dir / "config.toml").write_text(
        f'[verify]\nlint = "{python} -c pass"\n'
        f'types = "{python} -c pass"\n'
        f'test = "{python} -c pass"\n',
        encoding="utf-8",
    )
    # coverage has no [verify] key, so it comes from the script stage instead.
    (ultraloom_dir / "checks" / "coverage.py").write_text("", encoding="utf-8")
    return tmp_path


def test_one_check_runs_without_pulling_in_the_harness(tmp_path: Path) -> None:
    code, leaked, output = _probe(RUN_CHECK, "check", "lint", "--root", str(_project(tmp_path)))

    assert leaked == [], output
    assert code == 0, output


def test_every_check_at_once_runs_without_pulling_in_the_harness(tmp_path: Path) -> None:
    """`check all` is the path that resolves all four kinds and all four stages."""
    code, leaked, output = _probe(RUN_CHECK, "check", "all", "--root", str(_project(tmp_path)))

    assert leaked == [], output
    assert code == 0, output


def test_the_threshold_path_runs_without_pulling_in_the_harness(tmp_path: Path) -> None:
    code, leaked, output = _probe(
        RUN_CHECK, "check", "coverage", "--threshold", "90", "--root", str(_project(tmp_path))
    )

    assert leaked == [], output
    assert code == 0, output


def test_the_config_error_hint_runs_without_pulling_in_the_harness(tmp_path: Path) -> None:
    """The hint path leaves main() before any check runs; it must stay clean too."""
    (tmp_path / ".ultraloom").mkdir()
    (tmp_path / ".ultraloom" / "config.toml").write_text(
        '[verify]\ncoverage = "uv run coverage report"\n', encoding="utf-8"
    )

    code, leaked, output = _probe(RUN_CHECK, "check", "all", "--root", str(tmp_path))

    assert leaked == [], output
    assert code == 1, output
    assert "[verify.coverage]" in output


def test_importing_the_check_side_pulls_in_no_harness_module() -> None:
    _code, leaked, output = _probe(IMPORT_CHECK_SIDE)

    assert leaked == [], output


def test_the_probe_notices_a_harness_import_that_was_moved_to_the_top(tmp_path: Path) -> None:
    """Without this, a probe that never fails would prove nothing at all."""
    _code, leaked, output = _probe(HOIST_CHECK, "check", "lint", "--root", str(_project(tmp_path)))

    assert "ultraloom.runner" in leaked, output
    assert "ultraloom.graph" in leaked, output
