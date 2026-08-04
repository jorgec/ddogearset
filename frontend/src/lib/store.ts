import { writable } from 'svelte/store';
import type { main } from '../../wailsjs/go/models';

export const configStore = writable<main.OptimizationPayload>(({
    gearset_name: "",
    max_level: 34,
    build_type: "Melee",
    weapon_style: "Two Weapon Fighting",
    swashbuckling: false,
    offhand_style: "None",
    caster_spellpowers: [],
    caster_schools: [],
    stat_priorities: [],
    armor_restriction: "Light",
    reserved_minor_artifact_slot: "Ring",
    minor_artifact_filigree_slots: 4,
    exclude_gem_of_many_facets: false,
    runearm_use: false,
    excluded_packs: [],
    raid_item_limit: 2,
    max_search_time: 60,
    is_dino_artifact: false,
    output_filename: "",
    pre_equipped: {} as Record<string, string>,
    pre_filled_augments: {} as Record<string, Record<string, string>>,
    pre_filled_filigrees: { weapon: [], artifact: [] } as { weapon: string[], artifact: string[] },
    calculate_only: false
}) as unknown as main.OptimizationPayload);

export interface ResultPayload {
    success: boolean;
    error?: string;
    timeTaken?: number;
    gearSet?: Record<string, string>;
    realizedStats?: Record<string, number>;
    activeSets?: string[];
    filigrees?: Record<string, string[]>;
    allEffects?: Record<string, string[]>;
    slots?: Record<string, SlotDetail>;
}

export interface SlotBuff {
    stat: string;
    bonus: string;
    value: number;
}

export interface SlotAugment {
    color: string;
    name: string;
    buffs: SlotBuff[];
}

export interface SlotFiligree {
    name: string;
    buffs: SlotBuff[];
}

export interface SlotSetBonusContribution {
    set: string;
    pieces: number;
    buffs: SlotBuff[];
}

export interface SlotDetail {
    location: string;
    item: {
        name: string;
        file?: string;
        ml: number;
        is_raid: boolean;
        pack: string | null;
        minor: boolean;
    };
    augments: SlotAugment[];
    filigrees: SlotFiligree[];
    set_bonus_contributions: SlotSetBonusContribution[];
}

export const resultStore = writable<main.ResultPayload | null>(null);

// Snapshot of stat_priorities taken immediately before the last stat-set apply,
// backing the single-step Undo offered in that apply's toast
// (docs/TIERED_SOLVER_FRONTEND_SPEC.md §6.4). It is overwritten by the next
// apply and cleared by any other priority-list mutation, so "Undo" always means
// "undo the last stat-set apply specifically" and never restores stale state.
export const statSetUndoSnapshot = writable<main.StatPriorityEntry[] | null>(null);

// Lowercased stat names to flash briefly in StatPriorityEditor after a stat-set
// apply, so the user can see at a glance which stats the set disagreed with
// without having to parse the toast text (§6.4).
export const highlightedStats = writable<string[]>([]);

export function flashStats(stats: string[], durationMs = 3000) {
    if (stats.length === 0) return;
    const lowered = stats.map(s => s.toLowerCase());
    highlightedStats.set(lowered);
    setTimeout(() => {
        highlightedStats.update(current =>
            current === lowered || current.join('|') === lowered.join('|') ? [] : current
        );
    }, durationMs);
}
export const logsStore = writable<string[]>([]);
export const isParsing = writable(false);
export const isOptimizing = writable(false);
export const currentTab = writable<'solver' | 'editor' | 'filigrees' | 'summary' | 'itemSearch'>('solver');

