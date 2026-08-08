#!/usr/bin/env bash
# build-mac.sh — Native, fully self-contained macOS build.
#
# "Self-contained" means the resulting .app needs NOTHING installed on the
# machine that runs it — no system GLPK, no Python. Everything required
# (the compiled Python solver, glpsol, and glpsol's own dylib dependencies)
# is bundled under bundled/darwin-<arch>/, embedded into the Go binary at
# compile time (see embed_darwin_arm64.go / embed_darwin_amd64.go), and
# extracted to a temp directory at app startup (app.go's extractSolver()).
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

GOARCH="$(go env GOARCH)"
PLATFORM="darwin-${GOARCH}"
BUNDLE_DIR="bundled/${PLATFORM}"
DIST_DIR="dist/${PLATFORM}"

echo "=== DDO Gearset Optimizer — native macOS build (${PLATFORM}) ==="
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
echo "-> Ad-hoc re-signing patched binaries in ${BUNDLE_DIR}..."
for f in "${BUNDLE_DIR}"/*; do
    "$CODESIGN" --force --sign - "$f" >/dev/null 2>&1 || true
done
echo "   done."

# ── 3. Build the app ─────────────────────────────────────────────────────────
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

# ── 4. Sign the app ──────────────────────────────────────────────────────────
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

# ── 5. Copy into dist/<platform>/ — the "just copy and run" folder ─────────
echo ""
echo "-> Copying the finished build into ${DIST_DIR}/..."
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"
cp -R "$BUILT_PATH" "${DIST_DIR}/DDO Gearset Optimizer.app"
echo "   copied ${DIST_DIR}/DDO Gearset Optimizer.app"

# ── 6. Zip it for handoff ──────────────────────────────────────────────────
# `ditto`, not `zip`: it preserves symlinks, resource forks and the ad-hoc
# code signature applied in step 4. Plain `zip -r` flattens the symlinks
# inside .app frameworks, and the extracted copy can then be reported as
# damaged by Gatekeeper — the exact failure step 4's signing exists to avoid.
#
# Step 5 wipes DIST_DIR wholesale, so any previous zip is already gone; the
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
