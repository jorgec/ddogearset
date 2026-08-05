#!/usr/bin/env bash
# package_release.sh — Archive everything staged in dist/ into releases/vX.Y.Z/.
#
# Workflow: run build_releases.sh natively on each platform you're releasing
# for, then manually copy each platform's build output (a .app bundle, an
# .exe, or a plain Linux binary) into dist/ on this machine. This script does
# not build anything — it only archives whatever it finds directly inside
# dist/, one archive per top-level entry:
#   *.app/            -> zip
#   *.exe              -> zip
#   anything else       -> tar.gz  (assumed to be a Linux/macOS binary)
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
    echo "error: dist/ does not exist — nothing to package" >&2
    exit 1
fi

# Only real entries, ignore .gitkeep and dotfiles.
shopt -s nullglob dotglob
ENTRIES=()
for entry in dist/*; do
    base="$(basename "$entry")"
    case "$base" in
        .*) continue ;;
    esac
    ENTRIES+=("$entry")
done
shopt -u dotglob

if [ ${#ENTRIES[@]} -eq 0 ]; then
    echo "error: dist/ is empty — add the platform build(s) you want to package first" >&2
    exit 1
fi

OUTDIR="releases/v${VERSION}"
mkdir -p "$OUTDIR"

echo "=== Packaging release v${VERSION} from dist/ ==="

for entry in "${ENTRIES[@]}"; do
    base="$(basename "$entry")"
    case "$base" in
        *.app)
            name="${base%.app}"
            archive="${OUTDIR}/${name}.zip"
            echo "-> ${base} -> $(basename "$archive") (zip)"
            (cd dist && zip -qr "../${archive}" "$base")
            ;;
        *.exe)
            name="${base%.exe}"
            archive="${OUTDIR}/${name}.zip"
            echo "-> ${base} -> $(basename "$archive") (zip)"
            (cd dist && zip -qj "../${archive}" "$base")
            ;;
        *)
            archive="${OUTDIR}/${base}.tar.gz"
            echo "-> ${base} -> $(basename "$archive") (tar.gz)"
            (cd dist && tar -czf "../${archive}" "$base")
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
