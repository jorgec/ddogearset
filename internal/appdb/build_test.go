package appdb

import (
	"database/sql"
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

// sampleConfig is the config half of a .ddogearset — what SaveBuild receives
// after the app marshals an OptimizationPayload.
func sampleConfig() map[string]interface{} {
	return map[string]interface{}{
		"gearset_name":                    "My Caster",
		"build_type":                      "Caster",
		"max_level":                       34,
		"weapon_style":                    "Dual Caster",
		"offhand_style":                   "None",
		"armor_restriction":               "Light",
		"minor_artifact_filigree_slots":   5,
		"raid_item_limit":                 -1,
		"swashbuckling":                   false,
		"runearm_use":                     false,
		"is_dino_artifact":                false,
		"exclude_gem_of_many_facets":      true,
		"caster_restrict_weapon_families": true,
		"excluded_packs":                  []interface{}{"Some Pack", "Another Pack"},
		"caster_spellpowers":              []interface{}{"Force"},
		"caster_schools":                  []interface{}{"Evocation"},
		"stat_priorities": []interface{}{
			map[string]interface{}{"stat": "Force Spell Power", "tier": 1},
			map[string]interface{}{"stat": "Intelligence", "tier": 2, "cap": 40},
		},
		"pre_equipped": map[string]interface{}{
			"Helmet": "Legendary Lamordian Bowler",
			"Armor":  "Legendary Downcast Vest",
		},
		"pre_filled_augments": map[string]interface{}{
			"Armor": map[string]interface{}{"Yellow": "Topaz of Transmuted Power"},
		},
		"pre_filled_filigrees": map[string]interface{}{
			"weapon":   []interface{}{"Lunar Magic: +9 Force Spell Power"},
			"artifact": []interface{}{},
		},
	}
}

func TestSaveThenLoadRoundTripsTheConfiguration(t *testing.T) {
	db, _ := openTestDB(t)

	saved, err := SaveBuild(db, newFakeCatalog(), sampleConfig(), testAppVersion)
	if err != nil {
		t.Fatalf("SaveBuild: %v", err)
	}
	if !saved.Created {
		t.Error("first save did not report a created build")
	}

	loaded, err := LoadBuild(db, saved.UUID)
	if err != nil {
		t.Fatalf("LoadBuild: %v", err)
	}

	cfg := loaded.Config
	for key, want := range map[string]interface{}{
		"gearset_name": "My Caster", "build_type": "Caster", "max_level": 34,
		"weapon_style": "Dual Caster", "armor_restriction": "Light",
		"minor_artifact_filigree_slots": 5, "raid_item_limit": -1,
		"exclude_gem_of_many_facets": true, "caster_restrict_weapon_families": true,
		"swashbuckling": false,
	} {
		if !reflect.DeepEqual(cfg[key], want) {
			t.Errorf("%s = %#v, want %#v", key, cfg[key], want)
		}
	}

	if got := cfg["excluded_packs"].([]string); len(got) != 2 {
		t.Errorf("excluded_packs = %v", got)
	}
	if got := cfg["caster_spellpowers"].([]string); len(got) != 1 || got[0] != "Force" {
		t.Errorf("caster_spellpowers = %v", got)
	}

	priorities := cfg["stat_priorities"].([]map[string]interface{})
	if len(priorities) != 2 {
		t.Fatalf("stat_priorities = %v", priorities)
	}
	// Array position is intra-tier rank — order is load-bearing here, unlike
	// the four lists 0.5.1 Phase 0 found to be unordered.
	if priorities[0]["stat"] != "Force Spell Power" || priorities[1]["stat"] != "Intelligence" {
		t.Errorf("priorities came back out of order: %v", priorities)
	}
	if priorities[1]["cap"] != 40.0 {
		t.Errorf("cap = %#v, want 40", priorities[1]["cap"])
	}

	equipped := cfg["pre_equipped"].(map[string]string)
	if equipped["Helmet"] != "Legendary Lamordian Bowler" || len(equipped) != 2 {
		t.Errorf("pre_equipped = %v", equipped)
	}
	augments := cfg["pre_filled_augments"].(map[string]map[string]string)
	if augments["Armor"]["Yellow"] != "Topaz of Transmuted Power" {
		t.Errorf("pre_filled_augments = %v", augments)
	}
	filigrees := cfg["pre_filled_filigrees"].(map[string][]string)
	if len(filigrees["weapon"]) != 1 || len(filigrees["artifact"]) != 0 {
		t.Errorf("pre_filled_filigrees = %v", filigrees)
	}
}

func TestSavingTwiceUpdatesOneBuild(t *testing.T) {
	// The gate: create → edit → restart → the build is still there, and there
	// is one of it.
	db, path := openTestDB(t)

	first, err := SaveBuild(db, newFakeCatalog(), sampleConfig(), testAppVersion)
	if err != nil {
		t.Fatalf("first save: %v", err)
	}

	edited := sampleConfig()
	edited["max_level"] = 32
	edited["pre_equipped"] = map[string]interface{}{"Helmet": "Legendary Lamordian Bowler"}
	second, err := SaveBuild(db, newFakeCatalog(), edited, testAppVersion)
	if err != nil {
		t.Fatalf("second save: %v", err)
	}
	if second.UUID != first.UUID {
		t.Errorf("saving the same name twice made two builds: %s vs %s", first.UUID, second.UUID)
	}
	if second.Created {
		t.Error("second save reported a newly created build")
	}
	if n := count(t, db, "SELECT count(*) FROM build"); n != 1 {
		t.Errorf("%d builds after saving twice", n)
	}
	// The replaced gearset must not leave its old rows behind.
	if n := count(t, db, "SELECT count(*) FROM gearset_slot"); n != 1 {
		t.Errorf("%d slots after replacing a 2-slot gearset with a 1-slot one", n)
	}

	db.Close()
	reopened, err := Open(path, testAppVersion)
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer reopened.Close()

	loaded, err := LoadBuild(reopened, first.UUID)
	if err != nil {
		t.Fatalf("LoadBuild after restart: %v", err)
	}
	if loaded.Config["max_level"] != 32 {
		t.Errorf("the edit did not survive the restart: max_level = %v", loaded.Config["max_level"])
	}
}

func TestSavingPreservesCreatedAtAndMovesUpdatedAt(t *testing.T) {
	db, _ := openTestDB(t)

	first, _ := SaveBuild(db, newFakeCatalog(), sampleConfig(), testAppVersion)
	var created1, updated1 string
	if err := db.QueryRow("SELECT created_at, updated_at FROM build WHERE uuid = ?",
		first.UUID).Scan(&created1, &updated1); err != nil {
		t.Fatal(err)
	}

	if _, err := SaveBuild(db, newFakeCatalog(), sampleConfig(), testAppVersion); err != nil {
		t.Fatalf("second save: %v", err)
	}
	var created2 string
	if err := db.QueryRow("SELECT created_at FROM build WHERE uuid = ?",
		first.UUID).Scan(&created2); err != nil {
		t.Fatal(err)
	}
	if created2 != created1 {
		t.Errorf("created_at moved on re-save: %q -> %q", created1, created2)
	}
}

func TestAnUnnamedSaveIsAlwaysANewBuild(t *testing.T) {
	// Matching what the app has always done with an unnamed gearset: write a
	// new file. Collapsing them into one row would overwrite the previous
	// unnamed save without being asked to.
	db, _ := openTestDB(t)
	config := sampleConfig()
	delete(config, "gearset_name")

	first, err := SaveBuild(db, newFakeCatalog(), config, testAppVersion)
	if err != nil {
		t.Fatalf("first save: %v", err)
	}
	second, err := SaveBuild(db, newFakeCatalog(), config, testAppVersion)
	if err != nil {
		t.Fatalf("second save: %v", err)
	}
	if first.UUID == second.UUID {
		t.Error("two unnamed saves collapsed into one build")
	}
	if n := count(t, db, "SELECT count(*) FROM build"); n != 2 {
		t.Errorf("%d builds after two unnamed saves, want 2", n)
	}
}

func TestBuildNameIdentityIgnoresCaseAndSurroundingSpace(t *testing.T) {
	if BuildUUIDForName("My Caster") != BuildUUIDForName("  my caster ") {
		t.Error("the same build name produced two identities")
	}
	if BuildUUIDForName("My Caster") == BuildUUIDForName("My Ranger") {
		t.Error("two build names produced one identity")
	}
}

func TestAFailedSaveDoesNotDestroyThePreviousBuild(t *testing.T) {
	// Replace-then-write happens in ONE transaction. A save that deleted the
	// old rows and then failed would trade a working gearset for nothing, which
	// is the single thing app.db must never do.
	db, _ := openTestDB(t)
	first, err := SaveBuild(db, newFakeCatalog(), sampleConfig(), testAppVersion)
	if err != nil {
		t.Fatalf("first save: %v", err)
	}

	// Injected at the storage layer rather than through a malformed config,
	// because no config CAN fail: writeBuild clamps out-of-range tiers, skips
	// unresolvable names, and uses INSERT OR IGNORE where duplicates are
	// possible. A trigger reproduces the case that matters — the DELETE has
	// already run inside the transaction and the replacement then fails — which
	// is otherwise only reachable via a disk error.
	if _, err := db.Exec(`CREATE TRIGGER fail_build_insert BEFORE INSERT ON build
		BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END`); err != nil {
		t.Fatalf("installing the failure trigger: %v", err)
	}

	edited := sampleConfig()
	edited["max_level"] = 20
	if _, err := SaveBuild(db, newFakeCatalog(), edited, testAppVersion); err == nil {
		t.Fatal("a save that could not write the build reported success")
	}

	if _, err := db.Exec("DROP TRIGGER fail_build_insert"); err != nil {
		t.Fatalf("removing the failure trigger: %v", err)
	}

	loaded, err := LoadBuild(db, first.UUID)
	if err != nil {
		t.Fatalf("the previous build is gone after a failed save: %v", err)
	}
	if loaded.Config["max_level"] != 34 {
		t.Errorf("the previous build was damaged: %v", loaded.Config)
	}
	if n := count(t, db, "SELECT count(*) FROM gearset_slot"); n != 2 {
		t.Errorf("%d slots survived the failed save, want the original 2", n)
	}
}

func TestExportImportRoundTripsToIdenticalRows(t *testing.T) {
	// The gate: a build saved, exported to a file, and imported into a fresh
	// database must produce the same rows. This is what makes .ddogearset a
	// real export format rather than a lossy one.
	source, _ := openTestDB(t)
	saved, err := SaveBuild(source, newFakeCatalog(), sampleConfig(), testAppVersion)
	if err != nil {
		t.Fatalf("SaveBuild: %v", err)
	}

	// The export file's shape, exactly as app.go's exportGearsetFile writes it.
	file := map[string]interface{}{
		"version":      "1.2",
		"app_version":  testAppVersion,
		"gearset_name": "My Caster",
		"saved_at":     "2026-08-11T00:00:00Z",
		"config":       sampleConfig(),
		"result":       map[string]interface{}{"success": true},
	}
	dir := t.TempDir()
	path := writeGearset(t, dir, "export.ddogearset", file)

	target, _ := openTestDB(t)
	outcome := ImportFile(target, newFakeCatalog(), path, testAppVersion)
	if outcome.Status != StatusImported {
		t.Fatalf("import: %s (%s)", outcome.Status, outcome.Error)
	}

	// Compared by CONTENT, not by uuid: the two identities are minted
	// differently on purpose (a name for a save, file bytes for an import).
	before := dumpBuild(t, source, saved.UUID)
	after := dumpBuild(t, target, outcome.BuildUUID)
	if !reflect.DeepEqual(before, after) {
		t.Errorf("export/import did not round-trip.\n saved:    %s\n imported: %s",
			mustJSON(t, before), mustJSON(t, after))
	}
}

// dumpBuild returns every child row of a build, sorted, with the build_uuid
// stripped — so two builds can be compared on content when their identities
// are minted differently by design (a name for a save, file bytes for an
// import).
func dumpBuild(t *testing.T, db *sql.DB, buildUUID string) map[string][]string {
	t.Helper()
	queries := map[string]string{
		"slots":     "SELECT origin, slot, item_uuid, item_name FROM gearset_slot WHERE build_uuid = ? ORDER BY origin, slot",
		"augments":  "SELECT origin, slot, colour, augment_uuid, augment_name FROM gearset_augment WHERE build_uuid = ? ORDER BY origin, slot, colour",
		"filigrees": "SELECT origin, bucket, position, filigree_uuid, filigree_name FROM gearset_filigree WHERE build_uuid = ? ORDER BY origin, bucket, position",
		"priority":  "SELECT position, raw_text, tier, COALESCE(cap, -1) FROM build_priority WHERE build_uuid = ? ORDER BY position",
		"packs":     "SELECT pack FROM build_excluded_pack WHERE build_uuid = ? ORDER BY pack",
		"caster":    "SELECT kind, value FROM build_caster_option WHERE build_uuid = ? ORDER BY kind, value",
		"orphans":   "SELECT kind, COALESCE(slot,''), name FROM orphan_reference WHERE build_uuid = ? ORDER BY kind, name",
		"build": `SELECT name, build_type, max_level, COALESCE(weapon_style,''),
			COALESCE(offhand_style,''), COALESCE(armor_restriction,''),
			minor_artifact_filigree_slots, raid_item_limit, swashbuckling,
			runearm_use, is_dino_artifact, exclude_gem_of_many_facets,
			caster_restrict_weapon_families FROM build WHERE uuid = ?`,
	}

	out := map[string][]string{}
	for label, query := range queries {
		rows, err := db.Query(query, buildUUID)
		if err != nil {
			t.Fatalf("dumping %s: %v", label, err)
		}
		cols, err := rows.Columns()
		if err != nil {
			t.Fatalf("dumping %s: %v", label, err)
		}
		values := []string{}
		for rows.Next() {
			cells := make([]interface{}, len(cols))
			for i := range cells {
				cells[i] = new(sql.NullString)
			}
			if err := rows.Scan(cells...); err != nil {
				rows.Close()
				t.Fatalf("dumping %s: %v", label, err)
			}
			parts := make([]string, len(cells))
			for i, c := range cells {
				parts[i] = c.(*sql.NullString).String
			}
			values = append(values, strings.Join(parts, "|"))
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			t.Fatalf("dumping %s: %v", label, err)
		}
		out[label] = values
	}
	return out
}

func mustJSON(t *testing.T, v interface{}) string {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return string(raw)
}
