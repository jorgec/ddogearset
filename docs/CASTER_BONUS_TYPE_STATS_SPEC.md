# Bonus-type-scoped caster DC/Focus Mastery stats — research + spec

**Status:** Implemented.

**Decisions (confirmed):**
1. "Profane Spell DC" / "Artifact Spell DC" scope to the universal All-Schools
   DC bonus only (mirroring the existing "All Schools (Universal)" leaf) —
   not exposed per-school.
2. The bonus-type-prefix mechanism recognizes the full real bonus-type
   universe found in the data for Spell DC and Spell Focus Mastery, except
   Reaper: `sacred, quality, profane, artifact, insightful, exceptional,
   equipment, legendary, enhancement, fortune`. Taxonomy leaves were only
   added for bonus-type/stat combinations actually confirmed present in real
   DDOBuilderV2 data (see `SPELL_DC_ALL_SCHOOLS_BONUS_TYPES` /
   `SPELL_FOCUS_MASTERY_BONUS_TYPES` in `statTaxonomy.ts`) — no leaf can ever
   match zero real sources.

## Ask

Expose four new selectable stat priorities:

- Sacred Spell Focus Mastery
- Quality Spell Focus Mastery
- Profane Spell DC
- Artifact Spell DC

All four are real DDO bonus types. "Spell Focus Mastery" and "Spell DC" are
already-tracked stat categories in this app — the new part is scoping them to
one specific bonus type.

## Why this doesn't work today — two separate gaps

### Gap 1: `Spell Focus Mastery` has no UI entry at all

