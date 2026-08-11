package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"goGearset/internal/appdb"
)

// Phase 2's remaining gate clauses, at the level the app actually runs at:
// SaveGearset persists AND exports, the export is the same file 0.5.0 wrote,
// and nothing lands in the process working directory.

func newTestApp(t *testing.T) *App {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("DDO_APP_DB", filepath.Join(dir, "app.db"))
	t.Setenv("DDO_GEARSET_DIR", filepath.Join(dir, "gearsets"))

	catalogFile := "bundled/darwin-arm64/catalog.db"
	if p := os.Getenv(catalogEnvVar); p != "" {
		catalogFile = p
	}
	if _, err := os.Stat(catalogFile); err != nil {
		t.Skipf("no catalog at %s", catalogFile)
	}

	app := NewApp()
	app.catalogDBPath = catalogFile
	if err := app.ensureAppDB(); err != nil {
		t.Fatalf("ensureAppDB: %v", err)
	}
	t.Cleanup(func() {
		if app.appDB != nil {
			app.appDB.Close()
		}
	})
	return app
}

func samplePayload() OptimizationPayload {
	return OptimizationPayload{
		GearsetName:                  "Round Trip",
		BuildType:                    "Caster",
		MaxLevel:                     34,
		WeaponStyle:                  "Dual Caster",
		OffhandStyle:                 "None",
		ArmorRestriction:             "Light",
		MinorArtifactFiligreeSlots:   5,
		RaidItemLimit:                -1,
		CasterRestrictWeaponFamilies: true,
		ExcludeGemOfManyFacets:       true,
		ExcludedPacks:                []string{"Some Pack"},
		CasterSpellpowers:            []string{"Force"},
		CasterSchools:                []string{},
		StatPriorities: []StatPriorityEntry{
			{Stat: "Force Spell Power", Tier: 1},
			{Stat: "Intelligence", Tier: 2},
		},
		PreEquipped: map[string]string{
			"Helmet": "Legendary Lamordian Bowler",
			"Armor":  "Legendary Downcast Vest",
		},
		PreFilledAugments: map[string]interface{}{
			"Armor": map[string]interface{}{"Yellow": "Topaz of Transmuted Power"},
		},
		PreFilledFiligrees: map[string][]string{
			"weapon":   {"Lunar Magic: +9 Force Spell Power"},
			"artifact": {},
		},
	}
}

func TestSaveGearsetPersistsAndExports(t *testing.T) {
	app := newTestApp(t)

	path, err := app.SaveGearset(samplePayload(), ResultPayload{Success: true})
	if err != nil {
		t.Fatalf("SaveGearset: %v", err)
	}

	// The build is in app.db...
	builds, err := app.ListBuilds()
	if err != nil {
		t.Fatalf("ListBuilds: %v", err)
	}
	if len(builds) != 1 {
		t.Fatalf("%d builds after one save, want 1", len(builds))
	}
	if builds[0].Name != "Round Trip" || builds[0].SlotCount != 2 {
		t.Errorf("build summary = %+v", builds[0])
	}

	// ...and the file is on disk, in the export directory.
	exportDir, err := gearsetExportDir()
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Dir(path) != exportDir {
		t.Errorf("exported to %s, want a file in %s", path, exportDir)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("export file missing: %v", err)
	}
}

