#!/usr/bin/env bash
# build-linux.sh — Native, fully self-contained Linux build.
#
# "Self-contained" means the resulting binary needs NOTHING installed on the
# machine that runs it — no system GLPK, no Python, no game data, and no
# network. Everything required (the compiled Python solver, glpsol, glpsol's
# own shared-library dependencies, and catalog.db) is bundled under
# bundled/linux-<arch>/, embedded into the Go binary at compile time (see
# embed_linux_amd64.go), and unpacked at startup — the solver into a
# version-stamped cache directory (app.go's extractSolver()), catalog.db into
# the user data directory (catalog_seed.go's ensureCatalogSeeded()).
#
# The ETL that produces catalog.db runs from step 1 below. It is DEV-ONLY: it
# reads DDOBuilderV2's XML here, on this machine, and nothing in the shipped
# app can invoke it (docs/0.5.0/00_ETL_START_HERE.md constraints 1 and 3).
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

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "error: '${PYTHON}' not found. The ETL needs a Python 3 interpreter" \
         "(standard library only — it imports no third-party packages)." >&2
    exit 1
fi

# RELEASE=1 (the default) passes --strict to the ETL: an unexplained rename in
# DDOBuilderV2 fails the build instead of quietly minting a new identity that
# orphans saved gearsets. RELEASE=0 is for day-to-day dev builds mid-week, when
# a data bump should not block work — see START_HERE §6.2.
RELEASE="${RELEASE:-1}"

GOARCH="$(go env GOARCH)"
PLATFORM="linux-${GOARCH}"
BUNDLE_DIR="bundled/${PLATFORM}"
DIST_DIR="dist/${PLATFORM}"

echo "=== DDO Gearset Optimizer — native Linux build (${PLATFORM}) ==="
mkdir -p "$BUNDLE_DIR"

# ── 1. Build catalog.db from DDOBuilderV2 (the ETL) ────────────────────────
echo ""
if [ "$RELEASE" = "1" ]; then
    echo "-> Building catalog.db (strict — unresolved identity drift fails the build)..."
    STRICT_FLAG="--strict"
else
    echo "-> Building catalog.db (permissive — RELEASE=0)..."
    STRICT_FLAG=""
fi
# `|| status=$?`, not `if ! ...; then status=$?` — inside an `if !` body $? is
# the status of the negation (always 0), not of the command that failed, and
# the ETL's exit code is load-bearing here (2 == unresolved drift).
status=0
"$PYTHON" -m etl --out "${BUNDLE_DIR}/catalog.db" $STRICT_FLAG || status=$?
if [ "$status" -ne 0 ]; then
    if [ "$status" -eq 2 ]; then
        echo "" >&2
        echo "error: DDOBuilderV2 renamed something the ETL will not guess at." >&2
        echo "       Read the drift report it just wrote under etl/drift/, record the" >&2
        echo "       answers in etl/aliases.yaml, and re-run. To build anyway (dev only," \
             "new identities get minted): RELEASE=0 ./build-linux.sh" >&2
    fi
    exit "$status"
fi

# ── 2. Rebuild the embedded Python solver ───────────────────────────────────
echo ""
echo "-> Rebuilding Python solver with ${PYINSTALLER}..."
( cd python && "$PYINSTALLER" --noconfirm solver.spec )
# --onedir (python/solver.spec): an executable plus an _internal/ tree it
# cannot start without. Both are staged; app.go's extractSolver recurses.
if [ ! -x "python/dist/solver/solver" ]; then
    echo "error: expected PyInstaller output at 'python/dist/solver/solver' — check" \
         "python/solver.spec (it must have a COLLECT step; --onefile puts the" \
         "binary at python/dist/solver instead)." >&2
    exit 1
fi
# Wipe the previous solver tree first: PyInstaller's output is authoritative,
# and a file it no longer produces must not survive into the bundle. Explicitly
# NOT `rm -rf "${BUNDLE_DIR}"` — glpsol, its libraries and catalog.db live
# there too and are staged by other steps.
rm -rf "${BUNDLE_DIR}/_internal" "${BUNDLE_DIR}/solver"
cp -R "python/dist/solver/_internal" "${BUNDLE_DIR}/_internal"
cp "python/dist/solver/solver" "${BUNDLE_DIR}/solver"
chmod +x "${BUNDLE_DIR}/solver"
echo "   staged ${BUNDLE_DIR}/solver + _internal/ ($(find "${BUNDLE_DIR}/_internal" -type f | wc -l | tr -d ' ') files)"

# go:embed SILENTLY SKIPS SYMLINKS (`go doc embed`), and PyInstaller's --onedir
# output contains four: _internal/Python points at the framework's real library,
# and Python.framework has three more. Embedded, those paths simply vanish, and
# the extracted solver dies at startup with "Failed to load Python shared
# library" — which is exactly what happened, unnoticed, from the --onedir switch
# until the app was first launched.
#
# The links are recorded here and recreated at extraction (app.go's
# recreateSymlinks). A manifest rather than `cp -RL`, which would work and cost
# 14 MB of duplicated library paid twice — once inside the binary, once in every
# extracted cache directory.
echo "-> Recording symlinks for extraction (go:embed cannot carry them)..."
"$PYTHON" - "$BUNDLE_DIR" <<'PYEOF'
import json, os, sys
bundle = sys.argv[1]
links = {}
for root, dirs, files in os.walk(bundle):
    for name in dirs + files:
        full = os.path.join(root, name)
        if os.path.islink(full):
            links[os.path.relpath(full, bundle)] = os.readlink(full)
with open(os.path.join(bundle, ".symlinks.json"), "w") as f:
    json.dump(links, f, indent=2, sort_keys=True)
print(f"   recorded {len(links)} symlink(s)")
PYEOF

# ── 3. Locate and stage GLPK (glpsol) + its shared-library dependencies ─────
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

# ── 4. Build the app ─────────────────────────────────────────────────────────
# go:embed reads the FILESYSTEM, not git — anything sitting in BUNDLE_DIR right
# now is compiled into the shipped binary, tracked or not. SQLite's WAL
# sidecars appear whenever something opens the bundled catalog read-write, and
# the solver drops a progress log wherever it runs. Both are gitignored, so
# without this they would ride into a release completely unnoticed.
echo ""
echo "-> Clearing runtime debris out of ${BUNDLE_DIR} before embedding..."
rm -f "${BUNDLE_DIR}"/*.db-wal "${BUNDLE_DIR}"/*.db-shm "${BUNDLE_DIR}"/*.log
echo "   done."

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

# ── 5. Copy into dist/<platform>/ — the "just copy and run" folder ─────────
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
