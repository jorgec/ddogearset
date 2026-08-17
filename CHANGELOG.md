# Changelog

All notable changes to DDO Gearset Optimizer are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)  
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [0.5.3] — 2026-08-17

### Added

- **Gear Checklist tab** in the centre pane alongside Summary and Harness.
  Lists every item in the solved gearset with a checkbox, the equipment slot,
  adventure pack, and drop location. The quest name in each drop location is a
  clickable link that opens the corresponding ddowiki page in the real browser.
  If a Trove CSV is loaded, items found in the inventory are auto-checked;
  the user can also check or uncheck any item manually. Checked state persists
  in `checklist_owned` on the config and is saved/loaded with the gearset.

- **Proc detection fully operational for all proc types.** Shape A procs
  (Lightning Lash, Alchemical Attunements, etc.) are now stored in catalog.db
  during ETL and detected at query time. Previously the ETL called extraction
  with empty priorities, so proc presence flags were silently dropped.

- **Augment alias mapping for procs.** Isle of Dread fangs (Flamefang,
  Icefang, Sparkfang, Meltfang) and Dolorous/Woeful Legendary augments now
  resolve to the proc they actually grant (e.g. Meltfang → Alchemical Earth
  Attunement). 14 aliases added in `PROC_AUGMENT_ALIASES`.

- **Stat picker is now a full-screen modal** instead of a small positioned
  popover, with a dark backdrop and backdrop-click dismiss.

### Fixed

- **"Location unavailable" on every stat source in the Summary after a solve.**
  The optimizer's solve path emitted `allEffects` (display strings) but not
  `allEffectsDetail` (structured source data). The Summary's `locateSource()`
  needs `allEffectsDetail` to resolve which slot each source comes from;
  without it every source showed "Location unavailable". Now emitted by both
  the solve and recalculation paths.

- **"Legendary Steam" missing from `PROC_ZERO_EFFECT_AUGMENT_NAMES`.**
  Dolorous Dimlight (Legendary) grants it but it was not in the whitelist.

### Fixed (pre-existing)

- **Every filigree slot rendered "Empty" once Filigrees became a tab.** A build
  loaded from `app.db` showed none of its filigrees, though all of them were
  stored. The data was intact at every layer below the UI — the `.ddogearset`
  file, the `gearset_filigree` rows, and `LoadBuild` itself all returned the
  full set — because the bug was reactivity, not storage.

  `getSlotDisplay()` read `$configStore`/`$resultStore` off the closure and was
  called from a `{@const display = getSlotDisplay(idx, …)}` inside the each
  block. Svelte cannot see through a function call: the compiled
  `get_each_context` depends on `getSlotDisplay` and `idx` only. Confirmed
  against the compiled output — `$configStore` sits at ctx index 14 (dirty bit
  `16384`) while the each blocks re-run their context on masks `8063`/`8191`
  (bits 0–12), and `$resultStore` isn't in the ctx at all. The values were
  computed once at mount and never recomputed.

  This was latent the whole time and [0.5.2]'s Filigrees-into-a-tab change
  exposed it: inside the drawer's `{#if $drawerOpen}` the component was
  destroyed and recreated on every open, so it always remounted with current
  data. As a permanently-mounted tab toggled by `class:hidden`, it never
  remounts, so the staleness became permanent.

  Fixed by deriving `artifactDisplays`/`weaponDisplays` in `$:` statements that
  name both stores explicitly, and iterating those arrays directly; the update
  block now recomputes on mask `98304` = `$configStore` + `$resultStore`.
  Verified by mounting the real component against a real saved build and
  updating the store *after* mount — the exact sequence that broke — and by
  reverting the fix under the identical harness to confirm the check genuinely
  fails without it.

## [0.5.2] — 2026-08-11

UI/UX pass over the app.db-backed workflow, plus three bugs found by actually
running the app for the first time since the rewrite — none caught by the test
suite, because none of them crossed the boundary where the loss happened.

### Added

- **Check Inventory** button in the Gear Sockets header. Badges every socketed
  item green/red against a loaded Trove CSV — **exact, case-sensitive**
  matching on purpose, because that's precisely what the solver does
  (`name not in owned_names`); anything looser would badge an item green that
  the solver then refuses to use with "restrict to owned" on. Reactive
  (swapping an item re-badges it) and self-clearing if the CSV is unloaded.
- **New** button. Resets parameters, gear and the last result, with a
  confirmation. Deliberately leaves the loaded Trove inventory alone — that's a
  file you loaded, not part of the build.
- **Open DB** replaces the saved-builds dropdown with a table in the Summary
  panel: name, created date, build type, slot count, and per-row Load/Delete.
  Ordered by `created_at` (not `updated_at`) so a build's position doesn't move
  just because it was opened.
- **Wiki links on item-search results.** Each source name in the stat-search
  panel opens `https://ddowiki.com/index.php?search=<name>&title=Special:Search&go=Go`
  in the real browser — the `go=Go` form jumps straight to the page on an
  exact match and falls back to search otherwise. Opened via `BrowserOpenURL`,
  not `<a href>` — see Fixed, below, for why that distinction is load-bearing
  in a Wails webview.

### Changed

- **Clear now explicitly scoped to equipment only** (it already was; this pins
  it with a test). Priorities, build type, level cap, armor restriction and
  every other setting survive a Clear — New is the button that resets those.
- **Filigrees moved into the Gearset panel** as a `Gear` / `Filigrees` tab
  strip, instead of living in the Configuration & Auto-Solver drawer next to
  Build & Priorities. Gear and filigrees are one task, so they now share one
  panel; both tabs stay mounted (only visibility toggles), matching the
  keep-mounted convention used for the drawer and the right-hand readouts.
  The drawer opens straight into Build & Priorities now, with no sub-tab bar.

### Fixed