func TestExportedFileMatchesThe0_5_0Format(t *testing.T) {
	// The gate: byte-comparable with what 0.5.0 would have written. Only the
	// DIRECTORY moved — the format, the version string and the checksum
	// algorithm are all unchanged, so a file exported by this build loads in an
	// older one and vice versa.
	app := newTestApp(t)

	path, err := app.SaveGearset(samplePayload(), ResultPayload{Success: true, TimeTaken: 1.5})
	if err != nil {
		t.Fatalf("SaveGearset: %v", err)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading the export: %v", err)
	}

	var file map[string]interface{}
	if err := json.Unmarshal(raw, &file); err != nil {
		t.Fatalf("the export is not valid JSON: %v", err)
	}
	for _, key := range []string{"version", "app_version", "gearset_name", "saved_at",
		"config", "result", "checksum"} {
		if _, ok := file[key]; !ok {
			t.Errorf("export is missing %q — 0.5.0's format has it", key)
		}
	}
	if file["version"] != "1.2" {
		t.Errorf("format version = %v, want 1.2 — changing it breaks older readers", file["version"])
	}
	if file["app_version"] != AppVersion {
		t.Errorf("app_version = %v, want %s", file["app_version"], AppVersion)
	}

	// The checksum must verify through the same function that has always
	// computed it, or every file this build exports looks tampered with.
	result, err := app.VerifyGearsetChecksum(string(raw))
	if err != nil {
		t.Fatalf("VerifyGearsetChecksum: %v", err)
	}
	if !result.HasChecksum || !result.Valid {
		t.Errorf("the exported file fails its own checksum: %+v", result)
	}

	// Indented, as SaveGearset has always written it — a diffable file is the
	// reason anyone can inspect one by hand.
	if !strings.Contains(string(raw), "\n  \"config\"") {
		t.Error("export is not indented the way 0.5.0 wrote it")
	}
}

func TestExportedFileImportsBackToTheSameBuild(t *testing.T) {
	app := newTestApp(t)

	path, err := app.SaveGearset(samplePayload(), ResultPayload{Success: true})
	if err != nil {
		t.Fatalf("SaveGearset: %v", err)
	}

	outcome, err := app.ImportGearsetFile(path)
	if err != nil {
		t.Fatalf("ImportGearsetFile: %v", err)
	}
	if outcome.Status != appdb.StatusImported {
		t.Fatalf("import status = %s (%s)", outcome.Status, outcome.Error)
	}
	if len(outcome.Orphans) != 0 {
		t.Errorf("the app's own export produced orphans on re-import: %+v", outcome.Orphans)
	}

	loaded, err := app.LoadBuild(outcome.BuildUUID)
	if err != nil {
		t.Fatalf("LoadBuild: %v", err)
	}
	original := samplePayload()
	if loaded.Config.GearsetName != original.GearsetName ||
		loaded.Config.BuildType != original.BuildType ||
		loaded.Config.MaxLevel != original.MaxLevel ||
		loaded.Config.ArmorRestriction != original.ArmorRestriction {
		t.Errorf("configuration changed through export/import: %+v", loaded.Config)
	}
	if len(loaded.Config.PreEquipped) != len(original.PreEquipped) {
		t.Errorf("pre_equipped = %v, want %v", loaded.Config.PreEquipped, original.PreEquipped)
	}
	if len(loaded.Config.StatPriorities) != 2 || loaded.Config.StatPriorities[0].Tier != 1 {
		t.Errorf("stat_priorities = %+v", loaded.Config.StatPriorities)
	}
}

func TestSavingWritesNothingToTheWorkingDirectory(t *testing.T) {
	// The inherited bug, asserted rather than assumed: a double-clicked .app's
	// working directory is not the user's home, and on a read-only volume the
	// old relative "gearsets" path failed outright.
	app := newTestApp(t)

	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	strayDir := filepath.Join(cwd, legacyGearsetDirName)
	before, _ := filepath.Glob(filepath.Join(strayDir, "*.ddogearset"))

	if _, err := app.SaveGearset(samplePayload(), ResultPayload{Success: true}); err != nil {
		t.Fatalf("SaveGearset: %v", err)
	}

	after, _ := filepath.Glob(filepath.Join(strayDir, "*.ddogearset"))
	if len(after) != len(before) {
		t.Errorf("saving wrote %d file(s) into the working directory at %s",
			len(after)-len(before), strayDir)
	}
}

