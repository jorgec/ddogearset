# 0.5.1 — `app.db` and recalculation

**Status:** shipped. All six phases complete — see [`RETROSPECTIVE_AND_HANDOFF.md`](RETROSPECTIVE_AND_HANDOFF.md).

0.5.0 gave the app a catalog it can trust: stable UUIDs, a schema, and no
runtime dependency on game XML. 0.5.1 spends that. Two features that look
separate are the same feature seen from two sides:

- **`app.db`** — the user's builds, gearsets and run history become storage,
  not a pile of JSON files in the process's working directory.
- **Recalculation** — evaluating a gearset the user already has, without
  running the solver at all.

`gearset_slot(origin)` is where they meet. A build holds an `equipped` gearset
and a `suggested` one; recalculation evaluates `equipped`; the solver proposes
`suggested`; Accept All is one `INSERT … SELECT`.

**Read first:** [`../0.5.0/RETROSPECTIVE_AND_HANDOFF.md`](../0.5.0/RETROSPECTIVE_AND_HANDOFF.md)
§6 (invariants) and §9 (handoff). The `app.db` DDL is already written —
[`../0.5.0/01_CATALOG_AND_APP_SCHEMA.md`](../0.5.0/01_CATALOG_AND_APP_SCHEMA.md)
§5.2 — and this plan does not restate it.

---

## 1. What is already decided

These are settled. 0.5.1 implements them; it does not re-open them.

| Decision | Where | Why it is closed |
|---|---|---|
| A saved gearset references **catalog UUIDs**, with names as reporting tombstones | Schema §5.2, §5.3 | The registry makes UUIDs survive renames — the only reason names were ever safer |
| `.ddogearset` becomes **export/import**, not storage | START_HERE §9.3, schema §8 Q3 | A file can be sent to someone; a database cannot. Keep the feature, move the storage |
| Stacking stays in **`python/rules/`** | Schema §8 Q1 | Naming and stacking are applied together. SQL *could* express the aggregate; that is a property, not a reason to split domain logic across two languages. This is the `CALCULATE_STATS_RETROSPECTIVE.md` lesson |
| `filigree_base` is modelled, **never constrained** | Schema §8 Q2 | `optimizer.py:1817`'s one-per-base-name rule makes a real saved gearset unevaluatable. Settle the rule before building on it — not in this release |
| A recalculation payload **cannot express a search restriction** | START_HERE §9.2 | Restrictions are `WHERE` clauses the recalc query simply never adds. Unrepresentable, not merely unused |
| The two `<SetBonus>` / multi-`<Item>` questions | START_HERE §9.3 | Superseded by `filigree_set` rows and `effect_target.position`. Structural, already shipped |

## 2. What this release must not break

Beyond the 0.5.0 invariants (retrospective §6), three are specific to 0.5.1:

1. **An empty or failed result must never overwrite saved stats.** Carried
   verbatim from the deprecated recalculation spec. The two-node schema makes
   it structural — a failed run writes no `gearset_slot` rows at all — but the
   *run* tables can still be written half-populated. Write them in one
   transaction or not at all.
2. **`mode: "calculate"` stays until `mode: "recalculate"` reproduces the 14
   oracle fixtures.** That is what they were captured for, and once `calculate`
   is gone they cannot be recaptured. Delete it in Phase 5, not before.
3. **`app.db` is precious; `catalog.db` is disposable.** Every migration path
   must be safe to run twice, and no code path may delete or rewrite `app.db`
   to recover from a catalog problem.

## 3. A bug this release inherits and should fix

`SaveGearset` writes to the relative path `"gearsets"` (app.go:1008) — resolved
against the *process working directory*. For a double-clicked macOS `.app` that
is not the user's home, and on a read-only volume it fails outright. It has
been silently working only because the app is launched from the repo during
development.

`userDataDir()` (catalog_seed.go) already resolves the correct per-OS location
and is already used for `catalog.db`. `app.db` goes beside it, and the
`.ddogearset` export directory moves there too. This is not scope creep: 0.5.1
is the release that decides where user data lives.

---

## 4. Phases

Each phase ends green and commits. The gate is a command, not a description.

### Phase 0 — Baseline and the differential harness

Before writing `app.db`: prove the oracle still reproduces on the shipped
catalog, and turn "it reproduces" into a test rather than a script somebody
remembers to run.

What exists today is **not** that. `scripts/check_oracle.sh` only asserts the
14 fixtures are present, complete and internally consistent — it never runs the
solver. `scripts/capture_oracle.py` does replay, but only to *capture*: it has
no compare mode. So "the oracle reproduces" has never actually been executed as
a check; it has only ever been a claim about files on disk.

Phase 0 builds the missing half: replay each fixture's stored payload and
compare against its stored result, as a pytest. That harness is the only thing
that will stand between the old numbers and the new once `calculate` is deleted
in Phase 5, so it is built first and judged on its own.

Expect fixture-level tolerances: `known_deltas.yaml` exists precisely because
some differences were understood and accepted at capture time. Anything not
listed there is a regression.

**Gate:** `pytest python/tests -q` includes the oracle differential and it
actually invokes the solver · all 14 fixtures reproduce against
`bundled/darwin-arm64/catalog.db`, modulo `known_deltas.yaml` · the test fails
loudly (not skips) when the catalog is missing · deliberately breaking one
stored result makes it fail.

