#!/usr/bin/env bash
# Update the DDOBuilderV2 dataset and rebuild catalog.db for all platforms.
#
# Usage:
#   ./update-catalog.sh           # pull latest + rebuild
#   ./update-catalog.sh --strict  # same, but fail on unresolved identity drift
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

STRICT=""
if [[ "${1:-}" == "--strict" ]]; then
    STRICT="--strict"
fi

# ── 1. Update the DDOBuilderV2 submodule ─────────────────────────────────────

echo "==> Updating data/ddobuilder submodule..."
git submodule update --init --depth 1

# Pull the latest commit from upstream (the submodule pin in .gitmodules
# points at Maetrim/DDOBuilderV2 main).
(cd data/ddobuilder && git fetch origin main && git checkout origin/main)

COMMIT="$(cd data/ddobuilder && git rev-parse --short HEAD)"
echo "    now at $COMMIT"

# ── 2. Rebuild catalog.db ────────────────────────────────────────────────────

# Every platform that has a bundled/ directory gets the same catalog.
TARGETS=()
for dir in bundled/*/; do
    if [[ -d "$dir" ]]; then
        TARGETS+=("$dir/catalog.db")
    fi
done

if [[ ${#TARGETS[@]} -eq 0 ]]; then
    echo "error: no bundled/ platform directories found" >&2
    exit 1
fi

# Build once into the first target, then copy to the rest (the catalog is
# platform-independent — it's pure SQLite).
PRIMARY="${TARGETS[0]}"
echo "==> Building catalog.db (${STRICT:-permissive})..."
python3 -m etl --out "$PRIMARY" $STRICT

for target in "${TARGETS[@]:1}"; do
    cp "$PRIMARY" "$target"
    echo "    copied to $target"
done

echo ""
echo "Done. Catalogs updated to DDOBuilderV2 $COMMIT."
echo ""
echo "If the ETL reported identity drift, resolve it in etl/aliases.yaml"
echo "and re-run with --strict before committing."
