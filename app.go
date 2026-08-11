package main

import (
	"bufio"
	"context"
	"crypto/sha256"
	"database/sql"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"goGearset/internal/appdb"
	"goGearset/internal/catalog"
	"goGearset/internal/models"
	"goGearset/internal/services"
)

// solverBinary and glpsolBinary are declared per-platform in
// embed_<GOOS>_<GOARCH>.go (Go's filename-based build-constraint convention),
// each go:embed-ing that platform's own bundled/solver-* and bundled/glpsol-*
// files. Neither PyInstaller nor a prebuilt glpsol binary can be
// cross-compiled, so every supported platform needs its own pair, built
// natively on that platform and committed under bundled/ — see
// build_releases.sh, which stages them before `wails build` runs, and
// docs/PHASE10_HANDOFF.md for the portability rationale. A GOOS/GOARCH with
// no embed file (and no bundled/ pair) simply fails to compile for that
// target, which is the correct, loud failure mode — there is nothing
// meaningful to embed until someone builds natively on that platform.

// defaultStatSets is the bundled stat-set preset library. It is the fallback
// used by GetStatSets whenever no readable/valid ./stat_sets.json override
// exists — see docs/TIERED_SOLVER_FRONTEND_SPEC.md §6.2.
//
//go:embed data/stat_sets.default.json
var defaultStatSets []byte

// AppVersion is the running app's release version, stamped into every saved
// .ddogearset file (as "app_version", distinct from the file-format schema
// "version" field below) and returned by GetAppVersion so the frontend can
// warn on load when a saved file predates fixes that may affect it (e.g. the
// excluded_packs pack-name migration in Summary.svelte's migrateLegacyConfig).
//
// Wails does NOT expose wails.json's productVersion to the running binary at
// build or runtime (confirmed: no ldflags, no go:embed, no runtime API wired
// anywhere in this codebase) — this MUST be kept in sync by hand with
// wails.json's "version"/"productVersion" on every version bump. There is no
// automated check for drift between the two.
const AppVersion = "0.4.4"

// GetAppVersion returns the running app's release version (see AppVersion).
func (a *App) GetAppVersion() string {
	return AppVersion
}

// App struct
type App struct {
	ctx        context.Context
	logs       []string
	solverPath string
	glpsolPath string
	solverDir  string
	// catalogDBPath is the seeded, resolved catalog.db location — set once by
	// ensureCatalogSeeded() in startup(), read by loadCaches() and runSolver()
	// so Go's own caches and the Python subprocess always agree on which
	// catalog they're reading. Empty until startup() runs (see catalogPath()'s
	// fallback for callers, like tests, that read caches without it).
	catalogDBPath string
	// appDB is the user's own database — builds, gearsets, and from Phase 6 run
	// history. Opened once by ensureAppDB() in startup() and held for the
	// process lifetime, unlike the catalog, which is opened per read: this one
	// is written to, and one long-lived handle is what keeps WAL doing its job.
	// nil when storage could not be opened, which is survivable — see
	// ensureAppDB.
	appDB     *sql.DB
	appDBPath string

	itemsCache     []models.XMLItem
	augmentsCache  []models.XMLAugment
	filigreesCache []models.XMLFiligree
	setBonusCache  []models.XMLSetBonus

	// Name -> index into the corresponding cache, so the item-detail panel's
	// exact-name lookups are O(1) instead of a linear scan over ~8,800 items.
	// If two entries share a name the LAST one parsed wins; duplicate names are
	// not expected in DDOBuilder's data and this is an accepted tiebreak, not an
	// error (docs/ITEM_DETAIL_SPEC.md §4.2 / EC-11).
	itemsByName     map[string]int
	augmentsByName  map[string]int
	filigreesByName map[string]int
	setsByName      map[string]int

	initOnce sync.Once
}

// buildNameIndex maps each entry's name to its index in items.
func buildNameIndex[T any](items []T, nameOf func(T) string) map[string]int {
	idx := make(map[string]int, len(items))
	for i, it := range items {
		idx[nameOf(it)] = i
	}
	return idx
}

// NewApp creates a new App application struct
func NewApp() *App {
	return &App{
		logs: []string{},
	}
}

// startup is called when the app starts. The context is saved
// so we can call the runtime methods
func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	a.logs = make([]string, 0)

	// app.db first, and NOT in the goroutine below: it is the user's own data,
	// every RPC that persists anything needs the handle, and opening it is a
	// local file operation measured in milliseconds — there is nothing to
	// overlap. A failure is logged and survivable (see ensureAppDB); the app
	// still solves, it just cannot save.
	if err := a.ensureAppDB(); err != nil {
		a.addLog("Warning: user data unavailable, nothing will be saved: " + err.Error())
	}

	// Seed catalog.db into the user data directory before loading caches from
	// it — on a fresh install nothing is there yet, so this is what makes a
	// freshly unzipped/installed app self-sufficient with no manual setup
	// step and no network access (docs/0.5.0/00_ETL_START_HERE.md Phase 6).
	// Runs in a background goroutine so startup() itself returns immediately.
	go func() {
		path, err := a.ensureCatalogSeeded()
		if err != nil {
			a.addLog("Warning: failed to seed catalog: " + err.Error())
			return
		}
		a.catalogDBPath = path
		a.loadCaches("Cached")
	}()

	a.initOnce.Do(func() {
		if err := a.extractSolver(); err != nil {
			a.addLog("Warning: failed to extract bundled solver: " + err.Error())
		}
	})
}

// packMappingsPath is project-relative (resolved against the process's
// working directory), matching every other bundled data-file path in this
// app.
const packMappingsPath = "data/PackMappings.json"

// catalogEnvVar mirrors python/catalog_source.py's DDO_CATALOG_DB convention
// exactly, so both processes resolve the same file from the same override
// with no separate configuration surface. When set, it wins outright — no
// seeding, no bundle read — which is what makes running against a
// hand-built fixture catalog (dev, this project's own test suite) possible
// without going through the packaged app at all.
const catalogEnvVar = "DDO_CATALOG_DB"

// catalogPath resolves the env override, with a bare relative "catalog.db"
// as the last-resort fallback for callers that never ran
// ensureCatalogSeeded (a direct loadCaches call in a test, or `go run`
// during development). The real app always has a.catalogDBPath set by
// startup() before loadCaches ever runs — see ensureCatalogSeeded.
func catalogPath() string {
	if p := os.Getenv(catalogEnvVar); p != "" {
		return p
	}
	return "catalog.db"
}

