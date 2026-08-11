package appdb

import (
	"database/sql"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const testAppVersion = "0.5.1-test"

// fakeCatalog resolves a handful of names, so an import can be tested without
// a 58 MB catalog.db. Everything not listed is an orphan — which is the case
// most of these tests are about.
type fakeCatalog struct {
	items     map[string]string
	augments  map[string]string
	filigrees map[string]string
}

func newFakeCatalog() *fakeCatalog {
	return &fakeCatalog{
		items: map[string]string{
			"legendary lamordian bowler": "item-helm",
			"legendary downcast vest":    "item-armor",
		},
		augments:  map[string]string{"topaz of transmuted power\x1fyellow": "aug-topaz"},
		filigrees: map[string]string{"lunar magic: +9 force spell power": "fil-lunar"},
	}
}

func (f *fakeCatalog) ItemUUID(name string) (string, bool) {
	v, ok := f.items[normalizeName(name)]
	return v, ok
}

func (f *fakeCatalog) AugmentUUID(name, colour string) (string, bool) {
	v, ok := f.augments[augmentKey(name, colour)]
	return v, ok
}

func (f *fakeCatalog) FiligreeUUID(name string) (string, bool) {
	v, ok := f.filigrees[normalizeName(name)]
	return v, ok
}

func openTestDB(t *testing.T) (*sql.DB, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "app.db")
	db, err := Open(path, testAppVersion)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return db, path
}

func writeGearset(t *testing.T, dir, name string, content map[string]interface{}) string {
	t.Helper()
	path := filepath.Join(dir, name)
	raw, err := json.MarshalIndent(content, "", "  ")
	if err != nil {
		t.Fatalf("marshaling fixture: %v", err)
	}
	if err := os.WriteFile(path, raw, 0644); err != nil {
		t.Fatalf("writing fixture: %v", err)
	}
	return path
}

func sampleGearset() map[string]interface{} {
	return map[string]interface{}{
		"version":      "1.2",
		"app_version":  "0.4.4",
		"gearset_name": "Testy",
		"saved_at":     "2026-08-01T00:00:00Z",
		"config": map[string]interface{}{
			"gearset_name":   "Testy",
			"build_type":     "Caster",
			"max_level":      34,
			"weapon_style":   "Dual Caster",
			"excluded_packs": []interface{}{"Some Pack"},
			"stat_priorities": []interface{}{
				map[string]interface{}{"stat": "Force Spell Power", "tier": 1},
				map[string]interface{}{"stat": "Intelligence", "tier": 2, "cap": 40},
			},
			"caster_spellpowers": []interface{}{"Force"},
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
		},
		"result": map[string]interface{}{"success": true},
	}
}

func count(t *testing.T, db *sql.DB, query string, args ...interface{}) int {
	t.Helper()
	var n int
	if err := db.QueryRow(query, args...).Scan(&n); err != nil {
		t.Fatalf("counting (%s): %v", query, err)
	}
	return n
}

// --- schema and lifecycle -------------------------------------------------

func TestOpenCreatesAndStampsTheSchema(t *testing.T) {
	db, path := openTestDB(t)

	if _, err := os.Stat(path); err != nil {
		t.Fatalf("app.db was not created: %v", err)
	}
	version, err := SchemaVersionOf(db)
	if err != nil {
		t.Fatalf("SchemaVersionOf: %v", err)
	}
	if version != SchemaVersion {
		t.Errorf("schema version = %d, want %d", version, SchemaVersion)
	}
}

