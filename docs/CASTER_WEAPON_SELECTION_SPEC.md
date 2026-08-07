# Spec — Revisit Caster Weapon Selection

**Status:** Implemented (0.3.4). A separate "Two-Handed Weapon" caster style
(covering the broader two-handed pool, including crossbows without a runearm)
was added afterward to close a gap this spec didn't originally cover — see
`docs/HARD_REQUIRED_SLOTS_SPEC.md` §4.
**Depends on:** `docs/HARD_REQUIRED_SLOTS_SPEC.md` (the craftable-family + highest-ML +
fallback mechanism this spec extends already exists and is proven for Melee/Ranged/Tank).

## Goal

Casters currently pick Weapon1/Weapon2 purely by stat-priority score across the *entire*
one-handed/crossbow pool, with no notion of "this is a meta caster stick" at all. Extend
the same craftable-family restriction already built for other build types to casters, so
caster weapon selection reflects real DDO caster gearing practice: prefer weapons from
known multi-augment-slot "meta" families, informed by the user's own priorities rather
than a hardcoded per-element lookup.

## Why NOT a hardcoded element → weapon table

The original ask cited specific named weapons (Arctica for Cold, Amplin for Electric,
Wither for Poison, Clank/Soniar for Sonic, Caustica/Erosion for Acid, Defiled Reliquary
variants for whatever element they roll). Explicit instruction during scoping: **"I don't
want the current meta weapons to be fixed, but rather they form a template of what's
desirable."** These named weapons are useful as *evidence* of what a good caster weapon
looks like (multi-slot, from a specific crafting/raid family), not as a list to hardcode.

The mechanism below achieves this without any element-specific lookup: restrict the
candidate pool to the craftable families (which is where all the cited "meta" weapons
already live), then let the *existing* tiered stat-priority ILP — already informed by
whichever elements/schools/main stat the user picked in `CasterConfig.svelte` — pick
whichever family candidate actually scores best for their real priorities. A Cold caster
naturally ends up on the family weapon with the best Cold-relevant stats without this
code ever knowing the word "Arctica."

## Verified against real DDOBuilderV2 data

| Claim | Verified? | Detail |
|---|---|---|
| Amplin/Arctica/Clank/Soniar/Wither/Collision/Caustica/Erosion are all real | Yes | All 8 exist, all `MinLevel 33`, all `DropLocation` = "Den of Vipers, end chest" — **already covered** by the existing `den of vipers` DropLocation-substring family |
| "Lamordia weapons" | Partially wrong name, confirmed once corrected | No item is named "Lamordian ...weapon" (32 "Lamordian" items are all armor/cloaks, zero weapons). The real weapon line starts with **"Calamitous"** — confirmed `Legendary Calamitous Warhammer`'s own `DropLocation` is "Viktranium Experiment crafting..." — i.e. **Calamitous weapons ARE the existing Viktranium family**, already covered, no new work needed |
| "Defiler weapons" | Wrong name, confirmed once corrected | No item named "Defiler ...". The real line starts with **"Defiled Reliquary"** (confirmed 100 items, e.g. `Legendary Defiled Reliquary Sickle`, `Defiled Reliquary Longbow`) — **NOT currently covered**: its `DropLocation` text is "Unholy Defiler of the Hidden Hand, defiled version of ..." (a different quest name), not "Defiled Reliquary" itself, so this needs **name-substring** detection, same pattern as Dinosaur Bone/Undying Age/Green Steel |
| Brighthorn / Legendary Affirmation | Real, but out of scope here | Confirmed real (Brighthorn augment, `IoD: Weapon: Horn Slot`; three distinct "Legendary Affirmation"-granting augments across `Sealed in Fire`/`Sealed in Mist`, `Greensteel Weapon Active`, and `Woeful Slot (Weapon)`) — tracked as its own separate spec per explicit decision, since it's build-type-agnostic, not caster-specific; not yet written |

## Design

### 1. New sixth craftable family: Defiled Reliquary

Add `'defiled reliquary'` to `CRAFTABLE_FAMILY_NAME_SUBSTRINGS` in `optimizer.py`:

```python
CRAFTABLE_FAMILY_NAME_SUBSTRINGS = ('dinosaur bone', 'undying age', 'green steel', 'defiled reliquary')
```

