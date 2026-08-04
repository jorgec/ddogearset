# Phase 10 Handoff & Retrospective — Tiered Priority Solver

**Branch:** `feature/tiered-priority-solver`
**Status:** Implementation complete, verified end-to-end, uncommitted → committed by this doc's own commit.
**Audience:** Whoever picks this branch up next (future you, or a reviewer) without the benefit of this session's context.

This document is the successor to `docs/BRANCH_DISCUSSION.md` (which covers the *planning* phase — architectural decisions, tradeoffs, user-confirmed choices). This doc covers the *implementation* phase: what actually got built, what broke and how it was fixed, what's still loose, and what to do next. Read `BRANCH_DISCUSSION.md` first if you need the "why," then this doc for the "what happened."

---

## What Shipped

Five sequential builder passes, each verified before the next started:

| Pass | Scope | Files | Verification |
|---|---|---|---|
| **10a** | Python tiered solve core | `python/optimizer.py`, `python/solver.py`, `python/cli.py`, `python/tests/test_phase10_tiered.py` | 81 tests passing (later 85 after the lock-fix pass) |
| **10b** | Go wire contract + RPCs | `app.go`, `app_test.go`, wails bindings, `python/dist/solver` rebuild | `go build`/`vet`/`test` clean, live end-to-end smoke test |
| **Lock-fix** | Correctness bug found by 10b's smoke test | `python/optimizer.py`, `python/tests/test_phase10_tiered.py`, `python/dist/solver` rebuild | 85 tests passing, real payload re-verified |
| **Item Detail** | Go XML parsing + Svelte component | `internal/models/models.go`, `internal/services/parser.go`, `internal/services/enrichment.go`, `app.go` (additive), `frontend/src/lib/services/itemCatalog.ts`, `frontend/src/lib/components/domain/ItemDetail.svelte`, `internal/services/parser_faulttolerance_test.go` | 11 new Go tests, real-corpus smoke test (8,779 items, 0 skipped) |
| **Frontend restructure** | Tier lanes, stat picker, stat sets, accordions | `app.go` (additive: `GetStatSets`), `data/stat_sets.default.json`, 6 new Svelte/TS files, `JobConfigurationForm.svelte`, `Summary.svelte`, `GearsetEditor.svelte`, `store.ts`, `Toast.svelte` | `npm run check`/`build` clean, live dev-server smoke test |

Combined final verification (after merging all five passes in one working tree): `go build`, `go vet`, `go test` all clean; `npm run check` at the same 7-error pre-existing baseline (zero new errors); `npm run build` succeeds; `pytest python/tests/` → 85 passed.

---

## The One Real Bug: Tier-Lock Zero-Margin Self-Check

This is the most important thing in this document. It was found by 10b's smoke test, not by 10a's own unit tests, because it only manifests when a real multi-tier config is solved end-to-end through actual GLPK — the exact kind of thing unit tests with synthetic small models don't exercise well.

**Symptom:** Every solve degraded. Tier 1 locked; every tier from 2 onward reported `lock_violation` and got rolled back. Final gearset had 6 equipped slots instead of ~13, and `degraded: true` on every single run — not intermittent, not a rare artifact.

**Root cause:** `solve_tiered()` built the lock constraint and *verified* it with the same tolerance function:

```python
# constraint:
prob += (model.goals[t] >= v - _lock_tolerance(v), name)
# check, one stage later:
if _goal_value(model.goals[j]) < vj - _lock_tolerance(vj):
```

Every later stage optimizes a *different* goal, so the solver has every incentive to spend the locked tier's entire allowed slack and park `G_t` **exactly on** the constraint boundary. The post-solve guard then compared a value the solver had deliberately driven to equal the boundary against that same boundary — zero headroom. Whether the check passed or failed came down to how GLPK's solution-file round trip (12 significant digits) rounded the last digit. Instrumented numbers from the actual failing run:

```
lock tier 4: V=2.972222222222222   now=2.97221222222279...
```

A ~2.2e-12 deviation, well inside GLPK's own feasibility tolerance, decided whether the entire tier got discarded.

