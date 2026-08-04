# Technical Specification — Tiered Solver Frontend

**Branch:** `feature/tiered-priority-solver`
**Scope:** `frontend/src/lib/components/domain/JobConfigurationForm.svelte` (split into several components), new `frontend/src/lib/components/domain/StatPriorityEditor.svelte`, `StatPicker.svelte`, `StatSetPicker.svelte`, `TierReport.svelte`, new `frontend/src/lib/components/ui/Accordion.svelte`, new `frontend/src/lib/data/statTaxonomy.ts`, new Go `GetStatSets` RPC + embedded default + runtime override file, `frontend/src/lib/store.ts`, `frontend/src/lib/components/domain/GearsetEditor.svelte` (the `calculate_only` mutation fix only)
**Depends on:** `docs/PHASE10_PLAN.md` (all 15 sections, including the weapon-stat-priorities addendum) landing in Go/Python first, and `wails generate module` being re-run against the new Go structs before this frontend work starts. **Independent of** `docs/ITEM_DETAIL_SPEC.md` (no shared files, no contract dependency in either direction).
**Status:** Planning only — no implementation yet.

---

## 1. Overview and invariants

`JobConfigurationForm.svelte` (currently 472 lines, one flat component) is restructured into a set of focused components, the free-text-name + 1-100-slider stat priority UI is replaced by five spatial tier lanes matching Phase 10's `{stat, tier, cap}` model, a drill-down stat picker seeded from `docs/STAT_SHORTCUTS.md` replaces free-text entry, a curated "stat sets" preset system is added, and every large static UI block becomes a collapsible accordion section.

### 1.1 Non-negotiable invariants

| ID | Invariant |
|---|---|
| **INV-1** | A stat can exist in **at most one tier lane at a time** — enforced structurally by the UI (a chip physically lives in exactly one lane), not by pre-send validation. Phase 10 §2.6 rejects duplicate-stat-across-tiers as a hard server-side error; this frontend must make that payload shape unconstructable, not merely avoid triggering it in the happy path. |
| **INV-2** | Serialization flattens the five lanes in tier order (all tier-1 entries in lane order, then tier-2, …) into `[{stat, tier, cap?}]` — array order **is** intra-tier rank per Phase 10 §2.3/§3.6; there is no separate weight/value field anywhere in the new UI. |
| **INV-3** | `caster_spellpowers`/`caster_schools` fields remain on `OptimizationPayload` for backward-compatible deserialization of old `.ddogearset` files, but the UI never writes to them again — see §5. |
| **INV-4** | The `weapon base damage` composite stat and its two components (`weapon damage`, `base damage dice`) can never be selected together in the same priority list — enforced client-side, per `docs/PHASE10_PLAN.md` §15.3/EC-29. |
| **INV-5** | This spec ships **no earlier than** Phase 10's Go changes landing (specifically `MaxSearchTime`/`Mode` on `OptimizationPayload` and the tiered `StatPriorityEntry` shape) and a `wails generate module` re-run. Shipping ahead of that leaves the relabelled search-time slider promising a budget that's still silently dropped, and the tier-lane UI cannot type-check against the old flat wire shape. |

### 1.2 Confirmed decisions (do not re-litigate)

1. The caster spellpower/school checkbox grid is **removed outright**, folded into the general stat picker (§5).
2. Weapon combat properties (`weapon damage`, `base damage dice`, `critical multiplier`, `critical threat range`, `weapon base damage`) are real, selectable priority stats per `docs/PHASE10_PLAN.md` §15 — included in the taxonomy (§4) with the composite double-select block (§4.4).
3. Stat sets (§6) are **hand-edited only** (no in-app save/create UI in this pass) but must be **loaded at runtime**, not baked into the app binary at build time — see §6.2 for why this rules out the `expansions.json`/Vite-`public/` precedent and what replaces it.
4. This is spec'd as its own, second deliverable, separate from `docs/ITEM_DETAIL_SPEC.md`.

---

## 2. Component breakdown

`JobConfigurationForm.svelte` becomes a thin layout/orchestrator component. New/changed components:

| Component | Responsibility |
|---|---|
| `JobConfigurationForm.svelte` (existing, restructured) | Section layout, submit action, wiring child components to `configStore` |
| `StatPriorityEditor.svelte` (new) | The five tier lanes, chip rendering, reordering, cap editing, serialization to `configStore.stat_priorities` |
| `StatPicker.svelte` (new) | The "Add stat ▾" drill-down UI (category tree + search + custom-stat escape hatch), invoked per-lane by `StatPriorityEditor` |
| `StatSetPicker.svelte` (new) | Fetches and renders the stat-set preset list, click-to-add with conflict resolution (§6.4) |
| `TierReport.svelte` (new) | Post-solve display of `tierReport`/`tierScores`/`unmetTier4`/`unmatchedPriorities`/`degraded` (§7.2), lives in the results view (`Summary.svelte`), not in the form itself |
| `Accordion.svelte` (new, `$lib/components/ui/`) | Generic collapsible section wrapper, hand-rolled (§8) |

---

## 3. Tier lane UI (`StatPriorityEditor.svelte`)

### 3.1 Layout: five lanes, not a per-row tier dropdown

Five vertically-stacked drop-zone lanes, each independently rendering its own chip list. A tier dropdown-per-row was rejected because Phase 10 has two orthogonal dimensions (tier, and intra-tier rank via array order) and a flat list with a `<select>` per row renders only one of them visibly — the user would have to mentally reconstruct rank from a single global sequence. Lanes make both dimensions spatial: which lane = tier, position within the lane = rank. This also directly delivers INV-1: a chip cannot exist in two lanes at once because it is one DOM node with one parent.

### 3.2 Lane headers (exact copy, plain-English restatement of Phase 10's tier semantics)

| Lane | Header | Sub-label |
|---|---|---|
| 1 | **Must Maximize** | Solved first. Nothing below can reduce these. Filigrees only count here. |
| 2 | **Maximize Next** | Maximized without giving up any Tier 1. |
| 3 | **Maximize If Free** | Taken only when Tiers 1–2 are untouched. |
| 4 | **Get At Least Some** | Breadth first — one meaningful source per stat, then magnitude. |
| 5 | **Nice To Have** | Only when convenient. |