// loadCaches parses every data source, rebuilds all four name indexes, and runs
// the one-time acquisition-enrichment pass over the items.
//
// Each Parse* call is per-file fault tolerant (docs/ITEM_DETAIL_SPEC.md §3.1):
// a returned error now means a filesystem-level failure, while individual
// unparseable files arrive in `skipped` and are logged. A cache is only left
// untouched on a genuine walk error, so one bad file can no longer empty the UI.
//
// verb distinguishes the startup log wording from the reload wording.
func (a *App) loadCaches(verb string) {
	logSkipped := func(kind string, skipped []string) {
		if len(skipped) > 0 {
			a.addLog(fmt.Sprintf("Skipped %d unparseable %s row(s); the rest loaded normally.", len(skipped), kind))
		}
	}

	if err := services.InitEnrichment(packMappingsPath); err != nil {
		// Fatal for enrichment only: items still load, they just carry no pack
		// attribution. Everything else in the app is unaffected.
		a.addLog("Failed to load pack mappings, item pack attribution unavailable: " + err.Error())
	}

	// docs/0.5.0/00_ETL_START_HERE.md Phase 5 — every cache below reads
	// catalog.db instead of walking DDOBuilderV2 XML. Raid detection is no
	// longer computed here: catalog.LoadItems sets IsRaid straight from the
	// catalog's own precomputed column (verified against Python's identical
	// walk in Phase 4), so there is no quest list to parse and no
	// upgrade-chain to walk on this path.
	path := a.catalogDBPath
	if path == "" {
		path = catalogPath()
	}
	db, err := catalog.Open(path)
	if err != nil {
		a.addLog(fmt.Sprintf("Failed to open catalog at %s: %s", path, err.Error()))
		return
	}
	defer db.Close()

	if meta, err := catalog.ReadMeta(db); err == nil {
		a.addLog(fmt.Sprintf("Catalog v%d (schema %d, built %s)", meta.CatalogVersion, meta.SchemaVersion, meta.BuiltAt))
	}

	items, skippedItems, errItems := catalog.LoadItems(db)
	logSkipped("item", skippedItems)
	if errItems == nil {
		services.EnrichItemsInPlace(items)
		a.itemsCache = items
		a.itemsByName = buildNameIndex(items, func(it models.XMLItem) string { return it.Name })
		a.addLog(fmt.Sprintf("%s %d items for Gearset Editor", verb, len(items)))
	} else {
		a.addLog("Failed to cache items: " + errItems.Error())
	}

	augments, skippedAugs, errAugs := catalog.LoadAugments(db)
	logSkipped("augment", skippedAugs)
	if errAugs == nil {
		a.augmentsCache = augments
		a.augmentsByName = buildNameIndex(augments, func(g models.XMLAugment) string { return g.Name })
		a.addLog(fmt.Sprintf("%s %d augments for Gearset Editor", verb, len(augments)))
	} else {
		a.addLog("Failed to cache augments: " + errAugs.Error())
	}

	filigrees, skippedFils, errFils := catalog.LoadFiligrees(db)
	logSkipped("filigree", skippedFils)
	if errFils == nil {
		a.filigreesCache = filigrees
		a.filigreesByName = buildNameIndex(filigrees, func(f models.XMLFiligree) string { return f.Name })
		a.addLog(fmt.Sprintf("%s %d filigrees for Gearset Editor", verb, len(filigrees)))
	} else {
		a.addLog("Failed to cache filigrees: " + errFils.Error())
	}

	// Item/armor set bonuses and filigree set bonuses now come from one table
	// (set_tier + origin_hint at ETL time), so one query replaces the two
	// separate XML reads plus their append.
	sets, skippedSets, errSets := catalog.LoadSetBonuses(db)
	logSkipped("set bonus", skippedSets)
	if errSets != nil {
		a.addLog("Failed to cache set bonuses: " + errSets.Error())
	} else {
		a.setBonusCache = sets
		a.setsByName = buildNameIndex(sets, func(s models.XMLSetBonus) string { return s.Type })
		a.addLog(fmt.Sprintf("%s %d set bonuses", verb, len(sets)))
	}
}

// solverCacheDirName is the per-app subdirectory under the OS cache directory
// that holds extracted solver bundles. A CACHE, not user data (that's
// catalog_seed.go's userDataDir): every byte in it is reproducible from the
// app binary, so the OS is free to evict it and the next launch just
// re-extracts.
const solverCacheDirName = "ddo-solver"

// extractionStampName marks a solver cache directory as COMPLETE. Written
// last, inside the staging directory, before that directory is renamed into
// place — so a directory that exists but lacks the stamp can only be debris
// from a build that pre-dates this scheme, never a half-extracted bundle from
// this one.
const extractionStampName = ".extraction-complete"

// userCacheDir is a var, not a direct os.UserCacheDir call, purely so tests
// can point extraction at a temp directory. os.UserCacheDir reads a different
// environment variable on each platform (HOME, XDG_CACHE_HOME, LocalAppData),
// so overriding it via the environment would mean per-GOOS test setup for a
// behaviour that has nothing to do with the platform.
var userCacheDir = os.UserCacheDir

// bundleFingerprint hashes every embedded file's path and contents into the
// cache directory's name, alongside AppVersion.
//
// AppVersion alone is not enough, and the failure it misses is a nasty one:
// during development the version does not change between builds, so a cached
// extraction from an earlier build would keep being reused and the app would
// silently keep running a stale solver — behaviour that looks like the edit
// simply had no effect. Hashing the contents makes a changed bundle a changed
// directory, always. Measured cost is a few milliseconds over ~21 MB; see the
// timing note on extractSolver.
func bundleFingerprint() (string, error) {
	h := sha256.New()
	err := fs.WalkDir(bundleFS, bundleRoot, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || path == bundleRoot+"/"+catalogFileName {
			return nil
		}
		data, err := bundleFS.ReadFile(path)
		if err != nil {
			return err
		}
		h.Write([]byte(path))
		h.Write(data)
		return nil
	})
	if err != nil {
		return "", fmt.Errorf("fingerprinting embedded solver bundle: %w", err)
	}
	return hex.EncodeToString(h.Sum(nil))[:16], nil
}

