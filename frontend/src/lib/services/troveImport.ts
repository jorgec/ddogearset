// Trove inventory import. Drag-and-drop only — there is no file-open button
// any more, and this is the single place a dropped CSV is turned into app
// state, so a drop on either zone populates everything both screens need
// (see troveImportStore in store.ts).
//
// Takes a PATH and hands it to Go, which reads the file itself. That is the
// whole point of the drag-and-drop-only design:
//
//   * The CSV never crosses the IPC bridge. It used to be sent TWICE,
//     concurrently, to two RPCs that each parsed it — and Wails' calls.js
//     swallows a failed send with nothing but a console.error and no timeout,
//     so a send that did fail would have left the UI stuck forever.
//   * There is no <input type="file"> in the flow at all, so the element
//     lifetime bug that silently dropped loads cannot recur here
//     (docs/FILE_DIALOG_SILENT_DROP.md).
//
// A drop also works when the window is not focused, which the button never
// did: macOS spends the first click on an unfocused window activating it
// (WKWebView.acceptsFirstMouse is false), so clicking straight onto the old
// button from Finder did nothing at all.
import { LoadTroveFromPath } from '../../../wailsjs/go/main/App';
import { troveImportStore, troveImporting, showToast } from '$lib/store';
import { withTimeout } from '$lib/services/rpc';

// Go waits up to 15s for the item catalog before answering, so this has to
// clear that or it would fire on a legitimately slow first import.
const IMPORT_TIMEOUT_MS = 25_000;

/** True when the dropped path looks like a Trove export we can read. */
export function isCsvPath(path: string): boolean {
    return path.toLowerCase().endsWith('.csv');
}

/**
 * Imports the CSV at `path` and reports the outcome by toast. Every drop zone
 * routes here, so the result is identical wherever the file was dropped.
 */
export async function importTroveFromPath(path: string): Promise<void> {
    troveImporting.set(true);
    try {
        const result = await withTimeout(
            LoadTroveFromPath(path),
            IMPORT_TIMEOUT_MS,
            'Trove import',
        );

        if (!result.success) {
            showToast('Could not import that CSV: ' + (result.errorMessage || 'unknown error'), 'error');
            return;
        }

        troveImportStore.set({
            fileName: result.fileName,
            totalRows: result.totalRows,
            ownedNames: result.ownedNames ?? [],
            items: result.items ?? [],
            restrictToOwned: true,
        });

        showToast(
            `${result.fileName} — ${result.totalRows} rows, ` +
            `${(result.items ?? []).length} usable items, ` +
            `${(result.ownedNames ?? []).length} owned names.`,
            'success',
        );
    } catch (e) {
        showToast('Could not import that CSV: ' + e, 'error');
    } finally {
        troveImporting.set(false);
    }
}
