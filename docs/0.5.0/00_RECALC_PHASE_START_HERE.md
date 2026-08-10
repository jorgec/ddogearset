# START HERE — recalculation phase

> [!CAUTION]
> **DEPRECATED — superseded by [`00_ETL_START_HERE.md`](00_ETL_START_HERE.md).**
> The project pivoted on 2026-08-10 to a dev-only, build-time ETL producing a
> normalized SQLite catalog. **0.5.0 is the ETL, 0.5.1 is `app.db`, 0.5.2 is
> UI/UX.** The plan below is not the plan.
>
> **Keep for the findings, not the plan:** the XML shape traps (§4.1, §4.4, §4.5) are exactly what the Transform stage must handle, and the Wails bridge payload limits (§4.2) still bind.

**Written:** 2026-08-10.
**Audience:** an agent or developer picking this up **from `main`**, with no
memory of the session that produced these documents.

---

## 1. What happened, in five sentences

A previous session attempted to decouple "Calculate Stats" from the solver by
**reimplementing the stat pipeline in Go and the frontend**. It was completed
and it failed: rebuilding the domain rules outside Python meant forking the XML
parsing, the stat naming and the stacking rules, and on a real gearset the
headline priority panel ended up reading **0 for 13 of 14 priorities**. That
work has been **discarded** — the branch was reset and only these documents
were carried over. The correct separation is between the **search** and the
**domain rules**, and it runs *inside* Python. The UI/UX work from that attempt
was good and is specified here for rebuilding.

---

## 2. Read in this order

| # | Document | What it gives you |
|---|---|---|
| 1 | **This file** | Baseline, vocabulary, and what does/doesn't exist |
| 2 | [`CALCULATE_STATS_RETROSPECTIVE.md`](CALCULATE_STATS_RETROSPECTIVE.md) | Why the Go approach failed. **Read before proposing any alternative** |
| 3 | [`RECALCULATION_SEPARATION_PROPOSAL.md`](RECALCULATION_SEPARATION_PROPOSAL.md) | The replacement design + the full test architecture (addendum §10–§20) |
| 4 | [`UI_CHANGES_0_5_0.md`](UI_CHANGES_0_5_0.md) | UI/UX spec to **build** (none of it exists yet) |

Older documents that may also have been carried over —
`CALCULATE_STATS_IMPL_SPEC.md`, `CALCULATE_STATS_DECOUPLING_HANDOFF.md`,
`SESSION_REBUILD_SPEC.md` — describe the **abandoned** approach. They are
retained for their trap lists only. `CALCULATE_STATS_IMPL_SPEC.md` carries a
CAUTION banner; if it does not, you are looking at a stale copy.

---

## 3. Baseline — the exact state of `main`

Verified against `main` at the time of writing.

| Fact | Value |
|---|---|
| `main` HEAD | `fff94a9` |
| `AppVersion` (`app.go`) and `wails.json` | `0.4.4` |
| Python test suite | **171 passing** |
| `svelte-check` | 0 errors, 0 warnings, 15 hints |
| `go build` / `go vet` / `go test` | clean |

**Record your own baseline numbers before changing anything.** The previous
session reached a state with dozens of failing Python tests and no clean
baseline to attribute them to.

> [!WARNING]
> **The test oracle is not in git. Preserve it.**
>
> `.gitignore` line 22 is `*.ddogearset`, so **zero** gearset files are tracked.
> The saved `.ddogearset` files in `gearsets/` each carry the solver's own
> `realizedStats` for a real 14-slot gearset — they are the differential oracle
> the whole test plan rests on (proposal §14.1), and a fresh clone of `main`
> has **none of them**.
>
> They are untracked, so `git reset --hard` leaves them alone — but
> `git clean -fd` destroys them, and no other machine has them at all.
>
> **Before starting: copy `gearsets/*.ddogearset` somewhere safe, then check a
> representative set in as fixtures** (e.g. `python/tests/fixtures/gearsets/`,
> with a `!` negation in `.gitignore`). Record each one's `app_version` — files
> saved before 0.4.2/0.4.3/0.4.4 legitimately disagree with current behaviour,
> and proposal §14.1 turns those disagreements into regression tests rather
> than noise.

### 3.1 What EXISTS on main (and is the thing being changed)

- **`mode: "calculate"` is live.** `python/solver.py` has
  `VALID_MODES = ("optimize", "calculate", "alternatives", "stat_search")`,
  and `optimizer.py` has ~14 references to `calculate_only`. This is what
  the Calculate button uses today, via
  `RunOptimization({...configStore, mode: 'calculate'})` in **both**
  `Summary.svelte` (~line 331) and `GearsetEditor.svelte`.
- **It builds the full ILP and shells out to GLPK** to evaluate a gearset that
  is already determined, and applies **search-time restrictions** while doing
  so. That is the defect this phase exists to fix.
- `store.ts` exports **`hydrateConfigFromSlots`**, which backfills
  `pre_equipped` from solver output — i.e. a solve silently overwrites the
  user's own gearset.
