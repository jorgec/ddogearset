# Branch Discussion — `feature/tiered-priority-solver`

**Session Date:** August 4, 2026  
**Branch:** `feature/tiered-priority-solver` (created with Phase 10 spec + follow-up planning)  
**Status:** Planning complete (3 implementation-ready specs written and committed); no code implementation yet.

---

## Executive Summary

This branch redesigns the stat-priority solver and associated frontend from a **flat, weighted-sum** system (user specifies stat names + 1–100 weights, solver maximizes a single objective) to a **5-tier lexicographic** system (user specifies stats + discrete tier 1–5, solver maximizes tier 1, then tier 2 subject to tier-1 lock, etc.). This aligns the optimizer's semantics with how players actually think about gear priorities (critical stats must-have → strong secondaries → nice-to-haves), unlocks new solver capabilities (alternatives per slot, stricter consolidation), and simplifies the frontend form UX by replacing free-text input + percentage sliders with visual tier lanes.

The work spans three interconnected pieces:
1. **Backend solver (Phase 10):** Sequential lexicographic solve, tiered objective formulation, weapon-base-stat priorities, reconciliation LP for display accuracy.
2. **Item detail panel:** Full cross-referenced item info (buffs, weapon profile, augment choices, set bonuses, acquisition data).
3. **Frontend form restructure:** Tier lanes instead of weight sliders, static drill-down stat picker, curated stat-set presets with runtime-loaded defaults, hand-rolled accordions for all large UI blocks.

---

## Scope & Deliverables

### Committed Planning Documents

#### 1. [docs/PHASE10_PLAN.md](PHASE10_PLAN.md) (1,046 lines)

**Core tiered-solver backend redesign.** Specifies the sequential lexicographic solve, exact PuLP model construction with normalized-attainment weighting, tier-4 breadth-before-magnitude with big-M safety, consolidation penalty formulation, and post-solve reconciliation LP for display truth.

**Key sections:**
- §1–3: Overview, model additions, source provenance, z vs. z_nofil construction
- §3.4–3.10: Upper-bound computation, normalized attainment, intra-tier weights, goal expressions, penalty constants
- §4–5: Tier-solve driver, consolidation stage, graceful degradation on timeouts
- §6: Post-solve reconciliation LP (mandatory fix for zero-weight display bug)
- §9: New solver output fields (tierReport, tierScores, unmetTier4, unmatchedPriorities, degraded)
- §12: Deferred follow-ups (frontend contract changes, computeFiligreeBias deletion, filigree tie-break rewrite)
- §15 (Addendum): Weapon-stat priorities (base dice, crit profile, [W] multiplier, weapon base damage composite)

**Invariants enforced:**
- Slots never required to be filled (§14/INV-7); consolidation stage empties non-load-bearing items.
- Locks record achieved values, never targeted aspirations (§14.4).
- Filigrees valued directly in tier-1 objective, not via a separate bias term.
- Four weapon-base stats scoped to Weapon1 only (TWF assumption: off-hand duplicates main-hand).

#### 2. [docs/ITEM_DETAIL_SPEC.md](ITEM_DETAIL_SPEC.md) (842 lines)

**Go-side structural XML parsing + reusable Svelte component for full item detail views.**

Solves the problem: today the frontend receives thin `XMLItem` (name, ML, augment slot colors only) and dumps DDOBuilder's raw HTML description. No structured stat data, no augment-choice detail, no set-bonus membership.

**Key design decisions:**
- **Go does display parsing, not stat-matching.** Never ports `normalize_stat_name`; that stays single-sourced in Python. ~25% of item buffs are invisible to the solver by design; Go shows all of it verbatim.
- **Per-file fault tolerance:** Parser skips malformed files instead of aborting entire cache.
- **Enrichment wiring:** Pack ID + Wiki URL computed at cache-load time; raid detection out of scope (no raids data file exists in repo).
- **Component contract:** `ItemDetail.svelte` takes `itemName` + optional `slotDetail` + optional `slot`, self-fetches when context missing (graceful degradation).
- **Credited-marker logic:** When `slotDetail` available (Phase 9.2 rich output), each buff badges whether it counted toward the solve (authoritative, sourced from actual result).

