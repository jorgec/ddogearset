# Separating solving from recalculation — proposal

> [!IMPORTANT]
> Read [`00_RECALC_PHASE_START_HERE.md`](00_RECALC_PHASE_START_HERE.md) first —
> it records the exact state of `main`, and the hard-won findings (§4 there)
> that this proposal assumes you already know.
>
> **On `main`, `mode: "calculate"` still exists** and is what the Calculate
> button uses. This document proposes replacing it. Nothing described as
> "existing" below refers to the discarded branch — every `optimizer.py`
> reference is to code that is on `main` right now.

**Written:** 2026-08-10.
**Supersedes the approach in:** [`CALCULATE_STATS_IMPL_SPEC.md`](CALCULATE_STATS_IMPL_SPEC.md)
**Background:** [`CALCULATE_STATS_RETROSPECTIVE.md`](CALCULATE_STATS_RETROSPECTIVE.md)
· [`UI_CHANGES_0_5_0.md`](UI_CHANGES_0_5_0.md)

---

## 1. The ask, restated

> Separate **solving** from **recalculation**.
>
> Recalculation does not need the solver. It calculates what the current
> gearset *is* — whether that gearset came from the solver, from the user
> editing the solver's output, or from a fresh gearset that never went through
> the solver at all.
>
> **The stat calculation must not go through the solver's configuration rules
> at all.** Those rules exist so the solver can produce a *suggestion*; they are
> not a statement about what the user is allowed to equip.
>
> DDO's stacking rules still apply. The calculation runs on **what's equipped**.

Your "(i think)" is correct, and it is now provable rather than a hunch — see
§3.

---

## 2. The conflation that sank the last attempt

Three different things were treated as one:

| | What it is | Where it lives |
|---|---|---|
| **The search** | ILP model, GLPK, candidate pools, restrictions | `optimizer.py` |
| **The domain rules** | XML→effects, stat naming, stacking, set counting | `optimizer.py` |
| **The runtime** | Python, in a subprocess | `solver.py` |

"Calculate Stats shouldn't go to the solver" is a statement about the **search**.
It was implemented as a statement about the **runtime** — move it out of Python
entirely — which dragged the **domain rules** along with it. That is what forced
a fork of the XML parsing, the stat naming and the stacking rules, and it is the
whole of the retrospective.

**The correct cut is between the search and the domain rules, and it runs
straight through `optimizer.py`.** Both sides stay in Python. Nothing is
reimplemented.

```
                    ┌──────────────────────────────────┐
                    │  domain rules  (no pulp, no ILP) │
   recalculate ────▶│  parse · name · stack · sets     │◀──── solve
                    └──────────────────────────────────┘
                                    ▲
                                    │  optimizer.py imports it
                    ┌───────────────┴──────────────────┐
                    │  the search: ILP model, GLPK,    │
                    │  candidate pools, RESTRICTIONS   │
                    └──────────────────────────────────┘
```

Restrictions live **only** in the search box. Recalculation never touches that
box, so it cannot inherit them — not by discipline, but by construction.

---

## 3. The aggregation already exists

This is the finding that makes the whole proposal small. `optimizer.py` already
contains a pure, non-ILP evaluator, written for the §7 alternatives path:

```python
_collect_contributions(equipped, aug_list, fil_weapon, fil_artifact, sets)
    # "Direct arithmetic against a fixed gearset."
    # Walks equipped items/augments/filigrees, counts set pieces
    # (filigrees included), applies every met tier.
    # -> {(stat, bonus_type): [(value, origin), ...]}

_resolve_totals(contrib)
    # "Sum for stacking bonus types, max for non-stacking — the DDO rule."
```

That is **exactly** what recalculation needs, it builds no model, it calls no
GLPK, and it is already exercised in production by a code path that does no
solving. The Go rewrite reimplemented both of these from scratch.

**So recalculation is not a new calculation. It is a new *entry point* to an
existing one.** The only genuinely new work is resolution: turning equipped
*names* into the item/augment/filigree dicts those two functions consume.

