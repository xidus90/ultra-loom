"""What `import ultraloom.cli` may cost, measured by what it loads.

A millisecond threshold would be shaky on a shared machine -- the same bare
interpreter measured between 80 and 117 ms on one day. What is deterministic is
the cause: which modules the import pulls in. This holds the lazy imports
against the next contributor who adds one at the top of the file again.
"""

from __future__ import annotations

import subprocess
import sys

_PROGRAM = """
import sys
import ultraloom.cli

expensive = [
    name
    for name in ("ultraloom.checks", "concurrent.futures", "ctypes")
    if name in sys.modules
]
print("LEAKED:", expensive)
"""


def test_importing_the_cli_does_not_pull_in_the_check_chain() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROGRAM],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "LEAKED: []" in result.stdout, result.stdout
