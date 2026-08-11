# 0.5.1 — Retrospective and handoff

**Status:** shipped. Phases 0–6 complete on `major/0.5.0`, 8 commits, working
tree clean, unpushed. A real `./build-mac.sh` release was built and exercised
after the last phase landed.

Same shape as [0.5.0's retrospective](../0.5.0/RETROSPECTIVE_AND_HANDOFF.md):
the first half is what happened and what it taught, the second is what somebody
picking up 0.5.2 needs. The plan lives in
[`00_APP_DB_START_HERE.md`](00_APP_DB_START_HERE.md); the schema in
[`../0.5.0/01_CATALOG_AND_APP_SCHEMA.md`](../0.5.0/01_CATALOG_AND_APP_SCHEMA.md).
Neither is restated here.

---

## 1. What changed, in one paragraph

0.5.0 gave the app a catalog it could trust. 0.5.1 spent it. The user's builds
and gearsets moved out of JSON files in the process working directory and into
`app.db`; `.ddogearset` became an export format; a solve's output and the user's
own gearset became different rows so one can no longer overwrite the other; and
evaluating a gearset stopped borrowing the solver — `mode: "calculate"` is
deleted, replaced by `recalculate`, which is direct arithmetic over the two
functions that could always have answered the question.

## 2. The numbers

| | Before | After |
|---|---|---|
| Where a gearset lives | JSON, in the process working directory | `app.db`, in the user data directory |
| Evaluating a gearset | full candidate pool + ILP, 2.7–5.8 s | direct arithmetic, **0.55–0.66 s** |
| GLPK needed to evaluate | yes | no |
| A gearset with two same-base filigrees | **refused** | evaluated, with warnings |
| Optimize → Save writing an empty gearset | possible | structurally impossible |
| Release build (`./build-mac.sh`) | — | 27 s, `codesign --verify` passes |

Code: 27 files, +6,405 / −222 (excluding binaries and generated bindings).
`internal/appdb` is 3,252 lines; `python/rules/evaluate.py` — the thing that
replaced an ILP — is 275.

Tests: 239 pytest (was 215 at the start of the release), 90 Go test functions
across 5 packages, 30 parser-snapshot digests, 14 oracle fixtures.

`app.db` schema 2. `catalog.db` unchanged at catalog_version 2, data revision
`f91af4e6`.

---

## 3. What went wrong, and what it taught

### 3.1 The differential had never been run

`scripts/check_oracle.sh` asserted the 14 fixtures were present and internally
consistent. `scripts/capture_oracle.py` replayed them, but only to *capture* —
it had no compare mode. So "the oracle reproduces", asserted in the 0.5.0 plan
as Phase 4's gate, had never been executed against anything. What that gate
actually covered was the parser snapshot.

Phase 0 built the missing half, and it failed on all 12 fixtures the first time
it ran — on ordering, with every value identical. Three more times across the
release it caught something real (§3.3, §3.4). None of those would have been
found by any other check in the project.

**The lesson is about gate design, not about the oracle.** A gate that describes
a property is worth roughly nothing; a gate that executes it is worth the phase
it takes to build. 0.5.0's retrospective said the same thing about its four
latent bugs. This release is the second data point, and it is stronger, because
here the *un-executed* gate had been believed for a whole release.

### 3.2 A broken script destroyed an irreplaceable fixture

`capture_oracle.py` had been broken since 0.5.0 Phase 6 switched the solver from
`DDO_DATA_PATH` to `DDO_CATALOG_DB`. Every run failed — and on the first one, it
wrote that failure *over the fixture it was replaying*. The one asset in this
project that explicitly cannot be regenerated.

Restored from git in seconds. The lasting fix is that a failed capture now
refuses to overwrite a successful one without `--force`.

**Worth sitting with:** the destructive path was reached by *running the tool
normally*. No unusual flag, no misuse. A tool that writes to irreplaceable data
should treat "write" as the special case, not the default.

### 3.3 Two implementations of the same rule, twice avoided

Both times the temptation appeared, and both times taking the longer road paid
immediately:

- **Phase 2** — `SaveBuild` and `ImportFile` could each have written their own
  rows. They share `writeBuild` instead, which is what makes the export →
  import round-trip test meaningful rather than tautological.
- **Phase 3** — suggestions could have had their own writer. `origin` became a
  parameter, so the two nodes cannot disagree about how a gearset is stored.

The counter-example is in the same release: `_collect_contributions` grew a
third tuple element, and I updated two unpack sites after grepping `for v, o
in`. A third existed as `for v, _o in` and only two tier tests reached it. The
suite caught it — but the grep did not, and a pattern search is not a type
system.

### 3.4 Three findings the differential surfaced in Phase 4

Recorded because each is the kind of thing that ships silently:

- A catalog-wide "does anything grant this stat" check tested every stat against
  one hardcoded bonus type, so every bonus-type-prefixed priority
  ("insightful spell focus mastery") came back unmatched. **Bonus type is part
  of the question.**
- `allEffects` listed contributions that never reach the total — a set granting
  both a Stacking and an Artifact bonus to one stat, where the Artifact one
  loses to a bigger source. Listing it reads as additive and inflates what the
  gear appears to do.
- `slots.<slot>.augments` reordered on every caster fixture at once. Phase 0 had
  deliberately left that path out of the ordering allowance with the note that a
  reorder would be *"a signal worth failing on"*. It fired, the signal was read
  (enumeration order, same augments), and the path was added. **A check that
  fires once and is then understood has done its job.**

### 3.5 The specified schema was wrong twice, and only real data showed it

`run_active_set`'s documented key `(run_uuid, set_uuid)` would have accepted a
set's first active tier and silently rejected the rest — and a real gearset has
"Zarigan's Arcane Enlightenment" active at 2, 3 *and* 4 pieces simultaneously.
`run_effect`'s documented key included `source_uuid`, which in a `WITHOUT ROWID`
table is implicitly `NOT NULL`, so an effect whose source did not resolve could
not have been stored — and those are the ones most worth recording.

Both were written down carefully, reviewed, and wrong. Checking a schema against
the data it will hold is not the same activity as reading it.

### 3.7 The packaged app had never started — and neither had two of its tests

The first time the `.app` was actually launched, the solver died with
*"Failed to load Python shared library"*. **`go:embed` silently skips symbolic
links** (`go doc embed` says so plainly), and PyInstaller's `--onedir` output
contains four — `_internal/Python` points at the framework's real library, and
`Python.framework` has three more. They were staged into `bundled/`, tracked by
git, and never embedded. The extracted tree was missing them, so the interpreter
could not load.

Broken since the `--onedir` switch in 0.5.0 Phase 7. Every test passed
throughout, because the one that checked extraction asserted *"every embedded
file was extracted"* — trivially true of files that were never embedded.

Fixed with a manifest: the links are recorded at stage time and recreated at
extraction, rather than dereferenced with `cp -RL`, which would have worked and
cost 14 MB of duplicated library paid twice — once inside the binary, once in
every extracted cache directory.

**Two things are worth carrying forward.** First: the test that catches this is
the one that *runs the extracted binary*. Checking that files landed in the
right places cannot detect a file that was never supposed to be a file.

Second, and sharper: **two unrelated tests were green because of this bug.**
`TestAFailedOptimizeLeavesEquippedUntouched` and `TestAFailedSolveIsStillRecorded`
both established "a failed solve" by relying on the solver being unable to start.
They went red the moment it was fixed. A test whose premise is that the thing
under test is broken is worse than no test, and neither of them said out loud
what it was depending on.

### 3.8 Smaller ones

- **A test I could not write honestly.** Phase 2's "a failed save does not
  destroy the previous build" first used an out-of-range priority tier — which
  the writer clamps. No config *can* fail: it clamps tiers, skips unresolvable
  names, and uses `INSERT OR IGNORE` where duplicates are possible. A SQLite
  trigger injects the real failure instead. A test for a failure the code cannot
  produce tests nothing.
- **A second instance of this release's own bug.** `solver.py` writes
  `gearset_output.txt` relative to *its* working directory, inherited from the
  Go process. There was one sitting in the repo root. Found while checking that
  `SaveGearset` no longer does this.
- **`data/ddobuilder` had been a pinned submodule since the initial commit**,
  while the ETL read a gitignored copy of the same bytes. Found by measuring
  repository size, not by looking for it.
- **A hollow test, caught in review.** Phase 3's first calculate-mode guard test
  asserted a tautology about a local variable. The guard was extracted into a
  real predicate and tested properly.

---

## 4. What went right

**Phase 0 first.** Building the differential before anything depended on it is
the single decision the release rests on. By Phase 5 it was the only thing
standing between the old numbers and the new, and it could not have been built
then — `calculate` was already gone.

**Fixtures as payload + answer, not prose.** The fixtures survived the deletion
of the mode that produced them, unchanged, because they record *what was asked*
and *what came back* rather than a description of behaviour.

**Unrepresentable beats unused.** `RecalculationRequest` has nowhere to put a
search restriction; `evaluate_gearset`'s signature cannot take one; `solver.py`
rejects one by name. Three layers, and the innermost is a type. A field stripped
in transit is a field somebody re-adds.

**Structural invariants over careful code.** `equipped` and `suggested` as
different rows retired a named bug by construction. One transaction per write
made "a failed save destroys the build" unreachable rather than unlikely.

---

## 5. Architecture as it now stands

```
data/ddobuilder/  (pinned submodule)  ──[python -m etl, dev only]──▶ catalog.db
                                                                        │
                                                        go:embed + first-run seed
                                                                        ▼
<user data>/DDOGearsetOptimizer/
    catalog.db   disposable, replaced by an app update
    app.db       PRECIOUS, schema-versioned, migrated forward, never recreated
    gearsets/    .ddogearset EXPORTS — a file you can send someone

app.db
  build ─┬─ build_priority / build_excluded_pack / build_caster_option
         ├─ gearset_slot / gearset_augment / gearset_filigree   (origin: equipped | suggested)
         ├─ orphan_reference        names no catalog row answers to
         └─ run ─┬─ run_stat / run_effect / run_active_set / run_warning
                 └─ catalog_commit  which game data produced these numbers
```

Who writes what:

| Concern | Owner | Rule |
|---|---|---|
| `app.db` | Go (`internal/appdb`) | One writer. Python stays stateless about user data |
| Evaluating a gearset | `python/rules/evaluate.py` | No pulp, no pool, no restriction expressible |
| Searching for a gearset | `python/optimizer.py` | All search constraints, unconditionally |
| Which build a config is | `BuildUUIDForName` | Name identity; renaming is "Save As" |
| Which build a file is | `BuildUUIDForFile` | Content identity; re-import is a no-op |

---

## 6. Invariants — break these and something fails silently

Additional to [0.5.0's §6](../0.5.0/RETROSPECTIVE_AND_HANDOFF.md#6-invariants--break-these-and-something-fails-silently),
all of which still hold.

1. **A solve never writes an `equipped` row.** Only `AcceptAll` moves rows
   across, and it refuses an empty suggestion — otherwise the button is a
   one-click gearset eraser.
2. **Every `app.db` write is one transaction.** A half-written record is worse
   than none: it claims success while reporting nothing.
3. **Re-import is not a sync.** A build already imported is left alone; the
   file cannot know it was edited since.
4. **Migrations are forward-only and additive**, and a fresh database is created
   at schema 1 and migrated up — so the migration path runs on every clean
   install, not only on machines with an old file.
5. **`evaluate_gearset` must never gain a restriction parameter.** There is a
   test asserting its signature; do not "fix" that test by widening it.
6. **`allEffects` stays a display string.** `allEffectsDetail` carries the
   structured form. Changing `allEffects` breaks the only differential left.
7. **The oracle fixtures are not regenerable.** `capture_oracle.py` still
   exists, but the mode it captured with does not.

---

## 7. Known gaps and unverified claims

- **Windows and Linux remain unverified**, carried forward from 0.5.0 and now
  larger: `app.db`'s path resolution, the migration, and the whole storage layer
  have only ever run on macOS. `TestFirstRunCreatesAppDBWithNoOverrides` skips
  on Windows because `os.UserConfigDir` reads `%AppData%` rather than `HOME`.
- **The packaged `.app` was launched, and it was broken.** See §3.7 — the first
  real launch found that `go:embed` silently drops symlinks, so the extracted
  solver had been unable to start since the `--onedir` switch in 0.5.0. Fixed,
  with the extraction now verified by running the extracted binary. What is
  still untested is a human working through the UI: every RPC is driven by
  tests, including the exact sequence the frontend performs, but that is not the
  same as somebody using it.
- **`owned_item` is modelled and unwired.** It is player-level inventory fed by
  the Trove import, not per-build, and nothing in 0.5.1's gates touched it.
- **`run_effect.source_name` is not resolved to a catalog UUID.** The names are
  recorded; joining them back is a 0.5.2-or-later concern.
- **No backfill of run history from imported files.** `build.imported_from`
  records where a build came from precisely so this stays possible; the saved
  stats in those files are not lost, just not yet turned into `run` rows.
- **`unmatchedPriorities` / `unmetTier4` differ from the oracle**, explained and
  excluded by name in the differential — pool-scoped versus catalog-scoped. See
  `known_deltas.yaml`.
- **One permanent source-data ambiguity** (`Twilight` / Cannith Armor Prefix),
  reported on every ETL run.

---

## 8. The release build, actually run

```bash
./build-mac.sh          # 27 s, signature verified
```

- ETL rebuilt `catalog.db` in 8.5 s and **kept catalog_version 2** — the content
  hash was unchanged, so the auto-version logic correctly declined to bump.
- 30/30 parser snapshots identical.
- Artifacts: `dist/darwin-arm64/DDO Gearset Optimizer.app` (93 MB) and a 26 MB
  zip.
- The **shipped** PyInstaller solver, run against the **shipped** catalog, with
  no GLPK involved, recalculated the gearset the old implementation refused:
  14 slots, 12 realized stats, two warnings, `allEffectsDetail` present, in
  **0.55–0.66 s** warm.
- After the symlink fix (§3.7), the full path was exercised end to end: extract
  the embedded bundle exactly as launch does, run the extracted solver, and
  recalculate through `RecalculateGearset` — producing a stored run stamped with
  catalog `f91af4e6`.

Verification recipes are unchanged from
[0.5.0 §8](../0.5.0/RETROSPECTIVE_AND_HANDOFF.md#8-verification-recipes), plus:

```bash
# The differential — now the only thing between the old numbers and the new
python/.venv/bin/python -m pytest python/tests/test_oracle_differential.py -q
```

---

## 9. Handoff: starting 0.5.2

### 9.1 What 0.5.2 was always going to be

UI/UX implications. [`../0.5.0/UI_CHANGES_0_5_0.md`](../0.5.0/UI_CHANGES_0_5_0.md)
is its input document and has been waiting two releases.

### 9.2 What 0.5.1 built that the UI has not caught up with

The storage layer got ahead of the interface on purpose — the plan put UI work
in 0.5.2 — so several things exist and are barely surfaced:

- **Builds are a list now.** The picker in `Summary.svelte` is a `<select>`
  added to prove the wiring. Naming, renaming, deleting, duplicating and
  organising builds is real UX work that has not been done. `DeleteBuild` is an
  RPC with no button.
- **Suggestions are a first-class thing.** `equipped` and `suggested` are stored
  separately, and the UI shows one "Accept All" button. Showing a *diff* — what
  the solver would change, slot by slot — is now a query, not a feature.
- **Run history exists and nothing displays it.** `ListRuns` returns the last 50
  with timings, modes, failures and the catalog revision each ran against.
- **Orphans are recorded per build.** `orphan_reference` knows exactly which
  items a build references that the catalog no longer has; the UI shows a toast
  on load.
- **Warnings are structured.** `validate_physical_rules` returns
  `{kind, slot, message}`; the frontend does not render them at all yet.

### 9.3 Traps carried forward

- **The Wails bridge silently drops payloads above ~64 KB**, and a dropped
  message never settles. Still unmeasured for a recalculation carrying
  `allEffectsDetail` — that field roughly doubles the effect data on the wire.
  **Measure this before building anything that sends more.**
- **`frontend/tsconfig.json` excludes `wailsjs/`**, so generated bindings are
  never type-checked. Run `wails generate module` after every Go struct change;
  this release changed them four times.
- **`optimizer.py`'s one-filigree-per-`base_name` constraint** is still in the
  search path, still unsettled, and now demonstrably wrong as an *evaluation*
  rule. Whether it is right for the search is the open question recorded in
  `known_deltas.yaml`.
- **`GetSystemLogs` returns an unbounded slice** under no mutex, polled once a
  second.

### 9.4 Suggested first move

Not code. Decide what a "build" is to the user, because the storage now supports
more than the interface admits: one list, or per-character grouping? Is a
suggestion something you compare against, or something you accept and forget?
Does run history belong in the UI at all, or is it diagnostics?

The schema answers none of those, and 0.5.2 is the release where they stop being
deferrable.
