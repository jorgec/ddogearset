// One file-open dialog for the whole app, because the obvious way to write it
// is silently broken in the webview this app actually ships in.
//
// THE BUG THIS EXISTS TO PREVENT
//
// Every loader here used to do the textbook thing:
//
//     const input = document.createElement('input');
//     input.type = 'file';
//     input.onchange = (e) => { ...read the file... };
//     input.click();                       // <- input is never referenced again
//
// On macOS the webview is WKWebView, and `input` above is unreachable from JS
// the moment the function returns: it is not in the document, and nothing
// holds it. The pending native file chooser does not keep it alive either —
// verified directly, with a FinalizationRegistry that fired WHILE the Open
// panel was still on screen. Once the element is collected the chooser it
// owned goes with it, so the file the user then picks arrives nowhere: no
// `change` event, no error, no log line. The load is dropped in silence.
//
// It is intermittent because it is a race against a garbage collector: whether
// the element survives depends on how long the panel stays open and how much
// the page allocates meanwhile (StatusConsole polls GetSystemLogs every second
// and the log array is never trimmed, so the page always allocates).
//
// MEASURED, on macOS 26.5.2, in a WKWebView harness whose WKUIDelegate stands
// in for the Open panel so the dwell time is a parameter:
//
//     dwell <= 2s   CLICK -> CHANGE_FIRED -> READ_OK -> COLLECTED    loads
//     dwell >= 3s   CLICK -> COLLECTED                               dropped, 6/6 trials
//
// The fix is to make the element reachable for as long as the dialog can be
// open. Either of these is sufficient on its own (both verified in the same
// harness, under deliberately heavy allocation pressure); this module does
// both, because they cost nothing:
//
//   1. put the input in the document, and
//   2. hold a module-level reference to it.
//
// Cancelling is reported by the `cancel` event (WebKit 16.4+, WebView2/Chromium
// 113+). On an engine too old for it a cancelled pick leaves its promise
// pending — deliberately preferred over a focus-based fallback, which cannot
// distinguish "the user cancelled" from "the user is still browsing" and would
// therefore reintroduce the exact silent-drop this module exists to remove.
// The next pick clears the stale one, so at most one is ever outstanding.

interface PendingPick {
    input: HTMLInputElement;
    settle: (file: File | null) => void;
}

// THE load-bearing reference. Module scope, so it outlives the call that
// created it and the collector cannot touch the input mid-dialog.
let pending: PendingPick | null = null;

/**
 * Opens the system file dialog and resolves with the chosen file, or null if
 * the user cancelled. Must be called synchronously from a user gesture (a
 * click handler) — the `.click()` below only opens a dialog while the browser
 * still considers itself inside one.
 */
export function pickFile(accept: string): Promise<File | null> {
    return new Promise((resolve) => {
        // Retire a pick that never reported an outcome (see the `cancel` note
        // above) so at most one hidden input is ever in the document.
        pending?.settle(null);

        const input = document.createElement('input');
        input.type = 'file';
        input.accept = accept;
        // Out of sight but in the document, and fixed-positioned so it takes
        // part in no layout.
        input.style.position = 'fixed';
        input.style.left = '-9999px';
        input.style.opacity = '0';
        document.body.appendChild(input);

        let settled = false;
        const settle = (file: File | null) => {
            if (settled) return;
            settled = true;
            if (pending?.input === input) pending = null;
            input.remove();
            resolve(file);
        };

        pending = { input, settle };

        input.addEventListener('change', () => settle(input.files?.[0] ?? null), { once: true });
        input.addEventListener('cancel', () => settle(null), { once: true });

        input.click();
    });
}

/**
 * Reads a picked file as text. A FileReader with a read in flight is kept
 * alive by that pending activity (unlike the input element above), so this
 * needs no reference of its own.
 */
export function readTextFile(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(String(e.target?.result ?? ''));
        reader.onerror = () => reject(new Error('Failed to read the selected file.'));
        reader.readAsText(file);
    });
}
