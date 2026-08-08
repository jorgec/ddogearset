// Stat taxonomy — the vocabulary the stat picker offers.
//
// OWNERSHIP: this file is APP VOCABULARY, owned and versioned with the code.
// It is deliberately NOT a `public/` JSON asset like `expansions.json`, and
// deliberately NOT the same kind of thing as `stat_sets.json` (which IS meant
// to be hand-edited by the user at runtime, and is therefore served by the
// GetStatSets RPC instead of living here). The asymmetry is intentional:
// changing the taxonomy is a code change; changing your presets is not.
//
// WHY STATIC AND NOT BACKEND-ENUMERATED (docs/TIERED_SOLVER_FRONTEND_SPEC.md
// §4.1): these strings are inputs to python/optimizer.py's normalize_stat_name
// matcher, not raw XML <Type> values. Enumerating distinct <Type> values from
// the parsed pool would return thousands of strings (`Combustion`,
// `MagicalEfficiency`, `Chilling 3`, …) that are accurate about the XML but not
// in the vocabulary the matcher expects. The real risk this leaves open — a
// leaf that matches zero sources — is handled POST-solve via the solver's own
// `unmatchedPriorities` output, surfaced by TierReport.svelte and badged back
// onto the corresponding chips in StatPriorityEditor.svelte.

export interface StatTaxonomyLeaf {
    label: string; // display text, e.g. "Fire Spellpower"
    stat: string; // exact wire string, e.g. "fire spellpower"
    note?: string; // caveat text shown in the picker and under the placed chip
    advanced?: boolean; // render muted/de-emphasized to steer users elsewhere
}

export interface StatTaxonomyCategory {
    label: string;
    children: (StatTaxonomyCategory | StatTaxonomyLeaf)[];
}

export type StatTaxonomyNode = StatTaxonomyCategory | StatTaxonomyLeaf;

export function isLeaf(node: StatTaxonomyNode): node is StatTaxonomyLeaf {
    return (node as StatTaxonomyLeaf).stat !== undefined;
}

const UNDOCUMENTED_CASTER_LEVEL =
    'Undocumented in the data files — the effect exists in-game but the exact bonus value is not specified in the XML. May match nothing.';
const UNDOCUMENTED_PROC =
    'Most proc mechanics are undocumented in the data files. Listed for discoverability; may match nothing.';

// Element list shared by Spell Lore and Spell Critical Damage
// (docs/STAT_SHORTCUTS.md §2/§3).
const SPELL_ELEMENTS: [string, string][] = [
    ['Fire', 'fire'],
    ['Electric', 'electric'],
    ['Cold', 'cold'],
    ['Acid', 'acid'],
    ['Sonic', 'sonic'],
    ['Force', 'force'],
    ['Poison', 'poison'],
    ['Positive', 'positive'],
    ['Negative', 'negative'],
    ['All Elements (Universal)', 'all'],
];

const SPELL_SCHOOLS = [
    'Evocation',
    'Necromancy',
    'Enchantment',
    'Conjuration',
    'Divination',
    'Abjuration',
    'Transmutation',
    'Illusion',
];

function elementLeaves(suffix: string): StatTaxonomyLeaf[] {
    return SPELL_ELEMENTS.map(([label, key]) => ({
        label,
        stat: `${key} ${suffix}`,
    }));
}

// docs/CASTER_BONUS_TYPE_STATS_SPEC.md — bonus types confirmed present on
// real "All Schools" SpellDC sources (Solar/Lunar Gems, Lamordia Woeful
// augments, Dinosaur Bone horns, etc.) and on real SpellFocusMastery item
// buffs, respectively. Reaper is deliberately excluded everywhere (a
// stacking bonus type tied to Reaper difficulty, not a gear-farming target,
// same exclusion python/optimizer.py's BONUS_TYPE_PREFIXES makes).
//
// CORRECTION: these lists were originally derived by scanning the whole
// corpus with no level floor and without separating school-specific from
// All-Schools effects, and the comment here wrongly claimed no leaf could
// match zero sources. Three did, and were removed after re-auditing against
// the ML>=29 floor the solver actually parses at:
//   • Enhancement / Fortune "All Schools" DC — those bonus types exist ONLY
//     on school-specific SpellDC effects (Item=Evocation, …), never on
//     Item=All, so an All-Schools leaf for them matched nothing at any level.
//   • Legendary Spell Focus Mastery — its single corpus source (Argonnessen
//     Eye Band) is ML 10, far below the endgame floor, so it could never
//     match in a real solve.
// Every entry below is verified to have at least one source at ML>=29.
const SPELL_DC_ALL_SCHOOLS_BONUS_TYPES = [
    'Sacred', 'Quality', 'Profane', 'Artifact', 'Insightful', 'Exceptional',
    'Equipment',
];
const SPELL_FOCUS_MASTERY_BONUS_TYPES = [
    'Sacred', 'Quality', 'Profane', 'Insightful', 'Exceptional', 'Equipment',
];