No `CRAFTABLE_FAMILY_DROPLOCATION_SUBSTRINGS` change needed — Viktranium/Den of Vipers
already cover Calamitous and the eight named Den of Vipers weapons respectively.

This one change affects **every** build type that already uses the craftable-family
mechanism (Melee, Ranged, Tank, Thrower Weapon2), not just casters — Defiled Reliquary
weapons become a legitimate sixth family everywhere, which is correct: nothing scopes the
existing mechanism to "the families known when it was written," and there's no reason a
melee build's craftable-family Weapon1 search should overlook this family either.

### 2. Apply craftable-family restriction to caster Weapon1 (all four styles)

Today, caster styles set `weapon1_eligible_types = None` in `resolve_weapon_lists` — no
restriction at all. Change to: for `build_type == 'Caster'`, always restrict Weapon1 to
the six craftable families among whatever `w1_list` already allows (caster-stick one-
handed set for Dual Caster/Stick and Orb/Stick and Runearm; the crossbow set for Crossbow
and Runearm), with the same fallback-to-unrestricted-within-type behavior already proven
for Melee: if zero family candidates exist, fall back to any weapon of the eligible type,
with a note surfaced in the Summary UI and saved file (identical mechanism, no new code
path — `_restrict_weapon_slot_to_craftable_family` already takes `eligible_types` as a
plain set; caster just needs to pass one instead of `None`).

**Decided:** gated behind a new opt-out toggle, `caster_restrict_weapon_families`
(bool, default `true`) — a checkbox in the Caster Configuration panel
("Restrict to craftable-family weapons (Dinosaur Bone, Undying Age, Green Steel,
Calamitous, Den of Vipers, Defiled Reliquary)"), checked by default. Unchecking it sets
`weapon1_eligible_types = None` for the caster styles, same as today's unrestricted
behavior — the same escape hatch Melee's "Any (no restriction)" damage-type option
already provides, for the same reason (the family-restriction fallback only guards
against *zero* candidates, not "a family candidate exists but scores worse than a
better non-family weapon").

Wire-format: new `OptimizationPayload.CasterRestrictWeaponFamilies bool` field
(`json:"caster_restrict_weapon_families,omitempty"`), read in `solver.py` via
`parsed_data.get('caster_restrict_weapon_families', True)` — defaults to `True` even
for old saved files that predate this field, since that's the new intended default
behavior going forward, not a preserved-old-behavior fallback.

### 3. Weapon2 for Dual Caster gets the same treatment; Orb/Runearm do not

Dual Caster's Weapon2 is also a "caster stick" (one-handed weapon) — same restriction
applies, same as Weapon1. Stick and Orb's Weapon2 (an Orb) and Stick/Crossbow and
Runearm's Weapon2 (a Runearm) are **not** restricted by this spec — orbs and runearms
weren't part of the cited rationale (the rationale is entirely about *weapon* slot
augment capacity), and restricting orbs specifically would make a real, verified-good
item (`Legendary Alchemical Orb`, ML 29, "Legendary Master Artificer" raid loot,
independently praised in the original conversation) unreachable, since it doesn't belong
to any of the six families and isn't part of a larger "Orb family" pattern the way the
weapon lines are. Left alone deliberately, not an oversight.

## Verification plan (once implemented)

Same pattern already used for the Ranged/Tank extension: live checks against real data
for each of the four caster styles, confirming the solver lands on a real family weapon
(Den of Vipers/Dinosaur Bone/Undying Age/Green Steel/Calamitous/Defiled Reliquary) when
one exists for the selected element/priorities, and confirming the fallback note fires
correctly when `excluded_packs`/`owned_item_names` restrictions eliminate every family
candidate for a given style.

## Decisions (confirmed)

1. **Opt-out toggle, not always-on** — see §2's "Decided" note. `caster_restrict_weapon_families`,
   default `true`, unchecking reverts to today's fully-unrestricted behavior.
2. **No special recognition for single good non-family items** (`Legendary Alchemical
   Orb` etc.) — confirmed, leave fully unrestricted, no 7th "notable items" list.

## Out of scope (tracked separately)

- The Affirmation-slot-priority rule ("if Hit Points is in Tier 1, prefer Affirmation-
  slottable weapons regardless of build type") — separate spec, per explicit decision:
  build-type-agnostic, not specific to caster weapon selection.
- No changes to Ranged/Tank/Thrower weapon selection beyond the new sixth family
  automatically being available to them too (§1).
