// Package catalog reads catalog.db — the ETL's output — replacing
// internal/services/parser.go's XML walk. See
// docs/0.5.0/00_ETL_START_HERE.md Phase 5 and
// docs/0.5.0/01_CATALOG_AND_APP_SCHEMA.md §5.1.3.
//
// Every reader below queries `raw_xml` and unmarshals it into the SAME
// models.XMLItem / XMLAugment / XMLFiligree / XMLSetBonus structs the old
// parser produced — raw_xml is the source node's own serialization, so this
// is not a reimplementation of XML parsing, it is the same parsing pointed
// at a different byte source. Candidacy columns (is_raid, adventure_pack,
// min_level, slots) are read alongside to avoid re-deriving them from the
// unmarshaled struct where the catalog already computed them once, correctly,
// at build time.
package catalog

import (
	"database/sql"
	"encoding/xml"
	"fmt"

	_ "modernc.org/sqlite"

	"goGearset/internal/models"
)

// Open connects read-only and immutable — nothing writes this file while the
// app runs, so SQLite can skip locking entirely (START_HERE §5.2.3).
func Open(path string) (*sql.DB, error) {
	dsn := fmt.Sprintf("file:%s?mode=ro&immutable=1", path)
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("opening catalog %s: %w", path, err)
	}
	if err := db.Ping(); err != nil {
		db.Close()
		return nil, fmt.Errorf("catalog %s did not open: %w", path, err)
	}
	return db, nil
}

// Meta mirrors catalog_meta — see docs/0.5.0/01_CATALOG_AND_APP_SCHEMA.md §5.1.1.
type Meta struct {
	SchemaVersion        int
	CatalogVersion       int
	BuiltAt              string
	DDOBuilderCommit     string
	ETLVersion           string
	SourceFileCount      int
	MinAppVersion        string
	ContentHash          string
	IdentityRegistryHash string
	DDOBuilderVersion    string
}

func ReadMeta(db *sql.DB) (Meta, error) {
	var m Meta
	row := db.QueryRow(`SELECT schema_version, catalog_version, built_at,
		ddobuilder_commit, etl_version, source_file_count, min_app_version,
		content_hash, identity_registry_hash FROM catalog_meta WHERE id = 1`)
	err := row.Scan(&m.SchemaVersion, &m.CatalogVersion, &m.BuiltAt,
		&m.DDOBuilderCommit, &m.ETLVersion, &m.SourceFileCount,
		&m.MinAppVersion, &m.ContentHash, &m.IdentityRegistryHash)
	if err != nil {
		return Meta{}, fmt.Errorf("reading catalog_meta: %w", err)
	}
	// ddobuilder_version was added after the initial schema; old catalogs lack it.
	_ = db.QueryRow(`SELECT ddobuilder_version FROM catalog_meta WHERE id = 1`).Scan(&m.DDOBuilderVersion)
	return m, nil
}

// LoadItems returns every item in the catalog, unmarshaled from raw_xml, with
// IsRaid/PackID overlaid from the precomputed catalog column — see the
// package doc. Candidacy fields the picker bindings need (min_level, slots)
// are NOT applied here; this returns the full corpus, exactly as
// services.ParseItems always did, and callers filter as before.
func LoadItems(db *sql.DB) ([]models.XMLItem, []string, error) {
	rows, err := db.Query(`SELECT name, is_raid, raw_xml FROM item`)
	if err != nil {
		return nil, nil, fmt.Errorf("querying items: %w", err)
	}
	defer rows.Close()

	var items []models.XMLItem
	var skipped []string
	for rows.Next() {
		var name string
		var isRaid bool
		var rawXML string
		if err := rows.Scan(&name, &isRaid, &rawXML); err != nil {
			return nil, nil, fmt.Errorf("scanning item row: %w", err)
		}
		var item models.XMLItem
		if err := xml.Unmarshal([]byte(rawXML), &item); err != nil {
			skipped = append(skipped, name)
			continue
		}
		// is_raid comes from the catalog's own resolution (verified to match
		// Python's raid-chain walk — see docs/0.5.0/00_ETL_START_HERE.md
		// Phase 4). Go no longer walks the chain itself; see enrichment.go.
		item.IsRaid = isRaid
		items = append(items, item)
	}
	if err := rows.Err(); err != nil {
		return nil, nil, fmt.Errorf("reading items: %w", err)
	}
	return items, skipped, nil
}

