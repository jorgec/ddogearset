package appdb

import "testing"

func sampleOutcome() *RunOutcome {
	return &RunOutcome{
		RealizedStats: map[string]float64{"Charisma": 8.0, "force spellpower": 324.0},
		OtherStats:    map[string]float64{"Dodge": 3.0},
		// A set active at THREE tiers at once, plus the same tier listed twice
		// the way a catalog with duplicate rows would produce it.
		ActiveSets: []string{
			"Zarigan's Arcane Enlightenment (2-piece)",
			"Zarigan's Arcane Enlightenment (3-piece)",
			"Zarigan's Arcane Enlightenment (4-piece)",
			"Legendary Inevitable Balance (2-piece)",
			"Legendary Inevitable Balance (2-piece)",
		},
		EffectDetail: map[string][]map[string]interface{}{
			"Charisma": {
				{"value": 4.0, "bonusType": "Stacking", "sourceName": "Solar Gem", "sourceKind": "augment"},
				{"value": 4.0, "bonusType": "Stacking", "sourceName": "Lunar Gem", "sourceKind": "augment"},
			},
		},
		Warnings: []map[string]interface{}{
			{"kind": "duplicate-filigree", "slot": "weapon", "message": "slotted twice"},
		},
	}
}

func succeededRun(buildUUID string) RunRecord {
	return RunRecord{BuildUUID: buildUUID, Mode: "recalculate", AppVersion: testAppVersion,
		CatalogCommit: "f91af4e6", Seconds: 0.7, Succeeded: true}
}

func TestMigrationBringsASchema1FileForward(t *testing.T) {
	// The first migration this project has ever run. A file created by the
	// schema-1 build must arrive at exactly where a fresh one does — otherwise
	// every existing user's app.db diverges from every new one.
	db, path := openTestDB(t)
	version, err := SchemaVersionOf(db)
	if err != nil || version != SchemaVersion {
		t.Fatalf("fresh database is at schema %d (%v), want %d", version, err, SchemaVersion)
	}
	// Simulate an app.db left by the schema-1 build: the run tables did not
	// exist, and the stamp said 1.
	for _, table := range []string{"run_warning", "run_active_set", "run_effect", "run_stat", "run"} {
		if _, err := db.Exec("DROP TABLE " + table); err != nil {
			t.Fatalf("dropping %s: %v", table, err)
		}
	}
	if _, err := db.Exec("UPDATE app_meta SET schema_version = 1 WHERE id = 1"); err != nil {
		t.Fatal(err)
	}
	db.Close()

	migrated, err := Open(path, testAppVersion)
	if err != nil {
		t.Fatalf("migrating a schema-1 file: %v", err)
	}
	defer migrated.Close()

	if v, _ := SchemaVersionOf(migrated); v != SchemaVersion {
		t.Errorf("after migration: schema %d, want %d", v, SchemaVersion)
	}
	if n := count(t, migrated, "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='run'"); n != 1 {
		t.Error("the migration did not create the run table")
	}
}

func TestMigrationPreservesExistingData(t *testing.T) {
	// The one thing a migration on a precious file must never do.
	db, path := openTestDB(t)
	saved, err := SaveBuild(db, newFakeCatalog(), sampleConfig(), testAppVersion)
	if err != nil {
		t.Fatal(err)
	}
	for _, table := range []string{"run_warning", "run_active_set", "run_effect", "run_stat", "run"} {
		db.Exec("DROP TABLE " + table) //nolint:errcheck
	}
	db.Exec("UPDATE app_meta SET schema_version = 1 WHERE id = 1") //nolint:errcheck
	db.Close()

	migrated, err := Open(path, testAppVersion)
	if err != nil {
		t.Fatalf("migrating: %v", err)
	}
	defer migrated.Close()

	loaded, err := LoadBuild(migrated, saved.UUID)
	if err != nil {
		t.Fatalf("the build did not survive the migration: %v", err)
	}
	if len(loaded.Config["pre_equipped"].(map[string]string)) != 2 {
		t.Errorf("the gearset did not survive: %v", loaded.Config["pre_equipped"])
	}
}

func TestRecordRunWritesEverything(t *testing.T) {
	db, buildUUID := savedBuild(t)

	runUUID, err := RecordRun(db, succeededRun(buildUUID), sampleOutcome())
	if err != nil {
		t.Fatalf("RecordRun: %v", err)
	}

	realized, other, err := RunStats(db, runUUID)
	if err != nil {
		t.Fatal(err)
	}
	if realized["Charisma"] != 8.0 || realized["force spellpower"] != 324.0 {
		t.Errorf("realized = %v", realized)
	}
	if other["Dodge"] != 3.0 {
		t.Errorf("other = %v", other)
	}
	if n := count(t, db, "SELECT count(*) FROM run_effect WHERE run_uuid = ?", runUUID); n != 2 {
		t.Errorf("%d effect rows, want 2", n)
	}
	if n := count(t, db, "SELECT count(*) FROM run_warning WHERE run_uuid = ?", runUUID); n != 1 {
		t.Errorf("%d warning rows, want 1", n)
	}
}