**Sections:**
- §2: New Go model types (XMLBuff, XMLEffect, XMLEmbeddedAugment, weapon/armor fields, set bonuses)
- §3: Parser changes (fault-tolerance, set-bonus endpoint)
- §4: App changes (indexing, enrichment, new RPCs)
- §5: Frontend service layer (`itemCatalog.ts` caching)
- §6: Credited-marker logic (three states: counted, superseded, not a priority)
- §7: Component rendering rules (eight sections: header, stats & buffs, weapon profile, armor, augments, set bonuses, clickies, acquisition, raw description)

**Out of scope:** raid detection (no data source), conditional set-bonus solver divergence (pre-existing, documented).

#### 3. [docs/TIERED_SOLVER_FRONTEND_SPEC.md](TIERED_SOLVER_FRONTEND_SPEC.md) (689 lines)

**Form restructuring, tier lanes, stat picker, stat sets, accordions.**

Replaces the current `JobConfigurationForm.svelte` (472 lines, one flat component with ad-hoc grid layout) with focused components and a visual tier-lane UX.

**Key decisions:**
- **Tier lanes, not dropdown-per-row.** Five spatial lanes (one per tier) with chips, preserving both tier and intra-tier order. INV-1: a stat can only exist in one lane (enforced structurally).
- **Caster checkbox grid deleted.** Never read by backend; backward-compatible migration for old gearsets.
- **Static taxonomy (not backend-enumerated).** Seeded from `docs/STAT_SHORTCUTS.md`, includes weapon-property stats from Phase 10 addendum. Mutual-exclusion block for weapon base damage / weapon damage / base damage dice.
- **Stat sets runtime-loaded.** New `GetStatSets()` RPC checks `./stat_sets.json` override first (re-read on every call, no caching), falls back to embedded default. Additive-by-default conflict resolution: user placement always wins, "Replace instead" one-click override.
- **Hand-rolled Accordion.** shadcn-svelte not viable on this project's Svelte 3; existing toggle pattern generalized. Persisted open/closed state via localStorage per section (except Stat Priorities, always open).
- **Post-solve TierReport.svelte.** Displays tier-score vector, `unmetTier4`, `unmatchedPriorities`, elapsed vs. budgeted time, degradation notes.

**Sections:**
- §1–2: Overview, invariants, dependencies (Phase 10 wire contract + wails regen required first)
- §3–5: Tier-lane UI, stat picker, caster removal
- §6: Stat sets (shape, runtime loading, seed content, conflict resolution)
- §7: Results-side (filigree bias deleted, TierReport.svelte, search-time slider update)
- §8–9: Accordion component, form layout (7 sections, always-visible actions)

**Dependency on Phase 10:** Critical. Cannot start until Phase 10's Go changes land (MaxSearchTime/Mode on OptimizationPayload, new StatPriorityEntry shape) and wails-generated models.ts is regenerated.

---

## Architectural Decisions Made

### 1. Sequential Lexicographic Solve (not big-M single-solve)

**Decision:** Build model once, solve tier 1 → lock value → solve tier 1+2 → lock both → continue.

**Rationale:** GLPK double-precision + file-based invocation introduces compounding numerical risk when all five tier goals enter the objective simultaneously with 10^20-scale big-M constants. Sequential locks keep each stage's arithmetic in `[0, 1]` to `[0, 3]` bounds (tier-4 breadth term tops out at 2.0). Graceful degradation: if a stage times out with no incumbent, fold its goal into the next stage with `M_FOLD = 4.0` (safe, not giant).

**Impact:** Implementation must carefully handle snapshot/restore on failed stages and ensure lock constraints are never over-relaxed per decision 3 (strict zero slack).

### 2. Upper-Bound Normalization for Intra-Tier Weights

