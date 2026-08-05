#!/usr/bin/env bash
# build_releases.sh — Native, fully self-contained build for the current
# host platform.
#
# "Self-contained" means the resulting app needs NOTHING installed on the
# machine that runs it — no system GLPK, no Python. Everything required
# (the compiled Python solver, glpsol, and glpsol's own shared-library
# dependencies) is bundled under bundled/<goos>-<goarch>/, embedded into the
# Go binary at compile time (see embed_<goos>_<goarch>.go), and extracted to
# a temp directory at app startup (app.go's extractSolver()).
#
# Neither PyInstaller nor a real glpsol binary can be cross-compiled — both
# only ever produce a binary for the machine actually running this script.
# To ship for multiple platforms, run this script natively on one machine of
# each platform, commit the resulting bundled/<goos>-<goarch>/ directory,
# then hand-collect each platform's build output into dist/ (see
# package_release.sh) once you've done that on all the machines you need.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

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

GOOS="$(go env GOOS)"
GOARCH="$(go env GOARCH)"
PLATFORM="${GOOS}-${GOARCH}"
BUNDLE_DIR="bundled/${PLATFORM}"

echo "=== DDO Gearset Optimizer — native build (${PLATFORM}) ==="
mkdir -p "$BUNDLE_DIR"

# ── 1. Rebuild the embedded Python solver ───────────────────────────────────
echo ""
echo "-> Rebuilding Python solver with ${PYINSTALLER}..."
( cd python && "$PYINSTALLER" --noconfirm solver.spec )

SOLVER_SRC="python/dist/solver"
SOLVER_DST_NAME="solver"
if [ "$GOOS" = "windows" ]; then
    SOLVER_SRC="python/dist/solver.exe"
    SOLVER_DST_NAME="solver.exe"
fi
if [ ! -f "$SOLVER_SRC" ]; then
    echo "error: expected PyInstaller output at '${SOLVER_SRC}' — check python/solver.spec's" \
         "'name=' matches this script's assumption." >&2
    exit 1
fi
cp "$SOLVER_SRC" "${BUNDLE_DIR}/${SOLVER_DST_NAME}"
chmod +x "${BUNDLE_DIR}/${SOLVER_DST_NAME}"
echo "   staged ${BUNDLE_DIR}/${SOLVER_DST_NAME}"

# ── 2. Locate and stage GLPK (glpsol) + its shared-library dependencies ─────
echo ""
echo "-> Staging GLPK (glpsol) and its dependencies..."
GLPSOL_SRC="$(command -v glpsol || true)"
if [ -z "$GLPSOL_SRC" ]; then
    echo "error: glpsol not found on PATH. Install GLPK first (install.sh does this)." >&2
    exit 1
fi

