# 0.5.0 — Retrospective and handoff

**Status:** shipped. Phases 0–7 complete on `major/0.5.0`, 13 commits, working
tree clean, unpushed.

This document is two things. The first half is the **retrospective**: what
0.5.0 actually changed, what it cost, and — the part worth your time — what
went wrong and what that taught us. The second half is the **handoff**: what
somebody starting 0.5.1 cold needs to know, including the invariants that will
break silently if violated.

The plan itself lives in [`00_ETL_START_HERE.md`](00_ETL_START_HERE.md); the
schema in [`01_CATALOG_AND_APP_SCHEMA.md`](01_CATALOG_AND_APP_SCHEMA.md). This
document does not restate them. It records what only doing the work could
reveal.

---

## 1. What changed, in one paragraph

The app used to read DDOBuilderV2's XML at runtime — 9,070 files, walked by
both Go and Python on every launch, fetched over HTTPS on first run if absent.
It now reads a single SQLite file, `catalog.db`, built on a developer machine
by an ETL that never ships. Nothing in the shipped app parses game XML, touches
the network, or knows DDOBuilderV2 exists.

## 2. The numbers

| | Before | After |
|---|---|---|
| Runtime game-data dependency | 9,070 XML files, fetched if absent | one 58 MB `catalog.db`, shipped |
| Network on first run | HTTPS fetch of ~80 MB | none |
| Solver invocation (warm) | 3.83 s | **0.07 s** |
| Solver invocation (cold) | 10.14 s | 5.85 s |
| Full release build | — | 56 s cold, 25 s warm (ETL is 7 s of it) |

`catalog.db` (18 tables, `PRAGMA integrity_check` and `foreign_key_check` clean
on every build):

| | | | |
|---|---:|---|---:|
| `item` | 8,474 | `effect` | 44,314 |
| `item_family` | 6,237 | `effect_target` | 44,314 |
| `augment` | 2,237 | `item_augment_slot` | 13,415 |
| `filigree` | 437 | `item_slot` | 10,589 |
| `filigree_base` | 87 | `item_set` | 2,015 |
| `gear_set` | 331 | `filigree_set` | 460 |
| `set_tier` | 531 | `quest` | 569 |
| `stat` | 473 | `item_upgrade` | 0 *(deliberate — §7)* |

Code: 78 files changed, +23,016 / −2,222 (excluding binaries, the identity
registry and generated bindings). `etl/` is 2,206 lines, `python/rules/` 1,213.
Deleted outright: `internal/services/parser.go`, `ddobuilder_fetch.go`,
`scripts/update_data.go`, and the "Update External Sources" button.

Tests: 215 pytest (171 inherited + 44 new), 33 Go test functions across 4
packages, 30 parser-snapshot digests, 14 oracle fixtures.

---

## 3. What went wrong

This is the section to read. Everything below was found by *building the gate*,
not by reading the plan — which is the argument for gates that execute rather
than gates that describe.

### 3.1 Transform reconciled renames too late to matter

**The bug.** `reconcile_disappeared` ran *after* the loop that resolved and
emitted rows. So an operator resolving a rename through `aliases.yaml` got:
the registry repointed the NAME at the original UUID, while the catalog kept
the *fresh* UUID `resolve()` had already minted and stamped into every row it
emitted.

**Why it was dangerous.** Nothing failed. The build succeeded, every foreign
key resolved, `PRAGMA foreign_key_check` was clean, and the drift report said
the rename was handled. The registry's one promise — *once minted, a UUID never
changes* — was broken silently, and the only symptom would have appeared in
0.5.1, as saved gearsets that stopped resolving after an upstream rename.

**The fix, and the general lesson.** Every kind now reconciles *before* it
resolves. More importantly, `reconcile_disappeared` **raises** if called the
other way round. The ordering was previously a fact about how the code happened
to be arranged; it is now an invariant the code refuses to violate. When a
correctness property depends on call order, encode the order — a comment saying
"call this first" is not a mechanism.

### 3.2 The known augment collision made the catalog unbuildable

DDOBuilderV2 ships two augments named `Twilight` with colour
`Cannith Armor Prefix` that differ only in bonus type. Phase 2 correctly
refused to merge them and recorded a **validation error**. Phase 3's Load
refuses to write when any validation error exists.