---

## 4. The one real obstacle: parsing and filtering are fused

`parse_items` does two jobs in one pass:

```python
parse_items(base_dir, max_ml, priorities, allowed_armor, allowed_w1_list,
            allowed_w2_list, allow_gomf, art_slot_input, excluded_packs=None,
            quests_lookup=None, pre_equipped_names=None, min_ml=29,
            owned_names=None)
```

Everything after `priorities` is a **search restriction**. Inside the loop it
interleaves *"is this item a candidate?"* with *"what does this item grant?"*.

That fusion is why the old `calculate` mode had to smuggle exemptions through
the same function (`is_pre_equipped` bypasses, `not calculate_only and
raid_item_limit >= 0`, …) — and why the exemptions ended up **inconsistent**:
the raid cap was exempted, the ML floor was not, the weapon-style filter was
not. A legal hand-built gearset came back as *"could not be evaluated."*

**The fix is to split the loop, not to add another exemption flag:**

```python
def _item_from_node(item_node, priorities, quests_lookup, ...):
    """What does this item GRANT? No filtering, no restrictions."""
    # the existing buff/set/augment-slot extraction, unchanged

def parse_items(...restrictions...):
    for node in ...:
        if not _passes_search_filters(node, ...): continue   # candidacy
        items.append(_item_from_node(node, ...))             # grant

def resolve_equipped_items(base_dir, names, priorities, ...):
    """What do THESE items grant? Candidacy is 'the user equipped it'."""
    for node in ...:
        if node.findtext('Name') not in names: continue
        items.append(_item_from_node(node, ...))
```

Same extraction, two candidacy rules. Same for augments and filigrees.
`parse_sets` already takes no restrictions and needs no change.

---

## 5. Proposed contract

### 5.1 A new mode, with a payload that *cannot* express a restriction

```jsonc
// mode: "recalculate"
{
  "mode": "recalculate",
  "stat_priorities": [ { "stat": "force spellpower", "tier": 1 }, ... ],
  "pre_equipped":         { "Helmet": "…", "Weapon1": "…" },
  "pre_filled_augments":  { "Helmet": { "Sun": "…" } },
  "pre_filled_filigrees": { "weapon": [ "…" ], "artifact": [ "…" ] }
}
```

That is the **entire** payload. No `max_level`, no `armor_restriction`, no
`weapon_style`, no `excluded_packs`, no `owned_item_names`, no
`raid_item_limit`, no `min_ml`.

> **This is the load-bearing design decision.** Do not pass the restrictions and
> ignore them. "Passed but ignored" is precisely how `calculate_only` drifted
> into exempting some restrictions and not others, silently, over several
> releases. If the field is not in the payload, no future edit can accidentally
> start honouring it.
>
> `solver.py`'s validation for this mode should **reject** a payload carrying
> restriction keys rather than dropping them, so a stale caller fails loudly
> instead of quietly getting filtered results.

`stat_priorities` is present for **naming only** — it is what lets
`normalize_stat_name` report `force spellpower` instead of `SpellPower`. It must
never filter the output (§5.3).

### 5.2 Flow

```
recalculate(payload):
    items = resolve_equipped_items(base_dir, names(pre_equipped), priorities)
    augs  = resolve_equipped_augments(base_dir, names(pre_filled_augments), priorities)
    fils  = resolve_equipped_filigrees(base_dir, names(pre_filled_filigrees), priorities)
    sets  = parse_sets(base_dir, priorities)          # already restriction-free

    contrib = _collect_contributions(items, augs, fil_w, fil_a, sets)   # EXISTING
    totals  = _resolve_totals(contrib)                                  # EXISTING

    return { realizedStats, allEffects, activeSets, slots, warnings }
```

No model. No variables. No GLPK. No feasibility. **It cannot fail to
"evaluate"** — there is nothing to satisfy.

### 5.3 Output: report everything, name what you can

The line in the old spec — *"report every stat the gear provides, not just
priority stats"* — was read as "so priority names don't matter", and that is
what made the priority panel read 0 for 13 of 14 priorities. Both are wanted:

- **every** stat the gear grants is reported, including unprioritised ones;
- a stat that a priority claims is **additionally** reported under the user's
  own spelling, so the Optimized Priority Targets panel works.

In Python this is close to free: `normalize_stat_name` already yields the
second, and the first is just "don't discard the ones it returns `None` for" —
fall back to the raw `Type`/`Item` name instead of dropping the buff.

### 5.4 Physical rules: validate and report, never refuse

Genuinely physical constraints (one item per slot, augment colour
compatibility, minor-artifact exclusivity, filigree slot counts) still hold —
but under this design they are **observations about the gearset, not conditions
for evaluating it**:

- compute the totals **unconditionally**;
- return a `warnings` list ("Two minor artifacts equipped", "12 weapon
  filigrees in 10 slots");
- let the UI surface them.

The old mode encoded them as ILP constraints, which is why a duplicated
filigree name (`sum(fw) == 9` against 8 distinct pins) made a real file
**unevaluatable** rather than merely odd.

### 5.5 Rules carried forward, non-negotiable

- An empty or failed result must **never** overwrite a gearset's existing saved
  stats. A wrong number is worse than no number.
- Skip empty-string filigree entries; de-duplicate repeated names. Real saved
  files contain both.
- Keep `PYTHONUNBUFFERED=1` — this adds another subprocess round trip the user
  waits on, and without it the console is silent for all of it.
- `<Item>` and `<SetBonus>` repeat. Python's `findtext` takes the first, which
  is the established behaviour; if multi-target crediting is wanted, change it
  **once**, in the shared extractor, for both solve and recalculate.

---

## 6. Performance — measured, not estimated

The concern with "put it back in Python" is the subprocess. Measured on this
machine, on the real corpus:

| Step | Cost |
|---|---|
| Bare interpreter start | 34 ms |
| `import pulp` | **172 ms** |
| `import optimizer` | 83 ms |
| Glob 8779 `.item` files | 41 ms |
| **Full XML parse of all 8779** | **1788 ms** |
| **Text prescan, parse only the 16 files that can match** | **285 ms** |

Two consequences:

1. **Recalculation does not need `pulp`.** Splitting the domain rules into a
   module that does not import it removes the single largest fixed cost. This is
   an argument for the §2 split beyond tidiness.
2. **Resolution should prescan, not parse everything.** Reading each file as
   text and only XML-parsing the ones containing a wanted name is **6× faster**
   (285 ms vs 1788 ms) because it parses 16 files instead of 8779.

**Budget: comfortably under one second**, against 40–60 s for the old
`calculate` mode. Add PyInstaller's own unpack for the bundled binary (not
measured here — worth checking before committing to the design, as it is the
one number that could change the conclusion).

If that turns out too slow for a button press, the fallback is to have Go —
which already holds an in-memory catalog with name indexes — pass the resolved
item XML in the payload. **Do not reach for that first**; it re-introduces the
large-payload bridge problem the retrospective documents (§2.3).

---

## 7. What this means for the code on `main`

The abandoned branch is gone; there is nothing to delete. This is what to
**change** and **add**, starting from `main`:

| On `main` today | Action |
|---|---|
| `mode: "calculate"` in `solver.py`; ~14 `calculate_only` refs in `optimizer.py` | **Replace** with `mode: "recalculate"` (§5). Decide up front whether the calculate-mode Python tests are deleted or rewritten — do not leave them failing |
| `RunOptimization({...configStore, mode:'calculate'})` in `Summary.svelte` and `GearsetEditor.svelte` | **Repoint** at the new mode, sending only the §5.1 payload |
| `parse_items` / `parse_augments` / `parse_filigrees` fuse candidacy with extraction | **Split** (§4) — the whole risk of the project |
| `XMLBuff.Item` / `XMLEffect.Item` are single `string`s | **Fix** to slices — see START_HERE §4.1. A real bug on `main`, and the item-detail panel displays the wrong value |
| `XMLFiligree.SetName` is a single string; `ParseFiligrees` injects only the file-level set | **Fix** — dual-set filigrees currently belong to nothing |
| `GetSystemLogs()` returns the unbounded slice directly | **Fix** — mutex, cap, return a copy (START_HERE §4.2) |
| `frontend/tsconfig.json` excludes `wailsjs/` | **Fix** — include it; add the binding-regeneration script (START_HERE §4.3) |
| `runSolver` has no `PYTHONUNBUFFERED` | **Add** (UI doc §8) |
| No `withTimeout`, no `isLoadingFile`, no `AddLog` | **Add** (UI doc §4, §6) |
| Everything else in `UI_CHANGES_0_5_0.md` | **Build** |

