# Technical Specification — Phase 10: Tiered Priority Solver

**Branch:** `feature/tiered-priority-solver`
**Scope:** `app.go`, `python/optimizer.py`, `python/solver.py`, `docs/PHASE9_PLAN.md`
**Explicitly out of scope (deferred follow-up, see §12):** all of `frontend/`

---

## 1. Overview and invariants

The solver moves from a single weighted-sum ILP to a **sequential lexicographic solve** over up to five user-defined priority tiers, followed by a consolidation stage and a reconciliation LP. Tier semantics come from the orchestrator's architecture document; this spec pins the implementation-level details.

### 1.1 Non-negotiable invariants

| ID | Invariant |
|---|---|
| **INV-1** | `z[(stat, b_type)]` remains the **display truth** — built over *all* sources, including filigrees. `realizedStats`, `allEffects`, and `slots` are derived only from `z`, and only from the **reconciliation solution** (§6), never from a tier stage's raw solve. |
| **INV-2** | `priority_names` passed to `parse_sets` / `parse_items` / `parse_augments` / `parse_filigrees` (`python/solver.py:34`, used at L138, 162, 166, 172) **must contain stats from all five tiers**. Dropping tier-5 stats makes matching XML data invisible to `normalize_stat_name` and therefore to the entire model. |
| **INV-3** | A tier's achieved goal value is locked as a hard constraint on the **goal expression `G_t`**, never on `prob.objective`. Locking the objective would also lock penalty/tie-break terms and can render later stages infeasible. |
| **INV-4** | The consolidation penalty `P` and the filigree tie-break `B` are **never** part of any locked expression. |
| **INV-5** | The model is constructed **once**. Stages call `prob.setObjective(...)` and append lock constraints. `create_model()` is never called per stage. |
| **INV-6** | Go struct, Python payload parsing, and TS types must change atomically when a wire contract changes (repo convention, `docs/PHASE9_PLAN.md:117-120`). Go + Python land in this pass; TS is a **knowingly deferred** follow-up documented in §12 — not an oversight. |

### 1.2 Settled decisions (do not re-litigate)

1. Intra-tier weighting normalizes by each stat's **achievable upper bound**, not raw magnitude.
2. Tier-4 "at least 1" threshold = **one credited source** (any single contributing item/augment/filigree/set bonus).
3. Tier locks are **strict, zero user slack**. The only tolerance is float hygiene (§4.4). No `tier_slack` knob.
4. Alternatives are **target-slot only**. Every other slot is hard-locked to the passed-in `EquippedItems`. No `MaxOtherChanges`, no `ChangedSlots`.
5. A stat appearing in more than one tier entry → **reject the payload** with a validation error, checked in `solver.py` before any XML parsing.
6. "Prioritize highest value effects" (tiers 3/4) = **data magnitude**. No extra user-supplied field.
7. A stage that times out with **no incumbent** folds its goal into the next stage's objective (§4.6) rather than failing the run.
8. Caps (`[N]` syntax and the new `cap` field) are valid at **every** tier.
9. The post-solve reconciliation LP (§6) is **in scope** for this pass.
10. Time-budget split `[0.35, 0.25, 0.18, 0.12, 0.10]` with floor + rollover is the **starting allocation** — module-level constants, tunable, not hardcoded inline.

---

## 2. Data model and wire contract

### 2.1 `PriorityEntry` (new, `python/optimizer.py`)

A dataclass, the single in-Python representation of a priority. Replaces the `(stat_name, weight_val)` tuple list threaded through `create_model` / `run_optimization` today.

```
@dataclass(frozen=True)
class PriorityEntry:
    stat:  str          # BASE name, "[N]" already stripped; matches sources[] keys
    tier:  int          # 1..5, validated
    cap:   float | None # None when uncapped
    order: int          # 0-based index WITHIN its tier, from array order
```

`stat` must be the base name because `normalize_stat_name` (`optimizer.py:11-54`) returns `p_base` (L53, `[N]` stripped at L22), and that base name is what keys `sources`.

### 2.2 Go structs (`app.go`)

Replacing L100-103:

```go
// StatPriorityEntry is one user priority. Intra-tier rank comes from array
// order (index of appearance among entries sharing a Tier), not from a number.
type StatPriorityEntry struct {
    Stat  string `json:"stat"`
    Tier  int    `json:"tier"`            // 1..5
    Cap   *int   `json:"cap,omitempty"`   // promoted from the "[N]" suffix hack
    Value int    `json:"value,omitempty"` // LEGACY ONLY: migrated to Tier in solver.py; new code never reads it
}
```

`Cap` is `*int` so that "no cap" and "cap 0" are distinguishable on the wire; `cap: 0` is a validation error (§2.6).

Additions to `OptimizationPayload` (L105-132):

```go
    MaxSearchTime int    `json:"max_search_time"` // total wall-clock budget in seconds, all stages
    Mode          string `json:"mode,omitempty"`  // "optimize" | "calculate" | "alternatives"
```

`MaxSearchTime` is a **prerequisite fix**, not a feature: `frontend/src/lib/store.ts:21` and `JobConfigurationForm.svelte:439` already produce it, but it is absent from `OptimizationPayload` today and therefore silently dropped before Python ever sees it. `run_optimization` has always used its `max_search_time=60` default (`optimizer.py:733`). With up to seven solves per run, wiring this is mandatory.

New alternatives structs (replacing nothing; additive after L148):

```go
type AlternativesPayload struct {
    OptimizationPayload                    // embedded — same data-filtering inputs
    TargetSlot    string            `json:"target_slot"`
    CurrentItem   string            `json:"current_item"`
    EquippedItems map[string]string `json:"equipped_items"`
    Count         int               `json:"count"` // clamped to 3..10
}

type AlternativeItem struct {
    Rank           int                 `json:"rank"`
    ItemName       string              `json:"itemName"`
    Slot           string              `json:"slot"`
    ML             int                 `json:"ml"`
    IsRaid         bool                `json:"isRaid"`
    TierScores     map[string]float64  `json:"tierScores"`     // "1".."5" — AUTHORITATIVE ranking vector
    ObjectiveScore float64             `json:"objectiveScore"` // display convenience ONLY, see §7.6
    StatDeltas     map[string]float64  `json:"statDeltas"`     // vs. baseline, per priority stat
    Augments       []AugmentAssignment `json:"augments"`
    Filigrees      map[string][]string `json:"filigrees"`
}

type AugmentAssignment struct {
    Color string `json:"color"`
    Name  string `json:"name"`
}

type AlternativesResult struct {
    Success            bool               `json:"success"`
    Slot               string             `json:"slot"`
    BaselineTierScores map[string]float64 `json:"baselineTierScores"`
    Alternatives       []AlternativeItem  `json:"alternatives"`
    Warnings           []string           `json:"warnings,omitempty"`
    ErrorMessage       string             `json:"errorMessage,omitempty"`
}
```

`Warnings` is an addition to the orchestrator's sketch, required by edge cases EC-14 and EC-16 (§11).

### 2.3 `stat_priorities` JSON wire shape — new format

```jsonc
"stat_priorities": [
  { "stat": "Ranged Power",  "tier": 1 },
  { "stat": "Doubleshot",    "tier": 1 },
  { "stat": "Melee Power",   "tier": 3, "cap": 50 },
  { "stat": "Constitution",  "tier": 4 },
  { "stat": "Fortification", "tier": 5 }
]
```

Semantics:
- `tier` ∈ 1..5. Required in the new format.
- Entries **may be interleaved** by tier. Intra-tier rank = index of appearance among entries filtered to that tier. In the example, `Ranged Power` is rank 0 of tier 1 and `Doubleshot` is rank 1 of tier 1.
- `cap` is optional. When present it wins over any `[N]` suffix in `stat` (log a warning to `out_file` if both are present and disagree).
- A `[N]` suffix in `stat` remains accepted for backward compatibility with saved `.ddogearset` files (parser exists at `optimizer.py:404-407`; the equivalent logic moves to `solver.py`).

### 2.4 Legacy migration (implemented once, in `solver.py`)

| legacy `value` | → `tier` |
|---|---|
| ≥ 100 | 1 |
| 75 – 99 | 2 |
| 50 – 74 | 3 |
| 25 – 49 | 4 |
| < 25 | 5 |

Three input shapes must be accepted:

**Shape A — legacy dict** (oldest saved gearsets, `solver.py:30-31`):
```json
"stat_priorities": { "Constitution": 100, "Charisma": 90, "Melee Power[50]": 85, "Doublestrike": 70 }
```
→ migrates to
```json
[ {"stat":"Constitution","tier":1,"order":0},
  {"stat":"Charisma","tier":2,"order":0},
  {"stat":"Melee Power","tier":2,"cap":50,"order":1},
  {"stat":"Doublestrike","tier":2,"order":2} ]
```
Intra-tier order = Python `json` object insertion order (guaranteed since 3.7).

**Shape B — Phase 9 ordered list with `value`:**
```json
"stat_priorities": [
  {"stat":"Ranged Power","value":100},
  {"stat":"Doubleshot","value":100},
  {"stat":"Melee Power[50]","value":60}
]
```
→
```json
[ {"stat":"Ranged Power","tier":1,"order":0},
  {"stat":"Doubleshot","tier":1,"order":1},
  {"stat":"Melee Power","tier":3,"cap":50,"order":0} ]
```

**Shape C — new tiered list** (§2.3), used as-is.

Detection rule, in order: if `dict` → Shape A. Else if any element has a `tier` key → Shape C (elements *without* `tier` in a Shape-C list are a validation error, see §2.6). Else → Shape B.

### 2.5 Mode normalization

`mode` becomes a **payload field**, not a CLI flag (following the `calculate_only` precedent at `solver.py:127`). Normalize in exactly one place:

- `mode` present and in `{"optimize","calculate","alternatives"}` → use it.
- `mode` absent and `calculate_only == true` → `"calculate"`.
- otherwise → `"optimize"`.
- `mode` present but unrecognized → validation failure.

`calculate_only` remains accepted as a legacy field and is never read again after normalization.

### 2.6 Validation (early, in `solver.py`, **before any XML parsing**)

