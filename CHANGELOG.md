# Changelog

All notable changes to DDO Gearset Optimizer are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)  
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [0.2.0] — 2026-08-05

### Added

**Tiered Priority Solver**
- Replaces the flat weighted-sum stat-priority model with a 5-tier sequential
  lexicographic solve: tier 1 is maximized first, its achieved value locked,
  then tier 2 is maximized subject to that lock, and so on through tier 5
- Upper-bound-normalized attainment weighting so stats of very different
  natural magnitude (e.g. weapon crit multiplier vs. Ranged Power) can share a
  tier meaningfully
- Two-role consolidation stage that empties non-load-bearing slots once every
  tier lock is satisfied — fewer, more meaningful items instead of padding
  every slot
- Post-solve reconciliation pass so displayed realized stats always match the
  actual equipped gearset
- Cold-callable slot alternatives (`GetSlotAlternatives`) — ranks 3–10
  alternative items for a single slot without a full re-solve
- Weapon combat properties (critical multiplier, threat range, base dice,
  weapon damage) now usable as tier priorities, scoped to the main weapon hand
- New `TierReport` results view: per-tier stage status, consolidation and
  reconciliation summaries, unmet tier-4 stats, unmatched priorities

**Item Detail**
- Full structural item detail (buffs, weapon/armor profile, augment slots,
  set bonuses, clickies, acquisition) driven by new Go-side XML parsing,
  replacing the old name-only item lookups
- Per-file fault tolerance in the item/augment/filigree/set-bonus parsers —
  one malformed file no longer aborts the entire cache load

**Frontend**
- Stat priorities are now entered via five tier lanes with a drill-down stat
  picker, replacing the old 1–100 weight sliders and the unused caster
  checkbox grid
- Stat-set presets, loadable from a hand-editable `stat_sets.json` override
- Hand-rolled accordion component for the large form sections

**Release tooling — fully self-contained, portable builds**
- The shipped app now bundles everything it needs to run: the compiled
  Python solver, `glpsol`, and `glpsol`'s own shared-library dependencies
  (previously an unbundled runtime dependency hardcoded to one specific
  Homebrew install path — see Fixed, below). Verified end-to-end with
  `/opt/homebrew` stripped from `PATH` entirely: extraction, `glpsol`
  invocation, and a full solve all still succeed
- Per-platform bundles live under `bundled/<goos>-<goarch>/` and are embedded
  at compile time via `embed_<goos>_<goarch>.go` (Go's filename-based build
  constraints — only the file matching the actual build target compiles, so
  one repo checkout can hold multiple platforms' bundles simultaneously
  without conflict)
- `build_releases.sh` rebuilds the Python solver, locates the host's
  `glpsol`, and (on macOS) rewrites its dylib references to
  `@executable_path` via `install_name_tool` so it needs nothing installed
  on the machine that runs it, then runs a native `wails build` and prints
  the output path. PyInstaller and `glpsol` both being platform-native
  binaries, neither can be cross-compiled — building for a new platform
  means running this script natively on a machine of that platform once and
  committing the resulting `bundled/<goos>-<goarch>/` directory. Linux
  staging is implemented (via `ldd`) but unverified from this session, which
  only had macOS/arm64 available to test against; Windows staging isn't
  automated and is documented as a manual step
- `install.sh` sets up everything needed to build after a fresh clone (Go,
  Node, a Python venv with `pulp`/`pyinstaller`, GLPK, and on macOS the
  Xcode Command Line Tools `build_releases.sh` needs for the
  `install_name_tool` step), and checks for SSH access to the DDOBuilderV2
  repo the app will clone on first run (see Fixed, below)
- `package_release.sh` archives whatever's staged in `dist/` into
  `releases/v<version>/`

### Fixed

- **Item Search ("search items by stat") returned a validation error on
  every call**: `Stat priority validation failed: no stat priorities were
  provided.` `python/solver.py`'s `mode == "stat_search"` branch (which
  correctly bypasses the normal stat-priority validation) was already
  correct in source, but the **bundled `python/dist/solver` binary embedded
  via `go:embed` in `app.go` predated that code** and was still running the
  old path that unconditionally requires `stat_priorities`. Rebuilt
  `python/dist/solver` via PyInstaller and verified directly against the
  binary (`echo '{"mode":"stat_search",...}' | ./dist/solver`) that
  `stat_search` now returns real matches. Note for next time: a `strings
  python/dist/solver | grep <marker>` check is **not** a reliable way to
  confirm new code is present — the build is UPX-compressed, so plaintext
  markers don't show up in the packed binary even when the code is there;
  always verify by actually invoking the binary. See
  `docs/PHASE10_HANDOFF.md` "Loose Ends" — there is still no automated check
  tying the embedded binary's freshness to the Python source, so this class
  of bug (Go/Python both correct in source, stale compiled artifact) can
  recur after any `python/optimizer.py` or `python/solver.py` change that
  isn't followed by a solver rebuild before `wails build`.