- **The manual stat picker's "Pact Dice" entry, and the Warlock (Eldritch
  Blast) preset's Tier 1 priority, both matched nothing in the real corpus.**
  `pact dice` isn't a substring of any `raw_type`/`raw_target` in the catalog
  — checked directly against `catalog.db` — so the priority sat there doing
  nothing. The real sources are "Power in Pact" (Enhancement bonus to pact
  dice) and `EldritchBlastD6`/`EldritchBlastD8`
  (Artifact/Profane/Fortune/Stacking bonuses to Eldritch Blast dice size);
  `power in pact` and `eldritch blast` both substring-match through the
  existing, unmodified matcher — verified against `normalize_stat_name`
  directly, not just asserted. Preset- and taxonomy-content only; no matching
  logic changed.
- **Handwraps could be routed into Weapon2, leaving both slots filled.**
  Handwraps occupy both hands, but `weapon_style`'s `twf_weapons` candidate
  pool legitimately makes handwraps eligible for Weapon1 *and* Weapon2 (a
  monk's unarmed chain is a two-weapon-fighting style for feat/enhancement
  purposes), and nothing stopped the ILP from filling both. Fixed with two
  symmetric hard constraints — handwraps in either slot now locks the other
  empty. An initial one-directional version left an escape route the solver
  actually took (moving handwraps into Weapon2 to keep an unconstrained
  offhand in Weapon1); five new tests cover both directions, the
  non-equipped case, and that the constraints don't appear at all without a
  handwraps item in the pool. Verified against the real shipped solver
  binary and catalog, not just the Python unit tests.
- **GearsetEditor's Recalculate button sent search-restriction fields**
  (`armor_restriction`, `weapon_style`, `max_search_time`, and the rest of
  `OptimizationPayload`) on every recalculation, tripping the solver's own
  "recalculate evaluates gear you already have, so it cannot accept search
  restrictions" validation. Summary.svelte's Calculate flow already narrowed
  to `RecalculationRequest`, which has nowhere to put a restriction — the
  Recalculate button just never got the same treatment. Ported the same
  narrowing and switched to `RecalculateGearset`.
