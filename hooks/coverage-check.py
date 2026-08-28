# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""The coverage lane of a repository that holds two languages.

`[verify.coverage]` takes exactly one command -- a threshold belongs next to
the command that reports against it, so the table has `report` and no
`commands` list. One slot, two languages: this script is that slot, and it runs
both arms and fails on either.

The Python arm measures before it reports. `test` is configured in this
repository, so ultraloom no longer hands the coverage check a measuring step,
and a `coverage report` over whatever `.coverage` happened to lie around would
be a green line over stale data -- the one failure this whole system is built
to prevent. The price is the suite running twice per `precommit`, which is the
same price the configured `test` entry already pays and is written down there.

The Go arm needs a floor at all: `go test` has no `fail_under`, so without this
the Go tree's coverage is measured by nobody and reported by nobody.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Mirrors checks.py's `_TERSE_PYTEST`. A check report is read by a repairer
# that pays for every token, on every round.
TERSE_PYTEST = ("-q", "--tb=short", "--no-header")

# What `go tool cover -func` prints on its last line. The percentage is the
# only number on it, and the word before it names what was counted.
TOTAL = re.compile(r"^total:\s+\(statements\)\s+([0-9.]+)%", re.MULTILINE)

_WINDOWS_GO = Path(r"C:\Program Files\Go\bin\go.exe")


def _resolve_go() -> str:
    """Find the go executable, checking PATH then standard install location."""
    found = shutil.which("go")
    if found:
        return found
    if sys.platform == "win32" and _WINDOWS_GO.is_file():
        return str(_WINDOWS_GO)
    return "go"


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """One command, its output captured rather than streamed.

    Captured because the two arms must both run before anything is decided: a
    Python failure that ended the process would hide the Go result, and a
    repairer would then fix one thing per round.
    """
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def python_arm() -> tuple[bool, str]:
    """Measure the suite, then let the project's own fail_under judge it."""
    try:
        measured = run(["uv", "run", "coverage", "run", "-m", "pytest", *TERSE_PYTEST])
    except OSError as error:
        # A missing toolchain is not a coverage verdict and must not pass as one.
        return False, f"coverage could not be run: {error}"
    if measured.returncode != 0:
        # A red suite leaves a partial measurement, and a report over it would
        # name files nobody reached rather than files nobody covered.
        return False, "the suite failed under measurement:\n" + tail(measured)
    reported = run(["uv", "run", "coverage", "report", "--skip-covered", "--skip-empty", "-m"])
    return reported.returncode == 0, tail(reported)


def go_arm(floor: float) -> tuple[bool, str]:
    """Measure the Go tree and hold it to a floor `go test` cannot hold itself."""
    go = _resolve_go()
    with tempfile.TemporaryDirectory() as workspace:
        profile = str(Path(workspace) / "cover.out")
        try:
            measured = run([go, "test", "./...", "-covermode=set", f"-coverprofile={profile}"])
        except OSError as error:
            return False, f"go could not be run: {error}"
        if measured.returncode != 0:
            return False, "go test failed:\n" + tail(measured)
        summary = run([go, "tool", "cover", f"-func={profile}"])
    if summary.returncode != 0:
        return False, "go tool cover failed:\n" + tail(summary)
    found = TOTAL.search(summary.stdout)
    if found is None:
        # No total means nothing was measured, and an unmeasured tree must not
        # read as a tree at 100%.
        return False, "go tool cover named no total:\n" + summary.stdout
    percent = float(found.group(1))
    if percent < floor:
        return False, f"go coverage is {percent}%, below the floor of {floor}%\n" + summary.stdout
    return True, f"go coverage {percent}%"


def tail(done: subprocess.CompletedProcess[str]) -> str:
    """What a command said, in the order a reader wants it: findings, then noise."""
    return (done.stdout + done.stderr).strip()


def main(argv: list[str]) -> int:
    """Run both arms and report both, whichever of them failed."""
    if len(argv) != 1:
        print("usage: coverage-check.py <go-floor-in-percent>", file=sys.stderr)
        return 1
    try:
        floor = float(argv[0])
    except ValueError:
        print(f"{argv[0]!r} is not a percentage", file=sys.stderr)
        return 1
    python_ok, python_said = python_arm()
    go_ok, go_said = go_arm(floor)
    for language, ok, said in (("python", python_ok, python_said), ("go", go_ok, go_said)):
        stream = sys.stdout if ok else sys.stderr
        print(f"{language}: {said}", file=stream)
    return 0 if python_ok and go_ok else 1


if __name__ == "__main__":  # pragma: no cover  # the process edge; `main` is what the tests drive
    sys.exit(main(sys.argv[1:]))
