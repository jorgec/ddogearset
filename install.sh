#!/usr/bin/env bash
# install.sh — Set up everything needed to build goGearset after a fresh
# `git clone`, so build-mac.sh / build-linux.sh can be run immediately afterward.
#
# Installs/checks for: Homebrew (macOS) or apt packages (Linux), Go, Node,
# Python 3.11 + a project-local venv with pulp/pyinstaller, the Wails CLI,
# and GLPK. GLPK only needs to be present on THIS build machine —
# build-mac.sh / build-linux.sh bundle glpsol (and its shared-library dependencies)
# into the shipped app itself, so end users never need GLPK installed. Also
# warns about one remaining hardcoded absolute-path dependency this script
# cannot fix for you (see the end of this file).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

WAILS_VERSION="v2.10.0"
VENV_DIR="python/.venv"

info()  { echo "-> $*"; }
warn()  { echo "!! $*" >&2; }
ok()    { echo "OK $*"; }

OS="$(uname -s)"

# ── System packages ─────────────────────────────────────────────────────────
case "$OS" in
    Darwin)
        if ! command -v brew >/dev/null 2>&1; then
            warn "Homebrew not found. Install it yourself first, then re-run this script:"
            warn '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
            exit 1
        fi
        info "Installing/checking Homebrew packages (go, node, python@3.11, glpk, zip)..."
        brew install go node python@3.11 glpk zip >/dev/null
        ok "Homebrew packages present."
        PYTHON_BIN="$(brew --prefix python@3.11)/bin/python3.11"

        if ! command -v otool >/dev/null 2>&1 || ! command -v install_name_tool >/dev/null 2>&1; then
            warn "otool/install_name_tool not found — build-mac.sh needs these to bundle" \
                 "glpsol's shared libraries. Install Xcode Command Line Tools:"
            warn "  xcode-select --install"
            exit 1
        fi
        ok "Xcode Command Line Tools (otool, install_name_tool) present."
        ;;
    Linux)
        if ! command -v apt-get >/dev/null 2>&1; then
            warn "This script only automates apt-based Linux. Install go, nodejs, python3.11" \
                 "(+venv), glpk-utils, zip, and unzip yourself, then re-run."
            exit 1
        fi
        info "Installing/checking apt packages (this may prompt for sudo)..."
        sudo apt-get update -qq
        sudo apt-get install -y golang-go nodejs npm python3.11 python3.11-venv glpk-utils zip unzip >/dev/null
        ok "apt packages present."
        PYTHON_BIN="python3.11"
        ;;
    *)
        warn "Unsupported OS '${OS}'. This project's release tooling targets macOS/Linux only."
        exit 1
        ;;
esac

# ── Go toolchain / modules ──────────────────────────────────────────────────
info "Downloading Go module dependencies..."
go mod download
ok "Go modules ready."

info "Installing Wails CLI ${WAILS_VERSION}..."
go install "github.com/wailsapp/wails/v2/cmd/wails@${WAILS_VERSION}"
GOBIN="$(go env GOPATH)/bin"
if ! command -v wails >/dev/null 2>&1 && [ ! -x "${GOBIN}/wails" ]; then
    warn "wails CLI installed to ${GOBIN} but that's not on PATH — add it, e.g.:"
    warn "  export PATH=\"\$PATH:${GOBIN}\""
fi
ok "Wails CLI ready."

# ── Frontend ─────────────────────────────────────────────────────────────────
info "Installing frontend npm dependencies..."
( cd frontend && npm install --silent )
ok "Frontend dependencies ready."

# ── Python venv for the solver ──────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    info "Creating Python venv at ${VENV_DIR}..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
info "Installing Python dependencies (pulp, pyinstaller) into ${VENV_DIR}..."
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet -r python/requirements.txt pyinstaller
ok "Python venv ready at ${VENV_DIR} (pyinstaller needed to (re)build python/dist/solver)."

# ── GLPK presence check ──────────────────────────────────────────────────────
# Only needs to be ANYWHERE on PATH — build-mac.sh/build-linux.sh discover it
# (via `command -v glpsol`) and bundles it (plus its dylib/so dependencies)
# into the app. There is no hardcoded install path to match anymore.
echo ""
if command -v glpsol >/dev/null 2>&1; then
    ok "glpsol found at $(command -v glpsol) — build-mac.sh/build-linux.sh will bundle this."
else
    warn "glpsol not found on PATH. The 'glpk' package should have installed it above" \
         "— check brew/apt output for errors."
fi

# ── DDOBuilderV2 data ────────────────────────────────────────────────────────
# A BUILD-TIME input now, not a runtime one. Since 0.5.0 the app ships
# catalog.db (built by the ETL, embedded by go:embed) and never reads
# DDOBuilderV2's XML, never fetches anything, and needs no network at all —
# docs/0.5.0/00_ETL_START_HERE.md constraints 1 and 3. Nothing downloads it
# any more; the checkout has to be here before ./build-mac.sh runs, because
# that is what the ETL reads.
echo ""
if [ -d "DDOBuilderV2/Output/DataFiles/Items" ]; then
    ok "DDOBuilderV2 present at ./DDOBuilderV2 — the ETL will build catalog.db from it."
elif [ -d "DDOBuilderV2" ]; then
    warn "./DDOBuilderV2 exists but has no Output/DataFiles/Items — that is not a full" \
         "checkout, and the ETL will refuse to build. Re-clone it:" \
         "git clone --depth 1 https://github.com/Maetrim/DDOBuilderV2"
elif command -v git >/dev/null 2>&1; then
    warn "./DDOBuilderV2 is missing. The build needs it (it is the ETL's only input" \
         "— nothing fetches it for you). Get it once, from this directory:" \
         "git clone --depth 1 https://github.com/Maetrim/DDOBuilderV2"
else
    warn "./DDOBuilderV2 is missing and git is not installed. Download" \
         "https://github.com/Maetrim/DDOBuilderV2 as a zip and extract it to" \
         "./DDOBuilderV2 — the build needs it, and nothing fetches it for you."
fi

echo ""
echo "=== install.sh complete ==="
case "$OS" in
    Darwin) echo "Next: ./build-mac.sh" ;;
    Linux)  echo "Next: ./build-linux.sh" ;;
esac