case "$GOOS" in
    darwin)
        GLPSOL_DST_NAME="glpsol"
        cp "$GLPSOL_SRC" "${BUNDLE_DIR}/${GLPSOL_DST_NAME}"
        chmod u+w "${BUNDLE_DIR}/${GLPSOL_DST_NAME}"

        # Apple's real tools, by absolute path — NOT `command -v otool` /
        # `install_name_tool`. On a machine with Anaconda (or any other conda
        # install) on PATH ahead of /usr/bin, those names resolve to
        # Anaconda's bundled cctools-port reimplementation instead of
        # Apple's. cctools-port's install_name_tool writes what it itself
        # logs as a "fake signature" — Mach-O output that isn't a real Apple
        # code signature. That's what actually produces "You can't open ...
        # it may be damaged or incomplete": always use the real tools.
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

        # Every non-system dylib glpsol links against (system libs under
        # /usr/lib and /System are always present on macOS — no need to
        # bundle those).
        deps="$("$OTOOL" -L "$GLPSOL_SRC" | tail -n +2 | awk '{print $1}' | grep -Ev '^(/usr/lib|/System)')"
        for dep in $deps; do
            depname="$(basename "$dep")"
            if [ ! -f "${BUNDLE_DIR}/${depname}" ]; then
                cp "$dep" "${BUNDLE_DIR}/${depname}"
                chmod u+w "${BUNDLE_DIR}/${depname}"
                "$INSTALL_NAME_TOOL" -id "@rpath/${depname}" "${BUNDLE_DIR}/${depname}"
                echo "   staged ${BUNDLE_DIR}/${depname}"
            fi
            "$INSTALL_NAME_TOOL" -change "$dep" "@executable_path/${depname}" "${BUNDLE_DIR}/${GLPSOL_DST_NAME}"

            # One level of transitive deps (e.g. libglpk itself linking
            # libgmp) — repoint those at the bundled copies too.
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
        "$INSTALL_NAME_TOOL" -add_rpath "@executable_path" "${BUNDLE_DIR}/${GLPSOL_DST_NAME}" 2>/dev/null || true
        echo "   patched ${BUNDLE_DIR}/${GLPSOL_DST_NAME} to load its libraries from @executable_path"

        # install_name_tool invalidates any existing signature on the files
        # it touches — re-sign them ad-hoc (no paid Apple Developer ID
        # available) so they're at least well-formed, valid Mach-O binaries.
        for f in "${BUNDLE_DIR}"/*; do
            "$CODESIGN" --force --sign - "$f" >/dev/null 2>&1 || true
        done
        ;;
    linux)
        GLPSOL_DST_NAME="glpsol"
        cp "$GLPSOL_SRC" "${BUNDLE_DIR}/${GLPSOL_DST_NAME}"
        chmod +x "${BUNDLE_DIR}/${GLPSOL_DST_NAME}"
        if ! command -v ldd >/dev/null 2>&1; then
            echo "error: ldd not found — cannot determine glpsol's shared-library dependencies." >&2
            exit 1
        fi
        # Standard system libs (libc, libm, ld-linux, ...) are assumed
        # present on any target Linux and are not bundled; anything under
        # /lib*/ or /usr/lib*/ that ISN'T glpk/gmp-specific is treated as
        # such. This is a heuristic, not exhaustive — verify the bundled app
        # actually launches on a clean machine.
        deps="$(ldd "$GLPSOL_SRC" | awk '{print $3}' | grep -E '^/' | grep -Ei 'glpk|gmp')"
        for dep in $deps; do
            depname="$(basename "$dep")"
            cp "$dep" "${BUNDLE_DIR}/${depname}"
            echo "   staged ${BUNDLE_DIR}/${depname}"
        done
        echo "   NOTE: unlike macOS, this build does not patch glpsol's RPATH (no patchelf" \
             "dependency added). It relies on app.go setting LD_LIBRARY_PATH to the" \
             "extraction directory at runtime — verify this actually launches cleanly."
        ;;
    windows)
        echo "error: automated glpsol staging for Windows is not implemented." >&2
        echo "       Manually copy glpsol.exe and every DLL your GLPK install ships with" >&2
        echo "       (e.g. glpk_4_*.dll and any GMP DLL it depends on) into:" >&2
        echo "         ${BUNDLE_DIR}/" >&2
        echo "       Windows searches an exe's own directory for DLLs first, so no path" >&2
        echo "       patching is needed once they're sitting next to glpsol.exe — but this" >&2
        echo "       script cannot discover/copy them for you from a non-Windows host." >&2
        exit 1
        ;;
    *)
        echo "error: unsupported GOOS '${GOOS}' for GLPK bundling." >&2
        exit 1
        ;;
esac

# ── 3. Build the app ─────────────────────────────────────────────────────────
echo ""
echo "-> Running wails build for ${PLATFORM}..."
wails build -o DDOGearsetOptimizer

echo ""
case "$GOOS" in
    darwin) BUILT_PATH="build/bin/DDO Gearset Optimizer.app" ;;
    linux)  BUILT_PATH="build/bin/DDOGearsetOptimizer" ;;
    windows) BUILT_PATH="build/bin/DDOGearsetOptimizer.exe" ;;
    *) BUILT_PATH="build/bin/" ;;
esac

# ── 4. Sign the app (macOS) ──────────────────────────────────────────────────
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
if [ "$GOOS" = "darwin" ] && [ -e "$BUILT_PATH" ]; then
    echo "-> Ad-hoc code-signing ${BUILT_PATH}..."
    /usr/bin/codesign --force --deep --sign - "$BUILT_PATH"
    if /usr/bin/codesign --verify --deep --strict "$BUILT_PATH" 2>&1; then
        echo "   signature verified."
    else
        echo "warning: codesign --verify reported an issue — see output above." >&2
    fi
fi

if [ -e "$BUILT_PATH" ]; then
    echo "Build complete (self-contained, ${PLATFORM}): $(cd "$(dirname "$BUILT_PATH")" && pwd)/$(basename "$BUILT_PATH")"
    echo "Bundle staged at: ${BUNDLE_DIR}/ — commit it so this build is reproducible without" \
         "redoing the glpsol staging step."
else
    echo "warning: expected output not found at '${BUILT_PATH}' — check build/bin/ manually." >&2
    ls -la build/bin/ 2>/dev/null || true
fi
