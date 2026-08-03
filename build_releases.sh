#!/usr/bin/env bash
# build_releases.sh — Cross-platform release builder for DDO Gearset Optimizer v0.1.0
# Run this script from the project root. Requires Docker to be running for Windows/Linux builds.

set -e

VERSION="0.1.0"
OUTDIR="releases/v${VERSION}"
mkdir -p "$OUTDIR"

echo "=== DDO Gearset Optimizer v${VERSION} Release Builder ==="

# ── macOS (native) ────────────────────────────────────────────────────────────
echo ""
echo "→ Building macOS (darwin/arm64)..."
wails build -platform darwin/arm64 -o DDOGearsetOptimizer
cp -r "build/bin/DDO Gearset Optimizer.app" "${OUTDIR}/DDOGearsetOptimizer-v${VERSION}-macOS-arm64.app"
cd "$OUTDIR"
zip -r "DDOGearsetOptimizer-v${VERSION}-macOS-arm64.zip" "DDOGearsetOptimizer-v${VERSION}-macOS-arm64.app"
cd -
echo "✓ macOS build complete"

# ── Linux (Debian via Docker) ─────────────────────────────────────────────────
echo ""
echo "→ Building Linux/Debian (linux/amd64) via Docker..."
docker build -f .github/Dockerfile.linux -t ddo-gearset-linux .
docker run --rm -v "$(pwd)/${OUTDIR}:/output" ddo-gearset-linux cp -r /app/build/bin/DDOGearsetOptimizer /output/
mv "${OUTDIR}/DDOGearsetOptimizer" "${OUTDIR}/DDOGearsetOptimizer-v${VERSION}-linux-amd64"
cd "$OUTDIR"
tar -czf "DDOGearsetOptimizer-v${VERSION}-linux-amd64.tar.gz" "DDOGearsetOptimizer-v${VERSION}-linux-amd64"
cd -
echo "✓ Linux build complete"

# ── Windows (cross-compile via Docker) ────────────────────────────────────────
echo ""
echo "→ Building Windows (windows/amd64) via Docker..."
docker build -f .github/Dockerfile.windows -t ddo-gearset-windows .
docker run --rm -v "$(pwd)/${OUTDIR}:/output" ddo-gearset-windows cp -r /app/build/bin/DDOGearsetOptimizer.exe /output/
mv "${OUTDIR}/DDOGearsetOptimizer.exe" "${OUTDIR}/DDOGearsetOptimizer-v${VERSION}-windows-amd64.exe"
cd "$OUTDIR"
zip "DDOGearsetOptimizer-v${VERSION}-windows-amd64.zip" "DDOGearsetOptimizer-v${VERSION}-windows-amd64.exe"
cd -
echo "✓ Windows build complete"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=== Release artifacts in ${OUTDIR}/ ==="
ls -lh "$OUTDIR"
