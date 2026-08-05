#!/usr/bin/env bash
# build-linux.sh — Native, fully self-contained Linux build.
#
# "Self-contained" means the resulting binary needs NOTHING installed on the
# machine that runs it — no system GLPK, no Python. Everything required (the
# compiled Python solver, glpsol, and glpsol's own shared-library
# dependencies) is bundled under bundled/linux-<arch>/, embedded into the Go
# binary at compile time (see embed_linux_amd64.go), and extracted to a temp
# directory at app startup (app.go's extractSolver()).
#
# Neither PyInstaller nor a real glpsol binary can be cross-compiled — both
# only ever produce a binary for the machine actually running this script.
# To ship for multiple architectures, run this natively on one machine of
# each and commit the resulting bundled/linux-<arch>/.
#
# Every step below prints what it's doing before it does it, and what it
# found/produced after — nothing here should run silently.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ "$(uname -s)" != "Linux" ]; then
    echo "error: build-linux.sh must run on Linux (uname -s reported '$(uname -s)')." >&2
    exit 1
fi

VENV_PYINSTALLER="$HOME/dev/ddo/venv/bin/pyinstaller"
if command -v pyinstaller >/dev/null 2>&1; then
    PYINSTALLER="pyinstaller"
elif [ -x "$VENV_PYINSTALLER" ]; then
    PYINSTALLER="$VENV_PYINSTALLER"
else
    echo "error: pyinstaller not found on PATH or at ${VENV_PYINSTALLER}." >&2
    echo "       Install it (pip install pyinstaller) in the venv used to build the solver." >&2
    exit 1
fi

GOARCH="$(go env GOARCH)"
PLATFORM="linux-${GOARCH}"
BUNDLE_DIR="bundled/${PLATFORM}"
DIST_DIR="dist/${PLATFORM}"

echo "=== DDO Gearset Optimizer — native Linux build (${PLATFORM}) ==="
mkdir -p "$BUNDLE_DIR"

# ── 1. Rebuild the embedded Python solver ───────────────────────────────────
echo ""
echo "-> Rebuilding Python solver with ${PYINSTALLER}..."
( cd python && "$PYINSTALLER" --noconfirm solver.spec )
if [ ! -f "python/dist/solver" ]; then
    echo "error: expected PyInstaller output at 'python/dist/solver' — check" \
         "python/solver.spec's 'name='." >&2
    exit 1
fi
cp "python/dist/solver" "${BUNDLE_DIR}/solver"
chmod +x "${BUNDLE_DIR}/solver"
echo "   staged ${BUNDLE_DIR}/solver"

# ── 2. Locate and stage GLPK (glpsol) + its shared-library dependencies ─────
echo ""
echo "-> Staging GLPK (glpsol) and its dependencies..."
GLPSOL_SRC="$(command -v glpsol || true)"
if [ -z "$GLPSOL_SRC" ]; then
    echo "error: glpsol not found on PATH. Install GLPK first (install.sh does this)." >&2
    exit 1
fi
echo "   found glpsol at ${GLPSOL_SRC}"

cp "$GLPSOL_SRC" "${BUNDLE_DIR}/glpsol"
chmod +x "${BUNDLE_DIR}/glpsol"
if ! command -v ldd >/dev/null 2>&1; then
    echo "error: ldd not found — cannot determine glpsol's shared-library dependencies." >&2
    exit 1
fi
# Standard system libs (libc, libm, ld-linux, ...) are assumed present on any
# target Linux and are not bundled; anything under /lib*/ or /usr/lib*/ that
# ISN'T glpk/gmp-specific is treated as such. This is a heuristic, not
# exhaustive — verify the bundled app actually launches on a clean machine
# (a container or VM without GLPK installed is the real test).
deps="$(ldd "$GLPSOL_SRC" | awk '{print $3}' | grep -E '^/' | grep -Ei 'glpk|gmp')"
for dep in $deps; do
    depname="$(basename "$dep")"
    cp "$dep" "${BUNDLE_DIR}/${depname}"
    echo "   staged ${BUNDLE_DIR}/${depname}"
done
echo "   NOTE: unlike macOS, this does not patch glpsol's RPATH (no patchelf dependency" \
     "added). It relies on app.go setting LD_LIBRARY_PATH to the extraction directory" \
     "at runtime — verify this actually launches cleanly on a clean machine."

# ── 3. Build the app ─────────────────────────────────────────────────────────
echo ""
echo "-> Running wails build for ${PLATFORM}..."
wails build -o DDOGearsetOptimizer
BUILT_PATH="build/bin/DDOGearsetOptimizer"
if [ ! -e "$BUILT_PATH" ]; then
    echo "error: expected output not found at '${BUILT_PATH}' — check build/bin/ manually." >&2
    ls -la build/bin/ 2>/dev/null || true
    exit 1
fi
echo "   wails build produced '${BUILT_PATH}'"

# ── 4. Copy into dist/<platform>/ — the "just copy and run" folder ─────────
echo ""
echo "-> Copying the finished build into ${DIST_DIR}/..."
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"
cp "$BUILT_PATH" "${DIST_DIR}/DDOGearsetOptimizer"
chmod +x "${DIST_DIR}/DDOGearsetOptimizer"
echo "   copied ${DIST_DIR}/DDOGearsetOptimizer"

echo ""
echo "Build complete (self-contained, ${PLATFORM})."
echo "Ready to hand off from: $(cd "$DIST_DIR" && pwd)"
echo "Bundle staged at: ${BUNDLE_DIR}/ — commit it so this build is reproducible without" \
     "redoing the glpsol staging step."
