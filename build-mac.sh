#!/usr/bin/env bash
# build-mac.sh — Native, fully self-contained macOS build.
#
# "Self-contained" means the resulting .app needs NOTHING installed on the
# machine that runs it — no system GLPK, no Python, no game data, and no
# network. Everything required (the compiled Python solver, glpsol, glpsol's
# own dylib dependencies, and catalog.db) is bundled under
# bundled/darwin-<arch>/, embedded into the Go binary at compile time (see
# embed_darwin_arm64.go / embed_darwin_amd64.go), and unpacked at startup —
# the solver into a version-stamped cache directory (app.go's
# extractSolver()), catalog.db into the user data directory
# (catalog_seed.go's ensureCatalogSeeded()).
#
# The ETL that produces catalog.db runs from step 1 below. It is DEV-ONLY: it
# reads DDOBuilderV2's XML here, on this machine, and nothing in the shipped
# app can invoke it (docs/0.5.0/00_ETL_START_HERE.md constraints 1 and 3).
#
# Neither PyInstaller nor a real glpsol binary can be cross-compiled — both
# only ever produce a binary for the machine actually running this script.
# To ship for both Intel and Apple Silicon, run this natively on one machine
# of each architecture and commit the resulting bundled/darwin-<arch>/.
#
# Every step below prints what it's doing before it does it, and what it
# found/produced after — nothing here should run silently.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "error: build-mac.sh must run on macOS (uname -s reported '$(uname -s)')." >&2
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
PLATFORM="darwin-${GOARCH}"
BUNDLE_DIR="bundled/${PLATFORM}"
DIST_DIR="dist/${PLATFORM}"

echo "=== DDO Gearset Optimizer — native macOS build (${PLATFORM}) ==="
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
             "new identities get minted): RELEASE=0 ./build-mac.sh" >&2
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
# NOT `rm -rf "${BUNDLE_DIR}"` — glpsol, its dylibs and catalog.db live there
# too and are staged by other steps.
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
chmod u+w "${BUNDLE_DIR}/glpsol"

# Apple's real tools, by absolute path — NOT `command -v otool` /
# `install_name_tool`. On a machine with Anaconda (or any other conda
# install) on PATH ahead of /usr/bin, those names resolve to Anaconda's
# bundled cctools-port reimplementation instead of Apple's. cctools-port's
# install_name_tool writes what it itself logs as a "fake signature" — Mach-O
# output that isn't a real Apple code signature. That's what actually
# produces "You can't open ... it may be damaged or incomplete": always use
# the real tools.
OTOOL="/usr/bin/otool"
INSTALL_NAME_TOOL="/usr/bin/install_name_tool"
CODESIGN="/usr/bin/codesign"
for tool in "$OTOOL" "$INSTALL_NAME_TOOL" "$CODESIGN"; do
    if [ ! -x "$tool" ]; then
        echo "error: ${tool} not found — install Xcode Command Line Tools:" >&2
        echo "  xcode-select --install" >&2
        exit 1
    fi
done

# Every non-system dylib glpsol links against (system libs under /usr/lib and
# /System are always present on macOS — no need to bundle those).
deps="$("$OTOOL" -L "$GLPSOL_SRC" | tail -n +2 | awk '{print $1}' | grep -Ev '^(/usr/lib|/System)')"
for dep in $deps; do
    depname="$(basename "$dep")"
    if [ ! -f "${BUNDLE_DIR}/${depname}" ]; then
        cp "$dep" "${BUNDLE_DIR}/${depname}"
        chmod u+w "${BUNDLE_DIR}/${depname}"
        "$INSTALL_NAME_TOOL" -id "@rpath/${depname}" "${BUNDLE_DIR}/${depname}"
        echo "   staged ${BUNDLE_DIR}/${depname}"
    fi
    "$INSTALL_NAME_TOOL" -change "$dep" "@executable_path/${depname}" "${BUNDLE_DIR}/glpsol"

    # One level of transitive deps (e.g. libglpk itself linking libgmp) —
    # repoint those at the bundled copies too.
    subdeps="$("$OTOOL" -L "$dep" | tail -n +2 | awk '{print $1}' | grep -Ev '^(/usr/lib|/System)')"
    for subdep in $subdeps; do
        subdepname="$(basename "$subdep")"
        if [ ! -f "${BUNDLE_DIR}/${subdepname}" ]; then
            cp "$subdep" "${BUNDLE_DIR}/${subdepname}"
            chmod u+w "${BUNDLE_DIR}/${subdepname}"
            "$INSTALL_NAME_TOOL" -id "@rpath/${subdepname}" "${BUNDLE_DIR}/${subdepname}"
            echo "   staged ${BUNDLE_DIR}/${subdepname}"
        fi
        "$INSTALL_NAME_TOOL" -change "$subdep" "@rpath/${subdepname}" "${BUNDLE_DIR}/${depname}"
    done