**Crucially, the frontend contract does not change shape.** It keeps sending
the gearset by **name** and keeps receiving
`realizedStats` / `allEffects` / `activeSets` / `slots`. The Vellum Summary
needs no changes — which is exactly why this design avoids the save-format
churn and the bridge-payload problem that sank the last attempt.

---

## 8. Suggested order of work

1. **Extract `_item_from_node` / `_augment_from_node` / `_filigree_from_node`**
   from the existing parsers. Pure refactor — the full Python suite must stay
   at 168 passing with no behaviour change. *This is the whole risk of the
   project; do it on its own and prove it.*
2. **Split the domain rules into a module that does not import `pulp`.**
   `optimizer.py` imports it. Suite still green.
3. **Add `resolve_equipped_*` + `recalculate()`** on top of the extracted
   pieces and the existing `_collect_contributions` / `_resolve_totals`.
4. **Differential-test against the solver, on real saved gearsets, first.**
   Compare `recalculate` against the `realizedStats` in the existing
   `.ddogearset` files before writing any unit tests. That oracle was available
   the whole of last time and went unused until the end — it is what
   immediately exposed the 1-of-14 failure.
5. **Wire `mode: "recalculate"`** in `solver.py` (rejecting restriction keys)
   and Go, then point the Calculate button at it.
6. **Add `warnings`** and surface them (§5.4).

Steps 1–2 are the valuable, reusable part even if the rest is reconsidered
again: they are what actually separates solving from recalculation.

---

## 9. Why this answers the ask

| Requirement | How |
|---|---|
| Separate solving from recalculation | Split at the search/domain-rules boundary, inside Python |
| Recalc doesn't need the solver | Confirmed: `_collect_contributions` + `_resolve_totals` build no model and call no GLPK |
| Works for any gearset provenance | Resolution is by name; it never asks where the names came from |
| **Config rules must not apply** | They are **absent from the payload**, not ignored — and rejected if sent |
| Stacking rules still apply | `_resolve_totals`, unchanged and unforked |
| Runs on what's equipped | Candidacy is "the user equipped it"; there is no candidate pool |

---

# Addendum — test architecture

**Scope:** how correctness is validated at every step, end to end across
Python → Go → Svelte, and how the three stacks are held to *one* implementation
of each rule.

**Standing budget decision:** processing slowness is acceptable in exchange for
correct behaviour. That permission is spent deliberately below — the
differential suite runs the **whole** corpus rather than a sample, and the
end-to-end suite drives the **real** app rather than a mock.

---

## 10. Principles, derived from what actually failed

Four rules, each earned by a specific failure in the 0.5.0 attempt:

1. **For a reimplementation, the differential test comes first.** Unit tests of
   new code assert the new code's own assumptions. Last time the suite was
   fully green while 13 of 14 priorities read 0, because the oracle — the
   solver's own output on real gearsets — went unused until the end.
2. **A test that does not cross the boundary does not test the boundary.**
   Every Go test called `CalculateStats` directly. The Wails bridge dropped
   messages and hung the UI, invisibly, against a green suite.
3. **Generated code is code.** `wailsjs/` was excluded from type-checking, so
   the generated `models.ts` was syntactically invalid and nobody noticed.
4. **Duplication is not found by testing behaviour.** Two implementations of a
   rule both produce plausible numbers. Duplication has to be detected
   *structurally*, by tests that read the source.