**Decision:** Weight each stat within a tier by `achieved / max_achievable`, not raw magnitude.

**Rationale:** Raw-magnitude weighting makes weapon-base stats (crit multiplier 1–5, threat range 0–6, [W] ≈1–6.4) effectively invisible when they share a tier with conventional stats (Ranged Power ~200, Spellpower in the hundreds). UB-normalization makes this feature actually functional.

**Coupled with weapon-stats addendum:** This became load-bearing — weapon stats are only usable if this decision holds.

### 3. Strict Zero Slack on Tier Locks

**Decision:** `G_t ≥ V_t − tol_t` where `tol_t = max(1e-5, abs(V_t)·1e-6)` (float hygiene only).

**Rationale:** No user-facing `tier_slack` knob in Phase 10. Numeric tolerance is tight enough to never flip a tier-4 breadth-indicator (`present_s`, worth 2.0) and small enough to be ~0.001% relative to tier-1 goals.

**Consequence:** A future user knob (out of scope) would need a full respec pass (locking becomes a recommendation, not a hard constraint).

### 4. Target-Slot-Only Alternatives

**Decision:** `GetSlotAlternatives` re-scores only the target slot; every other slot is hard-locked to `EquippedItems`.

**Rationale:** Tractability (enumeration-based scoring, no ILP per candidate) + correctness (don't accidentally suggest a gearset worse at other slots just to eke out +1 of the target stat). Doesn't preclude alternatives-across-whole-gearset as a future, separate feature.

### 5. Go Does Display Parsing, Python Does Matching

**Decision:** Go mirrors XML structurally (every field, every buff, even ones the solver ignores). Python's `normalize_stat_name` stays single-sourced and is never ported.

**Rationale:** Two different output goals: Python filters and matches to user priorities; Go shows what the XML says. Porting the matcher would create a second source of truth that drifts. The ~25% of buffs invisible to the solver are correctly invisible because Python requires both value *and* bonus-type to emit; Go shows them in a distinct "not used by optimizer" group.

### 6. Caster Checkbox Grid Removed Entirely

**Decision:** No checkbox UI. Caster schools/spellpowers become just another branch of the stat picker.

**Rationale:** These fields are never read by the backend (confirmed by inspection). Removing the UI removes the entire mechanism with zero backend risk. Old gearsets migrate on load (one-time, tier-1 placement).

**Consequence:** The existing bug (unchecking a school doesn't remove its priority) is structurally impossible to reintroduce — no more standing reactive sync between two representations.

### 7. Stat Sets: Runtime-Loaded, Hand-Editable, Not Backend-Enumerated

**Decision:** New `GetStatSets()` RPC checks `./stat_sets.json` first (re-read on every call), falls back to embedded default. Not a `public/` asset (which would be baked into the Wails binary at build time).

**Rationale:** User requirement: "hand-edited but loaded at runtime." The `expansions.json` precedent (`frontend/public/*` copied to `frontend/dist/` at build time) doesn't satisfy that — it'd be embedded forever. New RPC + override file pattern matches the precedent already set by the bundled solver binary (`//go:embed`).

### 8. Static Taxonomy, Not Backend-Enumerated Stat Names

**Decision:** `frontend/src/lib/data/statTaxonomy.ts` is a hand-authored, type-checked tree seeded from `docs/STAT_SHORTCUTS.md`. Not fetched from a new backend endpoint.

**Rationale:** Backend enumeration of raw XML `<Type>` values would return thousands of strings (`Combustion`, `MagicalEfficiency`, `Chilling 3`) that are accurate about the XML but not in `normalize_stat_name`'s input vocabulary — an "always accurate but always useless" tradeoff. Post-solve `unmatchedPriorities` (Phase 10 §9) provides the real feedback loop: warn the user when a chip doesn't match.

### 9. Weapon-Base Stats Scoped to Weapon1 Only

**Decision:** `weapon damage`, `base damage dice`, `critical multiplier`, `critical threat range` sources are only built from `x[(i, 'Weapon1')]`, never `Weapon2`.

**Rationale:** Deliberate simplification for TWF (off-hand assumed to duplicate main-hand type) and automatic correctness for THF (Weapon2 unused). Resolves the correctness bug where an unqualified "crit multiplier" bucket would combine both hands and resolve to a silent max-of-both, misrepresenting actual game mechanics.

---

## Key Design Constraints & Tradeoffs

### Constraint: Phase 10 Must Land First

Frontend specs are gated on Phase 10's Go changes (MaxSearchTime/Mode fields, new StatPriorityEntry tier shape) and a wails-module regeneration. This is not a soft dependency — TS types won't type-check against the old flat wire shape.

### Tradeoff: Filigree Bias Deleted, TierReport Replaces It

Old `computeFiligreeBias()` was a JS mirror of the now-deleted Python `compute_priority_bias` heuristic. Phase 10 kills both: filigrees are ordinary sources in tier 1. The frontend now reports the solver's own factual tier scores + `unmetTier4` / `unmatchedPriorities` instead of re-computing a heuristic that drifts.

### Constraint: Raid Detection Out of Scope

`data/PackMappings.json` exists and is wired; the raids data file (`raidsPath` in `InitEnrichment`) does not exist in the repo. Rather than invent one, Item Detail spec gates raid detection off and surfaces an honest "not available in this version" note.

### Tradeoff: No In-App Stat-Set Authoring

Stat sets are runtime-loaded from hand-edited `stat_sets.json`. No create/edit/save UI in this phase. Future work can add a localStorage overlay or Go-backed write RPC; for now, the user edits the file by hand in a text editor.

---

## User Decisions Confirmed

| Decision | Options Presented | User Choice | Reasoning |
|---|---|---|---|
| **Stat sets persistence** | JSON file only (embed default) vs. localStorage+Go RPC | JSON file only (Wails embedded default + override on disk) | Simplest path; matches existing solver binary precedent |
| **Caster checkbox grid** | Keep as shortcut vs. Remove entirely | Remove entirely | Backend never reads these fields; no risk to removal |
| **Weapon combat stats** | Display-only vs. Make optimizable | Make optimizable | Want them in solver priorities now, not as future work |
| **Weapon stats scope** | Sum both hands vs. Main-hand only | Main-hand only (TWF assumption) | Simpler model, correct for THF, safe default for TWF |
| **Tier-4 baselines (weapons)** | Proposed (x3 crit, width-2 threat, [W]>1.0) vs. Custom | Proposed | Tuned from actual item corpus (1,228 items at [W]=1.0 mundane floor) |
| **Categoricals (DR bypass, material, weapon type)** | Include as priorities vs. Exclude | Exclude from Phase 10 | Don't fit numeric-maximization model; need separate set-membership filtering, deferred |
| **Spec split** | One combined spec vs. Two specs (Ask1 independent, Ask2+3 combined) | Two specs | Item Detail independent; form restructure can't start until Phase 10 lands |
| **Empty-slot preference** | Implicit/emergent vs. Explicit invariant | Explicit INV-7 | Make structural: slots `≤ 1`, consolidation empties non-load-bearing, snap/restore, corner cases documented |

---

## Open Questions Resolved

### Q: Should weapon-base stats be single-stat or multi-stat properties?

**User input:** Single-stat per property. `weapon base damage` is the composite recommended; `weapon damage` and `base damage dice` are advanced components. Mutual-exclusion block prevents double-counting.

### Q: Do weapon-base stats require new solver machinery?

**Resolution:** No. They fit existing non-stacking-source machinery (one per slot, max-of-one per bonus type). Slot-qualified bonus type (`WeaponBase:Weapon1` etc.) + existing source loop handles them cleanly.

### Q: Can empty slots happen, and how do we prevent unintended emptying?

**Resolution:** Yes, structurally allowed. Consolidation stage empties non-load-bearing items after all tier locks are satisfied. Prevented unintended emptying via strict locks + float-hygiene tolerance + snapshot/restore on failed stages.

---

## What's NOT in Phase 10 (Deferred)

1. **Frontend wire contract updates.** TS types, `store.ts` refactor, JobConfigurationForm redesign → Phase 10 Frontend Spec, depends on Phase 10 backend.
2. **`computeFiligreeBias` deletion & TierReport.svelte creation.** Documented in Phase 10 §12; implemented as part of frontend spec.
3. **Weapon-stat refinement for optimizer hints.** `weapon base damage` vs. components already decided; future: rune arms, DRBypass categoricals, per-hand weight for independent off-hand prioritization.
4. **Raid detection.** No source data; front-end stub in Item Detail spec notes it's unavailable.
5. **Bonus-type shared source of truth.** Currently duplicated across Python files; naming recorded as future direction (not built).

---

## Implementation Roadmap (No Code Yet)

| Phase | Component | Owner | Dependencies | Acceptance Criteria |
|---|---|---|---|---|
| **10a** | Python `optimizer.py` + `solver.py` | builder agent | none (ready to start) | AC-1–AC-45 in Phase 10 spec + reconciliation LP working |
| **10b** | Go `app.go` + models | builder agent | 10a merged | AC-40–AC-45 (Go build/vet clean, wails module regen successful) |
| **Item Detail** | Go parsing + Svelte component | builder agent | none (independent) | AC-1–AC-26 in Item Detail spec |
| **Frontend** | Form restructure + tier lanes | builder agent | Phase 10b (wire contract), Item Detail (no dep) | AC-1–AC-26 in Frontend spec |
| **Integration** | End-to-end test + demo | tester | all above | Single run: optimize → results in TierReport → alternatives picker live |

---

## Branching & Commits

- **Branch created:** `feature/tiered-priority-solver`
- **Initial plan commit:** `d81ae29` (Phase 10 spec, 1,046 lines)
- **Weapon addendum + Item Detail:** `25bcd8a` (Phase 10 addendum, Item Detail spec)
- **Frontend spec:** `ca05f6b` (1,689 lines total committed planning docs)
- **Current state:** Working tree clean, all three specs authored and committed, ready for builder phase.

---

## How to Reference This Document

- **Architecture decisions:** §1–9 (each explains rationale, tradeoff, and consequence)
- **Constraints & tradeoffs:** §10 (gating dependencies, known out-of-scope work)
- **User choices:** §11 (audit trail of decisions made during planning)
- **What's deferred:** §13 (future work, not Phase 10)
- **Implementation sequence:** §14 (who builds what, in what order)

For implementation details, refer directly to the three spec documents:
- **Backend solver:** [docs/PHASE10_PLAN.md](PHASE10_PLAN.md)
- **Item panel:** [docs/ITEM_DETAIL_SPEC.md](ITEM_DETAIL_SPEC.md)
- **Form & frontend:** [docs/TIERED_SOLVER_FRONTEND_SPEC.md](TIERED_SOLVER_FRONTEND_SPEC.md)

---

## Session Notes

This planning pass involved:

1. **Initial orchestrator briefing** on stat-priority redesign (Phase 10 core).
2. **User decisions on weapon-stat integration** — confirmed weapon-base stats are tier priorities, scoped to Weapon1, with mutual-exclusion block on the composite.
3. **Empty-slot preference clarification** — made explicit as INV-7 with consolidation as enforcement mechanism.
4. **Frontend architectural tradeoffs** — caster grid removal, stat-set runtime loading, tier lanes over dropdowns, static taxonomy.
5. **Item Detail as independent piece** — reusable component, no circuit-breaking dependency on Phase 10 (though both ship together).
6. **Spec authoring** — three implementation-ready documents (PHASE10_PLAN, ITEM_DETAIL_SPEC, TIERED_SOLVER_FRONTEND_SPEC) with 45+ acceptance criteria, 28+ edge cases, fully scoped for builder phase.

No implementation code yet — planning only. Branch is ready for sequential build phases per §14.
