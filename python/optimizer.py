"""DDO gearset optimizer — tiered (lexicographic) priority solver.

Phase 10 (docs/PHASE10_PLAN.md) replaces the flat weighted-sum ILP with a
sequential lexicographic solve over up to five user-defined priority tiers,
followed by a consolidation stage and a post-solve reconciliation LP.

Key invariants (see docs/PHASE10_PLAN.md §1.1 / §14.2):
  INV-1  `z[(stat, b_type)]` is display truth, built over *all* sources
         (filigrees included). Output is extracted only from the reconciled
         solution, never from a raw tier stage.
  INV-3  A tier's achieved goal value is locked on the goal expression `G_t`,
         never on `prob.objective`.
  INV-4  The consolidation penalty `P` and the filigree tie-break `B` are never
         part of any locked expression.
  INV-5  The model is constructed once; stages call `prob.setObjective(...)`
         and append lock constraints.
  INV-7  Slots are never required to be filled — occupancy is `<= 1`, never
         `== 1`. Do not "fix" this into an equality.
"""

import os
import glob
import shutil
import time
import xml.etree.ElementTree as ET
import pulp
import re
import collections
import functools
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Any

# ---------------------------------------------------------------------------
# Module-level tunable constants (docs/PHASE10_PLAN.md §3.6, §3.10, §4.5, §4.6)
# ---------------------------------------------------------------------------

# §3.6 — floor for the geometric intra-tier weight decay. 0.6*0.4**i reaches
# ~1.6e-4 at i=8 and ~1e-9 at i=13; without the floor the tail of a long tier
# becomes numerically indistinguishable from zero.
WEIGHT_FLOOR = 1e-4

# §3.4 — per-stat upper bounds never go below this, so we never divide by (or
# multiply through) a zero normalizer.
UB_FLOOR = 1e-6

# §3.7 — tier-4 breadth multiplier. Provably safe: the magnitude term is
# bounded by Sum(w_s * 1) == 1 because n_s carries upBound=1.0, so one extra
# included stat (+2.0) always outweighs the entire magnitude term.
M_TIER4 = 2.0

# §4.6 — folding multiplier used when a stage produces no incumbent. Strictly
# exceeds the max value of any single lower goal (G_4 <= 2*|tier4| + 1, others
# <= 1) for realistic tier sizes, so folding preserves tier priority without
# the 1e20-scale big-M a global single-solve would need.
M_FOLD = 4.0

# §3.10 role A — tie-break inside tier stages. Must stay strictly below the
# smallest meaningful goal difference (~5e-3); worst case here is ~2.4e-5.
LAMBDA_ITEM_TIE = 1e-6
LAMBDA_DUP_TIE = 1e-7

# §3.10 role B — the dedicated consolidation stage, where every G_t is already
# locked so aggressiveness is structurally free.
LAMBDA_ITEM = 1.0
LAMBDA_DUP = 0.1
EPS_FIL = 1e-3

# §4.5 — time-budget split across tier stages. Tunable; nothing depends on the
# exact values. Front-loaded because early tiers dominate the search space.
TIER_SHARES = [0.35, 0.25, 0.18, 0.12, 0.10]
MIN_TOTAL_BUDGET = 10.0
MAX_TOTAL_BUDGET = 1800.0
DEFAULT_SEARCH_TIME = 60.0
CONSOLIDATION_SHARE = 0.15
CONSOLIDATION_MIN = 5.0
CONSOLIDATION_MAX = 30.0
STAGE_FLOOR_SECONDS = 5.0

# §6 — the reconciliation LP is a pure LP over z/d with every binary fixed. Its
# budget is fixed and NOT drawn from max_search_time.
RECONCILE_TMLIM = 15

# Bonus types whose sources genuinely add together. Everything else routes down
# the d_var (max-of-sources) path.
STACKING_TYPES = ('stacking', 'mythic', 'reaper')

# docs/PROC_EFFECTS_EXPANSION_SPEC.md — the fixed bonus-type sentinel for
# presence-flag proc buffs (Shape A/B below): these carry no real magnitude
# in DDOBuilderV2 (bare `<Buff><Type>X</Type></Buff>` markers with no
# Value1/BonusType at all, or an augment whose own description says
# "(Undocumented: Grants X)" with zero <Effect> data), so they're credited as
# a flat 1.0 "do you have this proc at all" signal. Deliberately NOT a
# STACKING_TYPES member: two items granting the *same* named proc should
# still read as 1.0, not 2.0 — max-per-bonus-type is the correct DDO-ish
# semantics here ("you either have it or you don't"), not sum-of-sources.
PROC_BONUS_TYPE = 'Proc'

# Shape A (docs/PROC_EFFECTS_EXPANSION_SPEC.md): named procs confirmed to be
# real `<Buff><Type>` markers on real items whose own occurrences never carry
# a full (Value1 AND BonusType) pair — most have neither at all; a few (e.g.
# "Tendon Slice") carry a lone Value1 with no BonusType (10, likely a proc-
# chance percent, not a comparable magnitude) that the existing valued-buff
# path can't credit either way. Deliberately a whitelist, not "any buff
# missing BonusType": ~47 OTHER distinct buff Types in the corpus (Shield,
# Fortification, Elemental Absorption, etc. — legitimate stats, not procs)
# also lack a BonusType and must keep today's behavior untouched. Matched by
# substring against the buff's own Type text (lowercased) since real
# instances carry suffixes this whitelist doesn't (e.g. "Legendary Vile Grip
# of the Hidden Hand", "Revel in Blood (Piercing)", "Burning Glory 1").
PROC_PRESENCE_FLAG_TYPES = frozenset({
    'antimagic spike', 'bitter frostbite', 'blunt trauma', 'brazen brilliance',
    'brilliance of the shattered sun', 'burning glory', 'cerulean wave',
    'coalesced flame', 'coronach', 'dripping with magma', 'eternal fire',
    'eternal holy burst', 'freezing ice', 'grip of venom', 'inflict blight',
    'legendary negation', 'lightning lash', 'lingering acidic burn',
    'memory of binding', 'memory of butchery', 'mind tear', 'nightsinger',
    'noxious venom spike', 'overwhelming despair', 'quenched', 'revel in blood',
    'rippling energy', "royalty's frigid response", 'rupturing echo',
    'shadow spike', 'sinister chill', 'sound and silence', 'sounding',
    'spell resonance', 'spell turmoil', 'stone prison', 'tendon slice',
    "the artblade's gift", "the mummy's gift", "titania's warmth",
    'vile grip of the hidden hand', "vulkoor's bite",
    'alchemical fire attunement', 'alchemical water attunement',
    'alchemical air attunement', 'alchemical earth attunement',
})

# Shape B (docs/PROC_EFFECTS_EXPANSION_SPEC.md): augments confirmed to be
# real DDOBuilderV2 entries (verified against the corpus) whose own effect
# data is entirely empty — the augment's Name IS the only signal
# (DDOBuilderV2 itself marks these "(Undocumented: Grants <Name>)"). Without
# this whitelist, parse_augments' `if buffs or is_pre_filled:` gate drops
# them before they ever reach the candidate pool. Deliberately a whitelist,
# not "any augment with zero effects" — an augment with genuinely no data
# and no recognized name is far more likely a placeholder/WIP catalog entry
# than a real proc grant.
PROC_ZERO_EFFECT_AUGMENT_NAMES = frozenset({
    'legendary affirmation', 'legendary ash', 'legendary dust', 'legendary ice',
    'legendary ooze', 'legendary salt', 'legendary vacuum',
    'alchemical fire attunement', 'alchemical water attunement',
    'alchemical air attunement', 'alchemical earth attunement', 'paranoia',
})


def _is_proc_presence_flag_type(b_type):
    """Shape A whitelist membership, tolerant of the real corpus's
    inconsistent spacing (e.g. 'AlchemicalFireAttunement' with no spaces at
    all on some items, vs the normal spaced form elsewhere) — compares both
    sides with whitespace stripped out entirely."""
    norm = re.sub(r'\s+', '', (b_type or '')).lower()
    return any(re.sub(r'\s+', '', n) in norm for n in PROC_PRESENCE_FLAG_TYPES)


def _proc_priority_match(candidate_text, priorities):
    """Plain substring match against user priorities for proc presence-flag
    buffs (Shapes A/B) — deliberately does NOT go through
    normalize_stat_name's bonus-type-prefix splitting
    (docs/CASTER_BONUS_TYPE_STATS_SPEC.md's BONUS_TYPE_PREFIXES). Several
    real proc names (Legendary Affirmation, Legendary Ash, Legendary
    Negation, ...) literally start with "Legendary", one of the recognized
    Spell DC/Focus Mastery bonus-type prefix words — routing them through the
    shared matcher would silently strip that word, require a matching
    bonus_type that a proc buff never carries, and never match at all.
    Whitespace-insensitive, same as _is_proc_presence_flag_type."""
    candidate = re.sub(r'\s+', '', (candidate_text or '')).lower()
    if not candidate:
        return None
    for p in priorities:
        p_base = re.sub(r'\[\d+\]', '', p).strip()
        p_norm = re.sub(r'\s+', '', p_base).lower()
        if p_norm and p_norm in candidate:
            return p_base
    return None

# §3.4 — capacity constants used by the upper-bound computation.
MAX_WEAPON_FILIGREES = 10
MAX_ARTIFACT_FILIGREES = 5

# ---------------------------------------------------------------------------
# §15 — weapon combat properties as optimizable priority stats
# ---------------------------------------------------------------------------

# §15.1/§15.4: weapon-base sources are built ONLY from x[(i, 'Weapon1')]. The
# off-hand is assumed to duplicate the main hand (TWF) and is structurally
# absent for THF styles, so Weapon2 never contributes a weapon-base source.
# The bonus type is slot-qualified so that assumption is visible in the data and
# a future Weapon2 leak cannot silently max-collapse across hands. It must not
# appear in STACKING_TYPES — that is what makes "one weapon's value counts"
# work with zero new solver primitives.
WEAPON_BASE_SLOT = 'Weapon1'
WEAPON_BASE_BONUS_TYPE = 'WeaponBase:Weapon1'

WEAPON_STAT_DAMAGE = 'weapon damage'
WEAPON_STAT_DICE = 'base damage dice'
WEAPON_STAT_CRIT_MULT = 'critical multiplier'
WEAPON_STAT_CRIT_RANGE = 'critical threat range'
WEAPON_STAT_COMPOSITE = 'weapon base damage'

# §15.2 — exact-match lookup table. Deliberately NOT routed through
# normalize_stat_name: substring matching would misfire ("critical multiplier"
# overlapping "spell critical damage", "weapon damage" against Weapon_* types).
WEAPON_BASE_STATS = frozenset({
    WEAPON_STAT_DAMAGE,
    WEAPON_STAT_DICE,
    WEAPON_STAT_CRIT_MULT,
    WEAPON_STAT_CRIT_RANGE,
    WEAPON_STAT_COMPOSITE,
})

# §15.3 — the composite double-counts if listed alongside either component.
# This is specified as a frontend validation rule (EC-29): the backend does not
# reject such a payload, it only surfaces a note.
WEAPON_COMPOSITE_COMPONENTS = frozenset({WEAPON_STAT_DAMAGE, WEAPON_STAT_DICE})

# §15.6 — tier-4 "meaningful bar" per weapon-base stat. A weapon is essentially
# always equipped, so the generic "one credited source" rule would make
# present_s trivially 1 and tier-4 breadth toothless for these stats.
# `weapon damage` is "> 1.0"; the epsilon makes the strict inequality linear.
WEAPON_TIER4_BASELINES = {
    WEAPON_STAT_CRIT_MULT: 3.0,
    WEAPON_STAT_CRIT_RANGE: 2.0,
    WEAPON_STAT_DAMAGE: 1.0 + 1e-6,
}


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


def safe_name(s):
    return re.sub(r'[^a-zA-Z0-9_]', '_', str(s))


def _weapon_family_key(item):
    """Diversity key for find_slot_alternatives (per explicit instruction: a
    'reskin' of an already-suggested weapon — same named line, just a
    different weapon type — is not a true alternative). Real DDO themed
    weapon sets name every type variant identically apart from the type
    itself, e.g. 'Legendary Cataclysmic Greataxe' / '...Falchion' / '...Great
    Crossbow' (verified against the real corpus: ~30 Cataclysmic variants,
    one per weapon type, all sharing the same augment slots/buffs). Returns
    the shared prefix (a same-family signal) when `item`'s name literally
    ends with its own weapon type (ignoring whitespace/case); returns None
    for non-weapons or names that don't follow this pattern (e.g. unique
    named items like 'Arctica, the Mystic Cold' are never deduped against
    anything — nothing else shares that exact name)."""
    weapon_type = item.get('weapon_type')
    if not weapon_type:
        return None
    norm_name = re.sub(r'\s+', '', item.get('name', '')).lower()
    norm_type = re.sub(r'\s+', '', weapon_type).lower()
    if norm_type and norm_name.endswith(norm_type) and len(norm_name) > len(norm_type):
        return norm_name[:-len(norm_type)]
    return None


# The 21 real DDO skills, taken from the distinct <Item> values on the
# corpus's 992 SkillBonus buffs (docs/CASTER_BONUS_TYPE_STATS_SPEC.md's
# post-release corrections). Used to decide whether a user's priority is
# asking for a skill, so a skill buff is never absorbed by an unrelated
# priority — see is_skill_buff in normalize_stat_name.
SKILL_NAMES = frozenset({
    'balance', 'bluff', 'concentration', 'diplomacy', 'disable device',
    'haggle', 'heal', 'hide', 'intimidate', 'jump', 'listen',
    'move silently', 'open lock', 'perform', 'repair', 'search',
    'spellcraft', 'spot', 'swim', 'tumble', 'use magic device',
})


def _priority_wants_skill(p_clean):
    """True when a priority is asking for a skill: it either names one of the
    real skills outright, or says "skill(s)" (covering the group buffs like
    "Alluring Skills Bonus" that have no per-skill <Item>)."""
    return 'skill' in p_clean or any(s in p_clean for s in SKILL_NAMES)


def _is_stacking(b_type):
    return (b_type or '').lower().strip() in STACKING_TYPES


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


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _val(var):
    """varValue with a None-safe default. GLPK leaves values unset on a run that
    produced no incumbent."""
    v = getattr(var, 'varValue', None)
    return 0.0 if v is None else float(v)


def strip_cap_suffix(name):
    """'Melee Power[50]' -> 'Melee Power'."""
    return re.sub(r'\[\d+\]', '', str(name)).strip()


def normalize_stat_key(name):
    """Duplicate-detection key (§2.6): strip [N], strip whitespace, casefold."""
    return strip_cap_suffix(name).casefold()


# docs/CASTER_BONUS_TYPE_STATS_SPEC.md — recognized bonus-type qualifier
# prefixes for Spell DC / Spell Focus Mastery priorities (e.g. "Sacred Spell
# Focus Mastery", "Profane Spell DC"). Deliberately excludes Reaper (a
# stacking bonus type, not a real gear-farming target) and the caster-
# irrelevant bonus types (Armor, Competence, Deflection, Luck, Resistance,
# etc.) — this is every bonus type actually observed on real SpellDC/
# SpellFocusMastery sources in DDOBuilderV2, minus Reaper.
BONUS_TYPE_PREFIXES = frozenset({
    'sacred', 'quality', 'profane', 'artifact', 'insightful', 'exceptional',
    'equipment', 'legendary', 'enhancement', 'fortune',
})


