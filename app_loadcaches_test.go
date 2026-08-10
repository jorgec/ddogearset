package main

import (
	"os"
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
