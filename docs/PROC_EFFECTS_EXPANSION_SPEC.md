# Expanding proc-effect coverage — research + spec

**Status:** Implemented.

**Decisions (confirmed):**
1. Shipped all 54 confirmed-real proc names in one pass (not a curated
   subset).
2. Taxonomy grouped by theme: Damage Procs, Debuff & Crowd Control Procs,
   Elemental Attunement Grants.
3. First Blood / Warp Souls dropped from scope along with the other 8
   not-found names.

**Bug found and fixed during implementation, not anticipated in the original
research:** `normalize_stat_name`'s bonus-type-prefix splitting (added for
`docs/CASTER_BONUS_TYPE_STATS_SPEC.md`, recognizing `legendary` as a Spell
DC/Focus Mastery bonus-type qualifier) silently broke every proc name that
happens to start with "Legendary" (`Legendary Affirmation`, `Legendary Ash`,
`Legendary Negation`, etc. — 8 of the 54) — the word got stripped and the
buff's real bonus type (empty, for a presence-flag proc) never matched the
required `legendary` qualifier, so these names matched nothing at all despite
being real, confirmed data. Fixed with a dedicated `_proc_priority_match`
helper (bypasses the bonus-type split entirely) used by both Shape A and
Shape B instead of `normalize_stat_name`. Caught by testing every new stat
against real data before considering the work done — see
`test_proc_priority_match_bypasses_bonus_type_prefix_collision`.

## Ask