func TestReopeningKeepsTheData(t *testing.T) {
	// The whole reason app.db exists. A file that forgets on restart is a
	// cache, and this one is explicitly not that.
	dir := t.TempDir()
	path := filepath.Join(dir, "app.db")
	fixture := writeGearset(t, dir, "a.ddogearset", sampleGearset())

	db, err := Open(path, testAppVersion)
	if err != nil {
		t.Fatalf("first Open: %v", err)
	}
	outcome := ImportFile(db, newFakeCatalog(), fixture, testAppVersion)
	if outcome.Status != StatusImported {
		t.Fatalf("import: %s %s", outcome.Status, outcome.Error)
	}
	db.Close()

	reopened, err := Open(path, testAppVersion)
	if err != nil {
		t.Fatalf("second Open: %v", err)
	}
	defer reopened.Close()

	if n := count(t, reopened, "SELECT count(*) FROM build"); n != 1 {
		t.Errorf("after restart: %d builds, want 1", n)
	}
	if n := count(t, reopened, "SELECT count(*) FROM gearset_slot"); n != 2 {
		t.Errorf("after restart: %d slots, want 2", n)
	}
}

func TestOpenRefusesANewerSchema(t *testing.T) {
	// Silently writing to a file a newer build created is how data gets lost:
	// this build would not know about columns it never learned to fill.
	db, path := openTestDB(t)
	if _, err := db.Exec("UPDATE app_meta SET schema_version = ? WHERE id = 1", SchemaVersion+1); err != nil {
		t.Fatalf("bumping version: %v", err)
	}
	db.Close()

	reopened, err := Open(path, testAppVersion)
	if err == nil {
		reopened.Close()
		t.Fatal("Open accepted a database from a newer build")
	}
	if !strings.Contains(err.Error(), "newer version") {
		t.Errorf("unhelpful error for a newer schema: %v", err)
	}
}

func TestForeignKeysCascadeOnBuildDelete(t *testing.T) {
	// Every child table declares ON DELETE CASCADE, which only does anything if
	// foreign_keys is actually ON for the connection — a pragma that is off by
	// default in SQLite and easy to lose in a DSN edit.
	dir := t.TempDir()
	db, _ := openTestDB(t)
	fixture := writeGearset(t, dir, "a.ddogearset", sampleGearset())
	outcome := ImportFile(db, newFakeCatalog(), fixture, testAppVersion)
	if outcome.Status != StatusImported {
		t.Fatalf("import: %s %s", outcome.Status, outcome.Error)
	}
	if n := count(t, db, "SELECT count(*) FROM gearset_slot"); n == 0 {
		t.Fatal("nothing to cascade")
	}

	if _, err := db.Exec("DELETE FROM build WHERE uuid = ?", outcome.BuildUUID); err != nil {
		t.Fatalf("deleting build: %v", err)
	}
	for _, table := range []string{"gearset_slot", "gearset_augment", "gearset_filigree",
		"build_priority", "build_excluded_pack", "build_caster_option", "orphan_reference"} {
		if n := count(t, db, "SELECT count(*) FROM "+table); n != 0 {
			t.Errorf("%s kept %d row(s) after its build was deleted", table, n)
		}
	}
}

// --- import ----------------------------------------------------------------

