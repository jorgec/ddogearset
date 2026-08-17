"""Shared domain vocabulary — values every layer must agree on.

Part of `python/rules/`, which owns DDO's rules and MUST NOT import pulp or know
anything about search restrictions. See docs/0.5.0/00_ETL_START_HERE.md §7.

Nothing here is a policy knob: these are game facts (which bonus types stack,
what a weapon's base stats are called, how many filigree slots exist) and the
proc whitelists that stand in for data DDOBuilderV2 does not publish.
"""


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
    'legendary ooze', 'legendary salt', 'legendary steam', 'legendary vacuum',
    'alchemical fire attunement', 'alchemical water attunement',
    'alchemical air attunement', 'alchemical earth attunement', 'paranoia',
})


# Augments whose NAME differs from the proc they grant. The key is the
# augment name (lowercase); the value is the proc name (lowercase) that
# _proc_priority_match should match against. These augments typically have
# non-proc effects (like DRBypass) or no effects at all, so they aren't
# caught by Shape A's buff-type check or Shape B's name-IS-the-proc check.
PROC_AUGMENT_ALIASES = {
    # IoD fangs -> Alchemical Attunements
    'flamefang': 'alchemical fire attunement',
    'icefang': 'alchemical water attunement',
    'sparkfang': 'alchemical air attunement',
    'meltfang': 'alchemical earth attunement',
    # Dolorous (Legendary) -> Alchemical Attunements
    'dolorous flames (legendary)': 'alchemical fire attunement',
    'dolorous chill (legendary)': 'alchemical water attunement',
    'dolorous sparks (legendary)': 'alchemical air attunement',
    'dolorous acid (legendary)': 'alchemical earth attunement',
    'dolorous dimlight (legendary)': 'legendary steam',
    # Woeful (Legendary) -> Legendary procs
    'woeful flames (legendary)': 'legendary ash',
    'woeful chill (legendary)': 'legendary ice',
    'woeful sparks (legendary)': 'legendary vacuum',
    'woeful acid (legendary)': 'legendary dust',
    'woeful dimlight (legendary)': 'legendary affirmation',
}



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
