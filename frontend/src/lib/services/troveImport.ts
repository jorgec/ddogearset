// Shared CSV-loading logic for both Trove import surfaces (the solver-form
// accordion and the standalone Owned Items screen). A load from either one
// must populate everything the other needs — see troveImportStore in
// store.ts — so this fetches both RPC shapes together rather than letting
// each screen only fetch its own half.
import { LoadTroveInventory, GetTroveOwnedItems } from '../../../wailsjs/go/main/App';
import { troveImportStore } from '$lib/store';

export interface TroveLoadResult {
    success: boolean;
    errorMessage?: string;
    totalRows: number;
    ownedNamesCount: number;
    itemsCount: number;
}

export async function loadTroveCsv(csvContent: string, fileName: string): Promise<TroveLoadResult> {
    const [namesResult, itemsResult] = await Promise.all([
        LoadTroveInventory(csvContent),
        GetTroveOwnedItems(csvContent),
    ]);
    if (!namesResult.success) {
        return { success: false, errorMessage: namesResult.errorMessage || 'unknown error', totalRows: 0, ownedNamesCount: 0, itemsCount: 0 };
    }
    if (!itemsResult.success) {
        return { success: false, errorMessage: itemsResult.errorMessage || 'unknown error', totalRows: 0, ownedNamesCount: 0, itemsCount: 0 };
    }

    const ownedNames = namesResult.ownedNames ?? [];
    const items = itemsResult.items ?? [];
    const totalRows = namesResult.totalRows ?? itemsResult.totalRows ?? 0;

    troveImportStore.set({
        fileName,
        totalRows,
        ownedNames,
        items,
        restrictToOwned: true,
    });

    return { success: true, totalRows, ownedNamesCount: ownedNames.length, itemsCount: items.length };
}
