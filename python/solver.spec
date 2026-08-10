# -*- mode: python ; coding: utf-8 -*-
#
# --onedir, NOT --onefile. Measured on this project (docs/0.5.0/00_ETL_START_HERE.md
# Phase 7): --onefile + UPX costs ~3.8 s on EVERY invocation (~10 s cold),
# because the bootloader re-extracts the whole ~8 MB archive to a temp
# directory before a single line of Python runs. --onedir starts in ~0.1 s.
#
# The app invokes this binary once per solve, so that cost is paid every time
# the user presses Solve — it is not a one-off startup tax. The trade is a
# directory of ~55 files instead of one, which costs nothing here: the whole
# tree is embedded into the Go binary (go:embed all:bundled/<platform>) and
# extracted ONCE into a version-stamped cache directory (app.go's
# extractSolver), not on every launch.
#
# UPX is off for the same reason it was on before is now wrong: compressed
# shared libraries have to be decompressed at load time, which is exactly the
# per-invocation cost this change exists to remove.

a = Analysis(
    ['solver.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # the onedir switch: binaries go to COLLECT below
    name='solver',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='solver',
)