export const STAT_TAXONOMY: StatTaxonomyCategory[] = [
    {
        label: 'Spell Schools (Spell DC)',
        children: [
            ...SPELL_SCHOOLS.map((school) => ({
                label: school,
                stat: `${school.toLowerCase()} spelldc`,
            })),
            { label: 'All Schools (Universal)', stat: 'all spelldc' },
            {
                label: 'All Schools, by Bonus Type',
                children: SPELL_DC_ALL_SCHOOLS_BONUS_TYPES.map((bt) => ({
                    label: bt,
                    stat: `${bt.toLowerCase()} all spelldc`,
                })),
            },
        ],
    },
    {
        label: 'Spell Focus Mastery',
        children: [
            { label: 'Any Bonus Type (Universal)', stat: 'spell focus mastery' },
            {
                label: 'By Bonus Type',
                children: SPELL_FOCUS_MASTERY_BONUS_TYPES.map((bt) => ({
                    label: bt,
                    stat: `${bt.toLowerCase()} spell focus mastery`,
                })),
            },
        ],
    },
    {
        label: 'Spell Lore (Crit Chance)',
        children: elementLeaves('spelllore'),
    },
    {
        label: 'Spell Critical Damage',
        children: elementLeaves('spellcriticaldamage'),
    },
    {
        label: 'Spellpower',
        children: [
            {
                label: 'Elemental',
                children: [
                    { label: 'Fire (Combustion)', stat: 'fire spellpower' },
                    { label: 'Electric (Magnetism)', stat: 'electric spellpower' },
                    { label: 'Cold (Glaciation)', stat: 'cold spellpower' },
                    { label: 'Acid (Corrosion)', stat: 'acid spellpower' },
                    { label: 'Sonic (Resonance)', stat: 'sonic spellpower' },
                    { label: 'Force (Kinetic)', stat: 'force spellpower' },
                    { label: 'Poison', stat: 'poison spellpower' },
                    { label: 'Positive (Devotion)', stat: 'positive spellpower' },
                    { label: 'Negative (Nullification)', stat: 'negative spellpower' },
                ],
            },
            {
                label: 'Alignment',
                children: [
                    { label: 'Good', stat: 'good spellpower' },
                    { label: 'Evil', stat: 'evil spellpower' },
                    { label: 'Lawful', stat: 'lawful spellpower' },
                    { label: 'Chaos', stat: 'chaos spellpower' },
                    { label: 'Light / Alignment', stat: 'light spellpower' },
                ],
            },
            {
                label: 'Utility',
                children: [
                    { label: 'Repair', stat: 'repair spellpower' },
                    { label: 'Rust', stat: 'rust spellpower' },
                    { label: 'Physical', stat: 'physical spellpower' },
                ],
            },
            {
                label: 'Compound (Multi-Element)',
                children: [
                    {
                        label: 'Radiance',
                        stat: 'radiance spellpower',
                        note: 'One source, two elements: Light/Alignment and Chaos.',
                    },
                    {
                        label: 'Reconstruction',
                        stat: 'reconstruction spellpower',
                        note: 'One source, two elements: Repair and Rust.',
                    },
                    {
                        label: 'Impulse',
                        stat: 'impulse spellpower',
                        note: 'One source, two elements: Force and Physical.',
                    },
                ],
            },
            {
                label: 'Universal',
                children: [
                    {
                        label: 'All Spellpower',
                        stat: 'all spellpower',
                        note: 'Applies to every spellpower category at once.',
                    },
                ],
            },
        ],
    },
    {
        label: 'Spell Resources',
        children: [{ label: 'Spell Points', stat: 'spell points' }],
    },
    {
        label: 'Warlock',
        children: [
            {
                label: 'Pact Dice',
                stat: 'pact dice',
                note: 'Use instead of, not alongside, traditional spellpower/DC for Eldritch Blast builds.',
            },
        ],
    },
    {
        label: 'Caster Level',
        children: [
            { label: 'Fire Caster Level', stat: 'fire caster level', note: UNDOCUMENTED_CASTER_LEVEL },
            { label: 'Cold Caster Level', stat: 'cold caster level', note: UNDOCUMENTED_CASTER_LEVEL },
            { label: 'Electric Caster Level', stat: 'electric caster level', note: UNDOCUMENTED_CASTER_LEVEL },
            { label: 'Acid Caster Level', stat: 'acid caster level', note: UNDOCUMENTED_CASTER_LEVEL },
        ],
    },
    {
        label: 'Power',
        children: [
            { label: 'Melee Power', stat: 'melee power' },
            { label: 'Ranged Power', stat: 'ranged power' },
        ],
    },
    {
        label: 'Attack Speed',
        children: [
            { label: 'Melee Alacrity', stat: 'melee alacrity' },
            { label: 'Ranged Alacrity', stat: 'ranged alacrity' },
        ],
    },
    {
        label: 'Double Attacks',
        children: [
            { label: 'Doublestrike (Melee)', stat: 'doublestrike' },
            { label: 'Doubleshot (Ranged)', stat: 'doubleshot' },
        ],
    },
    {
        label: 'Critical (General)',
        children: [
            {
                label: 'Seeker',
                stat: 'seeker',
                note: 'Bonus to both the attack roll and the damage roll on a critical hit.',
            },
        ],
    },
    {
        label: 'Armor Piercing',
        children: [{ label: 'Armor Piercing', stat: 'armor piercing' }],
    },
    {
        label: 'Two-Weapon Fighting',
        children: [
            {
                label: 'Off-Hand Attack Bonus',
                stat: 'offhand attack bonus',
                note: 'Only meaningful for Two Weapon Fighting builds.',
            },
        ],
    },
    {
        // docs/PHASE10_PLAN.md §15.2 — these five strings are the solver's own
        // weapon-property stat names. AC-7 asserts literal equality with that
        // table; do not "tidy" them.
        label: 'Weapon Properties',
        children: [
            {
                label: 'Weapon Base Damage (recommended)',
                stat: 'weapon base damage',
                note: 'Combines [W] multiplier and base dice into one value. Do not also select Weapon Damage or Base Damage Dice.',
            },
            {
                label: 'Weapon Damage ([W])',
                stat: 'weapon damage',
                advanced: true,
                note: 'Advanced: use only if you specifically want to ignore base dice. Cannot be combined with Weapon Base Damage.',
            },
            {
                label: 'Base Damage Dice',
                stat: 'base damage dice',
                advanced: true,
                note: "Advanced: expected value of the weapon's dice only, ignoring [W]. Cannot be combined with Weapon Base Damage.",
            },
            { label: 'Critical Multiplier', stat: 'critical multiplier' },
            { label: 'Critical Threat Range', stat: 'critical threat range' },
        ],
    },
    {
        label: 'Procs',
        children: [
            // docs/PROC_EFFECTS_EXPANSION_SPEC.md — the on-spellcast/offhand
            // named procs below are all confirmed present in real
            // DDOBuilderV2 data (either a bare marker Buff Type with no
            // magnitude, or a zero-effect-data augment name — see the spec's
            // Shape A / Shape B). Every one credits a flat "do you have this
            // proc at all" presence signal (0 or 1), never a real magnitude
            // — the exact proc rate/damage described on the DDO wiki isn't
            // in the data files at all. Grouping is a best-effort read of
            // each proc's own name/theme (the underlying game mechanics are
            // themselves undocumented in the data, same caveat as before).
            {
                label: 'Damage Procs',
                children: [
                    { label: 'Bitter Frostbite (Cold)', stat: 'bitter frostbite', note: UNDOCUMENTED_PROC },
                    { label: 'Dripping with Magma (Fire)', stat: 'dripping with magma', note: UNDOCUMENTED_PROC },
                    { label: 'Grip of Venom (Poison)', stat: 'grip of venom', note: UNDOCUMENTED_PROC },
                    { label: 'Lightning Lash (Electric)', stat: 'lightning lash', note: UNDOCUMENTED_PROC },
                    { label: 'Lingering Acidic Burn (Acid)', stat: 'lingering acidic burn', note: UNDOCUMENTED_PROC },
                    { label: 'Revel in Blood (Bleed)', stat: 'revel in blood', note: UNDOCUMENTED_PROC },
                    { label: 'Rippling Energy (Force)', stat: 'rippling energy', note: UNDOCUMENTED_PROC },
                    { label: 'Rupturing Echo (Sonic)', stat: 'rupturing echo', note: UNDOCUMENTED_PROC },
                    { label: 'Inflict Blight (Acid)', stat: 'inflict blight', note: UNDOCUMENTED_PROC },
                    { label: 'Eternal Fire', stat: 'eternal fire', note: UNDOCUMENTED_PROC },
                    { label: 'Eternal Holy Burst', stat: 'eternal holy burst', note: UNDOCUMENTED_PROC },
                    { label: 'Noxious Venom Spike', stat: 'noxious venom spike', note: UNDOCUMENTED_PROC },
                    { label: 'Coalesced Flame', stat: 'coalesced flame', note: UNDOCUMENTED_PROC },
                    { label: 'Blunt Trauma', stat: 'blunt trauma', note: UNDOCUMENTED_PROC },
                    { label: 'Shadow Spike', stat: 'shadow spike', note: UNDOCUMENTED_PROC },
                    { label: "Vulkoor's Bite", stat: "vulkoor's bite", note: UNDOCUMENTED_PROC },
                    { label: 'Sinister Chill', stat: 'sinister chill', note: UNDOCUMENTED_PROC },
                    { label: 'Cerulean Wave', stat: 'cerulean wave', note: UNDOCUMENTED_PROC },
                    { label: 'Brazen Brilliance', stat: 'brazen brilliance', note: UNDOCUMENTED_PROC },
                    { label: 'Brilliance of the Shattered Sun', stat: 'brilliance of the shattered sun', note: UNDOCUMENTED_PROC },
                    { label: 'Burning Glory', stat: 'burning glory', note: UNDOCUMENTED_PROC },
                    { label: "Royalty's Frigid Response", stat: "royalty's frigid response", note: UNDOCUMENTED_PROC },
                ],
            },
            {
                label: 'Debuff & Crowd Control Procs',
                children: [
                    { label: 'Antimagic Spike', stat: 'antimagic spike', note: UNDOCUMENTED_PROC },
                    { label: 'Coronach', stat: 'coronach', note: UNDOCUMENTED_PROC },
                    { label: 'Freezing Ice', stat: 'freezing ice', note: UNDOCUMENTED_PROC },
                    { label: 'Legendary Negation', stat: 'legendary negation', note: UNDOCUMENTED_PROC },
                    { label: 'Memory of Binding', stat: 'memory of binding', note: UNDOCUMENTED_PROC },
                    { label: 'Memory of Butchery', stat: 'memory of butchery', note: UNDOCUMENTED_PROC },
                    { label: 'Mind Tear', stat: 'mind tear', note: UNDOCUMENTED_PROC },
                    { label: 'Nightsinger', stat: 'nightsinger', note: UNDOCUMENTED_PROC },
                    { label: 'Overwhelming Despair', stat: 'overwhelming despair', note: UNDOCUMENTED_PROC },
                    { label: 'Quenched', stat: 'quenched', note: UNDOCUMENTED_PROC },
                    { label: 'Sound and Silence', stat: 'sound and silence', note: UNDOCUMENTED_PROC },
                    { label: 'Sounding', stat: 'sounding', note: UNDOCUMENTED_PROC },
                    { label: 'Spell Resonance', stat: 'spell resonance', note: UNDOCUMENTED_PROC },
                    { label: 'Spell Turmoil', stat: 'spell turmoil', note: UNDOCUMENTED_PROC },
                    { label: 'Stone Prison', stat: 'stone prison', note: UNDOCUMENTED_PROC },
                    { label: 'Tendon Slice', stat: 'tendon slice', note: UNDOCUMENTED_PROC },
                    { label: "The Artblade's Gift", stat: "the artblade's gift", note: UNDOCUMENTED_PROC },
                    { label: "The Mummy's Gift", stat: "the mummy's gift", note: UNDOCUMENTED_PROC },
                    { label: "Titania's Warmth", stat: "titania's warmth", note: UNDOCUMENTED_PROC },
                    { label: 'Vile Grip of the Hidden Hand', stat: 'vile grip of the hidden hand', note: UNDOCUMENTED_PROC },
                ],
            },
            {
                label: 'Elemental Attunement Grants',
                children: [
                    { label: 'Alchemical Fire Attunement', stat: 'alchemical fire attunement', note: UNDOCUMENTED_PROC },
                    { label: 'Alchemical Water Attunement (Cold)', stat: 'alchemical water attunement', note: UNDOCUMENTED_PROC },
                    { label: 'Alchemical Air Attunement (Electric)', stat: 'alchemical air attunement', note: UNDOCUMENTED_PROC },
                    { label: 'Alchemical Earth Attunement (Acid)', stat: 'alchemical earth attunement', note: UNDOCUMENTED_PROC },
                    { label: 'Legendary Affirmation', stat: 'legendary affirmation', note: UNDOCUMENTED_PROC },
                    { label: 'Legendary Ash', stat: 'legendary ash', note: UNDOCUMENTED_PROC },
                    { label: 'Legendary Dust', stat: 'legendary dust', note: UNDOCUMENTED_PROC },
                    { label: 'Legendary Ice', stat: 'legendary ice', note: UNDOCUMENTED_PROC },
                    { label: 'Legendary Ooze', stat: 'legendary ooze', note: UNDOCUMENTED_PROC },
                    { label: 'Legendary Salt', stat: 'legendary salt', note: UNDOCUMENTED_PROC },
                    { label: 'Legendary Vacuum', stat: 'legendary vacuum', note: UNDOCUMENTED_PROC },
                    { label: 'Paranoia', stat: 'paranoia', note: UNDOCUMENTED_PROC },
                ],
            },
            {
                label: 'Activatable Abilities',
                children: [
                    { label: 'Clickie / Activatable', stat: 'activatable', note: UNDOCUMENTED_PROC },
                ],
            },
        ],
    },
];