func TestDeleteBuildRemovesIt(t *testing.T) {
	app := newTestApp(t)
	if _, err := app.SaveGearset(samplePayload(), ResultPayload{Success: true}); err != nil {
		t.Fatalf("SaveGearset: %v", err)
	}
	builds, _ := app.ListBuilds()
	if len(builds) != 1 {
		t.Fatalf("%d builds", len(builds))
	}

	if err := app.DeleteBuild(builds[0].UUID); err != nil {
		t.Fatalf("DeleteBuild: %v", err)
	}
	if remaining, _ := app.ListBuilds(); len(remaining) != 0 {
		t.Errorf("%d builds after deleting the only one", len(remaining))
	}
	if err := app.DeleteBuild(builds[0].UUID); err == nil {
		t.Error("deleting a build that is already gone reported success")
	}
}

func TestSaveFailsLoudlyWithoutUserData(t *testing.T) {
	// Silently exporting a file while failing to persist would look identical
	// in the UI and lose the build on the next launch.
	app := NewApp()
	app.catalogDBPath = "bundled/darwin-arm64/catalog.db"
	if _, err := app.SaveGearset(samplePayload(), ResultPayload{Success: true}); err == nil {
		t.Error("SaveGearset succeeded with no app.db open")
	}
}

func TestSolverRunsOutsideTheWorkingDirectory(t *testing.T) {
	// solver.py writes gearset_output.txt relative to ITS working directory,
	// which it inherits from this process — the same defect SaveGearset had.
	// Asserted on the command rather than by running a solve, because a real
	// solve takes tens of seconds and this is a one-line property.
	app := newTestApp(t)
	if err := app.extractSolver(); err != nil {
		t.Skipf("no bundled solver to run: %v", err)
	}

	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	dir, err := userDataDir()
	if err != nil {
		t.Fatal(err)
	}
	cmd := app.solverCommand("payload.json")
	if cmd.Dir == "" {
		t.Fatal("the solver inherits this process's working directory; " +
			"a packaged .app cannot write there")
	}
	if cmd.Dir == cwd {
		t.Errorf("solver working directory = %s, the process's own", cmd.Dir)
	}
	if cmd.Dir != dir {
		t.Errorf("solver working directory = %s, want the user data directory %s", cmd.Dir, dir)
	}
}

// --- Phase 3: the two-node model ------------------------------------------

func TestAFailedOptimizeLeavesEquippedUntouched(t *testing.T) {
	// The gate. Asserted through RunOptimization rather than the storage layer,
	// because the property has to hold at the level the UI calls: a solve that
	// errors must not have written anything.
	app := newTestApp(t)
	if _, err := app.SaveGearset(samplePayload(), ResultPayload{Success: true}); err != nil {
		t.Fatalf("SaveGearset: %v", err)
	}
	buildUUID := app.BuildIDForCurrentConfig("Round Trip")

	before := app.equippedSlots(t, buildUUID)
	if len(before) != 2 {
		t.Fatalf("setup: %d equipped slots, want 2", len(before))
	}

	// A payload with no stat priorities: solver.py rejects it during validation,
	// before parsing anything, and returns a failure payload.
	//
	// This used to rely on the solver being unable to START — which was true,
	// because go:embed had silently dropped its symlinks. Two tests were green
	// BECAUSE of that bug, and only went red when it was fixed. A test whose
	// premise is "the thing under test is broken" is worse than no test.
	failing := samplePayload()
	failing.StatPriorities = nil
	result, err := app.RunOptimization(failing)
	if err == nil && result.Success {
		t.Fatal("expected the optimize to fail with no stat priorities")
	}

	after := app.equippedSlots(t, buildUUID)
	if len(after) != len(before) {
		t.Errorf("a failed optimize changed equipped: %v -> %v", before, after)
	}
	has, err := appdb.HasSuggestion(app.appDB, buildUUID)
	if err != nil {
		t.Fatal(err)
	}
	if has {
		t.Error("a failed optimize recorded a suggestion")
	}
}