- `App.svelte` has a bottom drawer with `drawerSection: 'config' | 'filigrees'`
  — filigrees live **inside the configuration drawer**.
- `SaveGearset(payload, result)` — two arguments, save format **v1.2**.
- `GetSystemLogs()` returns `a.logs` **directly** (no mutex, no copy, unbounded).
- `frontend/tsconfig.json` `include` covers **`src/**` only** — the generated
  `wailsjs/` directory is *not* type-checked.
- `internal/models/models.go`: `XMLBuff.Item` and `XMLEffect.Item` are
  **single `string` fields** (see §4.1 — this is a real bug).

### 3.2 What does NOT exist on main

Everything below was built in the abandoned attempt and is **gone**. Where a
document says "keep" or "already done", read it as **"build this"**.

| Absent | Where its spec lives |
|---|---|
| `enrich.go`, `calculate_stats.go`, `stat_matching.go` | **Do not rebuild** — this is the failed approach |
| `gearset_upgrade.go`, Upgrade button | UI doc §7 — re-scope; may have nothing to do |
| `Suggestions.svelte`, three-tab layout, Accept flow | UI doc §1–§2 |
| `progressLog.ts`, `wailsCall.ts`, `isLoadingFile` | UI doc §4, §6 + §4.2 below |
| `AddLog` binding, log mutex/cap | UI doc §5 + §4.2 below |
| `PYTHONUNBUFFERED=1` in `runSolver` | UI doc §8 |
| Check Inventory button | UI doc §3 |
| `wailsjs/` in tsconfig, binding-patch script | §4.3 below |
| Multi-`<Item>` / multi-`<SetBonus>` model fixes | §4.1 below |

---

## 4. Findings that must not be lost

These were expensive to discover, are **still latent bugs on main**, and are
independent of which approach you take.

### 4.1 `<Item>` and `<SetBonus>` repeat — main reads them wrongly

`<Item>` is a repeating element. A single effect can apply to several targets:

```xml
<Effect>
  <Type>SpellPower</Type>
  <Bonus>Equipment</Bonus>
  <Amount size="1">159</Amount>
  <Item>Force</Item>
  <Item>Physical</Item>
  <Item>Untyped</Item>
</Effect>
```

*(from `Miserable Arcana: Force (Legendary)`, in
`DDOBuilderV2/Output/DataFiles/Augments/Lamordia_Legendary.Augments.xml`)*

- **Python** `findtext('Item')` returns the **first** — `Force`. Correct today.
- **Go** `Item string` keeps the **last** — `Untyped`. **Wrong on main**, and
  the item-detail panel displays it.

Corpus counts, measured: **4261 `<Effect>` blocks and 532 `<Buff>` blocks**
carry more than one `<Item>`. Not an edge case.

The same shape appears one level up: a filigree can carry **several
`<SetBonus>` elements** — `Zarigan's Arcane Enlightenment/Voltaic Experiment +2
Intelligence` is a piece of **both** named sets (see `Raid.Filigree.xml`).
`XMLFiligree.SetName` is a single string, and `ParseFiligrees` injects only the
**file-level** root set — and `Raid.Filigree.xml` has no root set, so those
filigrees end up belonging to **nothing**.

