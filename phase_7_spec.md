# Phase 7 Specification: UI Polish & Solver Locked Items

This specification addresses three user requests regarding the Auto-Solver configuration and Gearset Editor interaction.

## 1. Remove "Output JSON Filename"
**Goal**: Remove the legacy output filename field from the Auto-Solver screen since saving is now handled in the Summary tab.
**Modifications**:
- `frontend/src/lib/components/domain/JobConfigurationForm.svelte`: Delete the label and input field for "Output JSON Filename" (around line 285).
- `frontend/src/lib/store.ts`: (Optional) Remove `output_filename` from `OptimizationPayload` default values to keep it clean.
- `python/solver.py`: The `output_filename` parameter can be ignored or safely left with a fallback.

## 2. Enforce `pre_equipped` Items in Auto-Solver
**Goal**: When a user adds an item to an empty gearset (or any slot) and clicks "Optimize Gear", the solver must *lock* that item and build around it, rather than overwriting it.
**Analysis**: The issue occurs because manually selected items are passed to the Python backend in `pre_equipped`, but they get filtered out in `optimizer.py`'s `parse_items` function if they don't match the current solver configuration (e.g., armor type restrictions, excluded packs, Gem of Many Facets toggle). If they are filtered out, the solver's `create_model` function cannot find them in the `items` list and fails to add the lock constraint (`prob += x[(i, slot)] == 1`).
**Modifications**:
- `python/solver.py`: Pass `pre_equipped` to `parse_items`:
  ```python
  items = optimizer.parse_items(base_dir, cap, stat_priorities, armor_input, w1_list, w2_list, allow_gomf, art_slot_input, excluded_packs, quests_lookup, list(pre_equipped.values()))
  ```
- `python/optimizer.py`: Update `parse_items` signature to accept `pre_equipped_names=None`.
  Inside the item parsing loop (around line 77):
  ```python
  name = item_node.findtext('Name') or 'Unknown'
  is_pre_equipped = pre_equipped_names and name in pre_equipped_names
  ```
  Then, for all filtering logic (level range, gomf, weapon styles, armor styles, artifacts, excluded packs):
  If `is_pre_equipped` is true, **bypass** the rejection logic and keep the item's original slots. This guarantees the pre-equipped item is added to the `items` array so the solver can lock it.

## 3. Minor Artifact Auto-Sync & Uniqueness
**Goal**: If a user manually equips a Minor Artifact in the Gearset Editor, the Auto-Solver's "Minor Artifact" settings should automatically update to match. Furthermore, the UI must enforce that only 1 Minor Artifact can be placed.
**Modifications**:
- `frontend/src/lib/components/domain/GearsetEditor.svelte`:
  Update the `selectItem` function to detect if the selected item is a minor artifact:
  ```typescript
  const isMinor = item.MinorArtifact !== undefined && item.MinorArtifact !== null;
  if (isMinor) {
      // 1. Update solver config
      const baseSlot = selectedSlot.replace('_1', '').replace('_2', '');
      $configStore.reserved_minor_artifact_slot = baseSlot;
      $configStore.is_dino_artifact = item.Name.toLowerCase().includes('dinosaur');
      
      // 2. Enforce uniqueness: check all other equipped items to see if they are minor artifacts
      // To do this reliably without async fetching, we can iterate through the existing gearSet,
      // and if we know another slot holds a minor artifact, we clear it.
      // We can maintain a local state variable `currentMinorArtifactSlot` in GearsetEditor 
      // or simply fetch item details for all equipped items and clear the one that is a minor artifact.
  }
  ```
  Implementation approach for uniqueness: Add a reactive block or local state tracking the current slot containing a minor artifact. When a new minor artifact is placed, if `currentMinorArtifactSlot` exists and is different from `selectedSlot`, call `clearSlot(currentMinorArtifactSlot)`.

## Summary of Files to Change
1. `frontend/src/lib/components/domain/JobConfigurationForm.svelte`
2. `frontend/src/lib/components/domain/GearsetEditor.svelte`
3. `python/solver.py`
4. `python/optimizer.py`
