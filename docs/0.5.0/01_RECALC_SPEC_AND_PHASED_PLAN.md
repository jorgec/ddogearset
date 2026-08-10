# 0.5.0 — recalculation spec and phased plan

> [!CAUTION]
> **DEPRECATED — superseded by [`00_ETL_START_HERE.md`](00_ETL_START_HERE.md).**
> The project pivoted on 2026-08-10 to a dev-only, build-time ETL producing a
> normalized SQLite catalog. **0.5.0 is the ETL, 0.5.1 is `app.db`, 0.5.2 is
> UI/UX.** The plan below is not the plan.
>
> **The phase plan is void. The contract is not.** Recalculation is scheduled
> for **0.5.1**, and START_HERE §9.2 lists precisely which of this document's
> decisions it inherits (the restriction-free payload, `realizedStats` +
> `otherStats`, structured `allEffects`, warn-never-refuse physical rules) and
> which the ETL supersedes outright (§9.3: dual-`<SetBonus>`, multi-`<Item>`,
> the pre-0.5.0 file refusal).
>
> **Also keep §2's measured findings**, which the pivot does not invalidate:
> PyInstaller `--onefile` costing 3.8 s per invocation, the oracle survey, and
> the `optimizer.py:1817` filigree base-name defect that makes a real saved
> gearset unevaluatable.

**Written:** 2026-08-10, from `main` at `fff94a9`.
**Supersedes for planning purposes:** the "suggested order of work" in
[`RECALCULATION_SEPARATION_PROPOSAL.md`](RECALCULATION_SEPARATION_PROPOSAL.md) §8
and its test-plan scoping (§10–§20). The *design* in that document stands
unchanged; this document re-verifies it against `main`, records what the earlier
documents got wrong or left unmeasured, and turns it into executable phases.

**Read first:** [`00_RECALC_PHASE_START_HERE.md`](00_RECALC_PHASE_START_HERE.md).

---

## 1. Is it still necessary? — yes, and nothing has moved

Every claim in START_HERE §3 was re-verified against the working tree, not
taken on trust.

| Claim in the 0.5.0 docs | Verified | Result |
|---|---|---|
| `main` HEAD `fff94a9`, version `0.4.4` | `git log`, `app.go:51`, `wails.json` | ✅ exact |
| Python suite 171 passing | `pytest python/tests -q` | ✅ **171 passed**, 8.9 s |
| `svelte-check` 0/0/15 | `npm run check` | ✅ **0 errors, 0 warnings, 15 hints** |
| `go build` / `go vet` / `go test` clean | run | ✅ all clean |
| `mode: "calculate"` still live | `solver.py:9`, 14 `calculate_only` refs | ✅ present |
| Calculate button hits the solver | `Summary.svelte:330`, `GearsetEditor.svelte:267` | ✅ both send `mode:'calculate'` |
| `hydrateConfigFromSlots` exists | `store.ts:197` | ✅ present |
| Filigrees live in the config drawer | `App.svelte:28,143,155` | ✅ `drawerSection: 'config'\|'filigrees'` |
| `GetSystemLogs` returns `a.logs` directly | `app.go:775` | ✅ unbounded, no mutex, no copy |
| `tsconfig.json` excludes `wailsjs/` | `frontend/tsconfig.json` | ✅ `include` is `src/**` only |
| `XMLBuff.Item` / `XMLEffect.Item` single strings | `models.go:42,60` | ✅ still `string` |
| No `PYTHONUNBUFFERED` in `runSolver` | `app.go:656` | ✅ absent |
| None of the UI work exists | `ls frontend/src/lib` | ✅ no `Suggestions.svelte`, no `services/progressLog.ts`, no `services/wailsCall.ts` |
| `_collect_contributions` / `_resolve_totals` are pure | `optimizer.py:2586,2624` | ✅ no pulp, no GLPK |
| `parse_sets` takes no restrictions | `optimizer.py:976` | ✅ |

**Conclusion: the entire 0.5.0 body of work is still outstanding, and the
proposal's central design — cut between the search and the domain rules, inside
Python — survives inspection.** `_collect_contributions` really does count set
pieces from items + filigrees exactly the way `reconcile_solution` recomputes
`w_vars` (`optimizer.py:2538–2553` vs `2606–2620`), so the two paths agree by
construction, not by coincidence.

---

## 2. What the earlier documents got wrong or never measured

Seven findings that change the plan. Each is measured, not argued.
§2.6 was found during implementation, not review.

### 2.1 The subprocess costs 3.8 seconds, not 300 ms — and it is fixable

The proposal (§6) budgeted recalculation at "comfortably under one second" and
flagged PyInstaller's unpack as "the one number that could change the
conclusion". It does.

| Configuration | First run | Warm runs |
|---|---|---|
| **Shipped bundle** (`bundled/darwin-arm64/solver`, `--onefile` + UPX) | **8.93 s** | **3.80 / 3.80 / 3.85 s** |
| Same code, `--onedir` build | 5.03 s (Gatekeeper scan) | **0.12 / 0.11 / 0.11 s** |

`solver.spec` builds a UPX-compressed one-file archive, so **every invocation**
re-extracts ~8 MB to a temp directory before a single line of Python runs. That
is a fixed ~3.8 s tax on the Calculate button, invisible today only because it
is hiding inside a 40–60 s solve.

