# DDOBuilder XML Mapping: Physical Damage Stats

**Analysis Date:** 2026-08-04  
**Data Source:** DDOBuilder XML files (Augments, Items, Weapons)  
**Status:** Complete mapping for melee/ranged power, critical mechanics, and attack speed

---

## 1. Melee Power & Ranged Power

### Build Type Structure
Physical damage is categorized by build type at the effect level:

```xml
<Effect>
  <Type>MeleePower</Type>          <!-- or RangedPower -->
  <Bonus>Equipment</Bonus>         <!-- Enhancement, Insightful, Fortune, Mythic, etc. -->
  <AType>Simple</AType>
  <Amount size="1">152</Amount>     <!-- Power value (damage scaling) -->
</Effect>
```

### Valid Bonus Types
- `Enhancement` (most common)
- `Insightful`
- `Exceptional`
- `Fortune`
- `Mythic`
- `Profane`

### Build Types (Augment Categories)
Augments are categorized by weapon type at the Augment level via `<Type>` tags:
- `Cannith Melee Prefix/Suffix/Extra` — All melee weapons
- `Cannith Ranged Prefix/Suffix/Extra` — All ranged weapons (bows, crossbows)
- `Cannith Thrown Prefix/Suffix/Extra` — Thrown weapons
- `Cannith Weapon Prefix/Suffix` — Universal (all weapon types)
- `Cannith Handwraps Prefix` — Unarmed combat
- `Cannith Shield *` — Shield-specific

### Parsing Keywords
- **XML Type (Effect):** `MeleePower` or `RangedPower`
- **XML Type (Augment Category):** Determines which weapon types can accept the augment
- **Bonus Field:** Contains bonus type
- **Amount Field:** Contains the power value
- **Item Field:** Usually empty or "All"

### UI Mapping
- "Melee Power" → searches for `Type=MeleePower`
- "Ranged Power" → searches for `Type=RangedPower`
- UI should filter augments based on selected build type (melee vs ranged)

---

## 2. Doubleshot & Doublestrike

### Critical Distinction
- **Doublestrike:** Melee weapons - chance to attack twice in one attack cycle
- **Doubleshot:** Ranged weapons - same concept for ranged

### XML Structure
```xml
<Effect>
  <Type>Doublestrike</Type>         <!-- or Doubleshot -->
  <Bonus>Enhancement</Bonus>        <!-- Enhancement, Insightful, Profane, etc. -->
  <AType>Simple</AType>
  <Amount size="1">17</Amount>       <!-- Percentage chance (e.g., 17%) -->
</Effect>
```

### Valid Bonus Types
- `Enhancement`
- `Insightful`
- `Fortune`
- `Profane`

### Parsing Keywords
- **XML Type:** `Doublestrike` or `Doubleshot`
- **Amount Field:** Percentage as integer (e.g., 17 = 17%)
- **Item Field:** Usually empty or "All"

### Example from Alchemical Augments
```
Doublestrike +13%: +13% Enhancement bonus to Doublestrike chance.
<Type>Doublestrike</Type>
<Bonus>Enhancement</Bonus>
<Amount>13</Amount>
```

### UI Mapping
- "Doublestrike" → searches for `Type=Doublestrike`
- "Doubleshot" → searches for `Type=Doubleshot`

---

## 3. Armor Piercing (Fortification Bypass)

### Concept
Armor Piercing grants a chance to bypass enemy Fortification (damage reduction from heavy armor). It increases your physical attacks' ability to penetrate armor.

### XML Structure
```xml
<Effect>
  <Type>ArmorPiercing</Type>
  <Bonus>Equipment</Bonus>
  <AType>Simple</AType>
  <Amount size="1">20</Amount>       <!-- Percentage bypass chance -->
</Effect>
```

### Parsing Keywords
- **XML Type:** `ArmorPiercing`
- **Amount Field:** Percentage chance (e.g., 20%)
- **Item Field:** Usually empty

### Example Description
"Your physical attacks gain an Equipment bonus to bypass enemy Fortification"

### UI Mapping
- "Armor Piercing" → searches for `Type=ArmorPiercing`

---

## 4. Seeker (Critical Hit Bonus)

### Concept
Seeker provides a bonus to BOTH:
1. Confirming critical hits (d20 bonus to confirm roll)
2. Critical hit damage (bonus damage before multipliers applied)

### XML Structure
**Note:** Seeker appears to use `Weapon_AttackAndDamageCritical` type in some contexts:

```xml
<Effect>
  <Type>Weapon_AttackAndDamageCritical</Type>
  <Bonus>Enhancement</Bonus>
  <AType>Simple</AType>
  <Amount size="1">15</Amount>       <!-- Bonus to both attack and damage crits -->
  <Item>All</Item>
</Effect>
```

### Parsing Keywords
- **XML Type:** `Weapon_AttackAndDamageCritical` (dual-purpose critical bonus)
- **Amount Field:** Bonus value (applied before multipliers)
- **Item Field:** Usually "All" or specific weapon type
- **Description:** Mentions both "confirm critical hits" and "critical hit damage"

### Example
```
Seeker +10: Provides a +10 Enhancement bonus to confirm critical hits, and a
+10 Enhancement bonus to critical hit damage (before multipliers are applied).
```

---

## 5. Critical Damage & Multipliers

### Concept
Critical damage has multiple components in DDO:
1. **Base Critical Multiplier:** Inherent to weapon (e.g., x2, x3, x4)
2. **Critical Range Expansion:** Increases crit range (e.g., 19-20 becomes 18-20)
3. **Seeker Bonus:** Flat damage added before multiplier
4. **Elasticity:** Increases multiplier by 1 on crits (with restrictions)

### Weapon Critical Profile (Static Properties)
Weapon critical profiles are typically stored in weapon data as:
- **Crit Range:** Base range on d20 (e.g., 19-20, 18-20)
- **Crit Multiplier:** Damage multiplier (e.g., x2, x3, x4)
- **Example:** "19-20x3" = rolls 19-20 are criticals, damage multiplied by 3

**Note:** Weapon critical profiles may not be modified by augments; they're weapon-specific properties defined in the weapon's base stats.

### Critical-Related XML Types Found
- `Weapon_AttackAndDamageCritical` — Dual bonus to attack roll and damage criticals
- `Weapon_AttackCritical` — Bonus to attack roll only for criticals
- `Weapon_DamageCritical` — Bonus to damage crit rolls only
- `WeaponOtherDamageBonusCritical` — Additional critical damage bonus
- `Strikethrough` — Related to critical mechanics

### Structure Example
```xml
<Effect>
  <Type>Weapon_AttackAndDamageCritical</Type>
  <Bonus>Enhancement</Bonus>
  <AType>Simple</AType>
  <Amount size="1">15</Amount>
  <Item>All</Item>
</Effect>
```

---

## 6. Melee & Ranged Alacrity (Attack Speed)

### Concept
Alacrity increases attack speed in combat:
- **Melee Alacrity:** Faster melee attack cycles
- **Ranged Alacrity:** Faster ranged attack cycles (reload/draw speed)

### XML Structure
```xml
<Effect>
  <Type>WeaponAlacrityClass</Type>
  <Bonus>Enhancement</Bonus>
  <AType>Simple</AType>
  <Amount size="1">15</Amount>        <!-- Percentage increase (e.g., 15%) -->
  <Item>Melee</Item>                 <!-- or Ranged -->
</Effect>
```

### Valid Item Values
- `Melee` — Melee alacrity
- `Ranged` — Ranged alacrity

### Parsing Keywords
- **XML Type:** `WeaponAlacrityClass`
- **Item Field:** `Melee` or `Ranged`
- **Amount Field:** Percentage as integer (e.g., 15 = 15% faster)
- **Bonus Field:** Enhancement, Insightful, etc.

### Example
```
+15% Enhancement bonus to Melee Alacrity
<Type>WeaponAlacrityClass</Type>
<Item>Melee</Item>
<Amount>15</Amount>
```

---

## 7. Elasticity (Crit Multiplier Enhancement)

### Concept (Complex Mechanic)
Elasticity provides a conditional boost to critical multiplier:
- **When you roll 19 or 20** on a ranged attack, crit multiplier is **increased by +1**
- **Restrictions:**
  - Only applies on natural rolls of 19-20
  - Weapons with minimal crit range (crit on 20 only) get +5% base damage increase instead
  - Weapons with normal crit ranges (19-20 or better) get +10% base damage increase
  - Base damage rating does NOT include elasticity unless weapon has special note

### XML Structure
Elasticity likely uses a specialized type (not yet fully identified in search). Typically appears in weapon enhancement descriptions.