func LoadAugments(db *sql.DB) ([]models.XMLAugment, []string, error) {
	rows, err := db.Query(`SELECT name, raw_xml FROM augment`)
	if err != nil {
		return nil, nil, fmt.Errorf("querying augments: %w", err)
	}
	defer rows.Close()

	var augments []models.XMLAugment
	var skipped []string
	for rows.Next() {
		var name, rawXML string
		if err := rows.Scan(&name, &rawXML); err != nil {
			return nil, nil, fmt.Errorf("scanning augment row: %w", err)
		}
		var aug models.XMLAugment
		if err := xml.Unmarshal([]byte(rawXML), &aug); err != nil {
			skipped = append(skipped, name)
			continue
		}
		augments = append(augments, aug)
	}
	if err := rows.Err(); err != nil {
		return nil, nil, fmt.Errorf("reading augments: %w", err)
	}
	return augments, skipped, nil
}

// LoadFiligrees returns every filigree, with SetName populated from its
// FIRST set membership (filigree_set.position = 0) — matching the same
// first-wins convention used throughout this phase (and the solver's own
// findtext-based behaviour). A filigree's full membership (dual-set) is
// captured correctly in the catalog's filigree_set table; exposing more than
// the first through this struct is a frontend filter-UX change (SetName
// drives GearsetEditor/FiligreeEditor's set dropdown), out of scope here —
// see docs/0.5.0/00_ETL_START_HERE.md Phase 5 notes.
func LoadFiligrees(db *sql.DB) ([]models.XMLFiligree, []string, error) {
	rows, err := db.Query(`
		SELECT f.name, f.raw_xml,
		       (SELECT gs.name FROM filigree_set fs
		          JOIN gear_set gs ON gs.uuid = fs.set_uuid
		         WHERE fs.filigree_uuid = f.uuid AND fs.position = 0) AS first_set
		FROM filigree f`)
	if err != nil {
		return nil, nil, fmt.Errorf("querying filigrees: %w", err)
	}
	defer rows.Close()

	var filigrees []models.XMLFiligree
	var skipped []string
	for rows.Next() {
		var name, rawXML string
		var firstSet sql.NullString
		if err := rows.Scan(&name, &rawXML, &firstSet); err != nil {
			return nil, nil, fmt.Errorf("scanning filigree row: %w", err)
		}
		var fil models.XMLFiligree
		if err := xml.Unmarshal([]byte(rawXML), &fil); err != nil {
			skipped = append(skipped, name)
			continue
		}
		fil.SetName = firstSet.String
		filigrees = append(filigrees, fil)
	}
	if err := rows.Err(); err != nil {
		return nil, nil, fmt.Errorf("reading filigrees: %w", err)
	}
	return filigrees, skipped, nil
}

// LoadSetBonuses returns every gear_set that has its own raw_xml (a set
// referenced only as membership, with no <SetBonus> definition anywhere in
// the corpus, has nothing to unmarshal and is correctly absent — see
// gear_set.raw_xml's NULL case in the schema doc). Item and filigree set
// tiers are unified in one table already (§5.1's set_tier + origin_hint), so
// this single query replaces both ParseSetBonuses and
// ParseFiligreeSetBonuses.
func LoadSetBonuses(db *sql.DB) ([]models.XMLSetBonus, []string, error) {
	rows, err := db.Query(`SELECT name, raw_xml FROM gear_set WHERE raw_xml IS NOT NULL`)
	if err != nil {
		return nil, nil, fmt.Errorf("querying set bonuses: %w", err)
	}
	defer rows.Close()

	var sets []models.XMLSetBonus
	var skipped []string
	for rows.Next() {
		var name, rawXML string
		if err := rows.Scan(&name, &rawXML); err != nil {
			return nil, nil, fmt.Errorf("scanning gear_set row: %w", err)
		}
		var sb models.XMLSetBonus
		if err := xml.Unmarshal([]byte(rawXML), &sb); err != nil {
			skipped = append(skipped, name)
			continue
		}
		sets = append(sets, sb)
	}
	if err := rows.Err(); err != nil {
		return nil, nil, fmt.Errorf("reading set bonuses: %w", err)
	}
	return sets, skipped, nil
}
