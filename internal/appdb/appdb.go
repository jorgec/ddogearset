// Package appdb owns app.db — the user's builds, gearsets and run history.
//
// The distinction from internal/catalog is the whole point (schema doc §4):
//
//	catalog.db  disposable. Rebuilt by the ETL, shipped with the app, opened
//	            read-only and immutable, thrown away on every update.
//	app.db      PRECIOUS. Created once on the user's machine, written to for
//	            years, and never regenerable from anything.
//
// Every rule in here follows from that second line. Migrations are forward-only
// and versioned from the first release. Nothing deletes or recreates the file to
// recover from a problem. Imports are additive and refuse to overwrite.
//
// app.db holds no foreign key into catalog.db — SQLite cannot express one
// across files — so catalog references are stored as UUID plus a denormalized
// name (schema §5.3). The UUID is the join key; the name is a tombstone, so an
// item that leaves the game data reports as *"Legendary Bracers of Wind is no
// longer in the catalog"* instead of rendering as an empty slot.
//
// Go owns this file, not Python. The frontend talks to Go, Go writes app.db,
// and Python receives payloads exactly as it does today — one writer, no
// cross-process locking, and Python stays stateless with respect to user data.
package appdb

import (
	"database/sql"
	"fmt"
	"time"

	_ "modernc.org/sqlite"
)

func nowRFC3339() string { return time.Now().UTC().Format(time.RFC3339) }

// SchemaVersion is the version this build writes and understands. It starts at
// 1 and only ever moves forward.
//
// Recorded from the very first release on purpose: a file in the wild without a
// version cannot be migrated, only guessed at, and this one is expected to
// outlive many app versions. Same reasoning as catalog_meta's versioning
// (schema §5.1.1), applied to the database that actually matters.
const SchemaVersion = 1

// DDL mirrors docs/0.5.0/01_CATALOG_AND_APP_SCHEMA.md §5.2. Where this and the
// document disagree, the document is the spec and this is the bug.
//
// Tables in this first release cover builds and gearsets only. The run_* tables
// are Phase 6 — see the plan — and are deliberately absent rather than created
// empty: unlike catalog.db's item_upgrade, nothing here benefits from a table
// that exists before anything writes to it, and a migration adds them cleanly.
const DDL = `
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE app_meta (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version INTEGER NOT NULL,
    created_at     TEXT    NOT NULL,
    created_by     TEXT    NOT NULL
);

CREATE TABLE build (
    uuid        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    app_version TEXT NOT NULL,

    -- Provenance for an imported .ddogearset. NULL for a build created in the
    -- app. Kept so a Phase 6 backfill can find the file a build came from and
    -- turn its saved stats into a run row — the file is never deleted, so that
    -- information is postponed, not lost.
    imported_from TEXT,

    max_level                     INTEGER NOT NULL DEFAULT 34,
    build_type                    TEXT    NOT NULL,
    weapon_style                  TEXT,
    offhand_style                 TEXT,
    weapon_damage_type            TEXT,
    swashbuckling                 INTEGER NOT NULL DEFAULT 0,
    runearm_use                   INTEGER NOT NULL DEFAULT 0,
    armor_restriction             TEXT,
    reserved_minor_artifact_slot  TEXT,
    minor_artifact_filigree_slots INTEGER NOT NULL DEFAULT 4,
    is_dino_artifact              INTEGER NOT NULL DEFAULT 0,
    exclude_gem_of_many_facets    INTEGER NOT NULL DEFAULT 0,
    raid_item_limit               INTEGER NOT NULL DEFAULT -1,
    caster_restrict_weapon_families INTEGER NOT NULL DEFAULT 1,
    max_search_time               INTEGER
) WITHOUT ROWID;

-- Ordered: intra-tier rank is array position.
CREATE TABLE build_priority (
    build_uuid TEXT    NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    position   INTEGER NOT NULL,
    raw_text   TEXT    NOT NULL,
    tier       INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    cap        REAL,
    PRIMARY KEY (build_uuid, position)
) WITHOUT ROWID;

CREATE TABLE build_excluded_pack (
    build_uuid TEXT NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    pack       TEXT NOT NULL,
    PRIMARY KEY (build_uuid, pack)
) WITHOUT ROWID;

CREATE TABLE build_caster_option (
    build_uuid TEXT NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('spellpower','school')),
    value      TEXT NOT NULL,
    PRIMARY KEY (build_uuid, kind, value)
) WITHOUT ROWID;

-- Owned inventory belongs to the PLAYER, not to one build.
CREATE TABLE owned_item (
    item_uuid   TEXT PRIMARY KEY,
    item_name   TEXT NOT NULL,
    imported_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE gearset_slot (
    build_uuid TEXT NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    origin     TEXT NOT NULL CHECK (origin IN ('equipped','suggested')),
    slot       TEXT NOT NULL,
    item_uuid  TEXT NOT NULL,
    item_name  TEXT NOT NULL,
    PRIMARY KEY (build_uuid, origin, slot)
) WITHOUT ROWID;

CREATE TABLE gearset_augment (
    build_uuid   TEXT NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    origin       TEXT NOT NULL CHECK (origin IN ('equipped','suggested')),
    slot         TEXT NOT NULL,
    colour       TEXT NOT NULL,
    augment_uuid TEXT NOT NULL,
    augment_name TEXT NOT NULL,
    PRIMARY KEY (build_uuid, origin, slot, colour)
) WITHOUT ROWID;

CREATE TABLE gearset_filigree (
    build_uuid    TEXT    NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    origin        TEXT    NOT NULL CHECK (origin IN ('equipped','suggested')),
    bucket        TEXT    NOT NULL CHECK (bucket IN ('weapon','artifact')),
    position      INTEGER NOT NULL,
    filigree_uuid TEXT    NOT NULL,
    filigree_name TEXT    NOT NULL,
    PRIMARY KEY (build_uuid, origin, bucket, position)
) WITHOUT ROWID;

-- Names a build referenced that no catalog row answers to. Written at import,
-- read to tell the user WHICH item vanished rather than showing a gap. Not a
-- foreign key to anything by definition — the referent is what is missing.
CREATE TABLE orphan_reference (
    build_uuid TEXT NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('item','augment','filigree')),
    slot       TEXT,
    name       TEXT NOT NULL,
    detail     TEXT,
    PRIMARY KEY (build_uuid, kind, slot, name)
) WITHOUT ROWID;
`