All failures go through the existing `JSON_RESULT:{"success": false, "errorMessage": ...}` channel (`solver.py:189`) followed by `sys.exit(1)`. Every message begins with the literal prefix `Stat priority validation failed: `.

| Condition | Message (must contain the bolded substring) |
|---|---|
| `stat_priorities` empty or missing | `Stat priority validation failed: `**`no stat priorities were provided`**`.` |
| Same normalized stat in two different tiers | `Stat priority validation failed: 'Melee Power' `**`appears in more than one tier`**` (tiers 1 and 3). Each stat may be listed only once.` |
| Same normalized stat twice in the *same* tier | `Stat priority validation failed: 'Melee Power' `**`is listed more than once`**` in tier 3.` |
| `tier` outside 1..5 | `Stat priority validation failed: 'X' has invalid tier 7 (`**`must be 1-5`**`).` |
| Shape-C list element missing `tier` | `Stat priority validation failed: entry 'X' is `**`missing a tier`**`.` |
| `cap` present and ≤ 0, or non-integer | `Stat priority validation failed: 'X' has invalid cap 0 (`**`must be a positive integer`**`).` |
| `mode` unrecognized | `Stat priority validation failed: unknown `**`mode 'foo'`**`.` |

**Normalization key for duplicate detection:** strip `[\d+]`, `.strip()`, then `.casefold()`. So `"Melee Power[50]"`, `"melee power"`, and `" Melee Power "` all collide.

### 2.7 `app.go` failure-relay fix (required)

`app.go:200-203` currently returns `ResultPayload{Success:false, ErrorMessage: err.Error()}` whenever `cmd.Wait()` reports a non-zero exit, **discarding any `JSON_RESULT` already captured**. Since `solver.py` exits 1 on every validation failure, every message in §2.6 would reach the UI as `"exit status 1"`.

**Required behavior in the extracted `runSolver` helper:** if a `JSON_RESULT:` line was captured, return that payload regardless of exit code. Only synthesize an error from `cmd.Wait()` when *no* `JSON_RESULT` was seen.

---

## 3. Model construction

### 3.1 Source provenance (`origin`)

Source tuples grow from 3-tuples to 4-tuples: `(val, var, source_name, origin)` where `origin ∈ {'item','augment','filigree','set'}`.

| `optimizer.py` line | origin |
|---|---|
| L613 | `'item'` |
| L617 | `'augment'` |
| L621, L622 | `'filigree'` |
| L626 | `'set'` |

Consumers to update: the `for val, var, sname in srclist` loops at L638 and L645, and `sources_tracking` unpacking at L896. `sources_tracking` entries also become 4-tuples `(tracked_var, val, sname, origin)`.

### 3.2 `z` — display truth (unchanged construction, L632-656)

Built over **all** sources exactly as today:
- `b_type.lower().strip() in ['stacking','mythic','reaper']` → `z == Σ val·var`
- otherwise → per-source binary `d_var` with `d_var ≤ var`, `Σ d_var ≤ 1`, `z == Σ val·d_var`

Filigree entries stay in `sources`. Removing them would make `realizedStats`/`allEffects` lie about what the character actually has (INV-1).

### 3.3 `z_nofil` — objective input for tiers 2–5

Built only where it can differ from `z`. Materialize `z_nofil[(stat, b_type)]` **iff both**:
1. `stat` belongs to a tier ≥ 2, **and**
2. at least one source in `sources[(stat, b_type)]` has `origin == 'filigree'`.

Otherwise alias `z_nofil[(stat,b_type)] = z[(stat,b_type)]` in the dict and add **no** variables or constraints.

Construction over the non-filigree subset of `srclist`:
- stacking types: `z_nofil == Σ val·var` over `origin != 'filigree'`.
- non-stacking types: a **separate** binary family `d'_var` with `d'_var ≤ var`, `Σ d'_var ≤ 1`, `z_nofil == Σ val·d'_var`. Separate d-vars are required because the max over the non-filigree subset differs from the max over the full set.

Name `d'` vars `dn_{counter}` to keep them trivially distinguishable from the display `d_{counter}` family.

**Multi-buff answer, restated:** a filigree buffing tier-1 Ranged Power *and* tier-3 Doubleshot is selected on the strength of its Ranged Power alone. Its Doubleshot still lands in `z` and is displayed, but does not appear in stage 3's objective, which reads `z_nofil`.

### 3.4 Per-stat upper bounds `UB_s` — exact algorithm

`UB_s` is the maximum total for stat *s* achievable **ignoring competition from other stats but respecting the model's structural capacities.** A naive "sum every stacking source in the pool" bound is unusable as a normalizer: a stat with 200 stacking sources would get `ẑ/UB ≈ 0.01` while a purely non-stacking stat gets `≈ 1.0`, which is exactly the scale distortion the UB-normalization decision exists to remove.

Compute once per stat, per variant (`include_filigrees ∈ {True, False}`), **before solving**, from `sources` plus the parsed `items` / `filigrees` lists. It is used for both the tier-4 big-M and the §3.5 normalization.

For each stat *s*, `UB_s = Σ over b_type of ub(s, b_type)`:

**Non-stacking `b_type`** (anything not in `['stacking','mythic','reaper']`):
```
ub = max(val) over eligible sources of (s, b_type)     # exact: Σ d_var ≤ 1
```

**Stacking / Mythic / Reaper `b_type`** — sum of four capacity-respecting family bounds:

| Family | Bound | Justification (line ref) |
|---|---|---|
| `origin == 'item'` | For each slot in `required_slots`, take `max(val)` over item-sources of `(s,b_type)` whose `x` key is `(i, slot)`. Sum over slots. | ≤ 1 item per slot, L516 |
| `origin == 'augment'` | Per distinct augment index `a`, take the max `val` it contributes to `(s,b_type)`. Sum the top `AUG_SLOT_BUDGET` of those. | each augment usable once, L551-552 |
| `origin == 'filigree'` | Per distinct filigree `base_name`, take the max `val`. Sum the top **10** (weapon, `Σ fw ≤ 10`, L572) **plus** the top **5** (artifact, max artifact filigree slots, L580-599). | L565-570 dedupe by `base_name`; L572; L588 |
| `origin == 'set'` | Sum `val` over **all** `(k, m)` sources. | Multiple `m`-tiers of one set are legitimately simultaneously active (`m·w ≤ pieces`, L607) |

`AUG_SLOT_BUDGET` is computed structurally, not guessed: for each slot in `required_slots`, take `max(len(item['augments']))` over items placeable in that slot; sum across slots. Augment-color compatibility is deliberately ignored — ignoring it only loosens the bound, which is safe.

**Filigree exclusion:** the `nofil` variant drops the `origin == 'filigree'` family from the stacking bound, and excludes filigree sources from the non-stacking `max`.

**Cap interaction:**
```
if s has a cap:  UB_s := min(UB_s, cap)
```
This gives the correct semantic: normalized attainment reaches 1.0 exactly when the user's cap is satisfied, and the objective stops rewarding over-cap progress. This is what supersedes `capped_var` (§3.5).

**Floor:** `UB_s := max(UB_s, 1e-6)`. If `UB_s` computes to 0 because *s* has no sources at all, the stat is excluded entirely (edge case EC-4, §11).

### 3.5 Normalized attainment `n_s` — supersedes `capped_var`

For each priority stat *s* that has at least one source, create **one** continuous variable:

```
n_s  ∈ [0.0, 1.0]                       (LpVariable, lowBound=0, upBound=1)
Z_s  = Σ_{b_type} z[(s,b_type)]         if tier(s) == 1
     = Σ_{b_type} z_nofil[(s,b_type)]   if tier(s) ≥ 2
constraint:  UB_s · n_s  ≤  Z_s         (written multiplied out — never divide in the LP)
```

Because every goal expression has a positive coefficient on `n_s`, the solver drives `n_s = min(1, Z_s / UB_s)`.

**This replaces the `capped_var` mechanism at `optimizer.py:664-667` entirely.** `n_s ≤ 1` combined with `UB_s = min(raw_UB, cap)` reproduces the cap behavior exactly (the objective saturates once `Z_s ≥ cap`) and additionally makes `n_s ∈ [0,1]` a *provable* range — which is what makes the tier-4 big-M safe (§3.7). Delete `capped_var`. `z` itself stays uncapped: display truth reports what the character actually has, even above a cap.

Build only the variant a stat's tier actually reads. Never build both variants for the same stat.

### 3.6 Intra-tier weights — `compute_tier_weights`

Replaces `compute_priority_bias` (`optimizer.py:363-389`) wholesale. The `value >= 100` gate (L375-382) and the `< 100` prorate branch (L383-389) both **disappear**: the gate *becomes* tier 1 via the §2.4 migration, and intra-tier rank now comes from array order rather than from a magnitude the user has to invent.

Within each tier, over that tier's entries in ascending `order`:

```
raw_i  = max(0.6 * 0.4**i, WEIGHT_FLOOR)     WEIGHT_FLOOR = 1e-4
w_s    = raw_i / Σ raw                       →  Σ_{s ∈ tier} w_s == 1.0
```

`WEIGHT_FLOOR` matters: `0.6·0.4^i` reaches ~1.6e-4 at i=8 and ~1e-9 at i=13, at which point the tail of a long tier becomes numerically indistinguishable from zero and the solver would leave those stats unmaximized. The floor keeps every listed stat's weight distinguishable from float noise while preserving strict decay for the first ~8 entries.

Every tier normalizes independently, so **`G_t ∈ [0, 1]` for t ∈ {1,2,3,5}** — a stable, bounded numeric range that makes the absolute penalty constants in §3.9 meaningful.

### 3.7 Goal expressions `G_t`

**Tiers 1, 2, 3, 5** — plain weighted normalized magnitude:
```
G_t = Σ_{s ∈ tier t} w_s · n_s              ∈ [0, 1]
```
Tier 3's "maximize when possible but only if nothing higher is sacrificed" and tier 5's "only when convenient" need **no special modeling** — the sequential lock structure supplies both conditional clauses for free.