// extractSolver makes the embedded solver bundle available on disk and points
// a.solverPath/glpsolPath/solverDir at it.
//
// What gets extracted: everything in bundleFS (the PyInstaller solver tree,
// glpsol, and glpsol's own shared libraries — see embed_<GOOS>_<GOARCH>.go),
// with its directory structure PRESERVED. The structure matters twice over.
// The solver is a PyInstaller --onedir build, which finds its ~55-file
// _internal/ tree as a sibling of the executable and will not start without
// it. And glpsol needs its libraries beside it: on macOS its references are
// rewritten to @executable_path (build-mac.sh's install_name_tool step), and
// on Linux/Windows runSolver points LD_LIBRARY_PATH at this same directory.
//
// Where, and how often: ONCE per (AppVersion, bundle contents) pair, into
// <user cache>/ddo-solver/<version>-<hash>/. Re-extracting 21 MB across 57
// files on every launch would cost more than the --onedir switch saves —
// docs/0.5.0/00_ETL_START_HERE.md Phase 7 asks for zero extraction I/O on a
// second launch, and the stamp check below is what delivers it.
func (a *App) extractSolver() error {
	fingerprint, err := bundleFingerprint()
	if err != nil {
		return err
	}
	cacheRoot, err := userCacheDir()
	if err != nil {
		return fmt.Errorf("resolving user cache directory: %w", err)
	}
	parent := filepath.Join(cacheRoot, solverCacheDirName)
	targetDir := filepath.Join(parent, AppVersion+"-"+fingerprint)

	if _, err := os.Stat(filepath.Join(targetDir, extractionStampName)); err == nil {
		a.addLog("Solver already extracted at " + targetDir)
		return a.useSolverDir(targetDir)
	}

	if err := os.MkdirAll(parent, 0755); err != nil {
		return fmt.Errorf("creating solver cache directory: %w", err)
	}
	// Staged elsewhere and renamed in, so two instances launching at once can
	// never read a partially-written solver: the loser of the race finds
	// targetDir already there (rename onto an existing directory fails on both
	// POSIX and Windows) and simply uses it.
	stagingDir, err := os.MkdirTemp(parent, "staging-*")
	if err != nil {
		return fmt.Errorf("creating staging directory: %w", err)
	}
	defer os.RemoveAll(stagingDir) // no-op once the rename below succeeds

	err = fs.WalkDir(bundleFS, bundleRoot, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		relative, err := filepath.Rel(bundleRoot, path)
		if err != nil {
			return err
		}
		if relative == "." {
			return nil
		}
		if d.IsDir() {
			return os.MkdirAll(filepath.Join(stagingDir, relative), 0755)
		}
		// catalog.db rides in the same bundle but has its own destination —
		// ensureCatalogSeeded (catalog_seed.go) puts it in the persistent user
		// data directory. A 58 MB copy in an evictable cache would be waste on
		// top of waste.
		if relative == catalogFileName {
			return nil
		}
		data, err := bundleFS.ReadFile(path)
		if err != nil {
			return fmt.Errorf("reading embedded %s: %w", relative, err)
		}
		if err := os.WriteFile(filepath.Join(stagingDir, relative), data, 0755); err != nil {
			return fmt.Errorf("extracting %s: %w", relative, err)
		}
		return nil
	})
	if err != nil {
		return err
	}

	// Stamp last: until this exists the directory is not a valid cache entry.
	if err := os.WriteFile(filepath.Join(stagingDir, extractionStampName),
		[]byte(AppVersion+"-"+fingerprint+"\n"), 0644); err != nil {
		return fmt.Errorf("writing extraction stamp: %w", err)
	}

	if err := os.Rename(stagingDir, targetDir); err != nil {
		// Something is already at targetDir. Either another instance won the
		// race — in which case its extraction is as good as ours and we use it
		// — or it is unstamped debris, which nothing can be using (no launch
		// ever returns a directory without a stamp) and which must be cleared
		// rather than left to block every future launch. The stamp is
		// re-checked HERE, not earlier, so the window between "decided it is
		// debris" and "deleted it" is as small as it can be.
		stamp := filepath.Join(targetDir, extractionStampName)
		if _, statErr := os.Stat(stamp); statErr != nil {
			os.RemoveAll(targetDir)
			if retryErr := os.Rename(stagingDir, targetDir); retryErr != nil {
				return fmt.Errorf("installing extracted solver at %s: %w", targetDir, retryErr)
			}
		}
	}
	a.addLog(fmt.Sprintf("Solver and GLPK extracted to %s", targetDir))
	pruneStaleSolverCaches(parent, filepath.Base(targetDir))
	return a.useSolverDir(targetDir)
}

// useSolverDir points the App at an extracted bundle and verifies it actually
// contains the two executables — a cache directory that survived but lost
// files (manual cleanup, an aggressive disk utility) must fail here rather
// than at solve time.
func (a *App) useSolverDir(dir string) error {
	a.solverDir = dir
	a.solverPath = filepath.Join(dir, solverBinaryName)
	a.glpsolPath = filepath.Join(dir, glpsolBinaryName)
	if _, err := os.Stat(a.solverPath); err != nil {
		return fmt.Errorf("bundle did not contain %s: %w", solverBinaryName, err)
	}
	if _, err := os.Stat(a.glpsolPath); err != nil {
		return fmt.Errorf("bundle did not contain %s: %w", glpsolBinaryName, err)
	}
	return nil
}

// pruneStaleSolverCaches deletes extractions from other versions/builds. Every
// app update, and every dev rebuild, produces a new 21 MB directory; without
// this they accumulate forever in a directory no user will ever think to look
// in.
//
// Best-effort by design: a directory another running instance is using may
// refuse to delete (Windows locks running executables), and that is fine —
// the next launch tries again.
func pruneStaleSolverCaches(parent, keep string) {
	entries, err := os.ReadDir(parent)
	if err != nil {
		return
	}
	for _, entry := range entries {
		if entry.Name() == keep {
			continue
		}
		os.RemoveAll(filepath.Join(parent, entry.Name()))
	}
}

// StatPriorityEntry is one user priority (Phase 10, docs/PHASE10_PLAN.md §2.2).
//
// Array order is load-bearing: intra-tier rank is the index of appearance among
// the entries sharing a Tier, which is why this is a slice and not a map (a map
// loses ordering once marshaled — Go sorts map keys).
//
// Wire-shape notes, verified against python/solver.py's parse_stat_priorities:
//   - `tier` carries `omitempty` on purpose. parse_stat_priorities detects the
//     new tiered format ("Shape C") by the *presence* of a `tier` key on any
//     element, and rejects a Shape-C list that has an element without one. Old
//     saved .ddogearset files carry only `value`; they deserialize here with
//     Tier == 0, and omitempty keeps `tier` off the wire so Python still sees a
//     legacy "Shape B" list and runs its value->tier migration. Tier is never
//     legitimately 0 (valid range is 1..5), so nothing real is ever dropped.
//   - There is deliberately no `order` field. Python derives `order` from array
//     position; sending one would be ignored.
type StatPriorityEntry struct {
	Stat string `json:"stat"`
	Tier int    `json:"tier,omitempty"` // 1..5; omitted (0) only for legacy payloads
	Cap  *int   `json:"cap,omitempty"`  // pointer so "no cap" and "cap 0" differ on the wire
	// Value is LEGACY ONLY: solver.py migrates it to a tier. New code never
	// writes it, but it must survive a round trip so old saved gearsets load.
	Value int `json:"value,omitempty"`
}

