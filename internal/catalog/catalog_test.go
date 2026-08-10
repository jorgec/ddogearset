package catalog_test

import (
	"database/sql"
	"fmt"
	"path/filepath"
	"testing"

	_ "modernc.org/sqlite"

	"goGearset/internal/catalog"
)

// Minimal DDL: only the columns and tables the readers under test touch.
// Deliberately NOT the full etl/load.py schema — this is a fixture for
// exercising Go's read path and its fault tolerance, not a schema-parity
// test (that is scripts/parser_snapshot.py's verify-catalog job, run against
// a real ETL-built catalog).
const testDDL = `
CREATE TABLE item (uuid TEXT PRIMARY KEY, name TEXT NOT NULL, is_raid INTEGER NOT NULL DEFAULT 0, raw_xml TEXT NOT NULL);
CREATE TABLE augment (uuid TEXT PRIMARY KEY, name TEXT NOT NULL, raw_xml TEXT NOT NULL);
CREATE TABLE filigree (uuid TEXT PRIMARY KEY, name TEXT NOT NULL, raw_xml TEXT NOT NULL);
CREATE TABLE gear_set (uuid TEXT PRIMARY KEY, name TEXT NOT NULL, raw_xml TEXT);
CREATE TABLE filigree_set (filigree_uuid TEXT NOT NULL, set_uuid TEXT NOT NULL, position INTEGER NOT NULL);
`

// A real file, not :memory: — catalog.Open dials a `file:` DSN with
// mode=ro&immutable=1, so each test writes its fixture with a plain writable
// connection first, then reopens read-only through the real Open() to
// exercise the exact code path production uses.
func reopenReadOnly(t *testing.T, setup *sql.DB, path string) *sql.DB {
	t.Helper()
	setup.Close()
	db, err := catalog.Open(path)
	if err != nil {
		t.Fatalf("catalog.Open: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return db
}

// AC-1/AC-2/EC-10 successor: one row whose raw_xml fails to unmarshal must
// never empty the whole load — this is the fault-tolerance guarantee
// walkXMLFiles used to provide for file-level failures, reproduced here for
// row-level failures.
func TestLoadItems_SkipsUnparseableRowWithoutEmptyingCache(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test.db")
	setup, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open for setup: %v", err)
	}
	if _, err := setup.Exec(testDDL); err != nil {
		t.Fatalf("create schema: %v", err)
	}

	insert := `INSERT INTO item (uuid, name, is_raid, raw_xml) VALUES (?, ?, 0, ?)`
	for _, name := range []string{"a", "b", "c"} {
		rawXML := fmt.Sprintf(`<Item><Name>%s</Name><MinLevel>10</MinLevel></Item>`, name)
		if _, err := setup.Exec(insert, name, name, rawXML); err != nil {
			t.Fatalf("seed %s: %v", name, err)
		}
	}
	// Malformed XML: unmarshal fails for this row specifically.
	if _, err := setup.Exec(insert, "broken", "broken", "<Item><Name>Broken</Na"); err != nil {
		t.Fatalf("seed broken: %v", err)
	}

	db := reopenReadOnly(t, setup, path)
	items, skipped, err := catalog.LoadItems(db)
	if err != nil {
		t.Fatalf("LoadItems returned an error for a content-level failure: %v", err)
	}
	if len(items) != 3 {
		t.Fatalf("want 3 parsed items, got %d", len(items))
	}
	if len(skipped) != 1 || skipped[0] != "broken" {
		t.Errorf("want [\"broken\"] skipped, got %v", skipped)
	}
}

func TestLoadItems_IsRaidComesFromColumnNotXML(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test.db")
	setup, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open for setup: %v", err)
	}
	if _, err := setup.Exec(testDDL); err != nil {
		t.Fatalf("create schema: %v", err)
	}
	// The XML itself has no <IsRaid> concept at all — is_raid is a catalog
	// column, resolved once by the ETL. Confirm the reader trusts the
	// column, not something it re-derives from raw_xml.
	if _, err := setup.Exec(`INSERT INTO item (uuid, name, is_raid, raw_xml) VALUES (?, ?, 1, ?)`,
		"r1", "Raid Item", `<Item><Name>Raid Item</Name></Item>`); err != nil {
		t.Fatalf("seed: %v", err)
	}
	if _, err := setup.Exec(`INSERT INTO item (uuid, name, is_raid, raw_xml) VALUES (?, ?, 0, ?)`,
		"r2", "Normal Item", `<Item><Name>Normal Item</Name></Item>`); err != nil {
		t.Fatalf("seed: %v", err)
	}

	db := reopenReadOnly(t, setup, path)
	items, _, err := catalog.LoadItems(db)
	if err != nil {
		t.Fatalf("LoadItems: %v", err)
	}
	byName := map[string]bool{}
	for _, it := range items {
		byName[it.Name] = it.IsRaid
	}
	if !byName["Raid Item"] {
		t.Error("Raid Item: want IsRaid true")
	}
	if byName["Normal Item"] {
		t.Error("Normal Item: want IsRaid false")
	}
}

