# START HERE — the ETL pivot

**Written:** 2026-08-10.
**Status:** authoritative. **Supersedes every other document in `docs/0.5.0/`.**
**Audience:** whoever picks this up on a **fresh branch from `main`**, with no
memory of the session that produced it.

---

## 1. The decision, in one paragraph

The project stops parsing DDOBuilderV2 XML at runtime. A **dev-only ETL** turns
the XML into a normalized SQLite catalog at **build time**; the shipped app
contains `catalog.db` and nothing else. All three layers read one store, one
identity space, one set of names. The recalculation work that `docs/0.5.0/`
previously described is **deprecated** — not because it was wrong, but because
the ETL makes most of it either free or unnecessary.

---

## 2. Constraints, verbatim

These are requirements, not preferences. Everything in §5–§8 exists to satisfy
them.

1. **The ETL fires on dev, at build time only.** Never at runtime, never on an
   end-user machine.
2. **The shipped app never contains DDOBuilderV2 and never fetches it.**
   Everything the app needs is in `catalog.db`.
3. **The ETL is a separate entity** that does not ship with the executable.
   Dev-only, callable from the build step or standalone.
4. **Renames that cannot be cleanly derived are logged for a human decision**,
   in a form that can be edited to resolve them.
5. **Start clean from `main`** — no artifacts carried from the recalculation
   branch.
6. **Release map:** 0.5.0 = ETL · 0.5.1 = `app.db` (saving/loading)
   **and recalculation** · 0.5.2 = UI/UX implications.
7. **`rules/stacking.py` stays in Python.** Sum-vs-max is business logic, not a
   storage problem, and SQL expressibility is not a reason to move it.

---

## 3. What this deletes

The point of the pivot, stated as subtraction:

| Goes away | Why |
|---|---|
| `ddobuilder_fetch.go`, `ensureDDOBuilderData`, `updateDDOBuilderDataIfStale`, `fetchDDOBuilderData` | The app no longer fetches anything |
| `UpdateExternalSources` binding + its UI | Nothing external to update |
| `internal/services/parser.go` + `enrichment.go` (**444 lines**) | Go reads SQL, not XML |
| `DDO_DATA_PATH`, `solver.py`'s `base_dir` resolution | Replaced by `DDO_CATALOG_DB` |
| `optimizer.parse_items` / `parse_augments` / `parse_filigrees` / `parse_sets` | Replaced by queries |
| `.ddobuilderv2_commit` as a runtime concern | Becomes a build-time stamp inside `catalog.db` |
| First-run clone of a large repo, and its network dependency | The catalog ships |

Two whole classes of bug go with them: **the parser fork** (Go keeps the *last*
`<Item>`, Python the *first* — they already disagree) and **runtime data drift**
(the app's answers changing because someone's checkout moved).

---

## 4. Measured scale

Taken from the real corpus, so the design is sized rather than guessed:

| | Count |
|---|---|
| Items (all levels, no ML filter) | **8,474** |
| `item_slot` rows | 10,589 |
| `item_augment_slot` rows | 13,415 |
| `item_set` rows | 2,015 |
| Item effect rows | **32,357** |
| **Distinct `(raw_type, raw_target)` — the stat dimension** | **1,799** |
| Full XML scan | 1.7 s |

Augments, filigrees and set tiers add to this but are small (74 augments and 27
filigrees survive today's *filtered* parse; the unfiltered counts are larger but
the same order). Expect **~100k rows** and a **10–30 MB** `catalog.db`.

**1,799 is the headline number.** It is the entire stat vocabulary of the game
as this data expresses it. Runtime priority matching goes from "substring-search
8,779 files" to "match a dozen user strings against 1,799 rows".

---

## 5. Architecture