type OptimizationPayload struct {
	GearsetName   string `json:"gearset_name"`
	MaxLevel      int    `json:"max_level"`
	BuildType     string `json:"build_type"`
	WeaponStyle   string `json:"weapon_style"`
	Swashbuckling bool   `json:"swashbuckling"`
	OffhandStyle  string `json:"offhand_style"`
	// WeaponDamageType (Slashing/Piercing/Bludgeoning) restricts the
	// hard-required Weapon1 slot for Melee builds — see
	// docs/HARD_REQUIRED_SLOTS_SPEC.md. Ignored for every other build_type;
	// Ranged/Tank don't have a heuristic defined yet (deliberately deferred).
	WeaponDamageType string `json:"weapon_damage_type,omitempty"`
	// CasterRestrictWeaponFamilies gates the craftable-family restriction on
	// caster Weapon1 (all styles) and Weapon2 (Dual Caster only) — see
	// docs/CASTER_WEAPON_SELECTION_SPEC.md. Deliberately NOT `omitempty`: the
	// Go zero-value (false) means "opted out," which must be distinguishable
	// on the wire from "field absent" (an old saved file, which solver.py
	// defaults to true — the new intended behavior — via parsed_data.get's
	// own default, not this struct's zero-value). Ignored for non-Caster
	// build_type.
	CasterRestrictWeaponFamilies bool                `json:"caster_restrict_weapon_families"`
	CasterSpellpowers            []string            `json:"caster_spellpowers"`
	CasterSchools                []string            `json:"caster_schools"`
	StatPriorities               []StatPriorityEntry `json:"stat_priorities"`
	ArmorRestriction             string              `json:"armor_restriction"`
	ReservedMinorArtifactSlot    string              `json:"reserved_minor_artifact_slot"`
	MinorArtifactFiligreeSlots   int                 `json:"minor_artifact_filigree_slots"`
	ExcludeGemOfManyFacets       bool                `json:"exclude_gem_of_many_facets"`
	RunearmUse                   bool                `json:"runearm_use"`
	ExcludedPacks                []string            `json:"excluded_packs"`
	// OwnedItemNames restricts item/augment selection to exact-name matches
	// against this set (see docs/TROVE_INVENTORY_IMPORT_SPEC.md and
	// LoadTroveInventory). Empty/absent means unrestricted — this is an
	// opt-in filter, not a standing mode, so nobody who hasn't loaded a
	// Trove export gets an accidentally-empty item pool.
	OwnedItemNames []string          `json:"owned_item_names,omitempty"`
	RaidItemLimit  int               `json:"raid_item_limit"`
	IsDinoArtifact bool              `json:"is_dino_artifact"`
	OutputFilename string            `json:"output_filename"`
	PreEquipped    map[string]string `json:"pre_equipped"`
	// Keyed by slot -> augment color/type -> augment name (e.g. {"Weapon1": {"Green": "..."}}).
	// interface{} rather than a fixed map type so older saved gearsets that stored this
	// as a plain array of names per slot still deserialize without error; python/solver.py
	// normalizes both shapes.
	PreFilledAugments  map[string]interface{} `json:"pre_filled_augments"`
	PreFilledFiligrees map[string][]string    `json:"pre_filled_filigrees"`
	CalculateOnly      bool                   `json:"calculate_only"`
	// MaxSearchTime is the TOTAL wall-clock budget in seconds shared across all
	// solve stages (not a per-solve limit). The frontend has produced this value
	// since Phase 9 but it was absent from this struct and therefore silently
	// dropped before Python ever saw it. Python clamps it to [10, 1800] and
	// defaults to 60 when absent/zero.
	MaxSearchTime int `json:"max_search_time,omitempty"`
	// Mode is "optimize" | "calculate" | "alternatives". Empty falls back to
	// CalculateOnly (legacy) and then to "optimize" in solver.py's
	// normalize_mode. An unrecognized value is a validation failure.
	Mode string `json:"mode,omitempty"`
}

// AlternativesPayload drives the on-demand "what else could go in this slot"
// query (docs/PHASE10_PLAN.md §7). It embeds OptimizationPayload so the
// candidate pool is filtered exactly like the main solve's.
type AlternativesPayload struct {
	OptimizationPayload
	TargetSlot    string            `json:"target_slot"`
	CurrentItem   string            `json:"current_item"`
	EquippedItems map[string]string `json:"equipped_items"`
	Count         int               `json:"count"` // clamped to [3, 10] before sending
}

// AugmentAssignment is one color slot filled on a candidate item.
type AugmentAssignment struct {
	Color string `json:"color"`
	Name  string `json:"name"`
}

// AlternativeItem is one ranked candidate for the target slot.
type AlternativeItem struct {
	Rank     int    `json:"rank"`
	ItemName string `json:"itemName"`
	Slot     string `json:"slot"`
	ML       int    `json:"ml"`
	IsRaid   bool   `json:"isRaid"`
	// TierScores ("1".."5") is the AUTHORITATIVE ranking vector; compare
	// candidates lexicographically on it. Only populated tiers appear.
	TierScores map[string]float64 `json:"tierScores"`
	// ObjectiveScore is the §7.6 display collapse
	// (10000*G1 + 1000*G2 + 100*G3 + 10*G4 + G5). It is display sugar ONLY and
	// is NOT authoritative: it preserves the lexicographic order only when the
	// higher-tier gap exceeds ~0.333. Sort by Rank, compare via TierScores.
	ObjectiveScore float64             `json:"objectiveScore"`
	StatDeltas     map[string]float64  `json:"statDeltas"` // vs. baseline, per priority stat
	Augments       []AugmentAssignment `json:"augments"`
	Filigrees      map[string][]string `json:"filigrees"` // "weapon" / "artifact"
}

// AlternativesResult is what GetSlotAlternatives hands back to the UI.
type AlternativesResult struct {
	Success            bool               `json:"success"`
	Slot               string             `json:"slot"`
	BaselineTierScores map[string]float64 `json:"baselineTierScores"`
	Alternatives       []AlternativeItem  `json:"alternatives"`
	Warnings           []string           `json:"warnings,omitempty"`
	ErrorMessage       string             `json:"errorMessage,omitempty"`
}

type ResultPayload struct {
	Success       bool                   `json:"success"`
	TimeTaken     float64                `json:"timeTaken"`
	GearSet       map[string]interface{} `json:"gearSet"`
	RealizedStats map[string]interface{} `json:"realizedStats,omitempty"`
	ActiveSets    []string               `json:"activeSets,omitempty"`
	Filigrees     map[string][]string    `json:"filigrees,omitempty"`
	AllEffects    map[string]interface{} `json:"allEffects,omitempty"`
	// Slots is the authoritative per-slot detail (item, location, augments,
	// filigrees, set bonus contributions) — see docs/PHASE9_PLAN.md Phase 9.2.
	// The frontend calculator/Summary should read from this instead of
	// re-deriving state from GearSet/Filigrees/ActiveSets where possible.
	Slots        map[string]interface{} `json:"slots,omitempty"`
	ErrorMessage string                 `json:"errorMessage,omitempty"`

	// --- Phase 10 tiered-solver additions (docs/PHASE10_PLAN.md §9) ---

	// TierReport is the per-stage trace of the sequential lexicographic solve.
	TierReport *TierReport `json:"tierReport,omitempty"`
	// TierScores maps tier number ("1".."5") to the goal value G_t recomputed
	// from the FINAL reconciled solution — not echoed from the stage records.
	// Only populated tiers appear. Empty in calculate mode.
	TierScores map[string]float64 `json:"tierScores,omitempty"`
	// PriorityTiers maps each priority's base stat name to its tier.
	PriorityTiers map[string]int `json:"priorityTiers,omitempty"`
	// UnmetTier4 lists tier-4 stats the solve could not include at all. Not an
	// error: tier 4 is breadth-before-magnitude and is subordinate to tiers 1-3.
	UnmetTier4 []string `json:"unmetTier4,omitempty"`
	// UnmatchedPriorities lists priority stats with zero sources anywhere in the
	// parsed data (typos, or nothing in the game grants them).
	UnmatchedPriorities []string `json:"unmatchedPriorities,omitempty"`
	// Degraded is a convenience mirror of TierReport.Degraded, populated by Go
	// after unmarshaling so callers need not walk into the report. Python emits
	// it only inside tierReport.
	Degraded bool `json:"degraded,omitempty"`
}

