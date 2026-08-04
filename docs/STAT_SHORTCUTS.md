# Gearset Stat Shortcuts & Category Groups

**Purpose:** Logical stat groupings for UI drill-down selectors  
**Status:** Complete mapping of all documented stats  
**Date:** 2026-08-04

---

## TABLE OF CONTENTS

1. [Caster Stats](#caster-stats)
2. [Physical Damage Stats](#physical-damage-stats)
3. [Proc Mechanics (Secondary)](#proc-mechanics-secondary)
4. [Quick Reference by Build Type](#quick-reference-by-build-type)

---

## CASTER STATS

### 1. Spell Schools (Spell DC - Damage Class)

**Group Name:** `spell_schools`  
**Effect Type:** `SpellDC`  
**Usage:** Offensive spell penetration, spell resistance bypass

```
├─ Evocation
├─ Necromancy
├─ Enchantment
├─ Conjuration
├─ Divination
├─ Abjuration
├─ Transmutation
├─ Illusion
└─ All Schools (Universal)
```

**UI Pattern:**
```
[Spell Schools ▼]
├─ Evocation
├─ Necromancy
├─ Enchantment
├─ Conjuration
├─ Divination
├─ Abjuration
├─ Transmutation
└─ Illusion
```

**Stat Name Format:** `{school} spelldc`  
**Example:** "evocation spelldc", "necromancy spelldc"

---

### 2. Elemental Categories (Spell Lore - Critical Chance)

**Group Name:** `spell_lore_elements`  
**Effect Type:** `SpellLore`  
**Usage:** Spell critical hit chance % (damage type-specific)

```
├─ Fire
├─ Electric (Lightning)
├─ Cold (Ice/Glaciation)
├─ Acid
├─ Sonic
├─ Force
├─ Poison
├─ Positive (Healing)
├─ Negative (Void/Necromantic)
└─ All Elements (Universal)
```

**UI Pattern:**
```
[Spell Lore ▼]
├─ Fire
├─ Electric
├─ Cold
├─ Acid
├─ Sonic
├─ Force
├─ Poison
├─ Positive
├─ Negative
└─ Universal
```

**Stat Name Format:** `{element} spelllore`  
**Example:** "fire spelllore", "cold spelllore"

---

### 3. Spell Critical Damage (Crit Multiplier by Element)

**Group Name:** `spell_critical_damage`  
**Effect Type:** `SpellCriticalDamage`  
**Usage:** Multiplier on critical hits (same elements as Spell Lore)

```
├─ Fire
├─ Electric
├─ Cold
├─ Acid
├─ Sonic
├─ Force
├─ Poison
├─ Positive
├─ Negative
└─ All Elements
```

**UI Pattern:**
```
[Spell Critical Damage ▼]
├─ Fire
├─ Electric
├─ Cold
├─ Acid
├─ Sonic
├─ Force
├─ Poison
├─ Positive
├─ Negative
└─ Universal
```

**Stat Name Format:** `{element} spellcriticaldamage`  
**Example:** "fire spellcriticaldamage"  
**Amount Format:** Decimal multiplier (0.25 = +25%)

---

### 4. Spellpower (Spell Damage Scaling - COMPREHENSIVE)

**Group Name:** `spellpower`  
**Effect Type:** `SpellPower`  
**Usage:** Primary damage scaling for spells

#### 4.1 Elemental Spellpower

```
├─ Fire (Combustion)
├─ Electric (Magnetism/Lightning)
├─ Cold (Glaciation/Ice)
├─ Acid (Corrosion)
├─ Sonic (Resonance)
├─ Force (Kinetic)
├─ Poison
├─ Positive (Devotion/Healing)
└─ Negative (Nullification/Void)
```

#### 4.2 Alignment/Ethical Spellpower

```
├─ Good
├─ Evil
├─ Lawful
├─ Chaos
└─ Light/Alignment (Radiance - combines Good/Lawful/Chaos)
```

#### 4.3 Utility Spellpower

```
├─ Repair (healing spells)
├─ Rust (anti-construct)
└─ Physical
```

#### 4.4 Compound/Multi-Element Spellpower

**Note:** Single augment provides bonus to MULTIPLE elements

```
Radiance Bonus:
  ├─ Light/Alignment
  └─ Chaos

Reconstruction Bonus:
  ├─ Repair
  └─ Rust

Impulse Bonus:
  ├─ Force
  └─ Physical
```

#### 4.5 Universal Spellpower

```
└─ All (applies to all categories)
```

**Full UI Pattern:**
```
[Spellpower ▼]
├─ Elemental
│  ├─ Fire
│  ├─ Electric
│  ├─ Cold
│  ├─ Acid
│  ├─ Sonic
│  ├─ Force
│  ├─ Poison
│  ├─ Positive
│  └─ Negative
│
├─ Alignment
│  ├─ Good
│  ├─ Evil
│  ├─ Lawful
│  ├─ Chaos
│  └─ Light/Alignment
│
├─ Utility
│  ├─ Repair
│  ├─ Rust
│  └─ Physical
│
├─ Compound (Multi-Element)
│  ├─ Radiance (Light/Alignment + Chaos)
│  ├─ Reconstruction (Repair + Rust)
│  └─ Impulse (Force + Physical)
│
└─ Universal
   └─ All (all categories)
```

**Stat Name Format:** `{category} spellpower`  
**Example:** "fire spellpower", "good spellpower", "repair spellpower"

---

### 5. Spell Points (Casting Resource Pool)

**Group Name:** `spell_points`  
**Effect Type:** `SpellPoints`  
**Usage:** Mana equivalent resource pool  
**Note:** Less critical for DPS optimization

**Stat Name Format:** `spell points` or `elemental spell power` (bonus type descriptor)

---

### 6. Warlock-Specific: Eldritch Blast Dice

**Group Name:** `warlock_scaling`  
**Effect Type:** `EldritchBlastD6` (or `EldritchBlastD8`)  
**Usage:** Pact dice scaling for Eldritch Blast cantrip

```
└─ Pact Dice
   ├─ d6 Dice Bonus (EldritchBlastD6)
   └─ d8 Dice Bonus (EldritchBlastD8)
```

**UI Pattern:**
```
[Warlock Scaling ▼]
├─ Pact Dice (d6)
└─ Pact Dice (d8)
```

**Stat Name Format:** `eldritch blast dice` or `pact dice`  
**Amount Format:** Number of dice added (e.g., 1 = +1d6)

**Note:** Warlock exception - use this INSTEAD of traditional spellpower stats

---

### 7. Caster Level Boosters (Undocumented)

**Group Name:** `caster_level_boosts`  
**Status:** Undocumented in XML (tracked via description keywords)  
**Usage:** Boosts effective caster level for leveled spells

```
├─ Fire Caster Level (Improved Fire Augmentation)
├─ Cold Caster Level (Improved Cold Augmentation)
├─ Electric Caster Level (Improved Air Augmentation)
└─ Acid Caster Level (Improved Acid Augmentation)
```

**UI Pattern:**
```
[Caster Level ▼]
├─ Fire Spells
├─ Cold Spells
├─ Electric Spells
└─ Acid Spells
```

**Note:** Applies to "ninth level or lower" spells only (undocumented cap)

---

## PHYSICAL DAMAGE STATS

### 1. Power Stats (Damage Scaling)

**Group Name:** `power_stats`  
**Effect Types:** `MeleePower`, `RangedPower`  
**Usage:** Primary damage output scaling

```
├─ Melee Power
└─ Ranged Power
```

**UI Pattern:**
```
[Power ▼]
├─ Melee Power
└─ Ranged Power
```

**Stat Name Format:** `melee power`, `ranged power`  
**Build Filtering:** Melee builds get Melee Power; Ranged gets Ranged Power

---

### 2. Attack Speed (Alacrity)

**Group Name:** `alacrity`  
**Effect Type:** `WeaponAlacrityClass`  
**Usage:** Attack speed modifier (% faster)

```
├─ Melee Alacrity
└─ Ranged Alacrity
```

**UI Pattern:**
```
[Attack Speed ▼]
├─ Melee Alacrity
└─ Ranged Alacrity
```

**Stat Name Format:** `melee alacrity`, `ranged alacrity`  
**Amount Format:** Percentage (15 = 15% faster)

---

### 3. Double Attack Mechanics

**Group Name:** `double_attacks`  
**Effect Types:** `Doublestrike` (melee), `Doubleshot` (ranged)  
**Usage:** Chance to perform automatic extra attack

```
├─ Doublestrike (Melee)
└─ Doubleshot (Ranged)
```

**UI Pattern:**
```
[Double Attacks ▼]
├─ Melee Doublestrike
└─ Ranged Doubleshot
```

**Stat Name Format:** `doublestrike`, `doubleshot`  
**Amount Format:** Percentage as integer (17 = 17% chance)

---

### 4. Critical Hit Mechanics

**Group Name:** `critical_mechanics`

#### 4.1 Seeker (Attack & Damage Bonus on Crit)

**Effect Type:** `Weapon_AttackAndDamageCritical`

```
└─ Seeker (All Weapons)
```

**Stat Name Format:** `seeker`  
**Usage:** Bonus to both attack roll AND damage roll on critical

---

### 5. Armor Piercing (Fortification Bypass)

**Group Name:** `armor_piercing`  
**Effect Type:** `ArmorPiercing`  
**Usage:** Chance to bypass enemy Fortification

```
└─ Armor Piercing
```

**UI Pattern:**
```
[Armor Piercing]
└─ Armor Piercing %
```

**Stat Name Format:** `armor piercing`  
**Amount Format:** Percentage bypass chance

---

### 6. Combat Style & Weapon Proficiency

**Group Name:** `combat_styles`  
**Source:** WeaponGroupings.xml categories  
**Usage:** Build-type filtering + specialized bonuses

```
├─ One Handed
├─ Two Handed
├─ Dual Wield (Two Weapon)
├─ Light Weapons
├─ Finesseable (DEX-based)
├─ Centered (Monk-style)
├─ Swashbuckling (light off-hand penalty reduction)
│
├─ Weapon Types
│  ├─ Bow
│  ├─ Crossbow
│  ├─ Repeating Crossbow
│  ├─ Axe
│  └─ Shield
│
└─ Proficiency Levels
   ├─ Martial
   ├─ Simple
   └─ Exotic
```

**UI Pattern:**
```
[Combat Styles ▼]
├─ Grip Styles
│  ├─ One Handed
│  ├─ Two Handed
│  └─ Dual Wield
│
├─ Weapon Sizes
│  ├─ Light
│  ├─ Finesseable
│  └─ Centered
│
├─ Specialized
│  ├─ Swashbuckling
│  └─ Bow Specialization
│
└─ Proficiency
   ├─ Martial
   ├─ Simple
   └─ Exotic
```

**Note:** These filter augments by type, not direct stat selection

---

### 7. Two-Weapon Fighting Mechanics

**Group Name:** `two_weapon_mechanics`  
**Effect Type:** `OffHandAttackBonus`  
**Usage:** Reduces off-hand penalty for dual-wield builds

```
└─ Off-Hand Attack Bonus
```

**Stat Name Format:** `offhand attack bonus`  
**Usage:** Counteracts two-weapon fighting penalty (-6 typically)

---

### 8. Weapon Base Damage (Properties, Not Stats)

**Group Name:** `weapon_properties`  
**Note:** These are weapon properties, not augment stats  
**Usage:** Informational only (affects augment selection, not stat priorities)

```
├─ Base Damage Rating ([W] notation)
│  └─ Modified by player stats, not directly optimizable
│
├─ Weapon Critical Profile (e.g., 19-20x3)
│  ├─ Critical Range
│  └─ Critical Multiplier
│
└─ Elasticity (Conditional Crit Boost)
   └─ On roll 19-20, crit multiplier +1
```

---

## PROC MECHANICS (SECONDARY)

**Note:** Procs are secondary/probabilistic stats, not primary optimization targets

### 1. On-Hit Damage Procs (Weapon Scaling)

**Group Name:** `onhit_damage_procs`  
**Trigger:** Physical attack connects  
**Examples:** Flamescale (15d6 Fire), Touch of Flames

```
├─ Fire Procs
│  ├─ Magma Surge Guard
│  ├─ Flamescale (15d6)
│  └─ Minor Fire Guard (50% 1d4)
│
├─ Cold Procs
│  ├─ Ice Shards Guard
│  ├─ Icescale (15d6)
│  └─ Minor Ice Guard (50% 1d4)
│
├─ Electric Procs
│  ├─ Lightning Storm Guard
│  ├─ Sparkscale (15d6)
│  └─ Minor Lightning Guard (50% 1d4)
│
└─ Acid Procs
   ├─ Earthgrab Guard
   ├─ MeltScale (15d6)
   └─ Minor Acid Guard (50% 1d4)
```

**UI Pattern:**
```
[On-Hit Damage ▼]
├─ Fire (5 procs)
├─ Cold (5 procs)
├─ Electric (5 procs)
└─ Acid (5 procs)
```

---

### 2. On-Being-Hit Procs (Defensive/Reactive)

**Group Name:** `onbeinghit_procs`  
**Trigger:** Character takes damage  
**Status:** Undocumented mechanics  
**Examples:** Guard series (50% chance reactive damage)

```
├─ Fire Guard (50% 1d4 Fire on being hit)
├─ Cold Guard (50% 1d4 Cold on being hit)
├─ Electric Guard (50% 1d4 Electric on being hit)
└─ Acid Guard (50% 1d4 Acid on being hit)
```

**Note:** Primarily defensive use, low damage contribution

---

### 3. Dual-Purpose Procs (Attacks + Spells)

**Group Name:** `dual_purpose_procs`  
**Trigger:** Both physical attacks AND spell casts  
**Examples:** Alchemical Attunements, Woeful series

#### 3.1 Alchemical Attunements

```
├─ Fire Attunement (attacks & spells → Fire damage)
├─ Water Attunement (attacks & spells → Cold damage)
├─ Air Attunement (attacks & spells → Electric damage)
└─ Earth Attunement (attacks & spells → Acid damage)
```

#### 3.2 Woeful Crowd Control Procs

```
├─ Woeful Flames (MRR reduction)
├─ Woeful Chill (Freeze effect)
├─ Woeful Sparks (Vulnerability stacking)
├─ Woeful Acid (PRR reduction)
├─ Woeful Dimlight (Temporary HP grant)
└─ Woeful Shadows (Combined resistance reduction)
```

#### 3.3 Sealed in Fire (Offensive Debuffs)

```
├─ Magical Resistance Reduction
├─ Vulnerability Application
└─ Damage Amplification
```

**UI Pattern:**
```
[Dual-Purpose Procs ▼]
├─ Element-Based
│  ├─ Fire Attunement
│  ├─ Cold Attunement
│  ├─ Electric Attunement
│  └─ Acid Attunement
│
└─ Status Effects
   ├─ Freeze
   ├─ Vulnerability
   ├─ Resistance Reduction
   └─ Healing/Buffs
```

---

### 4. Activatable Abilities (Manual Triggers)

**Group Name:** `activatable_abilities`  
**Trigger:** Player manually activates (X uses per rest)  
**Examples:** Dragon Breath abilities  
**Implementation:** `SpellLikeAbility` effect type

```
├─ Acid Storm (Black Dragon Breath)
├─ Ice Storm (White Dragon Breath)
├─ Fire Storm (Red Dragon Breath)
└─ Lightning Storm (Blue Dragon Breath)
```

**Properties per ability:**
- Damage: 1d15 + 15 per caster level
- Uses: 3 per rest
- Scaling: Caster level 30
- Save: Reflex for half

**UI Pattern:**
```
[Activatable Abilities ▼]
├─ Dragon Breath (Tier 3)
│  ├─ Acid Storm
│  ├─ Ice Storm
│  ├─ Fire Storm
│  └─ Lightning Storm
│
└─ Other Abilities (if added)
```

---

### 5. Status Effects & Crowd Control

**Group Name:** `status_effect_procs`  
**Undocumented mechanics** — tracked via description keywords

```
├─ Freeze/Stun (Woeful Chill)
├─ Vulnerability (Woeful Sparks, 1st Degree Burns)
├─ Slow (Woeful Salt, Black Sands' Desire)
├─ Blindness (Blinding Fear)
├─ Hamstring (Tendon Slice)
└─ Buff/Healing (Woeful Dimlight → 1,000 temp HP)
```

**Note:** These are secondary effects, primarily tracked as descriptive attributes

---

## QUICK REFERENCE BY BUILD TYPE

### Spell Caster (Default Spell Build)

**Primary Stats:**
1. Spellpower (by element - choose 1-3 main elements)
2. Spell DC (by school - choose 1-3 main schools)
3. Spell Lore (by element - supports crit scaling)
4. Spell Critical Damage (by element - damage multiplier)

**Secondary Stats:**
1. Spell Points (resource pool - optional)
2. Caster Level Boosters (undocumented - optional)

**Procs:**
1. Dual-Purpose (Attunements, Woeful series)
2. Activatable Abilities (Dragon Breath)

**Build Example:**
```
Priority Selection:
├─ fire spellpower [200]
├─ evocation spelldc [+6]
├─ fire spelllore [+6]
├─ fire spellcriticaldamage [+0.25]
└─ [Optional] fire caster level boost
```

---

### Warlock (Eldritch Blast Build)

**Primary Stats:**
1. Eldritch Blast Dice (Pact Dice - d6/d8)
2. Spell Lore (for invocation crit scaling)
3. Spell Critical Damage (for invocation crit)

**Secondary Stats:**
1. Spellpower (for personal buff spells only)
2. Spell Points (resource pool)

**Note:** DO NOT use traditional spell DC or elemental spellpower

**Build Example:**
```
Priority Selection:
├─ pact dice [+3d6]
├─ fire spelllore [+6]
├─ fire spellcriticaldamage [+0.25]
└─ [Optional] fire spellpower [100]
```

---

### Melee Physical Build

**Primary Stats:**
1. Melee Power [primary scaling]
2. Doublestrike [attack frequency]
3. Armor Piercing [utility]
4. Seeker [critical scaling]

**Secondary Stats:**
1. Melee Alacrity [attack speed]
2. Off-Hand Attack Bonus [if dual-wield]

**Combat Style Filtering:**
- One Handed OR Two Handed OR Dual Wield
- Martial proficiency (default)

**Procs:**
1. On-Hit Damage (Fire/Cold/Electric/Acid)
2. Dual-Purpose (Attunements)

**Build Example:**
```
Priority Selection:
├─ melee power [primary]
├─ doublestrike [17%]
├─ armor piercing [chance]
├─ seeker [+5]
└─ [Optional] melee alacrity [15%]
```

---

### Ranged Physical Build

**Primary Stats:**
1. Ranged Power [primary scaling]
2. Doubleshot [attack frequency]
3. Armor Piercing [utility]
4. Seeker [critical scaling]

**Secondary Stats:**
1. Ranged Alacrity [attack speed]

**Combat Style Filtering:**
- Bow OR Crossbow OR Repeating Crossbow
- Martial proficiency (default)

**Procs:**
1. On-Hit Damage (Fire/Cold/Electric/Acid)
2. Dual-Purpose (Attunements)

**Build Example:**
```
Priority Selection:
├─ ranged power [primary]
├─ doubleshot [17%]
├─ armor piercing [chance]
├─ seeker [+5]
└─ [Optional] ranged alacrity [20%]
```

---

### Unarmed/Monk Build

**Primary Stats:**
1. Melee Power [primary scaling]
2. Doublestrike [attack frequency]
3. Seeker [critical scaling]

**Combat Style Filtering:**
- Centered (Monk-specific)
- Unarmed proficiency

**Build Example:**
```
Priority Selection:
├─ melee power [primary]
├─ doublestrike [unarmed bonus]
└─ seeker [+5]
```

---

### Mixed Damage Build (Attack + Spell)

**Approach:** Use dual-purpose procs to benefit from both

**Primary Stats:**
1. Melee/Ranged Power OR Spellpower (choose dominant)
2. Doublestrike/Doubleshot (for attack side)
3. Spell DC + Spell Lore (for spell side)

**Key Procs:**
1. Dual-Purpose Attunements (Fire/Cold/Electric/Acid)
2. Woeful Series (crowd control benefits both)

**Build Example:**
```
Priority Selection:
├─ melee power [primary]
├─ fire spellpower [secondary - benefits dual procs]
├─ doublestrike [attack scaling]
├─ evocation spelldc [spell scaling]
└─ fire attunement [dual-purpose]
```

---

## IMPLEMENTATION NOTES

### UI Drill-Down Structure

**Level 1 - Build Type Selection:**
```
[Select Build Type]
├─ Spell Caster
├─ Warlock
├─ Melee Fighter
├─ Ranged Attacker
├─ Unarmed/Monk
└─ Mixed Build
```

**Level 2 - Category Selection (Context-Sensitive):**
```
For "Spell Caster":
├─ [Spellpower ▼] → Element/Category sub-menu
├─ [Spell Schools ▼] → School list
├─ [Spell Lore ▼] → Element list
├─ [Spell Critical Damage ▼] → Element list
├─ [Procs ▼] → Dual-purpose/Activatable
└─ [Advanced ▼] → Caster Level, Spell Points
```

**Level 3 - Stat Selection:**
```
Select element/school → Get matching stat name
(e.g., Fire Spellpower → "fire spellpower")
```

### Stat Name Normalization

**Format Rules:**
- All lowercase
- Spaces between components
- Component order: [modifier] [element/school] [stat type]

**Examples:**
- `fire spellpower`
- `evocation spelldc`
- `melee power`
- `doublestrike`
- `pact dice`
- `armor piercing`

### Parser Matching Strategy

```python
stat_shortcuts = {
    "fire spellpower": {
        "xml_type": "SpellPower",
        "xml_item": "Fire",
        "documented": True
    },
    "fire spelllore": {
        "xml_type": "SpellLore",
        "xml_item": "Fire",
        "documented": True
    },
    # ... etc
}
```

---

## VALIDATION CHECKLIST

- [ ] All documented stat types included
- [ ] Logical groupings by function (not just alphabetical)
- [ ] Compound effects (multi-element bonuses) called out
- [ ] Undocumented mechanics flagged clearly
- [ ] Build-type context reflected in shortcuts
- [ ] UI drill-down structure is 3 levels max
- [ ] Stat name format consistent throughout
- [ ] Proc categories separate from core stats
- [ ] Warlock build correctly excludes traditional caster stats
- [ ] Combat style filtering relevant to physical builds
