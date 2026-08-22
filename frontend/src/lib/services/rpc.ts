// Timeout wrapper for Wails RPC calls.
//
// Wails' generated bindings return a promise that is settled by a callback the
// Go side sends back. Two things in its calls.js make a lost call unrecoverable
// rather than merely slow:
//
//   * the send itself is wrapped in `try { ... } catch (e) { console.error(e) }`,
//     so a failure to post the message is swallowed and the callback stays
//     registered, and
//   * the timeout parameter defaults to 0, which Wails reads as "wait forever".
//
// So a call that never reaches Go never settles. Anything that disables a
// control for the duration of a call — which is most of this app's actions —
// would then stay disabled for the rest of the session, with nothing logged
// and nothing on screen to explain it. That is the same class of silent
// failure as docs/FILE_DIALOG_SILENT_DROP.md: no error, no log, just a UI that
// stops responding.
//
// The solver call gets a timeout too, but derived rather than fixed — see
// solveTimeoutMs. A flat number would either kill legitimate long solves or be
// so large it never fires.

export class RpcTimeoutError extends Error {
    constructor(label: string, ms: number) {
        super(`${label} did not respond within ${Math.round(ms / 1000)}s`);
        this.name = 'RpcTimeoutError';
    }
}

/**
 * Rejects with RpcTimeoutError if `promise` has not settled within `ms`.
 *
 * The underlying call is not cancelled — Wails has no way to cancel one. This
 * only ensures the CALLER stops waiting, so its `finally` runs and whatever it
 * disabled gets re-enabled.
 */
export function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
    let timer: ReturnType<typeof setTimeout>;
    const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new RpcTimeoutError(label, ms)), ms);
    });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timer)) as Promise<T>;
}


// Slack added to the user's own search budget before a solve is considered
// lost: extracting the bundled solver on a cold start, reading the catalog,
// building the model and marshalling the result all happen outside the search
// itself, and none of them are covered by max_search_time.
const SOLVE_OVERHEAD_MS = 300_000;

/**
 * Timeout for a solve, in ms, derived from the configured search budget.
 *
 * A solve is legitimately long — minutes, on a large search — so this must
 * never be a flat constant: the user sets `max_search_time`, and anything past
 * that plus a wide allowance for the work around it means the call is lost,
 * not slow. Without it a lost solve leaves the UI in "Solving" for the rest of
 * the session, since Wails' own call timeout is infinite by default.
 */
export function solveTimeoutMs(maxSearchTimeSeconds: number | undefined): number {
    const budget = Number.isFinite(maxSearchTimeSeconds) ? Number(maxSearchTimeSeconds) : 0;
    return Math.max(budget, 0) * 1000 + SOLVE_OVERHEAD_MS;
}
