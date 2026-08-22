package main

import (
	"database/sql"
	"os"
	"path/filepath"
	"testing"
	"time"

	"goGearset/internal/catalog"

	_ "modernc.org/sqlite"
)

// The header's "Dataset 2.0.0.83" line is fed by GetDatasetVersion, which is a
// four-link chain: ETL writes catalog_meta.ddobuilder_version -> ReadMeta reads
// it -> loadCaches publishes it on App -> the RPC returns it. Every link has
// already broken once:
//
//   - the column did not exist, so ReadMeta's whole SELECT failed and every
//     meta field silently went to its zero value;
//   - the RPC returned before loadCaches had run, so it answered "" during the
//     ~0.5s startup window the frontend actually calls it in;
//   - and the app never reads the catalog these tests build — it seeds an
//     embedded copy into the user data directory and reseeds ONLY when
//     catalog_version strictly increases, so a rebuilt catalog carrying a
//     version that did not move is simply never installed.
//
// These tests pin the first three. The fourth is a release-packaging concern
// (bump --catalog-version past the installed one), not something a test can
// assert about a developer's own machine.

func testCatalogPath(t *testing.T) string {
	t.Helper()
	path := "bundled/darwin-arm64/catalog.db"
	if p := os.Getenv(catalogEnvVar); p != "" {
		path = p
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(abs); err != nil {
		t.Skipf("no catalog at %s", abs)
	}
	return abs
}

// ReadMeta must surface ddobuilder_version, and must keep working against a
// catalog built before the column existed — the installed catalog on an
// existing machine is exactly that, and a hard failure there takes every other
// meta field down with it.
func TestReadMetaSurfacesDatasetVersion(t *testing.T) {
	db, err := catalog.Open(testCatalogPath(t))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	meta, err := catalog.ReadMeta(db)
	if err != nil {
		t.Fatalf("ReadMeta: %v", err)
	}
	if meta.DDOBuilderVersion == "" {
		t.Error("DDOBuilderVersion is empty — the catalog was built without " +
			"ddobuilder_version, so the header will render Build only")
	}
	// Guards the parser bug that produced "\.0.0.83": BuildInfo.h mentions
	// BUILDINFO_VERSION_MAJOR on three lines, and a substring match picked up
	// the line-continuation backslash from the macro definition.
	if meta.CatalogVersion == 0 {
		t.Error("CatalogVersion is 0 — the rest of the row did not decode")
	}
	t.Logf("catalog_version=%d ddobuilder_version=%q",
		meta.CatalogVersion, meta.DDOBuilderVersion)
}

// A catalog predating the column must still yield a usable Meta rather than an
// error, since ReadMeta's caller treats a failure as "no meta at all".
func TestReadMetaToleratesCatalogWithoutDatasetVersion(t *testing.T) {
	// catalog.Open is deliberately read-only, so the column is dropped through
	// a separate read-write handle on a copy, and the result is then read back
	// through the real catalog.Open — the same call the app makes.
	source, err := os.ReadFile(testCatalogPath(t))
	if err != nil {
		t.Fatal(err)
	}
	legacy := filepath.Join(t.TempDir(), "legacy.db")
	if err := os.WriteFile(legacy, source, 0o644); err != nil {
		t.Fatal(err)
	}

	rw, err := sql.Open("sqlite", "file:"+legacy)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := rw.Exec(`ALTER TABLE catalog_meta DROP COLUMN ddobuilder_version`); err != nil {
		rw.Close()
		t.Fatalf("dropping ddobuilder_version: %v", err)
	}
	rw.Close()

	legacyDB, err := catalog.Open(legacy)
	if err != nil {
		t.Fatal(err)
	}
	defer legacyDB.Close()

	meta, err := catalog.ReadMeta(legacyDB)
	if err != nil {
		t.Fatalf("ReadMeta failed on a pre-column catalog: %v — this is the "+
			"regression that blanked every meta field", err)
	}
	if meta.DDOBuilderVersion != "" {
		t.Errorf("expected empty DDOBuilderVersion, got %q", meta.DDOBuilderVersion)
	}
	if meta.CatalogVersion == 0 {
		t.Error("CatalogVersion is 0 — the fallback lost the rest of the row")
	}
}

// The end-to-end path the frontend exercises: load the caches, then call the
// bound method exactly as App.svelte's onMount does.
func TestGetDatasetVersionReturnsTheCatalogsVersion(t *testing.T) {
	catalogFile := testCatalogPath(t)
	t.Chdir(t.TempDir())

	a := NewApp()
	a.catalogDBPath = catalogFile
	a.loadCaches("Cached")

	got := a.GetDatasetVersion()
	if got == "" {
		t.Fatal("GetDatasetVersion returned empty — the header renders Build only")
	}
	t.Logf("GetDatasetVersion() = %q", got)
}

// GetDatasetVersion must block until loadCaches has published the version,
// rather than racing it and returning "". loadCaches runs in a goroutine from
// startup() while the UI is already interactive, and the frontend's onMount
// call lands inside that window — the bug that made the header show Build only
// even with a correct catalog.
func TestGetDatasetVersionWaitsForCacheLoad(t *testing.T) {
	catalogFile := testCatalogPath(t)
	t.Chdir(t.TempDir())

	a := NewApp()
	a.catalogDBPath = catalogFile

	// Call the RPC BEFORE loadCaches starts, mirroring the startup ordering.
	result := make(chan string, 1)
	go func() { result <- a.GetDatasetVersion() }()

	// Give the RPC a chance to return early if it is not actually gated.
	time.Sleep(50 * time.Millisecond)
	select {
	case got := <-result:
		t.Fatalf("GetDatasetVersion returned %q before loadCaches ran — it is "+
			"not waiting on cachesReady, so it races the startup goroutine", got)
	default:
	}

	go a.loadCaches("Cached")

	select {
	case got := <-result:
		if got == "" {
			t.Fatal("GetDatasetVersion unblocked but returned empty")
		}
		t.Logf("GetDatasetVersion() = %q after cache load", got)
	case <-time.After(60 * time.Second):
		t.Fatal("GetDatasetVersion never returned — cachesReady was not closed")
	}
}