### Phase 1 — `app.db`: schema, creation, migration

Write the DDL from schema §5.2. Create `app.db` in `userDataDir()` on first
run, alongside the seeded catalog. `app_meta.schema_version` from the start —
this file is precious and will be migrated for years.

Import existing `.ddogearset` files: **explicit, non-destructive, idempotent.**
The files stay where they are; import copies them in and can be re-run without
duplicating. Name-to-UUID resolution happens here, against `catalog.db`, and an
unresolvable name is reported per-item rather than failing the import — that is
what `item_name` tombstones are for.

**Gate:** `app.db` is created on first run and survives a restart · importing
the same file twice produces one build, not two · a `.ddogearset` naming an
item absent from the catalog imports with a reported orphan and no crash · a
Go test drives create → import → read back.

### Phase 2 — Builds and gearsets move to `app.db`

The `build`, `build_priority`, `build_excluded_pack`, `build_caster_option`,
`owned_item` and `gearset_*` tables become the app's working storage. The
frontend's load path reads `app.db`; `SaveGearset` writes it.

`.ddogearset` becomes **Export** and **Import** — same format, same checksum
(`gearset_checksum.go` is unchanged), no longer the source of truth. The
existing file-picker load becomes Import.

**Gate:** create → edit → restart → the build is still there · Export produces
a file byte-comparable with what 0.5.0 would have written for the same build ·
Export → Import round-trips to identical rows · the export directory is under
`userDataDir()`, and nothing writes to the process working directory (§3).

### Phase 3 — The two-node model

`origin ∈ ('equipped','suggested')` becomes real: the solver writes
`suggested`, the editor edits `equipped`, and Accept All is the one
`INSERT OR REPLACE … SELECT` from schema §5.4.

**Gate:** *"Optimize → Save wrote an empty gearset"* is unreproducible by
construction · Accept All is a single statement in one transaction · a failed
optimize leaves `equipped` untouched.

### Phase 4 — `mode: "recalculate"`

The point of the release. `resolve_equipped_items` becomes
`WHERE name IN (...)` against `catalog.db` — no glob, no XML, no candidate
pool, no ILP. `_collect_contributions` and `_resolve_totals` already evaluate a
fixed gearset by direct arithmetic; this is a thin entry point over code that
exists.

Carried from the deprecated spec (START_HERE §9.2): `realizedStats`
(priority-spelled) plus `otherStats` (everything else); structured `allEffects`
objects with `parseEffectSource` deleted; `validate_physical_rules()` **warns,
never refuses**.

The payload type must make a search restriction unrepresentable, and reject one
if sent anyway.

**Gate:** all 14 oracle fixtures reproduce through `recalculate` — the Phase 0
harness, unchanged · recalculation of a full gearset completes in well under a
second (no solver, no ILP) · a payload carrying a restriction is rejected with
a clear error · `validate_physical_rules()` warns on the known
one-filigree-per-base-name gearset and still returns numbers.

### Phase 5 — Retire `mode: "calculate"`

Only now. Delete the mode, its ILP-shaped tests, and `parseEffectSource`;
rewrite the three behavioural tests against `recalculate` (START_HERE §9.2,
decision 3). Wire the Calculate button to the new mode.

**Gate:** `calculate` appears nowhere in `python/solver.py` or the frontend ·
the oracle differential still passes (now the only thing standing between the
old numbers and the new) · full suite green.

### Phase 6 — Run history

`run`, `run_stat`, `run_effect`, `run_active_set`, `run_warning`. Written in
one transaction per invariant §2.1. `run.catalog_commit` records which catalog
produced the numbers, which is what makes a stale result explainable after a
catalog update.

**Gate:** a failed run writes a `run` row with `succeeded = 0` and an error
message, and **no** stat rows · `run_active_set`'s primary key deduplicates a
set with three tier rows at two pieces, with no application-side dedup ·
history survives a restart.

---

## 5. Sequencing note

Phases 1–3 are storage; 4–5 are the feature; 6 is history. If the release needs
to be cut short, **1–4 is a coherent shipping point** — builds persist properly
and recalculation works — with 5 and 6 following. Cutting after 3 is not: it
moves storage without delivering the feature that justified moving it.

## 5b. Shipped — see the retrospective

0.5.1 is complete. What the work cost, what the differential caught, the two
places the specified schema turned out to be wrong, and the handoff into 0.5.2
are in [`RETROSPECTIVE_AND_HANDOFF.md`](RETROSPECTIVE_AND_HANDOFF.md). Read that
before starting 0.5.2; this document is the plan, not the outcome.

---

## 6. Explicitly out of scope

- **UI/UX implications — 0.5.2.** [`../0.5.0/UI_CHANGES_0_5_0.md`](../0.5.0/UI_CHANGES_0_5_0.md)
  is input to that release. 0.5.1 changes what the buttons *do*, not how the
  app looks.
- **The catalog-update feature.** `catalog_meta` carries everything it needs
  (schema §5.1.2) and `app.db`'s UUID references are what make it safe, but
  building it is not this release.
- **The `filigree_base` constraint.** See §1.
- **`item_upgrade` edges.** Still empty, still deliberate.