func TestImportWritesTheWholeBuild(t *testing.T) {
	dir := t.TempDir()
	db, _ := openTestDB(t)
	fixture := writeGearset(t, dir, "Testy.ddogearset", sampleGearset())

	outcome := ImportFile(db, newFakeCatalog(), fixture, testAppVersion)
	if outcome.Status != StatusImported {
		t.Fatalf("status = %s (%s)", outcome.Status, outcome.Error)
	}
	if outcome.BuildName != "Testy" {
		t.Errorf("build name = %q, want Testy", outcome.BuildName)
	}
	if len(outcome.Orphans) != 0 {
		t.Errorf("unexpected orphans: %+v", outcome.Orphans)
	}

	var name, buildType, importedFrom string
	var maxLevel int
	err := db.QueryRow(
		"SELECT name, build_type, max_level, imported_from FROM build WHERE uuid = ?",
		outcome.BuildUUID).Scan(&name, &buildType, &maxLevel, &importedFrom)
	if err != nil {
		t.Fatalf("reading build: %v", err)
	}
	if name != "Testy" || buildType != "Caster" || maxLevel != 34 {
		t.Errorf("build row = %q/%q/%d", name, buildType, maxLevel)
	}
	if importedFrom != fixture {
		t.Errorf("imported_from = %q, want %q", importedFrom, fixture)
	}

	for table, want := range map[string]int{
		"gearset_slot": 2, "gearset_augment": 1, "gearset_filigree": 1,
		"build_priority": 2, "build_excluded_pack": 1, "build_caster_option": 1,
	} {
		if n := count(t, db, "SELECT count(*) FROM "+table); n != want {
			t.Errorf("%s: %d rows, want %d", table, n, want)
		}
	}

	// Everything imports as `equipped`. A suggestion is the live output of a
	// solve; a years-old saved file never claimed to hold one.
	if n := count(t, db, "SELECT count(*) FROM gearset_slot WHERE origin = 'suggested'"); n != 0 {
		t.Errorf("%d slot(s) imported as suggested", n)
	}

	var cap sql.NullFloat64
	if err := db.QueryRow(
		"SELECT cap FROM build_priority WHERE raw_text = 'Intelligence'").Scan(&cap); err != nil {
		t.Fatalf("reading priority cap: %v", err)
	}
	if !cap.Valid || cap.Float64 != 40 {
		t.Errorf("priority cap = %+v, want 40", cap)
	}
}

func TestImportingTheSameFileTwiceProducesOneBuild(t *testing.T) {
	dir := t.TempDir()
	db, _ := openTestDB(t)
	fixture := writeGearset(t, dir, "Testy.ddogearset", sampleGearset())

	first := ImportFile(db, newFakeCatalog(), fixture, testAppVersion)
	second := ImportFile(db, newFakeCatalog(), fixture, testAppVersion)

	if first.Status != StatusImported {
		t.Fatalf("first import: %s (%s)", first.Status, first.Error)
	}
	if second.Status != StatusAlreadyImported {
		t.Errorf("second import: %s, want %s", second.Status, StatusAlreadyImported)
	}
	if second.BuildUUID != first.BuildUUID {
		t.Errorf("same file resolved to two identities: %s vs %s", first.BuildUUID, second.BuildUUID)
	}
	if n := count(t, db, "SELECT count(*) FROM build"); n != 1 {
		t.Errorf("%d builds after importing one file twice", n)
	}
	if n := count(t, db, "SELECT count(*) FROM gearset_slot"); n != 2 {
		t.Errorf("%d slots after importing one file twice, want 2", n)
	}
}

func TestReimportDoesNotOverwriteAnEditedBuild(t *testing.T) {
	// Re-import is not a sync. The build may have been edited in the app since
	// it was imported, and the file cannot know that — so the file loses.
	dir := t.TempDir()
	db, _ := openTestDB(t)
	fixture := writeGearset(t, dir, "Testy.ddogearset", sampleGearset())

	outcome := ImportFile(db, newFakeCatalog(), fixture, testAppVersion)
	if _, err := db.Exec("UPDATE build SET name = 'Renamed By The User' WHERE uuid = ?",
		outcome.BuildUUID); err != nil {
		t.Fatalf("simulating an edit: %v", err)
	}
	if _, err := db.Exec("DELETE FROM gearset_slot WHERE build_uuid = ? AND slot = 'Armor'",
		outcome.BuildUUID); err != nil {
		t.Fatalf("simulating an edit: %v", err)
	}

	if again := ImportFile(db, newFakeCatalog(), fixture, testAppVersion); again.Status != StatusAlreadyImported {
		t.Fatalf("re-import status = %s", again.Status)
	}

	var name string
	if err := db.QueryRow("SELECT name FROM build WHERE uuid = ?", outcome.BuildUUID).Scan(&name); err != nil {
		t.Fatalf("reading build: %v", err)
	}
	if name != "Renamed By The User" {
		t.Errorf("re-import clobbered the user's rename: name = %q", name)
	}
	if n := count(t, db, "SELECT count(*) FROM gearset_slot WHERE build_uuid = ?", outcome.BuildUUID); n != 1 {
		t.Errorf("re-import resurrected deleted rows: %d slots, want 1", n)
	}
}