**Tier 4** — breadth before magnitude. For each tier-4 stat *s*, one binary `present_s`:

```
present_s  ∈ {0,1}
constraint:  present_s  ≤  Σ  contributing_indicators(s)
```

where `contributing_indicators(s)` is, over all `b_type` of *s*, filtered to sources with `val > 0`:

| bonus type | indicator |
|---|---|
| non-stacking | the source's display `d_var` (d=1 ⟺ that source is the credited one) |
| stacking / mythic / reaper | the source's own `var` (`x`, `y`, `fw`, `fm`, or `w_var`) |

Use the **display** `d_var` family, not `d'`, so that "at least one credited source" means at least one source that genuinely contributes to the character — including a filigree. Sources with `val <= 0` are excluded because `var == 1` there would not represent an actual contribution.

**Only the `≤` direction is enforced.** The reverse (`present_s ≥ indicator`) would cost one constraint per source for no benefit: stage 4 maximizes `M₄ · Σ present_s`, so the solver sets `present_s = 1` wherever it is legal. Consequence to document in code: `present_s` is an *objective-side breadth indicator*, and after stages where tier 4 is not in the objective its value is only whatever the lock constraint forces.

```
G_4 = M_4 · Σ_{s ∈ tier 4} present_s  +  Σ_{s ∈ tier 4} w_s · n_s
M_4 = 1.0 + Σ_{s ∈ tier 4} w_s  =  2.0        (weights sum to 1 by construction)
```

`M₄ = 2.0` is **provably** safe, not a guess: the magnitude term is bounded by `Σ w_s · 1 = 1` because `n_s` carries an explicit `upBound=1.0`. So one additional included stat (`+2.0`) always outweighs the entire magnitude term (`≤ 1.0`). No compounding across tier boundaries, no 10²⁰ multipliers, no GLPK tolerance hazard. `G_4 ∈ [0, 2·|tier4| + 1]`.

The "unless higher tiers are sacrificed" clause is enforced *entirely* by the tiers 1–3 lock constraints: if a tier-4 stat is only reachable by giving up tier-1 value, the lock makes that solution infeasible and `present_s` stays 0. The rule falls out of the architecture.

### 3.8 Filigree tie-break `B` — replacing `FILIGREE_BIAS_SCALE`

**Delete the entire L671-689 block**, including the 1000× `FILIGREE_BIAS_SCALE`. Under the new design filigrees are already first-class sources in `sources` (L619-622), so stage 1's objective values their contributions correctly and directly through `z`. Keeping the bias term would **double-count** every filigree's tier-1 contribution — once through `z`, once through the bias.

Replace with a tiny normalized tie-break, present **only in the consolidation stage** (§5), after every `G_t` is hard-locked:

```
score_i   = Σ_{(stat, b_type, val) ∈ filigree_i.buffs}  w_stat · (val / UB_stat)
            summed across ALL tiers, 0 for stats not in any tier
score_i  := score_i / max_j(score_j)         # normalize to [0,1]; skip B entirely if max == 0
B         = Σ_i score_i · (fw_i + fm_i)      # ∈ [0, 15]
```

Because `B` runs only after every tier goal is locked, it can only fill otherwise-free filigree slots and can never distort a tier goal. `B` is never part of a locked expression (INV-4).

### 3.9 Consolidation penalty `P`

```
P       = λ_item · P_item  +  λ_dup · P_dup
P_item  = Σ over all x vars                              # keeps the L691-695 intent
P_dup   = Σ over eligible non-stacking sources of (var − d_var)
```

**`(var − d_var)` is exactly 1 when that source is equipped but contributes nothing**, and 0 otherwise — a precise, linear "wasted stat instance" indicator requiring **zero new variables**, reusing the `d_var` machinery already at L642-656.

Two mandatory restrictions:

1. **Non-stacking bonus types only.** For stacking / Mythic / Reaper types (L636) every equipped source legitimately adds to the total; penalizing multiplicity there directly fights the maximization the user asked for. Correctness requirement, not a preference.
2. **`origin ∈ {'item','augment','filigree'}` only — never `'set'`.** A set-bonus `w_var` costs no slot; it is bounded only from above by `m·w ≤ pieces` (L607) and is free to sit at 0. Including it in `P_dup` would let the consolidation stage suppress a harmless-but-real set bonus, permanently destroying displayed stats (the reconciliation LP runs *after* consolidation). The `origin` tag added in §3.1 makes this filter trivial.

The orchestrator's per-stat `ρ_s` weight is dropped: every source in `sources` already belongs to a user-listed priority stat (they only exist because `normalize_stat_name` matched), so `ρ_s ≡ 1` for all of them. Document the simplification in a comment.

**Known false positive, flagged not hidden:** an item equipped for stat X that incidentally carries a redundant Enhancement bonus to stat Y is charged for the duplicate even though nothing wasteful happened. Accept it; the linear form is cheap and the alternative (`useful_i` binary per item) is not worth the model growth. Note it in a comment above `P_dup`.

### 3.10 Penalty constants — concrete values and reasoning

`P` appears in **two distinct roles** at two different magnitudes. This is what resolves the orchestrator's open "how aggressive can penalties be" question.

**Role A — tie-break inside tier stages.** Penalties still compete against the *current* stage's goal (locks only protect *already-solved* tiers), so here they must stay strictly below the smallest meaningful goal difference.

```
LAMBDA_ITEM_TIE = 1e-6
LAMBDA_DUP_TIE  = 1e-7
```
Worst case: `Σ x ≤ 14` and `Σ(var−d)` realistically ≤ ~100, giving a maximum tie-penalty of `14e-6 + 100e-7 ≈ 2.4e-5`. A meaningful goal step for even the weakest stat in a 3-stat tier (`w ≈ 0.103`, `Δn ≈ 0.05`) is `≈ 5e-3` — two orders of magnitude above the penalty ceiling. Safe.

**Role B — the dedicated consolidation stage (§5), where `P` is the objective.** Every `G_t` is locked, so aggressiveness is structurally free: the stage can only shed items and redundant sources whose removal costs no locked tier value. This is where consolidation actually happens.

```
LAMBDA_ITEM = 1.0
LAMBDA_DUP  = 0.1
EPS_FIL     = 1e-3
```

Relative ordering and why:
- `λ_item (1.0) ≫ λ_dup (0.1)` — dropping an entire equipped item is worth roughly ten redundant stat instances. Removing an item usually eliminates several duplicates anyway; this ordering makes the solver prefer the structural win.
- `λ_dup (0.1) ≫ ε_fil · max(B) = 1e-3 · 15 = 0.015` — the filigree tie-break must never buy its way past a real duplicate reduction. `B`'s per-filigree score is normalized to `[0,1]` in §3.8 precisely so this bound is computable.

All five constants are module-level named constants in `optimizer.py`, not inline literals.

---

## 4. The tiered solve driver

### 4.1 Stage list

`T` = ascending list of tiers that actually contain at least one *usable* stat (a stat with ≥1 source; see EC-4). A user with only tiers 1 and 3 gets **2** stages. Empty tiers produce no stage.

### 4.2 Stage objective

Stage *k* over tier `t_k`:
```
maximize   G_{t_k}  −  (LAMBDA_ITEM_TIE · P_item + LAMBDA_DUP_TIE · P_dup)
subject to all structural constraints from create_model()
       and G_{t_j} ≥ V_j − tol_j    for every previously solved j < k
```
After the solve, record `V_k = value(G_{t_k})` (recomputed in Python from variable values, **not** read from `prob.objective`) and append the lock constraint with a stable name `tier_lock_{t_k}`.

### 4.3 Model reuse

Build the PuLP problem **once** via `create_model()`. Per stage: `prob.setObjective(expr)` then `prob += (lock_expr, name)`. Model construction is heavy — thousands of binaries, one `d_var` per non-stacking source (L646) — and rebuilding it five to seven times is pure waste (INV-5).

Be clear-eyed in a code comment about the limit: `pulp.GLPK_CMD` is file-based and writes a fresh LP on every `solve()`, so this saves **construction** time only. There is **no warm start** across stages. If solve time turns out to dominate, the known next lever is `PULP_CBC_CMD`, which supports `warmStart` — out of scope, but record it.

### 4.4 Lock tolerance (float hygiene only)

```
tol_k = max(1e-5, abs(V_k) * 1e-6)
```

This is **not** the `tier_slack` knob (out of scope per decision 3). `G_t` is a sum of float-coefficient terms over continuous `z` variables that GLPK solves to a default primal tolerance around 1e-7; an exact equality lock will occasionally go infeasible from last-bit rounding. `1e-5` absolute against `G_t ∈ [0,1]` is negligible in outcome terms and cannot flip a tier-4 `present_s` (which is worth `M₄ = 2.0`).

### 4.5 Time budget — one total, shared, with rollover

`max_search_time` is the **total wall clock across all stages**, not a per-solve limit. Five independent 60s budgets would turn a 60s job into a 5-minute one.

```
T_total = clamp(max_search_time or 60, 10, 1800)
T_cons  = clamp(0.15 * T_total, 5, 30)          # consolidation stage reserve, carved off first
T_tiers = T_total - T_cons

SHARES  = [0.35, 0.25, 0.18, 0.12, 0.10]        # module constant, tunable
shares_k = SHARES[position of t_k in T] renormalized over the populated stages to sum to 1

if T_tiers < 5.0 * len(T):
    budget_k = T_tiers / len(T)                 # degenerate low-budget case: even split, no floor
else:
    budget_k = max(5.0, shares_k * T_tiers)     # 5s per-stage floor

rollover: before stage k,  budget_k += carry
          after stage k,   carry = max(0, budget_k - elapsed_k)
after the last tier stage:  T_cons += carry
reconciliation LP:          fixed 15s tmlim, NOT drawn from the budget (it is a pure LP)
```

GLPK's `--tmlim` takes integer seconds: pass `int(max(1, round(budget)))`.

The `SHARES` list is a module constant with a comment marking it tunable — the front-loading reflects that early tiers dominate the search space, but nothing depends on these exact values.

### 4.6 Status handling and graceful degradation (required, not optional)

