# Technical Plan — Phase 12: The Harness (Sprite-Based Gear Board)

**Supersedes:** `docs/inventory_sprite_wails_spec.md` (kept as the design intent; this
document is the implementable version — see §1.2 for where the two disagree and why).
**Branch:** `feature/harness-board`
**Scope:** `frontend/src/lib/components/domain/` (new `HarnessBoard.svelte`,
`HarnessSlot.svelte`, `SlotPicker.svelte`), `frontend/src/lib/harness.ts` (new),
`frontend/src/lib/store.ts`, `frontend/src/App.svelte`,
`frontend/src/lib/components/domain/GearsetEditor.svelte`.
**Explicitly out of scope:** Go, Python, `app.db`, the solver, and the
`.ddogearset` format. Phase 12 adds no backend surface (§1.2 D).

---

## 1. What this phase delivers

A second view of the *same* gearset, rendered as the DDO character-sheet harness
art: a 3-wide board of framed equipment tiles that show colour when a slot is
filled and desaturated grey when it is empty. It sits in the centre column
(`App.svelte`'s 45% zone) alongside the existing Vellum Summary, switched by a
tab strip, exactly as the source spec asks.

The board is a **second presentation of `$resultStore.gearSet` /
`$configStore.pre_equipped`** — not a second copy of the state. Everything the
left-hand `GearsetEditor` socket list can do (pick, clear, find alternatives) the
board does, by driving the same stores through the same picker.

### 1.1 Invariants

| ID | Invariant |
|---|---|
| **INV-1** | One source of truth. The board reads and writes `$resultStore.gearSet` and `$configStore.pre_equipped` only. No new store holds "what is equipped". |
| **INV-2** | The socket list and the board are always consistent, with no sync step: changing a slot in either is visible in the other on the next reactive tick. |
| **INV-3** | No slot is reachable *only* from the board. Every action remains available in `GearsetEditor`, so the board is additive and can be hidden without loss of function. |
| **INV-4** | The board never fabricates a slot the solver doesn't know. Its slot ids are exactly the 14 entries of `baseSlots` in `GearsetEditor.svelte:13`. |
| **INV-5** | No dynamic Tailwind class strings. Sprite geometry travels as inline `style`, never as `class="w-[{x}px]"` (§1.2 B). |

### 1.2 Corrections to `inventory_sprite_wails_spec.md`

The source spec was written before the assets were measured and before the
current dashboard layout existed. Five things in it do not work as written:

**A. The 120px slot size is wrong.** Measured from the real assets: both
`harness.jpg` and `harness-disabled.jpg` are **412 × 731**. Tiles are **96 × 98**
at column origins x = 32, 158, 285 and row origins y = 54, 185, 315, 446, 603.
(Derived by brightness-profiling the frame bands and confirmed by overlaying the
computed rects on the sprite — all 15 land on their frames.) Note the weapons row
is *not* on the equipment row pitch: rows 1–4 step ~130.7px, row 5 sits 157px
below row 4 because the "WEAPONS" title band intervenes. A uniform grid formula
will miss it; use the literal origin table in §2.1.

**B. `class="w-[{SLOT_SIZE}px]"` does not compile.** Tailwind's JIT scans source
text; `w-[{SLOT_SIZE}px]` is a runtime template string and matches no candidate,
so the class silently never exists. Same for interpolating `bg-[position:...]`.
All sprite geometry goes in `style`.

**C. `backgroundImage` config with `url('/src/assets/…')` is fragile.** Vite
resolves that literal at CSS-build time and it bypasses the asset-hashing the
rest of this frontend uses (`App.svelte:15` imports `logo.jpg` as a module).
Import the sprites as modules and set `background-image` inline.

**D. The Go `GetInventoryState` / `ToggleEquip` API must not be built.** It is a
second source of truth for equipped state, parallel to `pre_equipped`, with no
way to stay in sync with it — and `App` already carries a `ctx` field of a
different type. Building it would create exactly the class of bug 0.5.3 was spent
fixing. The board binds to the existing stores; Phase 12 adds no Wails binding.

**E. Fifteen independent sprite viewports is more paint than needed, and loses
the board.** Rendering only tiles discards the leather frame, the border
ornament, and the "EQUIPMENT"/"WEAPONS" titles that live *between* the tiles.
Use the hybrid in §2.2 instead: one full-size `harness-disabled.jpg` as the board
background, with a colour tile painted over it only for filled slots.

One thing the spec gets right and should be kept: the third tile of the weapons
row is not a gear slot — it is the toggle back to the Vellum Summary (§2.1,
`__summary`).

---

## 2. Design

### 2.1 The slot map (`frontend/src/lib/harness.ts`)

The single table everything else derives from. Sprite-pixel truth in, CSS
percentages out, so the board scales to whatever width the centre column gives
it without a resize listener.

```ts
export const SHEET_W = 412, SHEET_H = 731, TILE_W = 96, TILE_H = 98;

// Sprite-pixel origins, measured from the assets (docs/PHASE12_PLAN.md §1.2 A).
const COL_X = [32, 158, 285];
const ROW_Y = [54, 185, 315, 446, 603];

// Reading order, top-left to bottom-right. `null` = decorative/non-gear tile.
export const HARNESS_LAYOUT: (string | null)[][] = [
  ['Goggles',  'Helmet',  'Necklace'],
  ['Cloak',    'Armor',   'Trinket' ],
  ['Bracers',  'Belt',    'Gloves'  ],
  ['Ring_1',   'Boots',   'Ring_2'  ],
  ['Weapon1',  'Weapon2', '__summary'],
];
```

The 14 gear ids are exactly `GearsetEditor`'s `baseSlots` (INV-4). A unit-free
assertion to that effect belongs in the module (§5, WP0).

**Geometry, per tile at (col, row):**

| Property | Formula | Values |
|---|---|---|
| `left` | `COL_X[col] / 412` | 7.767%, 38.350%, 69.175% |
| `top` | `ROW_Y[row] / 731` | 7.387%, 25.308%, 43.092%, 61.012%, 82.489% |
| `width` | `96 / 412` | 23.301% |
| `height` | `98 / 731` | 13.406% |
| `background-size` | `412/96`, `731/98` | `429.1667% 745.9184%` |
| `background-position` | `x/(412-96)`, `y/(731-98)` | x: 10.1266% / 50% / 90.1899%<br>y: 8.5308% / 29.2259% / 49.7630% / 70.4581% / 95.2607% |

The `background-position` denominators are `sheet − tile`, not `sheet`: that is
how percentage background-position is defined (`pct × (box − image)`), and it is
what makes the colour tile stay registered with the board at *any* rendered
scale. Precompute all six numbers in `harness.ts` as strings; no component does
arithmetic.

### 2.2 Rendering model

```
<div class="harness-board">              ← aspect-ratio 412/731,
    background-image: harness-disabled.jpg, background-size: 100% 100%
  <button class="harness-slot" …>        ← absolutely positioned, one per tile
      background-image: harness.jpg      ← ONLY when the slot is filled
      background-size / -position from §2.1
  </button>  × 15
</div>
```

- **Empty slot**: the button paints nothing; the greyed board shows through.
- **Filled slot**: the button paints the same tile from the colour sheet, pixel-
  registered on top of the grey one. No layout property changes, so this is a
  localised repaint — the performance claim in the source spec §5 survives.
- **Hover/focus/selected**: a `ring` / inset shadow on the button, using the
  existing `shadow-socket` and `ring-gold` tokens from `tailwind.config.js`.

**Sizing.** The board's natural aspect is 412:731 — tall and narrow, while the
centre column is wide and short. It must be height-constrained, not width-
constrained: `max-height: 100%; aspect-ratio: 412/731; margin-inline: auto`, in a
`min-h-0` flex parent. Getting this backwards produces a board that overflows the
column and pushes the app into a scrollbar; check it at a 1280×800 window (WP1
acceptance).

### 2.3 Where shared picker state lives

`GearsetEditor` currently owns `selectedSlot` / `availableItems` /
`selectedItemDetails` / `searchQuery` as component-local state, and renders the
picker modal itself (`GearsetEditor.svelte:562-620`). The board needs the same
modal from a different subtree.

Extract, don't duplicate: move the modal and its fetch/select/clear logic into
`SlotPicker.svelte`, mounted **once** in `App.svelte`, driven by one new store:

```ts
// store.ts
export const pickerSlot = writable<string | null>(null);       // open the picker
export const alternativesSlot = writable<string | null>(null); // open the drawer
```

Both `GearsetEditor` and `HarnessBoard` then just set `$pickerSlot = slot`. This
is a *move* of existing working code, not a rewrite — the `selectItem` /
`clearSlot` / `assignMinorArtifact` bodies transfer verbatim, with
`selectedSlot` becoming `$pickerSlot`.

Two known traps when doing this move:

- The 0.5.3 reactivity bug. `SlotPicker` will be permanently mounted, so it never
  remounts to pick up fresh store values. Anything derived from `$configStore` /
  `$resultStore` must be a `$:` statement that *names those stores in the
  statement itself* — never a helper function called from an `{#each}` `{@const}`.
  See the 0.5.3 CHANGELOG entry for exactly how that fails.
- `slot` is a reserved Svelte attribute name. Name the prop/store `pickerSlot` /
  `targetSlot`, as `SlotAlternatives.svelte:21` already had to.

---

## 3. Work packages

Ordered; each lands on its own and leaves the app working. Sizes are relative
effort, not hours.

### WP0 — Slot map module (S)
**Files:** new `frontend/src/lib/harness.ts`.
Build the table and precomputed geometry from §2.1. Export `HARNESS_LAYOUT`,
`HARNESS_TILES` (flat array of `{ slot, label, style }` where `style` is the
ready-to-use inline string), and `HARNESS_GEAR_SLOTS`.
**Acceptance:** `HARNESS_GEAR_SLOTS` sorted equals `baseSlots` sorted; `npm run
check` clean. No component imports yet.

### WP1 — Board shell + centre-column tab (M)
**Files:** new `HarnessBoard.svelte`; `App.svelte`.
Static board: grey sheet background, correct aspect and centring, 15 tiles
rendered as focusable buttons with `aria-label` but no click behaviour yet. Add a
`'summary' | 'harness'` tab strip above the centre column using the existing
`belt-stud` / `belt-stud-active` classes, matching `GearsetEditor`'s own Gear /
Filigrees strip (`GearsetEditor.svelte:434-445`). Both views stay mounted and
toggle with `class:hidden`, per the convention `App.svelte:110-112` established —
switching must not drop the Summary's scroll position.
**Acceptance:** at 1280×800 the whole board is visible inside the column with no
page scrollbar; every tile's outline lands on its painted frame (compare against
the sprite); tab switch preserves Summary scroll.

