# DDOBuilder XML Mapping: Caster-Specific Stats

**Analysis Date:** 2026-08-04  
**Data Source:** DDOBuilder XML files (Augments, Items)  
**Status:** Complete mapping for spell schools, spellpower, spell lore, and spell critical damage

---

## 1. Spell Schools & Spell DC (Damage Class)

### XML Structure
All spell school DCs use the `SpellDC` effect type:

```xml
<Effect>
  <Type>SpellDC</Type>
  <Bonus>Equipment</Bonus>          <!-- or Insightful, Enhancement, etc. -->
  <AType>Simple</AType>
  <Amount size="1">6</Amount>        <!-- The DC bonus value -->
  <Item>Evocation</Item>            <!-- School name -->
</Effect>
```

### Valid School Names (in XML `<Item>` field)
- `Evocation`
- `Necromancy`
- `Enchantment`
- `Conjuration`
- `Divination`
- `Abjuration`
- `Transmutation`
- `Illusion`
- `All` (applies to all schools)

### Parsing Keywords
- **XML Type:** `SpellDC`
- **Priority Field:** `<Item>` contains the school name
- **Amount Field:** `<Amount>` contains the DC bonus
- **Bonus Type Field:** `<Bonus>` contains the bonus type (Equipment, Insightful, Enhancement, etc.)

### UI Mapping
When user selects "Evocation" as a priority stat:
- Parser extracts "Evocation" → searches for `Type=SpellDC` with `Item=Evocation`
- Normalized stat name: "evocation spelldc" or "evocation dc"

---

## 2. Spell Lore (Spell Critical Chance)

### XML Structure
All spell lore effects use the `SpellLore` type:

```xml
<Effect>
  <Type>SpellLore</Type>
  <Bonus>Equipment</Bonus>
  <AType>Simple</AType>
  <Amount size="1">6</Amount>        <!-- Critical chance percentage -->
  <Item>Fire</Item>                 <!-- Element name -->
</Effect>
```

### Valid Element Names (in XML `<Item>` field)
- `Fire`
- `Electric` (Lightning)
- `Cold` (Ice)
- `Acid`
- `Negative` (Void/Negative energy)
- `Poison`
- `Positive` (Positive energy)
- `Force`
- `Sonic`

**Note:** Some elements can have multiple names:
- Cold = Ice
- Electric = Lightning
- Negative = Void

### Parsing Keywords
- **XML Type:** `SpellLore`
- **Priority Field:** `<Item>` contains the element name
- **Amount Field:** `<Amount>` contains the critical chance percentage
- **Bonus Type Field:** `<Bonus>` contains bonus type

### Example in Greensteel Augments
```xml
<Name>Fire Lore III</Name>
<Description>Fire Lore III: Passive: Your Fire spells gain a 6% Equipment bonus 
to their chance to critical hit and a 0.25 spell critical damage bonus.</Description>
<Effect>
  <Type>SpellLore</Type>
  <Bonus>Equipment</Bonus>
  <Item>Fire</Item>
  <Amount>6</Amount>
</Effect>
```

### UI Mapping
When user selects "Fire Lore" as a priority stat:
- Parser extracts "Fire" → searches for `Type=SpellLore` with `Item=Fire`
- Normalized stat name: "fire spelllore"

---

## 3. Spell Critical Damage Multiplier

### XML Structure
Spell critical damage uses the `SpellCriticalDamage` type:

```xml
<Effect>
  <Type>SpellCriticalDamage</Type>
  <Bonus>Equipment</Bonus>
  <AType>Simple</AType>
  <Amount size="1">0.25</Amount>     <!-- Damage multiplier (e.g., 0.25 = +25%) -->
  <Item>Fire</Item>                 <!-- Element name -->
</Effect>
```

### Valid Element Names
Same as SpellLore:
- `Fire`, `Electric`, `Cold`, `Acid`, `Negative`, `Poison`, `Positive`, `Force`, `Sonic`

### Parsing Keywords
- **XML Type:** `SpellCriticalDamage`
- **Priority Field:** `<Item>` contains the element name
- **Amount Field:** `<Amount>` contains the damage multiplier
- **Bonus Type Field:** `<Bonus>` contains bonus type

