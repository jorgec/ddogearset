# Phase 8 Specification: Fixes, Overrides, and App Icon

## 1. PyInstaller Rebuild (Fix for Overwritten Items)
**Issue**: The Phase 7 Python changes (`pre_equipped` locking logic) were applied to the source files (`optimizer.py`, `solver.py`), but the bundled PyInstaller binary (`python/dist/solver`) embedded into Go was never recompiled. Thus, the old logic ran and overwrote items.
**Fix**: Run `pyinstaller solver.spec` within the `python/` directory to rebuild the Python binary.

## 2. Minor Artifact Override Checkbox
**Issue**: Sometimes items like "The Spring Equinox" fail to be automatically detected as minor artifacts (possibly due to XML formatting differences or unmarshaling quirks with empty tags).
**Fix**: Add a "Is Minor Artifact?" checkbox in the Item Details pane in `GearsetEditor.svelte`. When a user toggles it on, it will run the same logic to update the Auto-Solver configuration and clear any other minor artifacts in the gearset.

## 3. Remove Legacy Minor Artifact Filigrees Section
**Issue**: The item details pane in `GearsetEditor.svelte` still renders a legacy "Minor Artifact Filigrees" section and a "Sentient Weapon Filigrees" section, which have since been moved to the dedicated Filigrees tab.
**Fix**: Delete lines 418 to 528 (the `<div class="mt-6 pt-4 border-t border-border/50">` containing the filigree slots) from `GearsetEditor.svelte`.

## 4. App Icon
**Issue**: The user provided an `icon.jpg` image to be used as the application icon.
**Fix**: 
- Use ImageMagick (`magick`) or `sips` to convert `icon.jpg` to `build/appicon.png` (for macOS/Linux) and `build/windows/icon.ico` (for Windows).
- (Wails automatically detects `build/appicon.png` during `wails build`).
