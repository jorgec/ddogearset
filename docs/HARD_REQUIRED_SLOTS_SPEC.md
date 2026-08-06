# Spec — Hard-Required Weapon Slots + Caster Dual-Stick Support

**Status:** Design complete via interactive review (2026-08-06), not yet implemented.
**Origin:** Solver rules review this session surfaced that non-weapon slots (Boots,
Bracers, Ring_2, etc.) can legitimately come back empty from a solve when the search
just didn't find an improvement there — that's acceptable. But some slots must never
come back empty, and the solver currently has no hard guarantee for any of them.

## Goal

Guarantee Weapon1 is always filled with an appropriate item for the build's fighting
style, and guarantee Weapon2 is filled with a runearm when `runearm_use` is on — both
enforced as hard ILP constraints, not left to the tiered search's discretion. Along the
way, give Caster builds a real Weapon2 slot (today `weapon_style` is force-set to
`'None'` for casters, so there is no offhand slot at all).

## 1. Melee weapon1 (hard-required)

### Damage-type classification — authoritative source, not guessed

`DDOBuilderV2/Output/DataFiles/WeaponGroupings.xml` has real `Slashing`/
`Bludgeoning`/`Piercing` `<WeaponGroup>` entries. Use these verbatim — do NOT derive
damage type from `<DRBypass>` (that reflects what DR a weapon bypasses, not its damage
type — many items grant bonus bypass types unrelated to their base) or from
`<Description>` text (only 5 items in the whole corpus mention a damage type in
description; far too sparse to rely on).

```
Slashing (15):    Bastard Sword, Battle Axe, Dwarven Axe, Falchion, Great Axe,
                   Great Sword, Hand Axe, Kama, Khopesh, Kukri, Longsword,
                   Scimitar, Shortsword, Shuriken, Sickle
Bludgeoning (11):  Club, Great Club, Handwraps, Heavy Mace, Light Hammer,
                   Light Mace, Maul, Morningstar, Quarterstaff, Unarmed, Warhammer
Piercing (5):      Dagger, Dart, Heavy Pick, Light Pick, Rapier
```

`Throwing Axe`, `Throwing Dagger`, `Throwing Hammer` are real melee-usable weapon
types in the corpus but appear in **none** of the three groups (DDOBuilderV2 treats
them as thrown/ranged only) — **excluded entirely** from this heuristic, not assigned
a guessed damage type.

New user input needed: a Slashing/Piercing/Bludgeoning selector (melee/tank builds
only — see §3 Deferred).

### "Craftable" weapon families

Redefined during review — this is NOT about augment-slot-type families (Cannith
Prefix/Suffix/Extra etc.), it's a specific list of five weapon *sources* known for
carrying multiple worthwhile augment slots:

