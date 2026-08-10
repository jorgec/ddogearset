#!/usr/bin/env bash
# package_release.sh — Archive dist/<platform>/ into releases/vX.Y.Z/.
#
# Workflow: run build-mac.sh / build-linux.sh / build-windows.ps1 natively on
# each platform you're releasing for. Each one copies its own finished,
# self-contained build into dist/<platform>/ automatically (e.g.
# dist/darwin-arm64/, dist/windows-amd64/, dist/linux-amd64/) — nothing to
# copy by hand. dist/<platform>/ is already immediately usable as-is (copy
# the folder, run what's inside); this script's only job is to also produce
# one shareable archive per platform in releases/, for e.g. attaching to a
# GitHub release.
#
# One archive per dist/<platform>/ subdirectory, containing everything in it:
#   darwin-*  -> zip
#   windows-* -> zip
#   anything else (linux-*, ...) -> tar.gz
#
# Version is read from wails.json. Output goes to releases/v<version>/ and is
# NOT committed automatically — review the archives, then `git add` them
# yourself when you're ready.
#
# The ETL is NOT run here. It runs inside each build script (they are the only
# things that produce a binary for it to be embedded into); this script only
# refuses to archive a dist/ that is older than its bundle — see the staleness
# guard below.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if command -v jq >/dev/null 2>&1; then
    VERSION="$(jq -r '.version' wails.json)"
else
    VERSION="$(grep -m1 '"version"' wails.json | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')"
fi

if [ -z "${VERSION:-}" ] || [ "$VERSION" = "null" ]; then
    echo "error: could not read version from wails.json" >&2
    exit 1
fi

if [ ! -d dist ]; then
    echo "error: dist/ does not exist — nothing to package. Run build-mac.sh /" \
         "build-linux.sh / build-windows.ps1 first." >&2
    exit 1
fi

# Only real platform subdirectories, ignore .gitkeep and dotfiles.
shopt -s nullglob dotglob
PLATFORM_DIRS=()
for entry in dist/*/; do
    entry="${entry%/}"
    base="$(basename "$entry")"
    case "$base" in
        .*) continue ;;
    esac
    if [ -d "$entry" ]; then
        PLATFORM_DIRS+=("$entry")
    fi
done
shopt -u dotglob

if [ ${#PLATFORM_DIRS[@]} -eq 0 ]; then
    echo "error: dist/ has no platform subdirectories — run build-mac.sh /" \
         "build-linux.sh / build-windows.ps1 first, each of which populates its" \
         "own dist/<platform>/ automatically." >&2
    exit 1
fi

OUTDIR="releases/v${VERSION}"
mkdir -p "$OUTDIR"

echo "=== Packaging release v${VERSION} from dist/ ==="
echo "Found ${#PLATFORM_DIRS[@]} platform folder(s): ${PLATFORM_DIRS[*]}"

# ── Staleness guard ─────────────────────────────────────────────────────────
# This script does not build anything — it archives whatever the build scripts
# left in dist/. Since 0.5.0 the app carries catalog.db compiled into it
# (go:embed), so "the ETL ran" and "the shipped binary contains that catalog"
# are two different facts. If anything in bundled/<platform>/ is NEWER than the
# dist artifact, the artifact predates the current bundle and would ship stale
# game data with a fresh version number on it — the exact mistake nobody would
# catch by looking at the archive.
newest_mtime() {
    find "$1" -type f -exec stat -f '%m' {} + 2>/dev/null \
        || find "$1" -type f -printf '%T@\n' 2>/dev/null | cut -d. -f1
}

for platform_dir in "${PLATFORM_DIRS[@]}"; do
    platform="$(basename "$platform_dir")"
    bundle_dir="bundled/${platform}"
    [ -d "$bundle_dir" ] || continue

    bundle_newest="$(newest_mtime "$bundle_dir" | sort -n | tail -1)"
    dist_newest="$(newest_mtime "$platform_dir" | sort -n | tail -1)"
    if [ -n "$bundle_newest" ] && [ -n "$dist_newest" ] && \
       [ "$bundle_newest" -gt "$dist_newest" ]; then
        echo "error: ${bundle_dir}/ is newer than ${platform_dir}/ — the build in" >&2
        echo "       dist/ predates the current bundle (solver, glpsol or catalog.db)" >&2
        echo "       and would ship stale data. Re-run the build script for ${platform}." >&2
        exit 1
    fi

    if [ -f "${bundle_dir}/catalog.db" ] && command -v python3 >/dev/null 2>&1; then
        python3 - "$platform" "${bundle_dir}/catalog.db" <<'PY'
import sqlite3, sys
platform, path = sys.argv[1], sys.argv[2]
conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
row = conn.execute("SELECT catalog_version, schema_version, built_at, "
                   "ddobuilder_commit FROM catalog_meta WHERE id = 1").fetchone()
conn.close()
print(f"   {platform}: catalog v{row[0]} (schema {row[1]}), built {row[2]}, data {row[3]}")
PY
    fi
done

for platform_dir in "${PLATFORM_DIRS[@]}"; do
    platform="$(basename "$platform_dir")"

    contents=()
    for f in "$platform_dir"/*; do
        [ -e "$f" ] && contents+=("$(basename "$f")")
    done
    if [ ${#contents[@]} -eq 0 ]; then
        echo "-> ${platform}: empty, skipping"
        continue
    fi

    case "$platform" in
        darwin-*|windows-*)
            archive="${OUTDIR}/${platform}.zip"
            echo "-> ${platform}/ (${contents[*]}) -> $(basename "$archive") (zip)"
            (cd "$platform_dir" && zip -qr "../../${archive}" .)
            ;;
        *)
            archive="${OUTDIR}/${platform}.tar.gz"
            echo "-> ${platform}/ (${contents[*]}) -> $(basename "$archive") (tar.gz)"
            (cd "$platform_dir" && tar -czf "../../${archive}" .)
            ;;
    esac
done

echo ""
echo "=== Release artifacts in ${OUTDIR}/ ==="
ls -lh "$OUTDIR"
echo ""
echo "Not committed. Review the archives, then:"
echo "  git add ${OUTDIR}"
echo "  git commit -m \"release: v${VERSION}\""
