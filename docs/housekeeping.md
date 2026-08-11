# Housekeeping — install, build, and rebuild the catalog

Everything you need to go from a fresh clone to a signed release, and to
refresh the game data when DDOBuilderV2 moves.

Nothing here is needed to *run* a release build. A shipped app carries its own
Python, GLPK and game catalog, and never touches the network — this document is
entirely about the build machine.

---

## 1. First clone

```bash
git clone --recurse-submodules <repo-url> goGearset
cd goGearset
```

**If you already cloned without `--recurse-submodules`:**

```bash
git submodule update --init --depth 1
```

`data/ddobuilder` is [DDOBuilderV2](https://github.com/Maetrim/DDOBuilderV2),
pinned to an exact revision. It is the ETL's only input, and being pinned is the
point — every catalog records the upstream revision it was built from. Nothing
fetches it at runtime.

Then:

```bash
./install.sh
```

Installs and verifies Go, Node, Python 3.11 (plus a project-local venv with
`pulp` and `pyinstaller`), GLPK, and the Wails CLI. On macOS it uses Homebrew;
on Linux, apt.

**GLPK is a build-machine dependency only.** The solver binary carries `glpsol`
and its libraries, so nobody running the app needs it installed.

### What you should have afterwards

| Tool | Version | Why |
|---|---|---|
| Go | 1.25+ | `go.mod` |
| Wails CLI | v2.10.0 | pinned; must match `go.mod`'s wails version |
| Node | LTS | frontend build |
| Python | 3.11 | the solver is compiled against it |
| GLPK | any recent | `glpsol`, bundled into the build |

---

## 2. Building

One script per platform. **None of them cross-compile** — PyInstaller and
`glpsol` only ever produce binaries for the machine running them, so each
platform must be built on that platform and its `bundled/<platform>/` committed.

```bash
./build-mac.sh        # macOS   → dist/darwin-<arch>/
./build-linux.sh      # Linux   → dist/linux-<arch>/
.\build-windows.ps1   # Windows → dist\windows-amd64\
```

Each script, in order: builds `catalog.db` from the submodule, compiles the
Python solver, stages `glpsol` and its libraries, records symlinks (§5.3), runs
`wails build`, signs, and copies the result into `dist/`.

macOS takes about 30 seconds warm.

### Release vs. dev builds

`RELEASE=1` is the default and passes `--strict` to the ETL: an unexplained
rename in the game data **fails the build** rather than quietly minting new
identities that orphan saved gearsets (§3.3).

```bash
RELEASE=0 ./build-mac.sh          # permissive — mid-week dev builds
$env:RELEASE = '0'; .\build-windows.ps1
```

Use `RELEASE=0` when a data bump would otherwise block work. Never for anything
you hand to someone.

### Building for another architecture

There is no cross-compilation shortcut. To ship for Intel *and* Apple Silicon,
run `./build-mac.sh` natively on one machine of each and commit both
`bundled/darwin-amd64/` and `bundled/darwin-arm64/`.

A target with no `bundled/<platform>/` directory fails at **compile** time with
a "no such file" error from `go:embed`. That is the intended failure: there is
nothing meaningful to embed until somebody builds natively on that platform.

### Packaging for handoff

```bash
./package_release.sh
```

Archives each `dist/<platform>/` into `releases/v<version>/`. It refuses to
archive a `dist/` older than its `bundled/` — that would ship stale game data
under a fresh version number.

---

## 3. The ETL — rebuilding `catalog.db`

The ETL reads DDOBuilderV2's XML and produces the SQLite catalog the app ships.
It is **dev-only**: it never ships, is never invoked by the app, and needs no
third-party Python packages.

The build scripts run it for you. Run it by hand when you want to inspect the
result, or after bumping the submodule.

```bash
python3 -m etl                    # → catalog.db in the repo root
python3 -m etl --strict           # fail on unresolved identity drift
python3 -m etl --help             # every flag
```

Useful flags:

| Flag | Effect |
|---|---|
| `--out PATH` | where to write (build scripts pass `bundled/<platform>/catalog.db`) |
| `--strict` | unresolved drift fails the build; release builds pass this |
| `--source DIR` | a different DataFiles directory |
| `--catalog-version N` | explicit version; defaults to carrying the previous one forward, +1 when the content changed |
| `--drift-report PATH` | where to write the drift report |

Takes roughly 7 seconds and produces about 58 MB.

### 3.1 Updating the game data

```bash
cd data/ddobuilder
git fetch && git checkout <new-revision>
cd ../..
git add data/ddobuilder          # the submodule pointer is tracked
./build-mac.sh
```

If the build stops with **exit code 2**, the data renamed something the ETL will
not guess at. See §3.3.

### 3.2 Catalog versioning

`catalog_version` is what a future "update catalog" feature compares against,
and what decides whether an app update's bundled catalog replaces the installed
one. It is derived, not typed by hand: the ETL reads the catalog it is about to
overwrite and bumps only when the content hash actually changed.

That works because the build scripts write straight into the **committed**
`bundled/<platform>/catalog.db`, so even a clean checkout has the previous
number to count from. Seeing `catalog content is unchanged — keeping
catalog_version N` is the system working.

### 3.3 Identity drift

Every entity has a UUID minted once and recorded in `etl/identity_registry.json`
(tracked, ~5 MB). **Once minted, a UUID never changes** — that is what keeps
saved gearsets resolving after the game renames something.

When a name disappears and no *clean derivation* explains it (a tier prefix,
whitespace or case alone, or an explicit "version of" relationship), the ETL
refuses to guess. It writes `etl/drift/<revision>.md` and, under `--strict`,
exits 2 without writing a catalog and **without modifying the registry**.

To resolve:

1. Read the drift report. It ranks the closest current names and includes a
   block ready to paste.
2. Confirm against `DropLocation` and the effect list — a wrong answer silently
   rewrites what a saved gearset's item reference *means*, and nothing later
   catches it.
3. Paste into `etl/aliases.yaml` and fill each `now:` — a quoted new name, or
   `null` if it is genuinely gone.
4. Re-run.

```yaml
- kind: item
  was: "Bracers of the Sun Soul"
  now: "Legendary Bracers of the Sun Soul"

- was: "Gem of Many Facets"
  now: null        # confirmed removed from the game
```

`now:` is never optional. Removal has to be typed out, because no identity
decision is made by omission.

### 3.4 Expected warnings

One ambiguity is permanent and reported on every run: DDOBuilderV2 ships two
augments named `Twilight` in a `Cannith Armor Prefix` slot, differing only in
bonus type. The first in sorted file order is kept. This is upstream data, not a
defect here — worth noticing only if the count ever changes.

---

## 4. Where things live at runtime

| Path | What | Lifecycle |
|---|---|---|
| `<user data>/DDOGearsetOptimizer/catalog.db` | game data | seeded from the app; replaced by an update |
| `<user data>/DDOGearsetOptimizer/app.db` | **your builds and history** | created once, migrated forward, never recreated |
| `<user data>/DDOGearsetOptimizer/gearsets/` | `.ddogearset` exports | yours |
| `<user cache>/ddo-solver/<version>-<hash>/` | extracted solver | rebuilt on demand; safe to delete |

`<user data>` is `~/Library/Application Support` on macOS, `%APPDATA%` on
Windows, `${XDG_DATA_HOME:-~/.local/share}` on Linux.

**`app.db` is the one irreplaceable file.** Nothing regenerates it. Back it up
if you care about your builds.

Overrides, for development:

```bash
DDO_CATALOG_DB=/path/to/catalog.db   # which catalog to read
DDO_APP_DB=/tmp/scratch.db           # never point this at your real app.db
DDO_GEARSET_DIR=/tmp/exports         # where exports land
```

---

## 5. Verification

Run before anything you hand to someone:

```bash
go build ./... && go vet ./... && go test -count=1 ./...
python/.venv/bin/python -m pytest python/tests -q
cd frontend && npx svelte-check --threshold error
```

Two checks deserve naming, because they guard things nothing else does:

**5.1 The parser snapshot** — 30 canonical digests over the full corpus under 9
restriction combinations. If it moves, a number changed.

```bash
python/.venv/bin/python scripts/parser_snapshot.py verify-catalog bundled/darwin-arm64/catalog.db
```

**5.2 The oracle differential** — 14 real saved gearsets, each with the answer
the pre-0.5.1 implementation gave, replayed through the current one. It is the
only thing standing between the old numbers and the new, and the mode that
produced those answers no longer exists, so **the fixtures cannot be
regenerated**. Included in the pytest run above; on its own:

```bash
python/.venv/bin/python -m pytest python/tests/test_oracle_differential.py -q
```

**5.3 `go:embed` cannot carry symlinks.** PyInstaller's output contains four,
and embedded they simply vanish — which shipped a solver that could not start
for an entire release. The build scripts record them in
`bundled/<platform>/.symlinks.json` and the app recreates them at extraction. If
you ever stage a solver tree by hand, regenerate that manifest or the app will
not start.

---

## 6. Common problems

| Symptom | Cause |
|---|---|
| ETL exits 2 | Unresolved identity drift — §3.3 |
| `no game data at …` | Submodule not checked out: `git submodule update --init --depth 1` |
| `glpsol not found` | GLPK missing on the build machine — re-run `./install.sh` |
| `expected python/dist/solver/solver` | `solver.spec` lost its `COLLECT` step (that is the `--onefile` layout) |
| "Failed to load Python shared library" | Symlink manifest missing or stale — §5.3 |
| Frontend types disagree with Go | Run `wails generate module` after every Go struct change |
| `codesign` fails on macOS | Anaconda's `install_name_tool` shadowing Apple's; the build scripts use absolute `/usr/bin` paths for exactly this reason |
| A button silently does nothing | Something reached for `window.confirm`/`alert`/`prompt`. Wails' webview never shows them and `confirm` returns false, so the guarded code never runs. Use `showToast(text, kind, [{label, onClick}])`; `TestFrontendUsesNoNativeDialogs` enforces it |

`wails generate module` is worth repeating: `frontend/tsconfig.json` excludes
`wailsjs/`, so stale bindings type-check clean and misbehave at runtime.
