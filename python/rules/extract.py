"""XML -> effects. "What does this node GRANT?"

Part of `python/rules/`: no pulp, and — the load-bearing property — **no search
restriction**. Nothing in this module knows about ML windows, armor or
weapon-style filters, excluded packs, owned-items lists or the raid cap. Those
live in `optimizer.parse_items` / `parse_augments` / `parse_filigrees`, which
decide CANDIDACY and then call in here for EXTRACTION.

That split is what lets two callers share one extraction:

    the search   candidacy = "is this a candidate for the model?"
    the ETL      candidacy = none — the catalog holds every item at every level

`keep_unmatched` is the ETL's one behavioural difference: report every stat the
gear grants, including ones no priority claims, instead of dropping them
(docs/0.5.0/00_ETL_START_HERE.md §7). It defaults to False so the search's
output is bit-for-bit unchanged.

Shapes in this data that a fresh parser gets wrong, all found the hard way:

* `<Item>` repeats — one effect can name several targets. findtext takes the
  FIRST, which is the established behaviour across 4261 effects. The ETL fixes
  this structurally with effect_target(effect_id, position, target) rows.
* `<SetBonus>` repeats on filigrees — see the note in `_filigree_from_node`.
* `<Rare/>` marks an ALTERNATE variant, not an addition; aggregation skips it.
* `<Type>` repeats inside one `<Effect>` — same amount, several stats.
"""

import os
import re
import xml.etree.ElementTree as ET

from .constants import (
    PROC_AUGMENT_ALIASES,
    PROC_BONUS_TYPE,
    PROC_ZERO_EFFECT_AUGMENT_NAMES,
    WEAPON_BASE_BONUS_TYPE,
    WEAPON_BASE_STATS,
    WEAPON_COMPOSITE_COMPONENTS,
    WEAPON_STAT_COMPOSITE,
    WEAPON_STAT_CRIT_MULT,
    WEAPON_STAT_CRIT_RANGE,
    WEAPON_STAT_DAMAGE,
    WEAPON_STAT_DICE,
)
from .naming import (
    _is_proc_presence_flag_type,
    _proc_priority_match,
    normalize_stat_name,
    strip_cap_suffix,
)
from .provenance import (
    WEAPON_DAMAGE_TYPES,
    _is_craftable_family_weapon,
    _resolve_is_raid,
)


# CORRECTION (confirmed by a real DDO player, superseding an earlier wrong
# assumption in this same file): a 'Colorless' augment slot does NOT accept
# the 8 standard elemental/celestial colors (Red/Orange/Yellow/Green/Blue/
# Purple/Sun/Moon) — that was the actual bug behind GitHub issue
# jorgec/ddogearset#2 ("Lunar/Solar gems in colorless slots"), not a fix for
# anything. Colorless slots only accept augments that are THEMSELVES
# colorless-compatible — DDO calls these "Diamond" augments.
#
# DDOBuilderV2 does NOT reliably encode this via <Type> at all: confirmed by
# enumerating every one of the 168 distinct real augment <Type> values in the
# corpus, zero are "Colorless" or "Diamond" or anything colorless-adjacent —
# e.g. "Diamond of Charisma" is typed "Blue" in the data, not "Colorless".
# The only reliable signal is the augment's NAME, matched against this
# pattern (confirmed against the real corpus: 46 matches, every one
# independently confirmed typed "Blue" — i.e. the <Type> field would have
# silently misidentified all 46 as Blue-slot-only without this override).
COLORLESS_AUGMENT_NAME_PATTERN = re.compile(
    r"^(Diamond of .+|Set Augment: .+|Globe of .+|Clearwater Diamond|"
    r"Essence of the Epic Litany of the Dead|"
    r"\+\d+ Festive .+|"
    r"Ravil's Book of (?:Legendary )?Recipes|The Master's Gift)$"
)


