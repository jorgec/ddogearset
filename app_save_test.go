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

	// No solver has been extracted, so runSolver fails before doing anything.
	failing := samplePayload()
	failing.BuildType = "Caster"
	if _, err := app.RunOptimization(failing); err == nil {
		t.Fatal("expected the optimize to fail with no solver available")
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