| Family | Identification method |
|---|---|
| Dinosaur Bone | `Name` contains `"Dinosaur Bone"` |
| Undying Age | `Name` contains `"Undying Age"` |
| Legendary Green Steel | `Name` contains `"Green Steel"` (confirmed: 40 real items, e.g. `"Legendary Green Steel Quarterstaff"` — note it's two words, not "Greensteel") |
| Viktranium Experiment crafting | `DropLocation` contains `"Viktranium"` — no reliable name substring found |
| Den of Vipers | `DropLocation`/quest contains `"Den of Vipers"` — no reliable name substring found |

### Selection heuristic

1. Filter the Weapon1 candidate pool to the selected damage type (per the table above).
2. Filter further to items from one of the 5 families above.
3. Among survivors: prefer highest `MinLevel`, then best critical threat range (18–20
   or better preferred).
4. **Fallback:** if step 2 leaves zero candidates (e.g. no family-weapon of the chosen
   damage type survives whatever pack exclusions / ML range are in effect), drop the
   5-family requirement and fall back to "any weapon of the right damage type" from
   step 1's pool. When this fallback fires, surface an explanation both in the
   Summary UI and persisted in the saved `.ddogearset` file — the user must be able to
   see after the fact that the craftable-family requirement was relaxed and why.

## 2. Weapon2 / Runearm (hard-required, conditional)

When `runearm_use` is checked, Weapon2 must be filled with the best-scoring available
runearm (by the existing tiered stat-priority scoring — no separate heuristic needed,
this slot is already a distinct, naturally-filtered candidate pool via
`allowed_w2_list = ['runearm']`). Every other offhand assignment (TWF second weapon,
Sword and Board shield, Orb) stays soft/optional — **Runearm is the only hard-required
Weapon2 case.**

## 3. Enforcement mechanism

Hard ILP constraints added directly to `create_model` (`python/optimizer.py`), mirroring
the existing minor-artifact "exactly one" rule (`optimizer.py:1141-1146`):

```python
# Weapon1 always required
weapon1_vars = [x[(i, s)] for (i, s) in x.keys() if s == 'Weapon1']
if weapon1_vars:
    prob += pulp.lpSum(weapon1_vars) == 1

# Weapon2 required only when runearm_use is on
if runearm_use:
    weapon2_vars = [x[(i, s)] for (i, s) in x.keys() if s == 'Weapon2']
    if weapon2_vars:
        prob += pulp.lpSum(weapon2_vars) == 1
```

The candidate pool feeding `x[(i, 'Weapon1')]` must already be pre-filtered to the
damage-type + craftable-family (or fallback) set described in §1 — the constraint
alone doesn't encode the heuristic, it just guarantees *something* from that pool gets
picked.

## 4. Caster weapon slots

Today `weapon_style` is force-set to `'None'` for `build_type === 'Caster'`
(`JobConfigurationForm.svelte`'s reactive block), so there is no Weapon2 slot for
casters at all. Replace this with four real caster-specific `weapon_style` options:

- **Dual caster sticks** — Weapon1 AND Weapon2 both required, both one-handed weapons.
  ("Caster stick" = any one-handed weapon, not literally a Quarterstaff — Quarterstaff
  is two-handed and is its own separate option below.)
- **Caster stick + orb** — Weapon1 one-handed (required), Weapon2 = Orb (required).
- **Caster stick + runearm** — Weapon1 one-handed (required), Weapon2 = Runearm
  (required — same hard-constraint mechanism as §2, just always-on for this style
  rather than conditional on a separate `runearm_use` checkbox).
- **Quarterstaff** — Weapon1 = Quarterstaff (two-handed, required); Weapon2 slot is
  blocked and must not be slotted (same as how THF works for melee today).

Rationale (from the original ask): two one-handed caster weapons (e.g. Dinosaur Bone,
Lamordian, or other multi-slot crafted one-handers) can carry Meltfang (Alchemical
Earth) + Icefang (Alchemical Water) procs plus two more of Melthorn/Brighthorn/
Shadowhorn/Black Sands' Desire/Aspect of Tar/Sparkhorn/Flamehorn/Icehorn, and a +2
alchemical stat bonus each — in practice out-scoring a single Quarterstaff's scale-
augment advantage in nearly every real build. Quarterstaff remains an option, just not
the assumed default.

### Caster tier-1 auto-prefill

New multi-select inputs for Caster builds, each pre-filling Tier 1 stat priorities:

- **Elemental damage type** (multi-select): Fire, Cold, Acid, Electric, Sonic, Force,
  Positive, Negative, Poison, Repair → adds `"<Element> Spellpower"` at Tier 1 for
  each selected element.
- **Main caster stat** (single-select): Intelligence, Charisma, or Wisdom → added at
  Tier 1.
- **Spell school** (multi-select, 0 to n): each selection adds **one** entry,
  `"<school> spelldc"` — matching the existing `statTaxonomy.ts` convention exactly
  (`Spell Schools (Spell DC)` category), not the originally-proposed separate
  `"<School> Spell Focus"` + `"<School> DC"` pair. `normalize_stat_name`
  (`optimizer.py`) already folds Spell Focus matching into any priority containing
  `"dc"`, so a second entry would just match overlapping data twice — corrected
  during implementation once this was noticed.

## 5. Ranged and Tank (implemented in a follow-up pass)

Same craftable-family + highest-ML mechanism as Melee's Weapon1, generalized in
`create_model` to `weapon1_eligible_types`/`weapon2_eligible_types` (sets of exact
lowercase `weapon_type` strings, rather than melee's damage-type classification) so
one restriction+fallback+note mechanism serves both. `solver.py`'s
`resolve_weapon_lists` computes the actual type set per `build_type`/`weapon_style`:

- **Bow** → Weapon1 restricted to `{longbow}` (never Shortbow); Weapon2 always
  blocked (`w2_list = ['none']`), `runearm_use` has no effect here.
- **Repeating Crossbow** → `{repeating heavy crossbow}` (never Repeating Light).
- **Great Crossbow** → `{great crossbow}` (only one real type, kept for consistency).
- **Dual Crossbow** → `{heavy crossbow}` (never Light Crossbow) — "other crossbows"
  in the original ask.
- All three crossbow styles: Weapon2 may **only** be a runearm, and only when
  `runearm_use` is checked (`require_weapon2` follows `runearm_use` exactly) — same
  "runearm is the exclusive choice, never blended" rule as everywhere else.
- **Thrown** → Weapon1 unrestricted beyond the style's own three types (throwing
  dagger/axe/dart — none carry a DDOBuilderV2 damage-type classification, so there's
  nothing further to narrow by); Weapon2 is **always** specifically a Kama
  (`w2_list = ['kama']`, hard-required), itself subject to the same craftable-family
  + highest-ML + fallback treatment as Weapon1.
- **Shuriken** → Weapon1 restricted to `{shuriken}`; Weapon2 always a Kama, same as
  Thrown.
- **Tank** → a blanket override, not one more `weapon_style` branch: Weapon1 is
  always `{longsword}` and Weapon2 is always `{large shield}`, both hard-required
  and both subject to the craftable-family + highest-ML + fallback treatment,
  **regardless of whatever `weapon_style` is selected** in the UI (Tank shares
  Melee's `weapon_style` dropdown, but that field is ignored for weapon selection
  once `build_type == 'Tank'`).

Verified against real DDOBuilderV2 data: Tank → `Dinosaur Bone Longsword` +
`Dinosaur Bone Large Shield`; Bow → `Legendary Cataclysmic Longbow` (Weapon2 empty);
Thrown → `Legendary Cataclysmic Dart` + `Dinosaur Bone Kama`.

Nothing else about the existing tiered stat-priority search changes — this spec only
adds a floor under Weapon1/Weapon2, it doesn't change how everything else is scored.

## Related, tracked separately

- Review finding #1 (`augment_fits_slot` substring false-positives) and #2
  (`parse_augments` dropping pre-filled augments with no priority-matching buffs) are
  queued as session TODO items, independent of this spec.
- GitHub issue jorgec/ddogearset#1 ("Solver not restricting by packs") — root-caused
  during this review to an exact-string pack-name mismatch (`"The Chill of Ravenloft"`
  vs. the real `AdventurePack` value `"Chill of Ravenloft"`), compounded by
  `expansions.json` only listing 9 of the 66 real pack names. Not yet fixed.
- GitHub issue jorgec/ddogearset#2 (Lunar/Solar gems in Colorless slots) — likely the
  same root cause as review finding #1; re-check after #1 is fixed, deferred per
  explicit instruction.