```
DEV / BUILD TIME                         SHIPPED APP
─────────────────                        ───────────
DDOBuilderV2 XML
      │
      ▼
  Extract      (python/rules/extract.py — per-node, no filtering)
      │
      ▼
  Transform    (normalize names + variants, build the stat dimension,
      │         mint/resolve UUIDs, validate referential integrity)
      ▼
   Load        (upsert into a temp db, atomic rename)
      │
      ▼
  catalog.db ──────────── shipped as a resource ────────►  catalog.db (mode=ro)
                                                              │        │
                                                          Go ─┘        └─ Python
                                                       (pickers,        (solver,
                                                        display)         rules/)
```

### 5.1 The ETL is written in Python

Not a preference — a consequence. Transform needs the same extraction and
classification logic the solver uses, and that logic lives in `python/rules/`.
Writing the ETL in Go would fork it a third time, which is the mistake the
retrospective exists to prevent. The ETL is dev-only, so Python's presence on a
build machine costs the shipped app nothing.

It lives in **`etl/`** at the repo root — outside `python/`, so it is obvious it
is not part of the shipped solver, and outside `internal/`, so it is obvious Go
does not link it.

### 5.2 How `catalog.db` ships

**A separate file on disk. Never `go:embed`, never inside the app bundle at
runtime.**

`go:embed` would force an extract-to-disk step on every launch before SQLite
could open it (the same pattern as `extractSolver`, and the same I/O cost) — and
it would make a future "update catalog" feature impossible without shipping a
whole new binary.

#### 5.2.1 Where the files live

`catalog.db` and `app.db` sit **side by side in the user data directory**:

| Platform | Directory |
|---|---|
| macOS | `~/Library/Application Support/DDOGearsetOptimizer/` |
| Windows | `%APPDATA%\DDOGearsetOptimizer\` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/DDOGearsetOptimizer/` |

```
DDOGearsetOptimizer/
    catalog.db      # replaceable, versioned (§5.1.1 of the schema doc)
    app.db          # user data — builds, gearsets, runs (0.5.1)
```

**Not** `Contents/Resources/` inside the macOS `.app`. That directory is
**code-signed**: modifying anything in it invalidates the signature, and under
the hardened runtime and notarization the app then refuses to launch. A catalog
that can never be replaced without re-signing the whole application is not a
catalog that can be updated.

Putting both databases in the same user-writable directory also means
reinstalling or updating the *app* never touches either one.

#### 5.2.2 First run: seed, then read only from the data directory

The release **also** carries `catalog.db` inside the app bundle
(`Contents/Resources/` on macOS, alongside the `.exe` on Windows, in the
AppDir on Linux) — purely as **installation media**, never as the file the app
reads.

On launch:

```
if data_dir/catalog.db is absent
   or bundled.catalog_version > installed.catalog_version:
        copy bundled -> data_dir/catalog.db   (temp file, then atomic rename)
open data_dir/catalog.db  read-only
```

Why seed rather than require a sibling file: on macOS people drag **only** the
`.app` to /Applications. A catalog shipped merely next to it is left behind, and
the best the app could then do is show an error. Seeding makes a single `.app`
self-sufficient.

The cost, stated plainly: **the catalog exists twice on disk after first run**
(~20 MB), because a signed bundle cannot delete its own contents. That is the
price of the bundle staying signed and verifiable.

The version comparison is what makes an app update also deliver a newer catalog
without a separate download — and because the copy is guarded by
`catalog_version`, it will never overwrite a *newer* catalog the user obtained
through a future update feature.

#### 5.2.3 Access modes differ

The two files are opened differently, and the difference is load-bearing:

```
catalog.db   file:…/catalog.db?mode=ro&immutable=1     Go and Python
app.db       read/write                                Go only (§5 writer discipline)
```

`immutable=1` on the catalog is honest — nothing writes it while the app runs —
and it lets SQLite skip locking entirely. Go passes the resolved catalog path to
the solver as `DDO_CATALOG_DB`, replacing `DDO_DATA_PATH`.

