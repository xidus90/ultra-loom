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

# 2. Build binaries
echo "Building ulguard..."
go build -o "${GOBIN_DIR}/ulguard" "${ROOT_DIR}/cmd/guard"

echo "Building ulinit..."
go build -o "${GOBIN_DIR}/ulinit" "${ROOT_DIR}/cmd/init"

chmod +x "${GOBIN_DIR}/ulguard" "${GOBIN_DIR}/ulinit"

echo ""
echo "[OK] UltraLoom binaries (ulguard, ulinit) installed to ${GOBIN_DIR}."
