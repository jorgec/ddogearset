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