func TestAcceptAllPromotesTheSuggestion(t *testing.T) {
	app := newTestApp(t)
	if _, err := app.SaveGearset(samplePayload(), ResultPayload{Success: true}); err != nil {
		t.Fatalf("SaveGearset: %v", err)
	}
	buildUUID := app.BuildIDForCurrentConfig("Round Trip")

	// Stand in for a solve: the same call RunOptimization makes on success.
	app.recordSuggestion(samplePayload(), ResultPayload{
		Success: true,
		GearSet: map[string]interface{}{"Helmet": "Legendary Downcast Vest"},
	})

	updated, err := app.AcceptAll(buildUUID)
	if err != nil {
		t.Fatalf("AcceptAll: %v", err)
	}
	if len(updated.Config.PreEquipped) != 1 ||
		updated.Config.PreEquipped["Helmet"] != "Legendary Downcast Vest" {
		t.Errorf("equipped after AcceptAll = %v", updated.Config.PreEquipped)
	}
}

func TestShouldRecordSuggestionGuardsBothCases(t *testing.T) {
	// The guard the two-node model rests on. `calculate` evaluates gear the
	// user already has and proposes nothing; an empty result proposes nothing
	// either, and storing it would put a one-click gearset-eraser behind the
	// Accept All button.
	withGear := ResultPayload{Success: true,
		GearSet: map[string]interface{}{"Helmet": "Legendary Lamordian Bowler"}}

	optimize := samplePayload()
	if !shouldRecordSuggestion(optimize, withGear) {
		t.Error("an optimize that proposed a gearset was not recorded")
	}

	for _, mode := range []string{"calculate", "recalculate"} {
		evaluating := samplePayload()
		evaluating.Mode = mode
		if shouldRecordSuggestion(evaluating, withGear) {
			t.Errorf("%s mode recorded a suggestion; it evaluates gear you already "+
				"have and proposes nothing", mode)
		}
	}

	legacy := samplePayload()
	legacy.CalculateOnly = true
	if shouldRecordSuggestion(legacy, withGear) {
		t.Error("the legacy calculate_only flag recorded a suggestion")
	}

	if shouldRecordSuggestion(optimize, ResultPayload{Success: true}) {
		t.Error("a result with no gearset was recorded as a suggestion")
	}
	if shouldRecordSuggestion(optimize, ResultPayload{Success: false, GearSet: withGear.GearSet}) {
		t.Error("a failed result was recorded as a suggestion")
	}
}

// equippedSlots reads a build's equipped gearset for comparison.
func (a *App) equippedSlots(t *testing.T, buildUUID string) map[string]string {
	t.Helper()
	loaded, err := a.LoadBuild(buildUUID)
	if err != nil {
		t.Fatalf("LoadBuild: %v", err)
	}
	return loaded.Config.PreEquipped
}

// --- Phase 5: calculate is gone -------------------------------------------

func TestRecalculationRequestCannotCarryARestriction(t *testing.T) {
	// The type IS the guarantee. solver.py rejects a restriction at runtime;
	// this makes it unrepresentable a layer earlier, so nothing has to remember
	// to strip one on the way through — a field removed in transit is a field
	// somebody re-adds later.
	forbidden := []string{
		"ArmorRestriction", "ExcludedPacks", "OwnedItemNames", "RaidItemLimit",
		"WeaponStyle", "OffhandStyle", "WeaponDamageType",
		"ReservedMinorArtifactSlot", "CasterRestrictWeaponFamilies",
		"ExcludeGemOfManyFacets", "IsDinoArtifact", "MaxSearchTime",
	}
	typ := reflect.TypeOf(RecalculationRequest{})
	for _, name := range forbidden {
		if _, found := typ.FieldByName(name); found {
			t.Errorf("RecalculationRequest grew a %s field — a search restriction "+
				"can now reach an evaluation of gear the user already has", name)
		}
	}

	// ...and it still carries everything an evaluation genuinely needs.
	for _, name := range []string{"StatPriorities", "PreEquipped",
		"PreFilledAugments", "PreFilledFiligrees", "MaxLevel", "BuildType"} {
		if _, found := typ.FieldByName(name); !found {
			t.Errorf("RecalculationRequest is missing %s", name)
		}
	}
}