- **Pack attribution silently failed on every packaged install** — reported
  from a real Windows install's log (`Failed to load pack mappings ... open
  data/PackMappings.json: The system cannot find the path specified`).
  `InitEnrichment` read the file via a plain `os.Open` resolved against the
  process's working directory, which is the repo root under `wails dev` but
  something else entirely once packaged — the sibling `stat_sets.default.json`
  two lines above it had been `go:embed`-ed the whole time; this one just
  wasn't. It shipped unnoticed because the failure only costs pack
  attribution rather than crashing, so nothing looked broken until someone
  checked where an item dropped. Fixed by embedding the file and parsing
  bytes directly, removing the failure mode instead of relocating it. New
  regression test runs `loadCaches` from a directory containing nothing but
  itself — what a packaged app's launch directory actually looks like — and
  confirms all 8,474 real items carry pack attribution.
- **The packaged solver could not start at all** —
  `Failed to load Python shared library`. `go:embed` silently skips symbolic
  links, and PyInstaller's `--onedir` output has four (`_internal/Python` and
  three inside `Python.framework`); they were staged and tracked by git but
  never embedded, so the extracted tree was missing them. Broken since the
  `--onedir` switch landed (0.5.0 Phase 7) through every test run since — the
  one test that checked extraction asserted "every *embedded* file was
  extracted," trivially true of files that were never embedded. Fixed with a
  manifest recorded at build time and recreated at extraction; the new test
  runs the extracted binary rather than just checking file placement.
- **Three solver result fields were silently dropped at the Go boundary** —
  `otherStats`, `allEffectsDetail` and `warnings` were emitted by the solver
  and absent from Go's `ResultPayload` struct, so `encoding/json` discarded
  them on unmarshal. Symptom: the "Duplicated Stat Sources" panel showed `0`
  and "Location unavailable" for every row, and run history recorded no
  effects or warnings (the recorder had re-marshaled the already-truncated
  struct and searched for fields that were already gone). All three declared
  now; the new test recalculates through the real solver and asserts they
  survive.
- **Delete (and New) silently did nothing.** Wails' webview does not implement
  the JavaScript dialog delegates, so `window.confirm` returns `false` without
  ever showing a dialog — both buttons were guarded by one and returned early
  on every click, with no error anywhere. This app has always asked
  confirmation via an action toast; both now use that instead. Guarded by a
  new test that scans the frontend for `confirm`/`alert`/`prompt`, and a
  sibling test for the same-family trap of a plain `<a href="https://…">`
  navigating the webview itself away from the app.

### Docs

- **`docs/housekeeping.md`** — install, per-platform builds (and why none of
  them cross-compile), the ETL and identity-drift workflow, where user data
  lives on disk, and the verification steps that guard things nothing else
  does (the parser snapshot, the oracle differential, the symlink manifest).

## [0.5.1] — 2026-08-11

`app.db` and recalculation — the user's builds and gearsets move out of JSON
files in the process working directory and into a real, versioned database,
and evaluating a gearset stops borrowing the ILP solver. Full writeup:
`docs/0.5.1/RETROSPECTIVE_AND_HANDOFF.md`.

### Added

- **`app.db`**, beside `catalog.db` in the user data directory: builds,
  priorities, gearsets and (new) run history, schema-versioned and migrated
  forward — never recreated. `.ddogearset` becomes an **export/import**
  format instead of the source of truth; import is non-destructive and
  idempotent (re-importing a file already imported is a no-op; content-hash
  identity means an edited file imports as a new build rather than
  overwriting).
- **The two-node gearset model** — `equipped` and `suggested` are different
  database rows, not different fields of shared state. A solve only ever
  writes `suggested`; only **Accept All** moves rows across, and it refuses
  to promote an empty suggestion. This retires *"Optimize → Save wrote an
  empty gearset"* by construction rather than by care — the old bug was
  possible because a solve's output and the user's own gearset lived in one
  place, so whichever wrote last won.
- **`mode: "recalculate"`** replaces `mode: "calculate"`. Evaluating a
  gearset the user already has is now direct arithmetic
  (`python/rules/evaluate.py`, ~275 lines) over the same two functions that
  built the candidate pool's scoring all along — no ILP, no `glpsol`, no
  candidate pool, and therefore no way for a search restriction to reach an
  evaluation at all: `RecalculationRequest`'s Go type has nowhere to put one,
  and the Python entry point rejects a payload that carries one by name.
  Measured: **0.55–0.66 s warm**, down from 2.7–5.8 s for the ILP that was
  solving a model whose answer was already determined.
- **Run history** — every solve and recalculation is recorded (mode,
  timestamp, the exact catalog revision it ran against, success/failure), in
  one transaction or not at all. A failed run is recorded too, with no stat
  rows — that's the part usually skipped because a failure feels like
  nothing to store, and it's exactly what's useful six weeks later.

### Fixed

- **A gearset with two filigrees sharing a base name could not be evaluated
  at all** under the old `calculate` mode — `optimizer.py:1817` limits one
  filigree per base name per bucket, a *search* heuristic (don't propose two
  variants of the same thing) that was incorrectly also applied while
  evaluating gear a real user already owned. `recalculate` has no such
  constraint, because it has no candidate pool to apply one to; the
  previously-unevaluatable fixture now returns full numbers plus warnings in
  well under a second.
- **The oracle differential — the only thing standing between the pre- and
  post-rewrite numbers — had never actually been run.** The existing script
  only checked that its 14 captured fixtures were internally consistent; a
  real compare-mode replay was built first (Phase 0, before anything else
  depended on it) and failed on all 12 replayable fixtures on the very first
  run: every *value* was identical, but four result lists came back in a
  different (immaterial) order due to the 0.5.0 XML→SQL migration. Recorded
  as an explicit, tested ordering allowance rather than silently re-sorted.
- **`capture_oracle.py` had been silently broken since 0.5.0** (still reading
  an environment variable the solver no longer honored) and, on its first
  working run this cycle, overwrote one of the 14 irreplaceable oracle
  fixtures with its own failure record before the bug was caught. Restored
  from git; the script now refuses to overwrite a fixture that already holds
  a successful capture without an explicit `--force`.

## [0.5.0] — 2026-08-10

The ETL rewrite. The app no longer reads DDOBuilderV2's XML at runtime, at
all, on any platform — a dev-only pipeline now compiles it once into a single
SQLite `catalog.db` that ships inside the app. Full writeup:
`docs/0.5.0/RETROSPECTIVE_AND_HANDOFF.md`.

### Added

- **`catalog.db`**: a normalized SQLite catalog (18 tables, ~8,500 items,
  ~44,000 effects) built by a new dev-only `etl/` package
  (`python -m etl`) from a pinned `data/ddobuilder` git submodule. Every
  entity gets a UUIDv5 minted **once** and recorded in a checked-in identity
  registry (`etl/identity_registry.json`, ~19,400 entities) — a later game
  update that renames something appends to that entity's alias list rather
  than minting a new identity, which is what lets a saved gearset keep
  resolving across game patches. An unexplained rename (no clean derivation —
  not a tier-prefix change, not whitespace/case, not an explicit "version of"
  relationship) stops the build under `--strict` and writes a drift report
  instead of guessing.
- **The catalog ships embedded in the binary** (`go:embed`) and is seeded
  into the user data directory on first run — no network access, ever, and no
  `DDOBuilderV2` checkout on the end user's machine at all. `catalog_meta`
  carries a `catalog_version` (auto-derived from a content hash, so a
  same-content rebuild doesn't bump it) for a future "update the catalog
  without updating the app" feature.
- **`--onedir` PyInstaller packaging** replaces `--onefile`: **3.8 s of
  per-invocation extraction overhead down to effectively zero.** The old
  `--onefile` binary re-extracted its entire ~8 MB payload to a temp
  directory on *every single solve*; `--onedir` extracts the bundled solver
  tree once into a version-stamped cache directory and reuses it thereafter.
- **`docs/0.5.0/RETROSPECTIVE_AND_HANDOFF.md`** — what the rewrite cost, four
  latent bugs the new differential-style gates caught before they shipped,
  and the invariants a future release must not break.

### Fixed

- **Multi-`<Item>` effect targets silently kept only the first target,
  dropping the rest** — `XMLEffect.Item` was `string`, not `[]string]`;
  fixed on the Go side and the catalog's `effect_target` rows are now
  positional (`position = 0` for first-wins parity with the prior behavior,
  with the full list available).
- **A real augment-identity collision surfaced by the ETL's stricter
  validation**: two distinct `Twilight` augments share a name and a
  `Cannith Armor Prefix` colour slot, differing only in bonus type. This is
  genuine upstream data ambiguity, not a bug in the pipeline — resolved
  deterministically (first in sorted file order wins) and reported on every
  build rather than silently merged.

### Removed

- **The runtime `DDOBuilderV2` fetch** (`ensureDDOBuilderData`,
  `ddobuilder_fetch.go`, the "Update External Sources" button) and the Go/
  Python XML parsers that read it directly at runtime — both fully replaced
  by the embedded, pre-built catalog. The app's only remaining runtime data
  dependency is `catalog.db`.

---

## [0.4.4] — 2026-08-09

### Fixed

- **Hireling stats were credited to the player.** Reported as an inexplicable
  filigree pick: the solver equipped two copies of "The Cry of Battle: +1
  Constitution" even though Constitution was only Tier 3 and filigrees count
  toward Tier 1 alone. It was not chasing the Constitution — filigrees also act
  as set PIECES, and set bonuses they activate are tagged as set sources rather
  than filigree ones, so they legitimately count at every tier. The bug was
  what that set grants: `HirelingPRR +20` / `HirelingMRR +20`, defence for your
  HIRELING. Since "prr" is a substring of "hirelingprr", both were credited to
  the player's own Tier-3 prr/mrr priorities, so the solver spent two filigree
  slots buying +40 of defence the character never receives — reported PRR 67
  against a real 47, MRR 61 against 41.

  A `Hireling*` buff now only matches a priority that says "hireling" (same
  per-priority gate as the 0.4.2 school saves and 0.4.3 skill groups). The
  whole family is four types: HirelingAbilityBonus, HirelingMeleePower,
  HirelingPRR, HirelingMRR.

## [0.4.3] — 2026-08-09

### Fixed

- **Skills could never be optimized for.** A blanket guard carried over from
  the original Phase 3 integration (`if 'skill' in typ/item/desc: return None`)
  dropped every skill buff before matching, so a Spellcraft or Disable Device
  priority found nothing — despite 992 well-structured `SkillBonus` buffs
  across 21 skills sitting in the data with real values and bonus types. The
  stat picker also offered no skills at all, so the priority could not even be
  expressed. Both halves fixed.

  The guard could not simply be deleted: the corpus also carries GROUP buffs
  typed like "Intelligence Skills - Exceptional Bonus" — a bonus to the skills
  governed by an ability, *not* to the ability score — and plain substring
  matching would let an `Intelligence` priority absorb them. Skills are now
  gated per-priority instead (only a priority naming a skill, or saying
  "skill", may claim a skill buff), the same targeted approach used for
  defensive school saves in 0.4.2.

### Added

- **Skills in the stat picker** — one flat, alphabetical "Skills" list holding
  all 21 individual DDO skills plus the in-game skill-GROUP bonuses
  ("Intelligence Skills", "Alluring Skills", "Nimble Skills", …). Bonus-type
  scoping works on them for free via the existing prefix mechanism, e.g.
  "insightful spellcraft skill" requires an Insightful-typed buff.

  Individual skills use a `"<skill> skill"` wire string rather than the bare
  name, because several bare names silently collide with unrelated stats —
  audited against the corpus, `heal` also matched HealingAmplification (183
  buffs) and HealingLore (88) against only 33 real Heal-skill buffs; `repair`
  matched Reconstruction/RepairAmplification/RepairLore; `hide` matched
  RoughHide. The buff text is literally `"<skill> skillbonus"`, so the suffix
  disambiguates and still matches. Constitution/Strength/Wisdom Skills are
  omitted: one corpus source each, all below the ML>=29 solver floor.

### Changed

- `build-mac.sh` now zips the finished app into `dist/<platform>/`, replacing
  any existing zip. Uses `ditto` rather than `zip` so symlinks, resource forks
  and the ad-hoc code signature survive the round trip.

## [0.4.2] — 2026-08-09

### Fixed

- **Defensive school saving throws were credited to offensive school
  priorities.** `Legendary Eyes of Enlightenment` carries `IllusionSave +11`
  (bonus type Resistance) — a saving throw *against* illusion, which does
  nothing for the DC of illusion spells you cast. Sharing the school's name was
  enough for the substring matcher to count it toward an offensive Illusion
  priority, inflating that stat's realized total (31 vs the correct 20 on the
  reported gearset). A buff whose structural type says "save" now only matches
  a priority that itself asks for a save or resistance; it stays selectable by
  name (`illusion save`) for anyone who wants the defensive stat. Affects the
  only three colliding types in the corpus: IllusionSave, "Illusion Save",
  EnchantmentSave.

## [0.4.1] — 2026-08-09

### Fixed

- **Bonus-type-scoped Spell Focus Mastery priorities reported "matched
  nothing"** (reported from a real saved gearset). `normalize_stat_name` adds
  the universal Spell-Focus-Mastery match terms to any priority containing
  "dc"/"focus" — correct, since SFM raises every school's DC — but they sat in
  the same flat list as the priority's own terms, and the matcher returns the
  first priority matching in user list order. So a "evocation spelldc"
  priority swallowed every SpellFocusMastery buff and starved the explicit
  "<bonus> spell focus mastery" priorities to zero sources. Match terms are now
  split into direct vs implied and evaluated in two passes: every priority gets
  a shot at a direct match before any may claim the buff by implication. A
  gearset listing only school DCs still credits SFM exactly as before. The
  defect predated the 0.3.5 feature that exposed it.
- **Removed three stat-picker options that could never match at endgame**,
  found by re-auditing the 0.3.5 bonus-type lists against the ML>=29 floor the
  solver actually parses at: "Enhancement"/"Fortune" All-Schools Spell DC (both
  bonus types exist only on school-specific DC effects, never All-Schools) and
  "Legendary" Spell Focus Mastery (its only source is an ML 10 item).

## [0.4.0] — 2026-08-08

Major UI redesign — see `docs/DDO_Gear_Optimizer_Design_Spec.pdf` (design) and
`docs/DASHBOARD_REDESIGN_SPEC.md` (implementation notes and decisions).

### Changed

- **Single-page dashboard replaces the six-tab layout.** Gear Sockets (25%),
  the Vellum Summary Scroll (45%) and the readout column (30%) are all on
  screen at once, with a collapsible Configuration & Auto-Solver drawer along
  the bottom. The top "belt" now switches only the right column between
  Console / Owned Items / Item Search. Every panel stays **mounted** when not
  fronted, so switching no longer drops scroll position, an in-flight search,
  a loaded Trove CSV or a half-filled configuration — the old tab system
  destroyed and recreated each view on every switch.
- **Dark-only theme** built on the design spec's palette (Void Black,
  Obsidian, Carved Stone, Aged/Burnt Vellum, Artificer Gold, Dragon's Blood,
  Arcane Blue, Nature's Vitality, Polished Steel). `darkMode: ["class"]` was
  removed rather than maintaining a light/dark pair for a design that only
  ships dark.
- **Typography**: Cinzel for headings, Inter for data, Fira Code for the
  console — all bundled locally via `@fontsource` (latin subsets), not linked
  from a CDN, since this ships as an offline desktop app.
- **Gear slots are now sockets**: recessed empty states reading "Socket Empty"
  / "Engrave Relic", item-type glyphs, and item names coloured by rarity
  (Legendary → gold, Epic → purple), derived from the item name prefix with
  minimum level as the authoritative fallback.
- **Item picker/detail moved from a side pane into a blurred-backdrop modal**
  — the old side-by-side layout could not fit a 25%-wide column, and the
  design spec §6 calls for exactly this treatment.
- **Set bonuses render as lit/dim pips** instead of a bulleted list. Entries
  are collapsed to one row per set at its highest active tier: the solver's
  `activeSets` lists every active *tier* separately (a 4-piece set appears as
  2-, 3- and 4-piece), which as a plain list read as three separate sets. The
  pip denominator is looked up via `GetSetBonus` and falls back to
  all-pips-lit when a set definition can't be resolved.
- **Owned Items condensed** from a five-column table (unreadable at 30% width)
  to two-line rows, with a glowing focus border on the filter field.
- After a successful solve the app now collapses the configuration drawer to
  reveal the result, replacing the old jump to the Gearset Editor tab — the
  sockets and summary are always visible now, so there is no tab to jump to.

## [0.3.7] — 2026-08-08

### Added

- **App icon and header logo** now use `logo.jpg`.
- **Solver/console layout**: once the layout goes side-by-side (`lg`
  breakpoint), the configuration form now takes 2/3 width and the console
  1/3 (was the reverse).

## [0.3.6] — 2026-08-08

### Added

- **"Any" caster weapon style.** Fully unrestricted Weapon1/Weapon2 — no
  weapon_style-based type narrowing at all, and Weapon2 is optional rather
  than required. The solver freely picks whichever weapon/offhand
  combination across every other caster style scores best. The caster
  craftable-family restriction toggle is a no-op for this style specifically
  (nothing left to restrict within).
- **Weapon-family diversity filter for slot alternatives.** `GetSlotAlternatives`
  no longer fills the suggestion list with reskins of the same weapon set
  (e.g. Legendary Cataclysmic Greataxe + ...Falchion + ...Great Crossbow, ~30
  variants sharing identical buffs) — keeps only the best-scoring item per
  detected weapon family, falling back to same-family repeats only when the
  pool has too few distinct families to fill the requested count. Known
  limitation: only catches names that literally end with their declared
  weapon type (Cataclysmic/Calamitous/most Defiled Reliquary) — "flavor
  renamed" reskins like a Club renamed "Sceptre" aren't caught yet (see
  docs/SLOT_ALTERNATIVES_UI_SPEC.md).

## [0.3.5] — 2026-08-08

### Added

- **Bonus-type-scoped caster DC / Spell Focus Mastery stats**
  (`docs/CASTER_BONUS_TYPE_STATS_SPEC.md`). New general mechanism: a stat
  priority name can now carry a recognized bonus-type prefix (e.g. `"Sacred
  Spell Focus Mastery"`, `"Profane All Spelldc"`) that requires the matched
  buff's actual DDO bonus type to agree, instead of crediting any bonus type
  to a single merged stat — `normalize_stat_name` gained a `bonus_type`
  parameter, threaded through from all five parse functions
  (items/augments/sets/filigrees). Fully backward-compatible: a priority with
  no recognized prefix keeps matching any bonus type exactly as before.
  Recognizes every real bonus type confirmed on real Spell DC / Spell Focus
  Mastery sources except Reaper (a stacking type, not a gear target):
  Sacred, Quality, Profane, Artifact, Insightful, Exceptional, Equipment,
  Legendary, Enhancement, Fortune. Also adds the previously-missing baseline
  "Spell Focus Mastery" (any bonus type) taxonomy leaf.

