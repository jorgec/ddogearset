package main

// Covers SearchItems' name mode and the filters both modes share.
//
// Name mode is answered entirely from the caches, so it is testable without
// GLPK or a solver subprocess. Stat mode is not covered here — it needs the
// bundled solver — but the two share slotMatches and the level window, which
// are asserted directly.

import (
	"strings"
	"testing"
)

// searchApp loads the catalog once for the tests below.
func searchApp(t *testing.T) *App {
	t.Helper()
	t.Setenv(catalogEnvVar, testCatalogOrSkip(t))
	a := NewApp()
	a.loadCaches("Cached")
	return a
}

// A name search must find an item by any part of its name, whatever the case,
// and must report where it can be worn.
func TestSearchItems_ByName(t *testing.T) {
	a := searchApp(t)

	// Query taken from the catalog rather than hardcoded, so this stays a test
	// of searching and never becomes an assertion about which items shipped.
	var want string
	var wantML int
	for _, it := range a.itemsCache {
		if len(it.Name) > 6 && len(it.EquipmentSlot.Slots) > 0 && strings.ContainsRune(it.Name, ' ') {
			want, wantML = it.Name, it.MinLevel
			break
		}
	}
	if want == "" {
		t.Fatal("catalog yielded no usable sample item")
	}

	res, err := a.SearchItems("name", strings.ToUpper(want), 0, 40, "")
	if err != nil {
		t.Fatalf("SearchItems: %v", err)
	}
	if !res.Success {
		t.Fatalf("SearchItems(name) failed: %s", res.ErrorMessage)
	}
	if res.Mode != "name" {
		t.Errorf("Mode = %q, want %q", res.Mode, "name")
	}

	var found *StatSearchEntry
	for i := range res.Results {
		if res.Results[i].SourceName == want {
			found = &res.Results[i]
			break
		}
	}
	if found == nil {
		t.Fatalf("searching for %q returned %d rows, none of them that item", want, len(res.Results))
	}
	if found.ML != wantML {
		t.Errorf("ML = %d, want %d", found.ML, wantML)
	}
	if len(found.Slots) == 0 {
		t.Error("an equippable item came back with no slots")
	}
}

// An empty query is a no-op, not a dump of the whole catalog.
func TestSearchItems_EmptyNameQueryReturnsNothing(t *testing.T) {
	a := searchApp(t)

	res, _ := a.SearchItems("name", "   ", 1, 34, "")
	if res.Success {
		t.Error("an empty query reported success")
	}
	if len(res.Results) != 0 {
		t.Errorf("an empty query returned %d rows", len(res.Results))
	}
}

// The level window is a filter on the ANSWER, not a suggestion: nothing
// outside it may come back.
func TestSearchItems_LevelWindowFilters(t *testing.T) {
	a := searchApp(t)

	res, _ := a.SearchItems("name", "of", 30, 32, "")
	if !res.Success {
		t.Fatalf("search failed: %s", res.ErrorMessage)
	}
	if len(res.Results) == 0 {
		t.Skip("catalog has no ML 30-32 item matching 'of' — nothing to assert")
	}
	for _, e := range res.Results {
		// Filigrees have no minimum level, so the window does not apply to
		// them — holding them to an ML they do not have would just make them
		// unfindable. Everything else is held to it.
		if e.SourceType == "filigree" {
			continue
		}
		if e.ML < 30 || e.ML > 32 {
			t.Errorf("%s (%s) has ML %d, outside the requested 30-32 window", e.SourceName, e.SourceType, e.ML)
		}
	}
}

// An inverted window is a typo mid-edit (typing "3" into a min box that reads
// 34), not a request for nothing.
func TestSearchItems_InvertedLevelWindowIsSwapped(t *testing.T) {
	a := searchApp(t)

	high, _ := a.SearchItems("name", "of", 20, 34, "")
	low, _ := a.SearchItems("name", "of", 34, 20, "")
	if len(high.Results) != len(low.Results) {
		t.Errorf("min/max swapped gave %d rows, want the same %d as the right way round",
			len(low.Results), len(high.Results))
	}
}

// A slot filter keeps only items eligible for that slot — and drops augments
// and filigrees entirely, because they are not worn in one.
func TestSearchItems_SlotFilter(t *testing.T) {
	a := searchApp(t)

	res, _ := a.SearchItems("name", "of", 1, 40, "Helmet")
	if !res.Success {
		t.Fatalf("search failed: %s", res.ErrorMessage)
	}
	if len(res.Results) == 0 {
		t.Skip("catalog has no helmet matching 'of' — nothing to assert")
	}
	for _, e := range res.Results {
		if e.SourceType != "item" {
			t.Errorf("%s is a %s, which cannot occupy a slot", e.SourceName, e.SourceType)
			continue
		}
		var ok bool
		for _, s := range e.Slots {
			if strings.EqualFold(s, "Helmet") {
				ok = true
			}
		}
		if !ok {
			t.Errorf("%s came back for the Helmet filter but its slots are %v", e.SourceName, e.Slots)
		}
	}
}

// Results carry what the item grants, so a name search answers "what does this
// do" without a second lookup.
func TestSearchItems_NameResultsSummariseStats(t *testing.T) {
	a := searchApp(t)

	res, _ := a.SearchItems("name", "of", 20, 34, "")
	if len(res.Results) == 0 {
		t.Skip("no matches to inspect")
	}
	for _, e := range res.Results {
		if e.SourceType == "item" && len(e.Stats) > 0 {
			return
		}
	}
	t.Error("no item in the results summarised a single stat")
}

// The gate: a search issued while the caches are still loading must wait and
// answer, not race through and report an empty catalog.
func TestSearchItems_WaitsForCacheLoad(t *testing.T) {
	t.Setenv(catalogEnvVar, testCatalogOrSkip(t))

	a := NewApp()
	go a.loadCaches("Cached")

	res, _ := a.SearchItems("name", "of", 1, 40, "")
	if !res.Success {
		t.Fatalf("search failed: %s", res.ErrorMessage)
	}
	if len(res.Results) == 0 {
		t.Error("searching during cache load returned nothing — the gate did not wait")
	}
}