Meanwhile the interpreter itself is cheap on this machine — `import pulp` is
60–80 ms (the proposal measured 172 ms), `import optimizer` 44 ms. **The
proposal's argument that recalculation should avoid `pulp` is correct for
layering reasons but worth ~70 ms, not 172 ms. The packaging change is worth
3.7 s.** Do not confuse the two.

`--onedir` is a contained change: `extractSolver` (`app.go:334`) already walks
the embedded bundle and writes every file to a temp dir — it just `continue`s on
directories, so it needs to recurse for `_internal/`. See Phase 5.

### 2.2 The oracle is far thinner than §14.1 assumes

START_HERE treats `gearsets/*.ddogearset` as the differential oracle. Surveyed,
all 14 files:

| Save format | app_version | Count | Usable as oracle? |
|---|---|---|---|
| v1.2 | 0.4.1 / 0.4.2 / 0.4.3 ×2 / 0.4.4 | **5** | Yes — real solver output |
| v1.3 | 0.5.0 | **9** | **No** — produced by the discarded Go implementation |

So the oracle is **5 files, of which exactly one (0.4.4) is delta-free.** The
other four predate the school-save (0.4.2), skill-group (0.4.3) and hireling
(0.4.4) fixes, so all four need §14.1's justified-delta machinery before they
assert anything.

The nine v1.3 files carry `enriched_gear` and `realizedStats` computed by the
approach the retrospective exists to reject. **Their stored stats must be
excluded by an explicit rule keyed on `version == "1.2"`, not by hand-picking
filenames.** Their *gear names*, however, are perfectly real.

**Consequence for the plan:** manufacturing oracle is a Phase 0 task, and it can
only be done **before** `mode: "calculate"` is removed. Feeding all 14 files'
gear back through today's implementation turns a corpus of one trustworthy
reference into fourteen — including the nine otherwise-useless v1.3 files. That
opportunity does not come back.

### 2.3 The output is built from pulp variables, not from the contributions

The proposal's §5.2 flow ends `return { realizedStats, allEffects, activeSets,
slots, warnings }` as though those fall out of `_resolve_totals`. They do not.
Every one of them is assembled from model state (`optimizer.py:3133–3280`):

| Output key | Built from |
|---|---|
| `realizedStats` | `model.z` variables, filtered to `entries` (priorities only) |
| `activeSets` | `model.w_vars` |
| `slots` | `model.x`, `model.y`, `model.fw`/`fm`, `model.w_vars` |
| `allEffects` | `model.sources_tracking` — **per-source names**, e.g. `"12.0 Insightful (Legendary Bracers of …)"` |

`_collect_contributions` records origins only as the coarse strings
`'item'`/`'augment'`/`'filigree'`/`'set'`. It cannot produce `allEffects` as it
stands.

**This is the largest genuinely-new piece of work in the project and neither
earlier document scopes it.** It needs a `_collect_contributions` variant that
carries the source name alongside the value, plus an assembler that renders the
four keys from equipped gear + contributions. It is presentation assembly, not
domain rules — but it is not free, and it is where a silent shape mismatch with
the Vellum Summary would hide.

### 2.4 Extraction is not purely a candidacy split

Proposal §4 frames the refactor as "same extraction, two candidacy rules". It is
not quite: `normalize_stat_name` is called **inside** the extraction loop
(`optimizer.py:907`), and the very next line drops anything it doesn't match:

```python
stat = normalize_stat_name(b_type, b_item, b_desc, priorities, bonus_type=b_bonus)
if stat and b_val and b_bonus:
    buffs.append(...)
```

§5.3 requires recalculation to **report every stat the gear grants**, including
unprioritised ones. That is a change to *extraction*, not to candidacy — the
extractor needs an explicit `keep_unmatched` behaviour that falls back to the
raw `Type`/`Item` name instead of dropping the buff.

**Therefore the §13 byte-identical snapshot test is only valid with
`keep_unmatched` off.** Say so in the test, or the refactor's purity proof
quietly stops proving anything the moment the flag is introduced.

### 2.5 Python has the dual-`<SetBonus>` bug too

START_HERE §4.1 presents multi-`<SetBonus>` as a Go-side defect. It is also a
Python one: `parse_filigrees` does `set_bonus = f_node.findtext('SetBonus')`
(`optimizer.py:1173`) and stores a single `f['set']`, which both
`create_model` (`optimizer.py:1854`) and `_collect_contributions`
(`optimizer.py:2612`) compare with `==`. A filigree belonging to two named sets
counts toward only the first.

**Fixing it changes solver output.** It therefore cannot ride along inside the
"prove nothing changed" refactor, and it cannot land before the differential
baseline exists — it would invalidate the oracle it is being measured against.
It gets its own phase, after Phase 4, with a deliberate re-baseline.

Same reasoning applies to any decision to credit multi-`<Item>` effects to all
targets rather than the first: **that is a behaviour change, not a bug fix, and
it is out of scope for 0.5.0 unless explicitly chosen.** The Go-side `Item
string` → `[]string` correction is different — Go only *displays* it, so fixing
it changes no numbers.

### 2.6 A filigree base-name rule makes real gearsets unevaluatable

*Found during Phase 0, by replaying every saved gearset through today's
`calculate` mode.* One of the 14 — `Test_CasterDualCaster_20260809055408`, a
v1.2/0.4.3 file — comes back as **"The supplied gearset could not be evaluated;
some locked items may be incompatible with each other."**

Bisected to `optimizer.py:1817`:

```python
for base_name, idx_list in base_name_groups.items():
    if len(idx_list) > 1:
        prob += pulp.lpSum([fw[idx] for idx in idx_list]) <= 1
        prob += pulp.lpSum([fm[idx] for idx in idx_list]) <= 1