---

## 11. The layering contract

Every test in §12–§17 exists to enforce one of these rows. If a change needs a
row relaxed, that is a design discussion, not a test to weaken.

| Layer | **Owns** | **Must never** |
|---|---|---|
| **Python** (`python/rules/*`) | XML → effects; stat naming; bonus-type stacking; set-piece counting and tiers; physical-rule warnings | import `pulp`; know about search restrictions |
| **Python** (`optimizer.py`) | The ILP search, candidate pools, **all** restrictions | duplicate anything in `rules/` |
| **Go** | Process management; catalog cache for *browsing/pickers*; file I/O; checksums; transport | do arithmetic on stat values; normalize a stat name; decide what stacks; count set pieces |
| **Svelte** | User intent; presentation; formatting for display | compute a total; derive a stat name; re-rank or re-aggregate anything |

**The single-source-of-truth rule.** A domain rule has exactly one owner. Where
a *value* is genuinely needed in more than one stack (slot names, bonus-type
vocabulary), it lives in **one data file** that all three read — never retyped.

---

## 12. Category A — layering and anti-duplication guards

These are the tests that answer "is the logic where it should be, and only
there". They read source, not behaviour. **They run on every commit** and are
the cheapest suite in the plan.

### 12.1 The rules registry

A checked-in manifest — `docs/rules-registry.yaml` — naming every domain rule,
its single owner, and the patterns that would indicate it has leaked:

```yaml
- rule: bonus-type stacking (sum vs max)
  owner: python/rules/stacking.py::resolve_totals
  forbidden_outside_owner:
    - regex: '\b(stacking|mythic|reaper)\b.*\b(sum|max)\b'
    - literal_set: ["stacking", "mythic", "reaper"]      # the triple, together
  scan: [ "*.go", "frontend/src/**/*.ts", "frontend/src/**/*.svelte" ]

- rule: stat-name normalization
  owner: python/rules/naming.py::normalize_stat_name
  forbidden_outside_owner:
    - regex: 'spell ?focus ?mastery'
    - regex: 'hireling'
    - identifiers: [ BONUS_TYPE_PREFIXES, SKILL_NAMES ]
  scan: [ "*.go", "frontend/src/**/*.ts", "frontend/src/**/*.svelte" ]

- rule: set-piece counting
  owner: python/rules/sets.py::count_pieces
  forbidden_outside_owner:
    - regex: 'piece[ _-]?count|pieceCount'
    - regex: '\(\d+[- ]piece\)'          # the label format
  scan: [ "*.go", "frontend/src/**/*.ts", "frontend/src/**/*.svelte" ]
```

| Test | Asserts | Fails when |
|---|---|---|
| `test_registry_owners_exist` | Every `owner` resolves to a real file and symbol | A rule was renamed or moved without updating the registry |
| `test_no_rule_leaks_outside_owner` | No `forbidden_outside_owner` pattern matches in `scan` paths | Someone reimplements a rule in Go or Svelte |
| `test_registry_covers_every_rule` | A curated list of rule names matches the registry keys exactly | A new rule was added without declaring an owner |

> The third is the one that keeps the registry honest. Without it the registry
> silently stops describing the system.

### 12.2 Dependency-direction tests

| Test | Layer | Asserts |
|---|---|---|
| `test_rules_module_does_not_import_pulp` | Python | `python/rules/**` has no `pulp` import, transitively. Protects both the layering *and* the 172 ms startup win |
| `test_optimizer_does_not_reimplement_rules` | Python | `optimizer.py` calls `rules.*` and defines no local copy of the registry-owned symbols |
| `test_go_has_no_stat_arithmetic` | Go | No Go file outside transport performs float arithmetic on a value that came from a stat payload |
| `test_frontend_does_not_aggregate` | Svelte | No `reduce`/`+=` over `realizedStats`, `allEffects` or effect values in `frontend/src/**` |

### 12.3 Shared-vocabulary parity