def _split_bonus_type_prefix(p_clean):
    """'sacred spell focus mastery' -> ('sacred', 'spell focus mastery').
    No recognized prefix -> (None, p_clean) unchanged, so every priority that
    isn't bonus-type-qualified keeps matching any bonus type, exactly as
    before this existed."""
    first, _, rest = p_clean.partition(' ')
    if first in BONUS_TYPE_PREFIXES and rest:
        return first, rest
    return None, p_clean


def normalize_stat_name(typ, item, desc, priorities, bonus_type=None):
    typ = (typ or '').lower()
    item = (item or '').lower()
    desc = (desc or '').lower()
    bonus_type = (bonus_type or '').strip().lower()

    # Skills used to be dropped outright here (`if 'skill' in typ/item/desc:
    # return None`), a blanket simplification carried over from the original
    # Phase 3 integration. It meant a Spellcraft or Disable Device priority
    # could never match anything, even though the data is perfectly
    # structured for it: Type='SkillBonus', Item='<skill name>', with a real
    # Value1 and BonusType (992 such buffs across 21 skills).
    #
    # They cannot simply be un-dropped, though. Alongside per-skill buffs the
    # corpus carries GROUP buffs typed e.g. "Intelligence Skills - Exceptional
    # Bonus" or "Alluring Skills Bonus" — bonuses to the skills governed by an
    # ability, NOT to the ability score. Matching those by plain substring
    # would let an "Intelligence" ability priority absorb them, which is the
    # same defect class as the school-save bug below.
    #
    # So skills are gated per-priority instead: only a priority that actually
    # asks for a skill may claim a skill buff. Structural fields only, never
    # the free-text description, so a buff that merely mentions "skills" in
    # prose is unaffected.
    is_skill_buff = 'skill' in typ or 'skill' in item

    # A Hireling* buff (HirelingPRR, HirelingMRR, HirelingMeleePower,
    # HirelingAbilityBonus) buffs YOUR HIRELING, not you. The stat name is a
    # substring of the character's own stat, so a plain match credits it to
    # the player: reported from a real gearset, The Cry of Battle's 2-piece
    # bonus (HirelingPRR +20 / HirelingMRR +20) was counted toward the user's
    # own PRR and MRR priorities, and the solver duly spent two filigree slots
    # acquiring +40 of defence that goes to a hireling. Same defect class as
    # the school-save and ability-skill-group collisions.
    is_hireling_buff = 'hireling' in typ or 'hireling' in item

    # A saving-throw buff — IllusionSave, EnchantmentSave, "Illusion Save" —
    # is a DEFENSIVE stat: it raises YOUR save against that school and does
    # nothing for the DC of spells you cast. Because it carries the school's
    # name, a plain substring match happily credits it to an OFFENSIVE
    # priority: reported from a real gearset, Legendary Eyes of
    # Enlightenment's "IllusionSave +11 (Resistance)" was being counted
    # toward an Illusion DC priority and inflating its realized total.
    #
    # Rather than dropping these outright (the skill guard's approach), they
    # are gated per-priority below, so someone who genuinely wants the
    # defensive stat can still ask for it by name ("illusion save" /
    # "illusion resistance"). Keyed on the structural Type/Item fields and
    # never the free-text description, so a buff that merely mentions "save"
    # in prose isn't swept in.
    is_save_buff = 'save' in typ or 'save' in item

    combined = f"{item} {typ} {desc}".lower()

    def match_terms(p_clean):
        """(direct, implied) match strings for one priority.

        `direct` are the stat this priority literally names. `implied` are
        stats it only benefits from indirectly — currently just Spell Focus
        Mastery, which raises the DC of EVERY school, so any school-DC
        priority legitimately profits from it.

        The split matters because a buff is attributed to exactly one
        priority. Before it existed, every "…dc"/"…focus" priority carried
        the universal Spell-Focus-Mastery terms in the same flat list, so a
        priority like "evocation spelldc" would swallow every
        SpellFocusMastery buff purely by being earlier in the user's list —
        starving an explicit "sacred spell focus mastery" priority to zero
        sources and reporting it as matching nothing.
        """
        direct = [p_clean, p_clean.replace(' ', '')]
        implied = []
        if p_clean == 'prr':
            direct.extend(['physical resistance', 'physicalresistancerating'])
        elif p_clean == 'mrr':
            direct.extend(['magical resistance', 'magicalresistancerating'])
        elif p_clean == 'hamp' or p_clean == 'healing amp':
            direct.extend(['healing amplification'])

        if 'spell power' in p_clean:
            direct.append(p_clean.replace('spell power', 'spellpower'))
        if 'spell crit chance' in p_clean or 'spell lore' in p_clean:
            ele = p_clean.replace('spell crit chance', '').replace('spell lore', '').strip()
            direct.append(f"{ele} spelllore")
            direct.append(f"{ele} spell lore")
        if 'spell crit damage' in p_clean or 'spell critical damage' in p_clean:
            ele = p_clean.replace('spell crit damage', '').replace('spell critical damage', '').strip()
            direct.append(f"{ele} spellcriticaldamage")
            direct.append(f"{ele} spell critical damage")
        if 'dc' in p_clean or 'focus' in p_clean:
            school = p_clean.replace('dc', '').replace('focus', '').replace('spell', '').strip()
            direct.append(f"{school} spellfocus")
            direct.append(f"{school} spell focus")
            # Universal, school-agnostic — hence implied, not direct. A
            # priority that names Spell Focus Mastery outright already
            # matches it through `direct` above.
            implied.append("spell focus mastery")
            implied.append("spellfocusmastery")
        return direct, implied

    # Two passes: every priority gets a shot at a DIRECT match before any
    # priority is allowed to claim the buff through an implied one. Within a
    # pass, earlier priorities still win, preserving the original ordering
    # semantics. A user who lists only school DCs and no Spell Focus Mastery
    # priority still credits SFM buffs on the second pass, exactly as before.
    for use_implied in (False, True):
        for p in priorities:
            p_base = re.sub(r'\[\d+\]', '', p).strip()
            required_bonus, p_clean = _split_bonus_type_prefix(p_base.lower())
            if required_bonus and required_bonus != bonus_type:
                continue
            # Weapon combat properties are matched by exact element name in
            # parse_items (§15.2) and must never go through the substring heuristic.
            if p_clean in WEAPON_BASE_STATS:
                continue
            # Only a priority that actually asks for a save may claim a
            # defensive saving-throw buff (see is_save_buff above).
            if is_save_buff and 'save' not in p_clean and 'resist' not in p_clean:
                continue
            # Likewise, only a skill-seeking priority may claim a skill buff
            # (see is_skill_buff above) — this is what stops an "Intelligence"
            # ability priority from absorbing "Intelligence Skills" buffs.
            if is_skill_buff and not _priority_wants_skill(p_clean):
                continue
            # Only a priority explicitly asking for a hireling stat may claim
            # a Hireling* buff (see is_hireling_buff above).
            if is_hireling_buff and 'hireling' not in p_clean:
                continue

            direct, implied = match_terms(p_clean)
            for m in (implied if use_implied else direct):
                if m in combined:
                    return p_base
    return None


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


def parse_items(base_dir, max_ml, priorities, allowed_armor, allowed_w1_list, allowed_w2_list, allow_gomf, art_slot_input, excluded_packs=None, quests_lookup=None, pre_equipped_names=None, min_ml=29, owned_names=None):
    items = []
    allowed_armor = allowed_armor.strip().lower() if allowed_armor else None

    # §15.2 — only emit weapon-property buffs the user actually asked for;
    # unused weapon-property stats add zero variables to the model.
    wanted_weapon_stats = {}
    for p in priorities or []:
        base = strip_cap_suffix(p)
        low = base.lower()
        if low in WEAPON_BASE_STATS:
            wanted_weapon_stats[low] = base

    force_dino = False
    if art_slot_input:
        art_slot_input = art_slot_input.lower().strip()
        if '(dino)' in art_slot_input:
            force_dino = True
            art_slot_input = art_slot_input.replace('(dino)', '').strip()

    # docs/RAID_DETECTION_SPEC.md — computed once per call, not per item: the
    # raid-name set (from Quests.xml via quests_lookup) and the full
    # unfiltered name->DropLocation index (needed to walk upgrade chains back
    # to a base item that may itself be below today's ML floor). `raid_memo`
    # is shared across every item in this call so the graph walk's cost is
    # paid once per distinct item name, not once per item that references it.
    raid_names = frozenset(
        qname for qname, qinfo in (quests_lookup or {}).items() if qinfo.get('is_raid')
    ) if quests_lookup else frozenset()
    raid_all_drop_locations = _all_item_name_drop_locations(base_dir) if quests_lookup else {}
    raid_memo = {}

    for item_file in glob.glob(os.path.join(base_dir, 'Items', '*.item')):
        try:
            tree = ET.parse(item_file)
            root = tree.getroot()

            for item_node in root.findall('.//Item'):
                name = item_node.findtext('Name') or 'Unknown'
                is_pre_equipped = pre_equipped_names and name in pre_equipped_names

                ml_node = item_node.find('MinLevel')
                ml = int(ml_node.text) if ml_node is not None and ml_node.text else 0

                if not is_pre_equipped:
                    if ml < min_ml or ml > max_ml:
                        continue
                    if not allow_gomf and "Gem of Many Facets" in name:
                        continue

                weapon_type = item_node.findtext('Weapon')
                is_minor = item_node.find('MinorArtifact') is not None

                slots = []
                slots_node = item_node.find('EquipmentSlot') or item_node.find('Slots')
                if slots_node is not None:
                    for child in slots_node:
                        tag = child.tag
                        if tag in ['Helmet', 'Necklace', 'Trinket', 'Cloak', 'Belt', 'Ring', 'Gloves', 'Boots', 'Bracers', 'Armor', 'Goggles', 'Weapon1', 'Weapon2']:
                            slots.append(tag)

                if not slots:
                    continue

                original_slots = slots.copy()

                if not is_pre_equipped:
                    if is_minor and art_slot_input:
                        matched_slots = [s for s in slots if art_slot_input in s.lower()]
                        if not matched_slots:
                            continue
                        if force_dino and 'dinosaur bone' not in name.lower():
                            continue
                        slots = matched_slots
                    elif is_minor and force_dino and not art_slot_input:
                        if 'dinosaur bone' not in name.lower():
                            continue

                    w_type_lower = (weapon_type or '').lower()

                    if 'Weapon1' in slots:
                        if allowed_w1_list and w_type_lower not in allowed_w1_list:
                            slots.remove('Weapon1')

                    if 'Weapon2' in slots:
                        if allowed_w2_list:
                            if 'none' in allowed_w2_list:
                                slots.remove('Weapon2')
                            elif w_type_lower not in allowed_w2_list:
                                slots.remove('Weapon2')

                    armor_type = item_node.findtext('Armor')
                    if 'Armor' in slots and allowed_armor:
                        if not armor_type or allowed_armor not in armor_type.strip().lower():
                            slots.remove('Armor')

                if not slots:
                    slots = original_slots if is_pre_equipped else []
                    if not slots:
                        continue

                drop_location = item_node.findtext('DropLocation') or ""
                item_is_raid = False
                item_pack = None

                if quests_lookup:
                    for quest_name, quest_info in quests_lookup.items():
                        if quest_name in drop_location:
                            item_pack = quest_info.get('AdventurePack')
                            break
                    # docs/RAID_DETECTION_SPEC.md — direct match (quest name
                    # in this item's own DropLocation) OR any upgrade/
                    # crafting ingredient (transitively) traces back to a
                    # raid. Replaces the old direct-match-only check; a
                    # direct match is still the common case and resolves
                    # immediately inside _resolve_is_raid.
                    item_is_raid = _resolve_is_raid(
                        name, drop_location, raid_names, raid_all_drop_locations, raid_memo)
                elif "raid" in drop_location.lower():
                    # No Quests.xml-derived raid list available at all (e.g.
                    # a caller that doesn't pass quests_lookup) — fall back
                    # to the old crude substring heuristic rather than
                    # reporting every item as non-raid.
                    item_is_raid = True

                if not is_pre_equipped and excluded_packs and item_pack in excluded_packs:
                    continue

                # docs/TROVE_INVENTORY_IMPORT_SPEC.md — exact-name membership
                # only, no fuzzy matching; DDOBuilderV2 is the definitive
                # source and a CSV name that doesn't match anything here is
                # simply never seen again after LoadTroveInventory. Bypassed
                # for pre-equipped items for the same reason as the ml/pack
                # checks above: something already locked into the gearset
                # must never be silently dropped by a pool filter.
                if not is_pre_equipped and owned_names is not None and name not in owned_names:
                    continue

                buffs = []
                for buff_node in item_node.findall('Buff'):
                    b_type = buff_node.findtext('Type')
                    b_item = buff_node.findtext('Item')
                    b_desc = buff_node.findtext('Description1')
                    b_val = buff_node.findtext('Value1')
                    b_bonus = buff_node.findtext('BonusType')

                    stat = normalize_stat_name(b_type, b_item, b_desc, priorities, bonus_type=b_bonus)
                    if stat and b_val and b_bonus:
                        try:
                            val = float(b_val)
                            buffs.append((stat, b_bonus.strip(), val))
                        except ValueError:
                            pass
                    elif not b_bonus and _is_proc_presence_flag_type(b_type):
                        # Shape A (docs/PROC_EFFECTS_EXPANSION_SPEC.md) — a
                        # whitelisted proc buff missing BonusType (most have
                        # no Value1 either; a few like Tendon Slice carry one
                        # that isn't a comparable magnitude). Matched via
                        # _proc_priority_match, not the `stat` computed above
                        # — several real proc names ("Legendary Affirmation",
                        # "Legendary Negation", ...) start with a word
                        # normalize_stat_name's bonus-type-prefix splitting
                        # would otherwise misinterpret. Presence-only: see
                        # PROC_BONUS_TYPE.
                        proc_stat = _proc_priority_match(b_type, priorities)
                        if proc_stat:
                            buffs.append((proc_stat, PROC_BONUS_TYPE, 1.0))

                # §15.2 — weapon combat properties are direct children of <Item>,
                # not <Buff> elements, but they land in the same `buffs` list so
                # sources / z / UB_s / n_s / goals / reconciliation are unchanged.
                try:
                    buffs.extend(_weapon_base_buffs(item_node, wanted_weapon_stats))
                except ValueError:
                    pass

                sets = []
                for set_node in item_node.findall('.//SetBonus'):
                    if set_node.text:
                        sets.append(set_node.text.strip())

                augments = []
                for aug_node in item_node.findall('.//ItemAugment'):
                    a_type = aug_node.findtext('Type')
                    if a_type:
                        augments.append(a_type.strip())

                # docs/HARD_REQUIRED_SLOTS_SPEC.md §1 — only meaningful for
                # weapons; None/False for everything else, which is exactly
                # what an unclassified weapon_type (e.g. Throwing Axe) also
                # gets, so callers don't need to special-case "not a weapon"
                # vs "a weapon type we deliberately don't classify".
                damage_type = WEAPON_DAMAGE_TYPES.get((weapon_type or '').lower())
                craftable_family = bool(weapon_type) and _is_craftable_family_weapon(name, drop_location)

                items.append({
                    'name': name,
                    'file': os.path.basename(item_file),
                    'slots': slots,
                    'buffs': buffs,
                    'sets': sets,
                    'augments': augments,
                    'minor': is_minor,
                    'is_raid': item_is_raid,
                    'pack': item_pack,
                    'ml': ml,
                    'weapon_type': weapon_type,
                    'damage_type': damage_type,
                    'craftable_family': craftable_family,
                })
        except Exception:
            pass
    return items


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