func TestAnEditedFileImportsAsItsOwnBuild(t *testing.T) {
	dir := t.TempDir()
	db, _ := openTestDB(t)

	first := ImportFile(db, newFakeCatalog(), writeGearset(t, dir, "a.ddogearset", sampleGearset()), testAppVersion)

	edited := sampleGearset()
	edited["gearset_name"] = "Testy Mk II"
	second := ImportFile(db, newFakeCatalog(), writeGearset(t, dir, "b.ddogearset", edited), testAppVersion)

	if second.Status != StatusImported {
		t.Fatalf("edited file: %s (%s)", second.Status, second.Error)
	}
	if second.BuildUUID == first.BuildUUID {
		t.Error("different content resolved to the same build identity")
	}
	if n := count(t, db, "SELECT count(*) FROM build"); n != 2 {
		t.Errorf("%d builds, want 2", n)
	}
}

func TestAMissingItemIsReportedNotFatal(t *testing.T) {
	// The gate: a .ddogearset naming an item absent from the catalog imports,
	// reports the orphan, and does not take the other thirteen slots with it.
	dir := t.TempDir()
	db, _ := openTestDB(t)

	content := sampleGearset()
	cfg := content["config"].(map[string]interface{})
	cfg["pre_equipped"].(map[string]interface{})["Boots"] = "Boots That No Longer Exist"
	cfg["pre_filled_filigrees"].(map[string]interface{})["artifact"] =
		[]interface{}{"A Filigree From A Deleted Pack"}
	fixture := writeGearset(t, dir, "orphans.ddogearset", content)

	outcome := ImportFile(db, newFakeCatalog(), fixture, testAppVersion)
	if outcome.Status != StatusImported {
		t.Fatalf("status = %s (%s)", outcome.Status, outcome.Error)
	}
	if len(outcome.Orphans) != 2 {
		t.Fatalf("orphans = %+v, want 2", outcome.Orphans)
	}
	if n := count(t, db, "SELECT count(*) FROM gearset_slot"); n != 2 {
		t.Errorf("the resolvable slots did not survive: %d, want 2", n)
	}

	var kind, name string
	if err := db.QueryRow(
		"SELECT kind, name FROM orphan_reference WHERE kind = 'item'").Scan(&kind, &name); err != nil {
		t.Fatalf("reading orphan_reference: %v", err)
	}
	if name != "Boots That No Longer Exist" {
		t.Errorf("orphan name = %q", name)
	}
}

func TestGearsetIsReadFromTheResultWhenConfigHasNone(t *testing.T) {
	// Real files exist in both shapes: pinned into config.pre_equipped, or
	// present only in result.gearSet when a solve was saved without writing the
	// picks back. Same precedence scripts/capture_oracle.py established.
	dir := t.TempDir()
	db, _ := openTestDB(t)

	content := sampleGearset()
	cfg := content["config"].(map[string]interface{})
	delete(cfg, "pre_equipped")
	delete(cfg, "pre_filled_filigrees")
	content["result"] = map[string]interface{}{
		"success":   true,
		"gearSet":   map[string]interface{}{"Helmet": "Legendary Lamordian Bowler"},
		"filigrees": map[string]interface{}{"weapon": []interface{}{"Lunar Magic: +9 Force Spell Power"}},
	}

	outcome := ImportFile(db, newFakeCatalog(), writeGearset(t, dir, "r.ddogearset", content), testAppVersion)
	if outcome.Status != StatusImported {
		t.Fatalf("status = %s (%s)", outcome.Status, outcome.Error)
	}
	if n := count(t, db, "SELECT count(*) FROM gearset_slot WHERE slot = 'Helmet'"); n != 1 {
		t.Error("gearset was not recovered from result.gearSet")
	}
	if n := count(t, db, "SELECT count(*) FROM gearset_filigree WHERE bucket = 'weapon'"); n != 1 {
		t.Error("filigrees were not recovered from result.filigrees")
	}
}

