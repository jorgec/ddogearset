# Handoff — Trove Inventory Import Feature

**Session date:** 2026-08-05
**Spec:** `docs/TROVE_INVENTORY_IMPORT_SPEC.md` (planning) → implemented same session.
**Status:** Implemented, verified end-to-end through the real compiled binary. Not committed.

## Update: standalone "Owned Items" screen (same session, second pass)

The user asked for the Trove loading mechanism to also exist as its own screen
(separate from the solver-form accordion above), with: a load button, toast
alerts on success/fail, a table of the CSV's usable items, and a sliding
drawer on row click showing item detail — then simplified scope with "don't
include augments."

**What shipped:**
- `GetTroveOwnedItems` RPC (`trove_inventory.go`) — items-only, reuses
  `parseTroveInventoryCSV`'s Location/Binding filter, then cross-references
  `a.itemsByName`/`a.itemsCache` directly in Go (no Python round-trip — this
  screen only browses, it doesn't feed the solver). Returns names already
  pre-filtered to real DDOBuilderV2 matches, sorted alphabetically.
- `frontend/src/lib/components/domain/OwnedItems.svelte` (new) — load button,
  toast on success (`Loaded N rows — M usable items.`) / failure, searchable
  table (Name/ML/Pack), and a true sliding drawer built with Svelte's
  `transition:fly`/`transition:fade` (not a CSS class toggle — the drawer
  `<div>` only exists in the DOM while open, so there's no "closed" state for
  a transform transition to animate from). Drawer reuses `ItemDetail.svelte`
  in `mode="view"`, same as `GearsetEditor.svelte` does.
- New "Owned Items" tab in `App.svelte` / `currentTab` store, between "Item
  Search" and "Summary Breakdown".

**Verified:**
- `go build ./...`, `go vet ./...`, `go test ./...` — clean.
- `npm run check` — 0 errors (baseline unchanged). `npm run build` — succeeds.
- `python -m pytest python/tests/ -q` — 95 passed (unaffected, this pass was
  Go/Svelte only).
- Real Go smoke test against `TroveExport.Inventory.csv`: 420 rows → 152
  matched items (e.g. `+1 Starter Dagger (ML 2, pack "base")`).
- Full `build-mac.sh` run — succeeded, `dist/darwin-arm64/` refreshed.
  Launched the built `.app`, confirmed via `pgrep` it starts without
  crashing, then stopped it.
- **Not verified:** actual click-through of the drawer/table in the running
  UI — no way to screenshot/drive a compiled native Wails window from this
  environment. Only Go/Python logic and app-launch-without-crash were
  confirmed directly.

**Not committed** (same as the accordion work above) — `trove_inventory.go`,
`OwnedItems.svelte`, and the rebuilt solver binaries are staged but not
committed; `App.svelte`/`store.ts` changes are unstaged. CHANGELOG.md 0.2.1
updated with both bullets.

## What shipped

A new "Owned Items (Trove Import)" section in the solver form lets the user load a
Trove inventory CSV export and restrict item/augment selection to gear they actually
own, instead of the full DDOBuilderV2 catalog.

**Filter chain** (validated against a real 420-row export before any code was written):
```
Location != "SharedCrafting"
AND Binding ∈ {"BtA", "BtC"}
AND Name matches a DDOBuilderV2 item/augment name exactly (else silently dropped)
```

**Deliberately out of scope**, per explicit direction during planning: filigree
matching (Trove's filigree names drop tier/value entirely and don't match
DDOBuilderV2's format — 0% match rate confirmed), and random/procedural loot items
(names like `+1 Deflecting 2 Hide of Light Resistance 3` have no corresponding static
catalog entry).

## Files touched

- **`trove_inventory.go`** (new) — CSV parsing (`parseTroveInventoryCSV`) + the
  `LoadTroveInventory` RPC. Reads CSV columns by name, not fixed index, so a reordered
  Trove export layout doesn't silently misparse. Strips a leading UTF-8 BOM. Tolerates
  ragged rows (`FieldsPerRecord = -1`) rather than aborting the whole file on one bad
  row.
- **`app.go`** — `OptimizationPayload.OwnedItemNames []string` (`omitempty`). Empty/
  absent means unrestricted — this is an opt-in filter, not a standing mode.
- **`python/optimizer.py`** — `parse_items`/`parse_augments` each gained an
  `owned_names=None` parameter. One more `if` alongside the existing pack-exclusion
  check; same `is_pre_equipped`/`is_pre_filled` bypass convention already used for the
  ML floor and pack exclusion (something already locked into the gearset is never
  dropped by a pool filter).
- **`python/solver.py`** — reads `owned_item_names` from the payload, converts to a
  `set` (or `None` if empty/absent — **not** an empty set, which would mean "owns
  nothing" instead of "unrestricted"; this distinction is load-bearing, see AC-3 in the
  spec). Explicitly exempts `stat_search` mode — that's a browse-the-whole-catalog
  feature, unrelated to what you own.
- **`frontend/src/lib/store.ts`** — `configStore.owned_item_names: string[]`, empty by
  default.
- **`frontend/src/lib/components/domain/JobConfigurationForm.svelte`** — new Accordion
  section: file picker (reads client-side via `FileReader`, matching the existing
  `loadGearset` pattern in `Summary.svelte` — Go never opens a file by path) + a toggle
  disabled until a CSV is loaded. `troveOwnedNames` (survives toggling off) is separate
  from `restrictToOwned` (the actual switch); `$configStore.owned_item_names` is only
  populated when both are true.
- **`python/tests/test_phase10_tiered.py`** — 4 new tests. Unlike the rest of the file
  (synthetic `make_item` fixtures), these exercise `parse_items`/`parse_augments`
  directly against the real DDOBuilderV2 checkout, since `owned_names` is applied
  inside the XML-walking loop itself. Guarded with `@_skip_without_real_data` so they
  skip cleanly (not fail) in an environment where DDOBuilderV2 hasn't been fetched yet.
- **`docs/TROVE_INVENTORY_IMPORT_SPEC.md`** — the spec, written and implemented in the
  same session.
- Wails bindings regenerated (`frontend/wailsjs/go/*`).
- `python/dist/solver` and `bundled/darwin-arm64/solver` rebuilt and re-staged so the
  fix is reflected in what actually runs, not just source.
- `dist/darwin-arm64/DDO Gearset Optimizer.app` refreshed via `build-mac.sh` — this
  overwrote a build the user had previously committed themselves; that's the intended
  behavior of the automated `dist/` copying (always reflects the latest build), not an
  accident, but worth knowing if the diff looks large.

## Two real bugs found and fixed during implementation (not present in the final code)

1. **Go compiler rejected a BOM-stripping string literal.** Writing
   `strings.TrimPrefix(csvContent, "﻿")` initially with a literal (invisible) BOM
   character embedded in the source produced `invalid BOM in the middle of the file` —
   Go only permits a BOM at the very start of a `.go` file, not inside a string
   literal. Fixed by using the escaped `﻿` form instead of a literal character.
2. **My own test script used a wrong relative path** (`DDOBuilderV2/...` instead of
   `../DDOBuilderV2/...` from `python/`'s working directory), which silently returned
   zero items (glob on a nonexistent directory returns no matches, no error) and
   briefly looked like a real regression. Not a bug in the implementation — worth
   noting only because it wasted a few minutes chasing a phantom.

## Verification performed

- Go: `LoadTroveInventory` against the real CSV reproduced an **independently computed
  Python analysis exactly** — 420 total rows, 190 distinct owned names after the
  Location/Binding filter.
- Python: `parse_items` restricted from 2,127 unrestricted items down to the 29 that
  are both in-range and owned, with correct real names (`Legendary Keylock Ring`,
  `Legendary Bottle of Shadows`, etc.). `parse_augments` isolated separately (14 → 1)
  since testing it against the real CSV directly was confounded by an unrelated,
  pre-existing behavior (heroic-tier CSV rows falling outside the default ML29-34
  search floor — not a bug, just not the right fixture for isolating this specific
  check).
- **Full stack, through the actual compiled/bundled solver binary** (not source): built
  a real `OptimizationPayload` with all 190 owned names, ran `./python/dist/solver`
  directly, got back a real solve that selected exactly two items — both confirmed
  present in the owned-names list. Filigrees came back unrestricted, as scoped.
- `npm run check`: 0 new errors (same pre-existing baseline as every other pass this
  session).
- `go build`/`vet`/`test`: clean. `pytest`: 95 passed (91 prior + 4 new).

## Not done / deferred

- No "N matched / M unmatched" reporting UI — unmatched CSV names are silently dropped,
  per explicit scope decision, no reporting requirement exists for this pass.
- No live UI smoke test (clicking through the actual file picker in a running app) —
  verified the underlying RPC and solve path directly instead; the Svelte wiring itself
  is straightforward enough (mirrors two already-proven patterns: `loadGearset`'s
  FileReader usage and `togglePack`'s array-toggle pattern) that this is lower risk
  than the backend logic, but it's still worth a real click-through before calling this
  fully done.
- Filigree matching and random-loot item support remain explicitly out of scope, not
  partially started — see the spec's "Scope" section for the reasoning (0% match rate
  for filigrees, no catalog entry to match against for random loot at all).

## Suggested next step

Click through the actual file picker in a running `wails dev` session with the real
CSV, then decide whether to commit. Nothing has been committed this session.