func TestActiveSetsDeduplicateWithoutLosingTiers(t *testing.T) {
	// The gate, and where the specified schema was wrong. Its documented key,
	// (run_uuid, set_uuid), would have accepted Zarigan's 2-piece and REJECTED
	// its 3- and 4-piece tiers, which are simultaneously active on a real
	// gearset. Including piece_count keeps all three while still collapsing the
	// duplicate 2-piece row the catalog genuinely contains.
	db, buildUUID := savedBuild(t)
	runUUID, err := RecordRun(db, succeededRun(buildUUID), sampleOutcome())
	if err != nil {
		t.Fatal(err)
	}

	rows, err := db.Query(`SELECT set_name, piece_count FROM run_active_set
		WHERE run_uuid = ? ORDER BY set_name, piece_count`, runUUID)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var got []string
	for rows.Next() {
		var name string
		var pieces int
		if err := rows.Scan(&name, &pieces); err != nil {
			t.Fatal(err)
		}
		got = append(got, name)
		_ = pieces
	}
	if len(got) != 4 {
		t.Errorf("%d active-set rows, want 4 (3 Zarigan tiers + 1 deduplicated Inevitable Balance): %v",
			len(got), got)
	}
	if n := count(t, db, `SELECT count(*) FROM run_active_set
		WHERE run_uuid = ? AND set_name = "Zarigan's Arcane Enlightenment"`, runUUID); n != 3 {
		t.Errorf("%d Zarigan tiers survived, want 3", n)
	}
}

func TestAFailedRunIsRecordedWithNoStats(t *testing.T) {
	// The gate. A failure is the part people omit because it feels like nothing
	// to store — and it is exactly what you want six weeks later.
	db, buildUUID := savedBuild(t)

	failed := succeededRun(buildUUID)
	failed.Succeeded = false
	failed.ErrorMessage = "no feasible solution"
	runUUID, err := RecordRun(db, failed, nil)
	if err != nil {
		t.Fatalf("RecordRun: %v", err)
	}

	var succeeded int
	var message string
	if err := db.QueryRow("SELECT succeeded, error_message FROM run WHERE uuid = ?",
		runUUID).Scan(&succeeded, &message); err != nil {
		t.Fatal(err)
	}
	if succeeded != 0 || message != "no feasible solution" {
		t.Errorf("run row = succeeded %d, %q", succeeded, message)
	}
	for _, table := range []string{"run_stat", "run_effect", "run_active_set", "run_warning"} {
		if n := count(t, db, "SELECT count(*) FROM "+table+" WHERE run_uuid = ?", runUUID); n != 0 {
			t.Errorf("a failed run wrote %d row(s) to %s", n, table)
		}
	}
}

func TestARunThatCannotBeWrittenLeavesNothingBehind(t *testing.T) {
	// All or nothing. A header committed without its stats is a run claiming to
	// have succeeded while reporting nothing.
	db, buildUUID := savedBuild(t)
	if _, err := db.Exec(`CREATE TRIGGER fail_stat BEFORE INSERT ON run_stat
		BEGIN SELECT RAISE(ABORT, 'simulated failure'); END`); err != nil {
		t.Fatal(err)
	}
	if _, err := RecordRun(db, succeededRun(buildUUID), sampleOutcome()); err == nil {
		t.Fatal("RecordRun reported success while its stats could not be written")
	}
	if n := count(t, db, "SELECT count(*) FROM run"); n != 0 {
		t.Errorf("%d run row(s) survived a failed write", n)
	}
}

func TestHistorySurvivesARestartAndCascadesWithItsBuild(t *testing.T) {
	db, path := openTestDB(t)
	saved, err := SaveBuild(db, newFakeCatalog(), sampleConfig(), testAppVersion)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := RecordRun(db, succeededRun(saved.UUID), sampleOutcome()); err != nil {
		t.Fatal(err)
	}
	db.Close()

	reopened, err := Open(path, testAppVersion)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()

	runs, err := ListRuns(reopened, saved.UUID, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(runs) != 1 || !runs[0].Succeeded || runs[0].CatalogCommit != "f91af4e6" {
		t.Fatalf("history after restart: %+v", runs)
	}

	if err := DeleteBuild(reopened, saved.UUID); err != nil {
		t.Fatal(err)
	}
	for _, table := range []string{"run", "run_stat", "run_effect", "run_active_set", "run_warning"} {
		if n := count(t, reopened, "SELECT count(*) FROM "+table); n != 0 {
			t.Errorf("%s kept %d row(s) after its build was deleted", table, n)
		}
	}
}

func TestParseActiveSetHandlesNamesContainingParentheses(t *testing.T) {
	for _, tc := range []struct {
		label  string
		name   string
		pieces int
	}{
		{"Lunar Magic (3-piece)", "Lunar Magic", 3},
		{"Legendary Soul of the Red Dragon (2 Piece) (2-piece)", "Legendary Soul of the Red Dragon (2 Piece)", 2},
		{"No Tier", "No Tier", 0},
	} {
		name, pieces := parseActiveSet(tc.label)
		if name != tc.name || pieces != tc.pieces {
			t.Errorf("parseActiveSet(%q) = %q/%d, want %q/%d", tc.label, name, pieces, tc.name, tc.pieces)
		}
	}
}