### WP2 — Equipped state (S)
**Files:** new `HarnessSlot.svelte`; `HarnessBoard.svelte`.
Paint the colour sheet on a tile when `$resultStore.gearSet[slot]` is set. The
`__summary` tile always paints colour (it is decorative) and switches the tab
back to Summary on click.
**Acceptance:** equipping an item in the left socket list colours the matching
tile without a reload; `Clear` greys all fourteen; loading a saved build from
`app.db` colours exactly the slots the socket list shows filled.

### WP3 — Picker extraction (M — the riskiest package)
**Files:** new `SlotPicker.svelte`; `GearsetEditor.svelte`; `store.ts`;
`App.svelte`.
Perform the move described in §2.3, wiring `GearsetEditor` to the store-driven
picker. **Behaviour must not change in this package** — no board wiring yet, so
any regression is unambiguously attributable to the move. Move
`alternativesSlot` to the store in the same package (same shape, trivial).
**Acceptance:** the pre-WP3 `GearsetEditor` flows all still work — pick item,
minor-artifact toggle and its cross-slot clearing, clear slot, alternatives
drawer, Escape/backdrop close, modal not opening on an empty slot that was just
cleared (`GearsetEditor.svelte:390`). Verified by driving the running app, not by
inspection: this is exactly the kind of change the test suite does not cover.