### Example in Greensteel Augments
```xml
<Effect>
  <Type>SpellCriticalDamage</Type>
  <Bonus>Equipment</Bonus>
  <Item>Fire</Item>
  <Amount>0.25</Amount>
</Effect>
```

### UI Mapping
When user selects "Fire Spell Critical Damage" as a priority stat:
- Parser extracts "Fire" → searches for `Type=SpellCriticalDamage` with `Item=Fire`
- Normalized stat name: "fire spellcriticaldamage"

---

## 4. Spellpower by Element/Category

### Critical Distinction
- **SpellPower** (`<Type>SpellPower</Type>`) = Spell damage/effectiveness scaling stat
- **SpellPoints** (`<Type>SpellPoints</Type>`) = Casting resource pool (mana equivalent)

This mapping covers **SpellPower** only.

### XML Structure - Spellpower (Element/Category Specific)
Unlike Spell Points (resource pool), actual Spellpower stats are **element and category specific**:

```xml
<Effect>
  <Type>SpellPower</Type>
  <Bonus>Equipment</Bonus>           <!-- or Insightful, Enhancement, etc. -->
  <AType>Simple</AType>
  <Amount size="1">152</Amount>      <!-- The spellpower value -->
  <Item>Fire</Item>                 <!-- Element/category name -->
</Effect>
```

### Valid Spellpower Categories (in XML `<Item>` field)

**Elemental/Damage Types:**
- `Fire` (Combustion)
- `Electric` (Lightning)
- `Cold` (Glaciation/Ice)
- `Acid`
- `Sonic`
- `Force`
- `Poison`
- `Negative` (Void)
- `Positive`

**Alignment Types:**
- `Good`
- `Evil`
- `Lawful`
- `Chaos`
- `Light/Alignment` (combined alignment bonus)

**Utility Types:**
- `Repair`
- `Rust`

**General:**
- `Physical`
- `Untyped`
- `All` (applies to all spellpower categories)

### Parsing Keywords
- **XML Type:** `SpellPower` (**NOT** SpellPoints)
- **Priority Field:** `<Item>` contains the category name (e.g., Fire, Cold, Physical)
- **Amount Field:** `<Amount>` contains the spellpower value (e.g., 152)
- **Bonus Type Field:** `<Bonus>` contains bonus type (Equipment, Insightful, Enhancement, etc.)

### Key Difference from SpellPoints
- `<Type>SpellPower</Type>` = Spell damage/effectiveness (what casters care about)
- `<Type>SpellPoints</Type>` = Casting resource pool (spell point bonuses, less relevant for optimization)

### UI Mapping
When user selects "Fire Spellpower" as a priority stat:
- Parser extracts "Fire" → searches for `Type=SpellPower` with `Item=Fire`
- Normalized stat name: "fire spellpower"

---

## 5. Eldritch Blast & Pact Dice (Warlock-Specific)

### Concept
Eldritch Blast is a Warlock cantrip that scales with **Pact Dice** instead of traditional spellpower. It's the primary damage scaling for Warlocks.

### XML Structure
```xml
<Effect>
  <Type>EldritchBlastD6</Type>
  <Bonus>Fortune</Bonus>           <!-- or Profane, Artifact, etc. -->
  <AType>Simple</AType>
  <Amount size="1">1</Amount>       <!-- Number of d6 dice to add -->
</Effect>
```

### Concept Breakdown
- **Pact Dice:** The dice that scale Eldritch Blast damage (d6 base)
- **EldritchBlastD6:** XML type for adding d6 dice to Eldritch Blast
- **Formula:** Eldritch Blast damage = Base dice + Pact Dice + Bonus (before any multipliers)

### Bonus Types
- `Fortune`
- `Profane`
- `Artifact`
- `Enhancement` (possibly)

### Parsing Keywords
- **XML Type:** `EldritchBlastD6`
- **Amount Field:** Number of d6 dice added (e.g., 1 = +1d6, 3 = +3d6)
- **Bonus Field:** Bonus type (affects how it stacks with other bonuses)

### Notes
- **Pact Dice vs Spellpower:** Warlocks don't use traditional spellpower (like Fire Spellpower). They use Pact Dice exclusively.
- **Arcane Caster Only:** Eldritch Blast is arcane magic, not divine.
- **Not Affected by School DCs or Spell Lore:** Warlock eldritch invocations don't benefit from school spell focuses or spell lore.