The current code treats `prob.status != 1` as total failure (`optimizer.py:759`, and the `break` at L728-729). With five to seven chances to time out, that is far too brittle.

PuLP's mapping of a `--tmlim`-truncated GLPK run to `LpStatus` **varies by version**. Do not trust `status == 1`. Implement an explicit incumbent test:

```
_has_incumbent(prob) -> bool
    True iff every LpVariable in prob.variables() has varValue is not None
```

Decision table per stage:

| Situation | Action |
|---|---|
| `status == LpStatusOptimal` | proven optimum. Record `V_k`, append lock, snapshot, continue. |
| `status == LpStatusInfeasible` **and** k == 0 | genuine failure. Return the existing error payload (`solver.py:189`). |
| `status == LpStatusInfeasible` **and** k > 0 | should be impossible (the previous solution remains feasible). Log loudly to `out_file` and to `tierReport.notes`, restore the last-good snapshot, **skip all remaining tier stages**, proceed to consolidation + reconciliation, set `degraded: true`. |
| otherwise **and** `_has_incumbent(prob)` | time-limited feasible. `V_k` is by definition *achievable*, so `G_t ≥ V_k` is feasible — locking on an incumbent costs optimality, never feasibility. Record, lock, snapshot, continue, mark the stage `proven: false`. |
| otherwise **and not** `_has_incumbent(prob)` | no incumbent. **Do not lock.** Fold `G_{t_k}` into the next stage's objective (below). If this was the *last* stage and no snapshot exists at all → genuine failure. |

**Additional guard:** after recording `V_k`, recompute every previously locked `G_{t_j}` in Python and assert `≥ V_j − tol_j`. On violation (a GLPK tolerance artifact), log it, restore the last-good snapshot, and treat the stage as "no incumbent."

**Folding formula.** Let `pending` = the ascending list of tiers not yet locked, including the current one. The stage objective becomes:

```
maximize  Σ_{j ∈ pending}  M_FOLD ** (len(pending) - index_of(j) - 1) · G_{t_j}   −   tie-break penalty
M_FOLD = 4.0
```

`M_FOLD = 4.0` strictly exceeds the max value of any single lower goal (`G_4 ≤ 2·|tier4| + 1`, others ≤ 1) for the realistic tier sizes here, so the fold preserves tier priority. Even a full 5-tier fold peaks at `4^4 · 3 = 768` — nowhere near a precision hazard, unlike the 10²⁰–10²⁴ that a global big-M across five tiers would require. When a folded stage finally succeeds, lock **all** tiers in `pending` at their achieved values and clear `pending`.

**Snapshotting.** `prob.solve()` overwrites `varValue` on every variable, so a failed stage destroys the previous solution. Implement:
```
_snapshot(prob) -> dict[str, float]      # var.name -> varValue
_restore(prob, snap) -> None             # writes varValue back
```
Snapshot after every successful stage. Restore before continuing past any stage that produced no usable incumbent.

---

## 5. Consolidation stage

Runs once, after the last tier stage, with every `G_t` locked:

```
maximize  −(LAMBDA_ITEM · P_item + LAMBDA_DUP · P_dup)  +  EPS_FIL · B
subject to all structural constraints + all tier_lock_* constraints
tmlim = T_cons (including rollover)
```

If this stage produces no incumbent, restore the last-good snapshot and proceed — consolidation is a quality improvement, never a correctness requirement.

**Note for the builder:** `w_vars` are *not* in this stage's objective, so GLPK may return them at arbitrary feasible values (including 0). This is deliberately harmless because §6 recomputes them deterministically before anything is displayed. Add a comment saying so — otherwise it looks like a bug.

---

## 6. Post-solve reconciliation (mandatory)

**Problem being fixed.** At L642-656 the only pressure pushing a non-stacking `d_var` to 1 is the objective. Any stat with a zero objective coefficient leaves its `z` at 0, so `realizedStats` (L817-829) and `allEffects` (L889-903) **under-report it**. This is latent today; it becomes acute in *every* intermediate stage where only one tier is in the objective, and in the consolidation stage where no goal is in the objective at all.

**Procedure**, run once after the consolidation stage:

1. **Fix the structural binaries** to their final solved values by clamping bounds (`v.lowBound = v.upBound = round(v.varValue)`): all `x`, all `y`, all `fw`, all `fm`, all `present_s`, and all `d'` (nofil) vars.
2. **Recompute every `w_vars[(k,m)]` deterministically in Python** from the now-fixed `x`/`fw`/`fm`: `pieces(k) = Σ x[(i,s)] for items carrying set k + Σ (fw_i + fm_i) for filigrees in set k` (mirroring L601-604), then fix `w_vars[(k,m)] = 1 if pieces(k) >= m else 0`. This is exact game truth and eliminates the LP's freedom to leave `w` fractional or zero.
3. **Leave free:** all display `d` vars, all `z`, all `z_nofil`, all `n_s`.
4. **Objective:** `maximize Σ z[(stat, b_type)]` over **every `z` variable in the model**.
5. **Keep all `tier_lock_*` constraints in place.** Feasibility is guaranteed: every lock is a `≥` on an expression non-decreasing in `z`, and step 4 can only raise `z`.
6. Solve with a 15s `tmlim`. All binaries are fixed, so this is a pure LP over `z`/`d` and is near-instant.
7. **Extract the entire L763-913 output structure from this solution**, not from any tier stage's raw solve (INV-1).

**Scope of "every `z` variable" — confirmed.** `z` is only built for `(stat, b_type)` pairs that appear in `sources`, and `sources` is populated exclusively from buffs that `normalize_stat_name(..., priority_names)` matched against the user's priority list (L161-165, L226-228, L262-264, L316-318, L343-345). Therefore **the set of all `z` vars is already exactly the set of priority stats' `z` vars** — no additional filtering is needed, and no non-priority stat has a `z` var to worry about. Use `Σ` over all of `z.values()`.

`z_nofil` is excluded from the objective; its `d'` vars are fixed in step 1 so it is fully determined and cannot drift.

**Correctness note:** maximizing `Σ z` with all equipment fixed does not inflate anything — the max-over-non-stacking-sources rule *is* the DDO stacking rule, so the LP optimum is precisely the character's true total.

**`calculate_only` / `mode == "calculate"` shortcut.** In calculate mode all equipment is pinned by construction (L518-523, L554-560, L574-578), so tier goals are irrelevant. **Skip all tier stages and the consolidation stage entirely** and run only the reconciliation LP (with `w_vars` recomputed per step 2). This is both faster and strictly more correct for display than today's path.

---

## 7. Alternatives API

### 7.1 Decision: separate on-demand RPC, cold-callable

`GetSlotAlternatives` is a **separate Go RPC**, not bundled into `RunOptimization`. The existing eager weapon-alternatives call at `optimizer.py:785-791` is **removed**.

**`GetSlotAlternatives` does NOT require a prior `RunOptimization`.** It is cold-callable against an arbitrary `EquippedItems` map — including a gearset the user assembled by hand in the editor that was never solver-optimized. Baseline tier scores are computed directly from whatever `EquippedItems` is passed in. This matches the user's stated inputs ("slot, current item, current gearset, priorities") which mention no prior solve. **This is the decision; implement it this way.**

### 7.2 Go surface

```go
func (a *App) GetSlotAlternatives(payload AlternativesPayload) (AlternativesResult, error)
```

Both `RunOptimization` and `GetSlotAlternatives` route through the extracted helper:

```go
// runSolver marshals payload, writes it to a UNIQUE temp file, invokes the
// bundled solver, and returns the captured JSON_RESULT line's raw JSON.
// Returns the captured payload even on non-zero exit (see §2.7).
func (a *App) runSolver(payload any) (json.RawMessage, error)
```

**Concurrency fix (mandatory).** `app.go:176` writes to a hardcoded `filepath.Join(os.TempDir(), "ddo_payload.json")`. With a second entry point the UI can fire while an optimization is running, two calls race on one file. Replace with `os.CreateTemp("", "ddo_payload_*.json")` and `defer os.Remove(...)`.

`GetSlotAlternatives` sets `payload.Mode = "alternatives"` before marshaling, and clamps `Count` into `[3, 10]` **before** sending.

### 7.3 Tractability — enumeration, not ban-iteration ILP

`solve_for_alternatives` (L699-731) is replaced by `find_slot_alternatives`. The old loop re-ran a full `create_model()` + solve per alternative; with every other slot locked to `EquippedItems` (decision 4), "which item goes in this slot" is a **single decision requiring no ILP at all**.

**Candidate set:** every parsed item whose `slots` includes `target_slot`, passing the existing `parse_items` filters (armor type, weapon style, ML window, pack exclusion, GoMF, minor-artifact slot reservation — all already applied during parsing), **excluding**:
- the item named in `CurrentItem`,
- any item already equipped in a *different* slot per `EquippedItems` (the model forbids one item index in two slots, L525-526).

`Ring_1` / `Ring_2` map to items whose `slots` contains `'Ring'`.

**Scoring:** direct arithmetic against the fixed rest-of-gearset. For each `(stat, b_type)`, sum `val` for stacking/mythic/reaper types and take `max(val)` for non-stacking types — the same arithmetic `calculate_only` mode already performs. Set bonuses are recomputed with the candidate substituted: `pieces(k)` from the resulting item set plus the fixed filigrees, activating tier `m` when `pieces(k) >= m`. Fixed augments and filigrees for the other slots come from the embedded payload's `PreFilledAugments` / `PreFilledFiligrees`.

**Tier stages are never re-run per candidate.** Each candidate is scored as its tier vector `(G₁,…,G₅)` by pure evaluation — the same `w_s` weights and `n_s = min(1, Z_s/UB_s)` normalization as the main solve.

**`UB_s` for alternatives is computed from the full parsed item/augment/filigree pool** — the same `compute_stat_upper_bounds` call the main solve would make — **not** re-derived from just the candidate set. This is what makes `TierScores` comparable to a main-solve `G_t` and comparable across candidates. Confirmed.

### 7.4 Candidate augment assignment — two-phase

Running a per-candidate ILP over hundreds of candidates would cost 30s+ in file-based GLPK invocations alone. Two phases:

- **Phase A (all candidates, instant, no solver):** assign the candidate's augment color slots greedily — iterate the item's color slots in XML order, and for each pick the not-yet-used compatible augment with the highest marginal gain in the collapsed score (§7.6). Score and rank every candidate.
- **Phase B (top `max(15, 3 × Count)` candidates only):** re-assign augments with a tiny per-candidate ILP over **only that item's** augment binaries, `tmlim = 2` seconds, maximizing the collapsed score `Σ_t 10^(5−t) · G_t`. Re-score and re-rank.

The collapsed objective is a **documented approximation confined to intra-item augment choice** — it is not used for the authoritative candidate ranking. The approximation is bounded: with `G_t ∈ [0,1]` (and `≤ 3` for tier 4), the maximum contribution of all tiers below *t* is `≤ 3 · 1.111 · 10^(4−t) = 0.333 · 10^(5−t) < 10^(5−t)`, a factor-3 margin. Note it in a comment.

### 7.5 Ranking

Sort **lexicographically descending on `(G₁, G₂, G₃, G₄, G₅, −P)`**, tie-broken by `ItemName` ascending for run-to-run determinism. `TierScores` is the authoritative data and `Rank` (1-based) is the authoritative order.

`P` here is evaluated arithmetically from the candidate's own contribution: `LAMBDA_ITEM · (1 if the slot is filled else 0) + LAMBDA_DUP · (count of the candidate's non-stacking, non-set buffs that are not the credited source for their stat)`.

Return the top `Count` candidates. **No tolerance cutoff.** This is a deliberate simplification versus the orchestrator's `alt_tolerance` idea; if the unfiltered top-N proves noisy in practice a cutoff can be added later. Record the simplification in `docs/PHASE9_PLAN.md`.

`StatDeltas[stat] = Z_s(candidate) − Z_s(baseline)` computed from the **all-source `z` totals** (display truth), so users see the real stat change including filigree contributions, regardless of tier.

### 7.6 `ObjectiveScore` — display collapse formula

```
ObjectiveScore = Σ_{t = 1..5}  10 ** (5 - t)  ·  G_t
```

i.e. `10000·G₁ + 1000·G₂ + 100·G₃ + 10·G₄ + 1·G₅`. With `G_t ∈ [0,1]` (`≤ 3` for tier 4) this lands in roughly `[0, 11330]`, well inside double precision.

**This value is display sugar only and must be commented as non-authoritative.** It preserves the lexicographic ordering only when the higher-tier gap exceeds `0.333` (§7.4's margin argument); for smaller gaps it can invert. The UI must sort by `Rank` and compare using `TierScores`. `ObjectiveScore` exists so a simple bar chart has one number to draw.

---

## 8. Function signatures

### 8.1 `python/optimizer.py`

**Removed:** `compute_priority_bias(priority_pairs)` (L363-389), `solve_for_alternatives(...)` (L699-731).

```python
@dataclass(frozen=True)
class PriorityEntry:
    stat: str; tier: int; cap: float | None; order: int

@dataclass
class Model:
    """Replaces create_model()'s 8-tuple return; too many members to keep positional."""
    prob:             pulp.LpProblem
    x:                dict[tuple[int, str], pulp.LpVariable]
    y:                dict[tuple[int, int, str], pulp.LpVariable]
    fw:               dict[int, pulp.LpVariable]
    fm:               dict[int, pulp.LpVariable]
    w_vars:           dict[tuple[str, int], pulp.LpVariable]
    z:                dict[tuple[str, str], pulp.LpVariable]
    z_nofil:          dict[tuple[str, str], pulp.LpVariable]   # aliases z where identical
    d_vars:           dict[tuple[str, str], list[tuple[pulp.LpVariable, pulp.LpVariable, float, str]]]
                                                               # (d_var, source_var, val, origin)
    dn_vars:          dict[tuple[str, str], list[tuple[pulp.LpVariable, pulp.LpVariable, float, str]]]
    n:                dict[str, pulp.LpVariable]                # normalized attainment per stat
    present:          dict[str, pulp.LpVariable]                # tier-4 breadth binaries
    goals:            dict[int, pulp.LpAffineExpression]        # tier -> G_t
    penalty_item:     pulp.LpAffineExpression
    penalty_dup:      pulp.LpAffineExpression
    filigree_tiebreak:pulp.LpAffineExpression                   # B, or a zero expression
    sources_tracking: dict[tuple[str, str], list[tuple]]        # now 4-tuples, see §3.1
    upper_bounds:     dict[str, float]
    weights:          dict[int, dict[str, float]]
    unmatched:        list[str]                                 # priority stats with zero sources


def compute_tier_weights(entries: list[PriorityEntry]) -> dict[int, dict[str, float]]:
    """{tier: {stat: weight}}; each tier's weights sum to 1.0. §3.6."""


def compute_stat_upper_bounds(
    sources:          dict[tuple[str, str], list[tuple[float, pulp.LpVariable, str, str]]],
    items:            list[dict],
    required_slots:   list[str],
    caps:             dict[str, float],
    include_filigrees: bool,
) -> dict[str, float]:
    """Per-stat UB. §3.4. Call twice: include_filigrees=True for tier-1 stats,
       False for tier-2+ stats. Returns {} entries omitted for zero-source stats."""


def create_model(
    items, sets, augments, filigrees,
    entries:              list[PriorityEntry],      # was: list[(stat, value)]
    art_slots, required_slots,
    raid_item_limit=None, pre_equipped=None,
    pre_filled_augments=None, pre_filled_filigrees=None,
    calculate_only=False,
) -> Model:


def solve_tiered(
    model:            Model,
    max_search_time:  float,
    out_file,
) -> dict:
    """Runs the tier stages (§4), the consolidation stage (§5), and the
       reconciliation LP (§6). Leaves the final variable values on `model`.
       Returns the tierReport dict described in §9. Returns
       {"failed": True, "reason": ...} when stage 1 is genuinely infeasible."""


def reconcile_solution(model: Model, tmlim: int = 15) -> None:
    """§6. Fixes structural binaries, recomputes w_vars deterministically,
       re-solves maximizing Σz. Mutates variable values in place."""


def find_slot_alternatives(
    items, sets, augments, filigrees,
    entries:         list[PriorityEntry],
    required_slots:  list[str],
    equipped_items:  dict[str, str],
    pre_filled_augments: dict,
    pre_filled_filigrees: dict,
    target_slot:     str,
    current_item:    str,
    count:           int,
    upper_bounds_all:   dict[str, float],
    upper_bounds_nofil: dict[str, float],
    weights:         dict[int, dict[str, float]],
) -> dict:
    """Enumeration-based, target-slot-only. §7. Returns the AlternativesResult
       JSON shape: {success, slot, baselineTierScores, alternatives, warnings}."""


def run_optimization(
    items, sets, augments, filigrees,
    entries:  list[PriorityEntry],
    out_file, cap, art_slots,
    raid_item_limit=None, pre_equipped=None,
    pre_filled_augments=None, pre_filled_filigrees=None,
    mode: str = "optimize",
    max_search_time: float = 60.0,
) -> dict | None:
```

Private helpers in `optimizer.py`: `_has_incumbent(prob) -> bool`, `_snapshot(prob) -> dict[str, float]`, `_restore(prob, snap) -> None`, `_glpk_cmd(tmlim: int) -> pulp.GLPK_CMD`.

`_glpk_cmd` centralizes the solver invocation currently duplicated at L719 and L756. Two pre-existing pieces of tech debt live there — the hardcoded `path="/opt/homebrew/bin/glpsol"` and the CWD-relative `--log solver_progress.log`, both of which will bite the bundled PyInstaller binary and are now hit up to 7× per run instead of once. **Fixing them is not in scope, but centralizing them in one function is** — do not make it worse by adding a sixth copy, and leave a `# TODO(phase-11)` comment naming both.

### 8.2 `python/solver.py`

```python
def parse_stat_priorities(raw) -> tuple[list[PriorityEntry], str | None]:
    """Accepts Shape A / B / C (§2.4). Returns (entries, None) on success or
       ([], error_message) on validation failure. Runs BEFORE any XML parsing."""

def normalize_mode(parsed_data: dict) -> tuple[str, str | None]:
    """(mode, error_message). §2.5."""

def fail(message: str) -> NoReturn:
    """Prints JSON_RESULT:{"success": false, "errorMessage": message}, then exit(1)."""

def run_alternatives(parsed_data, entries, items, sets, augments, filigrees,
                     required_slots, out_file) -> dict:
    """mode == 'alternatives' branch."""

def main() -> None:
```

Changes in `main()`:
- L25-34 → `parse_stat_priorities`, then `priority_names = [e.stat for e in entries]` (**INV-2**: all five tiers).
- L127 → `mode, err = normalize_mode(parsed_data)`.
- New: `max_search_time = parsed_data.get('max_search_time', 60)` — **currently never read at all**.
- L182 → pass `entries`, `mode`, `max_search_time` to `run_optimization`; or dispatch to `run_alternatives` when `mode == "alternatives"`.
- Validation (`parse_stat_priorities` + `normalize_mode`) runs immediately after `parse_payload`, before `parser.parse_quests` at L135.

### 8.3 `app.go`

| Lines | Change |
|---|---|
| 100-103 | `StatPriorityEntry` → `+Tier`, `+Cap *int`, legacy `Value` with `omitempty` |
| 105-132 | `OptimizationPayload` → `+MaxSearchTime`, `+Mode` |
| after 148 | `AlternativesPayload`, `AlternativeItem`, `AugmentAssignment`, `AlternativesResult` |
| 163-213 | Extract `runSolver`; fix hardcoded temp path at L176 → `os.CreateTemp`; fix the failure-relay bug at L200-203 (§2.7) |
| new | `GetSlotAlternatives` |

---

## 9. Solver output additions

`rich_output` (L905-912) gains five fields. All additive; every existing field keeps its current shape and meaning.

