# Retrospective — why "Calculate Stats in Go" failed, and what to do instead

> [!CAUTION]
> **DEPRECATED — superseded by [`00_ETL_START_HERE.md`](00_ETL_START_HERE.md).**
> The project pivoted on 2026-08-10 to a dev-only, build-time ETL producing a
> normalized SQLite catalog. **0.5.0 is the ETL, 0.5.1 is `app.db`, 0.5.2 is
> UI/UX.** The plan below is not the plan.
>
> **Still the most important document here.** Why reimplementing domain rules outside Python failed. The ETL does not repeal a single lesson in it — notably "one layer owns priority matching".

> [!IMPORTANT]
> **The code discussed here no longer exists.** The branch it lived on was
> discarded and only these documents were carried to `main`. File names below
> (`enrich.go`, `calculate_stats.go`, …) are named so you can recognise the
> *shape* of the mistake — not because you will find them. Start with
> [`00_RECALC_PHASE_START_HERE.md`](00_RECALC_PHASE_START_HERE.md).

**Written:** 2026-08-10, after the 0.5.0 attempt.
**Status:** the approach documented here is **abandoned**. Read this before
attempting recalculation again.
**Companions:**
[`UI_CHANGES_0_5_0.md`](UI_CHANGES_0_5_0.md) — the UI work from the same
effort, written as a spec **to rebuild**.
[`RECALCULATION_SEPARATION_PROPOSAL.md`](RECALCULATION_SEPARATION_PROPOSAL.md)
— the replacement design. §4 below sketches the direction; that document is the
worked proposal, and it supersedes this sketch where the two differ.

---

## 0. The one-paragraph version

The directive was right: *"Calculate Stats shouldn't go to the solver — it's a
purely UI calculation."* The **implementation** read that as "reimplement the
stat pipeline outside Python", and that pipeline is not a UI calculation. It is
the solver's domain model: XML quirks, stat naming, bonus-type stacking, set
piece counting, and three years of accumulated bug fixes. Rebuilding it in Go
meant forking all of it. Every hour of that effort went into rediscovering
things `python/optimizer.py` already knew.

**The objection was never "Python is wrong."** It was "don't build a 5000-row
ILP and shell out to GLPK to add up numbers that are already known." That is
fixable *inside* Python — see §4.

---

## 1. What was actually built

For the record, so the next attempt recognises the shape of it. **None of these
files exist on `main`** — this is an inventory of a deleted branch, and the
"verdict" column is the judgement that led to deleting it.

| Piece | File (deleted) | Verdict |
|---|---|---|
| Effect enrichment (XML → per-item effect list) | `enrich.go` | **Discard** — duplicates `parse_items`/`parse_augments`/`parse_filigrees` |
| Solver-free aggregation (stacking, sets) | `calculate_stats.go` | **Discard** — duplicates `_resolve_totals` + set counting |
| Priority-name matching | `stat_matching.go` | **Discard** — a hand port of `normalize_stat_name` |
| Enriched save format (`enriched_gear`, v1.3) | `app.go` `SaveGearset` | **Discard** — exists only to feed the above |
| Legacy upgrade path | `gearset_upgrade.go` | **Probably unnecessary** — see §5 |
| UI / UX changes | see companion doc | **Rebuild** — the one clear success |

Three of those files are a second implementation of rules that already exist,
tested, in Python.

---

## 2. What went wrong, in order of how much time it cost

### 2.1 Stat NAMING was the real killer (largest single cost)

`normalize_stat_name` does **two** jobs. The spec's confirmed answer to "what
does it report?" was *"every stat the gear provides, not filtered through
priority names"*, which was read as "drop `normalize_stat_name`". That dropped
both jobs:

1. **Filter** — return nothing for an unprioritised stat. *Correct to drop.*
2. **Name** — report a stat under the name the user's priority uses
   (`SpellPower` + Item `Force` → `force spellpower`). **Wrongly dropped.**