### UI Mapping
When user selects "Warlock" as build type:
- Show "Eldritch Blast Dice" instead of traditional spellpower stats
- Hide traditional spell DC/lore options
- Show invocation-specific bonuses (if any exist in data)

---

## 6. Arcane vs Divine Caster Classification

### Current Findings

**Arcane Casters (Spell-Based):**
- Wizard, Sorcerer, Bard, Artificer, Rogue (spells)
- Warlock (Eldritch Blast)
- Use: SpellPower, SpellDC (school-specific), SpellLore, SpellCriticalDamage
- Eldritch Blast scaling: Pact Dice (via `EldritchBlastD6`)

**Divine Casters (Spell-Based):**
- Cleric, Favored Soul, Ranger (spells), Paladin (spells)
- Use: SpellPower, SpellDC (school-specific), SpellLore, SpellCriticalDamage
- **Same mechanics as Arcane** — no special "Divine Spellpower" type found

**Hybrid/Special:**
- Bard: Arcane spellcaster (uses spell mechanics)
- Ranger: Primarily physical, but uses divine spell mechanics when casting

### What Was NOT Found

Despite searching for "divine" and "arcane" keywords:
- **No separate "Divine Spellpower"** type in XML (unlike expected)
- **No "Arcane Spellpower"** type (spellpower is untyped/general)
- **Arcane Spell Failure** is a mechanic modifier, not a damage stat

### Key Insight

DDO appears to use a **unified spell scaling system** where:
- All spell-based damage is calculated via **SpellPower** (untyped)
- School-specific bonuses come via **SpellDC** (school-specific focuses)
- Element-specific bonuses come via **SpellLore** (element-specific critical)
- **No inherent arcane vs divine distinction** in the spell scaling mechanics

---

## 7. Summary: XML Keywords by Stat Type

| Stat Type | XML Type | Priority Field | Key Value | Bonus Field | Note |
|-----------|----------|----------------|-----------|-------------|------|
| Spell DC | `SpellDC` | `<Item>` | School name | `<Bonus>` | School-specific |
| Spell Lore | `SpellLore` | `<Item>` | Element name | `<Bonus>` | Crit chance % |
| Spell Crit Dmg | `SpellCriticalDamage` | `<Item>` | Element name | `<Bonus>` | Damage multiplier |
| **Spellpower** | **`SpellPower`** | **`<Item>`** | **Element/category** | **`<Bonus>`** | **Spell effectiveness** |
| **Eldritch Blast Dice** | **`EldritchBlastD6`** | **N/A** | **Dice count** | **`<Bonus>`** | **Warlock only** |
| Spell Points | `SpellPoints` | `<Bonus>` | "Elemental Spell Power" | `<Bonus>` | Resource pool (not for casters) |

---

## 6. Data Files Containing Caster Stats

### Primary Augment Sources
- `Greensteel_Heroic.Augments.xml` — Spell Lore, Spell Crit Dmg (all elements)
- `Greensteel_Legendary.Augments.xml` — Spell Lore, Spell Crit Dmg
- `CannithAndRandomItem.Augments.xml` — Spell DC (all schools + school-specific)
- `DinosaurBone.Augments.xml` — Various spell stats
- `Diamond.Augments.xml` — Spell bonuses

### Item Sources
- Item files contain `<Buff>` elements with same structure as Augment `<Effect>` elements
- Search pattern: `/Items/*.item` files contain buffs with spell effect types

---

## 7. Implementation Notes for Parser

### Normalization Rules (from existing optimizer.py)
The codebase already normalizes stats with these rules:

1. **Spell School DCs:**
   - Input: "Evocation DC" → Normalized: "evocation spelldc"
   - Search XML: `Type=SpellDC, Item=Evocation`

2. **Spell Lore:**
   - Input: "Fire Lore" → Normalized: "fire spelllore"
   - Search XML: `Type=SpellLore, Item=Fire`

3. **Spell Critical Damage:**
   - Input: "Fire Spell Critical Damage" → Normalized: "fire spellcriticaldamage"
   - Search XML: `Type=SpellCriticalDamage, Item=Fire`