```jsonc
"tierReport": {
  "stages": [
    { "tier": 1, "goalValue": 0.8734, "status": "optimal",
      "proven": true, "budgetSeconds": 21.0, "elapsedSeconds": 8.2, "folded": [] },
    { "tier": 3, "goalValue": 0.4102, "status": "time_limited",
      "proven": false, "budgetSeconds": 27.8, "elapsedSeconds": 27.8, "folded": [] }
  ],
  "consolidation": { "status": "optimal", "elapsedSeconds": 3.1,
                     "itemsEquipped": 12, "duplicateSources": 4 },
  "reconciliation": { "status": "optimal", "elapsedSeconds": 0.3 },
  "totalElapsedSeconds": 39.4,
  "degraded": false,
  "notes": []
},
"tierScores":        { "1": 0.8734, "3": 0.4102 },
"priorityTiers":     { "Ranged Power": 1, "Doubleshot": 1, "Melee Power": 3 },
"unmetTier4":        ["Constitution"],
"unmatchedPriorities": ["Typoed Stat"]
```

`realizedStats` keys change from the raw priority string (which could carry a `[N]` suffix, L820) to the **base stat name**. Listed as a deferred frontend item in §12.

---

## 10. Success criteria / acceptance checks

Verifiable by builder and test_builder. Unit tests go in `python/tests/`; the existing `test_phase3_integration.py` is a blueprint-style file and should be left in place.

### Unit — payload parsing and validation

| ID | Check |
|---|---|
| **AC-1** | Shape C (`[{"stat":"Ranged Power","tier":1},{"stat":"Doubleshot","tier":1},{"stat":"Melee Power","tier":3,"cap":50}]`) parses to 3 `PriorityEntry`s with `order` 0, 1, 0 and `cap` `None, None, 50.0`. |
| **AC-2** | Shape B (`value` 100/100/60) migrates to tiers 1/1/3 with `order` 0/1/0. |
| **AC-3** | Shape A dict `{"Constitution":100,"Charisma":90,"Melee Power[50]":85,"Doublestrike":70}` migrates to tiers 1/2/2/2 with tier-2 `order` 0/1/2 and `CAPS["Melee Power"] == 50.0`. |
| **AC-4** | Boundary values 100→1, 99→2, 75→2, 74→3, 50→3, 49→4, 25→4, 24→5, 0→5. |
| **AC-5** | `[{"stat":"Melee Power","tier":1},{"stat":"melee power[50]","tier":3}]` returns an error containing `"appears in more than one tier"` and does **not** raise. |
| **AC-6** | Same stat twice in one tier returns an error containing `"is listed more than once"`. |
| **AC-7** | `tier: 7` → error containing `"must be 1-5"`. `cap: 0` → error containing `"must be a positive integer"`. Empty list → error containing `"no stat priorities"`. |
| **AC-8** | `priority_names` derived from a 5-tier payload contains **all** stats including every tier-5 entry (INV-2 regression guard). |
| **AC-9** | `mode` normalization: `{"calculate_only": true}` → `"calculate"`; `{"mode":"alternatives"}` → `"alternatives"`; neither → `"optimize"`; `{"mode":"foo"}` → error. |

### Unit — weights, bounds, model structure

| ID | Check |
|---|---|
| **AC-10** | `compute_tier_weights` for a 3-stat tier returns weights summing to `1.0 ± 1e-9`, strictly decreasing, ≈ `0.641 / 0.256 / 0.103`. |
| **AC-11** | A 20-stat tier: every weight `> 0` and the tier still sums to 1.0 (`WEIGHT_FLOOR` regression guard). |
| **AC-12** | `compute_stat_upper_bounds` on a fixture where stat S has non-stacking sources of value 10 and 15 in different slots returns `ub == 15` for that bonus type (max, not sum). |
| **AC-13** | Same fixture with `b_type == "Stacking"` and one source per slot across 3 slots returns the **sum**. |
| **AC-14** | With `caps["S"] = 20` and a raw UB of 60, `compute_stat_upper_bounds` returns `20.0`. |
| **AC-15** | `include_filigrees=False` excludes every filigree source; on a filigree-only stat it returns the `1e-6` floor. |
| **AC-16** | `create_model` produces **no** variable whose name starts with `capped_total_` (superseded by `n_s`). |
| **AC-17** | `create_model` produces **no** objective term containing `FILIGREE_BIAS_SCALE`'s 1000× factor; `compute_priority_bias` no longer exists in the module namespace. |
| **AC-18** | `z_nofil[(s,bt)] is z[(s,bt)]` (identity) for every pair with no filigree source or whose stat is tier 1; a distinct variable otherwise. |
| **AC-19** | `model.goals[4]` contains `present_s` terms with coefficient `2.0`, and every `present_s` has exactly one `≤`-direction linking constraint. |
| **AC-20** | `penalty_dup` contains **no** term whose source `origin == 'set'` and **no** term from a stacking/mythic/reaper bonus type. |

### Integration — solve behavior

| ID | Check |
|---|---|
| **AC-21** | **Tier-1-only equivalence.** A payload whose stats are all tier 1 produces one stage; the resulting gearset maximizes the same stats as today's flat-weight solve and every stat in `realizedStats` is `> 0`. (Exact item-for-item equality is *not* required — normalization changes relative weighting — but no stat may regress to 0.) |
| **AC-22** | **Lock monotonicity.** With tiers 1 and 3 populated, `tierScores["1"]` from the final result is `≥ V₁ − 1e-5`, where `V₁` is the value recorded in `tierReport.stages[0].goalValue`. |
| **AC-23** | **Tier-4 breadth.** On a fixture where a tier-4 stat is obtainable without touching tiers 1–3, that stat appears in `realizedStats` with a value `> 0` and is **not** in `unmetTier4`. |
| **AC-24** | **Tier-4 subordination.** On a fixture where the only source of a tier-4 stat would cost tier-1 value, that stat **is** in `unmetTier4` and `tierScores["1"]` is unchanged from the tier-1-only run. |
| **AC-25** | **Reconciliation completeness.** For every stat listed in `priorityTiers` that has at least one equipped source in `slots`, `realizedStats[stat] > 0`. No priority stat with a live source may report 0. This is the direct regression guard for the zero-weight corruption bug. |
| **AC-26** | **Set bonuses survive consolidation.** On a fixture whose optimum activates a set bonus, `activeSets` is non-empty in the final result and each listed set's buffs appear in `allEffects`. |
| **AC-27** | **Budget respected.** With `max_search_time: 30`, total wall clock for `RunOptimization` is `< 60s` (2× headroom for process start and XML parsing, which are outside the budget). `tierReport.totalElapsedSeconds ≤ 30 · 1.2`. |
| **AC-28** | **Degradation.** With `max_search_time: 10` on a large fixture, `RunOptimization` returns `success: true` with a populated `gearSet` (possibly `degraded: true`) — it must **not** return a failure payload. |
| **AC-29** | **Genuine infeasibility.** A payload with contradictory constraints (e.g. an armor restriction no item satisfies plus a required minor-artifact slot) returns `success: false` with a non-empty `errorMessage`. |
| **AC-30** | **Calculate mode.** `mode: "calculate"` with a fully specified `pre_equipped` returns all 14 slots populated and skips every tier stage (`tierReport.stages == []`). Regression guard for the destructive-clear bug (`docs/PHASE9_PLAN.md:106-111`). |
| **AC-31** | **No eager weapon alternatives.** A normal `optimize` run performs no alternatives search: `gearset_output.txt` contains no `[Weapon1 Alternatives]` section and `tierReport.totalElapsedSeconds` reflects only the tier stages. |

### Integration — alternatives

| ID | Check |
|---|---|
| **AC-32** | `GetSlotAlternatives` with `Count: 5` against a known fixture gearset returns exactly 5 items, `Rank` 1..5, in **strictly non-increasing lexicographic `TierScores` order** on `("1","2","3","4","5")`. |
| **AC-33** | `Count: 1` and `Count: 99` are clamped to 3 and 10 respectively. |
| **AC-34** | Every returned `ItemName` differs from `CurrentItem` and from every value in `EquippedItems`. |
| **AC-35** | Every returned item's `slots` (in the parsed pool) includes `TargetSlot`; for `Ring_1`/`Ring_2` it includes `Ring`. |
| **AC-36** | **Cold-callable.** `GetSlotAlternatives` succeeds against a hand-built `EquippedItems` map with no preceding `RunOptimization` in the process, and `BaselineTierScores` is populated. |
| **AC-37** | A `TargetSlot` with zero legal candidates returns `Success: true`, `Alternatives: []`, populated `BaselineTierScores`, and empty `ErrorMessage`. Not an error. |
| **AC-38** | `ObjectiveScore` equals `10000·G₁ + 1000·G₂ + 100·G₃ + 10·G₄ + G₅` to within `1e-6` for every returned item. |
| **AC-39** | `StatDeltas` for a candidate identical to baseline in every stat is all-zero (within `1e-6`). |

### Go / build

