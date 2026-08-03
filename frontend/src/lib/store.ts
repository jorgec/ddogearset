import { writable } from 'svelte/store';
import type { main } from '../../wailsjs/go/models';

export const configStore = writable<main.OptimizationPayload>({
    max_levels: [32],
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
    raid_item_limit: 2
});

export const resultStore = writable<main.ResultPayload | null>(null);
export const logsStore = writable<string[]>([]);
export const isParsing = writable(false);
export const isOptimizing = writable(false);
