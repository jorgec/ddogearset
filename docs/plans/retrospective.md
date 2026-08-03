# DDO Gearset Optimizer — Project Retrospective

> A phase-by-phase record of what was built, key decisions made, challenges encountered, and outcomes.

---

## Phase 1 — Project Bootstrap & Wails Scaffolding

### What Was Built
- Initialized the Go module (`goGearset`) with the Wails v2 framework
- Established the core directory layout: `frontend/`, `internal/`, `python/`, `scripts/`, `docs/`
- Configured the Wails project (`wails.json`) targeting macOS arm64
- Set up the Svelte + Vite frontend with basic tab skeleton
- Wrote foundational `App` struct in `app.go` with startup lifecycle
- Added placeholder Go test infrastructure

### Key Decisions
- **Wails over Electron** — chosen for much smaller binary size and native Go integration without a full Chromium runtime
- **Svelte over React/Vue** — compile-time framework produces tiny JS bundles and has zero runtime overhead, well-suited for a data-heavy dashboard

### Challenges
- Wails `wails generate module` must be re-run after every Go struct change; this became a frequent source of "why isn't my new field appearing in TypeScript?" confusion
- Initial Vite/Svelte configuration needed tuning to work correctly inside the Wails asset server

### Outcome
✅ Clean project skeleton with hot-reload dev mode working end-to-end.

---

## Phase 2 — XML Parsing & Data Enrichment

### What Was Built
- `internal/models/models.go` — Go structs mirroring the DDOBuilder XML format (`XMLItem`, `XMLAugment`, `XMLFiligree`, `XMLQuest`)
- `internal/services/parser.go` — XML deserializers for Items, Augments, and FiligreeSets directories
- `internal/services/enrichment.go` — Post-parse enrichment pipeline:
  - Wiki URL injection (DDO wiki URL constructed from item name)
  - Pack mapping: cross-referencing `PackMappings.json` to tag each item with its expansion pack
  - Raid flag: querying the quest XML lookup to mark items from raid quests as `is_raid: true`
- `scripts/update_data.go` — CLI tool that orchestrates parsing and outputs a full `enriched_items.json`
- Full Go test suite: `parser_test.go` and `enrichment_test.go`

### Key Decisions
- **Separate enrichment pass** — keeping parsing (raw XML → struct) and enrichment (struct → augmented struct) in separate layers makes each independently testable
- **DDOBuilderV2 as the source of truth** — rather than maintaining our own item database, we read directly from the external DDOBuilderV2 repository's output files, ensuring data stays current with game patches

### Challenges
- DDOBuilder's XML schema is inconsistent: some items use `<EquipmentSlot>` and others use `<Slots>`; the parser had to handle both
- Raid detection required cross-referencing `Quests.xml` against item drop locations — a multi-step join with no direct foreign key

### Outcome
✅ All tests pass. Item cache loads ~3,000+ items at startup with full enrichment metadata.

---

## Phase 3 — Python ILP Solver Integration

### What Was Built
- **Forked** the original `gearset/optimizer.py` into `python/optimizer.py` — all future development happens in this repo copy
- New **JSON payload schema** for Go-to-Python communication, replacing the old CLI argument interface
- **`optimizer.py` rewrites**:
  - `parse_items()` now accepts `excluded_packs` and filters accordingly
  - Raid constraint: `Σ(raid items) ≤ raid_item_limit` added as a PuLP constraint
  - Weighted objective function: replaced the old ordered-priority logic with a 1–100 weight dictionary. The objective is now `Maximize Σ(weight[stat] × realized_value[stat])`
- `solver.py` — thin entry point that reads stdin JSON, calls optimizer, and prints `JSON_RESULT:{...}` to stdout
- PyInstaller build pipeline to produce a standalone binary embedded in the Go app via `//go:embed`
- Python test suite in `python/tests/` using `unittest`

