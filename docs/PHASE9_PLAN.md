# Phase 9 Plan — Rich Slot Data, Read-Only Calculator, Filigree Accuracy, Responsive UI

This document scopes the major changes requested next. It's split into independently
shippable phases so each can be implemented, tested, and reviewed on its own.

## Phase 9.0 — Quick fixes (done in this pass)
- **Rare filigree bug (item 4)**: `parse_filigrees()` in `python/optimizer.py` was treating
  every `<Effect>` node under a `<Filigree>` as an independent stacking buff, including
  `<Rare/>`-tagged effects. In the DDOBuilderV2 data, "Rare" is an *alternate/upgraded*
  version of the same filigree, not an additional bonus stacked on top of the base one.
  This is the direct cause of the reported bug where a single equipped filigree (e.g.
  "Wildhunter: +3 Ranged Power") showed up contributing both its base value (3.0) and its
  Rare value (2.0) as if both applied simultaneously. **Fix**: skip any `<Effect>` node
  that contains a `<Rare/>` tag; only the base effect is ever parsed into `buffs`.
  - Note: the *other* duplicate pattern the user saw (identical value appearing twice in a
    row, e.g. two `6.0 Stacking (...)` entries) is **not** a bug — it's the legitimate
    "same filigree equipped on both weapon and minor artifact" stacking rule documented in
    `docs/USAGE.md`. `create_model()` intentionally creates one `sources` entry per filigree
    per slot (`fw[idx]`/`fm[idx]`), and `all_effects_out` only includes a source whose
    variable actually solved to 1, so a double entry there means the filigree really is
    equipped twice.
- **Responsive base font size (item 6)**: `frontend/src/style.css` now sets
  `html { font-size: clamp(14px, 1rem + 0.3vw, 18px); }` — scales with viewport width,
  floor 14px, ceiling 18px. All existing `rem`-based Tailwind utilities scale automatically.

## Phase 9.1 — Ordered, weighted stat priorities (item 5)
**Problem**: `stat_priorities` is currently `map[string]int` end-to-end (Go struct field,
JSON, Python dict). Go's `encoding/json` marshals maps in **sorted key order**, so any
"order entered" information from the UI is already lost by the time Python sees it. To
implement order-sensitive weighting we must change the wire format to an **ordered list**.

**Design**:
- Contract change: `stat_priorities` becomes an ordered array of
  `{ "stat": string, "value": int }` (or reuse the existing bracket-cap suffix convention,
  e.g. `"stat": "SpellPower[200]"`) instead of a map.
  - `app.go`: `StatPriorities []StatPriorityEntry` where
    `type StatPriorityEntry struct { Stat string; Value int }`.
  - `frontend/src/lib/store.ts`: `statPriorities: { stat: string; value: number }[]`,
    built by push order as the user adds priorities in `JobConfigurationForm.svelte`
    (already an ordered UI list — just stop collapsing it into an object).
  - `python/optimizer.py` / `solver.py`: accept a list of `(stat, value)` pairs instead of
    `dict.items()`; `create_model()`'s `WEIGHTS`/`CAPS` construction loop changes from
    `for stat_name, weight_val in priorities.items()` to iterating the ordered list while
    preserving index for the allocation rule below.
- **Allocation rule** (applies to which stat(s) filigree selection is biased toward):
  1. Exactly one priority has value `100` → all filigree-selection weight goes to that stat.
  2. More than one priority has value `100` → distribute weight across the `100`s in
     entry order with front-loaded bias: 2 stats → 60/40, 3 stats → ~47/33/20-style
     decaying split (exact curve TBD — proposed: geometric decay `wᵢ = 0.6 * 0.4^(i-1)`,
     renormalized to sum to 100).
  3. No `100`s present → prorate every listed stat directly by its value as a percentage
     of the sum of all listed values (current de facto behavior, just made explicit).
  - This allocation only reweights the **filigree-selection** objective terms (i.e. an
    additional multiplier applied to filigree `buffs` when building `sources`/objective
    terms), not the item/augment selection weighting, which continues to use the raw
    per-stat `WEIGHTS` values as today.
- **UI**: Surface the resulting allocation as muted help text under the priority list in
  `JobConfigurationForm.svelte` (e.g. "Filigree bias: 60% Ranged Power, 40% Doubleshot"),
  recomputed live as the user edits priorities.