func TestLoadFiligrees_SetNameFromFirstMembership(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test.db")
	setup, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open for setup: %v", err)
	}
	if _, err := setup.Exec(testDDL); err != nil {
		t.Fatalf("create schema: %v", err)
	}
	if _, err := setup.Exec(`INSERT INTO filigree (uuid, name, raw_xml) VALUES (?, ?, ?)`,
		"f1", "Dual/Set Filigree", `<Filigree><Name>Dual/Set Filigree</Name></Filigree>`); err != nil {
		t.Fatalf("seed filigree: %v", err)
	}
	if _, err := setup.Exec(`INSERT INTO gear_set (uuid, name) VALUES (?, ?), (?, ?)`,
		"s1", "First Set", "s2", "Second Set"); err != nil {
		t.Fatalf("seed sets: %v", err)
	}
	if _, err := setup.Exec(`INSERT INTO filigree_set (filigree_uuid, set_uuid, position) VALUES
		(?, ?, 0), (?, ?, 1)`, "f1", "s1", "f1", "s2"); err != nil {
		t.Fatalf("seed membership: %v", err)
	}

	db := reopenReadOnly(t, setup, path)
	fils, skipped, err := catalog.LoadFiligrees(db)
	if err != nil {
		t.Fatalf("LoadFiligrees: %v", err)
	}
	if len(skipped) != 0 {
		t.Fatalf("unexpected skips: %v", skipped)
	}
	if len(fils) != 1 || fils[0].SetName != "First Set" {
		t.Fatalf("want SetName %q from position 0, got %+v", "First Set", fils)
	}
}

func TestLoadSetBonuses_ExcludesMembershipOnlySets(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test.db")
	setup, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open for setup: %v", err)
	}
	if _, err := setup.Exec(testDDL); err != nil {
		t.Fatalf("create schema: %v", err)
	}
	// One set has a real definition; one is membership-only (raw_xml NULL) —
	// referenced by an item/filigree but never itself authored with a
	// <SetBonus> element anywhere in the corpus (see schema doc §5.1.3).
	if _, err := setup.Exec(`INSERT INTO gear_set (uuid, name, raw_xml) VALUES (?, ?, ?)`,
		"s1", "Defined Set", `<SetBonus><Type>Defined Set</Type></SetBonus>`); err != nil {
		t.Fatalf("seed defined set: %v", err)
	}
	if _, err := setup.Exec(`INSERT INTO gear_set (uuid, name, raw_xml) VALUES (?, ?, NULL)`,
		"s2", "Membership Only Set"); err != nil {
		t.Fatalf("seed membership-only set: %v", err)
	}

	db := reopenReadOnly(t, setup, path)
	sets, _, err := catalog.LoadSetBonuses(db)
	if err != nil {
		t.Fatalf("LoadSetBonuses: %v", err)
	}
	if len(sets) != 1 || sets[0].Type != "Defined Set" {
		t.Fatalf("want exactly the 1 defined set, got %+v", sets)
	}
}

func TestReadMeta(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test.db")
	setup, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open for setup: %v", err)
	}
	if _, err := setup.Exec(`CREATE TABLE catalog_meta (
		id INTEGER PRIMARY KEY, schema_version INTEGER, catalog_version INTEGER,
		built_at TEXT, ddobuilder_commit TEXT, etl_version TEXT,
		source_file_count INTEGER, min_app_version TEXT, content_hash TEXT,
		identity_registry_hash TEXT)`); err != nil {
		t.Fatalf("create catalog_meta: %v", err)
	}
	if _, err := setup.Exec(`INSERT INTO catalog_meta VALUES (1, 1, 42, 'built', 'commit', 'etlv', 100, '0.5.0', 'chash', 'rhash')`); err != nil {
		t.Fatalf("seed catalog_meta: %v", err)
	}

	db := reopenReadOnly(t, setup, path)
	meta, err := catalog.ReadMeta(db)
	if err != nil {
		t.Fatalf("ReadMeta: %v", err)
	}
	if meta.CatalogVersion != 42 || meta.MinAppVersion != "0.5.0" {
		t.Errorf("got %+v", meta)
	}
}
