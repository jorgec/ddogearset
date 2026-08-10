import {
    GetItemDetails,
    GetSetBonus,
    GetAugmentByName,
    GetFiligreeByName,
} from '../../../wailsjs/go/main/App';
import type { models } from '../../../wailsjs/go/models';

// Per-session read-through caches for the item-detail panel.
//
// There is no TTL and no background invalidation: the catalog is a static,
// versioned artifact (catalog.db, seeded once at app launch — see
// docs/0.5.0/00_ETL_START_HERE.md Phase 6), so within one running session the
// Go-side caches it backs never change. clearItemCatalogCache() exists for a
// future catalog-update feature (schema doc §5.1.2, not built in 0.5.0), not
// for anything called today.
//
// Every backend lookup below returns a ZERO-VALUE struct rather than an error on
// a miss (see app.go's GetSetBonus/GetAugmentByName/GetFiligreeByName), so an
// empty Name/Type is the uniform not-found signal and is normalized to null here.

const itemCache = new Map<string, models.XMLItem>();
const setBonusCache = new Map<string, models.XMLSetBonus | null>();
const augmentCache = new Map<string, models.XMLAugment | null>();
const filigreeCache = new Map<string, models.XMLFiligree | null>();

export async function fetchItem(name: string): Promise<models.XMLItem> {
    const cached = itemCache.get(name);
    if (cached) return cached;
    const item = await GetItemDetails(name);
    itemCache.set(name, item);
    return item;
}

export async function fetchSetBonus(name: string): Promise<models.XMLSetBonus | null> {
    if (setBonusCache.has(name)) return setBonusCache.get(name)!;
    const set = await GetSetBonus(name);
    const result = set?.Type ? set : null;
    setBonusCache.set(name, result);
    return result;
}

export async function fetchAugment(name: string): Promise<models.XMLAugment | null> {
    if (augmentCache.has(name)) return augmentCache.get(name)!;
    const aug = await GetAugmentByName(name);
    const result = aug?.Name ? aug : null;
    augmentCache.set(name, result);
    return result;
}

export async function fetchFiligree(name: string): Promise<models.XMLFiligree | null> {
    if (filigreeCache.has(name)) return filigreeCache.get(name)!;
    const fil = await GetFiligreeByName(name);
    const result = fil?.Name ? fil : null;
    filigreeCache.set(name, result);
    return result;
}

// Call from the success path of UpdateExternalSources so a data refresh does not
// leave the frontend serving items the Go caches have already replaced.
export function clearItemCatalogCache(): void {
    itemCache.clear();
    setBonusCache.clear();
    augmentCache.clear();
    filigreeCache.clear();
}