`frontend/src/lib/data/statTaxonomy.ts` has leaves for "Spell Schools (Spell
DC)", "Spell Lore", "Spell Critical Damage", and "Spellpower" — but no entry
for `SpellFocusMastery`, DDO's universal (applies to every school at once)
spell-DC bonus. The stat picker is taxonomy-driven with no free-text entry
(`StatPriorityEditor.svelte`'s `addStat` only fires from the picker), so a
user cannot add it today by any means, bonus-type-scoped or not.

(`python/optimizer.py`'s `normalize_stat_name` would actually match a literal
`"spell focus mastery"` priority correctly if one existed — the substring
`spellfocusmastery` is unconditionally added to every priority's match list
whenever `dc` or `focus` appears in the priority name. This is a pre-existing
side effect, not something built for this ask.)

### Gap 2: no priority can require a specific `BonusType`/`Bonus` value

This is the real gap. `normalize_stat_name(typ, item, desc, priorities)` never
sees the buff's bonus type — it only matches on `Type`/`Item`/`Description1`
text. The bonus type (`Sacred`, `Quality`, `Profane`, `Artifact`, …) is
extracted separately (`b_bonus` in both `parse_items` and `parse_augments`)
and passed straight into the `(stat, bonus_type, value)` triple used later for
DDO stacking math (same bonus type → max across sources; different bonus
types → sum) — but it plays no role in *which* priority a buff gets
attributed to.

Concretely: if a user typed `"Sacred Spell Focus Mastery"` as a priority today
(hypothetically, if the picker allowed it), `normalize_stat_name` would still
match it against **any** `SpellFocusMastery` buff regardless of whether its
actual `BonusType` is Sacred, Quality, Profane, Exceptional, Equipment,
Insightful, or Legendary — the bonus-type word in the priority name is
currently just inert text that happens to not appear in `combined` and
therefore never blocks a match once the unconditional `spellfocusmastery`
substring is in the match list.

## Verified against real DDOBuilderV2 data

**`SpellFocusMastery`** — appears exclusively as an `<Item><Buff>` (never via
the `Augments/*.xml` catalog). 204 items carry at least one. Confirmed
`<BonusType>` values across the whole corpus:

```
Exceptional, Sacred, Equipment, Quality, Legendary, Profane, Insightful
```

Both `Sacred` (e.g. *A Memento of Mori*, +2) and `Quality` (e.g. *Amplin, the
Channeling Bolt*, +2; *Blessed Longsword of the Fallen Age*, +1) are real and
already present on real items.

**`SpellDC`** — appears exclusively via the `Augments/*.xml` catalog (as an
`<Augment><Effect><Type>SpellDC</Type>...<Bonus>...</Bonus></Effect>`), never
as a direct `<Item><Buff>` — 176 occurrences across `Items/*.item` (all
embedded per-item augment-catalog mirrors) plus the canonical copies in
`Augments/*.xml` (145 `Effect` blocks actually reachable by
`parse_augments`). Confirmed `<Bonus>` values:

```
Equipment, Reaper, Insightful, Enhancement, Exceptional, Artifact, Profane,
Fortune, Quality, Sacred
```

Both `Profane` and `Artifact` are real and confirmed present (e.g. school-
specific SpellDC augments in the Cannith/random-item and other augment
catalogs).

**Full bonus-type universe** (for context, not all in scope here):

- Item `<Buff><BonusType>`: Armor, Armor Enhancement, Competence, Deflection,
  Determination, Enhancement, Equipment, Exceptional, False Life, Implement,
  Inherent, Insightful, Legendary, Luck, Natural Armor, Orb, Penalty, Primal,
  Profane, Quality, Resistance, Sacred, Shield Enhancement, Vitality, Weapon
  Enchantment
- Augment `<Effect><Bonus>`: Alchemical, Armor, Artifact, Base, Competence,
  Deflection, Destiny, Elemental Energy, Elemental Spell Power, Enhancement,
  Equipment, Eternal Faith, Exceptional, False Life, Festive, Fortune,
  Greater Elemental Energy, Greater Elemental Spell Power, Implement,
  Improved Elemental Energy, Improved Elemental Spell Power, Inherent,
  Insightful, Legendary, Luck, Morale, Mythic, Natural Armor, Orb, Penalty,
  Profane, Psionic, Quality, Reaper, Resistance, Sacred, Shield, Silver
  Flame, Stacking, Vitality, Weapon Enchantment

## Design

### 1. Extend `normalize_stat_name` to accept an optional required bonus type

Reuse the mechanism, don't invent a parallel one. Both call sites
(`parse_items`, `parse_augments`) already extract `b_bonus` before calling
`normalize_stat_name` — thread it through as a new parameter:

```python
def normalize_stat_name(typ, item, desc, priorities, bonus_type=None):
    ...
    for p in priorities:
        p_base = re.sub(r'\[\d+\]', '', p).strip()
        required_bonus, p_clean = _split_bonus_type_prefix(p_base.lower())
        if required_bonus and (bonus_type or '').strip().lower() != required_bonus:
            continue
        ...
```

`_split_bonus_type_prefix` recognizes a fixed, explicit prefix list — the
bonus types that are actually meaningful to filter on for casters (start with
exactly the four asked for: `sacred`, `quality`, `profane`, `artifact`) —
matched case-insensitively against the start of the lowercased priority
string, e.g. `"sacred spell focus mastery"` → `("sacred", "spell focus
mastery")`. A priority with no recognized prefix behaves exactly as today
(`required_bonus=None`, matches any bonus type) — fully backward compatible,
zero change for every existing priority in every existing saved gearset.

### 2. Add the missing baseline `Spell Focus Mastery` taxonomy leaf

Prerequisite for §3 below (Sacred/Quality need a base name to prefix) and a
real standalone gap in its own right — add it next to "Spell Schools (Spell
DC)" in `statTaxonomy.ts` as a normal, unscoped leaf (`stat: "spell focus
mastery"`), crediting all bonus types together (today's already-correct
stacking behavior).

### 3. Add the four requested taxonomy leaves

```ts
{
    label: 'Spell Focus Mastery (by Bonus Type)',
    children: [
        { label: 'Sacred', stat: 'sacred spell focus mastery' },
        { label: 'Quality', stat: 'quality spell focus mastery' },
    ],
},
```

and, alongside the existing "Spell Schools (Spell DC)" category (or as a
sibling "All Schools" bonus-type-scoped group — see Open Question 1):

```ts
{ label: 'Profane (All Schools)', stat: 'profane all spelldc' },
{ label: 'Artifact (All Schools)', stat: 'artifact all spelldc' },
```

### 4. Match `_split_bonus_type_prefix` against the *stat-name-with-prefix-stripped*, not the whole combined text

The existing `if 'dc' in p_clean or 'focus' in p_clean:` school-extraction
block must run on `p_clean` *after* the bonus-type prefix has been split off,
so `"profane all spelldc"` still correctly extracts `school="all"` the same
way `"all spelldc"` does today — no separate code path per bonus type.

## Out of scope

- Bonus-type scoping for any other stat category (Spellpower, Spell Lore,
  Spell Critical Damage, PRR/MRR, etc.) — not asked for; §2 of Open Questions
  covers whether the *mechanism* should be built general-purpose even so.
- Any change to DDO stacking math itself — already correct today via the
  existing `(stat, bonus_type, value)` triple and `_is_stacking`/max-per-type
  logic; this spec only changes which priority a buff gets *attributed to*,
  not how attributed amounts combine.