// TierStageReport is one tier stage of the sequential solve.
type TierStageReport struct {
	Tier int `json:"tier"`
	// GoalValue is nil when the stage produced no usable incumbent.
	GoalValue *float64 `json:"goalValue"`
	// Status is "optimal" | "time_limited" | "no_incumbent" | "infeasible" |
	// "lock_violation" | "unknown".
	Status         string  `json:"status"`
	Proven         bool    `json:"proven"`
	BudgetSeconds  float64 `json:"budgetSeconds"`
	ElapsedSeconds float64 `json:"elapsedSeconds"`
	// Folded lists earlier tiers whose goals were folded into this stage's
	// objective because their own stage produced no incumbent.
	Folded []int `json:"folded"`
}

// ConsolidationReport covers the stage that sheds items and redundant sources
// once every tier goal is locked. Nil in calculate mode.
type ConsolidationReport struct {
	// Status is "optimal" | "time_limited" | "restored".
	Status           string  `json:"status"`
	ElapsedSeconds   float64 `json:"elapsedSeconds"`
	ItemsEquipped    int     `json:"itemsEquipped"`
	DuplicateSources int     `json:"duplicateSources"`
}

// ReconciliationReport covers the final pure LP that maximizes the displayed
// totals over the already-fixed equipment.
type ReconciliationReport struct {
	Status         string  `json:"status"` // "optimal" | "failed"
	ElapsedSeconds float64 `json:"elapsedSeconds"`
}

// TierReport is the trace of a tiered solve. In calculate mode Stages is empty
// and Consolidation is nil — both are skipped by design.
type TierReport struct {
	Stages              []TierStageReport     `json:"stages"`
	Consolidation       *ConsolidationReport  `json:"consolidation"`
	Reconciliation      *ReconciliationReport `json:"reconciliation"`
	TotalElapsedSeconds float64               `json:"totalElapsedSeconds"`
	// Degraded is true when the run completed but had to fall back somewhere
	// (a stage timed out with no incumbent, a lock was violated, consolidation
	// or reconciliation was rolled back). The result is still usable.
	Degraded bool     `json:"degraded"`
	Notes    []string `json:"notes"`
}

func (a *App) addLog(msg string) {
	a.logs = append(a.logs, msg)
}

// ParseMetadata triggers the Phase 2 XML parsing logic.
func (a *App) ParseMetadata(filePath string) error {
	a.addLog(fmt.Sprintf("Parsing metadata from %s...", filePath))
	// Mock implementation
	a.addLog("Successfully parsed metadata.")
	return nil
}

// runSolver marshals payload, writes it to a UNIQUE temp file, invokes the
// bundled solver, and returns the raw JSON from the captured JSON_RESULT line.
//
// solverCommand builds the solver invocation: binary, payload path, working
// directory and environment.
//
// Split out of runSolver so the properties that are easy to get wrong and
// invisible at runtime — a working directory the app cannot write to, a missing
// environment variable — can be asserted without running a solve.
func (a *App) solverCommand(payloadPath string) *exec.Cmd {
	cmd := exec.Command(a.solverPath, payloadPath)

	// The solver writes gearset_output.txt (a human-readable dump of the run)
	// relative to ITS working directory, which it inherits from this process.
	// That is the same defect 0.5.1 fixed in SaveGearset: for a double-clicked
	// .app the working directory is not the user's home, and on a read-only
	// volume the write fails outright — it has only ever worked because the app
	// gets launched from the repo during development. Pointing it at the user
	// data directory makes the file both writable and findable.
	//
	// Nothing reads this file back; it exists for a human to look at.
	if dir, err := userDataDir(); err == nil {
		if err := os.MkdirAll(dir, 0755); err == nil {
			cmd.Dir = dir
		}
	}

	// GLPSOL_PATH tells optimizer.py's _glpk_cmd() exactly which bundled
	// glpsol to run instead of a hardcoded install path (see
	// docs/PHASE10_HANDOFF.md). LD_LIBRARY_PATH/DYLD_LIBRARY_PATH are set
	// unconditionally as a cross-platform fallback so glpsol's shared
	// libraries (co-extracted into a.solverDir) resolve even if a build's
	// dynamic-linker patching step (macOS's install_name_tool, see
	// build-mac.sh) was skipped or is incomplete for a given platform;
	// they're harmless no-ops on platforms/binaries that don't need them.
	// DDO_CATALOG_DB gives solver.py the same seeded catalog path Go's own
	// caches read (a.catalogDBPath, set once by ensureCatalogSeeded() in
	// startup() — see catalog_seed.go). Python no longer depends on
	// inheriting the Go process's working directory, or on DDOBuilderV2
	// existing on disk at all (docs/0.5.0/00_ETL_START_HERE.md Phase 6).
	catalogAbsPath, absErr := filepath.Abs(a.catalogDBPath)
	if absErr != nil {
		catalogAbsPath = a.catalogDBPath
	}
	cmd.Env = append(os.Environ(),
		"GLPSOL_PATH="+a.glpsolPath,
		"LD_LIBRARY_PATH="+a.solverDir,
		"DYLD_LIBRARY_PATH="+a.solverDir,
		"DDO_CATALOG_DB="+catalogAbsPath,
	)
	return cmd
}

// Two behaviors that matter (docs/PHASE10_PLAN.md §2.7, §7.2):
//
//  1. The payload file is created with os.CreateTemp rather than a hardcoded
//     path. RunOptimization and GetSlotAlternatives are independent entry
//     points and the UI can fire one while the other is running; a shared
//     filename would let two calls clobber each other's payload.
//  2. If a JSON_RESULT line was captured, it is returned REGARDLESS of exit
//     code. solver.py exits 1 on every validation failure after printing the
//     real message, so discarding the captured payload on a non-zero exit
//     would surface every one of those messages to the user as "exit status 1".
//     An error is synthesized from cmd.Wait only when no JSON_RESULT was seen.
func (a *App) runSolver(payload any) (json.RawMessage, error) {
	if a.solverPath == "" {
		if err := a.extractSolver(); err != nil {
			return nil, fmt.Errorf("solver not available: %w", err)
		}
	}

	a.addLog("Serializing payload...")
	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}

	tmp, err := os.CreateTemp("", "ddo_payload_*.json")
	if err != nil {
		return nil, err
	}
	tmpFile := tmp.Name()
	defer os.Remove(tmpFile)
	if _, err := tmp.Write(payloadBytes); err != nil {
		tmp.Close()
		return nil, err
	}
	if err := tmp.Close(); err != nil {
		return nil, err
	}

	a.addLog("Invoking solver...")
	cmd := a.solverCommand(tmpFile)
	stdout, _ := cmd.StdoutPipe()
	cmd.Stderr = cmd.Stdout

	if err := cmd.Start(); err != nil {
		return nil, err
	}

	var captured json.RawMessage
	scanner := bufio.NewScanner(stdout)
	// The solver's JSON_RESULT line carries the full gearset and can far exceed
	// bufio.Scanner's 64KiB default line limit.
	scanner.Buffer(make([]byte, 0, 64*1024), solverMaxLine)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "JSON_RESULT:") {
			captured = json.RawMessage(strings.TrimPrefix(line, "JSON_RESULT:"))
		} else {
			a.addLog(line)
		}
	}

	waitErr := cmd.Wait()
	if waitErr != nil {
		a.addLog("Solver exited with error: " + waitErr.Error())
		if captured == nil {
			return nil, waitErr
		}
		// A JSON_RESULT was captured — it carries the real message.
		return captured, nil
	}
	if captured == nil {
		return nil, fmt.Errorf("solver produced no result")
	}
	a.addLog("Solver completed successfully.")
	return captured, nil
}