Expand the app's proc-effect stats to cover the named effects listed on the
DDO wiki's [Category:On-Spellcast Procs](https://ddowiki.com/page/Category:On-Spellcast_Procs)
(49 pages) and [Category:Offhand Procs](https://ddowiki.com/page/Category:Offhand_Procs)
(39 pages) — union of both lists, 61 distinct names. "Some of these are
already covered (like attunement)."

## Finding before anything else: today's proc support doesn't actually match anything

`frontend/src/lib/data/statTaxonomy.ts` has a "Procs" category with 4 leaves
(`on hit damage`, `vulnerability`, `attunement`, `activatable`), each flagged
`UNDOCUMENTED_PROC` ("may match nothing"). Tested directly against the real
corpus:

```
--- attunement --- items:0 augments:0
--- on hit damage --- items:0 augments:0
--- vulnerability --- items:0 augments:0
--- activatable --- items:0 augments:0
```

All four match **zero** real items or augments. So "attunement" isn't
actually functioning today — it's listed in the picker, but selecting it as
a priority currently does nothing. This spec starts from that ground truth,
not from "some already work."

## Why it doesn't work: procs have a different data shape than every other stat

Every stat this app handles so far (Spellpower, PRR, Spell DC, Melee Power,
even the newly-added bonus-type-scoped stats) is **magnitude-based**: the XML
carries a `<Value1>`/`<Amount>` and a `<BonusType>`/`<Bonus>`, and
`normalize_stat_name` + the `(stat, bonus_type, value)` triple pipeline
handles it. Procs are different — verified against the real corpus in three
distinct shapes:

### Shape A — bare marker `<Buff>` (no value at all)

The large majority. A `<Buff>` with a `<Type>` and **nothing else** — no
`<Value1>`, no `<BonusType>`:

```xml
<Buff>
  <Type>Dripping with Magma</Type>
</Buff>
```

`parse_items`' existing buff loop requires `b_val` **and** `b_bonus` to both
be truthy to keep a buff — a bare marker fails that check and is silently
dropped today, even though `normalize_stat_name` would happily match the
`Type` text if given the chance.

### Shape B — augment-name-only, zero `<Effect>` data at all

`Legendary Affirmation`, `Legendary Ash`, `Legendary Dust`, `Legendary Ice`,
`Legendary Ooze`, `Legendary Salt`, `Legendary Vacuum`, and all four
Alchemical Attunements (`Alchemical Fire/Water/Air/Earth Attunement`) are
**augment names**, not buff/effect types. The augment has no `<Effect>` block
whatsoever — its own description literally says `(Undocumented: Grants
Legendary Affirmation)`. `parse_augments`' `if buffs or is_pre_filled:` gate
drops any augment with zero buffs — these never even reach the candidate
pool today, regardless of priorities.

### Shape C — free text only, no structured field

A handful (`Tendon Slice` turned out to actually have Shape-A bare markers
too on 29 items, so this bucket ended up smaller than expected on
inspection) have their only signal in prose `<Description>` text (e.g. "10%
chance to..."). Not reliably parseable without per-proc regex scraping.

## Verified against real DDOBuilderV2 data — full categorization

Union of both wiki category lists (61 names), each checked against real
`Items/*.item` and `Augments/*.xml`:

**Shape A — bare marker `<Buff><Type>`, real and parseable (42):**
Antimagic Spike, Bitter Frostbite, Blunt Trauma, Brazen Brilliance,
Brilliance of the Shattered Sun, Burning Glory *(numbered variants "Burning
Glory 1"/"6" — substring-matchable)*, Cerulean Wave, Coalesced Flame,
Coronach, Dripping with Magma, Eternal Fire, Eternal Holy Burst, Freezing
Ice, Grip of Venom, Inflict Blight, Legendary Negation, Lightning Lash,
Lingering Acidic Burn, Memory of Binding, Memory of Butchery, Mind Tear,
Nightsinger, Noxious Venom Spike, Overwhelming Despair, Quenched, Revel in
Blood *(damage-type-suffixed variants, e.g. "Revel in Blood (Piercing)" —
substring-matchable)*, Rippling Energy, Royalty's Frigid Response, Rupturing
Echo, Shadow Spike, Sinister Chill, Sound and Silence, Sounding, Spell
Resonance, Spell Turmoil, Stone Prison *(Greater/Legendary/Lesser variants)*,
Tendon Slice, The Artblade's Gift, The Mummy's Gift, Titania's Warmth, Vile
Grip of the Hidden Hand *(as "Legendary Vile Grip of the Hidden Hand")*,
Vulkoor's Bite.

**Shape B — augment-name-only, zero effect data (12):**
Legendary Affirmation, Legendary Ash, Legendary Dust, Legendary Ice,
Legendary Ooze, Legendary Salt, Legendary Vacuum, Alchemical Fire
Attunement, Alchemical Water Attunement, Alchemical Air Attunement,
Alchemical Earth Attunement, Paranoia.

**Not found in DDOBuilderV2 at all (7, likely feats/Epic-Destiny/racial
abilities — no gear source to search for):** Arcane Warrior, Elemental Soul,
Force's Edge, Force's Point, Half-Elf Dilettante: Warlock, Light of Glory,
Magical Ambush, Radiant Glory, Ring Burst, Elemental Area of Effect.
(First Blood and Warp Souls need a second look at implementation time — both
show up under related-but-not-exact text: "First Blood (Level N)" augment
names in what looks like a Reaper/Destiny tree export, and "Warp Souls" only
inside another effect's `<Description>` prose, not its own Type/Name.)

## Design

### 1. Presence-flag buffs — one new concept, reused by both shapes

Neither shape carries a real magnitude, so model both as a **presence flag**:
value `1.0`, a fixed non-stacking `bonus_type` sentinel (`"Proc"` — deliberately
*not* `"Stacking"`: two items granting the *same* named proc shouldn't sum to
2.0, since the credited amount should mean "do you have this proc at all,"
not "how many copies"). This reuses the existing max-per-bonus-type
non-stacking math for free — `_is_stacking('Proc')` is `False`, so the
existing `max(vals)`-per-bonus-type-per-stat logic in `optimizer.py` already
produces the right "0 or 1" signal with zero changes there.

### 2. Shape A: stop dropping bare-marker buffs in `parse_items`

```python
stat = normalize_stat_name(b_type, b_item, b_desc, priorities, bonus_type=b_bonus)
if stat and b_val and b_bonus:
    buffs.append((stat, b_bonus.strip(), float(b_val)))
elif stat and not b_val and not b_bonus:
    # Shape A (docs/PROC_EFFECTS_EXPANSION_SPEC.md) — bare marker proc buff,
    # no magnitude in the data. Presence-only: credits 1.0 under a fixed
    # non-stacking bonus type so two sources of the same proc don't double
    # count.
    buffs.append((stat, "Proc", 1.0))
```

This is scoped tightly to *only* buffs with neither value (so a buff that's
merely missing one of the two fields — which shouldn't happen in practice,
but hasn't been verified impossible — still falls through to today's
behavior rather than being misread as a presence marker).

### 3. Shape B: stop dropping zero-effect augments in `parse_augments`, but only for a known whitelist

Unlike Shape A (any bare-marker `Type` is safe to treat as a presence flag),
Shape B needs a whitelist — an augment with genuinely zero effect data and
*no* recognized name is almost certainly not a proc, just an augment this
app has no reason to expose as a priority target (e.g. a placeholder/WIP
entry). Add a small constant list of the 11 confirmed Shape-B names; an
augment whose `Name` matches synthesizes one presence-flag buff the same way
as §2, keyed off the augment's own name text run through
`normalize_stat_name`.

### 4. Taxonomy

Replace the current 4-leaf "Procs" stub in `statTaxonomy.ts` with the real
list from §"Verified against real data" above (Shape A + Shape B only — the
"not found" names are excluded, nothing to search for). Organize by rough
theme (damage procs, debuff/crowd-control procs, elemental attunement
grants) rather than one 54-item flat list — exact grouping is an open
question below.

## Open questions

1. **Scope: all 54 confirmed-real names, or a curated subset first?** The
   full Shape A + Shape B list is 54 entries — a lot of new taxonomy leaves
   at once. Ship everything verified real in one pass, or start with a
   smaller "most build-relevant" subset (e.g. the Magma-Like Effects family
   of 8, which the wiki itself calls out as the most mechanically significant
   damage procs, plus the Legendary Woeful-slot grants) and add the rest
   later?
2. **Bonus-type sentinel name** — `"Proc"` was chosen above as a clear,
   greppable, non-colliding label (verified: no real DDOBuilderV2 `BonusType`/
   `Bonus` value is literally `"Proc"`). Fine as-is, or prefer a different
   label?
3. **Taxonomy grouping** — by theme (as sketched in §4), by source system
   (Magma-Like / Legendary Woeful-Dolorous-Miserable-Melancholic / IoD /
   Thunderforged, matching the existing `proc_tiers_complete` memory's
   breakdown), or a flat alphabetical list? Affects picker usability, not
   backend behavior.
4. **First Blood / Warp Souls** — worth the extra digging to confirm their
   real XML shape before implementation, or drop them from scope along with
   the other 8 not-found names?

## Out of scope

- Shape C (free-text-only procs) — none confirmed to actually exist in this
  union after Tendon Slice turned out to be Shape A; revisit only if a
  future proc name turns out to genuinely have no structured field.
- Quantifying *actual* proc magnitude/rate (e.g. "Dripping with Magma" is
  10d20 per stack per the wiki, but that number isn't in DDOBuilderV2 at
  all) — this spec only makes procs *searchable/preferable* as a presence
  signal, not weighted by their real damage output.
- The 10 confirmed-absent names (feats/Epic Destiny/racial abilities) — no
  gear source exists for these in DDOBuilderV2, so there's nothing to search.