Consequence on a real gearset: the Optimized Priority Targets panel — the
app's headline readout — showed **0 for 13 of 14 priorities**. Totals were
computed correctly and filed under raw XML names no priority list mentions.

Restoring it meant porting ~250 lines, and *every guard in it is a past bug*:

| Guard | Origin | What it prevents |
|---|---|---|
| Hireling | 0.4.4 | `HirelingPRR` credited to the player (reported PRR 67 vs a real 47) |
| School save | 0.4.2 | `IllusionSave` (defensive) inflating an Illusion **DC** (offensive) |
| Skill group | 0.4.3 | An `Intelligence` priority absorbing `Intelligence Skills` buffs |
| Weapon base stats | §15.2 | Exact-match stats going through the substring heuristic |
| Bonus-type prefixes | CASTER_BONUS_TYPE_STATS_SPEC | `sacred spell focus mastery` matching only Sacred sources |
| Direct-before-implied two-pass | — | An early school-DC priority starving an explicit SFM priority |

> **Do not port this.** Porting it forks six bug fixes into a second language.
> They will drift, and the drift will be silent — both sides produce *a*
> number.

### 2.2 The XML is full of shapes a fresh parser gets wrong

Each of these was found the hard way, by a wrong number reaching the screen:

- **`<Item>` repeats.** `Miserable Arcana: Force` grants +159 to Force **and**
  Physical **and** Untyped spell power. Go's `Item string` kept the **last**
  (`Untyped`); Python's `findtext` takes the **first** (`Force`). Affects
  **4261 `<Effect>` and 532 `<Buff>` blocks** — not an edge case. Symptom: the
  effect is filed under a stat nothing references.
- **`<SetBonus>` repeats on filigrees.** The `SetA/SetB` filigrees are a piece
  of **both** sets. A single-string field kept one, so set piece counts ran
  short and tier bonuses silently failed to activate.
- **`<Rare/>` variants** replace the base effect rather than adding to it, and
  Go's *display* parser deliberately keeps them (AC-16). Aggregation must skip
  them; the two parsers want opposite things from the same field.
- **Multiple tier rows at the same piece count.** One real set has three rows
  all at 2 pieces. Effects all apply; the **label** must be deduplicated or
  `activeSets` shows "(2-piece)" three times.
- **Filigree names lie.** `Melony's Melody: +1 Intelligence` carries
  `AbilityBonus 2` in the data; `The Inevitable Grave: +1 Intelligence` carries
  1. The name is not a statement of value.
- **Embedded augments** (Cannith/Slavelord) — only the `SelectedAugment`
  applies; applying every offered choice credits mutually exclusive upgrades.

### 2.3 Moving the data became its own problem

Self-contained recalculation requires the effect graph to *be somewhere*. It
was put in the frontend store and shipped over the Wails bridge — and large
messages there are **silently dropped**. A dropped message is a promise that
never settles, so the `finally` clearing the busy flag never runs: the UI locks
with no error and no console output.

Measured against the running app:

| Payload | Concurrency | Returned |
|---|---|---|
| 16 KB | 40 | 40 / 40 |
| 64 KB | 40 | **6 / 40** |
| 64 KB | 1, repeated | 1st in 30 ms, **2nd never** |
| 256 KB | 40 | **0 / 40** |

Contributing factors, both self-inflicted: the load path sent the whole file
across **twice** (checksum + format check), and `GetSystemLogs` re-sent an
**unbounded** buffer every second (a solve appends every GLPK line).

> **Lesson:** the bridge is for *names and small results*. Do not design a
> feature whose correctness depends on shipping a large object graph across it.

### 2.4 Save-format churn punished the user directly

`enriched_gear` was added (v1.3), then needed `rawType`/`rawItem`/`rawDesc` for
priority matching, then `setName` → `setNames`. **Each change invalidated files
already upgraded** — three re-upgrades in one session.