// Computes hydrated pre_equipped/pre_filled_augments/pre_filled_filigrees from
// the current config plus the last known solved/loaded gearset's per-slot
// detail, filling in any slot/bucket the config doesn't already have an
// explicit value for. Used before any `calculate_only` RunOptimization call
// (GearsetEditor's "Calculate Stats", Summary's post-load recompute) so the
// solver locks in the actual equipped gearset instead of treating anything
// not manually picked in the editor as unequipped — see docs/ENGINEERING.md
// "Known Issues" for the destructive-clear bug this fixes.
export function hydrateConfigFromSlots(
    config: main.OptimizationPayload,
    slots: Record<string, SlotDetail> | undefined
): Pick<main.OptimizationPayload, 'pre_equipped' | 'pre_filled_augments' | 'pre_filled_filigrees'> | null {
    if (!slots) return null;

    const preEquipped: Record<string, string> = { ...config.pre_equipped };
    // Keyed by slot -> augment color/type -> augment name or array of names.
    // We allow arrays so that if an item has multiple slots of the exact same color,
    // they aren't overwritten.
    const preFilledAugments: Record<string, Record<string, string | string[]>> = { ...config.pre_filled_augments };
    const preFilledFiligrees = {
        weapon: [...(config.pre_filled_filigrees?.weapon ?? [])],
        artifact: [...(config.pre_filled_filigrees?.artifact ?? [])],
    };

    for (const [slot, detail] of Object.entries(slots)) {
        if (!(slot in preEquipped)) {
            preEquipped[slot] = detail.item?.name;
        }
        if (!(slot in preFilledAugments) && detail.augments?.length) {
            const byColor: Record<string, string | string[]> = {};
            for (const a of detail.augments) {
                if (byColor[a.color]) {
                    if (Array.isArray(byColor[a.color])) {
                        (byColor[a.color] as string[]).push(a.name);
                    } else {
                        byColor[a.color] = [byColor[a.color] as string, a.name];
                    }
                } else {
                    byColor[a.color] = a.name;
                }
            }
            preFilledAugments[slot] = byColor;
        }
        if (slot === 'Weapon1' || slot === 'Weapon2') {
            if (preFilledFiligrees.weapon.length === 0 && detail.filigrees?.length) {
                preFilledFiligrees.weapon = detail.filigrees.map(f => f.name);
            }
        } else if (detail.item?.minor) {
            if (preFilledFiligrees.artifact.length === 0 && detail.filigrees?.length) {
                preFilledFiligrees.artifact = detail.filigrees.map(f => f.name);
            }
        }
    }

    return { pre_equipped: preEquipped, pre_filled_augments: preFilledAugments, pre_filled_filigrees: preFilledFiligrees };
}

// --- Toast notifications ---------------------------------------------------
// Lightweight in-app toast system used to confirm completion of user-triggered
// operations (save, load, calculate, hydrate, auto-solve, data update) since
// these run silently otherwise. Rendered by Toast.svelte, mounted once in App.svelte.
export interface ToastAction {
    label: string;
    onClick: () => void;
}

export interface ToastMessage {
    id: number;
    text: string;
    kind: 'success' | 'error' | 'info';
    // Actions turn a toast into a decision point (the Undo / Replace-instead
    // pair after applying a stat set). A toast carrying actions must not vanish
    // on the standard timer — see TOAST_ACTION_DURATION_MS below.
    actions?: ToastAction[];
}

export const toastStore = writable<ToastMessage[]>([]);

let toastCounter = 0;
const TOAST_DURATION_MS = 3500;
// Long enough to read and decide, short enough that abandoned action toasts
// don't accumulate on screen indefinitely.
const TOAST_ACTION_DURATION_MS = 8000;

export function dismissToast(id: number) {
    toastStore.update(list => list.filter(t => t.id !== id));
}

export function showToast(
    text: string,
    kind: ToastMessage['kind'] = 'success',
    actions?: ToastAction[]
) {
    const id = ++toastCounter;
    toastStore.update(list => [...list, { id, text, kind, actions }]);
    setTimeout(() => {
        dismissToast(id);
    }, actions && actions.length > 0 ? TOAST_ACTION_DURATION_MS : TOAST_DURATION_MS);
    return id;
}