## [0.3.4] — 2026-08-08

### Added

- **Caster craftable-family weapon restriction** (`docs/CASTER_WEAPON_SELECTION_SPEC.md`).
  Weapon1 for every caster style (and Weapon2 for Dual Caster) is now restricted to
  the six known craftable weapon families — Dinosaur Bone, Undying Age, Legendary
  Green Steel, Calamitous (Viktranium Experiment crafting), Den of Vipers, and the
  newly-tracked Defiled Reliquary — with automatic fallback to any type-matching
  weapon if no family candidate exists. No hardcoded element-to-weapon table: the
  existing tiered stat-priority solver naturally surfaces the best real weapon
  (e.g. Calamitous/Defiled Reliquary items) from the narrowed pool. Gated behind a
  new opt-out checkbox in Caster Configuration, checked by default.
- **Colorless-slot augment detection fix**: Colorless slots no longer accept
  standard elemental/celestial-colored augments (a prior bug); they now correctly
  require either a literal Colorless augment type or a name match against the
  Diamond/Set Augment/Globe/etc. pattern DDOBuilderV2 mistypes as a standard color.
- **New caster weapon style: "Two-Handed Weapon"**, separate from the existing
  literal `Quarterstaff` style. Covers the broader two-handed pool (great sword,
  falchion, great axe, maul, great club, quarterstaff, and all crossbow types used
  without a runearm) so items like Arctica, the Mystic Cold (great axe) and
  Caustica, the Volley of Pain (crossbow) are reachable by the solver. Caster-only —
  does not affect Melee's Two Handed Fighting or Ranged's crossbow styles.