// solverMaxLine bounds a single JSON_RESULT line. 16 MiB is far above any real
// gearset payload while still refusing to grow without limit.
const solverMaxLine = 16 * 1024 * 1024

// RunOptimization triggers the bundled solver binary with the given payload.
func (a *App) RunOptimization(config OptimizationPayload) (ResultPayload, error) {
	if config.Mode == "" && config.CalculateOnly {
		config.Mode = "calculate"
	}

	raw, err := a.runSolver(config)
	if err != nil {
		return ResultPayload{Success: false, ErrorMessage: err.Error()}, err
	}

	var richResult ResultPayload
	if err := json.Unmarshal(raw, &richResult); err != nil {
		return ResultPayload{Success: false, ErrorMessage: "Could not read the solver's result: " + err.Error()}, err
	}

	if !richResult.Success && richResult.ErrorMessage != "" {
		// Solver explicitly returned a failure JSON payload.
		return richResult, nil
	}
	richResult.Success = true
	richResult.TimeTaken = 0
	if richResult.TierReport != nil {
		richResult.Degraded = richResult.TierReport.Degraded
	}

	if shouldRecordSuggestion(config, richResult) {
		a.recordSuggestion(config, richResult)
	}
	return richResult, nil
}

// shouldRecordSuggestion decides whether a solve's output is a PROPOSAL worth
// storing as origin='suggested'.
//
// Two things disqualify a run. `calculate` evaluates gear the user already has
// and proposes nothing, so recording it would replace a pending suggestion with
// the very thing it was being compared against. And a run that produced no
// gearset has nothing to propose — storing an empty suggestion would put a
// one-click gearset-eraser behind the Accept All button.
//
// A predicate rather than an inline condition because it is the guard the
// two-node model rests on, and a guard that cannot be tested without a
// tens-of-seconds solve is a guard nobody checks.
func shouldRecordSuggestion(config OptimizationPayload, result ResultPayload) bool {
	if config.Mode == "calculate" || config.CalculateOnly {
		return false
	}
	return result.Success && len(result.GearSet) > 0
}

// recordSuggestion stores what a solve proposed, as origin='suggested'.
//
// Best-effort and never fatal: a solve that produced a gearset must still reach
// the user even if storage is unavailable. Reported in the log rather than
// swallowed.
//
// It never writes an `equipped` row. That is the structural half of the fix for
// *"Optimize → Save wrote an empty gearset"* — the old code had one place for
// both the solver's output and the user's own gearset, so whichever wrote last
// won. Here a solve cannot reach the user's gearset at all; only AcceptAll
// moves rows across, and only when asked.
func (a *App) recordSuggestion(config OptimizationPayload, result ResultPayload) {
	if a.appDB == nil {
		return
	}
	resolver, closeCatalog, err := a.nameResolver()
	if err != nil {
		a.addLog("Could not store the suggestion: " + err.Error())
		return
	}
	defer closeCatalog()

	// A suggestion needs a build to hang off. Solving before ever saving is
	// normal, so the build is created from the current configuration when it is
	// missing — and left completely alone when it already exists, because its
	// `equipped` rows are the user's, not this solve's to rewrite.
	buildUUID, err := a.ensureBuildFor(config, resolver)
	if err != nil {
		a.addLog("Could not store the suggestion: " + err.Error())
		return
	}

	resultMap, err := resultAsMap(result)
	if err != nil {
		a.addLog("Could not store the suggestion: " + err.Error())
		return
	}
	orphans, err := appdb.SaveSuggestion(a.appDB, resolver, buildUUID, resultMap)
	if err != nil {
		a.addLog("Could not store the suggestion: " + err.Error())
		return
	}
	a.addLog(fmt.Sprintf("Stored the solver's suggestion for this build (%d slots, %d unresolved).",
		len(result.GearSet), len(orphans)))
}

// ensureBuildFor returns the build a solve belongs to, creating it from the
// current configuration only if it does not exist yet.
func (a *App) ensureBuildFor(config OptimizationPayload, resolver appdb.Catalog) (string, error) {
	name := strings.TrimSpace(config.GearsetName)
	if name == "" {
		name = "Untitled"
	}
	buildUUID := appdb.BuildUUIDForName(name)

	var exists int
	if err := a.appDB.QueryRow("SELECT count(*) FROM build WHERE uuid = ?", buildUUID).Scan(&exists); err != nil {
		return "", err
	}
	if exists > 0 {
		return buildUUID, nil
	}

	configMap, err := payloadAsMap(config)
	if err != nil {
		return "", err
	}
	if _, err := appdb.SaveBuildAs(a.appDB, resolver, configMap, buildUUID, AppVersion); err != nil {
		return "", err
	}
	return buildUUID, nil
}

// resultAsMap round-trips a result through JSON so appdb reads exactly the
// field names a .ddogearset's `result` object uses — the same reason
// payloadAsMap exists, and what lets one writer serve both.
func resultAsMap(result ResultPayload) (map[string]interface{}, error) {
	raw, err := json.Marshal(result)
	if err != nil {
		return nil, fmt.Errorf("serializing the result: %w", err)
	}
	var out map[string]interface{}
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, fmt.Errorf("serializing the result: %w", err)
	}
	return out, nil
}

// GetSlotAlternatives ranks the other items that could occupy TargetSlot, with
// every other slot hard-locked to the passed-in EquippedItems.
//
// It is COLD-CALLABLE (docs/PHASE10_PLAN.md §7.1): no prior RunOptimization is
// required. Baseline tier scores are computed directly from whatever
// EquippedItems map is supplied, including one the user assembled by hand in
// the editor. A target slot with zero legal candidates is a success with an
// empty Alternatives list, not an error.
func (a *App) GetSlotAlternatives(payload AlternativesPayload) (AlternativesResult, error) {
	payload.Mode = "alternatives"
	payload.CalculateOnly = false

	// Clamp before sending so Python and the UI agree on what was asked for.
	if payload.Count < minAlternatives {
		payload.Count = minAlternatives
	} else if payload.Count > maxAlternatives {
		payload.Count = maxAlternatives
	}

	raw, err := a.runSolver(payload)
	if err != nil {
		return AlternativesResult{Success: false, Slot: payload.TargetSlot, ErrorMessage: err.Error()}, err
	}

	var result AlternativesResult
	if err := json.Unmarshal(raw, &result); err != nil {
		return AlternativesResult{
			Success:      false,
			Slot:         payload.TargetSlot,
			ErrorMessage: "Could not read the solver's result: " + err.Error(),
		}, err
	}
	if result.Slot == "" {
		result.Slot = payload.TargetSlot
	}
	return result, nil
}

const (
	minAlternatives = 3
	maxAlternatives = 10
)