**Open question for user confirmation**: the exact decay curve for 3+ simultaneous `100`s,
and whether the allocation rule should also influence non-filigree gear selection
eventually (out of scope for now per the request wording, which says "when selecting which
filigree to use").

## Phase 9.2 — Rich per-slot solver output (items 1–3)
**Goal**: the solver becomes the single source of truth for every piece of slot detail;
the Go calculator layer becomes a **read-only** consumer/relay of that data (no
recomputation), and the Summary screen renders directly from the same structure so every
effect can be traced to "this slot, this item, this augment/filigree/set bonus."

**New solver output shape** (replaces the current flat `gearSet: map[string]string` +
side-channel `filigrees`/`activeSets`/`allEffects` maps with one authoritative structure):
```jsonc
"slots": {
  "Weapon1": {
    "location": "Weapon1",
    "item": {
      "name": "...", "ml": 30, "wiki_url": "...", "pack": "...", "is_raid": false,
      "slots_available": ["Red", "Blue"], "minor": false
      // full enriched Item detail (already produced by internal/services/enrichment.go)
    },
    "augments": [ { "color": "Red", "name": "...", "buffs": [...] } ],
    "filigrees": [ { "name": "...", "buffs": [...] } ],   // weapon-slotted filigrees, if applicable
    "set_bonus_contributions": [ { "set": "...", "pieces": 4, "buffs": [...] } ]
  },
  ...
}
```
- Per item 1(e): the solver already has full item dicts in `items[i]`; it does **not** need
  to omit the item and have the frontend re-derive it — `items[i]` already carries every
  field `enrichment.go` produces (they're parsed from the same enriched JSON). We keep
  the full item embedded directly in each slot rather than a name-only reference, to avoid
  a second read-only lookup layer duplicating data the solver already has in memory.
- `run_optimization()`'s existing per-source tracking (`sources_tracking`, added in the
  previous session) already has everything needed to build `set_bonus_contributions` and
  per-slot `buffs` — this phase is mostly a **reshaping** of already-tracked data into a
  per-slot structure, not new tracking logic.
- Go (`app.go`): `ResultPayload.GearSet` (and the separate `Filigrees`/`ActiveSets` fields)
  are replaced by a single `Slots map[string]SlotDetail` field. `RunOptimization` continues
  to just relay solver JSON unchanged (it already does today — no Go-side recomputation
  exists to remove here, confirming "calculator is already read-only" is mostly true on the
  Go side; the read-only concern is really about the **frontend** `GearsetEditor.svelte`'s
  local `calculateGearSet()`/stat recompute path, addressed next).
- Frontend (`GearsetEditor.svelte`, item 2): stop locally recomputing realized stats from
  `pre_equipped`/`configStore`. Instead, every "Calculate Stats" action calls
  `calculate_only` solver mode (already exists) and renders **only** what comes back in
  `slots`/`realizedStats`/`allEffects` — this also directly fixes the previously-documented
  destructive-clear bug, since the fix forces `pre_equipped` to be sourced from
  `resultStore.gearSet`/`slots` right before the call rather than relying on manually-typed
  state.
- Frontend (`Summary.svelte`, item 3): replace `locateSource()`'s current
  name-string-matching heuristic (added last session to patch "Location unavailable") with
  a direct lookup into `resultStore.slots[slot]` — exact, no parsing required, and
  effect descriptions can state slot + item + augment/filigree/set name precisely.

**Migration note**: this changes the `ResultPayload`/`OptimizationPayload` JSON contract in
three places at once (Go struct, Python emit, TS types) — must be done as one atomic change
per the project's own convention (see `AGENTS`/README: "changing field names/types requires
updating all three").

## Sequencing
1. ✅ 9.0 quick fixes — rare filigree fix, responsive font size.
2. ✅ 9.1 ordered priorities + filigree bias — `OptimizationPayload.StatPriorities` is now an
   ordered `[]StatPriorityEntry` (Go) / `{stat, value}[]` (TS) / list of tuples (Python);
   `compute_priority_bias()` implements the geometric-decay rule (single 100 → all weight;
   multiple 100s → renormalized geometric decay, e.g. 3-way ≈ 51/31/18; no 100s → prorate by
   value), applied as a separate ILP objective term (`FILIGREE_BIAS_SCALE`) that only
   influences *which* filigree is picked, never the displayed buff values.
3. ✅ 9.2 rich per-slot contract — implemented as documented above. Final shape actually
   emitted by `run_optimization()` (`rich_output["slots"]`) matches the sketch in this doc:
   each slot has `location`, `item` (full enriched item dict, not just a name), `augments`,
   `filigrees` (attached to the equipped Weapon1/Weapon2 for weapon filigrees, or to the
   equipped item with `minor == True` for artifact filigrees — filigrees are not literally
   per-slot data per `docs/USAGE.md`), and `set_bonus_contributions`. `app.go`'s
   `ResultPayload` gained `Slots map[string]interface{}` (additive — `GearSet` was kept
   alongside it rather than removed, since other call sites still rely on it) and
   `frontend/wailsjs/go/models.ts` mirrors it as `slots?: Record<string, any>`.
   `frontend/src/lib/store.ts` exports `hydrateConfigFromSlots(config, slots)`, called by
   both `GearsetEditor.svelte`'s `calculateGearSet()` and `Summary.svelte`'s
   `calculateStats()` immediately before any `calculate_only` `RunOptimization` call — this
   is what actually fixes the destructive-clear bug (see `docs/ENGINEERING.md` → Known
   Issues, now marked Fixed). `Summary.svelte`'s `locateSource()` now does an exact lookup
   into `resultStore.slots` first, falling back to the old name-heuristic only for older
   saved files that predate the `slots` field.

All phases verified: `py_compile`/`pytest python/tests/` (4/4 passed), `go build ./...` /
`go vet ./...` clean, `npm run check` in `frontend/` at the same 7 pre-existing baseline
errors (no new errors introduced), `python/dist/solver` rebuilt via PyInstaller after each
phase, and live smoke tests against `gearsets/test_RangedDualCrossbow_20260804040648.ddogearset`
— including a `calculate_only` run with a config hydrated from a prior solve's `slots` output,
confirming all 14 equipped slots are preserved (not cleared) and realized stats compute
correctly.