def flatten_pre_filled_augment_names(pre_filled_augments):
    """Extracts every augment name referenced by a pre_filled_augments payload,
    across both accepted shapes (see create_model's `pairs` handling): the new
    {color: name} / {color: [names]} dict format, and the legacy positional
    list-of-names format. Used to bypass parse_augments' ML floor for augments
    that are already slotted into a pre-equipped item."""
    names = set()
    for aug_entry in (pre_filled_augments or {}).values():
        if isinstance(aug_entry, dict):
            for v in aug_entry.values():
                if isinstance(v, list):
                    names.update(n for n in v if n)
                elif v:
                    names.add(v)
        else:
            names.update(n for n in (aug_entry or []) if n)
    return names


def parse_augments(base_dir, max_ml, priorities, pre_filled_augment_names=None, min_ml=29, owned_names=None):
    """`pre_filled_augment_names` mirrors parse_items' `pre_equipped_names` bypass
    (see is_pre_equipped there): an augment already slotted into a pre-equipped
    item is not optional gear-search inventory, it's a fact about the current
    build, so the ML>=29 floor (meant to keep the *search space* to
    endgame-relevant items) must not silently drop it. Without this, any
    pre-filled augment with MinLevel < 29 (e.g. the MinLevel-22 Festive line)
    fails to match in create_model, and the aggregate
    `sum(y) == total_pre_filled_augments` constraint (which counts every
    payload entry, matched or not) turns that single miss into a hard
    infeasibility for the whole calculate-only solve."""
    augments = []
    pre_filled_augment_names = set(pre_filled_augment_names or [])
    for aug_file in glob.glob(os.path.join(base_dir, 'Augments', '*.xml')):
        try:
            tree = ET.parse(aug_file)
            for aug_node in tree.findall('.//Augment'):
                name = aug_node.findtext('Name') or 'Unknown'
                a_type = aug_node.findtext('Type')
                if not a_type: continue

                is_pre_filled = name in pre_filled_augment_names

                ml_node = aug_node.find('MinLevel')
                ml = int(ml_node.text) if ml_node is not None and ml_node.text else 0
                if not is_pre_filled and (ml < min_ml or ml > max_ml):
                    continue

                # docs/TROVE_INVENTORY_IMPORT_SPEC.md — same exact-name
                # membership check as parse_items, same pre-filled bypass
                # rationale as the ML floor immediately above.
                if not is_pre_filled and owned_names is not None and name not in owned_names:
                    continue

                buffs = []
                for effect_node in aug_node.findall('Effect'):
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
                                    buffs.append((stat, b_bonus.strip(), val))
                        except ValueError:
                            pass

                # Shape B (docs/PROC_EFFECTS_EXPANSION_SPEC.md) — a small,
                # confirmed-real whitelist of augments whose own effect data
                # is entirely empty (DDOBuilderV2 marks these
                # "(Undocumented: Grants <Name>)"); the augment's Name is the
                # only signal. Only fires when the loop above found zero
                # buffs — an augment with both real effects AND a whitelisted
                # name (shouldn't happen, but stay conservative) keeps its
                # real buffs untouched. Matched via _proc_priority_match, not
                # normalize_stat_name — several whitelisted names ("Legendary
                # Affirmation", "Legendary Ash", ...) start with a word
                # normalize_stat_name's bonus-type-prefix splitting would
                # otherwise misinterpret (see that helper's docstring).
                if not buffs and name.strip().lower() in PROC_ZERO_EFFECT_AUGMENT_NAMES:
                    proc_stat = _proc_priority_match(name, priorities)
                    if proc_stat:
                        buffs.append((proc_stat, PROC_BONUS_TYPE, 1.0))

                # A pre-filled augment must never be dropped for having zero
                # buffs that match the user's *current* stat_priorities — same
                # rationale as the ML-floor and owned-names bypasses above:
                # create_model's aggregate sum(y) == total_pre_filled_augments
                # constraint expects every pre-filled augment to be findable by
                # name in this list regardless of its buffs (pinning it only
                # needs `name`/`type`, not `buffs` — see create_model's
                # pre_filled_augments matching loop). Without this bypass, an
                # augment whose only effects fall outside the current priority
                # list (e.g. the user removed that stat from priorities after
                # slotting it) would silently vanish here and turn a
                # calculate-only solve infeasible.
                if buffs or is_pre_filled:
                    augments.append({
                        'name': name,
                        'type': a_type.strip(),
                        'buffs': buffs
                    })
        except Exception:
            pass
    return augments


def parse_filigrees(base_dir, priorities):
    filigrees = []
    sets = {}

    for xml_file in glob.glob(os.path.join(base_dir, 'FiligreeSets', '*.xml')):
        try:
            tree = ET.parse(xml_file)

            for set_node in tree.findall('.//SetBonus'):
                name_node = set_node.find('Type')
                if name_node is None:
                    continue
                name = name_node.text
                if not name:
                    continue

                if name not in sets:
                    sets[name] = {}

                for buff_node in set_node.findall('Buff'):
                    count = buff_node.findtext('EquippedCount')
                    if not count: continue
                    count = int(count)

                    if count not in sets[name]:
                        sets[name][count] = []

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
                                        sets[name][count].append((stat, b_bonus.strip(), val))
                            except ValueError:
                                pass

            for f_node in tree.findall('.//Filigree'):
                name = f_node.findtext('Name') or 'Unknown'
                set_bonus = f_node.findtext('SetBonus')

                buffs = []
                for effect_node in f_node.findall('Effect'):
                    # "Rare" is an alternate/upgraded variant of the same filigree
                    # instance, not an additional stacking bonus on top of the base
                    # effect. Only the base (non-Rare) effect should ever be counted.
                    if effect_node.find('Rare') is not None:
                        continue
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
                                    buffs.append((stat, b_bonus.strip(), val))
                        except ValueError:
                            pass

                base_name = name.split(':')[0].strip() if ':' in name else name

                if buffs:
                    filigrees.append({
                        'name': name,
                        'base_name': base_name,
                        'set': set_bonus,
                        'buffs': buffs
                    })
        except Exception:
            pass

    return filigrees, sets


# ---------------------------------------------------------------------------
# §2.1 / §8.1 — data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PriorityEntry:
    """One user priority. §2.1.

    `stat` is the BASE name ("[N]" already stripped) because that is what
    `normalize_stat_name` returns and therefore what keys `sources`.
    `order` is the 0-based index WITHIN its tier, taken from array order.
    """
    stat: str
    tier: int
    cap: Optional[float] = None
    order: int = 0


@dataclass
class Model:
    """Replaces create_model()'s 8-tuple return; too many members to keep
    positional (§8.1)."""
    prob: Any
    x: Dict[Tuple[int, str], Any] = field(default_factory=dict)
    y: Dict[Tuple[int, int, str], Any] = field(default_factory=dict)
    fw: Dict[int, Any] = field(default_factory=dict)
    fm: Dict[int, Any] = field(default_factory=dict)
    w_vars: Dict[Tuple[str, int], Any] = field(default_factory=dict)
    z: Dict[Tuple[str, str], Any] = field(default_factory=dict)
    # aliases z where the two cannot differ (§3.3)
    z_nofil: Dict[Tuple[str, str], Any] = field(default_factory=dict)
    # (d_var, source_var, val, origin)
    d_vars: Dict[Tuple[str, str], list] = field(default_factory=dict)
    dn_vars: Dict[Tuple[str, str], list] = field(default_factory=dict)
    n: Dict[str, Any] = field(default_factory=dict)
    present: Dict[str, Any] = field(default_factory=dict)
    goals: Dict[int, Any] = field(default_factory=dict)
    penalty_item: Any = None
    penalty_dup: Any = None
    filigree_tiebreak: Any = None
    # 4-tuples (tracked_var, val, source_name, origin) — §3.1
    sources_tracking: Dict[Tuple[str, str], list] = field(default_factory=dict)
    upper_bounds: Dict[str, float] = field(default_factory=dict)
    weights: Dict[int, Dict[str, float]] = field(default_factory=dict)
    unmatched: List[str] = field(default_factory=list)

    # --- additions beyond the spec's minimal listing -----------------------
    # Carried so reconcile_solution() can match the spec's (model, tmlim)
    # signature while still recomputing w_vars from game truth (§6 step 2).
    items: List[dict] = field(default_factory=list)
    sets: Dict[str, dict] = field(default_factory=dict)
    augments: List[dict] = field(default_factory=list)
    filigrees: List[dict] = field(default_factory=list)
    required_slots: List[str] = field(default_factory=list)
    entries: List[PriorityEntry] = field(default_factory=list)
    tier_of: Dict[str, int] = field(default_factory=dict)
    caps: Dict[str, float] = field(default_factory=dict)
    sources: Dict[Tuple[str, str], list] = field(default_factory=dict)
    upper_bounds_all: Dict[str, float] = field(default_factory=dict)
    upper_bounds_nofil: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# §3.6 — intra-tier weights
# ---------------------------------------------------------------------------

def compute_tier_weights(entries):
    """{tier: {stat: weight}}; each tier's weights sum to 1.0. §3.6.

    Replaces compute_priority_bias wholesale: the old `value >= 100` gate
    *becomes* tier 1 via the legacy migration in solver.py, and intra-tier rank
    now comes from array order instead of a magnitude the user had to invent.
    """
    by_tier = collections.defaultdict(list)
    for e in entries:
        by_tier[e.tier].append(e)

    out = {}
    for tier, tier_entries in by_tier.items():
        ordered = sorted(tier_entries, key=lambda e: e.order)
        raw = [max(0.6 * (0.4 ** i), WEIGHT_FLOOR) for i in range(len(ordered))]
        total = sum(raw)
        if total <= 0:
            continue
        out[tier] = {e.stat: raw[i] / total for i, e in enumerate(ordered)}
    return out


# ---------------------------------------------------------------------------
# §3.4 — per-stat upper bounds
# ---------------------------------------------------------------------------

class _UBVar:
    """Metadata-only stand-in for an LpVariable, used when upper bounds are
    needed without constructing a PuLP model (the alternatives path, §7.3)."""

    __slots__ = ('ddo_slot', 'ddo_aug', 'ddo_fil_base', 'name', 'varValue')

    def __init__(self, name='ub', ddo_slot=None, ddo_aug=None, ddo_fil_base=None):
        self.name = name
        self.ddo_slot = ddo_slot
        self.ddo_aug = ddo_aug
        self.ddo_fil_base = ddo_fil_base
        self.varValue = None


def _augment_slot_budget(items, required_slots):
    """AUG_SLOT_BUDGET (§3.4): computed structurally, not guessed. For each
    required slot take the largest augment-slot count among items placeable
    there, then sum across slots. Augment-color compatibility is deliberately
    ignored — ignoring it only loosens the bound, which is safe."""
    total = 0
    for slot in required_slots:
        wanted = 'Ring' if slot in ('Ring_1', 'Ring_2') else slot
        best = 0
        for item in items:
            if wanted in item.get('slots', []):
                best = max(best, len(item.get('augments', [])))
        total += best
    return total


def _stacking_family_bound(entries, required_slots, aug_budget):
    """Sum of four capacity-respecting family bounds (§3.4). A naive
    "sum every stacking source" bound is unusable as a normalizer: a stat with
    200 stacking sources would land at z/UB ~ 0.01 while a purely non-stacking
    stat sits at ~1.0 — exactly the scale distortion UB-normalization exists to
    remove."""
    total = 0.0

    # Family 'item': at most one item per slot (optimizer occupancy constraint).
    per_slot = collections.defaultdict(float)
    for val, var, _sname, origin in entries:
        if origin != 'item':
            continue
        slot = getattr(var, 'ddo_slot', None)
        if slot is None or slot not in required_slots:
            continue
        per_slot[slot] = max(per_slot[slot], val)
    total += sum(v for v in per_slot.values() if v > 0)

    # Family 'augment': each augment is usable once; budget is the structural
    # number of augment slots across the gearset.
    per_aug = {}
    for val, var, sname, origin in entries:
        if origin != 'augment':
            continue
        key = getattr(var, 'ddo_aug', None)
        if key is None:
            key = sname
        per_aug[key] = max(per_aug.get(key, val), val)
    if per_aug and aug_budget > 0:
        top = sorted((v for v in per_aug.values() if v > 0), reverse=True)
        total += sum(top[:aug_budget])

    # Family 'filigree': dedupe by base_name (only one variant of a filigree may
    # be slotted), then take the top 10 weapon slots plus the top 5 artifact
    # slots. The same base_name may legitimately fill one of each.
    per_fil = {}
    for val, var, sname, origin in entries:
        if origin != 'filigree':
            continue
        key = getattr(var, 'ddo_fil_base', None)
        if key is None:
            key = str(sname).split(':')[0].strip()
        per_fil[key] = max(per_fil.get(key, val), val)
    if per_fil:
        top = sorted((v for v in per_fil.values() if v > 0), reverse=True)
        total += sum(top[:MAX_WEAPON_FILIGREES])
        total += sum(top[:MAX_ARTIFACT_FILIGREES])

    # Family 'set': multiple m-tiers of one set are legitimately simultaneously
    # active (m*w <= pieces), so every set source can contribute.
    total += sum(val for val, _v, _s, origin in entries if origin == 'set' and val > 0)

    return total


def compute_stat_upper_bounds(sources, items, required_slots, caps, include_filigrees):
    """Per-stat UB. §3.4.

    Call twice: include_filigrees=True for tier-1 stats, False for tier-2+.
    Stats with no sources at all are omitted entirely (EC-4). A stat whose only
    sources are filigrees still appears in the nofil variant, pinned at the
    UB_FLOOR (EC-18 / AC-15).
    """
    aug_budget = _augment_slot_budget(items, required_slots)
    per_stat = collections.defaultdict(float)
    seen = set()

    for (stat, b_type), srclist in sources.items():
        if not srclist:
            continue
        # A stat is "known" as soon as it has any source at all, even if this
        # variant filters every one of them out.
        seen.add(stat)

        eligible = srclist if include_filigrees else [t for t in srclist if t[3] != 'filigree']
        if not eligible:
            continue

        if _is_stacking(b_type):
            ub = _stacking_family_bound(eligible, required_slots, aug_budget)
        else:
            # Exact: Sum(d_var) <= 1 means at most one source is ever credited.
            ub = max(t[0] for t in eligible)

        per_stat[stat] += max(0.0, ub)

    out = {}
    for stat in seen:
        ub = per_stat.get(stat, 0.0)
        if stat in caps:
            # Normalized attainment reaches 1.0 exactly when the cap is met, and
            # the objective stops rewarding over-cap progress. This is what
            # supersedes the old capped_var mechanism (§3.5).
            ub = min(ub, float(caps[stat]))
        out[stat] = max(ub, UB_FLOOR)
    return out


