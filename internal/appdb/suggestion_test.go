package appdb

import (
	"database/sql"
	"testing"
)

// sampleResult is a solver ResultPayload marshaled to a map — the shape
// SaveSuggestion receives. Deliberately proposes DIFFERENT gear from
// sampleConfig()'s equipped set, so a test can tell the two nodes apart.
func sampleResult() map[string]interface{} {
	return map[string]interface{}{
		"success": true,
		"gearSet": map[string]interface{}{
			"Helmet": "Legendary Downcast Vest", // deliberately not the equipped helm
		},
		"filigrees": map[string]interface{}{
			"weapon":   []interface{}{"Lunar Magic: +9 Force Spell Power"},
			"artifact": []interface{}{},
		},
		"slots": map[string]interface{}{
			"Helmet": map[string]interface{}{
				"augments": []interface{}{
					map[string]interface{}{"name": "Topaz of Transmuted Power", "color": "Yellow"},
				},
			},
		},
	}
}

func savedBuild(t *testing.T) (*sql.DB, string) {
	t.Helper()
	db, _ := openTestDB(t)
	saved, err := SaveBuild(db, newFakeCatalog(), sampleConfig(), testAppVersion)
	if err != nil {
		t.Fatalf("SaveBuild: %v", err)
	}
	return db, saved.UUID
}

func TestASuggestionNeverTouchesEquipped(t *testing.T) {
	// The gate, and the reason the two nodes are separate ROWS: a solve cannot
	// reach the user's own gearset.
	db, buildUUID := savedBuild(t)

	if _, err := SaveSuggestion(db, newFakeCatalog(), buildUUID, sampleResult()); err != nil {
		t.Fatalf("SaveSuggestion: %v", err)
	}

	equipped := count(t, db, "SELECT count(*) FROM gearset_slot WHERE build_uuid = ? AND origin = 'equipped'", buildUUID)
	suggested := count(t, db, "SELECT count(*) FROM gearset_slot WHERE build_uuid = ? AND origin = 'suggested'", buildUUID)
	if equipped != 2 {
		t.Errorf("equipped has %d slots after a solve, want the original 2", equipped)
	}
	if suggested != 1 {
		t.Errorf("suggested has %d slots, want 1", suggested)
	}

	// The equipped rows must be byte-identical, not merely the same count.
	var stillHelm string
	if err := db.QueryRow(`SELECT item_name FROM gearset_slot
		WHERE build_uuid = ? AND origin = 'equipped' AND slot = 'Helmet'`,
		buildUUID).Scan(&stillHelm); err != nil {
		t.Fatalf("reading the equipped helm: %v", err)
	}
	if stillHelm != "Legendary Lamordian Bowler" {
		t.Errorf("the solve overwrote the equipped helm: %q", stillHelm)
	}
}

func TestOptimizeThenSaveCannotWriteAnEmptyGearset(t *testing.T) {
	// The named regression. It was possible because a solve's output and the
	// user's gearset shared one place, so an empty one could overwrite a full
	// one. Here a solve writes only `suggested`, and saving reads only
	// `equipped` — there is no ordering that loses the gearset.
	db, buildUUID := savedBuild(t)

	// A solve that proposes nothing at all.
	empty := map[string]interface{}{"success": true, "gearSet": map[string]interface{}{}}
	if _, err := SaveSuggestion(db, newFakeCatalog(), buildUUID, empty); err != nil {
		t.Fatalf("SaveSuggestion: %v", err)
	}

	loaded, err := LoadBuild(db, buildUUID)
	if err != nil {
		t.Fatalf("LoadBuild: %v", err)
	}
	equipped := loaded.Config["pre_equipped"].(map[string]string)
	if len(equipped) != 2 {
		t.Errorf("the gearset is now %v — an empty solve emptied it", equipped)
	}
}

func TestAcceptSuggestionPromotesEveryPart(t *testing.T) {
	db, buildUUID := savedBuild(t)
	if _, err := SaveSuggestion(db, newFakeCatalog(), buildUUID, sampleResult()); err != nil {
		t.Fatalf("SaveSuggestion: %v", err)
	}

	moved, err := AcceptSuggestion(db, buildUUID)
	if err != nil {
		t.Fatalf("AcceptSuggestion: %v", err)
	}
	if moved != 1 {
		t.Errorf("accepted %d slots, want 1", moved)
	}

	loaded, err := LoadBuild(db, buildUUID)
	if err != nil {
		t.Fatalf("LoadBuild: %v", err)
	}
	equipped := loaded.Config["pre_equipped"].(map[string]string)
	if len(equipped) != 1 || equipped["Helmet"] != "Legendary Downcast Vest" {
		t.Errorf("equipped after accepting = %v", equipped)
	}
	// The previous equipped rows are REPLACED, not merged: accepting a
	// 1-slot suggestion onto a 2-slot gearset leaves one slot, or the user
	// silently keeps gear the solver did not propose.
	if n := count(t, db, "SELECT count(*) FROM gearset_slot WHERE build_uuid = ? AND origin = 'equipped'", buildUUID); n != 1 {
		t.Errorf("%d equipped slots after accepting, want 1", n)
	}

	augments := loaded.Config["pre_filled_augments"].(map[string]map[string]string)
	if augments["Helmet"]["Yellow"] != "Topaz of Transmuted Power" {
		t.Errorf("augments did not come across: %v", augments)
	}
	filigrees := loaded.Config["pre_filled_filigrees"].(map[string][]string)
	if len(filigrees["weapon"]) != 1 {
		t.Errorf("filigrees did not come across: %v", filigrees)
	}
}

