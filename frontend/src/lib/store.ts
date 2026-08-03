import { writable } from 'svelte/store';
import type { main } from '../../wailsjs/go/models';

export const configStore = writable<main.OptimizationPayload>({
    gearset_name: "",
    max_level: 34,
    build_type: "Melee",
    weapon_style: "Two Weapon Fighting",
    swashbuckling: false,
    offhand_style: "None",
    caster_spellpowers: [],
    caster_schools: [],
    stat_priorities: {},
    armor_restriction: "Light",
    reserved_minor_artifact_slot: "Ring",
    minor_artifact_filigree_slots: 4,
    exclude_gem_of_many_facets: false,
    runearm_use: false,
    excluded_packs: [],
    raid_item_limit: 2,
    is_dino_artifact: false,
    output_filename: "",
    pre_equipped: {} as Record<string, string>,
    pre_filled_augments: {} as Record<string, string[]>,
    pre_filled_filigrees: { weapon: [], artifact: [] } as { weapon: string[], artifact: string[] },
    calculate_only: false
});

export interface ResultPayload {
    success: boolean;
    error?: string;
    timeTaken?: number;
    gearSet?: Record<string, string>;
    realizedStats?: Record<string, number>;
    activeSets?: string[];
    filigrees?: Record<string, string[]>;
    allEffects?: Record<string, string[]>;
}

export const resultStore = writable<main.ResultPayload | null>(null);
export const logsStore = writable<string[]>([]);
export const isParsing = writable(false);
export const isOptimizing = writable(false);
export const currentTab = writable<'solver' | 'editor' | 'filigrees' | 'summary'>('solver');