Which means the catalogs committed in Phases 3–6 could not have been produced
by the pipeline as written — and they weren't. They came from an ad-hoc script
that bypassed the guard. Nobody noticed for four phases, because the ad-hoc
script's output was correct and the gates all passed.

**The fix.** Source-data ambiguity is its own channel now
(`TransformResult.data_ambiguities`): reported on every run, carried into the
drift report, and never fatal. `validation_errors` means referential integrity
and nothing else. The distinction that was missing: *a permanent property of
upstream data is not a defect in this pipeline*, and no release should wait on
Maetrim editing a file.

**The process lesson is the sharper one.** A verification step that is
convenient to bypass will get bypassed, and the bypass will not be recorded.
The tell was available the whole time — the CLI was the first thing to run the
real pipeline end to end, and it failed on the first try.

### 3.3 `content_hash` hashed the diagnostics

It walked every list attribute on `TransformResult`, which swept in
`validation_errors` — and would have swept in `data_ambiguities`. So rewording
a warning message changed the answer to "did the data change?", which is
exactly what `--catalog-version` keys off. Load's inserts and the hash now run
off one shared `TABLES` list, so they cannot disagree about what "the catalog's
content" means.

### 3.4 Rename targets could steal a live identity

An alias pointing at a name that already belonged to another entity would
**delete that entity** and hand its UUID to the renamed one. Reachable by a
plausible typo. Candidates are now restricted to keys the registry has never
seen, and an occupied target is a conflict — fatal in both strict and permissive
mode, because it is the operator's file being wrong, not the data moving.

### 3.5 There were two copies of DDOBuilderV2, and the ETL read the wrong one

`data/ddobuilder` has been a pinned submodule since the *initial commit*. The
ETL was reading the gitignored `DDOBuilderV2/` directory that the (now deleted)
runtime fetch used to create. Byte-identical content — same 9,070 files, same
digest — but only the submodule is pinned, so `ddobuilder_commit` was recording
a content-digest fallback instead of the real upstream SHA that was sitting
right there.

Found by measuring repository size, not by looking for it. Worth noting how
long it survived: `_source_fingerprint` was written with a careful comment about
`git -C` walking up to the enclosing repository — the trap was understood, and
the answer to it was still missed.

### 3.6 Smaller ones, recorded so they are not rediscovered

- **`glob.glob` order is machine-dependent**, and file order decides which of
  two colliding entries survives. Every corpus glob is `sorted()` now.
- **`go:embed` reads the filesystem, not git.** SQLite WAL sidecars and the
  solver's progress log were sitting in `bundled/<platform>/`, gitignored,
  being compiled into the shipped binary. The build scripts clear them now.
- **`if ! cmd; then status=$?` reads the status of the negation**, not the
  command. The ETL's exit code is load-bearing (2 = unresolved drift), so the
  build scripts use `cmd || status=$?`.
- **PowerShell's `-Include` is silently ignored on a plain directory path.**
  Needs `"$dir\*"` or `-Recurse`, or it matches nothing and reports success.
- **`os.UserConfigDir()` is wrong on Linux** for data (`~/.config`, not
  `~/.local/share`). Linux gets its own branch in `userDataDir()`.
- **Go test caching hides behaviour.** A cache-hit test appeared to reseed on
  every run; `-count=1` showed the logic had been right all along. Use it when
  testing anything stateful.

---

## 4. What went right, and why

**The parser snapshot was the whole safety net.** 30 canonical digests over the
full corpus under 9 restriction combinations, byte-identical through every
refactor — through extracting `python/rules/`, through Python switching to SQL,
through Go switching to SQL, through deleting the XML parser. Nothing else
would have caught a silent numeric change across a rewrite this size. It cost
one afternoon in Phase 0 and paid for itself in Phase 1.

**`raw_xml` avoided reimplementing the display model.** Go needs far more
fields for the item-detail panel than the solver needs. Rather than model them
all, each catalog row carries the verbatim XML element, and Go unmarshals it
into the structs it already had. The structured columns stay solver-shaped and
small. This was a mid-flight decision (Phase 5) and it removed an entire
workstream.