### Parsing Keywords
- **Look for:** Descriptions containing "Elasticity" or "crit multiplier +1"
- **Conditions:** References to "19 or 20", "damage rating increase", "+5%", "+10%"

### Note
Elasticity is a complex mechanic that may require special handling in the UI - it's not a simple linear stat but a conditional bonus dependent on crit range.

---

## 8. Weapon Base Damage Rating (Static Property)

### Concept
Base Damage Rating (BDR) is:
- An inherent property of weapons (melee and ranged)
- Calculated from weapon type, material, enhancements
- **Does NOT include:** Elasticity, specific stat bonuses
- Can be modified by certain augment effects
- Used in damage calculations along with power stats

### Storage
- Typically stored in weapon definition (Items)
- Modified by weapon enhancement level and material
- May be affected by certain enchantment types

### In Optimization
BDR is usually a static input per weapon, not dynamically modified by stat priority selection. The solver uses:
- **Weapon BDR** (fixed) × **Power stat** (variable) × **Crit multiplier** (if applicable) = Damage

---

## 9. Weapon Groupings & Combat Styles

### Combat Style Categories
Weapons in DDO are organized into multiple overlapping groupings that define combat styles and capabilities. These are defined in `WeaponGroupings.xml`:

#### **Weapon Hand/Slot Categories**
- **One Handed:** Single weapon wielding
  - Bastard Sword, Battle Axe, Club, Dagger, Dwarven Axe, Hand Axe, Heavy Mace, Heavy Pick, Kama, Khopesh, Kukri, Light Hammer, Light Mace, Light Pick, Longsword, Morningstar, Rapier, Scimitar, Shortsword, Sickle, Warhammer
- **Two Handed:** Two-hand grip
  - Falchion, Great Axe, Great Club, Great Sword, Maul, Quarterstaff
- **Light:** Light/finesseable one-handed weapons
  - Dagger, Shortsword, Light Pick, Light Hammer, Light Mace, Scimitar, Sickle, Hand Axe, Kukri

#### **Combat Style Categories**
- **Finesseable:** DEX-based combat capable
  - Dagger, Hand Axe, Handwraps, Kama, Kukri, Light Hammer, Light Mace, Light Pick, Rapier, Scimitar, Shortsword, Sickle, Unarmed
- **Centered:** Balance/stability combat (Monk-style)
  - Empty slot, Kama, Shuriken, Handwraps, Quarterstaff, Unarmed
- **Swashbuckling:** Dual-wield with small off-hand weapons
  - Dagger, Hand Axe, Kama, Kukri, Light Hammer, Light Mace, Light Pick, Rapier, Shortsword, Sickle, Unarmed, Dart, Shuriken, Throwing Axe, Throwing Dagger, Throwing Hammer
- **SwashbucklingOffhand:** Off-hand weapons for swashbuckling
  - Buckler, Empty

#### **Damage Type Categories**
- **Slashing:** Slash-type weapons
- **Bludgeoning:** Blunt-type weapons (includes Unarmed, Handwraps)
- **Piercing:** Piercing-type weapons

#### **Weapon Proficiency Groups**
- **Martial:** Standard martial weapons (swords, axes, bows, etc.)
- **Simple:** Simpler weapons (clubs, maces, crossbows, etc.)
- **Exotic:** Advanced weapons (bastard sword, handwraps, repeating crossbow, etc.)

#### **Specific Weapon Types**
- **Axe:** All axe variants (Hand Axe, Battle Axe, Great Axe, Dwarven Axe, Throwing Axe)
- **Bow:** Longbow, Shortbow
- **Crossbow:** Light, Heavy, Great Crossbow
- **RepeatingCrossbow:** Repeating Light/Heavy Crossbow
- **Shield:** Buckler, Small Shield, Large Shield, Tower Shield

#### **Ranged/Thrown Categories**
- **Ranged:** Bows and crossbows (not throwing weapons)
- **Thrown:** Weapons designed to be thrown
- **All Ranged:** All ranged weapons including thrown

### How Combat Styles Map to Augments

Currently, augments don't appear to have combat-style-specific effects in the available data. However, the infrastructure exists via:

1. **Augment Slot Categories** — Augments are placed on specific item types (Melee weapons, Ranged weapons, Thrown weapons)
2. **Alacrity Item Field** — Uses `<Item>Melee</Item>` or `<Item>Ranged</Item>` to differentiate
3. **Off-Hand Mechanics** — `OffHandAttackBonus` type for two-weapon fighting

