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
- One build script per platform — `build-mac.sh`, `build-linux.sh`,
  `build-windows.ps1` (replacing a single cross-platform `build_releases.sh`,
  which got hard to keep straight once the platform-specific staging logic
  diverged this much) — each rebuilds the Python solver, locates the host's
  `glpsol`, stages it (+ dylibs/DLLs, patched via `install_name_tool` on
  macOS) into `bundled/<platform>/`, and runs a native `wails build`.
  PyInstaller and `glpsol` both being platform-native binaries, neither can
  be cross-compiled — building for a new platform means running that
  platform's script natively once and committing the resulting
  `bundled/<platform>/` directory. Linux staging is implemented (via `ldd`)
  but unverified this session (no Linux machine available to test against);
  Windows staging is implemented and verified by careful manual review only
  (no Windows machine available either — see the PowerShell-specific notes
  below)
- Every build script now finishes by copying its own finished, self-contained
  build into `dist/<platform>/` automatically (e.g. `dist/darwin-arm64/`,
  `dist/windows-amd64/`) — on Windows this includes an NSIS installer too, if
  `makensis` is available. That directory is the literal hand-off point:
  copy it, run what's inside, nothing else required. `package_release.sh`
  now archives each `dist/<platform>/` folder as a whole into
  `releases/v<version>/<platform>.{zip,tar.gz}`, for e.g. attaching to a
  GitHub release — it no longer expects a flat `dist/` you populate by hand
- `build-windows.ps1` never requests or requires elevation. Chocolatey
  installs (and the Chocolatey bootstrap itself, if missing) usually do need
  an elevated shell on Windows, but the script doesn't assume that up front —
  it tries unelevated first, and only if that fails does it print the exact
  command to run once in a separate elevated window, then tells you to close
  that window and re-run the script normally. This also sidesteps
  PyInstaller's own warning against being run elevated at all, since nothing
  in the script (PyInstaller included) ever runs elevated now
- `install.sh` sets up everything needed to build after a fresh clone (Go,
  Node, a Python venv with `pulp`/`pyinstaller`, GLPK, and on macOS the
  Xcode Command Line Tools the mac build script needs for the
  `install_name_tool` step), and checks network access to the DDOBuilderV2
  archive the app will fetch on first run (see Fixed, below)

### Fixed

- **`wails build -o DDOGearsetOptimizer` on Windows produced a file with no
  extension at all** (`DDOGearsetOptimizer`, not `DDOGearsetOptimizer.exe`),
  discovered from a real Windows build run. Unlike the assumption
  `build-windows.ps1` was originally written against, Wails does not append
  `.exe` to `-o` on Windows itself — it writes exactly the name given. Both
  the plain build and the `-nsis` installer build now pass
  `-o DDOGearsetOptimizer.exe` explicitly.

- **`ensureDDOBuilderData()` required a `git` binary at all**, which isn't
  guaranteed to be installed on every machine that runs the app — confirmed
  on a real Windows build machine that has none, and we deliberately don't
  want to assume any particular package manager is available to install one
  either (see `docs/DDOBUILDER_FETCH_WITHOUT_GIT_PLAN.md`). An intermediate
  fix (SSH → HTTPS clone URL, since the repo turned out to be public) was
  only a partial improvement — it still needed `git` itself. Replaced the
  whole mechanism with a plain HTTPS download of GitHub's generated zip
  archive (`codeload.github.com/Maetrim/DDOBuilderV2/zip/refs/heads/main`),
  extracted with the Go standard library (`net/http` + `archive/zip`) — no
  `git`, no credentials, no new dependencies of any kind, on any platform.
  New file `ddobuilder_fetch.go`:
  - Downloads to a temp file, extracts into a staging directory, and only
    replaces `./DDOBuilderV2` after every entry extracts successfully — a
    failed download or a crash mid-extraction leaves whatever was already
    there completely untouched (includes a zip-slip path-traversal guard on
    every extracted entry).
  - The archive is 79MB / 20,521 files — too large to re-download on every
    "Update External Sources" click without a way to skip it when nothing
    changed. Before fetching, checks GitHub's lightweight commits API for
    the latest commit SHA on `main` and compares it against a marker file
    (`.ddobuilderv2_commit`, project-root, gitignored) recorded after the
    last successful fetch; skips the 79MB download entirely if they match.
  - `ensureDDOBuilderData(checkForUpdates bool)` — app startup only fetches
    when `./DDOBuilderV2` is missing outright (no extra network call once
    it's already there); the "Update External Sources" button is the only
    path that pays for the staleness check, since checking is the point of
    that button.
  - Verified end-to-end (not just unit-level): a from-scratch fetch (13.5s,
    real data, `python/dist/solver` parsed it identically to a git
    checkout), an up-to-date skip (0.98s — confirms it doesn't silently
    redownload), and a forced-stale re-fetch that correctly re-downloads and
    updates the marker.
  - `install.sh` and `build-windows.ps1`'s reachability checks updated to
    match — plain HTTPS requests (`curl`/`Invoke-WebRequest`) against the
    same `codeload.github.com` endpoint the app itself uses, no `git`
    involved in the check either.

- **`python/solver.spec` was never actually committed** — `.gitignore` had a
  blanket `python/*.spec` rule that silently excluded it. Every build script
  runs `pyinstaller --noconfirm solver.spec`, so a fresh clone couldn't
  rebuild the embedded solver at all. Narrowed the ignore rule and committed
  the file, matching the existing reasoning for keeping `python/dist/solver`
  checked in.

- **The built macOS app failed to open at all**: "You can't open the
  application 'DDO Gearset Optimizer' because it may be damaged or
  incomplete." Root cause was `wails.json`'s `info.comments` field —
  `"...Dungeons & Dragons Online"` — containing a literal, unescaped `&`.
  Wails writes that string directly into `Info.plist`'s XML with no
  escaping, producing genuinely malformed XML
  (`plutil -lint Info.plist` reported "unknown ampersand-escape sequence").
  macOS can't parse a malformed `Info.plist` at all, which is exactly what
  produces "damaged or incomplete" rather than a normal launch or even the
  usual unsigned-app prompt. Changed the string to "...Dungeons and Dragons
  Online"; `plutil -lint` now reports OK, and the app opens via both
  `open` and Finder double-click.

  Two real, separate problems were found and fixed alongside this while
  debugging it, neither of which was the actual cause of this specific
  error but both worth having fixed:
  - `build_releases.sh`'s macOS staging step called bare `otool`/
    `install_name_tool`, which on a machine with Anaconda (or any conda
    install) ahead of `/usr/bin` on `PATH` resolves to Anaconda's bundled
    `cctools-port` reimplementation instead of Apple's real tools — its
    `install_name_tool` logs that it's "generating fake signature," i.e.
    not a real Apple code signature. Now hardcoded to `/usr/bin/otool` /
    `/usr/bin/install_name_tool` so this can't silently happen again on any
    machine with a conda install on `PATH`.
  - The built `.app` was **entirely unsigned** (`codesign -dv` reported
    "code object is not signed at all") — Wails does not sign macOS builds
    by default. `build_releases.sh` now ad-hoc signs the finished bundle
    (`codesign --force --deep --sign -`) and verifies the signature.
    This is ad-hoc only (no paid Apple Developer ID here) — `spctl -a`
    still reports "rejected" for a fresh/quarantined copy, which is the
    normal, expected, bypassable Gatekeeper prompt (right-click → Open, or
    System Settings → Privacy & Security → Open Anyway) for any
    unnotarized indie app. That prompt is not the bug; "damaged or
    incomplete" was.

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