### WP4 — Board interaction (S)
**Files:** `HarnessSlot.svelte`, `HarnessBoard.svelte`.
Click an empty tile → `$pickerSlot = slot` (search list). Click a filled tile →
`$pickerSlot = slot` with the item detail shown. Keyboard: tiles are real
`<button>`s in DOM reading order, so Tab/Enter work for free; add `Delete` /
`Backspace` on a focused filled tile to clear it.
**Acceptance:** every one of the 14 slots is pickable and clearable from the
board; state changes are immediately visible in the left socket list (INV-2).

### WP5 — Readability layer (M)
**Files:** `HarnessSlot.svelte`.
Sprite art alone does not say *which* item is in a slot — this is the difference
between a decoration and a usable view.
- Name plate: truncated item name in a translucent strip across the bottom of a
  filled tile, coloured by `rarityClass()` (lift that helper out of
  `GearsetEditor.svelte:405` into `harness.ts` so both use one copy).
- `title` tooltip with the full name and ML.
- Trove ownership dot, reusing `ownershipOf()` — same lift, same reason.
- A small `⚙` affordance on hover opening the alternatives drawer.
**Acceptance:** with a full gearset loaded, every slot's item is identifiable
from the board alone; ownership dots match the socket list's after `Check
Inventory`.

### WP6 — Style-locked weapon slots (S)
**Files:** `HarnessSlot.svelte`, `harness.ts`.
`Weapon2` is meaningless under Two Handed Fighting / Bow / and the `w2_list ==
['none']` branches of `solver.resolve_weapon_lists` (`python/solver.py:224`).
Render such a slot with a lock affordance and refuse the picker, mirroring the
Phase 11 §5 Step 3.1 intent. **Derive the rule from `weapon_style` +
`offhand_style` + `swashbuckling` + `build_type` in one exported predicate**, and
comment it as a mirror of `resolve_weapon_lists` — a second, drifting copy of
that table is the failure mode to avoid here (§4).
**Acceptance:** switching `weapon_style` to Two Handed Fighting locks Weapon2 on
the board; switching back unlocks it. An *already-equipped* Weapon2 is still
shown and still clearable — locking hides the picker, never the user's data.

### WP7 — Asset hygiene, docs, release (S)
- Delete `frontend/src/assets/images/harness/harness.png` (412 × 1024, ~880 KB,
  an untrimmed earlier export; nothing references it). The two JPEGs (~600 KB
  together) ship inside the binary and are load-bearing.
- `CHANGELOG.md` under a new `[0.6.0]` heading; `docs/USAGE.md` gets the tab.
- Mark `docs/inventory_sprite_wails_spec.md` as superseded by this document.

**Dependencies:** WP0 → WP1 → WP2; WP3 independent of WP1/WP2 and can land first
or in parallel; WP4 needs WP2 + WP3; WP5/WP6 need WP4; WP7 last.

---

## 4. Risks

| Risk | Mitigation |
|---|---|
| WP3 silently breaks a `GearsetEditor` flow — there is no frontend test runner in this repo (`frontend/package.json` has no vitest), so nothing catches it automatically. | Land WP3 alone, behaviour-frozen, and walk the acceptance list in the running app before building on it. |
| WP6's lock table drifts from `resolve_weapon_lists`, so the UI locks a slot the solver would happily fill (or vice versa). | One predicate, one comment pointing at `python/solver.py:224`, and a note in `docs/ENGINEERING.md`. Treat any future weapon-style change as touching both. |
| Sprite tiles look misregistered on fractional-scale rendering (HiDPI, odd column widths). | Percentage geometry (§2.1) is scale-free by construction; verify at 1280×800 and at a deliberately narrow window before calling WP1 done. |
| The board is pretty but slower to use than the socket list. | INV-3 keeps the socket list intact and primary. The board is a view the user opts into. |

---

## 5. Review of `PHASE11_PLAN.md`

Read against the code on `main` before writing the above, because Phase 12 (WP6)
depends on Phase 11's weapon-style rules. Most of Phase 11 is **already shipped**;
what remains is small and specific.

**Already implemented — the plan describes existing behaviour:**

- §2.1/§2.2 strict level + pack filtering with a pre-equipped exemption:
  `parse_items` (`python/optimizer.py:271`) takes `max_ml`, `excluded_packs` and
  `pre_equipped_names`, and every pool filter — pack (`:364`), owned-names
  (`:374`), armour and weapon-list narrowing (`:333-352`) — is bypassed for
  pre-equipped items, restoring `original_slots` rather than dropping the item.
  INV-1, INV-2 and EC-4 hold today.
- §3.1's weapon-style matrix exists as `solver.resolve_weapon_lists`
  (`python/solver.py:224`), whose docstring already states it was extracted "so
  the alternatives path uses exactly the same pool the main solve would". INV-3
  is structurally satisfied; there is nothing to add.
- §4 blank/parameter-only saving: `SaveGearset` (`app.go:1291`) has no
  empty-gearset gate. Worth one spot-check of the frontend save button for a
  local guard, but the backend already allows it.

**Genuinely outstanding:**

1. **§5 Step 3.3 limit indicators.** `SlotAlternatives.svelte` has no minor-
   artifact or raid-limit handling at all — no red border, no gold border. This
   is the largest real gap in Phase 11 and is pure frontend.
2. **§5 Step 2.2 / EC-1.** `GetSlotAlternatives` (`app.go:1107`) clamps `Count`
   and forwards; it does not reject a `Weapon2` request under a locked style.
   Note this overlaps WP6 — decide once whether the guard lives in Go, in the UI,
   or both, and do not build the UI lock and the backend rejection from two
   different tables.

**One correction the plan needs before anyone implements it:** §3.1's table is a
*less accurate* restatement of `resolve_weapon_lists`, and implementing it
verbatim would regress fixed behaviour. It lists "Scepters" as a valid type for
Dual Caster and Stick and Orb; `solver.py:263-267` documents that scepter "isn't
a real DDO weapon type at all and never matched anything", and that the narrow
hardcoded caster list was replaced by the authoritative `ONE_HANDED_WEAPON_TYPES`
group. The plan's Sword-and-Board row is likewise narrower than the code's
`shields` list. **Recommendation:** strike §3.1's table and replace it with a
pointer to `resolve_weapon_lists` as the single definition.

**Suggested disposition:** Phase 11 has roughly one frontend session of work
left. Fold items 1 and 2 above into Phase 12 as a WP6-adjacent package (both are
alternatives-drawer/weapon-lock work in the same files WP5/WP6 touch), retire
`PHASE11_PLAN.md`, and record in `docs/ENGINEERING.md` that §§2–4 shipped ahead
of the plan being written.
