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

export const STAT_TAXONOMY: StatTaxonomyCategory[] = [
    {
        label: 'Spell Schools (Spell DC)',
        children: [
            ...SPELL_SCHOOLS.map((school) => ({
                label: school,
                stat: `${school.toLowerCase()} spelldc`,
            })),
            { label: 'All Schools (Universal)', stat: 'all spelldc' },
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
            {
                label: 'On-Hit',
                children: [
                    { label: 'On-Hit Damage Proc', stat: 'on hit damage', note: UNDOCUMENTED_PROC },
                    { label: 'Vulnerability Proc', stat: 'vulnerability', note: UNDOCUMENTED_PROC },
                ],
            },
            {
                label: 'Dual-Purpose (Attunements)',
                children: [
                    { label: 'Alchemical Attunement', stat: 'attunement', note: UNDOCUMENTED_PROC },
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