**Fix:** A second, *tighter* tolerance (`_lock_check_tolerance`, ~10x smaller than the lock constraint's own tolerance) used only for the post-solve verification, giving real margin between "the constraint we told GLPK to satisfy" and "the check we use to decide whether it did." `_lock_tolerance()` itself — the one that defines actual tier semantics — was deliberately left untouched, per its own code comment warning against widening it casually.

**Why this matters for whoever reads this next:** if you ever touch tier-locking logic again, the lesson is — **never verify a hard constraint's satisfaction using the exact same tolerance you used to construct it.** The solver will always try to sit exactly on a binding constraint's boundary when there's no reward for exceeding it, and float round-trips through any file-based solver (GLPK via `GLPK_CMD` writes/reads plaintext) will occasionally push a boundary-sitting value to either side of that boundary by an amount much smaller than any reasonable "tolerance," but not smaller than a zero-margin check.

---

## Deliberate Spec Deviations (All Documented Inline, Consolidated Here)

These are places where the implementation differs from the original planning docs (`PHASE10_PLAN.md`, `ITEM_DETAIL_SPEC.md`, `TIERED_SOLVER_FRONTEND_SPEC.md`). Each was a judgment call made by a builder pass, not an oversight — but you should know about them.

### Backend (10a)
1. **`WeaponBase:Weapon1`** used as the bonus-type string instead of the spec's bare `WeaponBase`. Behaviorally identical (Weapon1-only either way); the qualified string is a structural guard against an accidental future Weapon2 leak.
2. **Weapon-stat mutual-exclusion is a `tierReport.notes` warning**, not a hard rejection. The spec's own edge case (EC-29) says the backend must not reject; an earlier instruction said "implement a guard" — the notes-warning approach satisfies EC-29's letter.
3. **Alternatives ranking is deterministic local search**, not a per-candidate ILP re-solve. The collapsed objective score isn't linear in the augment-choice binaries, so an "honest" ILP would need a miniature model per candidate — up to 30 file-based GLPK spawns per alternatives request. Local search over a pre-filtered shortlist reaches the same assignment for realistic augment-slot counts (≤5) at a fraction of the cost.
4. **Reconciliation objective is `Σz + Σn`**, not `Σz` alone as literally read from §6. `n_s` (normalized attainment) is a pure follower variable with no upward pressure of its own — without a coefficient, the solver parks it at the lock's tolerance floor instead of its true achieved value, which corrupts `tierScores`. Caught by 3 failing tests before the fix.
5. **`tierScores` recomputed from the final reconciled solution**, not echoed from stage records, so it's a real assertion rather than a tautology in tests.

### Item Detail
1. **Critical-range display formula corrected.** Spec §7.4 says render `20 - CriticalThreatRange`; that's off by one. A threat range of 3 means rolls of 18/19/20 crit, so the correct low end is `21 - range`. Implemented the correct formula; the spec text itself has the bug.
2. **`frontend/src/lib/types/itemDetail.ts` (spec §8's stopgap type file) was never created.** The spec describes it as scaffolding "until `wails generate module` is run… then delete this file." Since bindings regeneration succeeded during this same pass, the stopgap would have been born dead — everything imports the generated `wailsjs/go/models` namespace directly.
3. **`clearItemCatalogCache()` exists but isn't wired up.** Spec §5 wants it called from `JobConfigurationForm.svelte`'s data-refresh handler, but that file was out of scope for the Item Detail pass (owned by the parallel frontend pass). See "Loose Ends" below.

### Frontend
1. **Drag-and-drop was never built** — buttons only for reordering/moving stats between tiers, exactly as §3.4 specifies (not a deviation, just confirming the spec was followed on a point that might look like an oversight).
2. Two UX polish fixes discovered during live smoke-testing and applied on the spot: the stat-picker popover was overflowing the narrow form panel (`30rem` → `21rem`), and one exclusion-guard toast message read circularly when a user tried to add the exact stat already blocking them.

---

## Known Issues (Pre-Existing, Out of Scope, Deferred — Not Regressions)

These existed before this branch or are explicitly deferred by the specs. Listed so nobody mistakes them for new bugs.

1. **Conditional set-bonus membership can disagree between the solver and the Item Detail panel.** The Python solver's `.//SetBonus` XPath search and the Go-side structural parser resolve conditional/embedded set bonuses slightly differently on a small number of items. Documented as a known limitation in `ITEM_DETAIL_SPEC.md` §11.2; not fixed in this branch by design.
2. **`SlotDetail.item` has no `buffs` field**, so item-level "counted by optimizer" badges in `ItemDetail.svelte` never render today when opened from a post-solve results view — they degrade gracefully to the no-context state instead. This is the mandated §6.2 degradation path working as designed; it'll start rendering automatically if a future pass adds `buffs` to `SlotDetail.item`.
3. **`npm run check`'s 7-error baseline** (all pre-existing, none touched by this branch): `GearsetEditor` `Name`/`filigrees` typing, a `FiligreeEditor` unused-import issue, and `Summary.svelte`'s legacy plain-slot-map literal missing `convertValues`. None of the five builder passes introduced new errors; all five independently confirmed this against the baseline.
4. **Raid detection is unavailable.** No raids data file exists in this repo (`InitEnrichment`'s raids path is optional and currently unpopulated). `ItemDetail.svelte` shows an honest "not available" note rather than fabricating a raid flag. This was a known limitation going into the branch, not discovered during implementation.

---

## Loose Ends (Small, Should Be Closed Before/During Next Session)

1. **Wire up `clearItemCatalogCache()`.** One call needed in `JobConfigurationForm.svelte`'s `handleUpdateData` (or wherever `UpdateExternalSources()` is invoked from the UI), right after a successful refresh. Without it, a data refresh silently continues serving pre-refresh item data to the Item Detail panel for the rest of the session.
2. **`python/dist/solver` binary staleness discipline.** This binary was rebuilt twice during this session (once after 10b, once after the lock-fix) — it must be rebuilt via `pyinstaller --noconfirm solver.spec` from `python/` any time `optimizer.py` or `solver.py` changes, since Go invokes the bundled binary, not the `.py` source, in the packaged app. There's no CI check enforcing this staleness relationship; it's manual discipline only. Worth a future TODO: a Makefile target or pre-commit hook that rebuilds the binary whenever the Python source changes.
3. **No live in-app verification of a full `RunOptimization` → `TierReport.svelte` round trip inside the actual Wails app shell.** Both `GetStatSets` and the tiered solve were verified — separately — via a live dev server (frontend only, `TierReport` verified by construction against `app.go`'s structs) and via direct Go/Python invocation with real payloads. Nobody has yet clicked "Optimize" in the actual running Wails desktop app and watched a `TierReport` render from a live `RunOptimization` call. Recommended as the first smoke test next session, before anything else.
4. **`docs/PHASE9_PLAN.md`'s suggestion (§13/§2.7) to record the conditional-set-bonus divergence there was skipped** — none of the builder passes were permitted to touch `docs/` files. This handoff doc is where that note now lives instead (see Known Issues #1 above).

---

## Test Inventory (What Actually Got Run, Where)

- **Python:** `pytest python/tests/` → 85 passed (includes `test_phase10_tiered.py`'s 81 original + 4 lock-fix regression tests, plus all pre-existing suites unaffected).
- **Go:** `go test ./...` → clean, including new `app_test.go` (8 wire-contract round-trip tests) and `internal/services/parser_faulttolerance_test.go` (11 tests covering fault tolerance, set-bonus parsing, and the conditional-set-bonus non-leak property).
- **Frontend:** `npm run check` (7 pre-existing errors, 0 new) and `npm run build` (succeeds).
- **Real-data smoke tests:**
  - Full 5-tier optimize + alternatives + calculate against real `.ddogearset` fixtures, driven through the actual `python/dist/solver` binary via the real Go `App` methods (10b + lock-fix passes).
  - Full XML corpus parse: 8,779 items, 0 skipped, 32,381 buffs, 676 items with effects, 264 set bonuses + 64 filigree sets — all matching the spec's own stated corpus figures (Item Detail pass).
  - Live dev-server interaction with the new stat-priority form: tier lanes, drill-down picker, search, custom-stat escape hatch, mutual-exclusion blocking, cap editing/validation, reorder, accordion persistence across reload (Frontend pass).

No pass has yet exercised the full stack together inside the actual packaged Wails app — see Loose End #3.

---

## Suggested Next Session

1. Open the actual Wails app (`wails dev` or equivalent), load a real gearset, and run one full Optimize → results cycle, watching `TierReport.svelte` render live. This is the one path no automated test or isolated smoke test has covered.
2. Close Loose End #1 (`clearItemCatalogCache()` wiring) — five-minute fix.
3. Decide whether to reconcile the solver's vs. Item Detail panel's conditional-set-bonus logic (Known Issue #1), or formally accept the divergence and document it user-facing (e.g. a note in the panel itself) rather than just in these docs.
4. Consider the Makefile/pre-commit idea from Loose End #2 if `python/dist/solver` staleness becomes a recurring source of confusion.

---

## Cross-References

- **Planning rationale, user decisions, architecture tradeoffs:** [`docs/BRANCH_DISCUSSION.md`](BRANCH_DISCUSSION.md)
- **Backend spec:** [`docs/PHASE10_PLAN.md`](PHASE10_PLAN.md)
- **Item Detail spec:** [`docs/ITEM_DETAIL_SPEC.md`](ITEM_DETAIL_SPEC.md)
- **Frontend spec:** [`docs/TIERED_SOLVER_FRONTEND_SPEC.md`](TIERED_SOLVER_FRONTEND_SPEC.md)