An empty lane renders as a thin dashed drop target with the caption "No solve stage runs for an empty tier" — this is a direct, accurate restatement of Phase 10 §4.1 (`T` = only the tiers that actually contain a stat).

### 3.3 Chip

Each chip shows: stat display label (from the taxonomy leaf, §4, or the raw string for a custom/legacy stat), an optional cap badge (`[cap]`, editable inline — click opens a small numeric input, `min=1`, integers only; entering `0` or a non-integer is rejected client-side with the message **"Cap must be a positive integer."**, matching Phase 10 §2.6's server-side wording exactly so the two never disagree), up/down reorder buttons (disabled at the lane's ends), a "move to tier ▾" menu (five options, current tier disabled/greyed), and a remove `×`.

### 3.4 Reordering: buttons committed, drag-and-drop is not built in this pass

Up/down-within-lane plus the "move to tier" menu is a direct generalization of the existing `moveStatPriority` (`JobConfigurationForm.svelte:71-78`), needs no new dependency, and is keyboard-accessible without extra work. True cross-lane drag-and-drop is not implemented in this pass — not because it's undesirable, but because Svelte 3 (the project's current version, confirmed via `package.json`) has no drag-and-drop library already in the dependency tree, and hand-rolling HTML5 drag events across five drop targets is meaningful standalone work disproportionate to what buttons already deliver. If a future pass adds it, it must not remove the button-based path (keyboard accessibility requirement).

### 3.5 The `weapon base damage` mutual-exclusion guard (INV-4)

`StatPriorityEditor` maintains a small constant:

```typescript
const WEAPON_DAMAGE_EXCLUSION_GROUP = ['weapon base damage', 'weapon damage', 'base damage dice'];
```

Before adding any stat from `StatPicker`, `StatSetPicker`, or the legacy-import path (§5.3), check: if the incoming stat is in `WEAPON_DAMAGE_EXCLUSION_GROUP` and any *other* member of that group already exists anywhere across all five lanes, **block the add** and show a toast: *"Weapon base damage already includes [component]. Remove it first, or add [component] instead of the composite."* (message adapted to whichever direction the conflict runs). This check runs in one place — a shared `canAddStat(stat: string): {ok: boolean, reason?: string}` helper — reused by all three entry points so the rule can't be bypassed via one of them.

### 3.6 Serialization

```typescript
function serializePriorities(lanes: Record<1|2|3|4|5, StatChip[]>): StatPriorityEntry[] {
    const out: StatPriorityEntry[] = [];
    for (const tier of [1, 2, 3, 4, 5] as const) {
        for (const chip of lanes[tier]) {
            out.push({ stat: chip.stat, tier, ...(chip.cap ? { cap: chip.cap } : {}) });
        }
    }
    return out;
}
```

Matches Phase 10 §2.3's wire shape exactly, satisfying INV-2. This becomes `configStore.stat_priorities`'s value on every mutation (reactive, not only at submit time — so `TierReport`/other consumers reading `configStore` mid-edit see current state).

### 3.7 Loading existing state (hydration on mount / on `.ddogearset` load)

Given `configStore.stat_priorities` (already in the new `{stat, tier, cap}` shape, since Phase 10 lands first per INV-5), group by `tier`, preserving array order within each group as the lane's chip order — this is the exact inverse of §3.6 and is lossless by construction (no rounding, no reconstruction heuristics needed, unlike the old flat-weight UI which had nothing analogous to reconstruct).

---

## 4. Stat taxonomy and picker (`StatPicker.svelte`, `$lib/data/statTaxonomy.ts`)

### 4.1 Static taxonomy — confirmed design, not backend-enumerated