func TestAcceptingLeavesTheSuggestionInPlace(t *testing.T) {
	// Accepting is not consuming: someone who accepts and then wants to compare
	// should still be able to see what was proposed.
	db, buildUUID := savedBuild(t)
	if _, err := SaveSuggestion(db, newFakeCatalog(), buildUUID, sampleResult()); err != nil {
		t.Fatalf("SaveSuggestion: %v", err)
	}
	if _, err := AcceptSuggestion(db, buildUUID); err != nil {
		t.Fatalf("AcceptSuggestion: %v", err)
	}
	if n := count(t, db, "SELECT count(*) FROM gearset_slot WHERE build_uuid = ? AND origin = 'suggested'", buildUUID); n != 1 {
		t.Errorf("%d suggested slots after accepting, want the suggestion kept", n)
	}
}

func TestAcceptingNothingIsRefused(t *testing.T) {
	// Accepting an empty suggestion would be a one-click way to erase a
	// gearset — exactly the failure this model exists to prevent.
	db, buildUUID := savedBuild(t)

	if _, err := AcceptSuggestion(db, buildUUID); err == nil {
		t.Fatal("accepting with no suggestion reported success")
	}
	if n := count(t, db, "SELECT count(*) FROM gearset_slot WHERE build_uuid = ? AND origin = 'equipped'", buildUUID); n != 2 {
		t.Errorf("the refused accept still cleared equipped: %d slots left", n)
	}
}

func TestASecondSolveReplacesTheSuggestion(t *testing.T) {
	db, buildUUID := savedBuild(t)
	if _, err := SaveSuggestion(db, newFakeCatalog(), buildUUID, sampleResult()); err != nil {
		t.Fatalf("first suggestion: %v", err)
	}

	second := sampleResult()
	second["gearSet"] = map[string]interface{}{
		"Helmet": "Legendary Lamordian Bowler",
		"Armor":  "Legendary Downcast Vest",
	}
	if _, err := SaveSuggestion(db, newFakeCatalog(), buildUUID, second); err != nil {
		t.Fatalf("second suggestion: %v", err)
	}

	if n := count(t, db, "SELECT count(*) FROM gearset_slot WHERE build_uuid = ? AND origin = 'suggested'", buildUUID); n != 2 {
		t.Errorf("%d suggested slots, want the second solve's 2 (not merged with the first)", n)
	}
	if n := count(t, db, "SELECT count(*) FROM gearset_slot WHERE build_uuid = ? AND origin = 'equipped'", buildUUID); n != 2 {
		t.Errorf("equipped changed across two solves: %d slots", n)
	}
}

func TestSuggestionForAnUnknownBuildIsRefused(t *testing.T) {
	db, _ := openTestDB(t)
	if _, err := SaveSuggestion(db, newFakeCatalog(), "not-a-build", sampleResult()); err == nil {
		t.Error("stored a suggestion against a build that does not exist")
	}
}

func TestHasSuggestionReportsBothStates(t *testing.T) {
	db, buildUUID := savedBuild(t)

	has, err := HasSuggestion(db, buildUUID)
	if err != nil || has {
		t.Errorf("HasSuggestion on a fresh build = %v, %v", has, err)
	}
	if _, err := SaveSuggestion(db, newFakeCatalog(), buildUUID, sampleResult()); err != nil {
		t.Fatal(err)
	}
	has, err = HasSuggestion(db, buildUUID)
	if err != nil || !has {
		t.Errorf("HasSuggestion after a solve = %v, %v", has, err)
	}
}

func TestSavingABuildClearsItsStaleSuggestion(t *testing.T) {
	// SaveBuild replaces the whole build, and ON DELETE CASCADE takes the
	// suggestion with it. That is correct rather than incidental: a suggestion
	// is an answer to the configuration that produced it, and a re-saved
	// configuration is a different question.
	db, buildUUID := savedBuild(t)
	if _, err := SaveSuggestion(db, newFakeCatalog(), buildUUID, sampleResult()); err != nil {
		t.Fatal(err)
	}

	if _, err := SaveBuild(db, newFakeCatalog(), sampleConfig(), testAppVersion); err != nil {
		t.Fatalf("re-saving: %v", err)
	}
	has, err := HasSuggestion(db, buildUUID)
	if err != nil {
		t.Fatal(err)
	}
	if has {
		t.Error("a stale suggestion survived a re-save of its build")
	}
}