> A catalog *update* is not a write to an open database. It is: download to a
> temp file, verify, close, atomically rename, reopen. `immutable=1` stays
> correct.

#### 5.2.4 The catalog carries its own version

`catalog_meta` records a monotonic
`catalog_version` alongside `schema_version`, `min_app_version`, a content hash
and the identity-registry hash — see
[`01_CATALOG_AND_APP_SCHEMA.md`](01_CATALOG_AND_APP_SCHEMA.md) §5.1.1. 0.5.0
builds **no** update feature, but a catalog that ships without those fields can
never be compared or safely replaced by one, and they cannot be added
retroactively to a file already in the wild. Recording them now is free.

---

## 6. Identity: a checked-in registry, not just v5 hashing

Constraint 4 is the one that needs real design.

Deterministic UUIDv5 from a natural key gives stability across rebuilds, but
**not across renames** — if DDOBuilderV2 renames an item, its natural key
changes and so does its UUID, orphaning every reference in `app.db`. Hashing
alone cannot fix that, because the rename is information that exists only
between two runs.

So identity is **pinned in a checked-in registry**, and the hash is only how a
*new* identity is minted:

```jsonc
// etl/identity_registry.json  — append-only, tracked in git
{
  "version": 1,
  "entities": {
    "8f14e45f-...": {
      "kind": "item",
      "canonical": "Legendary Bracers of Wind",
      "aka": ["Epic Bracers of Wind"],
      "first_seen": "2026-08-10",
      "last_seen_commit": "a1b2c3d"
    }
  }
}
```

**Once minted, a UUID never changes.** A rename appends to `aka`. That makes
`app.db` references permanently stable, which is what 0.5.1 depends on.

### 6.1 The drift report

Each ETL run classifies every natural key:

| Case | Action |
|---|---|
| Key in registry (`canonical` or `aka`) | Reuse its UUID |
| Key absent from registry, nothing disappeared | **New entity** — mint a v5 UUID, append to registry |
| Key disappeared, a new key is a *clean derivation* of it | **Auto-resolve** — append to `aka`, log as `AUTO` |
| Key disappeared, no clean derivation | **UNRESOLVED** — log for a human |

"Clean derivation" is deliberately narrow, and only these:

- an upgrade-tier prefix changed (`Epic X` → `Legendary X` — `RAID_UPGRADE_TIER_PREFIXES`)
- whitespace, punctuation or case normalization alone
- an explicit `version of` relationship in the data (`_RAID_VERSION_OF_RE`)

Anything else is a guess, and a wrong guess silently rewrites a user's gearset.

Unresolved cases are written to **`etl/drift/<commit>.md`** — human-readable,
with disappeared and appeared keys ranked by string similarity so a decision is
quick — and resolved by editing **`etl/aliases.yaml`**:

```yaml
# Reviewed 2026-08-12. Confirmed by comparing DropLocation and effect lists.
- was: "Bracers of the Sun Soul"
  now: "Legendary Bracers of the Sun Soul"
- was: "Gem of Many Facets"
  now: null        # genuinely removed from the game
```

The next run reads `aliases.yaml`, resolves them, and folds them into the
registry.

### 6.2 Strictness

`--strict` fails the build on any UNRESOLVED entry; without it the ETL warns and
proceeds, minting new identities. **Release builds use `--strict`.** Day-to-day
dev does not, so a mid-week DDOBuilderV2 bump does not block work.

---

## 7. What Transform owns, and what stays at runtime

The rule that survives from the deprecated work, because it is the one that was
paid for in blood:

> **One layer owns priority matching.** If Go matches the user's priorities
> against the stat dimension itself, that is the failed 0.5.0 approach with a
> database in the middle.