func TestEmptyFiligreeEntriesAreDropped(t *testing.T) {
	// A known corruption class in real saves (capture_oracle.py's
	// `empty-filigree-entry`). An empty string is not a filigree, and storing
	// one would put a row in gearset_filigree that resolves to nothing.
	dir := t.TempDir()
	db, _ := openTestDB(t)

	content := sampleGearset()
	cfg := content["config"].(map[string]interface{})
	cfg["pre_filled_filigrees"].(map[string]interface{})["weapon"] =
		[]interface{}{"", "Lunar Magic: +9 Force Spell Power", ""}
	outcome := ImportFile(db, newFakeCatalog(), writeGearset(t, dir, "e.ddogearset", content), testAppVersion)

	if outcome.Status != StatusImported {
		t.Fatalf("status = %s (%s)", outcome.Status, outcome.Error)
	}
	if n := count(t, db, "SELECT count(*) FROM gearset_filigree"); n != 1 {
		t.Errorf("%d filigree rows, want 1", n)
	}
	var position int
	if err := db.QueryRow("SELECT position FROM gearset_filigree").Scan(&position); err != nil {
		t.Fatalf("reading position: %v", err)
	}
	if position != 0 {
		t.Errorf("position = %d, want 0 — positions are dense, not the source index", position)
	}
}

func TestAnUnreadableFileFailsWithoutWritingAnything(t *testing.T) {
	dir := t.TempDir()
	db, _ := openTestDB(t)
	path := filepath.Join(dir, "broken.ddogearset")
	if err := os.WriteFile(path, []byte("{not json"), 0644); err != nil {
		t.Fatal(err)
	}

	outcome := ImportFile(db, newFakeCatalog(), path, testAppVersion)
	if outcome.Status != StatusFailed {
		t.Errorf("status = %s, want %s", outcome.Status, StatusFailed)
	}
	if outcome.Error == "" {
		t.Error("a failed import must say why")
	}
	if n := count(t, db, "SELECT count(*) FROM build"); n != 0 {
		t.Errorf("a failed import left %d build(s) behind", n)
	}
}

func TestLegacyPrioritiesWithoutTiersSurviveTheImport(t *testing.T) {
	// "Shape B" files carry `value` instead of `tier`. The value→tier migration
	// lives in solver.py and is deliberately NOT reimplemented here; the import
	// only has to avoid violating the CHECK constraint and losing the priority.
	dir := t.TempDir()
	db, _ := openTestDB(t)

	content := sampleGearset()
	cfg := content["config"].(map[string]interface{})
	cfg["stat_priorities"] = []interface{}{
		map[string]interface{}{"stat": "Force Spell Power", "value": 100},
	}
	outcome := ImportFile(db, newFakeCatalog(), writeGearset(t, dir, "legacy.ddogearset", content), testAppVersion)

	if outcome.Status != StatusImported {
		t.Fatalf("status = %s (%s)", outcome.Status, outcome.Error)
	}
	var text string
	var tier int
	if err := db.QueryRow("SELECT raw_text, tier FROM build_priority").Scan(&text, &tier); err != nil {
		t.Fatalf("reading priority: %v", err)
	}
	if text != "Force Spell Power" {
		t.Errorf("priority text = %q", text)
	}
	if tier < 1 || tier > 5 {
		t.Errorf("tier = %d, outside the CHECK constraint", tier)
	}
}

func TestBuildUUIDIsStableForIdenticalContent(t *testing.T) {
	raw := []byte(`{"gearset_name":"x"}`)
	if BuildUUIDForFile(raw) != BuildUUIDForFile(raw) {
		t.Error("the same bytes produced two identities")
	}
	if BuildUUIDForFile(raw) == BuildUUIDForFile([]byte(`{"gearset_name":"y"}`)) {
		t.Error("different bytes produced one identity")
	}
}