### Future Consideration: Combat Style Affinity

Certain stats may eventually need combat-style awareness:
- **Two-Weapon (Dual Wield):** May have penalties/bonuses different from single weapon
- **Two-Handed:** Power scaling may differ from one-handed
- **Ranged:** Bows vs Crossbows may have different alacrity/attack profiles
- **Unarmed/Centered:** May have unique mechanics (Handwrap-specific, monk abilities)
- **Finesse:** May allow DEX-based damage instead of STR (handled by character stats, not here)

---

## 10. Summary: XML Keywords by Stat Type

| Stat Type | XML Type | Item Field | Amount | Augment Category | Purpose |
|-----------|----------|-----------|--------|------------------|---------|
| Melee Power | `MeleePower` | Empty/All | Power value | Melee Prefix/Suffix/Extra | Melee damage scaling |
| Ranged Power | `RangedPower` | Empty/All | Power value | Ranged Prefix/Suffix/Extra | Ranged damage scaling |
| Doublestrike | `Doublestrike` | Empty/All | Percentage | Melee Prefix/Suffix/Extra | Melee double attack chance |
| Doubleshot | `Doubleshot` | Empty/All | Percentage | Ranged Prefix/Suffix/Extra | Ranged double attack chance |
| Armor Piercing | `ArmorPiercing` | Empty | Percentage | Melee/Ranged Prefix | Fortification bypass |
| Seeker | `Weapon_AttackAndDamageCritical` | All | Bonus value | Universal/Melee/Ranged | Crit bonus (attack + damage) |
| Crit Bonus (Attack only) | `Weapon_AttackCritical` | All | Bonus value | Universal | Crit confirmation only |
| Crit Bonus (Damage only) | `Weapon_DamageCritical` | All | Bonus value | Universal | Crit damage only |
| Melee Alacrity | `WeaponAlacrityClass` | Melee | Percentage | Melee Prefix/Suffix | Melee attack speed |
| Ranged Alacrity | `WeaponAlacrityClass` | Ranged | Percentage | Ranged Prefix/Suffix | Ranged attack speed |
| Off-Hand Attack | `OffHandAttackBonus` | Empty | Bonus value | Melee Prefix | Two-weapon off-hand penalty reduction |

---

## 10. Data Files Containing Physical Stats

### Primary Augment Sources
- `DeckOfManyCurses.Augments.xml` — Melee Power, Ranged Power, Doublestrike, Doubleshot
- `Alchemical.Augments.xml` — Doublestrike, Doubleshot, Seeker, critical mechanics
- `CannithAndRandomItem.Augments.xml` — Armor Piercing, Seeker, Alacrity, Doubleshot/Doublestrike
- `DinosaurBone.Augments.xml` — Doublestrike, Doubleshot, Alacrity
- `Lamordia_Heroic.Augments.xml`, `Lamordia_Legendary.Augments.xml` — Alacrity variants
- `Mythic.Augments.xml` — Melee/Ranged Power with Mythic bonus

### Weapon Data
- Item files contain base weapon properties (crit range, crit multiplier, base damage rating)
- These are static weapon properties, not augment-modifiable

---

## 11. Implementation Notes for Parser

### Build Type Architecture

**Primary Build Types:**
- `melee` — Melee weapons (one-handed, two-handed, handwraps)
- `ranged` — Ranged weapons (bows, crossbows)
- `thrown` — Thrown weapons (darts, throwing axes, shurikens)
- `unarmed` — Unarmed combat (handwraps special case)

**Augment Filtering by Build Type:**
When user selects "Melee Power" as priority, parser should:
1. Search for `Type=MeleePower` effects
2. Filter augments by Augment Type tags: `Cannith Melee Prefix/Suffix`, `Cannith Weapon Prefix/Suffix` (universal)
3. Exclude ranged-specific augments like `Cannith Ranged Suffix`

### Normalization Rules Recommended
1. **Power Stats:**
   - Input: "Melee Power" → Normalized: "meleepower" → XML: `Type=MeleePower`
   - Input: "Ranged Power" → Normalized: "rangedpower" → XML: `Type=RangedPower`

2. **Double Attack:**
   - Input: "Doublestrike" → Normalized: "doublestrike" → XML: `Type=Doublestrike`
   - Input: "Doubleshot" → Normalized: "doubleshot" → XML: `Type=Doubleshot`