## [0.3.3] — 2026-08-08

### Added

- **Per-slot "Find Alternatives" drawer in the Gearset Editor** (`SlotAlternatives.svelte`,
  `docs/SLOT_ALTERNATIVES_UI_SPEC.md`). A new gear icon on every equipment slot row
  (filled or empty) opens a ranked list of 3–10 substitute items for that slot only,
  computed by an existing backend RPC (`GetSlotAlternatives`) that had never actually
  been called from the frontend until now. Respects the Trove owned-items restriction
  automatically. Equipping a suggestion requires an explicit confirm step, applies its
  precomputed augments/filigrees, and leaves a one-click "Restore" action to bring back
  what was replaced. (Note: this RPC is enumeration-based, not an ILP solve, so the
  global search-time setting doesn't apply to it — nothing to configure.)
- **Two new weapon styles carrying a required runearm.** Caster gained "Crossbow and
  Runearm" (any crossbow type at Weapon1, exclusively a runearm at Weapon2 — same
  mechanism as the existing "Stick and Runearm"); Melee gained "Single Handed Weapon
  and Runearm" (Weapon1 uses the exact same selection criteria — damage type +
  craftable-family + fallback — as every other melee style, restricted to one-handed
  weapon types; Weapon2 exclusively a runearm). Selecting either auto-checks the
  `runearm_use` checkbox for display consistency (cosmetic only — the backend never
  reads that flag for these styles). No weapon-type bias was implemented for either
  addition — considered, explicitly declined.

### Fixed