| Test | Asserts | Fixture |
|---|---|---|
| `test_slot_names_single_source` | The 14 slot names appear in exactly one data file; Python, Go and Svelte all read it | `data/vocabulary.json` |
| `test_no_hardcoded_slot_lists` | No stack contains a literal list of ≥5 slot names | — |

> This is aimed squarely at a duplication that already exists on `main`: the
> 14-slot list is written out separately in `GearsetEditor.svelte`,
> `JobConfigurationForm.svelte` and `optimizer.py` (`base_required`) — and the
> UI spec adds a fourth copy in `Suggestions.svelte` unless the shared file
> lands first.

---

## 13. Category B — refactor-equivalence (proposal steps 1–2)

Steps 1–2 are a **pure refactor** and carry the whole risk of the project. They
are validated by proving nothing changed.

| Test | Asserts | Oracle |
|---|---|---|
| `test_parser_output_snapshot` | `parse_items` / `parse_augments` / `parse_filigrees` produce **byte-identical** output before and after extraction | A golden snapshot captured on the pre-refactor commit |
| `test_existing_suite_unchanged` | All **171** Python tests on `main` pass, with no test edited as part of the refactor | The suite itself |

**Procedure — capture the snapshot first, on the current commit:**

1. Run each parser across the **entire** corpus under a fixed set of
   representative restriction combinations (endgame default; ML-unbounded;
   armor-restricted; each weapon style; excluded-packs; owned-restricted).
2. Serialize canonically (sorted keys, sorted lists) and check the digests in.
3. After the refactor, regenerate and compare.

> **A diff here is a failure, not a finding.** If extraction changes output, the
> extraction was not pure. Slowness is acceptable: run the full corpus, not a
> sample.

---

## 14. Category C — differential correctness (proposal steps 3–4)

The oracle suite. **Written before any unit test of `recalculate`.**

### 14.1 Against real saved gearsets

> [!WARNING]
> **`*.ddogearset` is gitignored — the oracle is not in the repository.** A
> fresh clone of `main` has no fixtures and this entire section is inert.
> Checking a representative set in (with a `.gitignore` negation) is a
> **prerequisite for step 3**, not a nicety. See START_HERE §3.

| Test | Asserts |
|---|---|
| `test_recalculate_matches_saved_results` | For every `.ddogearset` in the corpus, `recalculate` reproduces the file's own `realizedStats`, `activeSets` and `allEffects` |

Known-divergence handling: some saved files predate solver bug fixes (0.4.2
school saves, 0.4.3 skill groups, 0.4.4 hireling). Those must be recorded as
**named, justified exceptions** with the expected delta:

```yaml
- file: why_CasterDualCaster_*.ddogearset
  saved_app_version: "0.4.3"
  expected_deltas:
    prr:  { saved: 67, expected: 47, reason: "0.4.4 hireling guard — HirelingPRR is not the player's PRR" }
    mrr:  { saved: 61, expected: 41, reason: "0.4.4 hireling guard" }
```

> An unexplained delta fails. An explained one is a regression test for the fix
> that caused it. This turns stale fixtures from a nuisance into an asset.

### 14.2 Against the live solver (property-based, slow by design)

| Test | Asserts |
|---|---|
| `test_recalculate_agrees_with_solver_on_generated_gearsets` | For N randomly generated **valid** gearsets, `recalculate` and a full solve of the same pinned gearset produce identical totals |

- Generation: sample real items per slot, real augments per compatible colour,
  real filigrees; vary priority lists including bonus-type-qualified ones,
  capped priorities, skill priorities and hireling priorities.
- This is the **only** test that exercises naming, stacking and set counting
  together against an independent implementation. It is slow. Run the full N
  nightly, a smaller N per commit.

### 14.3 Restriction-independence — the `<important>` requirement

The proposal's central claim needs its own test, because it is the thing most
likely to regress silently.

