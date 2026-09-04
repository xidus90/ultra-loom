#!/usr/bin/env bash
# UltraLoom Native Binary Installer for Linux / macOS / POSIX

set -euo pipefail

echo "==> Installing UltraLoom native binaries..."

# 1. Resolve target bin directory
GOBIN_DIR="$(go env GOBIN)"
if [ -z "$GOBIN_DIR" ]; then
    GOPATH_DIR="$(go env GOPATH)"
    if [ -n "$GOPATH_DIR" ]; then
        GOBIN_DIR="${GOPATH_DIR}/bin"
    else
        GOBIN_DIR="${HOME}/go/bin"
    fi
fi

mkdir -p "$GOBIN_DIR"
echo "Target directory: $GOBIN_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 2. Name the binaries the way the platform runs them.
#
# Without the suffix this script cannot install on Windows at all, and it
# fails in the way that looks like progress: `go build` refuses to write
# over a file it did not produce -- "build output ... already exists and is
# not an object file" -- and the refusal arrives *after* the "Building..."
# line. Measured on this machine, the run stopped at ulguard and left both
# binaries at their previous version while reporting nothing wrong until
# the last line.
#
# What it collided with is the reason to name the suffix rather than to
# delete what is in the way: a two-line shim called `ulguard` sat beside
# `ulguard.exe` and forwarded to it. Git Bash resolves the extensionless
# name first, so the shim is what a caller reaches -- and `go build` will
# not overwrite it. The suffix takes the collision out of the picture:
# `.exe` is what Windows executes, and every shell there applies PATHEXT.
EXE=""
case "$(go env GOOS)" in
    windows) EXE=".exe" ;;
esac

# 3. Build binaries
echo "Building ulguard..."
go build -o "${GOBIN_DIR}/ulguard${EXE}" "${ROOT_DIR}/cmd/guard"

echo "Building ulinit..."
go build -o "${GOBIN_DIR}/ulinit${EXE}" "${ROOT_DIR}/cmd/init"

chmod +x "${GOBIN_DIR}/ulguard${EXE}" "${GOBIN_DIR}/ulinit${EXE}"

echo ""
echo "[OK] UltraLoom binaries (ulguard, ulinit) installed to ${GOBIN_DIR}."