| Concern | Where | Why |
|---|---|---|
| Entity naming, variants, upgrade chains | **Transform** | Pure function of the catalog |
| The `stat` dimension: `(raw_type, raw_target)` → identity + `is_skill` / `is_hireling` / `is_save` / `is_weapon_base` flags | **Transform** | Pure functions of the buff. Four guards that were code become columns |
| Repeating `<Item>` / `<Type>` / `<SetBonus>` expansion | **Transform** | Rows, not "which one wins" |
| Priority string expansion, bonus-type prefixes, direct-before-implied ordering | **Runtime (Python)** | Functions of what the user typed |
| **Bonus-type stacking (sum vs max)** | **Runtime (Python), `rules/stacking.py`** | Constraint 7 — business logic, not storage |
| Search restrictions (ML window, armor, packs, owned, raid cap) | **Runtime (Python)**, as query predicates | The catalog holds everything; restrictions shape a *suggestion* |

> **The ETL applies no search restriction of any kind.** `catalog.db` contains
> every item at every level. ML windows and pack exclusions become `WHERE`
> clauses in the solver's pool query. This is the same layering rule as before,
> now enforced by the schema instead of by discipline.

Schema detail: [`01_CATALOG_AND_APP_SCHEMA.md`](01_CATALOG_AND_APP_SCHEMA.md).

---

## 8. Phased plan — 0.5.0

Gates are scripts a human runs. No phase starts until the previous gate is
green.

### Phase 0 — Clean branch and regenerated oracles

Constraint 5. Branch fresh from `main`; carry **documentation and two scripts**,
nothing else.

1. Branch from `main` (`fff94a9` or later).
2. Copy across `docs/0.5.0/`, `docs/0.6.0/`, and **only** these two scripts:
   `scripts/capture_oracle.py`, `scripts/parser_snapshot.py`. Both run against
   unmodified `main` — they call `optimizer.parse_*` and `solver.py`'s
   `mode:"calculate"` with signatures the refactor never changed.
3. Run `capture_oracle.py` first (the snapshot's owned-names fixture reads its
   output), then `parser_snapshot.py capture`.
4. Record the baseline: **171 Python passing**, `svelte-check` 0 errors /
   0 warnings / 15 hints, `go build` / `vet` / `test` clean.

**Nothing else is carried.** The extractor refactor is re-done in Phase 1 —
about an hour of now-known work, with a proven verification method.

**Gate:** oracles regenerated on `main`; baseline recorded.

> **Why these two artefacts matter more than the code.** The parser snapshot is
> the ETL's acceptance test: 30 canonical digests of what `main`'s parsers
> produce across the full corpus under 9 restriction combinations. The catalog
> is correct exactly when Python, reading `catalog.db`, reproduces them. Without
> it the ETL has no oracle at all.

### Phase 1 — Extract: split candidacy from extraction

Re-do the extractor split on the clean branch: `_item_from_node`,
`_augment_from_node`, `_filigree_from_node`, `_effect_buffs_from_node`,
`_item_slots_from_node`, `_item_provenance`, plus `keep_unmatched` so extraction
can report every stat rather than only priority-matched ones.

**Gate:** 30/30 parser snapshots **byte-identical** · 171/171 Python, no test
edited · snapshot asserted with `keep_unmatched=False`.

*Known trap, already paid for once:* the parse loops wrap everything in
`except Exception: pass`, so a missing import silently drops records instead of
raising. Run a `pyflakes` undefined-name check over the new modules as part of
this gate — a snapshot diff will catch it, but the error message will not
mention the real cause.

### Phase 2 — Transform

Move the rules into `python/rules/` (no `pulp`), then build Transform in `etl/`:

1. Entity resolution: canonical names, tier prefixes, `version of` chains,
   filigree base/variant split, `A/B` dual-set expansion.
2. The **stat dimension** — dedupe `(raw_type, raw_target)`, compute
   `match_text` and the four classification flags.
3. Expand repeating `<Item>` / `<Type>` into positioned rows.
4. Identity resolution against `identity_registry.json` + `aliases.yaml` (§6).
5. **Validate before Load**: every `effect_target.stat_uuid` resolves, every
   `filigree_set.set_uuid` resolves, no duplicate natural keys. A Transform that
   cannot satisfy its own referential integrity fails loudly.