The taxonomy is a static, hand-authored, type-checked TypeScript tree, **not** fetched from a new backend enumeration endpoint. The reasoning (from the architectural planning pass, restated because it's load-bearing): the stat names a user needs to pick from are not raw XML `<Type>` values — they are *inputs to* `python/optimizer.py`'s `normalize_stat_name` matcher (e.g. `"fire spellpower"` matches via the `'spell power' → 'spellpower'` rewrite plus a substring search, `optimizer.py:34-35`). A backend endpoint enumerating "distinct `<Type>` values actually present in the parsed pool" would return thousands of raw strings (`Combustion`, `MagicalEfficiency`, `Chilling 3`, `Human Bane 3`, …) that are accurate about the XML but not in the vocabulary the matcher expects — an "always accurate, always useless" tradeoff, not a real accuracy win.

**Mitigation for the real risk (a user picks a taxonomy leaf that matches zero sources in the actual data):** this is a **post-solve** concern, not a pre-solve one, and Phase 10 already emits exactly what's needed for it — `unmatchedPriorities` in the solver output (`docs/PHASE10_PLAN.md` §9). `TierReport.svelte` (§7.2) surfaces this list prominently after every solve, and `StatPriorityEditor` cross-references it against currently-placed chips to add a warning badge on the next render. No live "N sources found" badge is built into the picker itself in this pass (that would require porting `normalize_stat_name` to Go — exactly the duplication `docs/ITEM_DETAIL_SPEC.md` §2.1/INV-1 independently already rejected for a different reason; the same reasoning applies here).

### 4.2 File location and ownership

`frontend/src/lib/data/statTaxonomy.ts` — TypeScript, in `src/`, type-checked, tree-shaken. **Deliberately not** a `public/` JSON asset like `expansions.json` or the new `stat_sets.json` (§6) — this file is app vocabulary the developer owns and versions with the code, not user-editable content. State this distinction explicitly in the file's header comment so the asymmetry with `stat_sets.json` (which *is* meant to be user-edited) reads as intentional.

### 4.3 Shape

```typescript
export interface StatTaxonomyLeaf {
    label: string;      // display text, e.g. "Fire Spellpower"
    stat: string;        // exact wire string, e.g. "fire spellpower"
    note?: string;        // caveat text, e.g. "Undocumented in the data files — may match nothing."
}

export interface StatTaxonomyCategory {
    label: string;
    children: (StatTaxonomyCategory | StatTaxonomyLeaf)[];
}

export const STAT_TAXONOMY: StatTaxonomyCategory[] = [ /* see §4.5 */ ];
```

Three levels deep at most (category → sub-category → leaf), matching `docs/STAT_SHORTCUTS.md`'s own documented ceiling.

### 4.4 Weapon Properties branch (new, per Phase 10 §15)

```typescript
{
  label: "Weapon Properties",
  children: [
    { label: "Weapon Base Damage (recommended)", stat: "weapon base damage",
      note: "Combines [W] multiplier and base dice into one value. Do not also select Weapon Damage or Base Damage Dice." },
    { label: "Weapon Damage ([W])", stat: "weapon damage",
      note: "Advanced: use only if you specifically want to ignore base dice. Cannot be combined with Weapon Base Damage." },
    { label: "Base Damage Dice", stat: "base damage dice",
      note: "Advanced: expected value of the weapon's dice only, ignoring [W]. Cannot be combined with Weapon Base Damage." },
    { label: "Critical Multiplier", stat: "critical multiplier" },
    { label: "Critical Threat Range", stat: "critical threat range" }
  ]
}
```

`StatPicker` visually marks `weapon damage`/`base damage dice` as "Advanced" (e.g. smaller/muted text) to steer users toward the composite by default, matching the confirmed recommendation from `docs/PHASE10_PLAN.md` §15.3. The actual mutual-exclusion enforcement lives in `StatPriorityEditor` per §3.5, not in the picker — the picker only needs to *label* the relationship, not enforce it, since a stat set (§6) can also introduce one of these and must go through the same `canAddStat` gate.

### 4.5 Full taxonomy seed (from `docs/STAT_SHORTCUTS.md`)

Top-level categories, mirroring the doc's structure:

- **Spell Schools** → 8 leaves (Evocation, Necromancy, Enchantment, Conjuration, Divination, Abjuration, Transmutation, Illusion), stat strings `"{school} spelldc"`, plus an "All Schools" leaf → `"all spelldc"`
- **Spell Lore** → sub-categories Elemental / Alignment / Utility mirroring `docs/CASTER_STATS_XML_MAPPING.md`'s element list, stat strings `"{element} spelllore"`
- **Spell Critical Damage** → same element list, stat strings `"{element} spellcriticaldamage"`
- **Spellpower** → sub-categories Elemental / Alignment / Utility / Compound / Universal, per `docs/STAT_SHORTCUTS.md` §4's own nested structure, stat strings `"{category} spellpower"` (compound entries like Radiance/Reconstruction/Impulse get their own leaves with `note` explaining the multi-element bonus, per that doc's §4.4)
- **Warlock** → `"pact dice"` (single leaf, `note`: "Use instead of, not alongside, traditional spellpower/DC for Eldritch Blast builds.")
- **Caster Level** → four element-specific leaves, each carrying `note`: "Undocumented in the data files — the effect exists in-game but the exact bonus value is not specified in the XML. May match nothing." (per `docs/CASTER_STATS_XML_MAPPING.md` §10's own "???"-marked findings)
- **Power** → Melee Power, Ranged Power (build-type-relevant leaves only shown/highlighted per current `build_type`, but not hidden — see §4.6)
- **Attack Speed** → Melee Alacrity, Ranged Alacrity
- **Double Attacks** → Doublestrike, Doubleshot
- **Critical (General)** → Seeker
- **Armor Piercing** → single leaf
- **Two-Weapon Fighting** → Off-Hand Attack Bonus
- **Weapon Properties** → per §4.4
- **Procs** → sub-categories On-Hit / Dual-Purpose (Attunements) / Activatable Abilities, each leaf carrying the `note` caveat that most proc mechanics are undocumented in the XML (per `docs/STAT_SHORTCUTS.md`'s own proc section) — included for completeness/discoverability, not because they're expected to reliably match

### 4.6 Build-type relevance is a soft highlight, never a hard filter

`configStore.build_type` (Melee/Ranged/Caster/Tank) may cause `StatPicker` to visually promote the most relevant branch to the top of the tree or pre-expand it, but **never** hides any branch — a Mixed-damage user (per `docs/STAT_SHORTCUTS.md`'s own "Mixed Damage Build" reference) must be able to reach every category regardless of `build_type`. This mirrors §6.1's identical rule for stat sets' `buildTypes` field.

### 4.7 Picker UI

"Add stat ▾" button per lane opens a popover: a search box (flat-filters every leaf across the whole tree by `label`/`stat`, live, no debounce needed given the tree is small and static), a two-pane drill-down (categories on the left, leaves on the right) below the search when no search term is active, and a **"Use a custom stat name…"** free-text fallback pinned at the bottom of the popover at all times — this is non-negotiable: it preserves exactly today's capability (typing any string) so the taxonomy can never wall off a stat the user knows about but the tree doesn't yet list. Selecting a leaf or submitting the custom-text field both call `canAddStat` (§3.5) before adding.

---

## 5. Removing the caster checkbox grid

### 5.1 What gets deleted

`JobConfigurationForm.svelte:227-262` (the checkbox grid), `:160-178` (the auto-inject reactive block), `:180-194` (`toggleCasterOption`) are all removed outright, not relocated.

### 5.2 Why this is zero-risk to the backend

Confirmed by direct inspection: `caster_spellpowers`/`caster_schools` are read **nowhere** in `python/solver.py` or `python/optimizer.py` — they exist purely as a client-side mechanism that auto-injects picks into `stat_priorities`. Removing the checkbox UI removes the entire mechanism with no backend-visible change. (The two fields stay on the Go/TS struct per INV-3, purely for old-file deserialization.)

### 5.3 Backward-compatible migration for old saved files

On loading a `.ddogearset` file (or any point `configStore` is hydrated from a saved payload) where `caster_spellpowers.length > 0` or `caster_schools.length > 0`:

1. For each entry in either array, if it is not already present as a chip in any lane, add it to **Tier 1** (via the same `canAddStat`-gated add path as everything else, so it also gets the weapon-damage exclusion check — though these will never collide with that group in practice).
2. Clear both arrays on `configStore` (`caster_spellpowers = []`, `caster_schools = []`) so this migration runs exactly once per load, not on every reactive tick.
3. Show a toast: *"Imported N caster stat(s) from a saved gearset into Tier 1."* (N = total entries migrated across both arrays; omit the toast entirely if N is 0).

This runs once, at load time, not as a standing reactive statement — the old code's bug (`JobConfigurationForm.svelte:160-178` only ever added, never removed, so unchecking a school left its priority behind permanently) is structurally impossible to reintroduce this way, since there is no more standing sync between two representations of the same intent.

---

## 6. Stat Sets

### 6.1 Data shape

```jsonc
{
  "version": 1,
  "sets": [
    {
      "id": "melee-physical",
      "name": "Melee Physical",
      "buildTypes": ["Melee", "Tank"],
      "description": "Standard melee DPS: damage scaling first, then attack frequency.",
      "notes": null,
      "priorities": [ { "stat": "melee power", "tier": 1 } ]
    }
  ]
}
```

`buildTypes` drives **soft ordering only** (sets matching the current `build_type` float to the top of the list) — never hard filtering, so a Mixed build (or simple curiosity) can still reach every set. This mirrors §4.6's identical rule for the taxonomy tree.

### 6.2 Runtime loading — confirmed design (overrides the `expansions.json`/Vite-`public/` precedent)

**Confirmed constraint from the user: hand-edited only, but must be loadable at runtime without a rebuild.** This rules out following `expansions.json`'s exact pattern: `main.go` embeds the entire built frontend via `//go:embed all:frontend/dist`, and Vite copies `frontend/public/*` into `frontend/dist/` at build time — so anything placed in `frontend/public/stat_sets.json` and fetched via `fetch('/stat_sets.json')` would be **baked into the compiled binary**, exactly like `expansions.json` is today, and editing it after the app is built would have no effect until a rebuild. That does not satisfy "loaded at runtime."

**Design:** a new Go RPC, following the same "embedded default + optional live override" pattern already established in this codebase for the solver binary itself (`app.go:21-22`, `//go:embed python/dist/solver`):

```go
//go:embed data/stat_sets.default.json
var defaultStatSets []byte

// GetStatSets returns the user's stat-set presets. It checks for a
// hand-editable override file first (./stat_sets.json, alongside the
// existing gearsets/ directory), and falls back to the bundled default
// embedded in the binary if no override file exists or it fails to parse.
// Re-reads the override file from disk on every call — no caching — so
// hand-edits take effect on the next call with no app restart required.
func (a *App) GetStatSets() (StatSetsFile, error) {
    if data, err := os.ReadFile("stat_sets.json"); err == nil {
        var parsed StatSetsFile
        if json.Unmarshal(data, &parsed) == nil {
            return parsed, nil
        }
        a.addLog("Warning: stat_sets.json exists but failed to parse; using bundled defaults.")
    }
    var parsed StatSetsFile
    json.Unmarshal(defaultStatSets, &parsed)
    return parsed, nil
}
```

The override path (`./stat_sets.json`, relative to the app's working directory) matches the existing precedent set by `SaveGearset`'s `dir := "gearsets"` (`app.go`, also a bare relative path) — consistent with how this codebase already handles user-local data, not a new convention. `data/stat_sets.default.json` (the seed content, §6.3) ships embedded in the binary via `//go:embed`, so the app always has *something* to show even before the user ever creates an override file, and the override is purely additive/optional.

**Frontend call site:** `StatSetPicker.svelte` calls the new wailsjs-generated `GetStatSets()` binding on mount — **no `fetch()` call, no `frontend/public/stat_sets.json`.** This is the one place this spec's design diverges from the `expansions.json` precedent the architectural planning pass initially assumed, and the divergence is deliberate, driven directly by the user's stated requirement.

**Explicitly out of scope for this pass:** an in-app editor/save flow for stat sets. The user edits `stat_sets.json` by hand in a text editor; the app picks it up on next fetch (which, given no caching per the RPC's own doc comment, means simply switching tabs back to the Solver form and reopening the Stat Sets accordion is enough — no app restart needed). A future pass could add a localStorage overlay or an in-app editor; not built now.

### 6.3 Seed content (`data/stat_sets.default.json`)

Converted from `docs/STAT_SHORTCUTS.md`'s "Quick Reference by Build Type" section. Mapping rule: that doc's Primary stats → tier 1, secondary/supporting stats → tier 2-3, breadth/utility → tier 4, `[Optional]`-marked entries → tier 5. All stat name strings are lowercase (matching resolves case-insensitively both server-side, `optimizer.py:23`, and in Phase 10's duplicate-detection casefold, §2.6, so case is cosmetic — the seed file uses lowercase for consistency with the taxonomy's `stat` strings).

```json
{
  "version": 1,
  "sets": [
    {
      "id": "melee-physical", "name": "Melee Physical", "buildTypes": ["Melee", "Tank"],
      "description": "Standard melee DPS: damage scaling first, then attack frequency.",
      "notes": "Off-Hand Attack Bonus matters only for Two Weapon Fighting; remove it otherwise.",
      "priorities": [
        { "stat": "melee power", "tier": 1 },
        { "stat": "doublestrike", "tier": 1 },
        { "stat": "seeker", "tier": 2 },
        { "stat": "armor piercing", "tier": 3 },
        { "stat": "melee alacrity", "tier": 3 },
        { "stat": "offhand attack bonus", "tier": 5 }
      ]
    },
    {
      "id": "melee-weapon-focused", "name": "Melee (Weapon-Focused)", "buildTypes": ["Melee", "Tank"],
      "description": "Melee Physical plus weapon base damage and crit profile as explicit priorities.",
      "notes": "Weapon-property stats only affect Weapon1 — see docs/PHASE10_PLAN.md §15.4.",
      "priorities": [
        { "stat": "melee power", "tier": 1 },
        { "stat": "doublestrike", "tier": 1 },
        { "stat": "weapon base damage", "tier": 2 },
        { "stat": "critical multiplier", "tier": 3 },
        { "stat": "critical threat range", "tier": 3 },
        { "stat": "seeker", "tier": 4 }
      ]
    },
    {
      "id": "ranged-physical", "name": "Ranged Physical", "buildTypes": ["Ranged"],
      "description": "Bow and crossbow DPS.",
      "notes": null,
      "priorities": [
        { "stat": "ranged power", "tier": 1 },
        { "stat": "doubleshot", "tier": 1 },
        { "stat": "seeker", "tier": 2 },
        { "stat": "armor piercing", "tier": 3 },
        { "stat": "ranged alacrity", "tier": 3 }
      ]
    },
    {
      "id": "unarmed-monk", "name": "Unarmed / Monk", "buildTypes": ["Melee"],
      "description": "Centered unarmed scaling.",
      "notes": "Set Weapon Style to a centered option; this set does not change weapon filtering.",
      "priorities": [
        { "stat": "melee power", "tier": 1 },
        { "stat": "doublestrike", "tier": 1 },
        { "stat": "seeker", "tier": 2 },
        { "stat": "melee alacrity", "tier": 3 }
      ]
    },
    {
      "id": "spell-caster-fire", "name": "Spell Caster (Fire / Evocation)", "buildTypes": ["Caster"],
      "description": "Single-element caster template. Swap the element and school to match your build.",
      "notes": "Replace 'fire' with your element and 'evocation' with your school. Fire Caster Level is undocumented in the data files and may match nothing.",
      "priorities": [
        { "stat": "fire spellpower", "tier": 1 },
        { "stat": "evocation spelldc", "tier": 1 },
        { "stat": "fire spelllore", "tier": 2 },
        { "stat": "fire spellcriticaldamage", "tier": 2 },
        { "stat": "spell points", "tier": 4 },
        { "stat": "fire caster level", "tier": 5 }
      ]
    },
    {
      "id": "warlock-eldritch-blast", "name": "Warlock (Eldritch Blast)", "buildTypes": ["Caster"],
      "description": "Pact dice scaling. Deliberately omits Spell DC and elemental spellpower.",
      "notes": "Do not add traditional Spell DC. Spellpower is Tier 5 here because it only affects personal buff spells.",
      "priorities": [
        { "stat": "pact dice", "tier": 1 },
        { "stat": "fire spelllore", "tier": 1 },
        { "stat": "fire spellcriticaldamage", "tier": 2 },
        { "stat": "spell points", "tier": 4 },
        { "stat": "fire spellpower", "tier": 5 }
      ]
    },
    {
      "id": "mixed-attack-spell", "name": "Mixed (Attack + Spell)", "buildTypes": ["Melee", "Caster"],
      "description": "Dual-purpose build leaning on procs that trigger from both attacks and spells.",
      "notes": "Pick your dominant damage source for Tier 1; the other side sits at Tier 2-3.",
      "priorities": [
        { "stat": "melee power", "tier": 1 },
        { "stat": "doublestrike", "tier": 2 },
        { "stat": "fire spellpower", "tier": 2 },
        { "stat": "evocation spelldc", "tier": 3 },
        { "stat": "spell points", "tier": 5 }
      ]
    }
  ]
}
```

**Deliberately no `cap` values in the seed sets.** `docs/STAT_SHORTCUTS.md`'s bracketed annotations (e.g. `[200]`) are illustrative *targets* from that doc's own examples, not DDO game caps — baking them in as `cap` would silently stop the solver rewarding progress past a number the user never actually chose. The `cap` field is fully supported by the schema for user-authored sets; the shipped defaults simply don't use it.

### 6.4 Click-to-add conflict resolution

**Additive-by-default, user placement always wins, single-step Undo, one-click "Replace instead," no modal.**

| Situation | Behavior |
|---|---|
| Stat not present in any lane | Added to the set's specified tier, appended to the end of that lane |
| Stat already present in the **same** tier | No-op — existing position and cap are preserved untouched |
| Stat already present in a **different** tier | **Left exactly where the user put it.** Not moved, not duplicated, not flagged as an error |

After applying a set, show one toast: *"[Set name] applied — N added, M already in your list (kept at your tiers)."* with two actions:

- **Undo** — reverts to a full snapshot of all five lanes taken immediately before the set was applied. The snapshot is held in a single store variable, overwritten by the *next* apply and cleared by any other unrelated priority-list mutation (so "Undo" always means "undo the last stat-set apply specifically," never something stale).
- **Replace instead** — re-applies the same set, but this time stats already present in a different tier ARE moved to the set's specified tier (this is the one-click path to the overwrite behavior, available without ever needing a confirmation modal).

Conflicting chips (present in a different tier than the set specifies) get a brief (~3s) visual highlight so the user can see at a glance which stats differed, without having to parse the toast text.

**Why this shape and not the alternatives:** a silent overwrite would destroy hand-tuning, and under the tiered model, silently moving a stat between tiers changes a hard lexicographic lock — a much larger invisible consequence per click than it was under the old flat-weight system. A confirmation modal directly fights the user's own stated goal ("just click on them and the values are added"). Skip-with-toast alone leaves the same-tier case ambiguous and gives no path back to the set's own opinion. Undo + Replace-instead covers both without a dialog, and — by construction, since a chip can only ever live in one lane (INV-1) — Phase 10 §2.6's duplicate-across-tiers server error can never be triggered by this flow; the conflict is resolved structurally on the client before any payload is built, not caught after the fact.

**Dependency on `Toast`/`showToast`:** the existing `ToastMessage` interface (`store.ts:147-151`) and `showToast()` (`store.ts:158-164`) support plain text only, auto-dismissing after a hard 3500ms. This spec requires:

```typescript
export interface ToastMessage {
    id: number;
    text: string;
    kind: 'success' | 'error' | 'info';
    actions?: { label: string; onClick: () => void }[];   // NEW
}
```

And `Toast.svelte` gains rendering for `actions` (buttons within the toast) plus a rule that a toast with any `actions` does **not** auto-dismiss on the standard timer — it dismisses only when an action is clicked, or after a longer grace period (recommend 8000ms, long enough to read+decide, short enough not to accumulate indefinitely) if left untouched. This is a small, explicit dependency this spec introduces on the shared toast system — call it out during implementation planning so it isn't discovered mid-build.

---

## 7. Results-side changes

### 7.1 `computeFiligreeBias()` — deleted, not ported

`JobConfigurationForm.svelte:80-98` is a JS mirror of the now-deleted Python `compute_priority_bias` (`docs/PHASE10_PLAN.md` §3.6 confirms the Python original is replaced by `compute_tier_weights`). Under the new design there is no bias percentage to compute — filigrees are already ordinary sources within Tier 1's own objective. Delete the function and its call site (`JobConfigurationForm.svelte:98` and the rendering at `:423-427`) entirely.

**Static replacement**, one line rendered directly under the Tier 1 lane header: *"Filigrees are only counted toward Tier 1. Tiers 2–5 are optimized from items, augments and set bonuses only."* — this is the honest, actionable version of what the deleted percentage display was gesturing at, and directly explains the one behavior most likely to surprise a user coming from the old system.

### 7.2 `TierReport.svelte` — new, in the results view

Renders `resultStore.tierReport`/`tierScores`/`unmetTier4`/`unmatchedPriorities` (Phase 10 §9's new output fields) after a solve:

- Per-stage summary: tier number, `goalValue`, `proven` (badge: "Optimal" vs. "Time-limited" when `false`), elapsed vs. budgeted seconds.
- `unmetTier4`: listed plainly as "Tier 4 stats not reached (would have cost a higher tier): [list]."
- `unmatchedPriorities`: listed plainly as "These priorities matched nothing in the data files: [list]" — and, per §4.1's mitigation design, this is the list `StatPriorityEditor` also cross-references to badge the corresponding still-placed chips on the form's next render.
- `degraded`: a visible banner when true, surfacing `tierReport.notes` verbatim (Phase 10's EC-11/EC-23/EC-24/EC-27 all populate `notes` with human-readable explanations for exactly this situation — display them as-is, don't re-word them).

This directly replaces the old bias-percentage display's *function* (explaining what drove the result) without reimplementing its *mechanism* — the frontend now reports the solver's own factual answer instead of recomputing a heuristic client-side, which is a strictly more trustworthy design (no possibility of the display drifting from what the solver actually did).

### 7.3 `max_search_time` slider

- Label changes to **"Total Search Time (seconds — across all solve stages)"**; helper text to *"Split across up to five tier stages plus a consolidation pass. Longer budgets help most when you use many tiers."*
- `min` changes from `5` to `10` (Phase 10 §4.5 clamps to `[10, 1800]`; the old `min=5` could submit a value the backend silently rewrites without telling the user).
- `max` changes from `300` to `600`; add static helper text noting the backend's hard ceiling of 1800 for users who need more.
- After a solve, render `tierReport.totalElapsedSeconds` against the configured budget (small text under the slider, e.g. "Last run: 42s of 60s budget") and flag any `proven: false` stage inline — this is the concrete, actionable signal for "you should raise this slider," directly sourced from `TierReport.svelte`'s data (§7.2), not a separate computation.

### 7.4 `calculate_only` store-mutation fix

`GearsetEditor.svelte`'s `calculateGearSet()` (`:350-378`) currently sets `$configStore.calculate_only = true`, calls `RunOptimization($configStore)`, and resets it in a `finally` block — a mutate-then-restore on a shared reactive store, visible to every other subscriber for the duration of the call, and unsafe if the user triggers a second action mid-call. Fix, using Phase 10's new `mode` field:

```typescript
async function calculateGearSet() {
    $isOptimizing = true;
    try {
        const hydrated = hydrateConfigFromSlots($configStore, $resultStore?.slots);
        const payload = { ...$configStore, ...(hydrated ?? {}), mode: 'calculate' };
        const res = await RunOptimization(payload);
        // ... unchanged from here
    } finally {
        $isOptimizing = false;   // no more calculate_only reset — nothing was mutated
    }
}
```

`configStore.calculate_only` itself stays on the struct (legacy field, Phase 10 §2.5 keeps it as a back-compat input) but this call site stops writing to it — the per-call shallow copy makes the store no longer a place where "calculate mode" is ever visible mid-flight to other subscribers.

---

## 8. `Accordion.svelte` (`$lib/components/ui/`)

### 8.1 Hand-rolled — confirmed, shadcn-svelte not viable

This project is pinned to `svelte: ^3.49.0` (confirmed via `package.json`). Current shadcn-svelte's Accordion wraps `bits-ui`, which targets Svelte 4/5 — adopting it means either pinning an old shadcn-svelte release or a Svelte major-version upgrade, a large, unrelated risk for one collapsible component. It would also pull `bits-ui` + `tailwind-variants` + `clsx` + `tailwind-merge` into a frontend whose entire current dependency list is Svelte + Tailwind + Vite + TypeScript (confirmed via `package.json` — no shadcn-svelte runtime packages are installed despite `components.json` being scaffolded), and the shadcn-svelte CLI additionally expects a `$lib/utils` `cn()` helper this repo doesn't have.

Against that: the existing hand-rolled pattern at `JobConfigurationForm.svelte:346-366` (`showExcludedPacks` boolean + `▲`/`▼` button) already works and already matches the `.glass-panel`/Tailwind visual language used throughout. Generalizing it is small.

### 8.2 Contract

```svelte
<script lang="ts">
  export let title: string;
  export let open: boolean = false;
  export let summary: string | undefined = undefined;   // collapsed-state digest, e.g. "Reserved: Ring · 4 filigree slots"
  export let persistKey: string | undefined = undefined; // localStorage key for open/closed state, see §8.3
</script>

<div class="glass-panel">
  <button on:click={toggle} aria-expanded={open} aria-controls={contentId}>
    <span>{title}</span>
    {#if !open && summary}<span class="text-muted-foreground text-sm">{summary}</span>{/if}
    <span>{open ? '▲' : '▼'}</span>
  </button>
  {#if open}
    <div id={contentId}><slot /></div>
  {/if}
</div>
```

No `AccordionGroup`/mutual-exclusion wrapper — sections open/close independently (a user will reasonably want Stat Priorities and Stat Sets open at once).

### 8.3 Persisted open/closed state

When `persistKey` is provided, the component reads/writes `localStorage['accordion:' + persistKey]` (`'open'`/`'closed'`) so the form doesn't re-collapse every time the user revisits it. `JobConfigurationForm.svelte` assigns a stable `persistKey` per section (§9's table) — Stat Priorities intentionally has **no** `persistKey` and is always mounted with `open=true` and no override, since it's the primary input and must never silently start collapsed regardless of prior session state.

---

## 9. Section layout for `JobConfigurationForm.svelte`

| # | Section | Wrapped in `Accordion`? | `persistKey` | Contents |
|---|---|---|---|---|
| 1 | Build Profile | No — always visible, not collapsible | — | Build Type, Weapon Style, Offhand Style (conditional), Character Level, Armor Restriction |
| 2 | Stat Sets | Yes, default collapsed | `stat-sets` | `StatSetPicker.svelte` |
| 3 | Stat Priorities | Yes, **always open, no persisted override** | — (none) | `StatPriorityEditor.svelte` |
| 4 | Equipment Constraints | Yes, default collapsed | `equipment-constraints` | Max Raid Items, Runearm Use, Exclude Gem of Many Facets (currently loose in the grid at `:281-309`) |
| 5 | Artifact Configuration | Yes, default collapsed | `artifact-config` | Existing block, `:311-343`, summary text e.g. "Reserved: Ring · 4 filigree slots" |
| 6 | Content Filters | Yes, default collapsed | `content-filters` | Excluded Expansion Packs — existing hand-rolled toggle at `:346-366`, converted to use `Accordion`, summary e.g. "3 excluded" |
| 7 | Solver Settings | Yes, default collapsed | `solver-settings` | Total Search Time (§7.3) |
| — | Actions | Always visible, sticky at panel bottom | — | Optimize / Update External Sources buttons, so they remain reachable regardless of which sections are expanded |

The caster grid (old `:227-262`) is not in this table — deleted per §5.

---

## 10. TypeScript/store changes

### 10.1 `store.ts`

- `statPriorities` initial value in `configStore` changes from `[]` (untyped) to an explicitly-typed empty array of the new tier shape (type comes from regenerated `wailsjs/go/models.ts` per INV-5's dependency on Phase 10 landing first).
- `ToastMessage` gains `actions?` per §6.4.
- No changes to `SlotDetail`/`SlotBuff`/etc. — those are `docs/ITEM_DETAIL_SPEC.md`'s and Phase 10's concern respectively, not this spec's.

### 10.2 New file `frontend/src/lib/data/statTaxonomy.ts`

Per §4.2/§4.3.

### 10.3 New file `frontend/src/lib/data/statSets.ts` (thin wrapper, not the data itself)

```typescript
import { GetStatSets } from '../../../wailsjs/go/main/App';

let cached: StatSetsFile | null = null;

export async function loadStatSets(forceRefresh = false): Promise<StatSetsFile> {
    if (cached && !forceRefresh) return cached;
    cached = await GetStatSets();
    return cached;
}
```

`forceRefresh` exists so `StatSetPicker` can offer a manual "Reload" affordance (small, e.g. a refresh icon next to the section title) letting a user who just hand-edited `stat_sets.json` see the change without navigating away and back — a cheap, direct answer to "how do I know my edit took effect," worth including given the runtime-loading requirement is the whole point of §6.2's design.

---

## 11. Success criteria / acceptance checks

### Tier lane UI

| ID | Check |
|---|---|
| **AC-1** | Adding the same stat twice (once per lane, via two separate `StatPicker` invocations) is impossible through the UI — the second add either moves the existing chip (if using "move to tier") or is a no-op; at no point do two chips for the same `stat` string exist simultaneously across all five lanes. |
| **AC-2** | `serializePriorities` on a populated set of lanes produces an array where, for any two entries with the same `tier`, their relative order matches their relative position within that lane. |
| **AC-3** | Loading a `configStore.stat_priorities` array with interleaved tiers (e.g. `[{stat:"A",tier:3}, {stat:"B",tier:1}, {stat:"C",tier:3}]`) into `StatPriorityEditor` places `B` alone in lane 1 and `A`,`C` in lane 3 in that exact relative order — round-trips losslessly through §3.6/§3.7. |
| **AC-4** | Entering `cap: 0` or a non-integer in the inline cap editor is rejected client-side with the message "Cap must be a positive integer." and no chip mutation occurs. |
| **AC-5** | Selecting `weapon base damage` when `weapon damage` is already present in any lane is blocked with the toast described in §3.5, and no chip is added. The reverse direction (composite present, adding a component) is also blocked. Adding `critical multiplier` alongside `weapon base damage` is **not** blocked (different exclusion group). |

### Stat picker / taxonomy

| ID | Check |
|---|---|
| **AC-6** | The "Use a custom stat name…" field is present and functional in every lane's picker popover, and successfully adds an arbitrary string not present anywhere in `STAT_TAXONOMY` (subject only to the AC-5 exclusion-group check). |
| **AC-7** | Every leaf's `stat` string in `STAT_TAXONOMY`'s Weapon Properties branch exactly matches one of the five strings defined in `docs/PHASE10_PLAN.md` §15.2's table (`weapon damage`, `base damage dice`, `critical multiplier`, `critical threat range`, `weapon base damage`) — a literal string-equality test against that table, to prevent taxonomy/solver drift. |
| **AC-8** | Search in the picker popover matches on both `label` and `stat` (e.g. searching "spelldc" surfaces "Evocation" via its `stat` string even though the visible `label` is "Evocation"). |

### Caster grid removal / migration

| ID | Check |
|---|---|
| **AC-9** | Loading a fixture `.ddogearset` payload with non-empty `caster_spellpowers`/`caster_schools` and an otherwise-empty `stat_priorities` results in every entry from both arrays appearing as a Tier 1 chip after load, and both arrays are empty on `configStore` immediately after. |
| **AC-10** | The same fixture load triggers exactly one toast, worded per §5.3, with the correct count N. |
| **AC-11** | No component anywhere in the codebase references `toggleCasterOption` after this change lands (a grep-based check, confirming full removal rather than dead code left behind). |

### Stat sets

| ID | Check |
|---|---|
| **AC-12** | `GetStatSets()` returns the embedded default content when no `stat_sets.json` override file exists at the app's working directory. |
| **AC-13** | Placing a valid override `stat_sets.json` at the app's working directory and calling `GetStatSets()` again (fresh process or via the `forceRefresh` reload path) returns the override's content, not the embedded default. |
| **AC-14** | Placing a malformed (invalid JSON) override file: `GetStatSets()` still returns the embedded default (does not error, does not return an empty/partial result), and a warning is logged (visible via `GetSystemLogs()`). |
| **AC-15** | Applying a stat set where every stat is new: all its entries appear as chips in their specified tiers, in the set's given order within each tier. |
| **AC-16** | Applying a stat set where one stat already exists in a **different** tier than the set specifies: that chip's tier and position are **unchanged** after applying; all other new stats from the set are still added normally; the toast reports the correct "N added, M already in your list" counts. |
| **AC-17** | Clicking "Undo" immediately after an apply restores the exact lane state (tiers, order, caps) from immediately before the apply. |
| **AC-18** | Clicking "Replace instead" immediately after an apply moves every conflicting stat (per AC-16's scenario) to the set's specified tier. |
| **AC-19** | The `weapon-melee-weapon-focused` (or any other seed set containing `weapon base damage`) can never be blocked by its own internal content — i.e. no shipped default set in `data/stat_sets.default.json` violates the mutual-exclusion group itself (a static content check, not a runtime one). |

### Accordion / layout

| ID | Check |
|---|---|
| **AC-20** | Toggling any accordion section with a `persistKey` set, then reloading the app (simulated via remounting the component in a test), restores the same open/closed state from `localStorage`. |
| **AC-21** | The Stat Priorities section renders open regardless of any `localStorage` state (confirms no `persistKey` was ever assigned to it, per §8.3's explicit exception). |
| **AC-22** | Every section listed in §9's table with `Yes` under "Wrapped in `Accordion`?" is in fact rendered via the `Accordion` component, not a bespoke boolean+button block (a structural/DOM check, guards against a future edit reverting to the old hand-rolled pattern piecemeal). |

### Results-side

| ID | Check |
|---|---|
| **AC-23** | `computeFiligreeBias` does not exist anywhere in the frontend codebase after this change (grep-based check). |
| **AC-24** | `TierReport.svelte` renders `tierReport.notes` verbatim (no re-wording) when `degraded === true`. |
| **AC-25** | `TierReport.svelte`'s `unmatchedPriorities` list, when non-empty, results in a warning badge appearing on the corresponding still-placed chip(s) in `StatPriorityEditor` on next render. |
| **AC-26** | `calculateGearSet()` in `GearsetEditor.svelte` never mutates `$configStore.calculate_only` (a static/structural check against the diff, or a runtime spy in a test verifying the store's `calculate_only` field is untouched across a full calculate-mode call). |

---

## 12. Edge cases

| ID | Case | Required behavior |
|---|---|---|
| **EC-1** | User empties every lane (removes all priorities) | The Optimize button remains enabled but a solve attempt fails per Phase 10's own EC-4 ("no stat priorities provided" validation error) — this spec does not add a client-side pre-check blocking submission with zero priorities; the existing error-toast path (already wired to `errorMessage` from a failed `RunOptimization`) surfaces the server's message as-is. |
| **EC-2** | A single lane contains more than ~8-10 stats | No UI limit imposed — Phase 10 §3.6's `WEIGHT_FLOOR` already keeps every entry's weight numerically distinguishable regardless of count; the lane simply scrolls if it overflows its container height. |
| **EC-3** | User selects a taxonomy leaf whose `note` field is present (e.g. an undocumented caster-level stat) | The `note` text is shown as a small inline caveat under the chip once added (not just in the picker popover before adding) — so the caveat remains visible for as long as the chip exists, not only at selection time. |
| **EC-4** | A stat set's `buildTypes` doesn't include the current `build_type` | The set still appears in the list (soft ordering only per §6.1), just not promoted to the top. |
| **EC-5** | `GetStatSets()` override file exists but its `version` field doesn't match what the frontend expects | This spec targets `version: 1` only; treat any other value the same as a parse failure (§ AC-14's path — fall back to embedded default, log a warning) rather than attempting a migration, since there is only one version defined so far. |
| **EC-6** | User applies the same stat set twice in a row with no edits in between | Second apply is a full no-op for every stat (all already present in matching tiers per the "same tier" row of §6.4's table) — toast reports "0 added, N already in your list," Undo/Replace-instead still offered but have nothing meaningful to do (Undo restores an identical state; Replace-instead moves nothing since nothing conflicts). Not an error. |
| **EC-7** | User clicks "Undo" a second time, after already using it once, with no new apply in between | No-op — the undo snapshot was already consumed/cleared by the first Undo (or by any other unrelated mutation) per §6.4's snapshot lifecycle description; a second click has no snapshot to restore and should be a disabled/hidden action once used, not a silent no-op the user can't distinguish from "it worked." |
| **EC-8** | The legacy migration (§5.3) runs on a file where a caster stat is *already* present in a lane at a tier other than 1 | Per the same logic as any other "already present" case — leave it where the user (or a prior migration) already placed it; do not force it to Tier 1. The migration only *adds* stats that aren't present anywhere yet. |
| **EC-9** | Cap editor is opened on a chip, then the popover is dismissed (click-away) without submitting | No mutation — the cap editor behaves like a standard cancelable inline-edit control, not a live-binding input. |
| **EC-10** | `TierReport.svelte` is rendered before any solve has ever run in the session (`resultStore.tierReport` is `undefined`) | Section does not render at all (same absent-data convention used throughout `docs/ITEM_DETAIL_SPEC.md`'s section-visibility rules, §7.2 of that doc) — no empty/placeholder panel. |

---

## 13. Out of scope for this pass (deferred, recorded for later)

1. **In-app stat-set authoring/saving.** `stat_sets.json` is hand-edited only; no create/edit/save UI ships now. A future pass could add a localStorage overlay or a Go-backed write RPC.
2. **Cross-lane drag-and-drop.** Buttons + "move to tier" cover the functionality; true DnD needs a library this project doesn't currently depend on.
3. **Live "N sources found" validation on taxonomy leaves.** Deferred because it requires porting `normalize_stat_name` to Go — the same duplication risk `docs/ITEM_DETAIL_SPEC.md` independently rejects. The post-solve `unmatchedPriorities` feedback loop (§4.1, §7.2) is the mitigation for this pass.
4. **Per-hand (`main hand`/`off hand`) weapon-stat variants.** Not built — `docs/PHASE10_PLAN.md` §15.4 confirms weapon-base stats are Weapon1-scoped only in this pass; if a future need for independent off-hand prioritization emerges, it's a separate extension to both the solver and this taxonomy.
5. **`alt_tolerance` cutoff for the (separately spec'd, not yet frontend-built) `GetSlotAlternatives` results UI.** Out of scope for this spec entirely — that RPC has no frontend consumer yet; this document does not attempt to design one.