> **Lesson:** persisting a derived cache means every fix to the derivation is a
> migration. Derive at read time from a source of truth that is already
> versioned (the catalog), or don't persist it.

### 2.5 The tests validated the wrong layer

- Every Go test called `CalculateStats` **directly**. Nothing crossed the Wails
  boundary, so §2.3's hang was invisible to a fully green suite.
- `wailsjs/` was **excluded from type-checking**, so the generated `models.ts`
  was syntactically invalid (`convertValues(source["augments"],
  EnrichedAugment[], true)` — a type in an expression position) and nobody
  noticed, because every import of it is `import type` and erased at build.
- Unit tests asserted the implementation's own assumptions. The oracle that
  actually mattered — *the solver's saved output in real `.ddogearset` files* —
  went unused until very late, and immediately exposed the 1-of-14 failure.

> **Lesson:** for a reimplementation, the **first** test is a differential test
> against the original on real data. Not unit tests of the new code's own logic.

### 2.6 Second-order breakage from the two-node model

Making solver output a *proposal* (correct, see companion doc) meant it no
longer flowed into `pre_equipped`. Nothing updated Save, so **Optimize → Save
wrote an empty gearset**. A guard now catches it — but the class of bug is
"changed a data-flow invariant without auditing its consumers."

---

## 3. The rules this should have been checked against

Any future attempt should be able to answer **yes** to all of these before
writing code:

1. **Is this a UI concern or a domain concern?** Stat naming, bonus-type
   stacking and set-piece counting are DDO *rules*. They live where the rules
   live. Only presentation belongs in the UI.
2. **Am I about to create a second implementation of an existing rule?** If
   yes, stop. Two implementations of the same rule drift silently, because both
   produce plausible numbers.
3. **What is my oracle?** For anything replacing existing behaviour, the
   original's output on real data — before anything else.
4. **How much data crosses a process/bridge boundary?** If the answer scales
   with gearset size, redesign.
5. **Am I persisting derived data?** Then every derivation fix is a user-facing
   migration. Budget for it or don't persist.

---

## 4. The recommended direction — recalculation in Python

The original objection stands and is worth fixing. It just does not require
leaving Python.

### 4.1 What was actually wrong with the old `calculate` mode

It ran the **full search machinery** to evaluate a gearset that was already
determined:

- built the entire ILP (`create_model`) — slot exclusivity, augment colour
  compatibility, filigree count constraints, set-piece counting;
- solved an LP to "realize" pinned binaries, then `reconcile_solution`;
- and — the real defect — applied **search-time preferences** (ML window,
  armor/weapon style, excluded packs, owned-items-only, raid cap) to a gearset
  the user had built by hand. A perfectly legal gearset came back as
  *"could not be evaluated; some locked items may be incompatible."*

It also inherited genuine latent bugs, e.g. `sum(fw) == total_w_fils` counting
**non-empty entries** while the pins are per **distinct name** — a file with 9
non-empty weapon filigrees but 8 distinct names was unsatisfiable on arrival.

### 4.2 What to build instead

A **`mode: "recalculate"`** path in `solver.py` that is parse-and-aggregate
only:

```
recalculate(payload):
    parse_items / parse_augments / parse_filigrees / parse_sets
        with NO search-time restrictions:
            no ML window, no armor or weapon-style filter,
            no excluded packs, no owned-items-only, no raid cap
        and NO min_ml floor — a hand-built gearset defines its own pool
    resolve the named gearset directly (no model, no variables, no GLPK)
    count set pieces (items + augments + filigrees)
    apply set tiers that are met
    _resolve_totals()   # the EXISTING sum-vs-max stacking rule
    return realizedStats / allEffects / activeSets / slots
```

**Properties this has that the Go version could not:**

- One implementation of every rule. `normalize_stat_name`, `_resolve_totals`
  and the parsers are *reused*, not forked.
- No enrichment, no `enriched_gear`, no save-format churn. The payload stays
  what it always was: names.
- Small bridge traffic — names in, a result in, nothing that scales with the
  effect graph.