| Test | Asserts |
|---|---|
| `test_recalculate_ignores_search_restrictions` | The same gearset recalculates to **identical** totals regardless of `max_level`, `armor_restriction`, `weapon_style`, `excluded_packs`, `owned_item_names`, `raid_item_limit`, `min_ml` |
| `test_recalculate_rejects_restriction_keys` | A payload containing any restriction key is **rejected with a clear error**, not silently filtered |
| `test_recalculate_evaluates_deliberately_illegal_gearsets` | A gearset that the solver would refuse still evaluates: two minor artifacts; a raid item over the cap; ML-1 items at cap 34; heavy armor under a Light restriction; items from excluded packs; items not owned |

The third is the direct regression test for *"could not be evaluated; some
locked items may be incompatible"*. It must produce **numbers plus warnings**,
never a failure.

### 14.4 Physical rules are warnings, not failures

| Test | Asserts |
|---|---|
| `test_physical_violations_warn_and_still_total` | Duplicate filigree names, over-count filigrees, two minor artifacts, an augment in an incompatible colour → totals returned **and** a `warnings` entry |
| `test_warning_is_specific` | Each warning names the offending slot/item, not a generic message |

---

## 15. Category D — boundary contracts

Two boundaries, each with its own class of failure.

### 15.1 Python ↔ Go

| Test | Layer | Asserts |
|---|---|---|
| `test_recalculate_response_schema` | Python | The response validates against a checked-in JSON Schema |
| `TestRecalculateResponseUnmarshals` | Go | Go's result struct unmarshals a **real captured Python response** with no field silently dropped |
| `TestPayloadRoundTripsUnchanged` | Go | A gearset marshalled by Go and re-read by Python is identical — catches the multi-`<Item>`-class bug of one side keeping first and the other last |
| `test_schema_is_the_only_contract` | Both | Neither side hardcodes a field name absent from the schema |

> `TestRecalculateResponseUnmarshals` is deliberately fed a **captured** Python
> response, not a Go-constructed one. A Go-built fixture tests Go against
> itself.

### 15.2 Go ↔ Svelte

| Test | Asserts |
|---|---|
| `svelte-check` includes `wailsjs/**` | Generated bindings are type-checked. Already in place; keep it |
| `test_bindings_are_current` | Regenerating produces no diff — a stale binding cannot ship |
| `test_generated_models_parse` | `models.ts` is syntactically valid (the `EnrichedAugment[]` class of codegen bug) |
| `test_no_orphan_bindings` | Every exported Go binding is either used by the frontend or explicitly listed as intentionally unused |

---

## 16. Category E — end-to-end through the real app

**The layer that was missing entirely, and the reason a hang shipped.**

Harness: `wails dev` exposes the real app with real bindings at
`localhost:34115`, drivable from a browser automation client. Every test below
runs against the **real Go backend and real Python subprocess** — no mocks.

| Test | Asserts |
|---|---|
| `e2e_recalculate_from_fresh_gearset` | Equip N items via the UI → Calculate → priority panel shows the expected non-zero values |
| `e2e_recalculate_after_load` | Load a saved gearset → totals match the file's own, or the documented delta |
| `e2e_recalculate_after_editing_solver_output` | Solve → Accept All → change one item → Calculate → totals reflect the change |
| `e2e_never_hangs` | Every user-triggered action settles within a hard timeout; the busy flag is observably cleared afterwards |
| `e2e_repeated_operations` | The same load/calculate cycle **6+ times consecutively** — the failure last time appeared on the *second* iteration |
| `e2e_console_ordering` | Progress lines appear in emission order and end on a terminal line |
| `e2e_bridge_payload_ceiling` | Records the largest payload that reliably round-trips; fails if any production path exceeds it |

> `e2e_repeated_operations` and `e2e_never_hangs` are non-negotiable. A
> single-shot happy path passed throughout the period the app was hanging.

---

## 17. Category F — the regression corpus

Every trap already paid for, as a permanent fixture. These are cheap and must
never be dropped.