### Key Decisions
- **ILP over heuristics** — pure greedy or genetic algorithms would be faster but cannot guarantee mathematical optimality. ILP with GLPK provides a provably optimal solution given the constraints
- **stdin/stdout JSON protocol** — avoids filesystem temp files and works cleanly with Go's `exec.Command` piping
- **PyInstaller single-file binary** — eliminates Python runtime dependency on the end user's machine; the entire Python + PuLP + GLPK binding is bundled

### Challenges
- `normalize_stat_name()` is inherently fragile — DDO's XML uses inconsistent naming conventions (`spellpower` vs `spell power` vs `SpellPower`). Extensive alias tables were needed
- PyInstaller on macOS arm64 required explicit SDK version alignment; the solver binary needed to be re-signed after embedding
- GLPK path is hardcoded to `/opt/homebrew/bin/glpsol` — needs to be made configurable for portability

### Outcome
✅ Solver produces correct, optimal gearsets. Runtime for a standard 34-cap solve: ~30–90 seconds depending on item pool size and constraint complexity.

---

## Phase 4 — Svelte UI Implementation

### What Was Built
- **Full tab-based UI** in Svelte:
  - **Auto Solver tab** (`JobConfigurationForm.svelte`): all config fields, stat priority management, Run Optimization button
  - **Gearset Editor tab** (`GearsetEditor.svelte`): per-slot item dropdowns, alternative items panel
  - **Summary tab** (`Summary.svelte`): realized stats, active set bonuses, all effects grouped by stat
- **Wails bindings** auto-generated from Go method signatures, providing type-safe TypeScript interfaces
- **Glassmorphism design system** — translucent panels with backdrop blur, dark mode palette, smooth hover transitions
- **`configStore` / `resultStore`** Svelte writables for reactive state management across all tabs
- Status console polling `GetLogs()` every 500ms to surface Go-side log messages

### Key Decisions
- **Svelte stores** over prop drilling — since multiple tabs share state (config, result), a central store is far cleaner than event buses or prop chains
- **Wails `generate module`** as the source of TypeScript types — rather than manually maintaining `.ts` interfaces for Go structs, we rely entirely on auto-generation

### Challenges
- Wails generates TypeScript models that don't perfectly handle Go `map[string]interface{}` — required explicit casting in several places
- A11y warnings from Svelte's linter (label associations, click handlers on divs) were surfaced in builds but treated as non-blocking

### Outcome
✅ Full interactive UI working end-to-end. Solver results populate all three result tabs correctly.

---

## Phase 5 — Auto Solver Enhancements

### What Was Built
- **Alternative items per slot** — after the primary solve, the system runs additional constrained solves to find the 2nd, 3rd-best alternatives for each slot, allowing the user to swap in alternatives in the Gearset Editor
- **Expansion pack exclusion UI** — toggle list of all expansion packs (loaded from `expansions.json`)
- **"Update External Sources" button** — triggers `git pull` on DDOBuilderV2 + hot-reloads all caches in Go without restarting the app
- Improved solver output: `allEffects` map added to `ResultPayload` to drive the detailed Summary breakdown

### Key Decisions
- **`solve_for_alternatives()` as a separate ILP pass** — rather than enumerating all feasible solutions (which is NP-hard), we run `n` additional solves with the target slot's best item forbidden each time. This gives "near-optimal" alternatives efficiently
- **Hot-reload cache** — using Go's `sync.Once` pattern replaced with explicit re-initialization to support UpdateExternalSources without process restart

### Challenges
- Running 14 slots × 3 alternatives = 42 additional ILP solves made the full alternative-generation pass prohibitively slow. Capped at top 3 alternatives per slot and only on-demand (when user clicks a slot in the editor)

### Outcome
✅ Solver enhancements working. Alternative items display correctly in the editor's right panel.

---

## Phase 6 — Sentient Gear Builder (Augments & Filigrees)

### What Was Built