def augment_fits_slot(aug_type, slot_color, aug_name=None):
    """A 'Colorless' slot accepts an augment ONLY if its name matches
    COLORLESS_AUGMENT_NAME_PATTERN (see above) or, defensively, if it is
    ever literally typed "Colorless" in the data (true of none today, but
    cheap to also honor in case that ever changes). Every other slot family,
    including Colorless for any other augment, requires an EXACT type
    match — no substring fallback.

    A substring fallback (`slot_color in aug_type`) used to sit here and was
    removed after a real-data audit of the full DDOBuilderV2 corpus (194 item
    slot types x 168 augment types) found 34 false-positive pairs it let
    through, e.g. a plain "Red" slot accepting the unrelated augment
    "Incredible Potential" (because "red" is a substring of "incREDible"), a
    plain "Green" slot accepting any Greensteel Weapon Tier augment, and
    heroic-tier slots (e.g. "Alchemical Tier 1") accepting their Legendary-
    tier counterparts ("Legendary Alchemical Tier 1") across a tier boundary
    that should never cross. Every one of those 34 pairs was a bug, not a
    legitimate match the substring rule was relied on for — of the 193 real
    non-Colorless slot types, the 70 with no exact-match augment counterpart
    at all (Cannith crafting prefix/suffix/extra, Set Bonus, Upgrade, Variant,
    etc.) got zero matches under the substring rule too, confirming those
    slot families are resolved through a different mechanism entirely, not
    this general augment-fitting path."""
    slot_color = (slot_color or '').lower()
    aug_type = (aug_type or '').lower()
    if slot_color == 'colorless':
        if aug_type == 'colorless':
            return True
        return bool(aug_name) and bool(COLORLESS_AUGMENT_NAME_PATTERN.match(aug_name.strip()))
    return aug_type == slot_color


def _float_text(text):
    if text is None:
        return None
    try:
        return float(str(text).strip())
    except (ValueError, TypeError):
        return None


def _weapon_base_buffs(item_node, wanted):
    """§15.2 — extract weapon combat properties as ordinary `buffs` entries.

    `wanted` maps canonical lowercase stat name -> the user's own spelling (so
    the emitted stat key matches the PriorityEntry exactly). Values are emitted
    only when the source element is present and parses; Rune Arms (which have
    no crit profile) correctly emit nothing rather than a fabricated default.
    """
    out = []
    if not wanted:
        return out

    wd = _float_text(item_node.findtext('WeaponDamage'))

    dice_ev = None
    dice_node = item_node.find('BaseDice')
    if dice_node is not None:
        number = _float_text(dice_node.findtext('Number'))
        sides = _float_text(dice_node.findtext('Sides'))
        if number is not None and sides is not None:
            # §15.3 — collapse the dice to expected value. Number and Sides are
            # individually meaningless as priorities (1d12 EV 6.5 would beat
            # 2d6 EV 7.0 on "sides" alone).
            dice_ev = number * (sides + 1.0) / 2.0

    crit_mult = _float_text(item_node.findtext('CriticalMultiplier'))
    crit_range = _float_text(item_node.findtext('CriticalThreatRange'))

    emitted = [
        (WEAPON_STAT_DAMAGE, wd),
        (WEAPON_STAT_DICE, dice_ev),
        (WEAPON_STAT_CRIT_MULT, crit_mult),
        (WEAPON_STAT_CRIT_RANGE, crit_range),
        # Composite: the two factors multiply, so neither ranks weapons alone.
        (WEAPON_STAT_COMPOSITE, (wd * dice_ev) if (wd is not None and dice_ev is not None) else None),
    ]

    for canonical, value in emitted:
        if value is None:
            continue
        user_name = wanted.get(canonical)
        if not user_name:
            continue
        out.append((user_name, WEAPON_BASE_BONUS_TYPE, float(value)))
    return out


