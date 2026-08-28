# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Turn `gofmt -l` into an exit code the stop gate can read.

gofmt reports by printing names and still exits 0; a gate needs the opposite.
Python and not bash, because `bash` on Windows resolves to WSL here, and a
Windows gofmt is not reachable from there by its bare name.
"""

from __future__ import annotations

import subprocess
import sys


def main(paths: list[str]) -> int:
    """Report unformatted files under `paths`, or say why gofmt could not say."""
    if not paths:
        print("usage: gofmt-check.py <path>...", file=sys.stderr)
        return 1
    try:
        done = subprocess.run(
            ["gofmt", "-l", *paths],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        # A missing toolchain is not a formatting verdict and must not pass as one.
        print(f"gofmt could not be run: {error}", file=sys.stderr)
        return 1
    if done.returncode != 0:
        # gofmt's own failure -- an unreadable path, a file it cannot parse.
        print(done.stderr.strip() or f"gofmt exited {done.returncode}", file=sys.stderr)
        return 1
    unformatted = done.stdout.strip()
    if unformatted:
        print(f"not gofmt-clean:\n{unformatted}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