**Gate:** `test_rules_module_does_not_import_pulp` · Transform output snapshot
is deterministic across two runs and two `PYTHONHASHSEED`s · validation
failures are fatal · drift report renders for a synthetic rename.

### Phase 3 — Load

Schema DDL, upsert in one transaction into a temp file, verify `catalog_meta`,
atomic rename.

**Gate:** `catalog.db` builds from a cold checkout · size and build time
recorded · `PRAGMA integrity_check` and `foreign_key_check` clean · rebuilding
twice produces **identical UUIDs** (the determinism the registry promises) ·
`catalog_meta` is populated with all of `schema_version`, `catalog_version`,
`min_app_version`, `content_hash` and `identity_registry_hash`, and the ETL
**refuses to build** when `identity_registry.json` is missing.

### Phase 4 — Python reads `catalog.db` · **the correctness gate**

Replace `parse_items` / `parse_augments` / `parse_filigrees` / `parse_sets` with
SQL, restrictions becoming `WHERE` predicates.

**Gate — the one that matters:** re-run `parser_snapshot.py verify` with the
parsers now backed by `catalog.db`. **All 30 digests must still match.** That is
the proof that the catalog changed no numbers. Then: 171/171 Python, and the
12 gearset oracle results reproduce.

### Phase 5 — Go reads `catalog.db`

Delete `internal/services/parser.go` and `enrichment.go`. Pickers, item detail
and set lookups become queries.

**Gate:** `go build` / `vet` / `test` clean · item detail shows the **first**
`<Item>` target, matching Python (today Go shows the last) · no XML parsing left
in Go.

### Phase 6 — Cut the runtime dependency

Delete `ddobuilder_fetch.go`, `ensureDDOBuilderData`, `updateDDOBuilderDataIfStale`,
`UpdateExternalSources` and `DDO_DATA_PATH`. Ship `catalog.db` as a resource;
pass `DDO_CATALOG_DB`.

**Gate:** the app runs with **no `DDOBuilderV2/` directory present at all** —
the definitive test of constraint 2 · no network access on first run · release
artefacts build on macOS, Windows and Linux · **first run seeds
`catalog.db` into the user data directory and reads it from there**, verified by
deleting the data directory and relaunching · the macOS bundle still passes
`codesign --verify` after first run, proving nothing wrote inside it.

### Phase 7 — Build integration and drift workflow

`etl/` gets a CLI (`--strict`, `--out`, `--drift-report`, `--catalog-version`).
`build-mac.sh`,
`build-windows.ps1`, `build-linux.sh` and `package_release.sh` invoke it before
`wails build`; release builds pass `--strict`.

**Also here: the PyInstaller `--onedir` fix.** It is independent of the ETL and
lost its home when the old plan was deprecated, but this phase already rewrites
all three build scripts, so doing it anywhere else means touching them twice.
Measured: `--onefile` + UPX costs **3.80 s on every invocation** (8.93 s cold)
because it re-extracts ~8 MB before running a line of Python; `--onedir` is
**0.11 s**. Two riders:

- `extractSolver` (`app.go:334`) must recurse into `_internal/` — it currently
  skips directories.
- Extraction must become **cached and version-stamped** (`<cache>/ddo-solver/<version>-<hash>/`,
  stamp written last), or a 55-file / 20 MB unpack happens on every launch.
  Assert zero extraction I/O on the second launch.

Flagging it rather than folding it in silently: if you would rather 0.5.0 stay
purely the ETL, this moves to 0.5.1 at the cost of editing the build scripts
again.

**Gate:** a clean checkout builds a release end to end · a synthetic rename
produces a drift report and, with `--strict`, fails the build · resolving it via
`aliases.yaml` unblocks the build and preserves the UUID · warm solver start
≤ 0.25 s on macOS and Windows.

