package appdb

import (
	"database/sql"
	"fmt"
)

// The two nodes of a build's gearset (schema doc §5.2/§5.4).
//
//	equipped   what the user HAS. Edited in the gearset editor, saved, exported,
//	           and — from Phase 4 — recalculated.
//	suggested  what the solver most recently PROPOSED. Overwritten by every
//	           solve, and only ever becomes equipped when the user accepts it.
//
// They are different ROWS, not different fields, and that is what makes
// "Optimize → Save wrote an empty gearset" unreproducible. That bug was
// possible because a solve's output and the user's own gearset lived in one
// place, so whichever wrote last won; here a solve cannot reach an `equipped`
// row at all.
const (
	OriginEquipped  = "equipped"
	OriginSuggested = "suggested"
)

// SaveSuggestion records what a solve proposed, replacing any previous
// suggestion for that build.
//
// `result` is a ResultPayload marshaled to a generic map — the same shape a
// .ddogearset's `result` object has, which is why it can go through the exact
// writer an import uses (insertGearset) rather than a second one.
//
// Touches ONLY origin='suggested'. A solve never reaches the user's own
// gearset, which is the whole point of the split and what makes the gate's
// "a failed optimize leaves equipped untouched" true by construction rather
// than by care.
func SaveSuggestion(db *sql.DB, catalog Catalog, buildUUID string,
	result map[string]interface{}) ([]Orphan, error) {

	var exists int
	if err := db.QueryRow("SELECT count(*) FROM build WHERE uuid = ?", buildUUID).Scan(&exists); err != nil {
		return nil, fmt.Errorf("looking up build: %w", err)
	}
	if exists == 0 {
		return nil, fmt.Errorf("no build with id %s to attach a suggestion to", buildUUID)
	}

	tx, err := db.Begin()
	if err != nil {
		return nil, fmt.Errorf("starting transaction: %w", err)
	}
	defer tx.Rollback() //nolint:errcheck // no-op after a successful Commit

	if err := deleteOrigin(tx, buildUUID, OriginSuggested); err != nil {
		return nil, err
	}

	// Config deliberately empty: a suggestion is read from the RESULT and
	// nowhere else. Passing the config too would let insertGearset's
	// config-first precedence quietly store the user's existing gear as the
	// solver's proposal.
	saved := savedGearset{Result: result}
	orphans, err := insertGearset(tx, catalog, buildUUID, OriginSuggested, saved)
	if err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("committing suggestion: %w", err)
	}
	return orphans, nil
}

// AcceptSuggestion promotes the stored suggestion to equipped and reports how
// many slots moved.
//
// Schema §5.4's statement, in one transaction: clear equipped, copy every
// suggested row across. The suggestion is left in place — accepting is not
// consuming, and a user who accepts and then wants to compare should still be
// able to see what was proposed.
//
// Returns an error when there is nothing to accept, rather than silently
// clearing `equipped`. Accepting an empty suggestion would be a one-click way
// to erase a gearset, which is precisely the failure this model exists to make
// impossible.
func AcceptSuggestion(db *sql.DB, buildUUID string) (int, error) {
	var suggested int
	err := db.QueryRow(
		"SELECT count(*) FROM gearset_slot WHERE build_uuid = ? AND origin = ?",
		buildUUID, OriginSuggested).Scan(&suggested)
	if err != nil {
		return 0, fmt.Errorf("counting the suggestion: %w", err)
	}
	if suggested == 0 {
		return 0, fmt.Errorf("there is no suggestion to accept for this build")
	}

	tx, err := db.Begin()
	if err != nil {
		return 0, fmt.Errorf("starting transaction: %w", err)
	}
	defer tx.Rollback() //nolint:errcheck // no-op after a successful Commit

	if err := deleteOrigin(tx, buildUUID, OriginEquipped); err != nil {
		return 0, err
	}
	for _, copyStmt := range []string{
		`INSERT INTO gearset_slot (build_uuid, origin, slot, item_uuid, item_name)
		 SELECT build_uuid, 'equipped', slot, item_uuid, item_name
		   FROM gearset_slot WHERE build_uuid = ? AND origin = 'suggested'`,
		`INSERT INTO gearset_augment (build_uuid, origin, slot, colour, augment_uuid, augment_name)
		 SELECT build_uuid, 'equipped', slot, colour, augment_uuid, augment_name
		   FROM gearset_augment WHERE build_uuid = ? AND origin = 'suggested'`,
		`INSERT INTO gearset_filigree (build_uuid, origin, bucket, position, filigree_uuid, filigree_name)
		 SELECT build_uuid, 'equipped', bucket, position, filigree_uuid, filigree_name
		   FROM gearset_filigree WHERE build_uuid = ? AND origin = 'suggested'`,
	} {
		if _, err := tx.Exec(copyStmt, buildUUID); err != nil {
			return 0, fmt.Errorf("accepting the suggestion: %w", err)
		}
	}

	if _, err := tx.Exec("UPDATE build SET updated_at = ? WHERE uuid = ?",
		nowRFC3339(), buildUUID); err != nil {
		return 0, fmt.Errorf("stamping updated_at: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return 0, fmt.Errorf("committing the accepted suggestion: %w", err)
	}
	return suggested, nil
}

// HasSuggestion reports whether a build has a solver proposal waiting.
func HasSuggestion(db *sql.DB, buildUUID string) (bool, error) {
	var n int
	err := db.QueryRow(
		"SELECT count(*) FROM gearset_slot WHERE build_uuid = ? AND origin = ?",
		buildUUID, OriginSuggested).Scan(&n)
	return n > 0, err
}

// LoadGearset reads one node of a build's gearset back in the shape the app
// configures solves with (pre_equipped / pre_filled_augments /
// pre_filled_filigrees).
func LoadGearset(db *sql.DB, buildUUID, origin string) (map[string]interface{}, error) {
	out := map[string]interface{}{}
	if err := loadGearsetOrigin(db, buildUUID, origin, out); err != nil {
		return nil, err
	}
	return out, nil
}

func deleteOrigin(tx *sql.Tx, buildUUID, origin string) error {
	for _, table := range []string{"gearset_slot", "gearset_augment", "gearset_filigree"} {
		if _, err := tx.Exec(
			"DELETE FROM "+table+" WHERE build_uuid = ? AND origin = ?",
			buildUUID, origin); err != nil {
			return fmt.Errorf("clearing %s rows in %s: %w", origin, table, err)
		}
	}
	return nil
}