// GetSystemLogs retrieves real-time execution logs.
func (a *App) GetSystemLogs() []string {
	return a.logs
}

// GetAvailableItems returns items for a given slot, maxLevel, and artifact filter
func (a *App) GetAvailableItems(slot string, maxLevel int, searchTerm string) []models.XMLItem {
	results := make([]models.XMLItem, 0)
	minLvl := maxLevel - 6
	searchTermLower := strings.ToLower(searchTerm)
	for _, item := range a.itemsCache {
		if item.MinLevel >= minLvl && item.MinLevel <= maxLevel {
			for _, s := range item.EquipmentSlot.Slots {
				slotName := s.Local
				if slotName == slot || (slot == "Ring_1" && slotName == "Ring") || (slot == "Ring_2" && slotName == "Ring") {
					if searchTermLower == "" || strings.Contains(strings.ToLower(item.Name), searchTermLower) || strings.Contains(strings.ToLower(item.RawXML), searchTermLower) {
						results = append(results, item)
					}
					break
				}
			}
		}
	}

	sort.Slice(results, func(i, j int) bool {
		return results[i].MinLevel > results[j].MinLevel
	})

	return results
}

// GetItemDetails returns the full XMLItem for a given item name
func (a *App) GetItemDetails(itemName string) models.XMLItem {
	if idx, ok := a.itemsByName[itemName]; ok && idx < len(a.itemsCache) {
		return a.itemsCache[idx]
	}
	return models.XMLItem{}
}

// GetSetBonus returns a named set's full tier detail.
//
// GetSetBonus, GetAugmentByName and GetFiligreeByName share one contract: exact
// name match, index-backed, and a ZERO-VALUE struct (not an error) on a miss, so
// the frontend can treat an empty Type/Name as the single not-found signal.
func (a *App) GetSetBonus(name string) models.XMLSetBonus {
	if idx, ok := a.setsByName[name]; ok && idx < len(a.setBonusCache) {
		return a.setBonusCache[idx]
	}
	return models.XMLSetBonus{}
}

// GetAugmentByName returns one augment's full detail by exact name.
//
// Deliberately NOT filtered by MinLevel or slot color, unlike
// GetAvailableAugments: an augment that is already socketed must stay resolvable
// for display regardless of the current max_level setting or which color slot it
// occupies (docs/ITEM_DETAIL_SPEC.md §4.5, EC-9).
func (a *App) GetAugmentByName(name string) models.XMLAugment {
	if idx, ok := a.augmentsByName[name]; ok && idx < len(a.augmentsCache) {
		return a.augmentsCache[idx]
	}
	return models.XMLAugment{}
}

// GetFiligreeByName returns one filigree's full detail by exact name, unfiltered
// — same rationale as GetAugmentByName.
func (a *App) GetFiligreeByName(name string) models.XMLFiligree {
	if idx, ok := a.filigreesByName[name]; ok && idx < len(a.filigreesCache) {
		return a.filigreesCache[idx]
	}
	return models.XMLFiligree{}
}

// GetAvailableAugments returns augments matching a given slot type (e.g. Green), maxLevel, and search term
func (a *App) GetAvailableAugments(slotType string, maxLevel int, searchTerm string) []models.XMLAugment {
	results := make([]models.XMLAugment, 0)
	searchTermLower := strings.ToLower(searchTerm)

	// DDO Rules mapping - green takes yellow or blue, purple takes clear or blue, etc.
	// But in DDOBuilder, augments specify which types they can fit into via multiple <Type> elements!
	// E.g. <Type>Blue</Type>, <Type>Green</Type>

	for _, aug := range a.augmentsCache {
		if aug.MinLevel <= maxLevel {
			matchType := false
			for _, t := range aug.Types {
				if t == slotType {
					matchType = true
					break
				}
			}

			if matchType {
				if searchTermLower == "" || strings.Contains(strings.ToLower(aug.Name), searchTermLower) || strings.Contains(strings.ToLower(aug.RawXML), searchTermLower) {
					results = append(results, aug)
				}
			}
		}
	}

	sort.Slice(results, func(i, j int) bool {
		return results[i].MinLevel > results[j].MinLevel
	})

	return results
}

// GetAvailableFiligrees returns filigrees matching a search term (by Name, Menu, or SetName)
func (a *App) GetAvailableFiligrees(searchTerm string) []models.XMLFiligree {
	results := make([]models.XMLFiligree, 0)
	searchTermLower := strings.ToLower(searchTerm)

	for _, fil := range a.filigreesCache {
		if searchTermLower == "" ||
			strings.Contains(strings.ToLower(fil.Name), searchTermLower) ||
			strings.Contains(strings.ToLower(fil.SetName), searchTermLower) ||
			strings.Contains(strings.ToLower(fil.Menu), searchTermLower) ||
			strings.Contains(strings.ToLower(fil.RawXML), searchTermLower) {
			results = append(results, fil)
		}
	}

	sort.Slice(results, func(i, j int) bool {
		return results[i].Name < results[j].Name
	})

	return results
}

// OpenFile opens a file using the default OS application.
func (a *App) OpenFile(filePath string) error {
	absPath, err := filepath.Abs(filePath)
	if err != nil {
		return err
	}
	return exec.Command("open", absPath).Start()
}

// SaveGearset persists a build and writes a .ddogearset export of it.
//
// Both, on purpose. app.db is the storage from 0.5.1 on (schema §8 Q3), but a
// file is the only thing you can hand to somebody else, so exporting stays —
// same format, same version "1.2", same checksum, byte-for-byte what 0.5.0
// wrote. Whichever the user thinks they pressed, they get both.
//
// The database write is the one that must not be silently skipped: a save
// reported as successful that only produced a file would look identical from
// the UI and lose the build on the next launch. The export is best-effort by
// comparison — it is a copy.
func (a *App) SaveGearset(payload OptimizationPayload, result ResultPayload) (string, error) {
	if err := a.persistBuild(payload); err != nil {
		return "", err
	}
	return a.exportGearsetFile(payload, result)
}

// persistBuild upserts the configuration and equipped gearset into app.db.
func (a *App) persistBuild(payload OptimizationPayload) error {
	if a.appDB == nil {
		return fmt.Errorf("user data is unavailable, so this build cannot be saved")
	}
	config, err := payloadAsMap(payload)
	if err != nil {
		return err
	}
	resolver, closeCatalog, err := a.nameResolver()
	if err != nil {
		return err
	}
	defer closeCatalog()

	saved, err := appdb.SaveBuild(a.appDB, resolver, config, AppVersion)
	if err != nil {
		return err
	}
	verb := "Updated"
	if saved.Created {
		verb = "Saved"
	}
	a.addLog(fmt.Sprintf("%s build %q (%d unresolved reference(s)).",
		verb, saved.Name, len(saved.Orphans)))
	return nil
}

// payloadAsMap round-trips the payload through JSON so appdb sees exactly the
// field names the .ddogearset format uses — which is what lets a save and an
// import share one writer.
func payloadAsMap(payload OptimizationPayload) (map[string]interface{}, error) {
	raw, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("serializing the build: %w", err)
	}
	var config map[string]interface{}
	if err := json.Unmarshal(raw, &config); err != nil {
		return nil, fmt.Errorf("serializing the build: %w", err)
	}
	return config, nil
}