- **Colorless augment slots incorrectly accepted standard-color augments**
  (Solar/Lunar gems and any Red/Orange/Yellow/Green/Blue/Purple-typed augment) —
  confirmed wrong by a real DDO player after a saved gearset showed `Legendary
  Thirteen`'s Colorless slot filled with `Solar Gem of Charisma (Legendary)`. This
  reverses a rule built and tested earlier this session (`STANDARD_AUGMENT_COLORS`)
  that turned out to be the actual bug behind GitHub
  [#2](https://github.com/jorgec/ddogearset/issues/2) ("Lunar/Solar gems in colorless
  slots"), not a fix for it. Colorless slots only accept colorless-compatible
  ("Diamond") augments — DDOBuilderV2 doesn't reliably encode this via `<Type>` at
  all (confirmed: zero augments in the real corpus are typed `"Colorless"` or
  `"Diamond"` — e.g. `Diamond of Charisma` is typed `"Blue"`), so `augment_fits_slot`
  now identifies them by **name** against a confirmed pattern (`Diamond of ...`,
  `Set Augment: ...`, `Globe of ...`, `Clearwater Diamond`, and a few other named
  exceptions), independent of the item's own (unreliable) `<Type>` field. Verified
  against real data (Solar/Lunar gems now correctly rejected, `Diamond of Charisma`
  still accepted) and against the reported gearset directly — recalculating it now
  correctly drops the invalid Solar Gem with an explanatory note instead of silently
  keeping it. Two tests updated, one new test added; 120 total passing.

### Added

- **`.ddogearset` files now carry a content checksum** (`gearset_checksum.go`, SHA-256
  over a canonicalized JSON form) computed at save time and re-verified on load. A
  mismatch (file edited outside the app, corrupted, etc.) shows a non-blocking warning
  toast — never refuses to load. A file with no checksum (saved before this feature
  existed) is treated as expected, not a failure.
- **`.ddogearset` files now carry the app's release version** (`app_version`, separate
  from the existing file-format `"version"` field) via a new `GetAppVersion` RPC. On
  load, a version mismatch (or a missing `app_version` — every file saved before this
  feature) shows a non-blocking warning with an "Update Saved File" button that
  re-saves the now-migrated config under the current version (does not overwrite the
  original file). Directly motivated by a real repro: a saved file still carrying the
  stale `"The Chill of Ravenloft"` pack name (fixed in 0.3.1) silently excluded
  nothing on reload, with no way to see why — the version-mismatch warning now
  surfaces exactly that kind of drift, and `Summary.svelte`'s existing
  `migrateLegacyConfig` (already renaming that stale pack name) is what "Update Saved
  File" re-runs and persists.

### Changed