#### 8.7.1 What Phase 7 actually built — and what it found

| Gate clause | Result |
|---|---|
| Release builds end to end | ✅ `./build-mac.sh` → signed `.app`, 56 s total (ETL 6.4 s of it) |
| Synthetic rename → drift report + `--strict` fails | ✅ exit **2**, no catalog written, registry **not** modified |
| `aliases.yaml` unblocks the build, UUID preserved | ✅ renamed item kept `b9075fd3-…`; the report's paste block parses as-is |
| Warm solver start ≤ 0.25 s | ✅ **0.07 s** (was 3.83 s warm / 10.14 s cold) |
| Zero extraction I/O on second launch | ✅ asserted by mtime snapshot in `app_extractsolver_test.go` |
| Real solve against the shipped artefacts | ✅ full 14-slot gearset, solver + `catalog.db` from `bundled/` only |

The CLI takes more than the four flags this section named — `--source`,
`--registry`, `--aliases`, `--ddobuilder-commit`, `--min-app-version`,
`--init-registry` — and `--catalog-version` defaults rather than being
required: it carries the previous catalog's version forward and adds one only
when `content_hash` moved. That works because the build scripts write straight
into the committed `bundled/<platform>/catalog.db`, so even a clean checkout
has the previous number to count from.

Four things surfaced while building it that the plan had not anticipated:

**Transform reconciled renames too late to matter.** `reconcile_disappeared`
ran *after* the loop that resolved and emitted rows, so a rename resolved via
`aliases.yaml` repointed the NAME at the original UUID while the catalog kept
the fresh one `resolve()` had already minted and stamped into every row. The
build succeeded, every foreign key resolved, and the registry's one promise
was quietly broken. Every kind now reconciles *before* it resolves, and
`reconcile_disappeared` raises if called the other way round.

**Rename targets could steal an established identity.** Candidate targets are
now only keys the registry has never seen, and an alias pointing at an
occupied name is reported as a conflict — fatal in both modes — instead of
deleting the entity that already owns it.

**The augment collision made the catalog unbuildable.** Load refuses to write
when `validation_errors` is non-empty, and the known `Twilight` / Cannith
Armor Prefix ambiguity was one — so the committed catalogs had in fact been
produced by an ad-hoc script that bypassed the guard. Source-data ambiguity is
now its own channel (`TransformResult.data_ambiguities`), reported on every run
and in the drift report; `validation_errors` means referential integrity only.
An upstream ambiguity is permanent, and no release should wait on Maetrim
editing a file.

**`content_hash` hashed the diagnostics.** It walked every list attribute on
the result, including `validation_errors`, so rewording a warning changed the
"did the data change?" answer that `--catalog-version` now keys off. Load's
inserts and the hash both run off one shared `TABLES` list.

Also fixed in passing: corpus globs are `sorted()` (file order decides which
duplicate survives, and `glob.glob` order varies by machine), and the build
scripts now clear WAL sidecars and stray logs out of `bundled/<platform>/`
before `wails build` — `go:embed` reads the filesystem, not git, so gitignored
debris was riding into the binary unnoticed.

---

## 9. Recalculation is 0.5.1 — decided

The original ask that started all of this —

> *"separate the solving and the recalculation … recalc doesn't need the solver"*

— lands in **0.5.1**, alongside `app.db`. `gearset_slot(origin)` and
"recalculate what's equipped" are the same feature seen from two sides.

The ETL makes it small. Once `catalog.db` exists, `resolve_equipped_items` is a
`WHERE name IN (...)` lookup — no glob, no XML, no candidate pool, no ILP — and
`_collect_contributions` + `_resolve_totals` already evaluate a fixed gearset by
direct arithmetic. Recalculation becomes a thin entry point, not a project.

### 9.1 What this obliges 0.5.0 to do