// nameResolver opens the catalog for the duration of one operation and returns
// a closer. Names resolve to UUIDs at write time; nothing keeps the catalog
// open for it.
func (a *App) nameResolver() (appdb.Catalog, func(), error) {
	path := a.catalogDBPath
	if path == "" {
		path = catalogPath()
	}
	catalogDB, err := catalog.Open(path)
	if err != nil {
		return nil, func() {}, fmt.Errorf("cannot resolve item names without the catalog: %w", err)
	}
	resolver, err := appdb.NewSQLCatalog(catalogDB)
	if err != nil {
		catalogDB.Close()
		return nil, func() {}, err
	}
	return resolver, func() { catalogDB.Close() }, nil
}

// exportGearsetFile writes the .ddogearset. Unchanged in format from 0.5.0 —
// only the DIRECTORY moved, out of the process working directory and into the
// user data directory (see gearsetExportDir).
func (a *App) exportGearsetFile(payload OptimizationPayload, result ResultPayload) (string, error) {
	timestamp := time.Now().Format("20060102150405")
	bt := strings.ReplaceAll(payload.BuildType, " ", "")
	ws := strings.ReplaceAll(payload.WeaponStyle, " ", "")
	name := strings.ReplaceAll(payload.GearsetName, " ", "_")

	var filename string
	if name != "" {
		filename = fmt.Sprintf("%s_%s%s_%s.ddogearset", name, bt, ws, timestamp)
	} else {
		filename = fmt.Sprintf("%s%s_%s.ddogearset", bt, ws, timestamp)
	}

	dir, err := gearsetExportDir()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(dir, 0755); err != nil {
		return "", fmt.Errorf("creating the export directory: %w", err)
	}

	path := filepath.Join(dir, filename)

	saveData := map[string]interface{}{
		"version": "1.2",
		// app_version is the release version that produced this file (see
		// AppVersion) — distinct from "version" above, which is the .ddogearset
		// file-format schema version, not the app's release version.
		"app_version":  AppVersion,
		"gearset_name": payload.GearsetName,
		"saved_at":     time.Now().Format(time.RFC3339),
		"config":       payload,
		"result":       result,
	}

	// checksum lets VerifyGearsetChecksum (gearset_checksum.go) detect a file
	// edited outside the app between save and load — see that file's doc
	// comment for why this must be computed via gearsetChecksum() and not
	// hashed some other way.
	checksum, err := gearsetChecksum(saveData)
	if err != nil {
		return "", err
	}
	saveData["checksum"] = checksum

	bytes, err := json.MarshalIndent(saveData, "", "  ")
	if err != nil {
		return "", err
	}

	err = os.WriteFile(path, bytes, 0644)
	return path, err
}

// --- Stat sets (docs/TIERED_SOLVER_FRONTEND_SPEC.md §6) ---------------------

// StatSetsFileVersion is the only schema version this build understands. An
// override file declaring anything else is treated exactly like a parse
// failure (spec EC-5) rather than migrated, since only one version exists.
const StatSetsFileVersion = 1

// StatSetPriority is one entry of a preset. Deliberately NOT StatPriorityEntry:
// presets never carry the legacy `value` field, and `tier` is mandatory here.
type StatSetPriority struct {
	Stat string `json:"stat"`
	Tier int    `json:"tier"`
	Cap  *int   `json:"cap,omitempty"`
}

// StatSet is one named, hand-authored bundle of priorities.
type StatSet struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	// BuildTypes drives SOFT ordering in the UI only (matching sets float to
	// the top). It is never a hard filter — see spec §6.1/EC-4.
	BuildTypes  []string          `json:"buildTypes"`
	Description string            `json:"description"`
	Notes       *string           `json:"notes"` // pointer: the schema uses explicit null
	Priorities  []StatSetPriority `json:"priorities"`
}

type StatSetsFile struct {
	Version int       `json:"version"`
	Sets    []StatSet `json:"sets"`
}

// GetStatSets returns the user's stat-set presets. It checks for a
// hand-editable override file first (./stat_sets.json, alongside the existing
// gearsets/ directory), and falls back to the bundled default embedded in the
// binary if no override file exists, it fails to parse, or it declares an
// unsupported version.
//
// Re-reads the override file from disk on every call — no caching — so
// hand-edits take effect on the next call with no app restart required.
func (a *App) GetStatSets() (StatSetsFile, error) {
	if data, err := os.ReadFile("stat_sets.json"); err == nil {
		var parsed StatSetsFile
		if err := json.Unmarshal(data, &parsed); err != nil {
			a.addLog("Warning: stat_sets.json exists but failed to parse; using bundled defaults.")
		} else if parsed.Version != StatSetsFileVersion {
			a.addLog(fmt.Sprintf("Warning: stat_sets.json declares unsupported version %d (expected %d); using bundled defaults.", parsed.Version, StatSetsFileVersion))
		} else {
			return parsed, nil
		}
	}

	var parsed StatSetsFile
	if err := json.Unmarshal(defaultStatSets, &parsed); err != nil {
		// The embedded file is compiled in, so this is a build-time defect
		// rather than a user-recoverable condition; surface it instead of
		// silently returning an empty list.
		return StatSetsFile{Version: StatSetsFileVersion}, fmt.Errorf("bundled stat sets are corrupt: %w", err)
	}
	return parsed, nil
}

// --- Stat Search (docs/DUPLICATE_STATS_AND_ITEM_SEARCH_PLAN.md) ---

type StatSearchPayload struct {
	Mode     string `json:"mode"`
	Stat     string `json:"stat"`
	MaxLevel int    `json:"max_level"`
}

type StatSearchEntry struct {
	SourceType string   `json:"sourceType"`
	SourceName string   `json:"sourceName"`
	BonusType  string   `json:"bonusType"`
	Value      float64  `json:"value"`
	ML         int      `json:"ml"`
	Slots      []string `json:"slots,omitempty"`
	Pack       *string  `json:"pack,omitempty"`
}

type StatSearchResult struct {
	Stat         string            `json:"stat"`
	Results      []StatSearchEntry `json:"results"`
	Success      bool              `json:"success"`
	ErrorMessage string            `json:"errorMessage,omitempty"`
}

func (a *App) SearchItemsByStat(stat string, maxLevel int) (StatSearchResult, error) {
	payload := StatSearchPayload{
		Mode:     "stat_search",
		Stat:     stat,
		MaxLevel: maxLevel,
	}
	raw, err := a.runSolver(payload)
	if err != nil {
		return StatSearchResult{Success: false, Stat: stat, ErrorMessage: err.Error()}, err
	}
	var result StatSearchResult
	if err := json.Unmarshal(raw, &result); err != nil {
		return StatSearchResult{Success: false, Stat: stat, ErrorMessage: "Could not read the solver's result: " + err.Error()}, err
	}
	if result.ErrorMessage != "" && !result.Success {
		return result, nil
	}
	result.Success = true
	if result.Results == nil {
		result.Results = []StatSearchEntry{}
	}
	return result, nil
}
