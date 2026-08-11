package appdb

import (
	"database/sql"
	"fmt"
)

// migrations are applied in order to bring an app.db up to SchemaVersion.
//
// Forward-only and additive. app.db is the file the user cannot regenerate, so
// a migration that drops or rewrites data needs a far better reason than tidiness
// — and none of these do either.
//
// The index of a migration is the version it produces: migrations[0] takes a
// schema-1 file to schema 2.
var migrations = []struct {
	to  int
	sql string
}{
	{to: 2, sql: runHistoryDDL},
}

// runHistoryDDL adds run history — 0.5.1 Phase 6, schema doc §5.2.
//
// Two deliberate departures from the schema document, both found by checking it
// against real data rather than by reading it:
//
//  1. `run_active_set` is keyed on (run_uuid, set_uuid, **piece_count**), not
//     (run_uuid, set_uuid). A set genuinely activates SEVERAL tiers at once —
//     measured on a real gearset, "Zarigan's Arcane Enlightenment" is active at
//     2, 3 AND 4 pieces simultaneously — so the documented key would have
//     accepted the first tier and rejected the other two. The dedup the
//     document was reaching for (a set with three separate 2-piece rows in the
//     catalog is ONE active tier) is exactly what including piece_count gives.
//
//  2. `run_effect` is keyed on (run_uuid, position) and stores the source NAME
//     alongside an optional uuid. The documented key included `source_uuid`,
//     which in a WITHOUT ROWID table is implicitly NOT NULL — so an effect whose
//     source does not resolve to a catalog row could not be stored at all, and
//     those are precisely the ones worth keeping a record of.
const runHistoryDDL = `
CREATE TABLE run (
    uuid           TEXT PRIMARY KEY,
    build_uuid     TEXT NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    mode           TEXT NOT NULL CHECK (mode IN ('optimize','recalculate','alternatives')),
    ran_at         TEXT NOT NULL,
    app_version    TEXT NOT NULL,
    -- Which catalog produced these numbers. The reason a stale result is
    -- explainable after a catalog update instead of merely puzzling.
    catalog_commit TEXT,
    seconds        REAL,
    succeeded      INTEGER NOT NULL,
    error_message  TEXT
) WITHOUT ROWID;
CREATE INDEX run_build_idx ON run(build_uuid, ran_at DESC);

CREATE TABLE run_stat (
    run_uuid     TEXT NOT NULL REFERENCES run(uuid) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    value        REAL NOT NULL,
    -- 1 for a stat the user asked for (realizedStats), 0 for one the gear
    -- happens to grant (otherStats). Conflating them is what made a priority
    -- that matched nothing indistinguishable from one the gear did not provide.
    is_priority  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_uuid, display_name)
) WITHOUT ROWID;

CREATE TABLE run_effect (
    run_uuid    TEXT    NOT NULL REFERENCES run(uuid) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    stat_name   TEXT    NOT NULL,
    bonus_type  TEXT    NOT NULL,
    value       REAL    NOT NULL,
    source_name TEXT    NOT NULL,
    source_kind TEXT,
    PRIMARY KEY (run_uuid, position)
) WITHOUT ROWID;

CREATE TABLE run_active_set (
    run_uuid    TEXT    NOT NULL REFERENCES run(uuid) ON DELETE CASCADE,
    set_name    TEXT    NOT NULL,
    piece_count INTEGER NOT NULL,
    PRIMARY KEY (run_uuid, set_name, piece_count)
) WITHOUT ROWID;

CREATE TABLE run_warning (
    run_uuid TEXT    NOT NULL REFERENCES run(uuid) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    kind     TEXT,
    slot     TEXT,
    message  TEXT    NOT NULL,
    PRIMARY KEY (run_uuid, position)
) WITHOUT ROWID;
`

// applyMigrations moves an existing app.db forward to SchemaVersion.
//
// Each step runs in its own transaction with its version stamp, so an
// interrupted upgrade leaves the file at a version that is actually true rather
// than half-way between two.
func applyMigrations(db *sql.DB, from int) error {
	for _, m := range migrations {
		if m.to <= from {
			continue
		}
		tx, err := db.Begin()
		if err != nil {
			return fmt.Errorf("starting migration to schema %d: %w", m.to, err)
		}
		if _, err := tx.Exec(m.sql); err != nil {
			tx.Rollback() //nolint:errcheck
			return fmt.Errorf("migrating app.db to schema %d: %w", m.to, err)
		}
		if _, err := tx.Exec("UPDATE app_meta SET schema_version = ? WHERE id = 1", m.to); err != nil {
			tx.Rollback() //nolint:errcheck
			return fmt.Errorf("stamping schema %d: %w", m.to, err)
		}
		if err := tx.Commit(); err != nil {
			return fmt.Errorf("committing migration to schema %d: %w", m.to, err)
		}
	}
	return nil
}
