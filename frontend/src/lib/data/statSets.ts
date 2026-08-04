// Thin accessor for the stat-set presets. The DATA is not here — it comes from
// the GetStatSets RPC, which reads a hand-editable ./stat_sets.json override at
// runtime and falls back to the copy embedded in the binary. That indirection
// is the whole point: presets must be editable without a rebuild, which rules
// out the frontend/public/ + fetch() pattern expansions.json uses (Vite copies
// public/ into dist/, and main.go embeds all of dist/ — so a public/ asset is
// baked into the binary forever).
//
// Contrast with statTaxonomy.ts, which IS a source file: that's app vocabulary
// the developer owns; this is user content.

import { GetStatSets } from '../../../wailsjs/go/main/App';
import type { main } from '../../../wailsjs/go/models';

export type StatSetsFile = main.StatSetsFile;
export type StatSet = main.StatSet;

let cached: StatSetsFile | null = null;

/**
 * Loads the preset library. Cached per-session by default; pass
 * `forceRefresh` to re-read the override file from disk, which is what the
 * picker's Reload affordance uses so a user who just hand-edited
 * stat_sets.json can confirm the edit took effect without restarting.
 */
export async function loadStatSets(forceRefresh = false): Promise<StatSetsFile> {
    if (cached && !forceRefresh) return cached;
    cached = await GetStatSets();
    return cached;
}
