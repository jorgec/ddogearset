package main

// Covers the catalog-readiness gate in LoadTroveFromPath (see App.cacheReadyCh).
//
// The bug these protect against: loadCaches runs in a goroutine from startup()
// while the UI is already usable, so a Trove CSV imported in the first ~0.5s
// of a launch was matched against an EMPTY item cache and came back
// Success=true with zero items — an import that looked, on screen, exactly
// like nothing having happened.

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

const gateTestCSV = "Character,Location,Name,Binding\n" +
	"Alice,Inventory,+1 Starter Dagger,BtC\n" +
	"Alice,Bank,+1 Starter Docent,BtC\n" +
	"Bob,Inventory,+1 Starter Greatsword,BtA\n"

// writeCSV puts the fixture on disk, since the import RPC takes a path now.
func writeCSV(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "TroveExport.Inventory.csv")
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}
	return path
}

func testCatalogOrSkip(t *testing.T) string {
	t.Helper()
	path := os.Getenv("GOGEARSET_TEST_CATALOG")
	if path == "" {
		t.Skip("set GOGEARSET_TEST_CATALOG to a built catalog.db to run this test")
	}
	return path
}

// The real startup shape: the caches are still loading when the user clicks.
// The call must WAIT and then answer correctly, not race through and answer
// "you own nothing".
func TestLoadTroveFromPath_WaitsForCatalogLoad(t *testing.T) {
	t.Setenv(catalogEnvVar, testCatalogOrSkip(t))

	a := NewApp()
	go func() {
		time.Sleep(150 * time.Millisecond) // stand-in for ensureCatalogSeeded
		a.loadCaches("Cached")
	}()

	res := a.LoadTroveFromPath(writeCSV(t, gateTestCSV)) // dropped before the caches exist
	if !res.Success {
		t.Fatalf("expected success, got error %q", res.ErrorMessage)
	}
	if len(res.Items) != 3 {
		t.Fatalf("matched %d items, want 3 — the gate did not wait for loadCaches", len(res.Items))
	}
}

// When the catalog genuinely cannot be loaded, the caller must be TOLD.
// Returning an empty list with Success=true is what made the original failure
// invisible.
func TestLoadTroveFromPath_ReportsUnavailableCatalog(t *testing.T) {
	a := NewApp()
	a.markCachesReady() // loadCaches finished, but with nothing in it

	res := a.LoadTroveFromPath(writeCSV(t, gateTestCSV))
	if res.Success {
		t.Fatal("expected failure when the item catalog is empty")
	}
	if res.ErrorMessage == "" {
		t.Fatal("expected an explanatory error message")
	}
	if res.TotalRows != 3 {
		t.Errorf("TotalRows = %d, want 3 (the CSV still parsed)", res.TotalRows)
	}
}

// A CSV whose names match nothing is NOT an error — it is a legitimately
// empty result, and must stay distinguishable from the case above.
func TestLoadTroveFromPath_UnmatchedNamesAreNotAnError(t *testing.T) {
	t.Setenv(catalogEnvVar, testCatalogOrSkip(t))

	a := NewApp()
	a.loadCaches("Cached")

	res := a.LoadTroveFromPath(writeCSV(t, "Character,Location,Name,Binding\nAlice,Inventory,Not A Real Item At All,BtC\n"))
	if !res.Success {
		t.Fatalf("expected success, got error %q", res.ErrorMessage)
	}
	if len(res.Items) != 0 {
		t.Fatalf("matched %d items, want 0", len(res.Items))
	}
}

// Run with -race: the reads of itemsByName/itemsCache must be ordered against
// loadCaches' writes, and addLog/GetSystemLogs must not race either.
func TestLoadTroveFromPath_NoRaceWithCacheLoad(t *testing.T) {
	t.Setenv(catalogEnvVar, testCatalogOrSkip(t))

	a := NewApp()
	csvPath := writeCSV(t, gateTestCSV)
	done := make(chan struct{})
	go func() {
		a.loadCaches("Cached")
		close(done)
	}()

	for {
		select {
		case <-done:
			return
		default:
			a.LoadTroveFromPath(csvPath)
			a.GetSystemLogs()
		}
	}
}

// A path that does not exist must be reported, not swallowed. The frontend
// hands us whatever Wails' OnFileDrop reported, so this is reachable.
func TestLoadTroveFromPath_MissingFile(t *testing.T) {
	a := NewApp()
	a.markCachesReady()

	res := a.LoadTroveFromPath(filepath.Join(t.TempDir(), "nope.csv"))
	if res.Success {
		t.Fatal("expected failure for a missing file")
	}
	if res.ErrorMessage == "" {
		t.Fatal("expected an explanatory error message")
	}
	if res.FileName != "nope.csv" {
		t.Errorf("FileName = %q, want %q", res.FileName, "nope.csv")
	}
}

// The names the solver constraint is built from must come back too — that is
// the half of the old two-RPC split that fed configStore.owned_item_names.
func TestLoadTroveFromPath_ReturnsOwnedNamesAndItems(t *testing.T) {
	t.Setenv(catalogEnvVar, testCatalogOrSkip(t))

	a := NewApp()
	a.loadCaches("Cached")

	res := a.LoadTroveFromPath(writeCSV(t, gateTestCSV))
	if !res.Success {
		t.Fatalf("expected success, got %q", res.ErrorMessage)
	}
	if len(res.OwnedNames) != 3 {
		t.Errorf("OwnedNames = %d, want 3", len(res.OwnedNames))
	}
	if len(res.Items) != 3 {
		t.Errorf("Items = %d, want 3", len(res.Items))
	}
	if res.FileName != "TroveExport.Inventory.csv" {
		t.Errorf("FileName = %q", res.FileName)
	}
}