3. **Critical Bonuses:**
   - Input: "Seeker" → Normalized: "seeker" → XML: `Type=Weapon_AttackAndDamageCritical`
   - Input: "Critical Damage" → Normalized: "criticaldamage" → XML: `Type=Weapon_DamageCritical`

4. **Attack Speed:**
   - Input: "Melee Alacrity" → Normalized: "meleealacrity" → XML: `Type=WeaponAlacrityClass, Item=Melee`
   - Input: "Ranged Alacrity" → Normalized: "rangedalacrity" → XML: `Type=WeaponAlacrityClass, Item=Ranged`

5. **Two-Weapon:**
   - Input: "Off-Hand Attack Bonus" → Normalized: "offhandattack" → XML: `Type=OffHandAttackBonus`

### Combat Style Awareness (Future Enhancement)
While not currently implemented in augment effects, the following combat styles should be tracked:
- **Single Weapon:** Solo weapon (one-handed melee, ranged, thrown)
- **Two-Weapon/Dual Wield:** Two one-handed weapons or weapon + shield
- **Two-Handed:** Grip with both hands for increased power
- **Unarmed/Centered:** Monk-style, handwrap-based
- **Finesseable:** Can use DEX instead of STR (character stat interaction, not augment-level)

### Case Sensitivity
- XML `<Type>` values are **case-sensitive:** `MeleePower`, `WeaponAlacrityClass`, `OffHandAttackBonus`
- XML `<Item>` values are **case-sensitive:** `Melee`, `Ranged`, `All`
- Normalized stat names should be **lowercase**
- Augment category tags are **case-sensitive:** `Cannith Melee Prefix`, `Cannith Ranged Suffix`, etc.

---

## 12. Build Type & Combat Style Summary

### How to Use This for UI Implementation

**User Selects Build Type:**
1. **Melee:**
   - Show melee-specific priority stats (Melee Power, Doublestrike, Melee Alacrity, Seeker, etc.)
   - Filter augments to `Cannith Melee *` and `Cannith Weapon *` (universal)
   - Show optional combat style selection (Single Weapon, Two-Weapon, Two-Handed, Unarmed)

2. **Ranged:**
   - Show ranged-specific priority stats (Ranged Power, Doubleshot, Ranged Alacrity, Seeker, etc.)
   - Filter augments to `Cannith Ranged *` and `Cannith Weapon *` (universal)
   - Show weapon category options (Bow, Crossbow, Repeating Crossbow)

3. **Thrown:**
   - Show thrown-specific stats (Ranged Power applies, Doubleshot applies)
   - Filter augments to `Cannith Thrown *`

**User Selects Combat Style (Melee):**
1. **Single Weapon:** Standard one-handed or two-handed
2. **Two-Weapon/Dual Wield:** Show `OffHandAttackBonus` relevant stats, consider off-hand penalties
3. **Two-Handed:** Two-hand power bonuses
4. **Unarmed/Centered:** Handwrap-specific items, potential monk abilities

---

## 13. Known Unknowns & Future Investigation

- ⏳ **Elasticity:** Full XML structure not yet identified; may require special handling in damage calculations
- ⏳ **Critical Range Modifiers:** How are crit range expansions stored? (e.g., expanding 19-20 to 18-20)
- ⏳ **Weapon Base Damage Rating:** Fixed values on weapon items in `/Items/` directory - need verification
- ⏳ **Other Critical Types:** Full list of `Weapon_*Critical` types and their distinctions
- ⏳ **Other Bonus Types:** `Mythic`, `Profane`, `Fortune` - how are they weighted/stacked in calculations?
- ⏳ **Combat Style-Specific Effects:** Are there future combat style affinity bonuses?
- ⏳ **Off-Hand Mechanics:** Full structure of `OffHandAttackBonus` and two-weapon penalty reduction

---

## 14. Next Steps

1. ✅ **Core physical damage stats mapped** — Power, Alacrity, Doubleshot/Doublestrike
2. ✅ **Critical mechanics identified** — Seeker, Weapon critical bonus types
3. ✅ **Build type categorization** — Melee, Ranged, Thrown with augment filtering
4. ✅ **Combat style framework** — Identified weapon groupings and categories
5. ⏳ **Deep dive on complex mechanics** — Elasticity, crit range, weapon profiles
6. ⏳ **Bonus type stacking rules** — How different bonus types interact in calculations
7. ⏳ **UI implementation** — Priority reordering for physical builds, build type selector, combat style selector