| Fixture | Guards |
|---|---|
| Filigree list with an empty-string entry | Corrupted saved data must be skipped, not counted |
| Filigree list with a duplicated name | 9 non-empty vs 8 distinct must not break anything |
| Set with three tier rows at the same piece count | All effects apply; label appears **once** |
| Effect with repeated `<Item>` (Force/Physical/Untyped) | First-wins is deliberate and consistent across stacks |
| Filigree with two `<SetBonus>` entries | Counts toward **both** sets |
| Filigree whose name disagrees with its value | Data wins over the name |
| Item with an embedded Cannith/Slavelord augment | Only `SelectedAugment` applies |
| `reserved_minor_artifact_slot: ""` + `is_dino_artifact: true` | The `" (dino)"` fragment must not reach parsing |
| Gearset with gear only in `result.gearSet` | Solve-then-save is still a real gearset |
| Empty gearset | Loads; recalculates to empty; **never overwrites saved stats** |

---

## 18. Per-step gates

No step starts until the previous step's gate is green.

| Step | Gate |
|---|---|
| **0.** Check the oracle fixtures into the repo | `gearsets/*.ddogearset` preserved and a representative set tracked, each tagged with its `app_version` (§14.1) |
| **1.** Extract per-node extractors | §13 snapshot byte-identical · 171/171 Python · §12.1 registry green |
| **2.** Split rules module (no `pulp`) | §13 still identical · `test_rules_module_does_not_import_pulp` · startup improvement measured and recorded |
| **3.** `resolve_equipped_*` + `recalculate()` | §14.1 all files match or have a justified delta · §14.3 restriction-independence · §14.4 warnings |
| **4.** Differential vs solver | §14.2 green at full N · §17 corpus green |
| **5.** Wire `mode` through Go + Svelte | §15 both boundaries · §16 end-to-end incl. `e2e_repeated_operations` |
| **6.** Warnings surfaced in UI | §14.4 specificity · `e2e` warning visible and non-blocking |

**Continuous, every commit:** §12 (layering), §15.2 (bindings), §17 (corpus).

---

## 19. Would these have caught 0.5.0's failures?

The honest check on this design — every row is a real failure from this session.

| Failure | Caught by | When |
|---|---|---|
| 13/14 priorities read 0 | §14.1 differential vs saved results | Step 3 gate, before any UI work |
| `<Item>` last-vs-first (4261 effects) | §15.1 round-trip + §17 fixture | Continuous |
| Dual-set filigrees lost a membership | §17 fixture | Continuous |
| Wails bridge dropping large payloads | §16 `e2e_repeated_operations` | Step 5 gate |
| Invalid generated `models.ts` | §15.2 `test_generated_models_parse` | Continuous |
| Rules forked into Go | §12.1 `test_no_rule_leaks_outside_owner` | Continuous — *would have blocked the approach on day one* |
| Save-format churn | Not applicable — no derived cache is persisted | By design |
| Optimize → Save wrote empty | §16 `e2e_recalculate_after_editing_solver_output` | Step 5 gate |
| Scrambled console ordering | §16 `e2e_console_ordering` | Step 5 gate |
| Search restrictions blocking evaluation | §14.3 | Step 3 gate |

The last row of §12.1 is the important one: an anti-duplication guard would
have failed the moment `stat_matching.go` was created, which is the single
cheapest way this whole detour could have been avoided.

---

## 20. Where the accepted slowness is spent

| Choice | Cost | Bought |
|---|---|---|
| Differential over the **full** gearset corpus, not a sample | Seconds per run | No blind spots between fixtures |
| Property-based differential at full N nightly | Minutes | Naming × stacking × sets tested together against an independent implementation |
| End-to-end against the **real** stack, no mocks | Slowest suite; needs a built app | The only layer that can catch bridge and integration failures |
| Snapshot over the whole corpus under several restriction sets | Seconds | Proves the refactor is pure |
| Repeat every e2e operation 6+ times | Multiplies e2e runtime | Catches second-iteration failures — exactly how the hang presented |

What is **not** worth paying for: unit tests that restate `recalculate`'s own
arithmetic. The differential suite covers that ground with a real oracle, and
the unit tests would have passed throughout last time.