- **GLPK was hardcoded to `/opt/homebrew/bin/glpsol`**, a real install path
  that only ever existed on one specific Apple-Silicon-Homebrew machine —
  the app could not solve anything anywhere else, and GLPK had to be
  pre-installed on the *end user's* machine, not just the build machine.
  `python/optimizer.py`'s `_glpk_cmd()` now resolves `glpsol` from a
  `GLPSOL_PATH` environment variable that `app.go` sets to the bundled,
  extracted copy (falling back to a `PATH` lookup so `python solver.py`
  still works standalone in a dev checkout). A missing/misresolvable
  `glpsol` now fails loudly and immediately from `solver.py`'s `main()`
  with an actionable message, instead of silently degrading into a generic
  "no feasible solution" from deep inside the solve loop.

- **The DDOBuilderV2 item/augment/filigree XML data source was hardcoded**
  to `/Users/jorgecosgayon/dev/ddo/DDOBuilderV2/Output/DataFiles`, identically
  in `app.go` and `python/solver.py`, and had to already exist there — the app
  only functioned on this one developer's machine. `app.go` now has
  `ensureDDOBuilderData()`: on startup (and from the existing "Update External
  Sources" button), it clones `git@github.com:Maetrim/DDOBuilderV2.git` into
  a project-relative `./DDOBuilderV2` (gitignored) if it isn't there yet, or
  `git pull`s it if it is. `ddoDataRoot` is now the relative path
  `DDOBuilderV2/Output/DataFiles`; `python/solver.py`'s `base_dir` resolves
  the same way, preferring a `DDO_DATA_PATH` env var that `app.go` sets to the
  absolute path (for robustness independent of the subprocess's working
  directory) and falling back to the same project-relative default for
  standalone `python solver.py` usage. Verified end-to-end from a state with
  no `./DDOBuilderV2` present at all: `ensureDDOBuilderData()` cloned it for
  real (20,308 files over SSH), and a full solve then ran successfully with
  no `DDO_DATA_PATH` override, using only the project-relative fallback.
  Requires SSH access to that repo on whatever machine runs this — `install.sh`
  checks for that access and warns if it can't confirm it.

## [0.1.0] — 2026-08-04

### Added

**Core ILP Optimizer**
- Integer Linear Programming solver (PuLP + GLPK) for mathematically guaranteed optimal gear selection
- Weighted stat priorities (1–100) — higher weights drive the objective function
- Build type support: Melee, Ranged, Caster, Tank
- Weapon style support: TWF, THF, SWF, Sword & Board, Bow, Repeating Crossbow, Great Crossbow, Dual Crossbow, Thrown, Shuriken
- Armor restriction filtering: Any, Cloth, Light, Medium, Heavy
- Expansion pack exclusion — toggle any expansion to prevent items from being selected
- Raid item limit constraint (0 = no raid items, -1 = unlimited)
- Swashbuckling and Runearm slot support
- Caster spell power and spell school targeting
- Minor Artifact slot reservation and filigree slot count (1–5)
- Dinosaur Bone artifact forced selection mode
- Gem of Many Facets exclusion option

**Data Pipeline**
- Reads directly from DDOBuilderV2 XML output files (items, augments, filigrees, quests)
- Automatic item enrichment: Wiki URLs, expansion pack tags, raid flags
- Hot-reload via "Update External Sources" button (runs `git pull` on DDOBuilderV2, reloads caches)

**Gearset Editor**
- Per-slot item selection with real-time search
- Augment slot dropdowns (color-filtered: Yellow, Blue, Red, Orange, etc.)
- Alternative items per slot (top alternatives from constrained re-solves)
- Calculate Stats button — evaluates current manual configuration without re-running full optimization
- Pre-filled items and augments are locked in the ILP; solver builds the rest around them

**Sentient Filigrees**
- Dedicated Filigrees tab for Sentient Weapon (10 slots) and Minor Artifact (1–5 slots)
- Real-time filigree search with set-name filter dropdown
- Filigree stacking rules enforced by ILP:
  - Same filigree: at most once per weapon, at most once per artifact
  - Same filigree may appear in both weapon AND artifact (cross-item stacking)
  - AUTO badge shows solver-recommended filigrees

**Summary & File Management**
- Priority effects panel (sorted by weight, highest first)
- Full effects breakdown grouped by stat (items + augments + set bonuses + filigrees)
- Active set bonuses panel
- `.ddogearset` file format (v1.2, JSON) — stores full configuration + solver result
- Timestamped auto-generated filenames: `<Name>_<BuildType><WeaponStyle>Gearset_<timestamp>.ddogearset`
- Load/Save round-trip: all configuration parameters fully restored on load
- Backwards compatible with legacy `.json` gearset files

**Documentation**
- `docs/USAGE.md` — end-user guide
- `docs/ENGINEERING.md` — developer reference with architecture diagram
- `docs/plans/retrospective.md` — detailed phase retrospective (Phases 1–6)

### Technical
- Wails v2 desktop app (Go backend + Svelte/Vite frontend)
- Python 3.11 solver compiled to standalone binary via PyInstaller (embedded in Go binary)
- GLPK solver via homebrew (`/opt/homebrew/bin/glpsol`)
- Glassmorphism dark-mode UI design