- **`mode: "calculate"` must survive 0.5.0 intact.** It is what Phase 0 captures
  the gearset oracle with, and it remains the Calculate button until 0.5.1
  replaces it with `mode: "recalculate"`. Do not delete it early.
- **Phase 4's gate covers both releases.** After the parsers become SQL-backed,
  the 12 captured gearset results must still reproduce — that is simultaneously
  proof the catalog changed no numbers *and* the baseline 0.5.1 will differential
  against.

### 9.2 What 0.5.1 inherits from the deprecated recalculation spec

These parts of [`01_RECALC_SPEC_AND_PHASED_PLAN.md`](01_RECALC_SPEC_AND_PHASED_PLAN.md)
are **not** void — they are scheduled:

| Carried into 0.5.1 | Note |
|---|---|
| A payload that **cannot express a search restriction**, rejected if one is sent | Stronger now: restrictions are `WHERE` clauses the recalc query simply never adds |
| `realizedStats` (priority-spelled) + `otherStats` (everything else) | Decision 2 |
| Structured `allEffects` objects, `parseEffectSource` deleted | Decision 1 — and the solve path changes with it |
| Physical rules **warn, never refuse**; `validate_physical_rules()` is net-new code | The `<= 1 per base_name` filigree defect is the headline case |
| An empty or failed result must never overwrite saved stats | Non-negotiable |
| Split the calculate-mode tests: rewrite the 3 behavioural, delete the ILP ones | Decision 3 |

### 9.3 What the ETL makes moot

Three decisions from that plan are **superseded rather than deferred** — the
schema solves them, so 0.5.1 must not re-litigate them:

| Was | Now |
|---|---|
| Fix Python's dual-`<SetBonus>` first-wins, alone, with a re-baseline (decision 7) | `filigree_set` rows. Structural — no separate fix, no re-baseline |
| Investigate multi-`<Item>` crediting before changing it (decision 8) | `effect_target.position`. First-wins is `WHERE position = 0`; the investigation becomes a one-line experiment |
| Refuse pre-0.5.0 files + offer an item-list export (decision 5) | Subsumed by `app.db`'s migration story. `.ddogearset` becomes an **export/import** format, not storage |

---

## 10. Deprecated

Every other document in `docs/0.5.0/` is superseded and carries a banner. They
are kept for their **findings**, which remain true, not their plans:

| Document | Still worth reading for |
|---|---|
| `CALCULATE_STATS_RETROSPECTIVE.md` | Why reimplementing domain rules outside Python failed. The single most important document in the folder |
| `00_RECALC_PHASE_START_HERE.md` | The XML shape traps (§4) and the Wails bridge payload limits (§4.2) |
| `RECALCULATION_SEPARATION_PROPOSAL.md` | The search-vs-domain-rules distinction (§2), which the ETL enforces structurally |
| `01_RECALC_SPEC_AND_PHASED_PLAN.md` | Measured findings (§2): PyInstaller 3.8 s startup, the oracle survey, the filigree base-name defect |
| `UI_CHANGES_0_5_0.md` | Input to **0.5.2**, not 0.5.0 |
| `critic.md` | The review and its adjudication |

Findings that outlive the plans and must not be rediscovered:

- **PyInstaller `--onefile` + UPX costs 3.8 s per invocation**; `--onedir` is
  0.11 s. Unrelated to the ETL and still worth fixing.
- **`optimizer.py:1817` constrains one filigree per `base_name` per bucket**,
  which makes a real saved gearset unevaluatable. Model `filigree_base`; build
  no constraint on it until that is settled.
- **The Wails bridge silently drops payloads above ~64 KB**, and a dropped
  message never settles. Keep responses small; measured today they are 10–18 KB.
- **`GetSystemLogs` returns an unbounded slice** under no mutex, polled once a
  second.
- **`frontend/tsconfig.json` excludes `wailsjs/`**, so generated bindings are
  never type-checked.