4. **Spellpower:**
   - Input: "Spellpower" or "Elemental Spellpower" → Normalized: "spellpower"
   - Search XML: `Bonus=Elemental Spell Power` OR `Bonus=Improved Elemental Spell Power`

### Case Sensitivity
- XML `<Type>` values are **case-sensitive:** `SpellDC`, `SpellLore`, `SpellCriticalDamage`
- XML `<Item>` and `<Bonus>` values are **case-sensitive:** School/element names start with capital letters
- Normalized stat names should be **lowercase** for consistent comparison

---

## 8. Discussion: Which Stats to Include & Build Type Categorization

### Recommended Core Stats to Include

**For All Spell-Based Casters:**
1. ✅ **Spellpower** (by element/category) — Primary damage scaling
2. ✅ **Spell DC** (by school) — Spell penetration/difficulty
3. ✅ **Spell Lore** (by element) — Critical chance scaling
4. ✅ **Spell Critical Damage** (by element) — Critical damage multiplier
5. ⚠️ **Spell Points** (Optional) — Casting resource; less critical for DPS optimization

### Recommended Specialized Stats

6. ✅ **Eldritch Blast Dice** (Warlock only) — Primary scaling for Warlock
7. ⚠️ **Arcane/Divine Classification** — Current finding shows NO mechanical distinction

### Why NOT Include Arcane vs Divine as Separate Mechanics

**Evidence:**
- No separate "Divine Spellpower" type found in XML
- No separate "Arcane Spellpower" type found in XML
- All spell-based casters use identical SpellPower/SpellDC/SpellLore mechanics
- "Arcane Spell Failure" is a defensive penalty, not damage scaling

**Recommendation:** DO NOT add arcane vs divine as a separate build type. Instead:
- Use **spell classes** as a UI selector (Wizard, Sorcerer, Cleric, Favored Soul, Bard, Ranger spells, Paladin spells)
- Or use **unified "Spell Caster"** build type with Warlock as special case
- Apply same stat prioritization rules to all spell-based casters

### Build Type Categories for Casters

**Option A: Unified Approach (Recommended)**
1. **Spell Caster** (default)
   - Includes: Wizard, Sorcerer, Cleric, Favored Soul, Bard, Ranger spells, Paladin spells
   - Stats: Spellpower, Spell DC, Spell Lore, Spell Crit Dmg, Spell Crit Range (future)
   
2. **Warlock**
   - Includes: Warlock (Pact Caster)
   - Stats: Eldritch Blast Dice, Spellpower (for personal spells), Spell Lore (invocation spells)
   - Note: Eldritch Blast Dice is primary scaling

**Option B: Detailed Approach (If Arcane/Divine Mechanics Are Added Later)**
1. **Arcane Caster** — Wizard, Sorcerer, Bard, Artificer spells
2. **Divine Caster** — Cleric, Favored Soul, Ranger spells, Paladin spells
3. **Warlock** — Special case with Pact Dice

### Implementation Recommendation

**Stage 1 (Current):**
- Implement unified **Spell Caster** build type
- Include: Spellpower (all elements), Spell DC (all schools), Spell Lore, Spell Crit Dmg
- Special case: Warlock can toggle between Eldritch Blast Dice vs Spellpower

**Stage 2 (Future Enhancement):**
- Add class selection within Spell Caster (optional UI refinement)
- Add arcane vs divine if game mechanics are updated to differentiate

### What We Should NOT Add

- ❌ Separate "Arcane Spellpower" stat (doesn't exist)
- ❌ Separate "Divine Spellpower" stat (doesn't exist)
- ❌ "Arcane Spell Failure" to DPS priorities (it's a penalty modifier, not damage)
- ❌ Class-specific damage types (all use same element/school system)

---

## 9. Next Steps

1. ✅ **Data mapping complete** — All keyword structures identified
2. ✅ **Arcane/Divine analysis** — Unified mechanics confirmed
3. ✅ **Eldritch Blast/Pact Dice** — Warlock-specific scaling identified
4. **Decision: Build type structure** — Confirm unified vs detailed approach
5. **Parser validation** — Test normalization rules against augment data
6. **UI implementation** — Create multi-selectors for schools and elements
