package main

import (
	"bufio"
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

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

// App struct
type App struct {
	ctx            context.Context
	logs           []string
	solverPath     string
	glpsolPath     string
	solverDir      string
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

	// Fetch DDOBuilderV2 before loading caches from it — on a fresh checkout
	// this directory doesn't exist yet, so this is what makes "clone this repo
	// and run" work with no manual setup step. checkForUpdates=false: a normal
	// launch never makes an extra network round trip once the data is already
	// there — checking for updates is what the "Update External Sources"
	// button is for. Both run in the same background goroutine so startup()
	// itself returns immediately.
	go func() {
		if _, err := a.ensureDDOBuilderData(false); err != nil {
			a.addLog("Warning: failed to fetch DDOBuilderV2 data: " + err.Error())
		}
		a.loadCaches("Cached")
	}()

	a.initOnce.Do(func() {
		if err := a.extractSolver(); err != nil {
			a.addLog("Warning: failed to extract bundled solver: " + err.Error())
		}
	})
}

// ensureDDOBuilderData makes sure DDOBuilderV2 is present, fetching it over
// HTTPS if it's missing entirely (see ddobuilder_fetch.go —
// docs/DDOBUILDER_FETCH_WITHOUT_GIT_PLAN.md has the full rationale for why
// this isn't `git clone`/`git pull` anymore). Shared by startup() and
// UpdateExternalSources() so the two can't drift into different behavior.
//
// checkForUpdates controls whether an ALREADY-PRESENT checkout is checked
// against the latest upstream commit — that's one GitHub API call, cheap,
// but still a network round trip, so startup() passes false (a normal
// launch shouldn't pay that cost) and UpdateExternalSources() passes true
// (checking is the entire point of that button). When the directory is
// missing entirely there's nothing to compare against, so this parameter is
// irrelevant to that path — it always fetches.
func (a *App) ensureDDOBuilderData(checkForUpdates bool) (string, error) {
	_, statErr := os.Stat(ddoRepoDir)
	switch {
	case statErr == nil && !checkForUpdates:
		return "DDOBuilderV2 already present.", nil
	case statErr == nil && checkForUpdates:
		return a.updateDDOBuilderDataIfStale()
	case os.IsNotExist(statErr):
		return a.fetchDDOBuilderData(
			fmt.Sprintf("DDOBuilderV2 not found at ./%s — downloading (~80MB, one-time)...", ddoRepoDir), "")
	default:
		return "", statErr
	}
}

// updateDDOBuilderDataIfStale checks GitHub for the latest commit on main
// and only downloads the (~79MB) archive if it differs from what's recorded
// in ddoCommitMarkerPath from the last successful fetch.
func (a *App) updateDDOBuilderDataIfStale() (string, error) {
	latestSHA, err := latestDDOBuilderCommitSHA()
	if err != nil {
		msg := "Could not check DDOBuilderV2 for updates: " + err.Error()
		a.addLog("Warning: " + msg + " (existing data is still usable)")
		return msg, nil
	}
	storedSHA, _ := os.ReadFile(ddoCommitMarkerPath)
	if strings.TrimSpace(string(storedSHA)) == latestSHA {
		a.addLog("DDOBuilderV2 is already up to date.")
		return "Already up to date.", nil
	}
	return a.fetchDDOBuilderData(
		fmt.Sprintf("DDOBuilderV2 update available (commit %s) — downloading (~80MB)...", shortSHA(latestSHA)),
		latestSHA)
}

// fetchDDOBuilderData does the actual download+extract and records the
// fetched commit SHA for next time. knownSHA avoids a second GitHub API call
// when the caller already looked it up (the "update" path); pass "" when it
// hasn't been (the "missing entirely" path) and this will look it up once,
// after the fetch, purely to populate the marker for future checks.
func (a *App) fetchDDOBuilderData(logMsg string, knownSHA string) (string, error) {
	a.addLog(logMsg)
	if err := fetchAndExtractDDOBuilderZip(); err != nil {
		a.addLog("Failed to fetch DDOBuilderV2: " + err.Error())
		return "", err
	}

	sha := knownSHA
	if sha == "" {
		var err error
		sha, err = latestDDOBuilderCommitSHA()
		if err != nil {
			a.addLog("DDOBuilderV2 fetched, but couldn't record its version: " + err.Error())
			return "DDOBuilderV2 fetched successfully (version marker not saved).", nil
		}
	}
	if err := os.WriteFile(ddoCommitMarkerPath, []byte(sha), 0644); err != nil {
		a.addLog("DDOBuilderV2 fetched, but couldn't save version marker: " + err.Error())
		return "DDOBuilderV2 fetched successfully (version marker not saved).", nil
	}

	msg := "DDOBuilderV2 fetched successfully (commit " + shortSHA(sha) + ")."
	a.addLog(msg)
	return msg, nil
}

// DDOBuilder data-file locations. Previously repeated inline at both cache-load
// sites; centralized here so startup() and UpdateExternalSources() cannot drift.
//
// ddoRepoDir is project-relative (resolved against the process's working
// directory, exactly like packMappingsPath below already was) rather than a
// hardcoded absolute path — the old "/Users/jorgecosgayon/dev/ddo/DDOBuilderV2"
// only ever worked on one specific machine. ensureDDOBuilderData() fetches it
// here on first run if it's missing (over HTTPS, no git binary required — see
// ddobuilder_fetch.go), so a fresh checkout is enough; nothing needs to
// pre-exist outside the project. It's gitignored (see .gitignore) — this is
// fetched data, not source.
const (
	ddoRepoDir  = "DDOBuilderV2"
	ddoDataRoot = ddoRepoDir + "/Output/DataFiles"

	ddoItemsPath        = ddoDataRoot + "/Items"
	ddoAugmentsPath     = ddoDataRoot + "/Augments"
	ddoFiligreeSetsPath = ddoDataRoot + "/FiligreeSets"
	// A single file, not a directory. ParseSetBonuses accepts either, and
	// pointing it at the file avoids walking (and reporting as "skipped") every
	// unrelated .xml in DataFiles.
	ddoSetBonusesPath = ddoDataRoot + "/SetBonuses.xml"

	packMappingsPath = "data/PackMappings.json"
	// No raids data source exists in this repo. Raid detection is therefore
	// unavailable and every item reports IsRaid == false — this is a deliberate,
	// documented scoping decision (docs/ITEM_DETAIL_SPEC.md §4.3, §11.1), not an
	// oversight, and the item panel says so rather than claiming "not a raid".
	raidsPath = ""
)

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
	raidsLoaded, err := services.InitEnrichment(packMappingsPath, raidsPath)
	if err != nil {
		// Fatal for enrichment only: items still load, they just carry no pack
		// attribution. Everything else in the app is unaffected.
		a.addLog("Failed to load pack mappings, item pack attribution unavailable: " + err.Error())
	}
	if !raidsLoaded {
		a.addLog("Raid detection is disabled: no raids data source is available.")
	}

	logSkipped := func(kind string, skipped []string) {
		if len(skipped) > 0 {
			a.addLog(fmt.Sprintf("Skipped %d unparseable %s file(s); the rest loaded normally.", len(skipped), kind))
		}
	}

	items, skippedItems, errItems := services.ParseItems(ddoItemsPath)
	logSkipped("item", skippedItems)
	if errItems == nil {
		for i := range items {
			services.EnrichItemInPlace(&items[i])
		}
		a.itemsCache = items
		a.itemsByName = buildNameIndex(items, func(it models.XMLItem) string { return it.Name })
		a.addLog(fmt.Sprintf("%s %d items for Gearset Editor", verb, len(items)))
	} else {
		a.addLog("Failed to cache items: " + errItems.Error())
	}

	augments, skippedAugs, errAugs := services.ParseAugments(ddoAugmentsPath)
	logSkipped("augment", skippedAugs)
	if errAugs == nil {
		a.augmentsCache = augments
		a.augmentsByName = buildNameIndex(augments, func(g models.XMLAugment) string { return g.Name })
		a.addLog(fmt.Sprintf("%s %d augments for Gearset Editor", verb, len(augments)))
	} else {
		a.addLog("Failed to cache augments: " + errAugs.Error())
	}

	filigrees, skippedFils, errFils := services.ParseFiligrees(ddoFiligreeSetsPath)
	logSkipped("filigree", skippedFils)
	if errFils == nil {
		a.filigreesCache = filigrees
		a.filigreesByName = buildNameIndex(filigrees, func(f models.XMLFiligree) string { return f.Name })
		a.addLog(fmt.Sprintf("%s %d filigrees for Gearset Editor", verb, len(filigrees)))
	} else {
		a.addLog("Failed to cache filigrees: " + errFils.Error())
	}

	// Item/armor set bonuses and filigree set bonuses share one cache and one
	// index so the panel resolves any set name through a single lookup.
	sets, skippedSets, errSets := services.ParseSetBonuses(ddoSetBonusesPath)
	logSkipped("set bonus", skippedSets)
	if errSets != nil {
		a.addLog("Failed to cache set bonuses: " + errSets.Error())
	} else {
		filigreeSets, skippedFilSets, errFilSets := services.ParseFiligreeSetBonuses(ddoFiligreeSetsPath)
		logSkipped("filigree set bonus", skippedFilSets)
		if errFilSets == nil {
			sets = append(sets, filigreeSets...)
		}
		a.setBonusCache = sets
		a.setsByName = buildNameIndex(sets, func(s models.XMLSetBonus) string { return s.Type })
		a.addLog(fmt.Sprintf("%s %d set bonuses", verb, len(sets)))
	}
}