> **Decide once, for all stacks:** is a multi-target effect credited to the
> first target (today's Python behaviour) or to all of them? Whichever you
> choose, it must be implemented in exactly one place.

### 4.2 The Wails bridge silently drops large messages

Measured against the running app (`wails dev`, real bindings):

| Argument size | Concurrent calls | Returned |
|---|---|---|
| 16 KB | 40 | 40 / 40 |
| 64 KB | 40 | **6 / 40** |
| 64 KB | 1, then 1 again | 1st in ~30 ms, **2nd never returned** |
| 256 KB | 40 | **0 / 40** |

A dropped message is a promise that **never settles** — it does not reject. Any
`finally` that clears a busy flag never runs, so the UI locks with no error and
no console output. This is what "the load hangs" turned out to be.

**Consequences for any design:** keep bridge payloads small (send *names*, not
object graphs); keep advisory calls off the critical path; and wrap any call
that can carry a large payload in a timeout so an invisible hang becomes an
ordinary error.

Two contributing factors on main, both worth fixing regardless:

- `GetSystemLogs()` returns the **unbounded** log slice, and it is polled about
  **once per second, forever**. A single solve appends every line GLPK prints.
  Fix: mutex, cap (~2000 lines), and return a **copy** — `append` can
  reallocate the backing array mid-read.
- Any new `AddLog`-style binding makes the frontend a **third** concurrent
  writer to that slice, alongside the startup goroutine and RPC handlers.

### 4.3 Wails codegen emits invalid TypeScript for `map[string][]Struct`

For a Go field `map[string][]Foo`, `wails generate module` writes:

```ts
this.convertValues(source["augments"], Foo[], true);   // Foo[] is a TYPE
```

`Foo[]` in an expression position is not parseable JavaScript, so `models.ts`
becomes a broken module. Nobody noticed because `wailsjs/` is excluded from
type-checking and every import of it is `import type` (erased at build) — until
someone value-imports it, at which point the build breaks.

**Naming the slice type does not help** — the generator resolves it back to the
element type. Mitigations: add `wailsjs/**` to `frontend/tsconfig.json`'s
`include`, and post-process the generated file (rewrite `Foo[]` → `Foo` in the
`convertValues` argument) behind a single "regenerate bindings" script so
`wails generate module` is never run bare.

### 4.4 Real saved-file hazards

Confirmed in real `.ddogearset` files in `gearsets/`:

- A **corrupted empty-string** filigree entry (`""`) in
  `pre_filled_filigrees.weapon`. Origin unknown.
- **Duplicate filigree names** in the same list — one file has 9 non-empty
  weapon entries but only **8 distinct** names. The old calculate mode pinned
  one variable per distinct name and then asserted `sum(fw) == 9`: unsatisfiable
  on arrival, reported as *"the supplied gearset could not be evaluated."*
- `reserved_minor_artifact_slot: ""` with `is_dino_artifact: true` produces the
  string `" (dino)"` — a leading-space fragment with no slot name — which is
  passed into item parsing.
- A gearset whose gear exists **only** in `result.gearSet` with an empty
  `pre_equipped` (what a solve-then-save produces). Still a real gearset.
- A **filigree name that disagrees with its data**: `Melony's Melody: +1
  Intelligence` carries `AbilityBonus 2`; `The Inevitable Grave: +1
  Intelligence` carries 1. Trust the data, not the name.
- `<Rare/>`-tagged effects are an **alternate variant** of a filigree, not an
  addition. Python's `parse_filigrees` skips them; Go's display parser
  deliberately keeps them (there is a test asserting so). Two consumers, opposite
  requirements, one field.

### 4.5 A set can have several tier rows at the same piece count

One real set has **three** separate tier rows all at 2 pieces, one effect each.
All the effects apply, but they describe **one** active tier — emit the
`(N-piece)` label once or the UI shows it three times.

---

## 5. Vocabulary

Terms used consistently across these documents.

| Term | Meaning |
|---|---|
| **The solver / the search** | The ILP model, GLPK, candidate pools, and the restrictions that shape them. `optimizer.py`'s `create_model` and below |
| **The domain rules** | XML → effects, stat naming, bonus-type stacking, set-piece counting. Currently interleaved with the search in `optimizer.py` |
| **Recalculation** | Evaluating a gearset that is *already determined*. No search. The subject of this phase |
| **Search-time restriction / configuration rule** | ML window, armor restriction, weapon style, excluded packs, owned-items-only, raid-item cap. **They exist to shape a suggestion and must never constrain what a user may equip** |
| **Physical rule** | One item per slot, augment colour compatibility, minor-artifact exclusivity, filigree slot counts. Real game constraints — but they should *warn*, never make evaluation fail |
| **`pre_equipped`** | The user's own gearset (`configStore.pre_equipped`). Their intent |
| **Two-node model** | Keeping the user's gearset and the solver's proposal as separate stores, with an explicit Accept between them (UI doc §2) |

---

## 6. The directive this phase serves

Verbatim, from the project owner:

> The configuration restrictions are only relevant to the UI experience, for
> making passing parameters to the solver easier and less error prone. It
> should not dictate what the user can or cannot do when creating or modifying
> their gearset and running calculate stats.

and, refining it after the failed attempt:

> The ask is just to be able to separate the solving and the recalculation.
> Recalc doesn't need the solver — it just calculates what the current gearset
> is. That includes the user just entering gear by themselves, either with the
> solver's base solution, or them editing the gearset, or from a fresh gearset
> that didn't go through the solver at all. Furthermore, the calculation of
> stats **does not need to go through the configuration rules for the solver at
> all**. Those configuration rules are just for the solver to come up with a
> suggestion, not to restrict what the user just wants to equip. But of course,
> the calculations for what stacks and what does not still apply — and the
> calculation should still run based on **what's equipped**.

**Note what this does *not* say.** It does not say "leave Python". The previous
attempt read it that way; see the retrospective §2.

---

## 7. Ground rules for whoever picks this up

1. **Establish and record a green baseline first** (§3).
2. **Do not create a second implementation of any domain rule.** If a rule
   exists in Python, Go and Svelte must call it, not copy it. The proposal's
   §12 designs tests that enforce this structurally.
3. **Differential-test against the existing behaviour before writing unit
   tests.** The `.ddogearset` files in `gearsets/` carry the solver's own
   `realizedStats` — that is the oracle, and it went unused until the end last
   time.
4. **Test across the boundaries, not just within them.** A green Go suite told
   us nothing about the Wails bridge.
5. **Never let an empty or failed result overwrite a gearset's saved stats.** A
   wrong number is worse than no number.
6. **Commit nothing until explicitly told.** Standing instruction on this
   project.
