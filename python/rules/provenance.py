"""Item provenance and weapon classification: where an item comes from, whether
it is raid-sourced, and what family/damage type a weapon belongs to.

Part of `python/rules/`: no pulp, no search restrictions. Note the distinction
that keeps it here — this module answers *"what IS this item?"*. Deciding
whether a raid item may be USED (the raid cap) or whether its adventure pack is
excluded is candidacy, and stays in `optimizer.parse_items`.

Raid detection is transitive: an item counts as raid-sourced if its own
DropLocation names a raid, or if any upgrade/crafting ingredient traces back to
one. See docs/RAID_DETECTION_SPEC.md.
"""

import functools
import glob
import os
import re
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# §16 — hard-required Weapon1/Weapon2 slots (docs/HARD_REQUIRED_SLOTS_SPEC.md)
# ---------------------------------------------------------------------------

# Authoritative source: DDOBuilderV2/Output/DataFiles/WeaponGroupings.xml's
# Slashing/Bludgeoning/Piercing <WeaponGroup> entries, taken verbatim — NOT
# derived from <DRBypass> (that reflects what DR a weapon bypasses, which is
# not the same thing as its own damage type; many items grant bonus bypass
# types unrelated to their base) and NOT from <Description> text (only 5
# items in the whole corpus mention a damage type there — far too sparse).
# Throwing Axe/Dagger/Hammer are real melee-usable weapon types in the corpus
# but appear in none of the three WeaponGroupings.xml groups (DDOBuilderV2
# treats them as thrown/ranged only) — deliberately excluded here rather than
# guessed at, per explicit instruction during the spec review.
_SLASHING_WEAPONS = ('Bastard Sword', 'Battle Axe', 'Dwarven Axe', 'Falchion',
                     'Great Axe', 'Great Sword', 'Hand Axe', 'Kama', 'Khopesh',
                     'Kukri', 'Longsword', 'Scimitar', 'Shortsword', 'Shuriken', 'Sickle')


_BLUDGEONING_WEAPONS = ('Club', 'Great Club', 'Handwraps', 'Heavy Mace', 'Light Hammer',
                        'Light Mace', 'Maul', 'Morningstar', 'Quarterstaff', 'Unarmed',
                        'Warhammer')


_PIERCING_WEAPONS = ('Dagger', 'Dart', 'Heavy Pick', 'Light Pick', 'Rapier')


WEAPON_DAMAGE_TYPES = {
    **{w.lower(): 'Slashing' for w in _SLASHING_WEAPONS},
    **{w.lower(): 'Bludgeoning' for w in _BLUDGEONING_WEAPONS},
    **{w.lower(): 'Piercing' for w in _PIERCING_WEAPONS},
}



# Same authoritative source, "One Handed" <WeaponGroup> — used to identify a
# "caster stick" (any one-handed weapon; the term does NOT mean literally a
# Quarterstaff, which is two-handed and its own separate caster weapon_style
# option — see docs/HARD_REQUIRED_SLOTS_SPEC.md §4).
ONE_HANDED_WEAPON_TYPES = frozenset(w.lower() for w in (
    'Bastard Sword', 'Battle Axe', 'Club', 'Dagger', 'Dwarven Axe', 'Hand Axe',
    'Heavy Mace', 'Heavy Pick', 'Kama', 'Khopesh', 'Kukri', 'Light Hammer',
    'Light Mace', 'Light Pick', 'Longsword', 'Morningstar', 'Rapier',
    'Scimitar', 'Shortsword', 'Sickle', 'Warhammer',
))



# The six weapon "families" known for carrying multiple worthwhile craftable
# augment slots (redefined during spec review — this is NOT about augment-
# slot-TYPE families like Cannith Prefix/Suffix/Extra, it's specific weapon
# sources). Dinosaur Bone / Undying Age / Legendary Green Steel / Defiled
# Reliquary are reliably name-substring-identifiable (verified against the
# real corpus — note it's "Green Steel", two words, not "Greensteel"; Defiled
# Reliquary's own DropLocation text says "Unholy Defiler of the Hidden Hand,
# defiled version of ...", NOT "Defiled Reliquary", so name is the only
# reliable signal for it too — added per docs/CASTER_WEAPON_SELECTION_SPEC.md
# after confirming "Calamitous" weapons, also proposed as a family, already
# ARE the Viktranium family below: Legendary Calamitous Warhammer's own
# DropLocation literally starts with "Viktranium Experiment crafting").
# Viktranium Experiment crafting and Den of Vipers have no reliable name
# pattern and are identified via DropLocation text instead.
CRAFTABLE_FAMILY_NAME_SUBSTRINGS = ('dinosaur bone', 'undying age', 'green steel', 'defiled reliquary')


CRAFTABLE_FAMILY_DROPLOCATION_SUBSTRINGS = ('viktranium', 'den of vipers')


def _is_craftable_family_weapon(name, drop_location):
    name_l = (name or '').lower()
    if any(s in name_l for s in CRAFTABLE_FAMILY_NAME_SUBSTRINGS):
        return True
    drop_l = (drop_location or '').lower()
    return any(s in drop_l for s in CRAFTABLE_FAMILY_DROPLOCATION_SUBSTRINGS)


def weapon_types_for_damage_type(damage_type):
    """The set of lowercase weapon_type strings classified under a given
    damage type (Slashing/Piercing/Bludgeoning) — solver.py's bridge from a
    user-facing damage-type choice to create_model's weapon1_eligible_types."""
    dt = (damage_type or '').strip().lower()
    return {w for w, d in WEAPON_DAMAGE_TYPES.items() if d.lower() == dt}