- **Excluded Expansion Packs list trimmed to 11 packs** (`frontend/public/expansions.json`),
  down from the full 66 real `AdventurePack` values — the full list was unwieldy in the
  UI. Kept: Menace of the Underdark, Shadowfell Conspiracy, Mists of Ravenloft,
  Masterminds of Sharn, Fables of the Feywild, Sinister Secret of Saltmarsh, The Isle of
  Dread, Vecna Unleashed, Magic of Myth Drannor, Chill of Ravenloft, Terror of
  Demogorgon. Frontend-only change. One correction applied against the real data:
  `"Chill of Ravenloft"` has no "The" prefix in the real `AdventurePack` value — using
  the requested `"The Chill of Ravenloft"` verbatim would have silently recreated the
  exact pack-name mismatch fixed in 0.3.0 (GitHub #1).

## [0.3.0] — 2026-08-07

### Added

- **Hard-required Weapon1/Weapon2 slots** (`docs/HARD_REQUIRED_SLOTS_SPEC.md`), designed
  interactively over a full solver-rules review session. Weapon1 is now a hard ILP
  constraint (`sum(x[i,'Weapon1']) == 1`) — it can never come back empty, unlike other
  slots which may legitimately stay unfilled if nothing scores well there. Weapon2 gets
  the same guarantee whenever it's meaningful (runearm builds, dual-wielding casters,
  thrower off-hand, Tank's shield).
  - **Melee**: new "Weapon Damage Type" selector (Slashing/Piercing/Bludgeoning, sourced
    verbatim from `WeaponGroupings.xml` — not guessed, not derived from `DRBypass` or
    item descriptions, which were checked and found unreliable). Weapon1 is restricted to
    that damage type plus five "craftable" weapon families (Dinosaur Bone, Undying Age,
    Legendary Green Steel, Viktranium Experiment crafting, Den of Vipers — identified by
    name or `DropLocation` substring, verified against the real corpus), falling back to
    damage-type-only if no family match exists, with the fallback surfaced as a note in
    the Summary UI and the saved file.
  - **Ranged**: Bow → Longbow only (Weapon2 always blocked); Repeating Crossbow →
    Repeating Heavy Crossbow only; Great Crossbow → Great Crossbow; Dual Crossbow → Heavy
    Crossbow only; all three crossbow styles allow Weapon2 as a runearm only when
    `runearm_use` is checked; Thrown/Shuriken → the style's own ranged type at Weapon1,
    always a Kama at Weapon2.
  - **Tank**: Weapon1 always Longsword, Weapon2 always Large Shield — a blanket override
    independent of whatever `weapon_style` is selected (Tank shares Melee's dropdown, but
    it no longer affects weapon selection).
  - **Caster**: four new real `weapon_style` options (Dual Caster, Stick and Orb, Stick
    and Runearm, Quarterstaff) replacing a forced `'None'` that made Weapon2 entirely
    unreachable for casters. New "Caster Configuration" panel — multi-select elemental
    damage type(s), main stat, and spell school(s) — applies to Tier 1 via a one-time
    "Apply" button (explicitly *not* a live reactive sync: this exact feature existed
    once before as one and had a real bug from it, documented in
    `statPriorities.ts`'s `migrateLegacyCasterFields`). Also replaced the old
    hardcoded, incomplete "caster stick" weapon list (missing common one-handers,
    and included "scepter", which isn't a real DDO weapon type) with the authoritative
    `WeaponGroupings.xml` "One Handed" group.
  - `runearm_use` no longer silently blends a runearm into TWF/Sword and Board/etc as an
    optional extra — narrowed to exactly the cases where a runearm is meant to be the
    exclusive offhand choice.
  - 30 new regression tests; verified end-to-end against real DDOBuilderV2 data for
    every build type (e.g. Tank → `Dinosaur Bone Longsword` + `Dinosaur Bone Large
    Shield`; Thrown → `Legendary Cataclysmic Dart` + `Dinosaur Bone Kama`).

### Fixed

- **`augment_fits_slot`'s substring fallback let unrelated augments into standard slots**
  — a full corpus audit (194 item slot types × 168 augment types) found 34 real false
  positives the substring rule let through, e.g. a plain "Red" slot accepting the
  unrelated augment "Incredible Potential" (because `"red"` is a substring of
  `"incREDible"`), a plain "Green" slot accepting any Greensteel Weapon Tier augment,
  and heroic-tier slots accepting their Legendary-tier counterparts across a tier
  boundary that should never cross. Now exact-match only (the intentional
  Colorless-accepts-standard-colors rule is unaffected).
- **`parse_augments` could silently drop a pre-filled augment** whose only effects fall
  outside the user's *current* stat priorities, breaking `create_model`'s aggregate
  pre-filled-augment count and turning a calculate-only solve infeasible. Now bypassed
  for pre-filled augments, matching the same pattern already used for the ML floor and
  owned-names filters in the same function.
- **GitHub issue [#1](https://github.com/jorgec/ddogearset/issues/1) — "Solver not
  restricting by packs"**: root-caused to an exact-string pack-name mismatch
  (`"The Chill of Ravenloft"` vs. the real `AdventurePack` value `"Chill of
  Ravenloft"`, no "The"), compounded by `expansions.json` — the *live*, runtime-fetched
  copy, not the dead unused duplicate in `src/lib/data/` — only listing 9 of the 66 real
  pack names. Replaced with the full real list; added a warning (surfaced in the Status
  Console, not just the debug log) whenever an excluded-pack entry matches nothing real.
- **Solver pack-exclusion CSV/config rules review** surfaced two further findings not
  yet acted on: quest-name substring collisions in pack/raid attribution (e.g. `"The
  Chronoscope"` vs. `"The Chronoscope (Legendary)"`) — explicitly deprioritized per
  product decision, all quest-level variants are treated the same for this app — and
  `calculate_only` deliberately skipping the raid-item-limit constraint (confirmed
  intentional, documented in-code).

## [0.2.3] — 2026-08-06

### Fixed

- **Trove CSV parsing required a `Binding` column that isn't actually
  guaranteed to exist.** Only `SubscriptionHash`, `Character`, `Location`,
  `Tab`, and `Name` are guaranteed present in a Trove export — `Binding` is
  not. `parseTroveInventoryCSV` (`trove_inventory.go`) now treats `Binding`
  as optional: when the column is present, rows are still filtered to
  `BtA`/`BtC` as before; when it's absent, that filter is skipped entirely
  rather than erroring out the whole file or silently keeping zero rows.
  `Location` and `Name` remain required, since those are guaranteed.
  `docs/TROVE_INVENTORY_IMPORT_SPEC.md` updated (row-filtering rule, AC-2)
  to match. Verified with synthetic CSVs covering both the with- and
  without-`Binding` cases.

### Added

- **Character and Location columns on the Owned Items table.** A name can
  legitimately appear more than once in an export (two characters owning
  the same named item, or one character banking and re-inventorying it), so
  `parseTroveInventoryCSV` now accumulates the distinct `Character`/
  `Location` values seen per owned name (new `troveNameInfo` type) instead
  of discarding everything but the name itself. `GetTroveOwnedItems` exposes
  these as comma-joined strings on `TroveOwnedItem`; the Owned Items screen
  renders them as two new table columns. Verified against the real sample
  export, including the shared-bank case (`Character: "-"`,
  `Location: "SharedBank"`).

## [0.2.2] — 2026-08-06

### Fixed

- **The Owned Items drawer could get permanently stuck on "Loading item…"**
  for any item with zero augment slots (e.g. `Anger's Gift`, `+1 Starter
  Dagger`) even though the backend call had already returned successfully —
  confirmed via the actual devtools network log, which showed a correct
  `GetItemDetails` response arriving while the UI never updated. Root cause:
  Go's `encoding/json` serializes a nil/empty slice as `null`, not `[]`, so
  `XMLItem.ItemAugments` is `null` for any item with no augment slots, and
  `ItemDetail.svelte`'s reactive augment-resolution block called
  `item.ItemAugments.forEach(...)` with no null guard — a `TypeError` thrown
  mid-render, before the DOM patch that would have shown the loaded item.
  Items with at least one augment slot never hit this path, which is why it
  looked isolated to specific items rather than a systemic bug. Fixed both
  unguarded call sites (`item.ItemAugments ?? []`); also added a hard 8s
  timeout around the load itself so a genuinely stuck fetch can no longer
  leave the drawer spinning forever regardless of cause. (An earlier,
  speculative fix in this same investigation — rejecting Trove-matched items
  that lacked `EquipmentSlot` data — was reverted after real testing showed
  it incorrectly hid legitimate gear like `Legendary Executioner's
  Platemail`; the null-`ItemAugments` guard above was the actual bug.)

- **A loaded Trove CSV silently vanished when switching tabs, and the
  solver would stop respecting the "only use items I own" restriction even
  though nothing was changed.** Both the solver-form accordion and the
  Owned Items screen live inside an `{#if $currentTab === ...}` block in
  `App.svelte`, so Svelte destroys and recreates the component on every tab
  switch. The loaded-CSV state was plain component-local state, so it reset
  to empty on remount — and worse, the accordion's reactive assignment
  (`$configStore.owned_item_names = restrictToOwned && ... ? ... : []`)
  fired immediately on remount with the now-empty local state, silently
  clearing the solver constraint on every visit back to the solver tab.
  Fixed by moving the state into a module-level store (`troveImportStore`
  in `store.ts`), which lives outside the component lifecycle and survives
  remounts. As part of the same fix, loading a CSV from either screen now
  populates both — a single shared `loadTroveCsv()` helper
  (`services/troveImport.ts`) fetches both the solver's name-list shape and
  the browsing screen's matched-item shape together, so whichever screen
  you check next already reflects the same loaded file.

### Changed

- **The "Only use items I own" toggle moved beside the "Load Trove CSV..."
  button** in the solver form (previously below it, in its own row), and is
  now visibly disabled (not just hidden) until a CSV has been loaded.
  Behavior unchanged: defaults off, turns on automatically the moment a CSV
  loads, and — confirmed by re-reading `parse_filigrees()` — filigrees were
  never subject to this restriction in the first place, since
  `owned_item_names` is only ever passed to `parse_items`/`parse_augments`;
  filigrees remain fully available to the solver whether or not the
  restriction is on.

## [0.2.1] — 2026-08-05

### Added

- **Constrain gearset generation to owned items via Trove inventory import**
  (`docs/TROVE_INVENTORY_IMPORT_SPEC.md`). A new "Owned Items (Trove Import)"
  section loads a Trove inventory CSV export and restricts item/augment
  selection to gear you actually own, instead of the full DDOBuilderV2
  catalog. Deliberately narrow scope, validated against a real 420-row
  export before implementation: rows in `SharedCrafting` are excluded, only
  `Binding ∈ {BtA, BtC}` rows are considered (this alone improved match
  quality from 65% to 82%, since bound items skew toward real named gear
  while unbound rows are mostly tradeable commodities), and a CSV name that
  doesn't exactly match DDOBuilderV2 is silently dropped — no fuzzy
  matching, no filigree matching (Trove's filigree names don't include
  tier/value and don't match DDOBuilderV2's format at all), no random-loot
  item support (procedurally-named items like `+1 Deflecting 2 Hide of
  Light Resistance 3` have no corresponding catalog entry to match against).
  New `LoadTroveInventory` RPC (`trove_inventory.go`) parses the CSV
  client-side-content-in, matching how gearset files are already loaded
  (`Summary.svelte`'s `loadGearset`) rather than Go opening a file by path.
  `OptimizationPayload.owned_item_names` is empty/absent by default — an
  opt-in filter, not a standing mode, so nobody who hasn't loaded a CSV gets
  an accidentally-restricted item pool; the UI toggle is disabled until a
  CSV is loaded for the same reason. `parse_items`/`parse_augments` gained
  one more optional parameter mirroring the existing `excluded_packs`
  filter, including the same "never drops a pre-equipped item" bypass.
  Explicitly exempted from `stat_search` mode (browsing what's possible in
  the game, not what you own). Verified end-to-end through the actual
  compiled, bundled solver binary — not just source — using the real CSV:
  Go's CSV parser reproduced an independent Python analysis exactly (420
  total rows, 190 distinct owned names after filtering), and a real solve
  correctly selected only owned items.

- **New standalone "Owned Items" screen** for browsing a Trove export
  directly, separate from the solver-constraint section above. Items-only by
  design (no augments, kept simple) and pre-filtered in Go against the
  already-loaded `itemsByName` index (`GetTroveOwnedItems`, new RPC) — no
  Python round-trip needed, and nothing "non-usable" ever reaches the list
  since matching happens before the frontend sees it. Clicking a name opens
  a sliding drawer (`svelte/transition`'s `fly`, not a manually-toggled CSS
  class — the drawer only exists in the DOM while open, so there's no
  "closed" state for a plain transform transition to animate from) hosting
  `ItemDetail.svelte` in read-only `mode="view"`, the same component
  `GearsetEditor` already uses. Verified for real: `GetTroveOwnedItems`
  against the actual CSV returned 152 matched items with correct names/ML/
  pack; the built app launches cleanly with the new screen wired in.

- **"Docent" added as an Armor Restriction option** (alongside Cloth, Light,
  Medium, Heavy). No backend change needed — `armor_restriction` matching
  was already a generic substring match against each item's XML `<Armor>`
  tag, and "Docent" (Artificer-class armor) was already a real value in the
  DDOBuilderV2 data; the dropdown just never exposed it. Verified against
  real data: 45 Docent-restricted armor items correctly filtered (Legendary
  Templar's Docent, Legendary Docent of the Black Earth, etc.).

### Fixed

- **A dinosaur/Isle-of-Dread augment (e.g. Meltfang) could be slotted into
  an ordinary Colorless augment slot on a non-dino item** — not legal in
  DDO; dino augments (Fang/Claw/Scale/Horn) only fit their own matching
  dino-specific slot. Root cause: an earlier fix in this same release cycle
  (see 0.2.0's `augment_fits_slot()` entry, below) made Colorless slots
  accept *any* augment type whatsoever, not just the standard colors it was
  meant to fix. Enumerating every distinct top-level `<Augment><Type>`
  across the real corpus surfaced dozens of other special, item/system-
  specific slot families this same over-broad rule was also incorrectly
  letting through — Cannith crafting prefix/suffix/extra slots, Dolorous/
  Melancholic/Miserable/Woeful named slots, "Nearly Complete: ..." slots,
  Reaper/Random/Thunderforged/Slavelords slots, and the IoD dino slots that
  triggered this report. `augment_fits_slot()` now only treats Colorless as
  accepting the 8 real standard colors (Red, Orange, Yellow, Green, Blue,
  Purple, Sun, Moon) — every other family still requires an exact slot-type
  match, same as before the original Colorless fix existed. Verified against
  the exact reported scenario (a dino Fang augment forced into a Colorless
  slot via `pre_filled_augments` on an ordinary item): now correctly
  rejected and flagged as "not credited" instead of silently accepted. Two
  new regression tests added; rebuilt and re-signed the bundled solver
  binaries so this is reflected in what the app actually runs, not just in
  source.

### Changed

- **Two stray root-level spec docs moved into `docs/`** for consistency with
  every other planning/spec document in the project: `phase_7_spec.md` →
  `docs/PHASE7_SPEC.md`, `phase_8_spec.md` → `docs/PHASE8_SPEC.md` (moved
  with `git mv` to preserve history; nothing referenced the old paths).

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