# ---------------------------------------------------------------------------
# §3.1 — source construction with provenance
# ---------------------------------------------------------------------------

def build_sources(items, sets, augments, filigrees, x, y, fw, fm, w_vars):
    """Build `sources[(stat, b_type)] -> [(val, var, source_name, origin)]`.

    `origin` is one of 'item' | 'augment' | 'filigree' | 'set' (§3.1) and drives
    z_nofil construction, the upper-bound families, and the P_dup filter.

    Each var is tagged with the structural metadata the upper-bound computation
    needs (slot / augment index / filigree base name), so the 4-tuple contract
    from §3.1 does not have to grow.
    """
    sources = collections.defaultdict(list)

    for (i, s), var in x.items():
        try:
            setattr(var, 'ddo_slot', s)
        except AttributeError:
            pass
        for stat, b_type, val in items[i]['buffs']:
            # §15.1/§15.4 — weapon-base sources are Weapon1-only. Without this
            # guard, an item legal in both hands would push tuples keyed by both
            # x[(i,'Weapon1')] and x[(i,'Weapon2')] into one non-stacking bucket
            # whose single Sum(d) <= 1 would silently pick whichever hand won.
            if b_type == WEAPON_BASE_BONUS_TYPE and s != WEAPON_BASE_SLOT:
                continue
            sources[(stat, b_type)].append((val, var, items[i]['name'], 'item'))

    for (a, i, c), var in y.items():
        try:
            setattr(var, 'ddo_aug', a)
        except AttributeError:
            pass
        for stat, b_type, val in augments[a]['buffs']:
            sources[(stat, b_type)].append((val, var, augments[a]['name'], 'augment'))

    for idx, f in enumerate(filigrees):
        for holder in (fw, fm):
            var = holder.get(idx)
            if var is None:
                continue
            try:
                setattr(var, 'ddo_fil_base', f['base_name'])
            except AttributeError:
                pass
        for stat, b_type, val in f['buffs']:
            if idx in fw:
                sources[(stat, b_type)].append((val, fw[idx], f['name'], 'filigree'))
            if idx in fm:
                sources[(stat, b_type)].append((val, fm[idx], f['name'], 'filigree'))

    for (k, m), var in w_vars.items():
        for stat, b_type, val in sets[k][m]:
            sources[(stat, b_type)].append((val, var, f"{k} ({m} Piece)", 'set'))

    return sources


def build_ub_sources(items, sets, augments, filigrees, required_slots):
    """Metadata-only mirror of build_sources for callers that need upper bounds
    without a PuLP model (§7.3 — alternatives must use the same UB_s the main
    solve would compute, from the full parsed pool)."""
    x = {}
    for i, item in enumerate(items):
        for slot in item['slots']:
            if slot == 'Ring':
                for rs in ('Ring_1', 'Ring_2'):
                    x[(i, rs)] = _UBVar(ddo_slot=rs)
            else:
                x[(i, slot)] = _UBVar(ddo_slot=slot)

    # Augment-color compatibility is deliberately ignored here (§3.4) — it only
    # loosens the bound, which is safe.
    y = {(a, 0, 'any'): _UBVar(ddo_aug=a) for a in range(len(augments))}

    fw = {idx: _UBVar(ddo_fil_base=f['base_name']) for idx, f in enumerate(filigrees)}
    fm = {idx: _UBVar(ddo_fil_base=f['base_name']) for idx, f in enumerate(filigrees)}

    w_vars = {}
    for k, tiers in sets.items():
        for m in tiers.keys():
            w_vars[(k, m)] = _UBVar()

    return build_sources(items, sets, augments, filigrees, x, y, fw, fm, w_vars)


# ---------------------------------------------------------------------------
# §3 — model construction
# ---------------------------------------------------------------------------