# --- Raid detection (docs/RAID_DETECTION_SPEC.md) --------------------------
#
# Confirmed real tier-quality prefixes that share a base item's exact name
# once stripped (verified against the corpus: 1702/1796 "Legendary "-prefixed
# items, 524/648 "Epic ", 14/28 "Perfected ", 7/8 "Mythic ", 1/1 "Elite " —
# "Ancient " was tested and dropped, 0/12 real matches, not a real
# tier-upgrade prefix in this data). Order doesn't matter — every prefix is
# tried independently.
RAID_UPGRADE_TIER_PREFIXES = ('Epic ', 'Legendary ', 'Mythic ', 'Perfected ', 'Elite ')



# "<Tier> version of <Name>[ and <Name2>][, ...]" — 605 confirmed real
# occurrences, always naming one or more ingredient items by their exact name
# (e.g. "Epic version of Torc of Prince Raiyum-de II", "Cauldron of Sora
# Katra, Upgraded version of Blade of Fury and Hooked Blade").
_RAID_VERSION_OF_RE = re.compile(r'(?:upgraded )?version of\s+(.+)', re.IGNORECASE)



# Scoping keywords for the looser ingredient-name cross-reference (needed for
# catalyst-crafted items like "Perfected Longsword of the Weapon Master",
# whose real ingredient — "Drow Longsword of the Weapon Master" — isn't
# reachable by tier-prefix stripping OR "version of" phrasing). Deliberately
# scoped to crafting-flavored DropLocation text rather than run on every
# item: bounds the O(items-with-keyword × corpus-size) cost (measured ~3s
# one-time for the full real corpus) and the false-positive surface from
# short/generic names appearing incidentally inside unrelated text.
_RAID_CRAFTING_KEYWORDS = ('turn in', 'catalyst', 'crafting')



# A candidate ingredient name shorter than this is more likely to
# false-positive-match as a substring of unrelated text than to be a genuine
# ingredient reference.
_RAID_MIN_INGREDIENT_NAME_LEN = 8


@functools.lru_cache(maxsize=4)
def _all_item_name_drop_locations(base_dir):
    """Lightweight Name -> DropLocation index across every item in the
    corpus, completely unfiltered by ML/pack/armor/etc. Needed because an
    upgrade chain's *base* item (e.g. a Heroic-tier raid item) is often well
    under today's endgame ML search floor and would otherwise never appear
    in the filtered candidate pool `is_raid` resolution needs to walk back
    through. Cached per base_dir — this project only ever solves against one
    base_dir per process, so the cache is effectively "compute once per
    solver invocation," not a source of staleness risk."""
    out = {}
    for item_file in glob.glob(os.path.join(base_dir, 'Items', '*.item')):
        try:
            tree = ET.parse(item_file)
            for item_node in tree.findall('.//Item'):
                name = item_node.findtext('Name')
                if name:
                    out[name] = item_node.findtext('DropLocation') or ''
        except Exception:
            pass
    return out


def _raid_ingredient_names(name, drop_location, all_names):
    """The set of other item names this item's raid status should be
    inherited from, per docs/RAID_DETECTION_SPEC.md's two-signal design.
    `all_names` is the full corpus name set, for cross-referencing."""
    found = set()
    dl = drop_location or ''

    # Signal A — "<Tier> version of <Name>[ and <Name2>]" phrasing.
    m = _RAID_VERSION_OF_RE.search(dl)
    if m:
        tail = re.sub(r'\s*\([^)]*\)\s*$', '', m.group(1)).strip()
        for part in re.split(r'\s+and\s+|\s*\+\s*', tail):
            part = part.strip().rstrip('.')
            if part in all_names:
                found.add(part)

    # Signal A (cont.) — looser ingredient cross-reference for catalyst-
    # crafted items whose ingredient name doesn't follow "version of"
    # phrasing at all. Scoped to crafting-flavored DropLocation text only.
    dl_lower = dl.lower()
    if any(kw in dl_lower for kw in _RAID_CRAFTING_KEYWORDS):
        for candidate in all_names:
            if (candidate != name
                    and len(candidate) >= _RAID_MIN_INGREDIENT_NAME_LEN
                    and candidate in dl):
                found.add(candidate)

    # Signal B — tier-prefix name stripping (catches e.g. "Perfected X"
    # items whose DropLocation is a generic catalyst turn-in with no textual
    # link to "X" at all).
    for prefix in RAID_UPGRADE_TIER_PREFIXES:
        if name and name.startswith(prefix):
            remainder = name[len(prefix):]
            if remainder in all_names:
                found.add(remainder)

    found.discard(name)
    return found


def _resolve_is_raid(name, drop_location, raid_names, all_drop_locations, memo):
    """Memoized graph walk: True if `name` is sourced from a real raid
    (`drop_location` names a raid directly) OR any of its upgrade/crafting
    ingredients (transitively) are. `memo` also doubles as a cycle guard —
    seeded False before recursing, so a (theoretical, never observed) cycle
    resolves to False rather than infinite-looping."""
    if name in memo:
        return memo[name]
    memo[name] = False

    dl = drop_location or ''
    if any(rn in dl for rn in raid_names):
        memo[name] = True
        return True

    all_names = all_drop_locations.keys()
    for ingredient_name in _raid_ingredient_names(name, dl, all_names):
        ingredient_dl = all_drop_locations.get(ingredient_name, '')
        if _resolve_is_raid(ingredient_name, ingredient_dl, raid_names, all_drop_locations, memo):
            memo[name] = True
            return True

    return False