ITEM_SLOT_TAGS = ['Helmet', 'Necklace', 'Trinket', 'Cloak', 'Belt', 'Ring',
                  'Gloves', 'Boots', 'Bracers', 'Armor', 'Goggles',
                  'Weapon1', 'Weapon2']


def wanted_weapon_stats_for(priorities):
    """§15.2 — only emit weapon-property buffs the user actually asked for;
    unused weapon-property stats add zero variables to the model."""
    wanted = {}
    for p in priorities or []:
        base = strip_cap_suffix(p)
        low = base.lower()
        if low in WEAPON_BASE_STATS:
            wanted[low] = base
    return wanted


def _raw_stat_name(b_type, b_item):
    """Catalog name for a buff `normalize_stat_name` did not match to a priority.

    `"<Item> <Type>"`, lowercased — so `<Item>Force</Item><Type>SpellPower</Type>`
    becomes "force spellpower", which is how a priority spells it.

    It is NOT universally the priority spelling, and must not be sold as such:
    `<Item>Intelligence</Item><Type>AbilityBonus</Type>` yields "intelligence
    abilitybonus" where a priority says "Intelligence". Acceptable because these
    names key the CATALOG's stat dimension, where the natural key is
    (raw_type, raw_target) anyway — priority spelling stays the job of
    normalize_stat_name at query time.

    Only reachable via keep_unmatched=True.
    """
    parts = [(b_item or '').strip(), (b_type or '').strip()]
    return ' '.join(p for p in parts if p).lower() or None


def _item_slots_from_node(item_node):
    """The slots this item can occupy, straight from the XML."""
    slots = []
    slots_node = item_node.find('EquipmentSlot') or item_node.find('Slots')
    if slots_node is not None:
        for child in slots_node:
            if child.tag in ITEM_SLOT_TAGS:
                slots.append(child.tag)
    return slots


def _item_provenance(item_node, name, quests_lookup, raid_names,
                     raid_all_drop_locations, raid_memo):
    """(drop_location, pack, is_raid). Needed by BOTH the pack-exclusion
    candidacy check and the emitted item, so it is computed once and shared."""
    drop_location = item_node.findtext('DropLocation') or ""
    item_is_raid = False
    item_pack = None

    if quests_lookup:
        for quest_name, quest_info in quests_lookup.items():
            if quest_name in drop_location:
                item_pack = quest_info.get('AdventurePack')
                break
        # docs/RAID_DETECTION_SPEC.md — direct match (quest name in this
        # item's own DropLocation) OR any upgrade/crafting ingredient
        # (transitively) traces back to a raid. Replaces the old
        # direct-match-only check; a direct match is still the common case and
        # resolves immediately inside _resolve_is_raid.
        item_is_raid = _resolve_is_raid(
            name, drop_location, raid_names, raid_all_drop_locations, raid_memo)
    elif "raid" in drop_location.lower():
        # No Quests.xml-derived raid list available at all (e.g. a caller that
        # doesn't pass quests_lookup) — fall back to the old crude substring
        # heuristic rather than reporting every item as non-raid.
        item_is_raid = True

    return drop_location, item_pack, item_is_raid