// extractSolver writes every file embedded in bundleFS (the Python solver,
// glpsol, and glpsol's own shared-library dependencies — see
// embed_<GOOS>_<GOARCH>.go) into one flat temp directory, so glpsol and its
// libraries end up siblings on disk exactly as they were staged by
// build_releases.sh. That co-location is what makes the platform's dynamic
// linker able to find them: on macOS the bundled glpsol has its library
// references rewritten to @executable_path (see build_releases.sh's
// install_name_tool step) and needs no extra help; on Linux/Windows,
// runSolver additionally points LD_LIBRARY_PATH/the process's own directory
// at this same tmpDir as a fallback (harmless no-op on platforms that don't
// use it).
func (a *App) extractSolver() error {
	tmpDir, err := os.MkdirTemp("", "ddo-solver-*")
	if err != nil {
		return err
	}

	entries, err := bundleFS.ReadDir(bundleRoot)
	if err != nil {
		return fmt.Errorf("reading embedded solver bundle: %w", err)
	}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		data, err := bundleFS.ReadFile(bundleRoot + "/" + entry.Name())
		if err != nil {
			return fmt.Errorf("reading embedded %s: %w", entry.Name(), err)
		}
		if err := os.WriteFile(filepath.Join(tmpDir, entry.Name()), data, 0755); err != nil {
			return fmt.Errorf("extracting %s: %w", entry.Name(), err)
		}
	}

	a.solverDir = tmpDir
	a.solverPath = filepath.Join(tmpDir, solverBinaryName)
	a.glpsolPath = filepath.Join(tmpDir, glpsolBinaryName)
	if _, err := os.Stat(a.solverPath); err != nil {
		return fmt.Errorf("bundle did not contain %s: %w", solverBinaryName, err)
	}
	if _, err := os.Stat(a.glpsolPath); err != nil {
		return fmt.Errorf("bundle did not contain %s: %w", glpsolBinaryName, err)
	}
	a.addLog(fmt.Sprintf("Solver and GLPK extracted to %s", tmpDir))
	return nil
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
	GearsetName                string              `json:"gearset_name"`
	MaxLevel                   int                 `json:"max_level"`
	BuildType                  string              `json:"build_type"`
	WeaponStyle                string              `json:"weapon_style"`
	Swashbuckling              bool                `json:"swashbuckling"`
	OffhandStyle               string              `json:"offhand_style"`
	// WeaponDamageType (Slashing/Piercing/Bludgeoning) restricts the
	// hard-required Weapon1 slot for Melee builds — see
	// docs/HARD_REQUIRED_SLOTS_SPEC.md. Ignored for every other build_type;
	// Ranged/Tank don't have a heuristic defined yet (deliberately deferred).
	WeaponDamageType           string              `json:"weapon_damage_type,omitempty"`
	CasterSpellpowers          []string            `json:"caster_spellpowers"`
	CasterSchools              []string            `json:"caster_schools"`
	StatPriorities             []StatPriorityEntry `json:"stat_priorities"`
	ArmorRestriction           string              `json:"armor_restriction"`
	ReservedMinorArtifactSlot  string              `json:"reserved_minor_artifact_slot"`
	MinorArtifactFiligreeSlots int                 `json:"minor_artifact_filigree_slots"`
	ExcludeGemOfManyFacets     bool                `json:"exclude_gem_of_many_facets"`
	RunearmUse                 bool                `json:"runearm_use"`
	ExcludedPacks              []string            `json:"excluded_packs"`
	// OwnedItemNames restricts item/augment selection to exact-name matches
	// against this set (see docs/TROVE_INVENTORY_IMPORT_SPEC.md and
	// LoadTroveInventory). Empty/absent means unrestricted — this is an
	// opt-in filter, not a standing mode, so nobody who hasn't loaded a
	// Trove export gets an accidentally-empty item pool.
	OwnedItemNames             []string            `json:"owned_item_names,omitempty"`
	RaidItemLimit              int                 `json:"raid_item_limit"`
	IsDinoArtifact             bool                `json:"is_dino_artifact"`
	OutputFilename             string              `json:"output_filename"`
	PreEquipped                map[string]string   `json:"pre_equipped"`
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
	cmd := exec.Command(a.solverPath, tmpFile)
	// GLPSOL_PATH tells optimizer.py's _glpk_cmd() exactly which bundled
	// glpsol to run instead of a hardcoded install path (see
	// docs/PHASE10_HANDOFF.md). LD_LIBRARY_PATH/DYLD_LIBRARY_PATH are set
	// unconditionally as a cross-platform fallback so glpsol's shared
	// libraries (co-extracted into a.solverDir) resolve even if a build's
	// dynamic-linker patching step (macOS's install_name_tool, see
	// build_releases.sh) was skipped or is incomplete for a given platform;
	// they're harmless no-ops on platforms/binaries that don't need them.
	// DDO_DATA_PATH gives solver.py the absolute path to the same
	// DDOBuilderV2 checkout ensureDDOBuilderData() maintains, so Python
	// doesn't independently depend on inheriting the Go process's working
	// directory to find it (see python/solver.py's base_dir resolution).
	ddoDataAbsPath, absErr := filepath.Abs(ddoDataRoot)
	if absErr != nil {
		ddoDataAbsPath = ddoDataRoot
	}
	cmd.Env = append(os.Environ(),
		"GLPSOL_PATH="+a.glpsolPath,
		"LD_LIBRARY_PATH="+a.solverDir,
		"DYLD_LIBRARY_PATH="+a.solverDir,
		"DDO_DATA_PATH="+ddoDataAbsPath,
	)
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
	return richResult, nil
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