// Open opens (and creates, if absent) app.db at `path`, applying the schema on
// a fresh file and verifying it on an existing one.
//
// Read-WRITE and non-immutable, unlike catalog.Open — this is the file the app
// exists to accumulate. WAL matters here for a reason it does not there: a
// reader (the UI listing builds) must not block a writer (a solve finishing).
// appVersion is stamped into app_meta.created_by, so a file can say which
// release first created it. Passed in rather than read from a global because
// internal/ cannot import main.
func Open(path, appVersion string) (*sql.DB, error) {
	dsn := fmt.Sprintf("file:%s?_pragma=foreign_keys(1)&_pragma=busy_timeout(5000)", path)
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("opening app database %s: %w", path, err)
	}
	if err := db.Ping(); err != nil {
		db.Close()
		return nil, fmt.Errorf("app database %s did not open: %w", path, err)
	}
	if err := migrate(db, appVersion); err != nil {
		db.Close()
		return nil, err
	}
	return db, nil
}

// migrate brings an app.db to SchemaVersion, or fails loudly.
//
// Forward-only, and it REFUSES a file from a newer build rather than trying to
// read it. Downgrading a user's data is the one failure mode this file cannot
// recover from — a newer app may have written columns this build would silently
// drop on the next write.
func migrate(db *sql.DB, appVersion string) error {
	var count int
	err := db.QueryRow(
		"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='app_meta'").Scan(&count)
	if err != nil {
		return fmt.Errorf("inspecting app database: %w", err)
	}

	if count == 0 {
		if _, err := db.Exec(DDL); err != nil {
			return fmt.Errorf("creating app database schema: %w", err)
		}
		_, err := db.Exec(
			"INSERT INTO app_meta (id, schema_version, created_at, created_by) VALUES (1, ?, ?, ?)",
			SchemaVersion, nowRFC3339(), appVersion)
		if err != nil {
			return fmt.Errorf("stamping app database schema version: %w", err)
		}
		return nil
	}

	var found int
	if err := db.QueryRow("SELECT schema_version FROM app_meta WHERE id = 1").Scan(&found); err != nil {
		return fmt.Errorf("reading app database schema version: %w", err)
	}
	switch {
	case found == SchemaVersion:
		return nil
	case found > SchemaVersion:
		return fmt.Errorf(
			"app.db was written by a newer version of this app (schema %d, this "+
				"build understands %d). Update the app rather than letting this "+
				"one write to it — an older build can silently drop data a newer "+
				"one stored", found, SchemaVersion)
	default:
		// No migrations exist yet because no released schema precedes 1. The
		// first one lands here, and this must never become a silent no-op:
		// leaving an old file unmigrated and writing to it anyway is how the
		// data gets corrupted.
		return fmt.Errorf(
			"app.db is at schema %d and this build needs %d, but no migration "+
				"is implemented for that step", found, SchemaVersion)
	}
}

// SchemaVersionOf reports the schema version recorded in an open app.db.
func SchemaVersionOf(db *sql.DB) (int, error) {
	var v int
	err := db.QueryRow("SELECT schema_version FROM app_meta WHERE id = 1").Scan(&v)
	return v, err
}