def _item_buffs_from_node(item_node, priorities, wanted_weapon_stats,
                          keep_unmatched=False, with_raw=False):
    """Every buff this item grants. No candidacy, no restrictions.

    `keep_unmatched` is what the ETL needs: report every stat the item provides,
    including ones no priority claims, instead of dropping them. It defaults to
    False so the search's output — and therefore the Phase 1 purity snapshot —
    is bit-for-bit what it always was.

    `with_raw`, independently: when True, each tuple gains a 4th element
    `(raw_type, raw_target)` — the untouched `<Type>`/`<Item>` pair, before
    normalize_stat_name or _raw_stat_name ever see it. This is what the ETL's
    stat dimension keys on (docs/0.5.0/01_CATALOG_AND_APP_SCHEMA.md §5.1's
    `stat` table is built from the true pair, not from a display string).
    Defaults to False so every existing 3-tuple caller — the search and the
    Phase 1 snapshot — is completely unaffected; this only ever widens a tuple
    that keep_unmatched=True already changed the meaning of.
    """
    buffs = []
    for buff_node in item_node.findall('Buff'):
        b_type = buff_node.findtext('Type')
        b_item = buff_node.findtext('Item')
        b_desc = buff_node.findtext('Description1')
        b_val = buff_node.findtext('Value1')
        b_bonus = buff_node.findtext('BonusType')

        stat = normalize_stat_name(b_type, b_item, b_desc, priorities, bonus_type=b_bonus)
        if not stat and keep_unmatched and b_val and b_bonus:
            stat = _raw_stat_name(b_type, b_item)
        if stat and b_val and b_bonus:
            try:
                val = float(b_val)
                entry = (stat, b_bonus.strip(), val)
                buffs.append(entry + ((b_type, b_item),) if with_raw else entry)
            except ValueError:
                pass
        elif not b_bonus and _is_proc_presence_flag_type(b_type):
            # Shape A (docs/PROC_EFFECTS_EXPANSION_SPEC.md) — a whitelisted
            # proc buff missing BonusType (most have no Value1 either; a few
            # like Tendon Slice carry one that isn't a comparable magnitude).
            # Matched via _proc_priority_match, not the `stat` computed above —
            # several real proc names ("Legendary Affirmation", "Legendary
            # Negation", ...) start with a word normalize_stat_name's
            # bonus-type-prefix splitting would otherwise misinterpret.
            # Presence-only: see PROC_BONUS_TYPE.
            proc_stat = _proc_priority_match(b_type, priorities)
            if proc_stat:
                entry = (proc_stat, PROC_BONUS_TYPE, 1.0)
                buffs.append(entry + ((b_type, None),) if with_raw else entry)
            elif keep_unmatched:
                entry = (b_type, PROC_BONUS_TYPE, 1.0)
                buffs.append(entry + ((b_type, None),) if with_raw else entry)

    # §15.2 — weapon combat properties are direct children of <Item>, not
    # <Buff> elements, but they land in the same `buffs` list so sources / z /
    # UB_s / n_s / goals / reconciliation are unchanged.
    #
    # Deliberately NOT widened by keep_unmatched: `wanted_weapon_stats` is a
    # priority-driven projection of a fixed vocabulary, not a match/no-match
    # filter over catalog data. The ETL passes the full vocabulary instead.
    try:
        weapon_buffs = _weapon_base_buffs(item_node, wanted_weapon_stats)
        if with_raw:
            # Weapon base stats have no <Type>/<Item> pair of their own — the
            # stat name IS the raw identity here (WEAPON_STAT_* constants).
            weapon_buffs = [(s, bt, v, (s, None)) for (s, bt, v) in weapon_buffs]
        buffs.extend(weapon_buffs)
    except ValueError:
        pass

    return buffs