// UpdateExternalSources fetches DDOBuilderV2 if it's stale or missing (see
// ensureDDOBuilderData) and reloads every cache from it.
func (a *App) UpdateExternalSources() (string, error) {
	a.addLog("Updating external sources from DDOBuilderV2...")

	out, err := a.ensureDDOBuilderData(true)
	if err != nil {
		return out, err
	}

	// Reload every cache, name index and the enrichment pass together, so no
	// index can survive pointing into a cache that has since been replaced.
	a.addLog("Reloading item, augment, filigree and set-bonus caches...")
	a.loadCaches("Reloaded")

	return out, nil
}

// OpenFile opens a file using the default OS application.
func (a *App) OpenFile(filePath string) error {
	absPath, err := filepath.Abs(filePath)
	if err != nil {
		return err
	}
	return exec.Command("open", absPath).Start()
}

// SaveGearset writes the payload and result to a .ddogearset file in the gearsets/ directory
func (a *App) SaveGearset(payload OptimizationPayload, result ResultPayload) (string, error) {
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

	dir := "gearsets"
	os.MkdirAll(dir, 0755)

	path := filepath.Join(dir, filename)

	saveData := map[string]interface{}{
		"version":      "1.2",
		"gearset_name": payload.GearsetName,
		"saved_at":     time.Now().Format(time.RFC3339),
		"config":       payload,
		"result":       result,
	}

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
