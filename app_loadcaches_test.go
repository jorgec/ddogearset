package main

import (
	"os"
	"path/filepath"
	"testing"
)

// TestLoadCaches_AgainstRealCatalog is an integration test, not a unit test:
// it runs loadCaches — the real function app.go's startup() calls — against a
// real, fully-built catalog.db, produced by the actual ETL pipeline
// (etl/walk.py -> transform.py -> load.py) from the real DDOBuilderV2 corpus.
// Skipped by default since that fixture lives outside the repo (built during
// Phase 4/5 development, see docs/0.5.0/00_ETL_START_HERE.md); point
// GOGEARSET_TEST_CATALOG at one to run it.
//
// This is what proves loadCaches' WIRING is correct — the unit tests in
// internal/catalog cover the reader in isolation, but nothing else exercises
// InitEnrichment -> catalog.Open -> the four Load* calls -> EnrichItemsInPlace
// -> the name indexes, end to end, the way the running app actually does.
func TestLoadCaches_AgainstRealCatalog(t *testing.T) {
	path := os.Getenv("GOGEARSET_TEST_CATALOG")
	if path == "" {
		t.Skip("set GOGEARSET_TEST_CATALOG to a built catalog.db to run this integration test")
	}
	t.Setenv(catalogEnvVar, path)

	a := NewApp()
	a.loadCaches("Cached")

	if len(a.itemsCache) == 0 {
		t.Fatal("itemsCache is empty — loadCaches did not populate it")
	}
	if len(a.augmentsCache) == 0 {
		t.Fatal("augmentsCache is empty")
	}
	if len(a.filigreesCache) == 0 {
		t.Fatal("filigreesCache is empty")
	}
	if len(a.setBonusCache) == 0 {
		t.Fatal("setBonusCache is empty")
	}

	idx, ok := a.itemsByName["Docent of Defiance"]
	if !ok {
		t.Fatal("name index missing a known item")
	}
	item := a.itemsCache[idx]
	if item.Description == "" {
		t.Error("item Description empty — raw_xml unmarshal did not populate display fields")
	}
	if item.Armor != "Docent" {
		t.Errorf("Armor: want %q, got %q", "Docent", item.Armor)
	}
	// PackID/WikiURL come from Go-side enrichment (packIDFor/wikiURLFor), run
	// over the catalog-sourced item — confirms EnrichItemsInPlace still ran.
	if item.WikiURL == "" {
		t.Error("WikiURL empty — EnrichItemsInPlace did not run")
	}

	t.Logf("items=%d augments=%d filigrees=%d sets=%d",
		len(a.itemsCache), len(a.augmentsCache), len(a.filigreesCache), len(a.setBonusCache))
}

// TestPackAttributionSurvivesAForeignWorkingDirectory reproduces a real report
// from a packaged Windows install:
//
//	Failed to load pack mappings, item pack attribution unavailable: open
//	data/PackMappings.json: The system cannot find the path specified.
//
// InitEnrichment used to be handed "data/PackMappings.json", resolved against
// the process's WORKING DIRECTORY — the repo root under `go run`/`wails dev`,
// and whatever directory the OS launched the packaged app from otherwise. That
// is why it went unnoticed here: every test in this repo runs with the repo
// root as cwd, so the path always resolved in CI and in every local run.
//
// The fix embeds the file (`packMappingsJSON` in app.go) so there is no path
// left to get wrong. This test is the one that would have caught the
// original bug: it runs loadCaches from a directory containing nothing but
// itself, exactly what a packaged app's launch directory looks like.
func TestPackAttributionSurvivesAForeignWorkingDirectory(t *testing.T) {
	catalogFile, err := filepath.Abs("bundled/darwin-arm64/catalog.db")
	if err != nil {
		t.Fatal(err)
	}
	if p := os.Getenv(catalogEnvVar); p != "" {
		if catalogFile, err = filepath.Abs(p); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := os.Stat(catalogFile); err != nil {
		t.Skipf("no catalog at %s", catalogFile)
	}

	// Absolute, taken BEFORE the chdir below — a relative catalog path would
	// break for the same reason PackMappings.json used to, and that is not
	// the bug this test exists to catch.
	t.Chdir(t.TempDir())

	a := NewApp()
	a.catalogDBPath = catalogFile
	a.loadCaches("Cached")

	if len(a.itemsCache) == 0 {
		t.Fatal("items failed to load from a non-repo-root working directory")
	}
	var attributed int
	for _, it := range a.itemsCache {
		if it.PackID != "" {
			attributed++
		}
	}
	if attributed == 0 {
		t.Fatal("every item has an empty PackID — this reproduces the Windows report")
	}
	t.Logf("%d of %d items carry pack attribution from a foreign working directory",
		attributed, len(a.itemsCache))
}