def _item_from_node(item_node, item_file, slots, priorities, wanted_weapon_stats,
                    provenance, keep_unmatched=False, with_raw=False):
    """What does this item GRANT? No filtering, no restrictions.

    `slots` is supplied by the caller because candidacy does not merely accept
    or reject an item — the search NARROWS an item's slot list (a khopesh whose
    type is disallowed in Weapon2 keeps Weapon1). The ETL passes the raw list
    from _item_slots_from_node.
    """
    name = item_node.findtext('Name') or 'Unknown'
    ml_node = item_node.find('MinLevel')
    ml = int(ml_node.text) if ml_node is not None and ml_node.text else 0
    weapon_type = item_node.findtext('Weapon')
    drop_location, item_pack, item_is_raid = provenance

    sets = []
    for set_node in item_node.findall('.//SetBonus'):
        if set_node.text:
            sets.append(set_node.text.strip())

    augments = []
    for aug_node in item_node.findall('.//ItemAugment'):
        a_type = aug_node.findtext('Type')
        if a_type:
            augments.append(a_type.strip())

    # docs/HARD_REQUIRED_SLOTS_SPEC.md §1 — only meaningful for weapons;
    # None/False for everything else, which is exactly what an unclassified
    # weapon_type (e.g. Throwing Axe) also gets, so callers don't need to
    # special-case "not a weapon" vs "a weapon type we deliberately don't
    # classify".
    damage_type = WEAPON_DAMAGE_TYPES.get((weapon_type or '').lower())
    craftable_family = bool(weapon_type) and _is_craftable_family_weapon(
        name, drop_location)

    return {
        'name': name,
        'file': os.path.basename(item_file),
        'slots': slots,
        'buffs': _item_buffs_from_node(item_node, priorities, wanted_weapon_stats,
                                       keep_unmatched=keep_unmatched,
                                       with_raw=with_raw),
        'sets': sets,
        'augments': augments,
        'minor': item_node.find('MinorArtifact') is not None,
        'is_raid': item_is_raid,
        'pack': item_pack,
        'ml': ml,
        'weapon_type': weapon_type,
        'damage_type': damage_type,
        'craftable_family': craftable_family,
    }


def parse_sets(base_dir, priorities):
    set_bonuses = {}
    try:
        tree = ET.parse(os.path.join(base_dir, 'SetBonuses.xml'))
        for set_node in tree.findall('.//SetBonus'):
            name = set_node.findtext('Type')
            if not name: continue

            if name not in set_bonuses:
                set_bonuses[name] = {}

            for buff_node in set_node.findall('Buff'):
                count = buff_node.findtext('EquippedCount')
                if not count: continue
                count = int(count)

                if count not in set_bonuses[name]:
                    set_bonuses[name][count] = []

                for effect_node in buff_node.findall('Effect'):
                    b_types = [t.text for t in effect_node.findall('Type') if t.text]
                    b_bonus = effect_node.findtext('Bonus')
                    b_item = effect_node.findtext('Item')
                    amt_node = effect_node.find('Amount')
                    b_val = amt_node.text if amt_node is not None else None

                    if b_val and b_bonus:
                        try:
                            val = float(b_val)
                            for t in b_types:
                                stat = normalize_stat_name(t, b_item, "", priorities, bonus_type=b_bonus)
                                if stat:
                                    set_bonuses[name][count].append((stat, b_bonus.strip(), val))
                        except ValueError:
                            pass
    except Exception:
        pass
    return set_bonuses


def _effect_buffs_from_node(effect_node, priorities, keep_unmatched=False,
                            with_raw=False):
    """Buffs from one `<Effect>`. Shared by augments, filigrees and filigree set
    tiers — all three read the same shape (`<Type>+ <Bonus> <Item> <Amount>`),
    and before the Phase 1 split each carried its own copy of this loop.

    `<Type>` repeats: one effect can grant the same amount to several stats.

    `with_raw` — see `_item_buffs_from_node`'s docstring; same contract, same
    default. Each `<Type>` repeat gets its own `(raw_type, raw_target)` pair,
    since each is genuinely a distinct stat identity sharing one amount.
    """
    b_types = [t.text for t in effect_node.findall('Type') if t.text]
    b_bonus = effect_node.findtext('Bonus')
    b_item = effect_node.findtext('Item')
    amt_node = effect_node.find('Amount')
    b_val = amt_node.text if amt_node is not None else None

    out = []
    if b_val and b_bonus:
        try:
            val = float(b_val)
        except ValueError:
            return out
        for t in b_types:
            stat = normalize_stat_name(t, b_item, "", priorities, bonus_type=b_bonus)
            if not stat and keep_unmatched:
                stat = _raw_stat_name(t, b_item)
            if stat:
                entry = (stat, b_bonus.strip(), val)
                out.append(entry + ((t, b_item),) if with_raw else entry)
    return out