**Deterministic-by-construction beat deterministic-by-testing.** UUIDs are
minted once from a checked-in registry; two rebuilds produce a byte-identical
registry and identical row content. `built_at` is truncated to midnight UTC
specifically so a same-day rebuild diffs to nothing.

**Refusing to guess.** "Clean derivation" is three narrow rules, and everything
else stops the build and asks a human. That is why §3.1 was a *latent* bug and
not a shipped one: unresolved drift never silently resolved itself.

---

## 5. Architecture as it now stands

```
data/ddobuilder/            git submodule, pinned (2.0.0.83) — the ETL's ONLY input
        │
        │  python -m etl  (dev machine only, never ships)
        │    walk.py      Extract  — restriction-free corpus walk
        │    transform.py Transform — identity, stat dimension, entity resolution
        │    load.py      Load     — DDL, one transaction, temp file, atomic rename
        │    identity.py + identity_registry.json + aliases.yaml   (UUID stability)
        ▼
bundled/<platform>/catalog.db        committed; go:embed compiles it into the binary
        │
        │  first run: ensureCatalogSeeded()  (catalog_seed.go)
        ▼
<user data>/DDOGearsetOptimizer/catalog.db      ← everything reads THIS
        │
        ├── Go     internal/catalog/  → models.XML* via raw_xml
        └── Python python/catalog_source.py  (DDO_CATALOG_DB)
```

Where things live, and why:

| Concern | Home | Rule |
|---|---|---|
| Domain rules (stacking, naming, matching) | `python/rules/` | Never imports `pulp`. Never knows about search restrictions |
| Search restrictions (ML window, packs, owned) | `python/optimizer.py` | The ETL cannot express one — deliberately |
| Identity | `etl/identity.py` + registry | Mint once. A rename appends to `aka` |
| Display fields | `raw_xml` columns | Go unmarshals; nothing re-models them |
| Priority matching | Python, one layer | See `CALCULATE_STATS_RETROSPECTIVE.md` for what happens otherwise |

---

## 6. Invariants — break these and something fails silently

1. **Reconcile before resolve.** `reconcile_disappeared` raises if you don't;
   do not "fix" that by removing the guard (§3.1).
2. **`python/rules/` never imports `pulp`**, and never gains a restriction
   parameter. If a restriction cannot be expressed, it cannot be silently
   reinstated.
3. **`validation_errors` is referential integrity only.** Source-data ambiguity
   goes in `data_ambiguities`. Conflating them makes releases hostage to
   upstream (§3.2).
4. **Load's `TABLES` list is the single definition of catalog content.** Adding
   a table means one edit there; anything else desynchronises the content hash
   (§3.3).
5. **Save the registry *before* Load**, because `build_catalog` hashes the
   registry file into `identity_registry_hash`. Saving after stamps the catalog
   with the previous registry's hash.
6. **Nothing writes inside the app bundle.** Seeded catalog → user data dir;
   extracted solver → user cache dir. macOS `codesign --verify` is the check.
7. **The parser snapshot must stay byte-identical.** If it moves, you changed a
   number. Re-baseline only with an explicit, understood reason.

---

## 7. Known gaps and unverified claims

Stated plainly rather than buried:

- **Windows is unverified.** `build-windows.ps1` was rewritten and reviewed but
  never executed — no Windows machine. The Phase 7 gate's "warm solver start
  ≤ 0.25 s on macOS **and Windows**" is met on macOS only (0.07 s).
- **Linux is unverified** for the same reason.
- **"Clean checkout builds a release"** was verified from this working tree
  with the submodule present — not from a fresh `git clone --recurse-submodules`
  into an empty directory.
- **`item_upgrade` is created but empty**, by design. `item_family` already
  groups an item with its tier siblings, which is what every 0.5.0/0.5.1 feature
  needs. Adding the directed edges later needs no migration.
- **Derived entity kinds are not reconciled** (`item_family`, `filigree_base`,
  `gear_set`, `set_tier`, `stat`). Their drift is implied by the primary kind's;
  reconciling them too would ask a human the same question three times. If a
  0.5.1 feature starts referencing a `gear_set` UUID from `app.db`, revisit this.
