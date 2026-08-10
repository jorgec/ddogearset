"""Stat naming — turning an XML effect into the name a user's priority uses.

Part of `python/rules/`: no pulp, no search restrictions.

**This module is the single most expensive thing in the project to get wrong.**
The 0.5.0 Go attempt dropped it, and the app's headline panel went to 0 for 13
of 14 priorities; restoring it meant porting ~250 lines in which *every guard is
a past bug*:

| Guard | Origin | Prevents |
|---|---|---|
| Hireling | 0.4.4 | `HirelingPRR` credited to the player (PRR read 67 vs a real 47) |
| School save | 0.4.2 | `IllusionSave` (defensive) inflating an Illusion **DC** (offensive) |
| Skill group | 0.4.3 | An `Intelligence` priority absorbing `Intelligence Skills` buffs |
| Weapon base stats | §15.2 | Exact-match stats going through the substring heuristic |
| Bonus-type prefixes | CASTER_BONUS_TYPE_STATS_SPEC | `sacred spell focus mastery` matching only Sacred sources |
| Direct-before-implied | — | An early school-DC priority starving an explicit SFM priority |

`normalize_stat_name` does two jobs, and they must not be confused again:

1. **Filter** — return None for a stat no priority claims.
2. **Name** — report a stat under the priority's own spelling
   (`SpellPower` + Item `Force` -> `force spellpower`).

Recalculation wants the naming and NOT the filtering, which is what the
extractors' `keep_unmatched` flag is for — not a second implementation.
"""

import re

from .constants import (
    PROC_PRESENCE_FLAG_TYPES,
    WEAPON_BASE_STATS,
    WEAPON_STAT_COMPOSITE,
)

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
