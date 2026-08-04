// Shared stat-priority model helpers.
//
// These live outside StatPriorityEditor.svelte because the same rules have to
// hold at three different entry points (the picker, a stat-set apply, and the
// legacy .ddogearset migration on load). Keeping them here is what makes
// `canAddStat` un-bypassable — see docs/TIERED_SOLVER_FRONTEND_SPEC.md §3.5.

import type { main } from '../../../wailsjs/go/models';

export type Tier = 1 | 2 | 3 | 4 | 5;
export const TIERS: Tier[] = [1, 2, 3, 4, 5];

export interface StatChip {
    stat: string;
    cap?: number;
}

export type Lanes = Record<Tier, StatChip[]>;

export const TIER_META: Record<Tier, { header: string; sub: string }> = {
    1: {
        header: 'Must Maximize',
        sub: 'Solved first. Nothing below can reduce these. Filigrees only count here.',
    },
    2: { header: 'Maximize Next', sub: 'Maximized without giving up any Tier 1.' },
    3: { header: 'Maximize If Free', sub: 'Taken only when Tiers 1–2 are untouched.' },
    4: {
        header: 'Get At Least Some',
        sub: 'Breadth first — one meaningful source per stat, then magnitude.',
    },
    5: { header: 'Nice To Have', sub: 'Only when convenient.' },
};

// docs/PHASE10_PLAN.md §15.3 / EC-29: the composite and its two components
// double-count if selected together.
export const WEAPON_DAMAGE_EXCLUSION_GROUP = [
    'weapon base damage',
    'weapon damage',
    'base damage dice',
];

export const CAP_ERROR = 'Cap must be a positive integer.';

export function emptyLanes(): Lanes {
    return { 1: [], 2: [], 3: [], 4: [], 5: [] };
}

export function cloneLanes(lanes: Lanes): Lanes {
    return {
        1: lanes[1].map((c) => ({ ...c })),
        2: lanes[2].map((c) => ({ ...c })),
        3: lanes[3].map((c) => ({ ...c })),
        4: lanes[4].map((c) => ({ ...c })),
        5: lanes[5].map((c) => ({ ...c })),
    };
}

export function allChips(lanes: Lanes): { chip: StatChip; tier: Tier }[] {
    const out: { chip: StatChip; tier: Tier }[] = [];
    for (const t of TIERS) for (const chip of lanes[t]) out.push({ chip, tier: t });
    return out;
}

export function findTier(lanes: Lanes, stat: string): Tier | null {
    const key = stat.trim().toLowerCase();
    for (const t of TIERS) {
        if (lanes[t].some((c) => c.stat.trim().toLowerCase() === key)) return t;
    }
    return null;
}

// The single gate every add path goes through. Enforces INV-4 (weapon damage
// mutual exclusion). It deliberately does NOT reject an already-present stat as
// an error: "already there" is a no-op decided by the caller, not a failure.
export function canAddStat(lanes: Lanes, stat: string): { ok: boolean; reason?: string } {
    const key = stat.trim().toLowerCase();
    if (!key) return { ok: false, reason: 'Enter a stat name.' };

    if (WEAPON_DAMAGE_EXCLUSION_GROUP.includes(key)) {
        const conflict = allChips(lanes)
            .map(({ chip }) => chip.stat.trim().toLowerCase())
            .find((s) => s !== key && WEAPON_DAMAGE_EXCLUSION_GROUP.includes(s));
        if (conflict) {
            const composite = 'weapon base damage';
            const reason =
                key === composite
                    ? `Weapon base damage already includes ${conflict}. Remove ${conflict} first, or keep it instead of the composite.`
                    : `Weapon base damage already includes ${key}. Remove the composite first if you want to prioritize ${key} on its own.`;
            return { ok: false, reason };
        }
    }
    return { ok: true };
}

// INV-2: flatten lanes in tier order; array position IS intra-tier rank. There
// is deliberately no `order` and no `value` on the wire — Python derives rank
// from array position (see the StatPriorityEntry doc comment in app.go).
export function serializePriorities(lanes: Lanes): main.StatPriorityEntry[] {
    const out: main.StatPriorityEntry[] = [];
    for (const tier of TIERS) {
        for (const chip of lanes[tier]) {
            out.push({
                stat: chip.stat,
                tier,
                ...(chip.cap ? { cap: chip.cap } : {}),
            } as main.StatPriorityEntry);
        }
    }
    return out;
}

// Exact inverse of serializePriorities (§3.7), lossless by construction.
// Entries without a usable tier (legacy flat-list files, where `tier` is absent
// entirely) land in Tier 1 so nothing is silently dropped on load.
export function hydrateLanes(entries: main.StatPriorityEntry[] | undefined | null): Lanes {
    const lanes = emptyLanes();
    if (!entries) return lanes;
    for (const e of entries) {
        if (!e || !e.stat) continue;
        const tier = (e.tier && e.tier >= 1 && e.tier <= 5 ? e.tier : 1) as Tier;
        if (findTier(lanes, e.stat)) continue; // INV-1, defensively
        lanes[tier].push({ stat: e.stat, ...(e.cap ? { cap: e.cap } : {}) });
    }
    return lanes;
}

export function isValidCap(raw: string): boolean {
    const trimmed = raw.trim();
    if (!/^\d+$/.test(trimmed)) return false;
    return parseInt(trimmed, 10) >= 1;
}

// --- Legacy caster-field migration (§5.3) ----------------------------------

export interface LegacyMigrationResult {
    priorities: main.StatPriorityEntry[];
    migrated: number;
}

// Folds a legacy payload's caster_spellpowers/caster_schools into Tier 1.
// Runs ONCE at load time, never as a standing reactive statement — the old
// code's bug (unchecking a school left its priority behind forever) came from
// keeping two representations of the same intent in sync continuously.
//
// Stats already placed anywhere keep their existing tier (EC-8): the migration
// only adds what is missing.
export function migrateLegacyCasterFields(
    priorities: main.StatPriorityEntry[] | undefined | null,
    casterSpellpowers: string[] | undefined | null,
    casterSchools: string[] | undefined | null
): LegacyMigrationResult {
    const lanes = hydrateLanes(priorities);
    let migrated = 0;

    for (const raw of [...(casterSpellpowers ?? []), ...(casterSchools ?? [])]) {
        const stat = (raw ?? '').trim();
        if (!stat) continue;
        if (findTier(lanes, stat)) continue;
        if (!canAddStat(lanes, stat).ok) continue;
        lanes[1].push({ stat });
        migrated++;
    }

    return { priorities: serializePriorities(lanes), migrated };
}