def _augment_from_node(aug_node, priorities, keep_unmatched=False, with_raw=False):
    """What does this augment GRANT? No candidacy, no restrictions.

    Returns None when the node is not a usable augment at all (no `<Type>`) —
    a data-shape check, not a search restriction.
    """
    a_type = aug_node.findtext('Type')
    if not a_type:
        return None

    name = aug_node.findtext('Name') or 'Unknown'

    buffs = []
    for effect_node in aug_node.findall('Effect'):
        buffs.extend(_effect_buffs_from_node(effect_node, priorities,
                                             keep_unmatched=keep_unmatched,
                                             with_raw=with_raw))

    # Shape B (docs/PROC_EFFECTS_EXPANSION_SPEC.md) — a small, confirmed-real
    # whitelist of augments whose own effect data is entirely empty
    # (DDOBuilderV2 marks these "(Undocumented: Grants <Name>)"); the augment's
    # Name is the only signal. Only fires when the loop above found zero buffs —
    # an augment with both real effects AND a whitelisted name (shouldn't
    # happen, but stay conservative) keeps its real buffs untouched. Matched via
    # _proc_priority_match, not normalize_stat_name — several whitelisted names
    # ("Legendary Affirmation", "Legendary Ash", ...) start with a word
    # normalize_stat_name's bonus-type-prefix splitting would otherwise
    # misinterpret (see that helper's docstring).
    name_lower = name.strip().lower()
    if not buffs and name_lower in PROC_ZERO_EFFECT_AUGMENT_NAMES:
        proc_stat = _proc_priority_match(name, priorities)
        if proc_stat:
            entry = (proc_stat, PROC_BONUS_TYPE, 1.0)
            buffs.append(entry + ((name, None),) if with_raw else entry)
        elif keep_unmatched:
            entry = (name, PROC_BONUS_TYPE, 1.0)
            buffs.append(entry + ((name, None),) if with_raw else entry)

    # Aliased augments: the augment's name differs from the proc it grants
    # (e.g. Meltfang -> Alchemical Earth Attunement). Match the alias's proc
    # name against priorities, not the augment's own name.
    alias_proc = PROC_AUGMENT_ALIASES.get(name_lower)
    if alias_proc:
        proc_stat = _proc_priority_match(alias_proc, priorities)
        if proc_stat:
            entry = (proc_stat, PROC_BONUS_TYPE, 1.0)
            buffs.append(entry + ((alias_proc, None),) if with_raw else entry)
        elif keep_unmatched:
            entry = (alias_proc, PROC_BONUS_TYPE, 1.0)
            buffs.append(entry + ((alias_proc, None),) if with_raw else entry)

    return {'name': name, 'type': a_type.strip(), 'buffs': buffs}


def _filigree_from_node(f_node, priorities, keep_unmatched=False, with_raw=False):
    """What does this filigree GRANT? No candidacy, no restrictions."""
    name = f_node.findtext('Name') or 'Unknown'

    buffs = []
    for effect_node in f_node.findall('Effect'):
        # "Rare" is an alternate/upgraded variant of the same filigree
        # instance, not an additional stacking bonus on top of the base
        # effect. Only the base (non-Rare) effect should ever be counted.
        if effect_node.find('Rare') is not None:
            continue
        buffs.extend(_effect_buffs_from_node(effect_node, priorities,
                                             keep_unmatched=keep_unmatched,
                                             with_raw=with_raw))

    return {
        'name': name,
        'base_name': name.split(':')[0].strip() if ':' in name else name,
        # NOTE: `<SetBonus>` repeats — a filigree can belong to two named sets,
        # and findtext keeps only the first, so the second membership is lost.
        # Real bug, deliberately NOT fixed here: the ETL fixes it structurally
        # by emitting one filigree_set row per membership (schema doc §2.3).
        'set': f_node.findtext('SetBonus'),
        'buffs': buffs,
    }