def create_model(items, sets, augments, filigrees, entries, art_slots, required_slots,
                 raid_item_limit=None, pre_equipped=None, pre_filled_augments=None,
                 pre_filled_filigrees=None, calculate_only=False,
                 weapon1_eligible_types=None, weapon2_eligible_types=None, require_weapon2=False):
    """Build the PuLP model once (INV-5). Sets NO objective — every stage does
    that itself via prob.setObjective().

    docs/HARD_REQUIRED_SLOTS_SPEC.md: `weapon1_eligible_types`/
    `weapon2_eligible_types` (each a set/iterable of lowercase weapon_type
    strings, e.g. {"longsword"} or the set of every Slashing weapon type for
    a melee damage-type restriction) additionally restrict that slot's
    candidate pool to those types + the six "craftable" weapon families,
    falling back to types-only if that combination has zero candidates
    (recorded as a note — see _restrict_weapon_slot_to_craftable_family).
    Solver.py computes the actual type set per build_type/weapon_style (melee
    damage-type selection, fixed per-style types for Ranged, a fixed
    Longsword/Large-Shield pair for Tank, etc.) — create_model itself doesn't
    know or care where the set came from. `require_weapon2` forces Weapon2 to
    also always be filled (e.g. runearm_use, a caster weapon_style that needs
    a second weapon, thrower off-hand Kama, or Tank's shield) — the pool
    itself is expected to already be pre-filtered to the right item types via
    allowed_w1_list/allowed_w2_list in parse_items, same as every other
    weapon-style restriction; this parameter only adds the "must be exactly
    one" guarantee on top. Weapon1 itself is unconditionally required
    whenever it's a valid slot — this isn't gated by a parameter, it's a
    standing invariant."""
    if pre_equipped is None:
        pre_equipped = {}
    if pre_filled_augments is None:
        pre_filled_augments = {}
    if pre_filled_filigrees is None:
        pre_filled_filigrees = {}

    entries = list(entries or [])
    tier_of = {e.stat: e.tier for e in entries}
    caps = {e.stat: float(e.cap) for e in entries if e.cap is not None}

    prob = pulp.LpProblem("DDO_Gear_Optimization", pulp.LpMaximize)

    x = {}
    for i, item in enumerate(items):
        for slot in item['slots']:
            if slot == 'Ring':
                x[(i, 'Ring_1')] = pulp.LpVariable(f"x_{i}_Ring_1", cat="Binary")
                x[(i, 'Ring_2')] = pulp.LpVariable(f"x_{i}_Ring_2", cat="Binary")
            else:
                x[(i, slot)] = pulp.LpVariable(f"x_{i}_{slot}", cat="Binary")

    hard_slot_notes = []

    def _restrict_weapon_slot_to_craftable_family(slot, eligible_types):
        """Zeroes out every slot candidate that isn't both (a) one of
        eligible_types (lowercase weapon_type strings) and (b) from one of
        the six craftable families — falling back to (a) alone if that
        combination has zero candidates, and recording a note when it does.
        The already-pre_equipped item for this slot (if any) is always
        exempt — an existing saved gearset, possibly created before this
        feature existed, must never be turned infeasible by a filter
        introduced after the fact (same principle as every other
        pre_equipped bypass in this codebase). No-op if eligible_types is
        falsy or the slot isn't required."""
        nonlocal prob
        if not eligible_types or slot not in required_slots:
            return
        pre_equipped_name = (pre_equipped or {}).get(slot)
        types = {t.strip().lower() for t in eligible_types}
        slot_indices = [i for i, item in enumerate(items) if (i, slot) in x]

        def _matches_type(i):
            return (items[i].get('weapon_type') or '').lower() in types

        candidates = [i for i in slot_indices if _matches_type(i) and items[i].get('craftable_family')]
        if not candidates:
            candidates = [i for i in slot_indices if _matches_type(i)]
            types_desc = '/'.join(sorted(t.title() for t in types))
            hard_slot_notes.append(
                f"No {types_desc} weapon from the required craftable families "
                f"(Dinosaur Bone, Undying Age, Legendary Green Steel, Defiled Reliquary, "
                f"Viktranium Experiment crafting, Den of Vipers) was available for {slot} "
                f"under the current filters — fell back to any {types_desc} weapon."
            )

        candidate_set = set(candidates)
        for i in slot_indices:
            if i in candidate_set:
                continue
            if pre_equipped_name and items[i]['name'] == pre_equipped_name:
                continue
            prob += x[(i, slot)] == 0

    _restrict_weapon_slot_to_craftable_family('Weapon1', weapon1_eligible_types)
    _restrict_weapon_slot_to_craftable_family('Weapon2', weapon2_eligible_types)

    if pre_equipped:
        for slot, eq_name in pre_equipped.items():
            if slot in required_slots:
                for i, item in enumerate(items):
                    if item['name'] == eq_name:
                        if (i, slot) in x:
                            prob += x[(i, slot)] == 1
                        break

    y = {}
    for i, item in enumerate(items):
        color_counts = collections.Counter(item['augments'])
        for color, limit in color_counts.items():
            for aug_idx, aug in enumerate(augments):
                if augment_fits_slot(aug['type'], color, aug['name']):
                    y[(aug_idx, i, color)] = pulp.LpVariable(f"y_{aug_idx}_{i}_{safe_name(color)}", cat="Binary")

    fw = {}
    fm = {}
    for idx, f in enumerate(filigrees):
        fw[idx] = pulp.LpVariable(f"fw_{idx}", cat="Binary")
        fm[idx] = pulp.LpVariable(f"fm_{idx}", cat="Binary")

    matched_pre_filled_augment_count = 0
    unmatched_pre_filled_augments = []
    if pre_filled_augments and pre_equipped:
        for slot, aug_entry in pre_filled_augments.items():
            if slot in required_slots and slot in pre_equipped:
                eq_name = pre_equipped[slot]
                for i, item in enumerate(items):
                    if item['name'] == eq_name:
                        # Support both the new color-keyed dict format
                        # ({color: augment_name}, unambiguous — see docs/PHASE9_PLAN.md)
                        # and the legacy positional list-of-names format from older
                        # saved gearsets (where the color must be inferred).
                        if isinstance(aug_entry, dict):
                            pairs = []
                            for k, v in aug_entry.items():
                                if isinstance(v, list):
                                    for name in v:
                                        pairs.append((k, name))
                                else:
                                    pairs.append((k, v))
                        else:
                            pairs = [(None, aug_name) for aug_name in aug_entry]
                        for known_color, aug_name in pairs:
                            if not aug_name: continue
                            matched_aug_idx = None
                            for idx, a in enumerate(augments):
                                if a['name'] == aug_name:
                                    matched_aug_idx = idx
                                    break
                            if matched_aug_idx is None:
                                unmatched_pre_filled_augments.append(f"{aug_name} ({slot})")
                                continue
                            matched_aug = augments[matched_aug_idx]
                            matched_color = None
                            if known_color and (matched_aug_idx, i, known_color) in y:
                                matched_color = known_color
                            else:
                                color_counts = collections.Counter(item['augments'])
                                for c in color_counts.keys():
                                    if augment_fits_slot(matched_aug['type'], c, matched_aug['name']):
                                        if (matched_aug_idx, i, c) in y:
                                            matched_color = c
                                            break
                            if matched_color:
                                prob += y[(matched_aug_idx, i, matched_color)] == 1
                                matched_pre_filled_augment_count += 1
                            else:
                                unmatched_pre_filled_augments.append(f"{aug_name} ({slot})")
                        break

    if pre_filled_filigrees and filigrees:
        w_fils = pre_filled_filigrees.get('weapon', [])
        a_fils = pre_filled_filigrees.get('artifact', [])

        for fname in w_fils:
            if not fname: continue
            for idx, f in enumerate(filigrees):
                if f['name'] == fname:
                    prob += fw[idx] == 1
                    break

        for fname in a_fils:
            if not fname: continue
            for idx, f in enumerate(filigrees):
                if f['name'] == fname:
                    prob += fm[idx] == 1
                    break

    w_vars = {}
    for k, tiers in sets.items():
        for m in tiers.keys():
            w_vars[(k, m)] = pulp.LpVariable(f"w_{safe_name(k)}_{m}", cat="Binary")

    z = {}

    # INV-7: occupancy is `<= 1`, never `== 1`. Leaving a slot empty is always a
    # legal solution; the consolidation stage (§5) is what actively empties
    # non-load-bearing slots once every tier goal is locked.
    for slot in required_slots:
        prob += pulp.lpSum([x[(i, s)] for (i, s) in x.keys() if s == slot]) <= 1

    if calculate_only:
        # Force all unequipped slots to be empty
        all_possible_slots = set(s for (_, s) in x.keys())
        for slot in all_possible_slots:
            if slot not in required_slots:
                prob += pulp.lpSum([x[(i, s)] for (i, s) in x.keys() if s == slot]) == 0

    for i in range(len(items)):
        prob += pulp.lpSum([x[(i, s)] for (item_idx, s) in x.keys() if item_idx == i]) <= 1

    # Pre-existing carve-out from INV-7: if the pool contains any minor artifact,
    # exactly one must be equipped. A DDO build rule, not a solver preference —
    # do not relax it (EC-26).
    minor_vars = []
    for i, item in enumerate(items):
        if item['minor']:
            minor_vars.extend([x[(item_idx, s)] for (item_idx, s) in x.keys() if item_idx == i])
    if minor_vars:
        prob += pulp.lpSum(minor_vars) == 1

    # docs/HARD_REQUIRED_SLOTS_SPEC.md — Weapon1 must always be filled
    # (unconditional whenever it's a valid slot at all — build-type-agnostic,
    # unlike the eligible-types narrowing above, which is opt-in per
    # build_type/weapon_style and computed by solver.py).
    # Weapon2 is only forced when require_weapon2 is set (runearm_use, or a
    # caster weapon_style that needs a second weapon); the item pool for
    # Weapon2 is expected to already be narrowed to the right type upstream
    # (allowed_w2_list in parse_items), same as the existing Weapon1/Weapon2
    # weapon-style filtering — this constraint only adds "must be exactly
    # one", it doesn't itself pick which weapon type qualifies.
    if 'Weapon1' in required_slots:
        weapon1_vars = [x[(i, 'Weapon1')] for i in range(len(items)) if (i, 'Weapon1') in x]
        if weapon1_vars:
            prob += pulp.lpSum(weapon1_vars) == 1, "Weapon1_Always_Required"

    if require_weapon2 and 'Weapon2' in required_slots:
        weapon2_vars = [x[(i, 'Weapon2')] for i in range(len(items)) if (i, 'Weapon2') in x]
        if weapon2_vars:
            prob += pulp.lpSum(weapon2_vars) == 1, "Weapon2_Required"

    # calculate_only is a strict reproduction of a saved/pre_equipped gearset,
    # not a search — the raid-item cap is a search-time preference, not a fact
    # about whether that gearset can exist. Enforcing it here means a gearset
    # saved under an older/looser raid_item_limit (or hand-edited, or saved
    # before a limit was set) becomes permanently uncalculatable even though
    # every item in it is individually valid.
    if not calculate_only and raid_item_limit is not None and raid_item_limit >= 0:
        raid_vars = []
        for i, item in enumerate(items):
            if item.get('is_raid'):
                raid_vars.extend([x[(item_idx, s)] for (item_idx, s) in x.keys() if item_idx == i])
        if raid_vars:
            prob += pulp.lpSum(raid_vars) <= raid_item_limit, "Max_Raid_Items"

    for i, item in enumerate(items):
        color_counts = collections.Counter(item['augments'])
        for color, limit in color_counts.items():
            valid_y = [y[(a, item_idx, c)] for (a, item_idx, c) in y.keys() if item_idx == i and c == color]
            item_is_equipped = pulp.lpSum([x[(item_idx, s)] for (item_idx, s) in x.keys() if item_idx == i])
            if valid_y:
                prob += pulp.lpSum(valid_y) <= limit * item_is_equipped

    if not calculate_only:
        # Prevents the search from slotting the identical augment into every
        # compatible color across the whole gearset. Skipped in calculate_only:
        # augments like Solar/Lunar Gems are craftable/purchasable in multiple
        # copies (no bind-unique restriction), so a saved gearset can legally
        # have the same augment name in two different slots (confirmed against
        # a real saved .ddogearset — see docs/PHASE10_HANDOFF.md). Enforcing
        # this here would force pre_filled_augments' two matching `y == 1`
        # constraints for the same aug_idx to both hold while also capping
        # their sum at 1 — an unsatisfiable pair that fails calculate_only
        # outright instead of just under-crediting the duplicate.
        for a in range(len(augments)):
            prob += pulp.lpSum([y[(aug_idx, i, c)] for (aug_idx, i, c) in y.keys() if aug_idx == a]) <= 1

    if calculate_only:
        # To strictly compute what was passed, force sum of y to equal the number
        # of pre-filled augments that were actually resolved to a real (augment,
        # item, color) triple above — NOT the raw count of payload entries. An
        # entry can legitimately fail to resolve (unknown/renamed augment name,
        # or — historically, before augment_fits_slot existed — any augment in a
        # Colorless slot); counting those anyway forced the model to place extra
        # unrelated augments to make the numbers balance, and when no compatible
        # slot existed for that surplus, the whole calculate-only solve went
        # infeasible instead of just not crediting the one bad entry.
        prob += pulp.lpSum(y.values()) == matched_pre_filled_augment_count

    if filigrees:
        base_name_groups = collections.defaultdict(list)
        for idx, f in enumerate(filigrees):
            base_name_groups[f['base_name']].append(idx)

        for base_name, idx_list in base_name_groups.items():
            if len(idx_list) > 1:
                prob += pulp.lpSum([fw[idx] for idx in idx_list]) <= 1
                prob += pulp.lpSum([fm[idx] for idx in idx_list]) <= 1

        prob += pulp.lpSum(fw.values()) <= MAX_WEAPON_FILIGREES

        if calculate_only:
            total_w_fils = len([f for f in pre_filled_filigrees.get('weapon', []) if f]) if pre_filled_filigrees else 0
            total_m_fils = len([f for f in pre_filled_filigrees.get('artifact', []) if f]) if pre_filled_filigrees else 0
            prob += pulp.lpSum(fw.values()) == total_w_fils
            prob += pulp.lpSum(fm.values()) == total_m_fils

        max_fm_slots_expr = []
        for i, item in enumerate(items):
            if item['minor']:
                slots_for_item = 3
                if item['name'] == "Epic Voice of the Master":
                    slots_for_item = 1
                elif item.get('ml', 0) >= 33:
                    slots_for_item = 5
                elif item.get('ml', 0) >= 31:
                    slots_for_item = 4
                elif item.get('ml', 0) >= 30:
                    slots_for_item = 3

                item_equipped_var = pulp.lpSum([x[(item_idx, s)] for (item_idx, s) in x.keys() if item_idx == i])
                max_fm_slots_expr.append(slots_for_item * item_equipped_var)

        if max_fm_slots_expr:
            prob += pulp.lpSum(fm.values()) <= pulp.lpSum(max_fm_slots_expr)
        else:
            prob += pulp.lpSum(fm.values()) <= 0

    for k, tiers in sets.items():
        pieces = pulp.lpSum([x[(i, s)] for (i, s) in x.keys() if k in items[i]['sets']])
        if filigrees:
            pieces += pulp.lpSum([fw[idx] + fm[idx] for idx, f in enumerate(filigrees) if f['set'] == k])

        for m in tiers.keys():
            prob += m * w_vars[(k, m)] <= pieces

    # ---- sources, upper bounds, usable priorities -------------------------
    sources = build_sources(items, sets, augments, filigrees, x, y, fw, fm, w_vars)

    ub_all = compute_stat_upper_bounds(sources, items, required_slots, caps, True)
    ub_nofil = compute_stat_upper_bounds(sources, items, required_slots, caps, False)

    # EC-4: a priority stat with zero sources in the parsed pool is excluded
    # from every goal, from tier-4 breadth, and from weight normalization (so
    # the remaining weights still sum to 1).
    usable_entries = [e for e in entries if e.stat in ub_all]
    unmatched = [e.stat for e in entries if e.stat not in ub_all]
    weights = compute_tier_weights(usable_entries)

    flat_weights = {}
    for tier_map in weights.values():
        flat_weights.update(tier_map)

    notes = list(hard_slot_notes)

    if unmatched_pre_filled_augments:
        notes.append(
            "Pre-filled augment(s) not credited (no matching augment data found): "
            + ", ".join(unmatched_pre_filled_augments))

    # §15.3 / EC-29: the composite double-counts against its components. The
    # frontend is responsible for blocking the combination; the backend only
    # surfaces it rather than silently computing both.
    listed = {e.stat.lower() for e in entries}
    if WEAPON_STAT_COMPOSITE in listed and (listed & WEAPON_COMPOSITE_COMPONENTS):
        notes.append(
            "'weapon base damage' is listed alongside one of its components "
            "('weapon damage' / 'base damage dice'); the two overlap and the "
            "combination should be blocked in the priority picker.")

    # ---- z (display truth, INV-1) and z_nofil (§3.3) -----------------------
    source_counter = 0
    z_counter = 0
    sources_tracking = collections.defaultdict(list)
    d_vars = {}
    dn_vars = {}
    z_nofil = {}

    for (stat, b_type), srclist in sources.items():
        z_counter += 1
        z_var = pulp.LpVariable(f"z_{z_counter}_{safe_name(stat)}_{safe_name(b_type)}", lowBound=0)
        z[(stat, b_type)] = z_var

        if _is_stacking(b_type):
            expr = []
            for val, var, sname, origin in srclist:
                expr.append(val * var)
                sources_tracking[(stat, b_type)].append((var, val, sname, origin))
            prob += z_var == pulp.lpSum(expr)
        else:
            deltas = []
            entry_list = []
            for val, var, sname, origin in srclist:
                d_var = pulp.LpVariable(f"d_{source_counter}", cat="Binary")
                source_counter += 1
                prob += d_var <= var
                deltas.append(val * d_var)
                entry_list.append((d_var, var, val, origin))
                sources_tracking[(stat, b_type)].append((d_var, val, sname, origin))

            prob += pulp.lpSum([e[0] for e in entry_list]) <= 1
            prob += z_var == pulp.lpSum(deltas)
            d_vars[(stat, b_type)] = entry_list

        # z_nofil is materialized only where it can differ from z: the stat is
        # tier >= 2 AND at least one of its sources is a filigree. Otherwise it
        # aliases z outright — no extra variables, no extra constraints.
        tier = tier_of.get(stat)
        has_filigree = any(t[3] == 'filigree' for t in srclist)
        if tier is None or tier < 2 or not has_filigree:
            z_nofil[(stat, b_type)] = z_var
            continue

        sub = [t for t in srclist if t[3] != 'filigree']
        zn_var = pulp.LpVariable(f"zn_{z_counter}_{safe_name(stat)}_{safe_name(b_type)}", lowBound=0)
        if not sub:
            prob += zn_var == 0
        elif _is_stacking(b_type):
            prob += zn_var == pulp.lpSum([val * var for val, var, _s, _o in sub])
        else:
            # A SEPARATE d' family is required: the max over the non-filigree
            # subset differs from the max over the full set.
            dn_list = []
            for val, var, _sname, origin in sub:
                dn_var = pulp.LpVariable(f"dn_{source_counter}", cat="Binary")
                source_counter += 1
                prob += dn_var <= var
                dn_list.append((dn_var, var, val, origin))
            prob += pulp.lpSum([e[0] for e in dn_list]) <= 1
            prob += zn_var == pulp.lpSum([val * dv for dv, _v, val, _o in dn_list])
            dn_vars[(stat, b_type)] = dn_list

        z_nofil[(stat, b_type)] = zn_var

    # ---- n_s: normalized attainment (§3.5, supersedes capped_var) ----------
    by_stat = collections.defaultdict(list)
    for (stat, b_type) in z.keys():
        by_stat[stat].append(b_type)

    n = {}
    upper_bounds = {}
    for e in usable_entries:
        stat = e.stat
        if stat in n:
            continue
        tier = e.tier
        src = z if tier == 1 else z_nofil
        total = pulp.lpSum([src[(stat, bt)] for bt in by_stat.get(stat, [])])
        ub = ub_all[stat] if tier == 1 else ub_nofil.get(stat, UB_FLOOR)

        n_var = pulp.LpVariable(f"n_{safe_name(stat)}", lowBound=0, upBound=1.0)
        # Written multiplied out — never divide inside the LP.
        prob += ub * n_var <= total
        n[stat] = n_var
        upper_bounds[stat] = ub

        if tier >= 2 and ub <= UB_FLOOR and ub_all.get(stat, 0.0) > UB_FLOOR:
            notes.append(
                f"'{stat}' (tier {tier}) is only obtainable from filigrees, which "
                f"tiers 2+ do not consider; it contributes 0 to its tier goal.")

    # ---- tier-4 breadth binaries (§3.7) -----------------------------------
    present = {}
    for e in usable_entries:
        if e.tier != 4 or e.stat in present:
            continue
        stat = e.stat
        p_var = pulp.LpVariable(f"present_{safe_name(stat)}", cat="Binary")

        theta = WEAPON_TIER4_BASELINES.get(stat.lower())
        if theta is not None:
            # §15.6 — a weapon is essentially always equipped, so a bare
            # presence check would make present_s trivially 1. Use the corpus
            # baseline over the display-truth total instead.
            total = pulp.lpSum([z[(stat, bt)] for bt in by_stat.get(stat, [])])
            prob += theta * p_var <= total
        else:
            # "At least one credited source". Only the <= direction is enforced:
            # stage 4 maximizes M_TIER4 * Sum(present), so the solver sets
            # present_s = 1 wherever it is legal. Consequence: present_s is an
            # objective-side breadth indicator, and after stages where tier 4 is
            # not in the objective its value is only whatever the lock forces.
            indicators = []
            for bt in by_stat.get(stat, []):
                key = (stat, bt)
                if _is_stacking(bt):
                    indicators.extend([var for val, var, _s, _o in sources[key] if val > 0])
                else:
                    # Use the DISPLAY d family, not d', so a filigree can credit
                    # a tier-4 stat.
                    indicators.extend([dv for dv, _v, val, _o in d_vars.get(key, []) if val > 0])
            if indicators:
                prob += p_var <= pulp.lpSum(indicators)
            else:
                prob += p_var == 0
        present[stat] = p_var

    # ---- goal expressions G_t (§3.7) --------------------------------------
    goals = {}
    for tier, tier_weights in weights.items():
        magnitude = pulp.lpSum([w * n[s] for s, w in tier_weights.items() if s in n])
        if tier == 4:
            breadth_scale = 1.0 + sum(tier_weights.values())  # == 2.0 by construction
            breadth = pulp.lpSum([present[s] for s in tier_weights if s in present])
            goals[tier] = breadth_scale * breadth + magnitude
        else:
            goals[tier] = magnitude

    # ---- consolidation penalty P (§3.9) -----------------------------------
    penalty_item = pulp.lpSum(list(x.values()))

    # (var - d_var) is exactly 1 when a source is equipped but contributes
    # nothing — a precise linear "wasted stat instance" indicator needing zero
    # new variables.
    #
    # Two mandatory restrictions:
    #   1. Non-stacking bonus types only — d_vars holds exactly those. For
    #      stacking/Mythic/Reaper every equipped source legitimately adds to the
    #      total, and penalizing multiplicity there fights the maximization the
    #      user asked for.
    #   2. origin != 'set'. A set-bonus w_var costs no slot and is free to sit
    #      at 0; penalizing it would let consolidation suppress a harmless-but-
    #      real set bonus and permanently destroy displayed stats.
    #
    # The orchestrator's per-stat rho_s weight is dropped: every source in
    # `sources` already belongs to a user-listed priority stat (they only exist
    # because normalize_stat_name matched), so rho_s == 1 for all of them.
    #
    # Known false positive, flagged not hidden: an item equipped for stat X that
    # incidentally carries a redundant Enhancement bonus to stat Y is charged
    # for the duplicate even though nothing wasteful happened. Accepted — the
    # linear form is cheap and a `useful_i` binary per item is not worth the
    # model growth.
    dup_terms = []
    for entry_list in d_vars.values():
        for d_var, src_var, _val_, origin in entry_list:
            if origin in ('item', 'augment', 'filigree'):
                dup_terms.append(src_var - d_var)
    penalty_dup = pulp.lpSum(dup_terms)

    # ---- filigree tie-break B (§3.8) --------------------------------------
    # Replaces the deleted FILIGREE_BIAS_SCALE block. Filigrees are already
    # first-class sources in `sources`, so stage 1 values them directly through
    # z; keeping the old bias term would double-count every filigree's tier-1
    # contribution. B is present ONLY in the consolidation stage, after every
    # G_t is locked, so it can only fill otherwise-free filigree slots (INV-4).
    filigree_tiebreak = pulp.lpSum([])
    if filigrees:
        scores = []
        for idx, f in enumerate(filigrees):
            score = 0.0
            for stat, b_type, val in f['buffs']:
                w = flat_weights.get(stat)
                ub = upper_bounds.get(stat)
                if w and ub:
                    score += w * (val / ub)
            scores.append(score)
        max_score = max(scores) if scores else 0.0
        if max_score > 0:
            filigree_tiebreak = pulp.lpSum([
                (score / max_score) * (fw[idx] + fm[idx])
                for idx, score in enumerate(scores) if score > 0
            ])

    # create_model deliberately sets NO objective (INV-5): each stage installs
    # its own via prob.setObjective().

    return Model(
        prob=prob, x=x, y=y, fw=fw, fm=fm, w_vars=w_vars,
        z=z, z_nofil=z_nofil, d_vars=d_vars, dn_vars=dn_vars,
        n=n, present=present, goals=goals,
        penalty_item=penalty_item, penalty_dup=penalty_dup,
        filigree_tiebreak=filigree_tiebreak,
        sources_tracking=sources_tracking,
        upper_bounds=upper_bounds, weights=weights, unmatched=unmatched,
        items=items, sets=sets, augments=augments, filigrees=filigrees,
        required_slots=list(required_slots), entries=entries,
        tier_of=tier_of, caps=caps, sources=dict(sources),
        upper_bounds_all=ub_all, upper_bounds_nofil=ub_nofil,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# §4 — solve driver helpers
# ---------------------------------------------------------------------------

def resolve_glpsol_path():
    """GLPSOL_PATH is set by app.go's runSolver() to the bundled glpsol binary
    it just extracted (alongside its shared libraries — see extractSolver in
    app.go and build_releases.sh's per-platform staging). Falling back to a
    PATH lookup keeps `python solver.py` usable directly from a dev checkout,
    without the Go app in the loop, as long as GLPK is installed locally.
    Returns None if neither resolves to anything."""
    env_path = os.environ.get("GLPSOL_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    return shutil.which("glpsol")


def _glpk_cmd(tmlim=None, msg=1):
    """Centralizes the GLPK invocation formerly duplicated at two call sites.

    glpsol's path, and the directory solver_progress.log is written into,
    both come from resolve_glpsol_path() rather than a hardcoded install path
    / the process's CWD — a hardcoded "/opt/homebrew/bin/glpsol" only ever
    worked on one specific Homebrew-on-Apple-Silicon machine, and CWD is not
    guaranteed writable once this runs from an installed app bundle. Callers
    that can fail fast should call resolve_glpsol_path() themselves first
    (see solver.py's main()) — this function still raises if it's missing,
    but _solve()'s broad except would otherwise swallow that into a generic
    "no feasible solution" rather than surfacing the real cause.
    """
    glpsol_path = resolve_glpsol_path()
    if not glpsol_path:
        raise RuntimeError(
            "glpsol not found. Set GLPSOL_PATH, or install GLPK so 'glpsol' is on PATH.")
    log_dir = os.path.dirname(glpsol_path) or "."
    options = ["--log", os.path.join(log_dir, "solver_progress.log")]
    if tmlim:
        # GLPK's --tmlim takes integer seconds.
        options += ["--tmlim", str(int(max(1, round(tmlim))))]
    return pulp.GLPK_CMD(msg=msg, path=glpsol_path, options=options)


def _has_incumbent(prob):
    """True iff every LpVariable carries a value.

    PuLP's mapping of a --tmlim-truncated GLPK run to LpStatus varies by
    version, so `status == 1` is not trustworthy (§4.6). This explicit test is.
    """
    for v in prob.variables():
        if v.varValue is None:
            return False
    return True


def _snapshot(prob):
    """var.name -> varValue. prob.solve() overwrites varValue on every variable,
    so a failed stage would otherwise destroy the previous solution."""
    return {v.name: v.varValue for v in prob.variables()}


def _restore(prob, snap):
    if not snap:
        return
    for v in prob.variables():
        if v.name in snap:
            v.varValue = snap[v.name]


def _solve(prob, tmlim):
    try:
        return prob.solve(_glpk_cmd(tmlim))
    except Exception:
        return pulp.LpStatusNotSolved


def _lock_tolerance(value):
    """§4.4 — float hygiene only. NOT the (out-of-scope) tier_slack knob.
    Do not widen this to make consolidation more aggressive: it would silently
    change tier semantics.

    This is the tolerance BUILT INTO the constraint (`G_t >= V_t - tol`). The
    post-solve self-check must use _lock_check_tolerance() instead — see there.
    """
    return max(1e-5, abs(value) * 1e-6)


# Numerical headroom the post-solve self-check needs ON TOP of the tolerance
# already baked into the tier_lock_t constraint. Two independent sources, both
# strictly numerical (neither one relaxes tier semantics):
#
#   * GLPK's own primal feasibility tolerance (--tol_bnd, default 1e-7): a row
#     is "satisfied" once it is within that of its bound, so a returned solution
#     may sit up to ~1e-7 below the lock's RHS in GLPK's own arithmetic.
#   * The solution file round trip: glpsol's -w writer emits 12 significant
#     digits, so every n_s / present_s value we read back carries ~1e-12
#     relative error, and G_t recomputed from them inherits it.
#
# 1e-6 absolute keeps a 10x margin over the first and dwarfs the second, while
# staying 10x TIGHTER than _lock_tolerance's own 1e-5 floor — the worst-case
# accepted regression moves from 1e-5 to 1.1e-5 on goals of magnitude ~1, which
# is still pure float hygiene and not a semantic change.
LOCK_CHECK_SLACK_ABS = 1e-6
LOCK_CHECK_SLACK_REL = 1e-9


def _lock_check_tolerance(value):
    """Tolerance for verifying a previously locked tier still holds (§4.6).

    MUST be strictly looser than _lock_tolerance(). The lock constraint is
    `G_t >= V_t - _lock_tolerance(V_t)`, and every later stage maximizes a
    different goal, so the solver deliberately spends that entire slack and
    parks G_t exactly ON the bound. Checking with the same tolerance therefore
    tests `recomputed_G_t < RHS` against a value the solver set equal to RHS —
    a zero-margin comparison whose outcome is decided by whether the 12-digit
    round trip through GLPK's solution file rounded the last digit up or down.
    That coin flip, not any real regression, was the source of the spurious
    "lock_violation" statuses (each one discarded a good incumbent and left the
    run degraded).
    """
    return _lock_tolerance(value) + max(LOCK_CHECK_SLACK_ABS,
                                        abs(value) * LOCK_CHECK_SLACK_REL)


def _first_lock_violation(model, locked):
    """The lowest locked tier whose goal no longer holds, or None."""
    for j in sorted(locked):
        if _goal_value(model.goals[j]) < locked[j] - _lock_check_tolerance(locked[j]):
            return j
    return None


def _goal_value(expr):
    v = pulp.value(expr)
    return 0.0 if v is None else float(v)


def _fold_objective(model, pending):
    """§4.6 — carry every not-yet-locked tier goal, most significant first."""
    if len(pending) == 1:
        return model.goals[pending[0]]
    count = len(pending)
    return pulp.lpSum([
        (M_FOLD ** (count - i - 1)) * model.goals[t]
        for i, t in enumerate(pending)
    ])


def _tie_penalty(model):
    return LAMBDA_ITEM_TIE * model.penalty_item + LAMBDA_DUP_TIE * model.penalty_dup


def _stage_budgets(tiers, max_search_time):
    """§4.5 — one total wall-clock budget shared across all stages."""
    total = max_search_time if max_search_time and max_search_time > 0 else DEFAULT_SEARCH_TIME
    total = _clamp(float(total), MIN_TOTAL_BUDGET, MAX_TOTAL_BUDGET)
    cons = _clamp(CONSOLIDATION_SHARE * total, CONSOLIDATION_MIN, CONSOLIDATION_MAX)
    tier_budget = max(0.0, total - cons)

    if not tiers:
        return [], cons, total

    shares = [TIER_SHARES[t - 1] if 1 <= t <= len(TIER_SHARES) else TIER_SHARES[-1] for t in tiers]
    share_sum = sum(shares) or 1.0
    shares = [s / share_sum for s in shares]

    if tier_budget < STAGE_FLOOR_SECONDS * len(tiers):
        # Degenerate low-budget case: even split, no floor.
        budgets = [tier_budget / len(tiers)] * len(tiers)
    else:
        budgets = [max(STAGE_FLOOR_SECONDS, s * tier_budget) for s in shares]

    return budgets, cons, total


def _equipped_count(model):
    return sum(1 for v in model.x.values() if _val(v) > 0.5)


def solve_tiered(model, max_search_time, out_file):
    """Run the tier stages (§4), the consolidation stage (§5) and the
    reconciliation LP (§6). Leaves the final variable values on `model`.

    Returns the tierReport dict described in §9, or
    {"failed": True, "reason": ...} when stage 1 is genuinely infeasible.

    Why emptying a slot can never violate a not-yet-locked tier's eventual lock
    (§14.4) — three points, stated here so this does not resurface as an open
    question:

      1. V_k is MEASURED, not aspirational. It is recorded from the stage's own
         solved variable values, so whatever slots were empty when stage k
         solved are simply part of the solution that produced V_k.
      2. Locks never constrain which items are equipped. Every tier_lock_t is
         `G_t >= V_t - tol_t`, an inequality over n_s (and present_s); slot
         occupancy is unconstrained by any lock, so a later stage is always free
         to re-fill a slot or reach the same G_t via a different item set.
      3. No item is ever dropped before every tier is locked. Consolidation runs
         strictly after the last tier stage, with ALL tier_lock_* constraints
         simultaneously present, so every removal is validated against every
         tier at once.

    Model reuse note: pulp.GLPK_CMD is file-based and writes a fresh LP on every
    solve(), so building the model once saves CONSTRUCTION time only. There is
    no warm start across stages. If solve time comes to dominate, the known next
    lever is PULP_CBC_CMD, which supports warmStart — out of scope here.
    """
    prob = model.prob
    report = {
        "stages": [],
        "consolidation": None,
        "reconciliation": None,
        "totalElapsedSeconds": 0.0,
        "degraded": False,
        "notes": list(model.notes),
    }

    tiers = sorted(model.goals.keys())
    budgets, cons_budget, total_budget = _stage_budgets(tiers, max_search_time)

    if out_file:
        out_file.write(f"Search budget: {total_budget:.1f}s total "
                       f"({len(tiers)} tier stage(s), {cons_budget:.1f}s consolidation reserve)\n")

    run_start = time.time()
    carry = 0.0
    pending = []
    locked = {}
    snap = None
    abort_stages = False

    for k, tier in enumerate(tiers):
        if abort_stages:
            break
        pending.append(tier)
        budget = budgets[k] + carry

        prob.setObjective(_fold_objective(model, pending) - _tie_penalty(model))

        t0 = time.time()
        status = _solve(prob, budget)
        elapsed = time.time() - t0
        carry = max(0.0, budget - elapsed)

        stage = {
            "tier": tier,
            "goalValue": None,
            "status": "unknown",
            "proven": False,
            "budgetSeconds": round(budget, 2),
            "elapsedSeconds": round(elapsed, 2),
            "folded": [t for t in pending if t != tier],
        }

        if status == pulp.LpStatusInfeasible:
            if k == 0:
                return {"failed": True,
                        "reason": "Solver could not find a valid combination of gear that "
                                  "satisfies all of your constraints. Try clearing some locked "
                                  "items or reducing requirements."}
            # Should be impossible: the previous solution remains feasible.
            msg = (f"Tier {tier} stage reported INFEASIBLE despite a feasible incumbent from "
                   f"an earlier stage. Restoring the last-good solution and skipping the "
                   f"remaining tier stages.")
            if out_file:
                out_file.write("!! " + msg + "\n")
            report["notes"].append(msg)
            report["degraded"] = True
            stage["status"] = "infeasible"
            report["stages"].append(stage)
            _restore(prob, snap)
            abort_stages = True
            continue

        incumbent = _has_incumbent(prob)
        if not incumbent:
            stage["status"] = "no_incumbent"
            report["stages"].append(stage)
            report["degraded"] = True
            note = (f"Tier {tier} stage produced no incumbent within its {budget:.1f}s budget; "
                    f"its goal was folded into the next stage.")
            if out_file:
                out_file.write("!! " + note + "\n")
            report["notes"].append(note)
            _restore(prob, snap)
            if k == len(tiers) - 1 and snap is None:
                return {"failed": True,
                        "reason": "Solver ran out of time before finding any feasible gearset. "
                                  "Try increasing the search time or relaxing constraints."}
            # `pending` keeps this tier; it gets folded into the next stage.
            continue

        # Guard (§4.6): recompute every previously locked goal and verify it
        # still holds. Firing here means GLPK returned something that misses the
        # lock by more than any numerical explanation allows, so the incumbent is
        # not trustworthy — treat the stage as "no incumbent". The check runs at
        # _lock_check_tolerance(), NOT _lock_tolerance(); see the former's
        # docstring for why using the constraint's own tolerance here made this
        # guard fire on essentially every stage.
        violated = _first_lock_violation(model, locked)
        if violated is not None:
            note = (f"Tier {tier} stage returned a solution violating the tier {violated} lock "
                    f"(unexplained solver deviation); restored the last-good solution.")
            if out_file:
                out_file.write("!! " + note + "\n")
            report["notes"].append(note)
            report["degraded"] = True
            stage["status"] = "lock_violation"
            report["stages"].append(stage)
            _restore(prob, snap)
            continue

        stage["proven"] = (status == pulp.LpStatusOptimal)
        stage["status"] = "optimal" if stage["proven"] else "time_limited"
        stage["goalValue"] = round(_goal_value(model.goals[tier]), 6)

        # Lock every pending tier at its ACHIEVED value (never a target), on the
        # goal expression rather than the objective (INV-3).
        for t in pending:
            v = _goal_value(model.goals[t])
            locked[t] = v
            name = f"tier_lock_{t}"
            if name not in prob.constraints:
                prob += (model.goals[t] >= v - _lock_tolerance(v), name)
        pending = []
        snap = _snapshot(prob)
        report["stages"].append(stage)

    if snap is None and tiers:
        return {"failed": True,
                "reason": "Solver could not find a valid combination of gear that satisfies "
                          "all of your constraints. Try clearing some locked items or reducing "
                          "requirements."}

    # ---- §5 consolidation stage ------------------------------------------
    if snap is not None:
        pre_cons = snap
        pre_cons_items = _equipped_count(model)
        cons_budget += carry
        prob.setObjective(
            -(LAMBDA_ITEM * model.penalty_item + LAMBDA_DUP * model.penalty_dup)
            + EPS_FIL * model.filigree_tiebreak
        )
        t0 = time.time()
        status = _solve(prob, cons_budget)
        elapsed = time.time() - t0

        cons = {"status": "optimal" if status == pulp.LpStatusOptimal else "time_limited",
                "elapsedSeconds": round(elapsed, 2),
                "itemsEquipped": 0, "duplicateSources": 0}

        ok = _has_incumbent(prob) and status != pulp.LpStatusInfeasible
        if ok and _first_lock_violation(model, locked) is not None:
            ok = False
        if ok and pre_cons_items > 0 and _equipped_count(model) == 0:
            # EC-27 — structurally unreachable in practice; defensive only.
            report["notes"].append("Consolidation produced an empty gearset; restored the "
                                   "pre-consolidation solution.")
            report["degraded"] = True
            ok = False

        if not ok:
            # Consolidation is a quality improvement, never a correctness
            # requirement (EC-23).
            cons["status"] = "restored"
            _restore(prob, pre_cons)
        else:
            snap = _snapshot(prob)

        cons["itemsEquipped"] = _equipped_count(model)
        cons["duplicateSources"] = int(round(_goal_value(model.penalty_dup)))
        report["consolidation"] = cons

    # NOTE: w_vars are not in the consolidation objective, so GLPK may return
    # them at arbitrary feasible values (including 0). This is deliberately
    # harmless — §6 recomputes them deterministically before anything is
    # displayed. It is not a bug.

    # ---- §6 reconciliation LP --------------------------------------------
    t0 = time.time()
    rec_ok = reconcile_solution(model)
    report["reconciliation"] = {
        "status": "optimal" if rec_ok else "failed",
        "elapsedSeconds": round(time.time() - t0, 2),
    }
    if not rec_ok:
        # EC-24 — should be impossible (a pure LP over a feasible point).
        report["degraded"] = True
        report["notes"].append("Reconciliation LP failed; displayed stats were taken from the "
                               "pre-reconciliation solution.")
        _restore(model.prob, snap)

    report["totalElapsedSeconds"] = round(time.time() - run_start, 2)
    return report


# ---------------------------------------------------------------------------
# §6 — post-solve reconciliation
# ---------------------------------------------------------------------------

def _fix_binary(var):
    if var is None or var.varValue is None:
        return
    value = float(round(var.varValue))
    var.lowBound = value
    var.upBound = value
    var.varValue = value


def reconcile_solution(model, tmlim=RECONCILE_TMLIM):
    """§6 — fix the structural binaries, recompute w_vars deterministically, then
    re-solve maximizing Sum(z). Mutates variable values in place.

    Problem being fixed: the only pressure pushing a non-stacking d_var to 1 is
    the objective, so any stat with a zero objective coefficient leaves its z at
    0 and realizedStats/allEffects under-report it. That is latent in a single
    weighted solve but acute in every tier stage where only one tier is in the
    objective, and in the consolidation stage where no goal is.
    """
    prob = model.prob

    # 1. Fix the structural binaries to their final solved values.
    for var in list(model.x.values()) + list(model.y.values()) + \
            list(model.fw.values()) + list(model.fm.values()) + list(model.present.values()):
        _fix_binary(var)
    for entry_list in model.dn_vars.values():
        for dn_var, _src, _val_, _origin in entry_list:
            _fix_binary(dn_var)

    # 2. Recompute every w_vars[(k, m)] deterministically from the now-fixed
    #    x / fw / fm. This is exact game truth and removes the LP's freedom to
    #    leave w fractional or zero.
    equipped = [i for (i, s), var in model.x.items() if _val(var) > 0.5]
    for (k, m), w_var in model.w_vars.items():
        pieces = 0
        for i in equipped:
            if k in model.items[i].get('sets', []):
                pieces += 1
        for idx, f in enumerate(model.filigrees):
            if f.get('set') != k:
                continue
            if idx in model.fw and _val(model.fw[idx]) > 0.5:
                pieces += 1
            if idx in model.fm and _val(model.fm[idx]) > 0.5:
                pieces += 1
        value = 1.0 if pieces >= m else 0.0
        w_var.lowBound = value
        w_var.upBound = value
        w_var.varValue = value

    # 3. Leave free: all display d vars, all z, all z_nofil, all n_s.
    # 4. Maximize the sum of every z variable. `sources` is populated only from
    #    buffs that normalize_stat_name matched against the user's priority
    #    list, so the set of all z vars is already exactly the priority stats'
    #    z vars — no additional filtering needed.
    # 5. All tier_lock_* constraints stay in place; feasibility is guaranteed
    #    because every lock is a >= on an expression non-decreasing in z.
    #
    # Sum(n_s) rides along in the objective. n_s is a pure follower — its only
    # constraint is UB_s * n_s <= Z_s, so it can never trade against z — but
    # without a coefficient the solver is free to leave it at the lock's
    # tolerance floor, which would make the reported tierScores read
    # V_t - tol_t instead of the value actually achieved.
    prob.setObjective(pulp.lpSum(list(model.z.values()) + list(model.n.values())))
    status = _solve(prob, tmlim)

    # 6. Maximizing Sum(z) with all equipment fixed inflates nothing: the
    #    max-over-non-stacking-sources rule IS the DDO stacking rule, so the LP
    #    optimum is precisely the character's true total.
    return status != pulp.LpStatusInfeasible and _has_incumbent(prob)


# ---------------------------------------------------------------------------
# §7 — alternatives (enumeration, no ILP for item selection)
# ---------------------------------------------------------------------------

def _slot_matches(item, slot):
    wanted = 'Ring' if slot in ('Ring_1', 'Ring_2') else slot
    return wanted in item.get('slots', [])


def _collect_contributions(equipped, aug_list, fil_weapon, fil_artifact, sets):
    """Direct arithmetic against a fixed gearset — the same computation
    calculate_only mode performs. Returns {(stat, b_type): [(val, origin)]}."""
    contrib = collections.defaultdict(list)

    for slot, item in equipped:
        for stat, b_type, val in item['buffs']:
            if b_type == WEAPON_BASE_BONUS_TYPE and slot != WEAPON_BASE_SLOT:
                continue
            contrib[(stat, b_type)].append((val, 'item'))

    for aug in aug_list:
        for stat, b_type, val in aug['buffs']:
            contrib[(stat, b_type)].append((val, 'augment'))

    for f in list(fil_weapon) + list(fil_artifact):
        for stat, b_type, val in f['buffs']:
            contrib[(stat, b_type)].append((val, 'filigree'))

    # Set bonuses recomputed with the candidate substituted.
    piece_counts = collections.Counter()
    for _slot, item in equipped:
        for k in item.get('sets', []) or []:
            piece_counts[k] += 1
    for f in list(fil_weapon) + list(fil_artifact):
        if f.get('set'):
            piece_counts[f['set']] += 1

    for k, tiers in sets.items():
        pieces = piece_counts.get(k, 0)
        for m, buffs in tiers.items():
            if pieces >= m:
                for stat, b_type, val in buffs:
                    contrib[(stat, b_type)].append((val, 'set'))

    return contrib


def _resolve_totals(contrib, exclude_filigrees=False):
    """Sum for stacking bonus types, max for non-stacking — the DDO rule."""
    totals = collections.defaultdict(float)
    for (stat, b_type), entries in contrib.items():
        vals = [v for v, o in entries if not (exclude_filigrees and o == 'filigree')]
        if not vals:
            continue
        totals[stat] += sum(vals) if _is_stacking(b_type) else max(vals)
    return dict(totals)


def _tier_vector(contrib, weights, tier_of, ub_all, ub_nofil):
    """Score a gearset as its tier vector (G1..G5) by pure evaluation — the same
    w_s weights and n_s = min(1, Z_s/UB_s) normalization as the main solve. Tier
    stages are never re-run per candidate."""
    z_all = _resolve_totals(contrib, exclude_filigrees=False)
    z_nofil = _resolve_totals(contrib, exclude_filigrees=True)

    scores = {}
    for tier, tier_weights in weights.items():
        magnitude = 0.0
        breadth = 0.0
        for stat, w in tier_weights.items():
            if tier == 1:
                total = z_all.get(stat, 0.0)
                ub = ub_all.get(stat, UB_FLOOR)
            else:
                total = z_nofil.get(stat, 0.0)
                ub = ub_nofil.get(stat, UB_FLOOR)
            n = min(1.0, total / ub) if ub > 0 else 0.0
            magnitude += w * n
            if tier == 4:
                theta = WEAPON_TIER4_BASELINES.get(stat.lower())
                display_total = z_all.get(stat, 0.0)
                if theta is not None:
                    breadth += 1.0 if display_total >= theta else 0.0
                else:
                    breadth += 1.0 if display_total > 0 else 0.0
        if tier == 4:
            scale = 1.0 + sum(tier_weights.values())
            scores[tier] = scale * breadth + magnitude
        else:
            scores[tier] = magnitude
    return scores, z_all


def _collapsed_score(tier_scores):
    """§7.6 — display collapse. DISPLAY SUGAR ONLY, non-authoritative: it
    preserves the lexicographic ordering only when the higher-tier gap exceeds
    ~0.333. Rank / TierScores are the authoritative outputs."""
    return sum((10.0 ** (5 - t)) * tier_scores.get(t, 0.0) for t in range(1, 6))


def _lex_key(tier_scores, penalty):
    return tuple(tier_scores.get(t, 0.0) for t in range(1, 6)) + (-penalty,)


def _augment_marginal_weights(weights, tier_of, ub_all):
    """Collapsed per-stat coefficient used only for intra-item augment choice.

    Documented approximation (§7.4): with G_t in [0,1] (<= 3 for tier 4) the
    maximum contribution of all tiers below t is <= 0.333 * 10**(5-t), a factor-
    3 margin. It is never used for the authoritative candidate ranking.
    """
    out = {}
    for tier, tier_weights in weights.items():
        scale = 10.0 ** (5 - tier)
        for stat, w in tier_weights.items():
            ub = ub_all.get(stat, UB_FLOOR)
            out[stat] = scale * (w / ub if ub > 0 else 0.0)
    return out


def _assign_augments_greedy(item, augments, used_names, base_contrib, marginal):
    """Phase A (§7.4): iterate the item's color slots in XML order and pick the
    not-yet-used compatible augment with the highest marginal gain. Instant, no
    solver.

    Returns a list ALIGNED to `item['augments']` (the color slots), with None
    where no compatible augment was worth taking, so colors and augments stay
    paired in the output.
    """
    chosen = []
    used = set(used_names)

    # Running credited maxima for non-stacking bonus types, so marginal gain is
    # measured against what the rest of the gearset already provides.
    current_max = {}
    for key, entries in base_contrib.items():
        if not _is_stacking(key[1]) and entries:
            current_max[key] = max(v for v, _o in entries)

    for color in item.get('augments', []) or []:
        best_idx = None
        best_gain = 0.0
        for a_idx, aug in enumerate(augments):
            if aug['name'] in used:
                continue
            a_type = aug['type'].lower()
            if not (a_type == color.lower() or color.lower() in a_type):
                continue
            gain = 0.0
            for stat, b_type, val in aug['buffs']:
                coeff = marginal.get(stat)
                if not coeff:
                    continue
                if _is_stacking(b_type):
                    gain += coeff * val
                else:
                    gain += coeff * max(0.0, val - current_max.get((stat, b_type), 0.0))
            if gain > best_gain:
                best_gain = gain
                best_idx = a_idx
        if best_idx is None:
            chosen.append(None)
            continue
        aug = augments[best_idx]
        chosen.append(aug)
        used.add(aug['name'])
        for stat, b_type, val in aug['buffs']:
            if not _is_stacking(b_type):
                key = (stat, b_type)
                current_max[key] = max(current_max.get(key, 0.0), val)
    return chosen


def _candidate_penalty(item, aug_list, contrib):
    """§7.5 — P evaluated arithmetically from the candidate's own contribution."""
    aug_list = [a for a in aug_list if a is not None]
    p = LAMBDA_ITEM * (1.0 if item is not None else 0.0)
    dup = 0
    credited = {}
    for key, entries in contrib.items():
        if _is_stacking(key[1]):
            continue
        credited[key] = max((v for v, _o in entries), default=0.0)
    own = list(item['buffs']) if item is not None else []
    for aug in aug_list:
        own.extend(aug['buffs'])
    for stat, b_type, val in own:
        if _is_stacking(b_type):
            continue
        if val < credited.get((stat, b_type), 0.0):
            dup += 1
    return p + LAMBDA_DUP * dup


def find_slot_alternatives(items, sets, augments, filigrees, entries, required_slots,
                           equipped_items, pre_filled_augments, pre_filled_filigrees,
                           target_slot, current_item, count,
                           upper_bounds_all, upper_bounds_nofil, weights):
    """Enumeration-based, target-slot-only alternatives (§7).

    Every OTHER slot is hard-locked to `equipped_items`, so "which item goes in
    this slot" is a single decision requiring no ILP at all. Cold-callable: no
    prior optimization run is required, and `equipped_items` may be a gearset
    the user assembled by hand.
    """
    warnings = []
    count = int(_clamp(int(count or 0), 3, 10))
    tier_of = {e.stat: e.tier for e in entries}

    by_name = {}
    for idx, item in enumerate(items):
        by_name.setdefault(item['name'], idx)

    # Resolve the fixed gearset.
    equipped_items = dict(equipped_items or {})
    name_slots = collections.defaultdict(list)
    for slot, name in equipped_items.items():
        if name:
            name_slots[name].append(slot)

    duplicated_names = set()
    for name, slots in name_slots.items():
        if len(slots) > 1:
            duplicated_names.add(name)
            warnings.append(
                f"Item '{name}' is equipped in more than one slot "
                f"({', '.join(sorted(slots))}); it was excluded from the candidate list.")

    fixed = []           # (slot, item dict)
    excluded_names = set(duplicated_names)
    for slot, name in equipped_items.items():
        if not name:
            continue
        excluded_names.add(name)
        if slot == target_slot:
            continue
        idx = by_name.get(name)
        if idx is None:
            warnings.append(
                f"Equipped item '{name}' for slot '{slot}' was not found in the data files "
                f"and was ignored.")
            continue
        fixed.append((slot, items[idx]))

    if current_item:
        excluded_names.add(current_item)

    # Fixed augments / filigrees for the other slots.
    fixed_augments = []
    used_aug_names = set()
    aug_by_name = {a['name']: a for a in augments}
    for slot, aug_entry in (pre_filled_augments or {}).items():
        if slot == target_slot:
            continue
        names = []
        if isinstance(aug_entry, dict):
            for v in aug_entry.values():
                names.extend(v if isinstance(v, list) else [v])
        elif isinstance(aug_entry, (list, tuple)):
            names.extend(aug_entry)
        for name in names:
            aug = aug_by_name.get(name)
            if aug is not None:
                fixed_augments.append(aug)
                used_aug_names.add(name)

    fil_by_name = {f['name']: f for f in filigrees}
    fil_weapon = [fil_by_name[n] for n in (pre_filled_filigrees or {}).get('weapon', []) or []
                  if n in fil_by_name]
    fil_artifact = [fil_by_name[n] for n in (pre_filled_filigrees or {}).get('artifact', []) or []
                    if n in fil_by_name]

    def evaluate(candidate_item, candidate_augs):
        equipped = list(fixed)
        if candidate_item is not None:
            equipped.append((target_slot, candidate_item))
        chosen = [a for a in (candidate_augs or []) if a is not None]
        contrib = _collect_contributions(
            equipped, fixed_augments + chosen, fil_weapon, fil_artifact, sets)
        scores, z_all = _tier_vector(contrib, weights, tier_of, upper_bounds_all, upper_bounds_nofil)
        return scores, z_all, contrib

    # Baseline = the gearset exactly as passed in (EC-13: the target slot may be
    # empty and current_item may be "").
    baseline_item = items[by_name[current_item]] if current_item and current_item in by_name else None
    baseline_augs = []
    baseline_entry = (pre_filled_augments or {}).get(target_slot)
    if baseline_entry:
        names = []
        if isinstance(baseline_entry, dict):
            for v in baseline_entry.values():
                names.extend(v if isinstance(v, list) else [v])
        else:
            names.extend(baseline_entry)
        baseline_augs = [aug_by_name[n] for n in names if n in aug_by_name]

    baseline_scores, baseline_z, _bc = evaluate(baseline_item, baseline_augs)

    # Candidate pool (§7.3).
    base_contrib = _collect_contributions(fixed, fixed_augments, fil_weapon, fil_artifact, sets)
    marginal = _augment_marginal_weights(weights, tier_of, upper_bounds_all)

    candidates = []
    for idx, item in enumerate(items):
        if not _slot_matches(item, target_slot):
            continue
        if item['name'] in excluded_names:
            continue
        augs = _assign_augments_greedy(item, augments, used_aug_names, base_contrib, marginal)
        scores, z_all, contrib = evaluate(item, augs)
        penalty = _candidate_penalty(item, augs, contrib)
        candidates.append({
            'item': item, 'augs': augs, 'scores': scores,
            'z': z_all, 'penalty': penalty, 'contrib': contrib,
        })

    candidates.sort(key=lambda c: (_lex_key(c['scores'], c['penalty']), _negname(c['item']['name'])),
                    reverse=True)

    # Phase B (§7.4): re-assign augments for the top candidates only.
    #
    # DEVIATION (documented): the spec calls for a 2s per-candidate GLPK ILP
    # here. The collapsed score is not linear in the augment binaries (it mixes
    # max-over-sources with min(1, Z/UB)), so an honest ILP would require a
    # miniature d/n model per candidate, and up to 30 file-based GLPK process
    # spawns per request. A deterministic best-response local search over a
    # pre-filtered augment shortlist reaches the same assignment for the small
    # slot counts involved (<= 5 colors) at a fraction of the cost.
    top_n = max(15, 3 * count)
    for cand in candidates[:top_n]:
        improved = _local_search_augments(
            cand['item'], augments, used_aug_names, cand['augs'], evaluate)
        if improved is not None:
            cand['augs'] = improved
            scores, z_all, contrib = evaluate(cand['item'], improved)
            cand['scores'] = scores
            cand['z'] = z_all
            cand['contrib'] = contrib
            cand['penalty'] = _candidate_penalty(cand['item'], improved, contrib)

    candidates.sort(key=lambda c: (_lex_key(c['scores'], c['penalty']), _negname(c['item']['name'])),
                    reverse=True)

    # Diversity filter (explicit instruction): don't let a single "reskinned"
    # weapon family (same named line, different weapon type — see
    # _weapon_family_key) fill every alternative slot. Walk the score-sorted
    # list once, keeping only the single best-scoring candidate per family
    # key; same-family runners-up are held back as a fallback fill in case
    # the pool doesn't have enough distinct families to reach `count` (a true
    # alternative that scores slightly lower is still preferred over a
    # same-family repeat, but never return fewer alternatives than the pool
    # actually supports).
    diverse = []
    seen_family_keys = set()
    same_family_fallback = []
    for cand in candidates:
        fam = _weapon_family_key(cand['item'])
        if fam is None or fam not in seen_family_keys:
            diverse.append(cand)
            if fam is not None:
                seen_family_keys.add(fam)
        else:
            same_family_fallback.append(cand)
        if len(diverse) >= count:
            break
    if len(diverse) < count:
        diverse.extend(same_family_fallback[:count - len(diverse)])
        diverse.sort(key=lambda c: (_lex_key(c['scores'], c['penalty']), _negname(c['item']['name'])),
                     reverse=True)
    candidates = diverse

    priority_stats = [e.stat for e in entries]
    out = []
    for rank, cand in enumerate(candidates[:count], start=1):
        item = cand['item']
        out.append({
            "rank": rank,
            "itemName": item['name'],
            "slot": target_slot,
            "ml": item.get('ml', 0),
            "isRaid": bool(item.get('is_raid', False)),
            # Not rounded: ObjectiveScore must reproduce the §7.6 collapse of
            # these exact numbers to within 1e-6 (AC-38).
            "tierScores": {str(t): cand['scores'].get(t, 0.0) for t in range(1, 6)
                           if t in weights},
            "objectiveScore": _collapsed_score(cand['scores']),
            "statDeltas": {s: round(cand['z'].get(s, 0.0) - baseline_z.get(s, 0.0), 6)
                           for s in priority_stats},
            "augments": [{"color": c, "name": a['name']}
                         for c, a in zip(item.get('augments', []), cand['augs']) if a is not None],
            "filigrees": {"weapon": [f['name'] for f in fil_weapon],
                          "artifact": [f['name'] for f in fil_artifact]},
        })

    return {
        "success": True,
        "slot": target_slot,
        "baselineTierScores": {str(t): baseline_scores.get(t, 0.0)
                               for t in range(1, 6) if t in weights},
        "alternatives": out,
        "warnings": warnings,
    }


class _negname(str):
    """Sort helper: makes ItemName ascend while everything else descends under a
    single reverse=True sort (§7.5 determinism requirement)."""

    def __lt__(self, other):
        return str.__gt__(self, other)

    def __gt__(self, other):
        return str.__lt__(self, other)

    def __le__(self, other):
        return str.__ge__(self, other)

    def __ge__(self, other):
        return str.__le__(self, other)


def _local_search_augments(item, augments, used_names, initial, evaluate, shortlist=8, passes=2):
    """Best-response local search over one item's augment slots. See the
    DEVIATION note in find_slot_alternatives."""
    colors = list(item.get('augments', []) or [])
    if not colors:
        return None

    compatible = []
    for color in colors:
        pool = [a for a in augments
                if a['name'] not in used_names
                and augment_fits_slot(a['type'], color, a['name'])]
        # Pre-filter by raw buff magnitude so the search stays cheap.
        pool.sort(key=lambda a: (-sum(abs(v) for _s, _b, v in a['buffs']), a['name']))
        compatible.append(pool[:shortlist])

    current = list(initial) + [None] * (len(colors) - len(initial))
    current = current[:len(colors)]

    def score_of(assign):
        chosen = [a for a in assign if a is not None]
        scores, _z, _c = evaluate(item, chosen)
        return _collapsed_score(scores)

    best_score = score_of(current)
    for _ in range(passes):
        changed = False
        for pos in range(len(colors)):
            taken = {a['name'] for i, a in enumerate(current) if a is not None and i != pos}
            for cand in compatible[pos] + [None]:
                if cand is not None and cand['name'] in taken:
                    continue
                if (cand is None and current[pos] is None) or \
                        (cand is not None and current[pos] is not None and cand['name'] == current[pos]['name']):
                    continue
                trial = list(current)
                trial[pos] = cand
                s = score_of(trial)
                if s > best_score + 1e-12:
                    best_score = s
                    current = trial
                    changed = True
        if not changed:
            break

    return current


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def run_optimization(items, sets, augments, filigrees, entries, out_file, cap, art_slots,
                     raid_item_limit=None, pre_equipped=None, pre_filled_augments=None,
                     pre_filled_filigrees=None, mode="optimize", max_search_time=DEFAULT_SEARCH_TIME,
                     weapon1_eligible_types=None, weapon2_eligible_types=None, require_weapon2=False):
    calculate_only = (mode == "calculate")

    # Required slots based on available items
    available_slots = set()
    for item in items:
        for slot in item['slots']:
            if slot == 'Ring':
                available_slots.add('Ring_1')
                available_slots.add('Ring_2')
            else:
                available_slots.add(slot)

    base_required = ['Helmet', 'Necklace', 'Trinket', 'Cloak', 'Belt', 'Ring_1', 'Ring_2', 'Gloves', 'Boots', 'Bracers', 'Armor', 'Goggles', 'Weapon1', 'Weapon2']
    if calculate_only and pre_equipped:
        required_slots = [s for s in base_required if s in available_slots and s in pre_equipped]
    else:
        required_slots = [s for s in base_required if s in available_slots]

    model = create_model(items, sets, augments, filigrees, entries, art_slots, required_slots,
                         raid_item_limit, pre_equipped, pre_filled_augments,
                         pre_filled_filigrees, calculate_only,
                         weapon1_eligible_types=weapon1_eligible_types,
                         weapon2_eligible_types=weapon2_eligible_types,
                         require_weapon2=require_weapon2)

    out_file.write(f"\n======================================\n")
    out_file.write(f"       RUNNING FOR MAX LEVEL {cap}\n")
    out_file.write(f"======================================\n\n")
    out_file.write(f"Mode: {mode}\n")
    out_file.write(f"Received max_search_time: {max_search_time}\n")
    if model.unmatched:
        out_file.write(f"Unmatched priorities (no source in the data files): "
                       f"{', '.join(model.unmatched)}\n")

    # EC-4 — every priority unmatched is a genuine failure.
    if entries and not model.weights:
        return {"success": False,
                "errorMessage": "None of the listed stat priorities matched any item, augment, "
                                "filigree, or set bonus in the data files."}

    if calculate_only:
        # §6 shortcut: in calculate mode all equipment is pinned by
        # construction, so tier goals are irrelevant. Skip every tier stage and
        # the consolidation stage; one pass to realize the pinned binaries, then
        # the reconciliation LP.
        model.prob.setObjective(pulp.lpSum(list(model.z.values())))
        status = _solve(model.prob, RECONCILE_TMLIM)
        if status == pulp.LpStatusInfeasible or not _has_incumbent(model.prob):
            out_file.write("Could not compute the supplied gearset.\n")
            return {"success": False,
                    "errorMessage": "The supplied gearset could not be evaluated; some locked "
                                    "items may be incompatible with each other."}
        t0 = time.time()
        rec_ok = reconcile_solution(model)
        tier_report = {
            "stages": [],
            "consolidation": None,
            "reconciliation": {"status": "optimal" if rec_ok else "failed",
                               "elapsedSeconds": round(time.time() - t0, 2)},
            "totalElapsedSeconds": round(time.time() - t0, 2),
            "degraded": not rec_ok,
            "notes": list(model.notes),
        }
        tier_scores = {}
    else:
        result = solve_tiered(model, max_search_time, out_file)
        if result.get("failed"):
            out_file.write("Status: Infeasible\n")
            out_file.write("Could not find a feasible set of gear for this cap/priorities.\n")
            return {"success": False, "errorMessage": result["reason"]}
        tier_report = result
        # Recomputed from the FINAL (reconciled) solution rather than echoed
        # from the stage records, so `tierScores` describes the gearset that is
        # actually returned. Every locked tier is guaranteed >= its recorded
        # V_t - tol because the lock constraint is still in the model.
        tier_scores = {str(t): round(_goal_value(model.goals[t]), 6) for t in sorted(model.goals)}

    out_file.write(f"Status: {pulp.LpStatus[model.prob.status]}\n")

    x, y, fw, fm, w_vars, z = model.x, model.y, model.fw, model.fm, model.w_vars, model.z
    sources_tracking = model.sources_tracking

    out_file.write("\n=== EQUIPPED ITEMS ===\n")
    equipped = {}
    equipped_simple = {}
    equipped_idx = {}
    for (i, s), var in x.items():
        if _val(var) > 0.5:
            equipped[s] = items[i]
            equipped_simple[s] = items[i]['name']
            equipped_idx[s] = i

    for slot in required_slots:
        if slot in equipped:
            item = equipped[slot]
            if item['minor']:
                out_file.write(f"{slot}: {item['name']} (Minor Artifact) (ML: {item['file']})\n")
            else:
                out_file.write(f"{slot}: {item['name']} (ML: {item['file']})\n")
            for (a, i, c), y_var in y.items():
                if i == equipped_idx[slot] and _val(y_var) > 0.5:
                    out_file.write(f"  + Augment [{c}]: {augments[a]['name']}\n")

    # NOTE: the eager per-run weapon alternatives search is gone (§7.1).
    # Alternatives are now an on-demand, cold-callable call into
    # find_slot_alternatives().

    w_fil, m_fil = [], []
    if filigrees:
        w_fil = [f for idx, f in enumerate(filigrees) if _val(fw[idx]) > 0.5]
        m_fil = [f for idx, f in enumerate(filigrees) if _val(fm[idx]) > 0.5]

        if w_fil:
            out_file.write(f"\n=== WEAPON FILIGREES ===\n")
            for f in w_fil:
                out_file.write(f"  + {f['name']}\n")

        if m_fil:
            out_file.write(f"\n=== MINOR ARTIFACT FILIGREES ===\n")
            for f in m_fil:
                out_file.write(f"  + {f['name']}\n")

    active_sets_out = []
    out_file.write("\n=== ACTIVE SET BONUSES ===\n")
    for (k, m), w_var in w_vars.items():
        if _val(w_var) > 0.5:
            out_file.write(f"{k} ({m}-piece)\n")
            active_sets_out.append(f"{k} ({m}-piece)")
            if k in sets and m in sets[k]:
                for stat, bonus, val in sets[k][m]:
                    out_file.write(f"  + {val} {bonus} bonus to {stat}\n")

    # realizedStats is keyed on the BASE stat name (the raw "[N]" suffix is
    # stripped upstream now — see §12 item 5).
    realized_stats_out = {}
    out_file.write("\n=== REALIZED STATS ===\n")
    for entry in entries:
        p_base = entry.stat
        if p_base in realized_stats_out:
            continue
        total = 0.0
        details = []
        for (st, b_type), z_var in z.items():
            if st.lower() == p_base.lower() and _val(z_var) > 0:
                total += _val(z_var)
                details.append(f"{_val(z_var)} {b_type}")
        if total > 0:
            out_file.write(f"{p_base}: {total} ({', '.join(details)})\n")
            realized_stats_out[p_base] = total

    filigrees_out = {"weapon": [f['name'] for f in w_fil], "artifact": [f['name'] for f in m_fil]}

    # Per-slot rich detail (item 1 / Phase 9.2, docs/PHASE9_PLAN.md): the single
    # authoritative structure the frontend calculator/Summary should read from —
    # what item is in a slot, what augments/filigrees/set bonuses it contributes.
    def _buff_dicts(buffs):
        return [{"stat": st, "bonus": bt, "value": v} for st, bt, v in buffs]

    slots_out = {}
    for slot, item in equipped.items():
        i = equipped_idx[slot]
        slot_augments = []
        for (a, ii, c), y_var in y.items():
            if ii == i and _val(y_var) > 0.5:
                aug = augments[a]
                slot_augments.append({"color": c, "name": aug['name'], "buffs": _buff_dicts(aug['buffs'])})

        slot_set_bonuses = []
        for (k, m), w_var in w_vars.items():
            if _val(w_var) > 0.5 and k in item.get('sets', []):
                slot_set_bonuses.append({
                    "set": k,
                    "pieces": m,
                    "buffs": _buff_dicts(sets.get(k, {}).get(m, [])),
                })

        # Filigrees aren't per-literal-slot (they belong to the "Sentient Weapon"
        # as a whole or the Minor Artifact item, see docs/USAGE.md) — attach the
        # relevant bucket to whichever slot(s) actually carry that concept.
        slot_filigrees = []
        if slot in ('Weapon1', 'Weapon2'):
            slot_filigrees = [{"name": f['name'], "buffs": _buff_dicts(f['buffs'])} for f in w_fil]
        elif item.get('minor'):
            slot_filigrees = [{"name": f['name'], "buffs": _buff_dicts(f['buffs'])} for f in m_fil]

        slots_out[slot] = {
            "location": slot,
            "item": {
                "name": item['name'],
                "file": item.get('file'),
                "ml": item.get('ml', 0),
                "is_raid": item.get('is_raid', False),
                "pack": item.get('pack'),
                "minor": item.get('minor', False),
            },
            "augments": slot_augments,
            "filigrees": slot_filigrees,
            "set_bonus_contributions": slot_set_bonuses,
        }

    all_effects_out = {}
    for (st, b_type), z_var in z.items():
        if _val(z_var) > 0:
            if st not in all_effects_out:
                all_effects_out[st] = []

            contributing = []
            for tracked_var, val, sname, _origin in sources_tracking[(st, b_type)]:
                if _val(tracked_var) > 0.5:
                    contributing.append(f"{val} {b_type} ({sname})")

            if contributing:
                all_effects_out[st].extend(contributing)
            else:
                all_effects_out[st].append(f"{_val(z_var)} {b_type}")

    unmet_tier4 = sorted([stat for stat, var in model.present.items() if _val(var) < 0.5])

    rich_output = {
        "gearSet": equipped_simple,
        "realizedStats": realized_stats_out,
        "activeSets": active_sets_out,
        "filigrees": filigrees_out,
        "allEffects": all_effects_out,
        "slots": slots_out,
        # §9 additions
        "tierReport": tier_report,
        "tierScores": tier_scores,
        "priorityTiers": {e.stat: e.tier for e in entries},
        "unmetTier4": unmet_tier4,
        "unmatchedPriorities": list(model.unmatched),
    }
    return rich_output