```

At most one filigree per `base_name` per bucket. This gearset equips **two
"Lunar Magic" variants in both the weapon and the artifact bucket**, so the
model is unsatisfiable before it solves anything. Confirmed by bisection:
removing either bucket alone still fails (both collide independently); removing
all filigrees succeeds; any artifact subset containing one Lunar Magic succeeds.

The same file also carries **every other hazard the earlier documents predicted,
simultaneously**: an empty-string filigree entry, a duplicated filigree name
(9 non-empty weapon entries, 8 distinct), the `" (dino)"` fragment, and three
live search restrictions. It is the single most valuable fixture in the corpus.

Two things follow:

- **For 0.5.0:** this is a search heuristic — a statement about what the solver
  may *propose* — reaching into the evaluation of gear the user already owns. It
  is exactly the defect class the phase exists to remove, and under
  `recalculate` it disappears by construction. Phase 4 asserts this file returns
  numbers plus warnings.
- **Out of scope, but worth raising:** the rule may be wrong for the *search*
  too. Two filigrees sharing a base name are two pieces of the same named set,
  and set bonuses require several pieces — so `<= 1 per base_name` may be
  suppressing legitimate solutions. Not touched here; recorded in
  `known_deltas.yaml` under `out_of_scope_question`.

### 2.7 There is no CI

`.github/` has Dockerfiles and copilot instructions; there are no workflows. The
proposal's "runs on every commit" and "full N nightly" describe automation that
does not exist. **0.5.0 adds a minimal workflow** (Phase 7) so the cheap suites
genuinely are continuous; the slow differential stays a **named script a human
runs**, and each phase says which.

---

## 3. The specification

This is the contract. Everything in §4 exists to deliver it.

### 3.1 Modes

`VALID_MODES` becomes `("optimize", "recalculate", "alternatives",
"stat_search")`. `"calculate"` is **removed**, not aliased — a stale caller must
fail loudly (proposal §5.1). `normalize_mode`'s legacy `calculate_only`
acceptance is removed with it.

### 3.2 Request

```jsonc
{
  "mode": "recalculate",
  "stat_priorities":      [ { "stat": "force spellpower", "tier": 1 }, … ],
  "pre_equipped":         { "Helmet": "…", "Weapon1": "…" },
  "pre_filled_augments":  { "Helmet": { "Sun": "…" } },
  "pre_filled_filigrees": { "weapon": [ "…" ], "artifact": [ "…" ] },
  "minor_artifact_filigree_slots": 4   // warning thresholds only, never a filter
}
```

**Rejected with an error** if the payload carries any of: `max_level`,
`min_ml`, `armor_restriction`, `weapon_style`, `offhand_style`,
`weapon_damage_type`, `swashbuckling`, `runearm_use`, `excluded_packs`,
`owned_item_names`, `raid_item_limit`, `exclude_gem_of_many_facets`,
`reserved_minor_artifact_slot`, `is_dino_artifact`,
`caster_restrict_weapon_families`. Rejection, not silent dropping — this is the
load-bearing decision of the whole design.

`stat_priorities` is **naming only**. It must never filter the result.

> Go's `RunOptimization` takes a typed `OptimizationPayload` carrying every one
> of those fields, so the frontend cannot reach this mode through it. A new
> binding — `RecalculateGearset(payload RecalcPayload) (ResultPayload, error)`
> with its own narrow struct — is mandatory, not cosmetic. A `RecalcPayload`
> that physically has no `MaxLevel` field is what makes "cannot express a
> restriction" true in Go as well as in Python.

### 3.3 Response

| Key | Content |
|---|---|
| `realizedStats` | The user's **priorities**, under the priority's own spelling. Unchanged meaning — the Optimized Priority Targets panel keeps its contract |
| `otherStats` | **New.** Every stat the gear grants that no priority claims, keyed `"<item> <type>"` lowercased (`"force spellpower"`) so it matches how a priority would spell it |
| `allEffects` | **Shape change.** Per-stat list of `{"value": 12.0, "bonusType": "Insightful", "source": "Legendary Bracers of …"}` objects, replacing today's `"12.0 Insightful (Legendary Bracers of …)"` strings |
| `activeSets` | `"<Set> (N-piece)"`, **deduplicated** — one real set has three tier rows at 2 pieces |
| `slots` | Per-slot item / augments / filigrees / set contributions, same shape as `optimizer.py:3239` |
| `filigrees` | `{weapon: [...], artifact: [...]}` as resolved |
| `warnings` | **New.** Physical-rule observations (§3.5) |
| `tierScores`, `tierReport` | `{}` / minimal — parity with today's calculate mode, which already returns empty |

**Payload cost, measured on all 13 real gearsets with results** (§7 review item
1): the full result payload is **10–18 KB**; `allEffects` is 1.9–3.4 KB of it and
grows to 3.1–5.4 KB structured (+56–68% on that key, **+2 KB on the whole
response**). Real gearsets carry **36–57 effects**, not hundreds. The measured
bridge cliff is 64 KB *arguments* at concurrency 40 — this response is ~20 KB
and travels the other way. `otherStats` adds little: the 14 items of a full
caster gearset expose **34 `<Buff>` nodes total**, 12 of which are already
reported, so the new key is tens of entries and ~1–2 KB.

> **The `allEffects` shape change is not confined to recalculation.** The solve
> path builds the same key from `model.sources_tracking` (`optimizer.py:3263`),
> and `Summary.svelte:91` regex-parses the strings back apart in
> `parseEffectSource` to build the duplicate-stats panel. Two shapes for one key
> would be worse than either, so **the solve path changes with it**, in the same
> release: `optimizer.py`'s assembler, Go's `ResultPayload`, and
> `parseEffectSource` (deleted, along with the regex). This is a scope increase
> over the proposal's "the frontend contract does not change shape" — accepted
> deliberately, because §7 makes pre-0.5.0 files unreadable anyway, and because
> it removes the last piece of domain-shaped string parsing from Svelte.

### 3.3.1 Save format

Bumps to **`version: "2.0"`**. `enriched_gear` is not reintroduced; nothing
derived is persisted.

### 3.4 It cannot fail to evaluate

No model, no variables, no GLPK — including no `resolve_glpsol_path()` gate,
which `solver.py:467` currently applies to *every* mode and would abort
recalculation on a machine with a broken glpsol for no reason.

An empty gearset returns empty totals and **must never overwrite saved stats**
on the caller's side.

### 3.5 Physical rules warn, never refuse

Computed unconditionally, reported in `warnings`, each naming the offending
slot or item:

- two minor artifacts equipped
- more filigrees than slots (weapon or artifact)
- duplicate filigree names in one list (de-duplicated, then warned)
- empty-string filigree entries (skipped silently — corrupted data, not user error)
- an augment in a colour the item does not offer
- a name that resolves to nothing in the catalog

> **This is net-new code, not a reporting tweak** (§7 review item 2). These
> constraints currently exist only as ILP rows in `create_model`; bypassing the
> model means writing the checks. They are cheap — each is a loop over resolved
> gear, and `_item_from_node` already extracts the augment-slot colours the
> colour check needs — but they must be written and tested, not assumed.
>
> One constraint drops out for free: **"one item per slot" cannot be violated**,
> because `pre_equipped` is a slot→name map. Do not write a check for it.

### 3.6 Layering

Unchanged from proposal §11. The one clarification worth writing down: **Go and
Svelte may not gain a single new line of stat arithmetic or stat naming in this
project.** If a number is needed on screen, Python returns it. Deleting
`parseEffectSource` (§3.3) moves the codebase toward that, not away from it.

### 3.7 File compatibility — a clean break

**0.5.0 does not read anything saved before it.** No migration, no upgrade path,
no best-effort load.

- Opening a pre-2.0 file **refuses before a single store is written**, with a
  message that names the reason: *"This gearset was saved by an older version
  and can't be opened. Re-create it in 0.5.0."*
- The refusal dialog offers **Export item list** — a one-click plain-text dump
  of the file's equipped item, augment and filigree names (read straight from
  the JSON, nothing interpreted) so the user can re-enter the gearset without
  opening the file by hand. This is the whole of the concession to existing
  users; it is deliberately dumb and cannot half-apply anything.
- Detection is on the **format version**, not on a missing key — an empty
  gearset saved by 0.5.0 is legal and must load.
- The Upgrade button of UI doc §7 is **cancelled**, not deferred. Its
  refuse-don't-migrate *rule* survives as the bullet above.

> The 14 existing `.ddogearset` files stay useful as **test fixtures** — pytest
> reads them as plain JSON and never goes through the app's loader, so the
> refusal does not touch them (§4 Phase 0).

---

## 4. Phases

**0.5.0 is phases 0–7. The UI rebuild (phase 8) ships as 0.5.1.** Gates are
scripts; no phase starts before the previous gate is green. Phases 5 and 7 are
independent of the 1→4 spine and can be run in parallel by a second pair of
hands.

The 0.5.0/0.5.1 line is drawn at *behaviour* versus *layout*. Anything the
recalculation contract forces — the `allEffects` shape, `otherStats`, the
pre-2.0 refusal — ships in 0.5.0 even though it touches Svelte. The three-tab
column, the two-node model and the Accept flow are layout, and wait.

### Phase 0 — Preserve and manufacture the oracle · ✅ **DONE 2026-08-10**

1. ✅ All 14 `.ddogearset` files copied to
   `~/ddo-gearset-oracle-backup-20260810/` (outside the repo; they are
   gitignored by `.gitignore:22` and existed on exactly one machine).
2. ✅ **Simpler than planned — no `.gitignore` negation was needed.** Each
   fixture is a self-contained `*.oracle.json` carrying the replayable payload,
   the fresh capture, *and* the file's own `stored_reference` with a
   `trustworthy` flag derived from `source_version`. Nothing needs the
   `.ddogearset` files at runtime, so no gitignored file type has to be
   un-ignored.
3. ✅ `python/tests/fixtures/known_deltas.yaml` written — `expected_deltas` left
   empty on purpose, to be filled from the **first observed** divergence rather
   than guessed in advance.
4. ✅ `scripts/capture_oracle.py` replayed all 14 through `mode: "calculate"`.
   **Far cheaper than budgeted: ~40 s total, not 10–15 minutes** — calculate mode
   skips every tier stage, so each run is 2–5 s rather than a 40–60 s solve.
5. ✅ Baseline re-verified after the change: **171 Python passing**, `go build` /
   `vet` / `test` clean, working tree otherwise untouched.

**Result: 12 usable 0.4.4 oracle results**, not the 14 hoped for. Two fixtures
legitimately have no result and are more valuable for it:

| Fixture | Why no result |
|---|---|
| `__1___MeleeTwoWeaponFighting_20260810021656` | Genuinely empty gearset — the §17 empty-gearset regression fixture |
| `Test_CasterDualCaster_20260809055408` | **Today's implementation refuses it** — see §2.6 |

The second is the find of the phase. It fails with the exact *"could not be
evaluated"* error the project exists to eliminate, and it carries **every**
hazard class the earlier documents predicted at once: base-name collision,
duplicate filigree name, empty-string entry, the `" (dino)"` fragment, and three
live search restrictions. Its diagnosis is recorded on the fixture and asserted
by the gate.

The corpus covers only `CasterDualCaster` and `MeleeTwoWeaponFighting`. **Known
blind spot:** Tank, Bow/Ranged and Two-Handed Fighting exercise the weapon
base-stat naming path (§15.2) that nothing here touches. Accepted for 0.5.0;
worth authoring fixtures for if Phase 4 turns up anything weapon-shaped.

**Gate:** ✅ `scripts/check_oracle.sh` — 11 checks, all passing. It asserts the
count, that every fixture is version-tagged and replayable, that exactly the two
known result-less fixtures are result-less, that trustworthiness is derived from
`source_version` rather than hand-picked filenames, and that the headline
fixture keeps its diagnosis.

### Phase 1 — Extract per-node extractors · ✅ **DONE 2026-08-10**

Extracted into `optimizer.py`, above their respective parsers:

| Helper | Replaces inline code in |
|---|---|
| `wanted_weapon_stats_for` | `parse_items` |
| `_item_slots_from_node` | `parse_items` |
| `_item_provenance` | `parse_items` (shared by the pack-exclusion check **and** the emitted item) |
| `_item_buffs_from_node` | `parse_items` |
| `_item_from_node` | `parse_items` |
| `_effect_buffs_from_node` | `parse_augments` **and both** `parse_filigrees` loops — three copies of one loop, now one |
| `_augment_from_node` | `parse_augments` |
| `_filigree_from_node` | `parse_filigrees` |
| `_raw_stat_name` | new — the `keep_unmatched` fallback |

**Gate: ✅ 30/30 snapshots byte-identical · ✅ 171/171 Python, no test edited.**

Notes worth keeping:

- **`slots` is passed *into* `_item_from_node`, not derived inside it.** Candidacy
  here does not merely accept or reject — the search *narrows* an item's slot
  list (a khopesh disallowed in Weapon2 keeps Weapon1). Recalculation will pass
  the raw list from `_item_slots_from_node`.
- **The snapshot was proved deterministic before it was trusted**, by re-running
  under a different `PYTHONHASHSEED`. A snapshot that drifts on its own would
  make the whole purity proof worthless.
- **`keep_unmatched=True` is implemented and spot-checked** but unreachable until
  Phase 3; every parser calls with the default `False`, which is what keeps the
  snapshot honest (§2.4).
- The `<SetBonus>` first-wins bug is now marked at its single site in
  `_filigree_from_node`, deliberately unfixed until Phase 7.

#### Phase 1 as originally specified

Split `parse_items` / `parse_augments` / `parse_filigrees` into
`_x_from_node(node, priorities, …, keep_unmatched=False)` plus a candidacy
predicate. Nothing else changes. `parse_sets` is already restriction-free.

**Gate:**
- `test_parser_output_snapshot` byte-identical across the full 8779-file corpus
  under ≥6 restriction combinations (endgame default, ML-unbounded,
  armor-restricted, each weapon style, excluded-packs, owned-restricted),
  captured **before** the change on `fff94a9`.
- 171/171 Python, no test edited.
- Snapshot asserted with `keep_unmatched=False` — see §2.4.

Budget: `parse_items` over the full corpus is **1824 ms** measured, so a
6-combination snapshot run is ~12 s. Cheap. Run it whole, never sampled.

### Phase 2 — `python/rules/`, free of `pulp`

Move the extractors, `normalize_stat_name`, `_collect_contributions`,
`_resolve_totals`, set counting and the stacking rule into `python/rules/`.
`optimizer.py` imports them.

**Gate:** snapshot still identical · 171/171 ·
`test_rules_module_does_not_import_pulp` (transitive) · measured import delta
recorded.

> Honest scoping: this buys ~70 ms, not 172 ms (§2.1). Do it for the layering —
> it is what makes "recalculation cannot inherit a restriction" structurally
> true — and let Phase 5 carry the performance argument.

### Phase 3 — `resolve_equipped_*`, `recalculate()`, and the output assembler

1. `resolve_equipped_items/augments/filigrees` — candidacy is "the user equipped
   it". Text-prescan the `.item` files and XML-parse only those containing a
   wanted name (proposal §6: 285 ms vs 1824 ms).
2. Extend contributions to carry source names (§2.3).
3. **`validate_physical_rules(resolved_gearset) -> [warning]`** — pure Python,
   its own module in `python/rules/`, its own unit tests. Net-new code (§3.5):
   the checks exist today only as ILP rows. Write it before the assembler so
   `warnings` is a real input to it, not an afterthought.
4. Build the §3.3 response assembler: `realizedStats` (priorities), `otherStats`
   (everything else, `"<item> <type>"` lowercased), structured `allEffects`,
   deduplicated `activeSets`, `slots`, `warnings`.
5. **Convert the solve path's `allEffects` to the same structured shape**
   (`optimizer.py:3263`). One shape, both paths, same release.
6. `recalculate()` wiring in `solver.py`, restriction keys rejected, GLPK gate
   skipped.

**Gate:** the fixtures resolve; totals are produced for every fixture; a solve
still round-trips end to end with the new `allEffects` shape. Nothing is
asserted about *correctness* yet — that is Phase 4's job, deliberately.

### Phase 4 — Differential correctness · **before any unit test**

In this order:

1. `test_recalculate_matches_saved_results` against the 14 manufactured 0.4.4
   oracle results (primary, delta-free) and the 5 v1.2 files' stored stats
   (secondary, four needing justified deltas). Every divergence is either a
   match or a named, justified delta. An unexplained delta fails.
2. `test_recalculate_ignores_search_restrictions` — identical totals regardless
   of what a caller *tries* to send.
3. `test_recalculate_rejects_restriction_keys`.
4. `test_recalculate_evaluates_deliberately_illegal_gearsets` — two minor
   artifacts, raid items over the cap, ML-1 items at cap 34, heavy armor under a
   Light restriction, excluded-pack items, unowned items. Numbers **plus**
   warnings, never a failure. This is the direct regression test for *"the
   supplied gearset could not be evaluated"*.
5. The §17 regression corpus as fixtures.
6. Property-based agreement with a live solve — **scoped to N≈10**, run by hand
   once at this gate and recorded, not "full N nightly". A single ILP solve is
   40–60 s. Ten (~10 minutes) is enough to catch a systematic naming, stacking
   or set-counting divergence; a hundred catches the same class of bug an hour
   later. Generation must vary priority shapes: bonus-type-qualified, capped,
   skill, and hireling priorities — those are where the six guards in
   `normalize_stat_name` live.

**Gate:** 1–5 green, 6 run once and its output recorded in this document.

### Phase 5 — Packaging: `--onedir` · *parallelizable, in 0.5.0*

`solver.spec` → `--onedir`; `extractSolver` recurses into `_internal/`;
`build-mac.sh`, `build-windows.ps1`, `build-linux.sh`, `package_release.sh`,
`install.sh` and the `embed_*.go` bundle roots updated.

**Extraction must become cached and version-stamped** (§7 review item 4).
Measured: the onedir bundle is **55 files / 20 MB**, against the current 2 files
/ 7.9 MB. `extractSolver` today writes to a fresh `os.MkdirTemp` on every app
start, so shipping onedir unchanged trades a 3.8 s-per-*call* CPU cost for a
20 MB-per-*launch* disk cost — better, but needlessly so, and unpredictable
under antivirus or on slow drives.

- Extract to a stable per-version path (`<cache>/ddo-solver/<AppVersion>-<hash>/`),
  not a random temp dir.
- Write a `.stamp` file **last**; on startup, if the stamp matches, skip
  extraction entirely and reuse the directory.
- Extraction then happens once per install, not once per launch.
- Note the embedded-bundle size: 20 MB uncompressed inside the Go binary versus
  7.9 MB today. If the binary growth matters, embed a zip and expand it during
  the one-time extraction — the decompression cost is paid per install, not per
  run, which is the whole point of the change.

**Gate:** warm solver start ≤ 0.25 s measured on macOS and Windows · second and
subsequent app launches perform **zero** extraction I/O (assert on the stamp) ·
a full solve still succeeds end to end · release artifacts build on all three
platforms.

Expected result: Calculate goes from ~4.1 s (3.8 startup + 0.3 parse) to
**~0.45 s**.

### Phase 6 — Wire the mode through Go and Svelte

- `RecalculateGearset` binding + `RecalcPayload` (§3.2); `Summary.svelte:330` and
  `GearsetEditor.svelte:267` repointed.
- `mode: "calculate"` and every `calculate_only` reference deleted from
  `optimizer.py` / `solver.py`; `normalize_mode`'s legacy `calculate_only`
  acceptance removed.
- **Calculate-mode tests, split by kind:** rewrite the three behavioural
  regressions against recalculate —
  `test_calculate_only_credits_pre_filled_augment_in_a_colorless_slot`,
  `test_calculate_only_allows_the_same_augment_name_in_two_slots`,
  `test_calculate_only_ignores_raid_item_limit` (each encodes a real reported
  bug). Delete the ILP-mechanics ones —
  `test_ec12_calculate_mode_skips_every_tier_stage` and the
  `normalize_mode({"calculate_only": True})` assertion — they describe stages
  and pinned binaries that no longer exist. Nothing is left failing.
- `PYTHONUNBUFFERED=1` added to `runSolver`'s env (`app.go:656`).
- Save format → `2.0`; the pre-2.0 refusal + **Export item list** (§3.7).
- `Summary.svelte` minimal update only: consume structured `allEffects`, delete
  `parseEffectSource`, surface `warnings`. **`warnings` renders as a plain
  bulleted list or a toast — no layout work** (§7 review item 5). That layout is
  being replaced in 0.5.1; do not invest in fitting anything into it.
  `otherStats` is returned and saved but **not displayed** until 0.5.1.

**Gate:** §15 boundary tests (response schema; Go unmarshals a *captured Python*
response; payload round-trip) · e2e: fresh gearset → Calculate → non-zero
priority panel; load → Calculate; solve → edit → Calculate; **the same cycle 6+
times consecutively**; every action settles within a hard timeout · a pre-2.0
file is refused with no store written, and Export item list produces the right
names · **`e2e_bridge_payload_ceiling`: record the actual recalculate and solve
response sizes and fail if either exceeds 32 KB** — half the measured cliff.
Today's are 10–18 KB (§3.3); this turns "the payload is fine" from an argument
into an assertion.

### Phase 7 — Latent-bug fixes · *parallelizable except where noted*

Safe at any time:

- `GetSystemLogs`: mutex, 2000-line cap, return a copy (`app.go:775`).
- `frontend/tsconfig.json` `include` += `wailsjs/**`; add
  `scripts/generate-bindings.sh` + `scripts/patch_wails_models.mjs` so
  `wails generate module` is never run bare (START_HERE §4.3).
- `XMLBuff.Item` / `XMLEffect.Item` → `[]string` (`models.go:42,60`). Go
  currently keeps the **last** `<Item>` where Python keeps the **first**, so the
  item-detail panel labels a buff `Untyped` while the maths credits `Force`
  (`ItemDetail.svelte:100`, `:764`). This aligns Go to Python's existing
  behaviour — a display fix that moves no number.

  > **Bind the display to `Item[0]`, and only `Item[0]`** (§7 review item 3).
  > The slice exists so Go can know which target is *first*; it is not a licence
  > to render "Force, Physical, Untyped". Showing all three while the maths
  > credits one would be a new lie, and a worse one than today's — so the change
  > is safe **only** with this constraint. Revisit the display when the
  > multi-target investigation (decision 8) concludes; until then display and
  > arithmetic move in lockstep because they read the same element.
- **Minimal CI** (`.github/workflows/`): `go build`/`vet`/`test`, the Python
  suite, `svelte-check`, and the Phase 9 grep. No GLPK, no DDOBuilderV2
  checkout, no solver — fast enough to run on every push. The slow differential
  stays manual.

**After Phase 4's baseline is green, on its own:**

- Python `f['set']` → `f['sets']`, so a filigree in two named sets counts toward
  both (§2.5). **Changes solver output** — affected sets currently fail to reach
  their tier thresholds. Land alone, re-run Phase 4, and record the new numbers
  as the baseline going forward.
- `XMLFiligree.SetName` → `[]string` (the Go *display* half of the same bug) is
  **deferred** — cosmetic, and keeping it out holds the re-baseline to one
  change.

**Not in 0.5.0 — investigate first:** crediting a multi-`<Item>` effect to all
targets instead of the first (4261 effects). Open a separate task to confirm
against in-game behaviour what `Force`/`Physical`/`Untyped` on one effect
actually grants before changing anything. 0.5.0 lands on first-wins.

### Phase 8 — UI rebuild · **0.5.1, not 0.5.0**

Everything in [`UI_CHANGES_0_5_0.md`](UI_CHANGES_0_5_0.md), in its own order:
three-tab left column (all tabs mounted, filigrees single-column
unconditionally) · the two-node model with `hydrateConfigFromSlots` **deleted**
· Accept / Accept All · the Optimize-is-a-no-op and Save-refuses-empty guards ·
Check Inventory (exact, case-sensitive) · `progressLog.ts` + `AddLog` +
`isLoadingFile` lockout · `wailsCall.ts` `withTimeout` · a surface for
`otherStats`, which 0.5.0 returns but does not display · a proper home for
`warnings`, which 0.5.0 renders as a bare list.

**`withTimeout`'s error must be actionable** (§7 review item 6). A timeout fires
because the bridge dropped a message, and a bridge that has dropped one may keep
dropping them — so "Request timed out" leaves the user stuck in a state that
will recur. The message must name the recovery: *"The calculation timed out and
the app's connection may be unstable. Save your gearset and restart the app."*

**§7's Upgrade button is cancelled**, not deferred — §3.7 makes 0.5.0 a clean
break with no migration to perform. Its refuse-don't-migrate rule ships in
0.5.0 as the pre-2.0 refusal.

**Gate:** the §9 build checklist, item by item · e2e console ordering ends on a
terminal line · warnings from §3.5 visible and non-blocking.

### Phase 9 — Anti-duplication guard · **scoped down deliberately**

The proposal's §12.1 three-test YAML rules registry is over-built for this
design: with the domain rules staying in Python, the failure it guards against
(a Go/Svelte reimplementation) is no longer the live risk it was.

Ship instead **one** test — a grep over `*.go` and `frontend/src/**` for a short
list of domain identifiers that must never appear outside `python/rules/`:
`spell focus mastery`, `hireling`, the `stacking`/`mythic`/`reaper` triple,
`piece count`/`pieceCount`, `(N-piece)` label construction, and any `reduce`/`+=`
over `realizedStats` or `allEffects`. It runs in CI (Phase 7).

Plus `test_slot_names_single_source` backed by a shared `data/vocabulary.json`:
the 14-slot list is currently written out in `GearsetEditor.svelte`,
`JobConfigurationForm.svelte` and twice in Python (`optimizer.py:3066`,
`solver.py:394`), and Phase 8 adds a fifth copy unless the shared file lands
first.

---

## 5. Decisions — settled

Recorded so a later reader knows these were chosen, not defaulted into.

| # | Decision | Chosen | Consequence |
|---|---|---|---|
| 1 | `allEffects` shape | **Structured objects**, `parseEffectSource` deleted | Solve path changes too (§3.3); scope increase over the proposal |
| 2 | Unmatched stats | **Separate `otherStats` key** | `realizedStats` keeps its meaning; no existing consumer surprised |
| 3 | Calculate-mode tests | **Split**: rewrite 3 behavioural, delete the ILP ones | Phase 6 |
| 4 | Release scope | **0.5.0 = recalc (0–7), 0.5.1 = UI (8)** | Phase 8 moves out |
| 5 | Pre-0.5.0 files | **Refuse + Export item list** | §3.7; Upgrade button cancelled |
| 6 | `--onedir` packaging | **Inside 0.5.0** | Phase 5; Calculate ~4.1 s → ~0.45 s |
| 7 | Dual-`<SetBonus>` | **Fix after Phase 4 baseline**, Python only | Phase 7, own re-baseline; Go display half deferred |
| 8 | Multi-`<Item>` | **Investigate first** | Out of 0.5.0; separate task |
| 9 | Anti-duplication guard | **One grep test + `vocabulary.json`** | Phase 9 |
| 10 | Live-solver differential | **N≈10, once at the Phase 4 gate** | ~10 min, recorded |
| 11 | CI | **Minimal, during 0.5.0** | Phase 7; cheap suites only |
| 12 | Oracle | **Re-run all 14 through today's calculate** | Phase 0; 14 refs instead of 1 |

## 6. Out of scope for 0.5.0

- Multi-`<Item>` all-target crediting — pending investigation (decision 8).
- `XMLFiligree.SetName` → `[]string` on the Go display side (decision 7).
- The Upgrade button — cancelled outright (decision 5).
- The UI rebuild — 0.5.1 (decision 4).
- Tank / Bow / THF oracle fixtures — known blind spot, Phase 0.
- A Wails v2 → v3 migration — rejected on measurement (§7 review item 1).
- Any stat arithmetic moving to Go or Svelte, in any form.

---

## 7. Review — [`critic.md`](critic.md) adjudicated

Six objections were raised against this plan. Four are adopted, one is adopted
with its conclusion reversed, one is rejected on measurement. Recorded in full
so the rejections are auditable rather than silent.

| # | Objection | Verdict | Where it landed |
|---|---|---|---|
| 1 | Structured `allEffects` inflates the payload toward the 64 KB bridge cliff; upgrade to Wails v3 | **Rejected on measurement** | §3.3, Phase 6 gate |
| 2 | Physical-rule warnings are net-new code, not a reporting change | **Adopted** | §3.5, Phase 3 step 3 |
| 3 | Go `[]string` display + Python first-wins maths = a UI that claims uncredited stats | **Adopted, conclusion reversed** | Phase 7 |
| 4 | `--onedir` trades CPU unpack for per-launch disk I/O | **Adopted** | Phase 5 |
| 5 | Sending `otherStats` a release before anything displays it is waste; warnings in the old layout is a time-sink | **Split: rejected / adopted** | Phase 6 |
| 6 | A `withTimeout` error must tell the user how to recover | **Adopted** | Phase 8 |

**On #1 — rejected.** Measured across all 13 real gearsets carrying results: the
whole response is **10–18 KB**, `allEffects` is 1.9–3.4 KB of it, and the
structured form adds **~2 KB to the response**. Real gearsets carry 36–57
effects, not "hundreds". The measured cliff is 64 KB *arguments* at concurrency
40 (retrospective §2.3), and this is a ~20 KB return value. The objection is
directionally sound discipline applied to a number that isn't there — and
migrating Wails v2.10 → v3 is a whole-app binding and runtime rewrite, which is
a disproportionate remedy for a 2 KB delta. What is adopted instead is the
*discipline*: `e2e_bridge_payload_ceiling` asserts a 32 KB budget, so the claim
stays true by measurement rather than by argument.

**On #3 — adopted, conclusion reversed.** The trap is real: rendering "Force,
Physical, Untyped" while crediting only Force would be a new lie. But the
proposed remedy — leave Go alone until Python's crediting changes — preserves a
*worse* state, because Go today keeps the **last** `<Item>` and labels the buff
`Untyped` while the maths credits `Force`. Display and arithmetic already
disagree; the fix is to bind the display to `Item[0]` so they agree again. The
constraint is adopted verbatim, the deferral is not.

**On #5 — split.** Withholding `otherStats` from the wire for a release is
rejected: it costs ~1–2 KB (the 14 items of a full caster gearset expose 34
`<Buff>` nodes total, 12 already reported), Phase 4's differential asserts on
it, and omitting it means changing the wire contract **twice** — which is the
save-format churn the retrospective §2.4 exists to warn about. The second half
is adopted outright: `warnings` renders as a plain list or toast in 0.5.0, with
no attempt to fit it into a layout that 0.5.1 replaces.

---

## 8. Standing constraints

- Commit nothing until explicitly told. Standing instruction on this project.
- Never let an empty or failed result overwrite a gearset's saved stats.
- One implementation of every rule. If it exists in Python, Go and Svelte call
  it.