done
"$INSTALL_NAME_TOOL" -add_rpath "@executable_path" "${BUNDLE_DIR}/glpsol" 2>/dev/null || true
echo "   patched ${BUNDLE_DIR}/glpsol to load its libraries from @executable_path"

# install_name_tool invalidates any existing signature on the files it
# touches — re-sign them ad-hoc (no paid Apple Developer ID available) so
# they're at least well-formed, valid Mach-O binaries.
#
# Top-level files only. _internal/ is skipped deliberately: PyInstaller already
# ad-hoc signs everything it collects there, nothing in this script rewrites
# those binaries, and `codesign` on a plain (non-bundle) directory fails
# anyway — the error would just be swallowed by the `|| true` below.
echo "-> Ad-hoc re-signing patched binaries in ${BUNDLE_DIR}..."
for f in "${BUNDLE_DIR}"/*; do
    [ -f "$f" ] || continue
    "$CODESIGN" --force --sign - "$f" >/dev/null 2>&1 || true
done
echo "   done."

# ── 4. Build the app ─────────────────────────────────────────────────────────
# go:embed reads the FILESYSTEM, not git — anything sitting in BUNDLE_DIR right
# now is compiled into the shipped binary, tracked or not. SQLite's WAL
# sidecars appear whenever something opens the bundled catalog read-write, and
# the solver drops a progress log wherever it runs. Both are gitignored, so
# without this they would ride into a release completely unnoticed.
echo ""
echo "-> Clearing runtime debris out of ${BUNDLE_DIR} before embedding..."
rm -f "${BUNDLE_DIR}"/*.db-wal "${BUNDLE_DIR}"/*.db-shm "${BUNDLE_DIR}"/*.log
find "${BUNDLE_DIR}" -name '.DS_Store' -delete
echo "   done."

echo ""
echo "-> Running wails build for ${PLATFORM}..."
wails build -o DDOGearsetOptimizer
BUILT_PATH="build/bin/DDO Gearset Optimizer.app"
if [ ! -e "$BUILT_PATH" ]; then
    echo "error: expected output not found at '${BUILT_PATH}' — check build/bin/ manually." >&2
    ls -la build/bin/ 2>/dev/null || true
    exit 1
fi
echo "   wails build produced '${BUILT_PATH}'"

# ── 5. Sign the app ──────────────────────────────────────────────────────────
# Wails does not sign the .app itself. An entirely unsigned app, especially
# once quarantined (downloaded, extracted from a zip, etc.), is exactly what
# produces "You can't open ... it may be damaged or incomplete" — not just
# the milder, bypassable "unidentified developer" prompt. There is no paid
# Apple Developer ID here, so this is an AD-HOC signature (`--sign -`): it
# satisfies Gatekeeper's "is this signed and internally consistent" check,
# but does NOT satisfy notarization — a fresh download/AirDrop from another
# machine will still show the unidentified-developer prompt, which the user
# can bypass (right-click -> Open, or System Settings -> Privacy & Security).
# That prompt is expected and fine; "damaged or incomplete" is not.
echo ""
echo "-> Ad-hoc code-signing '${BUILT_PATH}'..."
"$CODESIGN" --force --deep --sign - "$BUILT_PATH"
if "$CODESIGN" --verify --deep --strict "$BUILT_PATH" 2>&1; then
    echo "   signature verified."
else
    echo "warning: codesign --verify reported an issue — see output above." >&2
fi

# ── 6. Copy into dist/<platform>/ — the "just copy and run" folder ─────────
echo ""
echo "-> Copying the finished build into ${DIST_DIR}/..."
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"
cp -R "$BUILT_PATH" "${DIST_DIR}/DDO Gearset Optimizer.app"
echo "   copied ${DIST_DIR}/DDO Gearset Optimizer.app"

# ── 7. Zip it for handoff ──────────────────────────────────────────────────
# `ditto`, not `zip`: it preserves symlinks, resource forks and the ad-hoc
# code signature applied in step 5. Plain `zip -r` flattens the symlinks
# inside .app frameworks, and the extracted copy can then be reported as
# damaged by Gatekeeper — the exact failure step 5's signing exists to avoid.
#
# Step 6 wipes DIST_DIR wholesale, so any previous zip is already gone; the
# explicit rm keeps the overwrite guaranteed if these steps are ever reordered.
ZIP_PATH="${DIST_DIR}/DDO Gearset Optimizer.zip"
echo ""
echo "-> Zipping for handoff..."
rm -f "$ZIP_PATH"
ditto -c -k --sequesterRsrc --keepParent \
    "${DIST_DIR}/DDO Gearset Optimizer.app" "$ZIP_PATH"
echo "   wrote ${ZIP_PATH} ($(du -h "$ZIP_PATH" | cut -f1))"

echo ""
echo "Build complete (self-contained, ${PLATFORM})."
echo "Ready to hand off from: $(cd "$DIST_DIR" && pwd)"
echo "Bundle staged at: ${BUNDLE_DIR}/ — commit it so this build is reproducible without" \
     "redoing the glpsol staging step."