func TestNarrowingDropsRestrictionsAndKeepsTheGearset(t *testing.T) {
	full := samplePayload()
	full.ArmorRestriction = "Light"
	full.ExcludedPacks = []string{"Some Pack"}

	narrowed := RecalculationRequestFrom(full)
	if narrowed.GearsetName != full.GearsetName ||
		len(narrowed.PreEquipped) != len(full.PreEquipped) ||
		len(narrowed.StatPriorities) != len(full.StatPriorities) {
		t.Errorf("narrowing lost part of the gearset: %+v", narrowed)
	}

	// Round-tripping through JSON is what actually reaches the solver, so
	// assert on THAT rather than on the struct: a stray json tag would put a
	// restriction back on the wire.
	raw, err := json.Marshal(narrowed)
	if err != nil {
		t.Fatal(err)
	}
	var onTheWire map[string]interface{}
	if err := json.Unmarshal(raw, &onTheWire); err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"armor_restriction", "excluded_packs",
		"owned_item_names", "raid_item_limit", "weapon_style", "max_search_time"} {
		if _, present := onTheWire[field]; present {
			t.Errorf("%q reached the wire in a recalculation request", field)
		}
	}
	if onTheWire["mode"] != nil {
		t.Error("the request carries its own mode; RecalculateGearset sets it")
	}
}

// --- Phase 6: run history --------------------------------------------------

func TestRunHistoryIsRecordedWithTheCatalogRevision(t *testing.T) {
	app := newTestApp(t)
	if _, err := app.SaveGearset(samplePayload(), ResultPayload{Success: true}); err != nil {
		t.Fatal(err)
	}
	buildUUID := app.BuildIDForCurrentConfig("Round Trip")

	app.recordRun(samplePayload(), "recalculate", ResultPayload{
		Success:       true,
		RealizedStats: map[string]interface{}{"Charisma": 8.0},
		ActiveSets:    []string{"Lunar Magic (2-piece)", "Lunar Magic (3-piece)"},
	}, 0.7, nil)

	runs, err := app.ListRuns(buildUUID)
	if err != nil {
		t.Fatalf("ListRuns: %v", err)
	}
	if len(runs) != 1 {
		t.Fatalf("%d runs, want 1", len(runs))
	}
	if !runs[0].Succeeded || runs[0].Mode != "recalculate" {
		t.Errorf("run = %+v", runs[0])
	}
	// The point of the column: which game data produced these numbers.
	if runs[0].CatalogCommit == "" {
		t.Error("the run did not record which catalog produced it")
	}
	t.Logf("recorded run against catalog %s", runs[0].CatalogCommit)
}

func TestAFailedSolveIsStillRecorded(t *testing.T) {
	app := newTestApp(t)
	if _, err := app.SaveGearset(samplePayload(), ResultPayload{Success: true}); err != nil {
		t.Fatal(err)
	}
	buildUUID := app.BuildIDForCurrentConfig("Round Trip")

	// No stat priorities: rejected during validation. See the note in
	// TestAFailedOptimizeLeavesEquippedUntouched — this deliberately does NOT
	// rely on the solver failing to start.
	failing := samplePayload()
	failing.StatPriorities = nil
	result, err := app.RunOptimization(failing)
	if err == nil && result.Success {
		t.Fatal("expected the optimize to fail with no stat priorities")
	}

	runs, err := app.ListRuns(buildUUID)
	if err != nil {
		t.Fatal(err)
	}
	if len(runs) != 1 {
		t.Fatalf("%d runs after a failed solve, want 1 — a failure is exactly "+
			"what history is for", len(runs))
	}
	if runs[0].Succeeded || runs[0].ErrorMessage == "" {
		t.Errorf("the failure was recorded as %+v", runs[0])
	}
}