- The physical rules (one item per slot, augment colour compatibility, minor
  artifact exclusivity, filigree slot counts) can still be *validated and
  reported* without being *constraints that can make evaluation fail*.

**Non-negotiables, carried from §2.4 of `SESSION_REBUILD_SPEC.md` and this
session:**

- An empty or failed aggregation must **never** overwrite a gearset's existing
  saved stats. A wrong number is worse than no number.
- Skip empty-string filigree entries and de-duplicate repeated names; real
  saved files contain both.
- Never let a search-time preference make a hand-built gearset unevaluatable.
- Keep `PYTHONUNBUFFERED=1` (0.5.0) or the console stays silent for the whole
  call and a working run is indistinguishable from a hang.

### 4.3 Cost comparison, measured

| | Go/frontend attempt | Python `recalculate` |
|---|---|---|
| New implementations of DDO rules | 3 files (~900 lines) | 0 |
| Save-format versions burned | 3 | 0 |
| Bridge payload | scales with gearset | constant, small |
| Priority match rate on a real gearset | 1/14 → 13/14 after a full port | already correct |
| Differential oracle available | added late | inherent |

---

## 5. What to REBUILD from the 0.5.0 attempt

Nothing here survived the reset — these are specifications, not code that is
sitting in the tree. Each item was independently valuable and is worth
rebuilding regardless of how recalculation is implemented. Implementation
detail for the non-obvious ones is in
[`00_RECALC_PHASE_START_HERE.md`](00_RECALC_PHASE_START_HERE.md) §4.

**Rebuild:**

- Everything in [`UI_CHANGES_0_5_0.md`](UI_CHANGES_0_5_0.md) — written as a build spec.
- `PYTHONUNBUFFERED=1` in `runSolver` (`app.go`).
- The bounded log buffer + `GetSystemLogs` returning a copy (`app.go`,
  `logs_test.go`) — this was a real data race *and* a real bridge-load problem.
- Ordered progress logging (`frontend/src/lib/services/progressLog.ts`) and the
  `AddLog` binding.
- `frontend/src/lib/services/wailsCall.ts` — `withTimeout`. Any Wails call that
  can carry a large payload should keep this; it converts an invisible
  unrecoverable hang into an ordinary error.
- `wailsjs/**` in `frontend/tsconfig.json`'s `include`, plus
  `scripts/generate-bindings.sh` and `scripts/patch_wails_models.mjs` — the
  generator emits invalid TypeScript for `map[string][]Struct` and nothing
  caught it for as long as the directory was unchecked.
- The multi-`<Item>` and multi-`<SetBonus>` model corrections in
  `internal/models/models.go` — these describe the data correctly regardless of
  who does the maths, and the display layer was reading them wrongly too.

**Do not rebuild:** the enrichment layer, the Go aggregation, the priority-name
port, the `enriched_gear` save key and the frontend enrichment plumbing. That is
the failed approach in its entirety.

**Probably unnecessary:** the Upgrade button. The refuse-rather-than-migrate
*rules* are good UX (companion doc §7), but they existed because the abandoned
design persisted a derived cache that needed migrating. The Python-side design
persists nothing, so `main`'s save format v1.2 stays valid and there is likely
nothing to upgrade. Keep the rules on file for a future genuine format change.

---

## 6. Open question the next attempt must answer first

`docs/CALCULATE_STATS_IMPL_SPEC.md` §2.2 recorded a confirmed decision:

> **What does it report?** Every stat the gear provides — not just the user's
> priority stats.

That is what made §2.1 happen, because it was read as "so priority names are
irrelevant". Both are wanted, and they are not in conflict:

- report **all** stats, under their catalog names, **and**
- report the **priority** stats under the user's own names, so the priority
  panel works.

In Python this is nearly free: `normalize_stat_name` already produces the
second, and the first is just "don't discard the unmatched ones". **Decide and
write this down before writing code.**