| ID | Check |
|---|---|
| **AC-40** | `go build ./...` and `go vet ./...` are clean. |
| **AC-41** | Two concurrent `RunOptimization` calls do not clobber each other's payload file (`os.CreateTemp` regression guard) — assert the two payload paths differ. |
| **AC-42** | A validation failure (AC-5's payload) surfaces to Go as `ResultPayload{Success:false, ErrorMessage: "...appears in more than one tier..."}`, **not** as `"exit status 1"` (§2.7 regression guard). |
| **AC-43** | `max_search_time` set in the payload reaches Python: assert `gearset_output.txt` logs the received value and it matches what was sent. |
| **AC-44** | `python -m py_compile python/*.py` clean; `pytest python/tests/` passes. |
| **AC-45** | `python/dist/solver` rebuilt via PyInstaller after the Python changes; `RunOptimization` against the bundled binary succeeds end to end. |

---

## 11. Edge cases

| ID | Case | Required behavior |
|---|---|---|
| **EC-1** | Sparse tiers (only 1 and 4 populated) | 2 stages. `SHARES` restricted to `[0.35, 0.12]` and renormalized to `[0.745, 0.255]`. |
| **EC-2** | Exactly one priority total, in tier 3 | 1 stage, `w = 1.0`, `G₃ = n_s`. Behaves like a single-stat solve. |
| **EC-3** | All stats in tier 1 | Single stage; see AC-21. |
| **EC-4** | Priority stat with **zero** sources in the parsed pool (typo, or nothing grants it) | No `z` var exists → no `n_s`, no `UB`. Exclude from all goals, from tier-4 `present`, and from weight normalization (so remaining weights still sum to 1). List in `unmatchedPriorities`. If a tier becomes empty as a result, **drop that stage**. If *all* priorities are unmatched → fail with `"None of the listed stat priorities matched any item, augment, filigree, or set bonus in the data files."` |
| **EC-5** | Cap already exceeded by a locked/pre-equipped source | `n_s` pins at 1.0, `w_s` contributes a constant to `G_t`. Harmless. **Not** an error, no warning. |
| **EC-6** | `cap: 0` or negative | Validation error (§2.6). |
| **EC-7** | Structurally unattainable tier-4 stat | `present_s = 0`, listed in `unmetTier4`. Not an error, not a warning-level log. |
| **EC-8** | 5 tiers with `max_search_time: 10` | `T_cons = 5`, `T_tiers = 5 < 5·5` → even split, 1s per stage. Most stages time-limited. Must still return a result (AC-28). |
| **EC-9** | Stage 1 times out with no incumbent | Fold `G₁` into stage 2 with `M_FOLD` weighting (§4.6). If stage 1 is the only stage → genuine failure. |
| **EC-10** | Stage 1 infeasible | Genuine failure; existing error payload at `solver.py:189`. |
| **EC-11** | Any later stage infeasible | Should be impossible. Log loudly to `out_file` **and** `tierReport.notes`, restore the last-good snapshot, skip remaining stages, set `degraded: true`, still return a result. |
| **EC-12** | `mode == "calculate"` | Skip all tier stages and consolidation; run only the reconciliation LP (§6). `tierReport.stages == []`. |
| **EC-13** | `TargetSlot` absent from `EquippedItems` (empty slot) | Valid. Baseline computed with that slot empty; `CurrentItem` may be `""`. |
| **EC-14** | `EquippedItems` names an item not in the parsed pool | Skip it, append `"Equipped item 'X' for slot 'Y' was not found in the data files and was ignored."` to `AlternativesResult.Warnings`. Do not fail. |
| **EC-15** | `Ring_1` / `Ring_2` | Item pool matched on `'Ring' in item['slots']`. The item equipped in the *other* ring slot is excluded from candidates. |
| **EC-16** | Same item name in `EquippedItems` for two slots | Excluded from candidates for both. Append a warning. |
| **EC-17** | `max_level < 34` → `filigrees == []` (`solver.py:170`) | `z_nofil ≡ z` everywhere; tier 1 and tier 2+ read identical totals; `B` is a zero expression. Must not crash or divide by zero. |
| **EC-18** | Tier-2+ stat whose **only** sources are filigrees | `Z_s^nofil ≡ 0`, `n_s = 0`, `UB` at the `1e-6` floor. Not an error. List the stat in `tierReport.notes` as `"'X' (tier N) is only obtainable from filigrees, which tiers 2+ do not consider; it contributes 0 to its tier goal."` |
| **EC-19** | Stat appearing under both stacking and non-stacking bonus types | `UB_s` sums the per-bonus-type bounds. Correct — the two totals genuinely stack. |
| **EC-20** | `max_search_time` absent, 0, or negative | Default to 60, then clamp to `[10, 1800]`. |
| **EC-21** | Tier with more than ~8 stats | `WEIGHT_FLOOR = 1e-4` keeps the tail nonzero (AC-11). |
| **EC-22** | Both `cap` field and `[N]` suffix present and disagreeing | `cap` field wins; log a warning line to `out_file`. |
| **EC-23** | Consolidation stage produces no incumbent | Restore the last-good snapshot and proceed to reconciliation. Consolidation is a quality improvement, never a correctness requirement. |
| **EC-24** | Reconciliation LP fails (should be impossible — it is a pure LP over a feasible point) | Log to `tierReport.notes`, set `degraded: true`, emit output from the pre-reconciliation values. Do **not** fail the run. |

---

## 12. Deferred follow-ups (document, do not implement)

These are **knowingly deferred**, not oversights. Record them in the new Phase 10 section of `docs/PHASE9_PLAN.md`.

1. **`frontend/wailsjs/go/models.ts`** — `StatPriorityEntry` (currently `{stat, value}` at L3-16) needs `tier`/`cap`; `OptimizationPayload` needs `max_search_time` and `mode`; the new `AlternativesPayload`/`AlternativeItem`/`AlternativesResult` classes need generating. Regenerated by `wails generate module`.
2. **`frontend/src/lib/store.ts`** — `statPriorities` shape change; `max_search_time` (L21) now actually reaches the backend.
3. **`JobConfigurationForm.svelte:439`** — the `max_search_time` slider becomes live for the first time. Its label should be updated to say "total across all solve stages," since the semantics changed from per-solve to total.
4. **`JobConfigurationForm.svelte:85-98` — `computeFiligreeBias()` becomes WRONG the moment this lands.** It is a JS mirror of `compute_priority_bias`, which this change deletes, and it drives the "Filigree bias: 60% Ranged Power, 40% Doubleshot" help text. Once filigrees are valued directly through `z` in stage 1, that displayed percentage describes a mechanism that no longer exists. **It must be flagged as knowingly stale in a code comment in this pass** — not left to silently mislead the user — and removed or rewritten in the frontend pass.
5. **`realizedStats` keys** now use base stat names (`"Melee Power"`) rather than the raw priority string (`"Melee Power[50]"`). Any frontend lookup keyed on the raw string needs updating.
6. **A tier UI** — a 1–5 selector per stat plus drag-to-reorder within a tier. The wire format is already designed for it (array order carries intra-tier rank).
7. **`PULP_CBC_CMD` + `warmStart`** — the known next lever if solve time dominates. `GLPK_CMD` is file-based with no warm start across stages.
8. **Pre-existing tech debt now hit up to 7× per run instead of once:** the hardcoded `path="/opt/homebrew/bin/glpsol"` and the CWD-relative `--log solver_progress.log` (both at `optimizer.py:719, 756`). Centralized into `_glpk_cmd()` in this pass but **not fixed**; both will bite the bundled PyInstaller binary.
9. **Alternatives tolerance cutoff** (`alt_tolerance`) — deliberately omitted; the top-`Count` list is unfiltered. Add if it proves noisy.

---

## 13. Files to change — summary

**`python/optimizer.py`**

| Lines | Change |
|---|---|
| 363-389 | Delete `compute_priority_bias`; add `compute_tier_weights`, `compute_stat_upper_bounds`, `PriorityEntry`, `Model` |
| 391 | `create_model` signature → `entries: list[PriorityEntry]`, returns `Model` |
| 398-409 | `WEIGHTS`/`CAPS` construction → consume `PriorityEntry` (tier/cap already parsed upstream) |
| 609-626 | Add `origin` as the 4th element of every source tuple (L613, 617, 621, 622, 626) |
| 632-656 | Update source-tuple consumers (L638, L645); add conditional `z_nofil` + `dn` construction |
| 658-669 | Replace `capped_var`/`objective_terms` with `n_s` variables and per-tier `G_t` expressions |
| 671-689 | **Delete** the `FILIGREE_BIAS_SCALE` block; build `B` as a separate expression instead |
| 691-695 | Replace the inline `-0.001 * Σx` with the `penalty_item` / `penalty_dup` expressions; `create_model` no longer sets an objective at all |
| 699-731 | `solve_for_alternatives` → `find_slot_alternatives` (enumeration, no ILP for item selection) |
| new | `solve_tiered`, `reconcile_solution`, `_has_incumbent`, `_snapshot`, `_restore`, `_glpk_cmd` |
| 733-913 | `run_optimization`: call `solve_tiered` (replaces the single solve at L756); **remove** the eager weapon alternatives at L784-791; update the priorities loop at L819-829; extract all output from the reconciled solution; add the §9 output fields |

**`python/solver.py`**

| Lines | Change |
|---|---|
| 25-34 | → `parse_stat_priorities` (Shapes A/B/C, migration, duplicate/tier/cap validation) |
| 34 | **Keep all five tiers in `priority_names`** (INV-2) |
| 127 | `calculate_only` → `normalize_mode` |
| new | `fail()`, `run_alternatives()`, `mode == "alternatives"` dispatch |
| 182 | Read `max_search_time` (never read today) and pass it plus `mode` and `entries` |

**`app.go`** — per §8.3.

**`docs/PHASE9_PLAN.md`** — new "Phase 10 — Tiered Priority Solver" section per the repo's own convention that contract changes get documented. Go and Python land together; the TS half is a knowingly-deferred follow-up (§12).
---

## 14. Addendum — Empty-slot preference ("if priorities are met, it's OK to leave slots empty; prefer fewer slots")

### 14.1 Confirmation: zero additional modeling required

**Confirmed — this is not a new feature.** The requested behavior is produced by two things the spec already commits to, and the work here is to *name* it as a guarantee and *test* it, not to build it:

1. **Slot occupancy is already optional.** `optimizer.py:516` emits `Σ_i x[(i,slot)] ≤ 1` per slot in `required_slots`. Nothing in this spec touches that line, and nothing in the tiered design needs it changed.
2. **§5's consolidation stage is the active mechanism.** Once every `tier_lock_*` constraint is in place, the stage's objective is `−(LAMBDA_ITEM · P_item + LAMBDA_DUP · P_dup) + EPS_FIL · B`. `P_item = Σ x`, so the solver is directly rewarded, at full strength, for dropping any item whose removal violates no lock. That is "prioritize fewer slots once priorities are met," verbatim.

The reason this can be aggressive rather than a timid tie-breaker is §3.10's structural argument: with every tier goal already hard-locked, a penalty **cannot** trade away tier value, so `LAMBDA_ITEM` does not have to be tuned against a goal it might damage.

### 14.2 INV-7 (new invariant)

> **INV-7 — Slots are never required to be filled.**
> For every slot in `required_slots`, the occupancy constraint is `Σ_i x[(i, slot)] ≤ 1` (`optimizer.py:516`) and **must remain `≤`**. It must not be changed to `== 1`, and no new constraint may require a slot to be occupied. Leaving a slot empty is always a legal solution.
> The **consolidation stage (§5)** is the designated mechanism that actively empties non-load-bearing slots: after all `tier_lock_*` constraints are appended, `LAMBDA_ITEM · Σ x` is minimized at full strength, so any item whose removal violates no lock **will** be removed.
> Builder note: `≤ 1` is not a bug. Do not "fix" it into an equality.

**Two pre-existing carve-outs** — these are correct, intentional, and must be preserved (they are the reason INV-7 is stated as "no slot is *individually* mandatory" rather than "the gearset may always be empty"):

| Carve-out | Line | Why it stays |
|---|---|---|
| `Σ minor_vars == 1` | `optimizer.py:528-533` | If the parsed pool contains any minor artifact, exactly one **must** be equipped. This is a DDO build rule, not a solver preference. Consequence: the minor-artifact-bearing slot can never be emptied by consolidation. |
| `x[(i, slot)] == 1` for `pre_equipped` | `optimizer.py:422-429` | User-pinned items. The user asked for that item in that slot; consolidation must not remove it. |

`calculate_only`'s `Σ x[slot] == 0` for non-required slots (L518-523) pushes in the same direction as INV-7 and does not conflict.

### 14.3 Constants: existing values suffice — no revision needed

**`LAMBDA_ITEM = 1.0` (consolidation role) is sufficient as specified.** In the consolidation stage the objective contains *only* `P` and `B`, so the margins are unambiguous:

| Competing term | Max magnitude | Ordering |
|---|---|---|
| dropping one item | **1.0** gain | — |
| `LAMBDA_DUP · P_dup` | `0.1` per duplicate instance | `1.0 ≫ 0.1` — an emptied slot beats up to 10 duplicate removals |
| `EPS_FIL · B` | `1e-3 · 15 = 0.015` | `1.0 ≫ 0.015` — the filigree tie-break can never buy a slot back |

Dropping an item also usually eliminates several duplicates, so the two penalty terms point the same way; the ordering only decides the rare case where they conflict, and it decides it correctly.

**`LAMBDA_ITEM_TIE = 1e-6` (tier-stage role) also needs no change,** and deliberately so. During tier stages, penalties still compete against the *current* stage's un-locked goal, so making the tie-break stronger would risk trading real stat value for an empty slot — exactly the failure mode the two-role split exists to prevent. Its job is only to stop a tier stage from returning a gratuitously bloated *tie*; genuine emptying is consolidation's job and happens later in the same run. `2.4e-5` worst-case tie penalty against a `~5e-3` smallest meaningful goal step is the correct margin.

**One consequence to state plainly rather than leave implicit:** an item contributing a *measurable* amount to any locked tier — even a tiny amount to a low-weight tier-5 stat — **will be kept**. Per settled decision 3 (strict, zero slack), the only slack in a lock is the float-hygiene tolerance `tol_k = max(1e-5, |V_k|·1e-6)` (§4.4), which on a `G_t ∈ [0,1]` scale is ~0.001% of a tier goal. That tolerance incidentally doubles as the "numerically negligible" threshold: an item contributing less than `tol_k` to every locked tier is droppable. Anything above it is not. Builder must **not** widen `tol_k` to make emptying more aggressive — the future user-facing `tier_slack` knob (§1.2, out of scope) is the correct lever for that, and widening `tol_k` would silently change tier semantics.

### 14.4 Boundary analysis: can emptying a slot violate a not-yet-locked tier's eventual lock?

**No. This is structurally impossible, for one reason: locks record what was *achieved*, never what is *targeted*, and locks constrain goal values, never slot occupancy.**

The full argument, stated explicitly so it does not resurface as an open question:

1. **`V_k` is measured, not aspirational.** §4.2 records `V_k = value(G_{t_k})` from the stage's own solved variable values. There is no independently-computed target that a later configuration could fall short of. Whatever slots were empty at the moment stage *k* solved are simply part of the solution that produced `V_k`.
2. **Locks never constrain which items are equipped.** Every `tier_lock_{t}` constraint is `G_t ≥ V_t − tol_t`, an inequality over `n_s` (and `present_s` for tier 4). Slot occupancy is unconstrained by any lock. So the solver is always free to re-fill a slot in a later stage, or to satisfy the same `G_t` through an entirely different item set.
3. **No item is ever dropped before every tier is locked.** Consolidation (§5) runs strictly *after* the last tier stage. When it removes an item, **all** `tier_lock_*` constraints are simultaneously present, so the removal is validated against every tier at once. There is no window in which a slot is emptied while a tier that depends on it is still un-locked.
4. **Tier-stage tie-breaks cannot create a latent violation.** During stage *k*, `LAMBDA_ITEM_TIE` could in principle nudge the solver to leave a slot empty rather than fill it with an item useful to a later tier *j > k*. This is not a violation: `V_j` is recorded from stage *j*'s own solve, which is free to fill that slot. At worst there is a negligible search-path effect, bounded by `2.4e-5` of goal value.
5. **Folding (§4.6) does not weaken this.** A stage that produces no incumbent records **no** lock; its goal is carried in `pending` and locked only when a later stage actually achieves it. Again: only achieved values are ever locked.
6. **Reconciliation (§6) cannot change the slot set.** It fixes every `x`, `y`, `fw`, `fm` to the consolidation values and only redistributes the free display `d` vars. The final equipped-slot set is exactly consolidation's output.

Add points 1–3 as a comment block above `solve_tiered`.

### 14.5 New acceptance criteria (append to §10, "Integration — solve behavior")

| ID | Check |
|---|---|
| **AC-46** | **Empty-slot preference.** Synthetic fixture, **no minor artifacts in the pool** (so `Σ minor == 1` at L533 does not force an equip): priorities `[{"stat":"A","tier":1},{"stat":"B","tier":1}]`. Items — `Dense` (Helmet): `Enhancement +10 A`, `Enhancement +10 B`; `SoloA` (Cloak): `Enhancement +10 A`; `SoloB` (Belt): `Enhancement +10 B`. All bonus types **non-stacking**, so `UB_A = UB_B = 10` and `Dense` alone yields `n_A = n_B = 1.0`, `G₁ = 1.0` — the tier-1 lock is fully satisfiable with **one** item. **Assert:** `gearSet` contains `Dense`; `gearSet` contains **neither** `SoloA` **nor** `SoloB`; `"Cloak"` and `"Belt"` are absent as keys from both `gearSet` and `slots`; `len(gearSet) == 1`. This tests `P_item` and `P_dup` together and fails loudly if any slot constraint was turned into an equality. |
| **AC-47** | **No over-emptying (load-bearing items are retained).** Same fixture shape, but `Dense` grants only `Enhancement +10 A` and `SoloB` (Belt) grants only `Enhancement +10 B`. Both stats are tier 1, so `G₁ = 1.0` requires both items. **Assert:** `gearSet` contains both; `len(gearSet) == 2`; `realizedStats["A"] == 10` and `realizedStats["B"] == 10`. Guards against the consolidation penalty eroding real stat value — which would indicate a locking bug, since `LAMBDA_ITEM` is deliberately aggressive. |
| **AC-48** | **Occupancy constraints are inequalities (INV-7 static guard).** Inspect the constructed `Model.prob`: every slot-occupancy constraint (one per entry of `required_slots`) has sense `LpConstraintLE`, not `LpConstraintEQ`. The **only** permitted equality constraints over `x` variables are the minor-artifact constraint (`Σ minor_vars == 1`) and any `pre_equipped` pins. Cheap, and it catches a "fix" to L516 immediately. |

### 14.6 New edge cases (append to §11)

| ID | Case | Required behavior |
|---|---|---|
| **EC-25** | An item contributes a **nonzero but negligible** amount to an already-satisfied tier that is not yet locked | Cannot cause a violation — see §14.4. Locks are recorded from achieved values, constrain goal values rather than slot occupancy, and consolidation runs only after every tier is locked. No guard code needed; add the §14.4 reasoning as a comment above `solve_tiered`. |
| **EC-26** | Pool contains a minor artifact | `Σ minor_vars == 1` (L533) forces exactly one minor artifact equipped. That slot is **never** emptied by consolidation, regardless of its stat contribution. Correct and intentional — do not relax it. Fixtures for AC-46/AC-47 must exclude minor artifacts. Note also that dropping the minor artifact would zero the artifact-filigree capacity (L580-599), a second reason the constraint stays. |
| **EC-27** | Consolidation empties **every** slot (`gearSet == {}`) | Structurally unreachable in practice: if any tier-1 stat matched at least one source, equipping that source yields `G₁ > 0`, which the tier-1 lock then requires — and if *no* priority matched any source, EC-4 already fails the run first. Defensive handling only: if `gearSet` is empty after consolidation, restore the last-good snapshot, set `tierReport.degraded = true`, and append to `tierReport.notes`: `"Consolidation produced an empty gearset; restored the pre-consolidation solution."` Do not fail the run. |
| **EC-28** | Consolidation drops an item that was the sole piece completing a set bonus | Legal only if every lock still holds — the set's contribution flows into `z` → `n_s` → `G_t`, so a lock protects it if any locked tier depended on it. If no locked tier depended on it, the set bonus was not load-bearing and dropping it is the requested behavior. `activeSets` is recomputed from the reconciled solution (§6 step 2 recomputes every `w_var` deterministically from the final `x`/`fw`/`fm`), so the output stays consistent with what is actually equipped. |

### 14.7 Documentation

Add to the Phase 10 section of `docs/PHASE9_PLAN.md`, under a short "Empty slots" heading: slots are never mandatory (`≤ 1`, unchanged since before Phase 9); once every tier goal is locked, the consolidation stage actively empties any slot whose item is not load-bearing; the two exceptions are the mandatory minor artifact and user-pinned `pre_equipped` items. This is user-visible behavior — a solved gearset may legitimately come back with fewer than 14 slots filled, and the UI should not treat a missing slot key as an error.