- **One permanent source-data ambiguity** (`Twilight` / Cannith Armor Prefix).
  Reported every run; the first in sorted file order wins.
- **Repository size is ~450 MB** and grows ~80 MB per rebuild (`bundled/`
  carries a 58 MB catalog and a 21 MB solver tree, both required for `go build`).
  `dist/` was untracked in the final commit; its 98 MB of history was
  deliberately left in place. Accepted, explicitly, not overlooked.

---

## 8. Verification recipes

Every gate, re-runnable. `$CATALOG` is any built catalog.

```bash
# The acceptance test. 30 digests, full corpus, 9 restriction combinations.
python/.venv/bin/python scripts/parser_snapshot.py verify-catalog "$CATALOG"

# Python (215) and Go (4 packages) — note -count=1, see §3.6
python/.venv/bin/python -m pytest python/tests -q
go build ./... && go vet ./... && go test -count=1 ./...

# Frontend types, including regenerated Wails bindings
cd frontend && npx svelte-check --threshold error

# Never trust a Python refactor before this
python/.venv/bin/python -m pyflakes etl/*.py python/rules/*.py

# The whole release, end to end (~25 s warm)
./build-mac.sh
```

To exercise the drift workflow without waiting for upstream to rename
something, copy the corpus, edit one `<Name>`, and point `--source` at the
copy — `--strict` should exit 2, write no catalog, and leave the registry
untouched.

---

## 9. Handoff: starting 0.5.1

### 9.1 What is already true

- `catalog.db` exists, is read-only at runtime, and both processes resolve it
  from the same `DDO_CATALOG_DB` convention.
- `mode: "calculate"` **survived 0.5.0 intact**, as §9.1 of the plan required.
  It is still the Calculate button, and it is what the 14 oracle fixtures were
  captured with. It is the differential baseline for `mode: "recalculate"` —
  do not delete it before that baseline is reproduced.
- The user data directory (`<platform data dir>/DDOGearsetOptimizer/`) already
  exists and is created on first run. `app.db` goes beside `catalog.db` there.
- `catalog_meta` carries `catalog_version`, `schema_version` and
  `min_app_version`, so the update story 0.5.1 needs is already versionable.

### 9.2 Why recalculation is now small

`resolve_equipped_items` becomes `WHERE name IN (...)` — no glob, no XML, no
candidate pool, no ILP. `_collect_contributions` and `_resolve_totals` already
evaluate a fixed gearset by direct arithmetic. The work is a thin entry point
plus `app.db`, not a project.

### 9.3 What 0.5.1 inherits, and what it must not re-litigate

Both tables are in [`00_ETL_START_HERE.md`](00_ETL_START_HERE.md) §9.2 and §9.3.
The short version: the recalculation *payload shape* decisions are scheduled,
and three of that plan's decisions are **superseded by the schema** — dual
`<SetBonus>` (now `filigree_set` rows), multi-`<Item>` crediting (now
`effect_target.position`), and pre-0.5.0 file refusal (subsumed by `app.db`'s
migration story, with `.ddogearset` becoming export/import rather than storage).

### 9.4 Traps carried forward

- **`optimizer.py`'s one-filigree-per-`base_name` constraint** makes a real
  saved gearset unevaluatable. `filigree_base` is modelled; no constraint is
  built on it. Settle the rule before adding one.
- **The Wails bridge silently drops payloads above ~64 KB**, and a dropped
  message never settles. Current responses are 10–18 KB. A recalculation
  response carrying full effect provenance could approach the limit.
- **`frontend/tsconfig.json` excludes `wailsjs/`**, so generated bindings are
  never type-checked. A stale binding type-checks clean and misbehaves at
  runtime — this nearly shipped in Phase 5 (`XMLEffect.Item` string → string[]).
  Run `wails generate module` after every Go struct change.
- **An empty or failed result must never overwrite saved stats.** Non-negotiable,
  carried from the deprecated spec.

### 9.5 Suggested first move

Phase 0 of 0.5.1 is not code: it is deciding `app.db`'s schema against the one
question 0.5.0 could not answer — *what does a saved gearset reference?* The
registry guarantees UUID stability, so the answer can be UUIDs rather than
names. That choice determines the migration story for the 14 existing
`.ddogearset` files and everything after it.