func TestSolveModeNormalizesForTheRunConstraint(t *testing.T) {
	// run.mode's CHECK admits three values; an empty or legacy mode must
	// normalize rather than abort the record over a reporting detail.
	if got := solveMode(OptimizationPayload{}); got != "optimize" {
		t.Errorf("empty mode = %q, want optimize", got)
	}
	if got := solveMode(OptimizationPayload{CalculateOnly: true}); got != "recalculate" {
		t.Errorf("calculate_only = %q, want recalculate", got)
	}
	for _, mode := range []string{"recalculate", "alternatives"} {
		if got := solveMode(OptimizationPayload{Mode: mode}); got != mode {
			t.Errorf("%s = %q", mode, got)
		}
	}
}

func TestSolverFieldsSurviveTheGoBoundary(t *testing.T) {
	// The test this class of bug needed. encoding/json DISCARDS any field the
	// target struct does not declare, silently — so a value Python emits and
	// ResultPayload omits reaches neither the frontend nor run history, with
	// nothing reporting a problem anywhere.
	//
	// It happened to all three of otherStats / allEffectsDetail / warnings: the
	// solver emitted them, the UI rendered "Location unavailable" for every
	// duplicated stat, and every test passed — because the Python tests compare
	// the solver's JSON directly and the Go tests built ResultPayload by hand.
	// Nothing crossed the line where the loss occurred.
	app := newTestApp(t)
	if err := app.extractSolver(); err != nil {
		t.Skipf("no bundled solver: %v", err)
	}

	result, err := app.RecalculateGearset(RecalculationRequestFrom(samplePayload()))
	if err != nil {
		t.Fatalf("RecalculateGearset: %v", err)
	}
	if !result.Success {
		t.Fatalf("recalculation failed: %s", result.ErrorMessage)
	}

	if len(result.AllEffects) == 0 {
		t.Fatal("allEffects is empty; this fixture should produce effects")
	}
	if len(result.AllEffectsDetail) == 0 {
		t.Error("allEffectsDetail did not survive the Go boundary — the UI cannot " +
			"show where any number came from")
	}

	// Same stats, same counts: the structured form must line up with the display
	// form index for index, because the frontend pairs them positionally after
	// filtering the flat list by stat.
	byStat := map[string][]EffectDetail{}
	for _, d := range result.AllEffectsDetail {
		byStat[d.Stat] = append(byStat[d.Stat], d)
	}
	for stat, display := range result.AllEffects {
		list, _ := display.([]interface{})
		detail := byStat[stat]
		if len(detail) != len(list) {
			t.Errorf("%s: %d display strings but %d structured entries",
				stat, len(list), len(detail))
		}
		for _, d := range detail {
			if d.SourceName == "" {
				t.Errorf("%s: a structured effect has no source name — this is what "+
					"renders as \"Location unavailable\"", stat)
				break
			}
		}
	}
}

func TestRunHistoryRecordsEffectsFromARealResult(t *testing.T) {
	// runOutcomeFrom used to re-marshal ResultPayload and fish for fields by
	// name, which found nothing once they had been dropped on the way in.
	// Re-serialising a value cannot recover what was discarded.
	app := newTestApp(t)
	if err := app.extractSolver(); err != nil {
		t.Skipf("no bundled solver: %v", err)
	}
	if _, err := app.SaveGearset(samplePayload(), ResultPayload{Success: true}); err != nil {
		t.Fatal(err)
	}

	if _, err := app.RecalculateGearset(RecalculationRequestFrom(samplePayload())); err != nil {
		t.Fatalf("RecalculateGearset: %v", err)
	}

	buildUUID := app.BuildIDForCurrentConfig("Round Trip")
	runs, err := app.ListRuns(buildUUID)
	if err != nil || len(runs) == 0 {
		t.Fatalf("no run recorded: %v", err)
	}
	var effects int
	if err := app.appDB.QueryRow("SELECT count(*) FROM run_effect WHERE run_uuid = ?",
		runs[0].UUID).Scan(&effects); err != nil {
		t.Fatal(err)
	}
	if effects == 0 {
		t.Error("the run recorded no effects; runOutcomeFrom is not seeing the result's detail")
	}
	t.Logf("recorded %d effect rows from a real recalculation", effects)
}