#### Backend
- `internal/services/parser.go` extended to parse `Augments/*.augment` and `FiligreeSets/*.filigree` XML
- Go startup now builds `augmentsCache` and `filigreesCache` in parallel with `itemsCache`
- `OptimizationPayload` extended with `pre_filled_augments`, `pre_filled_filigrees`, `calculate_only`, `gearset_name` fields
- `app.go` exposes `GetAugments(color)` and `GetFiligrees()` for UI dropdowns

#### Python Solver
- `parse_augments()` and `parse_filigrees()` functions added to `optimizer.py`
- **Augment locking**: pre-filled augments set `y[(aug_idx, item_idx, color)] = 1` in the ILP — solver treats them as fixed and builds around them
- **Filigree locking**: pre-filled filigrees set `fw[idx] = 1` or `fm[idx] = 1` as appropriate
- **Filigree stacking rules enforced**:
  - Same `base_name` filigree: at most 1 per weapon, at most 1 per artifact (separate constraints)
  - Same filigree can appear once in weapon AND once in artifact (cross-item stacking allowed)
- **`calculate_only` mode**: solver locks down to only the pre-equipped slots and computes effects without re-optimizing
- Filigree output restructured from flat list to `{"weapon": [...], "artifact": [...]}` map

#### Frontend
- **New Filigrees tab** (`FiligreeEditor.svelte`):
  - 10-slot weapon filigree grid
  - 1–5 slot artifact grid (driven by `minor_artifact_filigree_slots` config field)
  - Real-time search + set-name filter dropdown
  - AUTO badge for solver-recommended slots
- **Gearset Editor**: augment slot dropdowns per item slot, color-filtered augment picker
- **Summary tab**: Load/Save `.ddogearset` files with full config + result round-trip
- **Calculate Stats button** replaces the old Generate button — triggers `calculate_only` solve, instantly populating Summary without re-running full optimization
- **`.ddogearset` file format** (v1.2): JSON with `version`, `gearset_name`, `saved_at`, `config`, `result` — auto-timestamped filenames prevent overwrites
- Filigree editor decoupled from item identification (was previously misidentifying weapon vs artifact by trying to detect item properties from the equipped gearset)

### Key Decisions
- **Separate Filigrees window** (not embedded in Gearset Editor) — keeps the editor focused on items/augments; filigrees are a distinct concern
- **`calculate_only` as an ILP constraint, not a bypass** — we still run the solver but with extra equality constraints, ensuring the result is consistent with the ILP formulation and all set bonus calculations remain correct
- **Decoupled filigree slot count from item detection** — instead of trying to identify which equipped item is the "artifact" (which caused misidentification bugs), the Filigree tab uses the `minor_artifact_filigree_slots` config parameter directly
- **Timestamped filenames** — guarantees no file is ever silently overwritten; each Save produces a unique filename

### Challenges
- Filigree XML `base_name` field is not directly present in the DDOBuilder XML; it had to be inferred by stripping the suffix pattern from filigree names (e.g., `"Spines of the Manticore/The Wreath of Flame +6 Ranged Power"` → base `"Spines of the Manticore"`)
- The `calculate_only` mode required careful ILP constraint design: naively adding equality constraints to a pre-existing model can make it infeasible if the pre-filled state isn't consistent with the original constraint set
- PyInstaller macOS arm64 re-signing was needed after every recompile; automated in the build workflow

### Outcome
✅ Phase 6 complete. The app is now a full Sentient Gear Builder: users can manually configure every augment and filigree slot, have the solver optimize around those choices, and save/restore the full configuration as a portable `.ddogearset` file.

---

## Summary Table

| Phase | Key Deliverable | Lines of Code (approx) | Test Coverage |
|---|---|---|---|
| 1 | Wails + Svelte scaffolding | ~400 | — |
| 2 | XML parsing + enrichment | ~800 Go | Unit tests pass |
| 3 | Python ILP solver | ~600 Python | Unit tests pass |
| 4 | Full Svelte UI | ~1,500 Svelte | Manual |
| 5 | Alternatives + hot-reload | ~400 Go+Python | Manual |
| 6 | Sentient Gear Builder | ~1,200 Go+Python+Svelte | Manual + ILP validation |