// Build-type -> the category label that should float to the top of the picker.
// SOFT highlight only — no branch is ever hidden (spec §4.6), so a mixed-damage
// build can still reach everything.
export const BUILD_TYPE_PROMOTED_CATEGORY: Record<string, string> = {
    Melee: 'Power',
    Ranged: 'Power',
    Tank: 'Power',
    Caster: 'Spellpower',
};

export interface FlatStatEntry {
    label: string;
    stat: string;
    note?: string;
    advanced?: boolean;
    path: string; // "Spellpower › Elemental"
}

function flatten(nodes: StatTaxonomyNode[], trail: string[], out: FlatStatEntry[]) {
    for (const node of nodes) {
        if (isLeaf(node)) {
            out.push({ ...node, path: trail.join(' › ') });
        } else {
            flatten(node.children, [...trail, node.label], out);
        }
    }
}

// Every leaf in the tree, flattened once at module load for the picker's search.
export const FLAT_STATS: FlatStatEntry[] = (() => {
    const out: FlatStatEntry[] = [];
    flatten(STAT_TAXONOMY, [], out);
    return out;
})();

const BY_STAT: Record<string, FlatStatEntry> = (() => {
    const map: Record<string, FlatStatEntry> = {};
    for (const e of FLAT_STATS) map[e.stat.toLowerCase()] = e;
    return map;
})();

// Display label for a wire stat string. Falls back to the raw string for
// custom/legacy stats the taxonomy doesn't know about — never throws, never
// hides a stat just because it isn't in the tree.
export function labelForStat(stat: string): string {
    const entry = BY_STAT[stat?.toLowerCase()];
    return entry ? entry.label : stat;
}

export function noteForStat(stat: string): string | undefined {
    return BY_STAT[stat?.toLowerCase()]?.note;
}
