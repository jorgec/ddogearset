package main

// Covers the catalog-readiness gate on every RPC that reads itemsCache,
// augmentsCache, filigreesCache or setBonusCache (see App.awaitCaches).
//
// Same defect as the Trove one in trove_cachegate_test.go, on a wider
// surface: loadCaches runs in a goroutine from startup() while the UI is
// already clickable, so for the first ~0.5s of a launch every one of these
// answered from an EMPTY cache — an item panel that rendered blank, a search
// that found nothing, with no error anywhere — and every read of the caches
// raced loadCaches' writes.

import (
	"sync"
	"testing"
	"time"
)

// catalogSamples are query arguments taken from the catalog itself rather
// than hardcoded, so these tests assert gate behaviour and never quietly
// become assertions about which items shipped in a given catalog build.
type catalogSamples struct {
	itemName  string
	itemSlot  string
	itemLevel int

	augName  string
	augType  string
	augLevel int

	filName string
	setName string
}

// sampleCatalog loads the catalog once and picks one usable query of each
// kind out of it.
func sampleCatalog(t *testing.T) catalogSamples {
	t.Helper()
	t.Setenv(catalogEnvVar, testCatalogOrSkip(t))

	a := NewApp()
	a.loadCaches("Cached")

	var s catalogSamples
	for _, it := range a.itemsCache {
		if len(it.EquipmentSlot.Slots) > 0 && it.Name != "" {
			s.itemName, s.itemSlot, s.itemLevel = it.Name, it.EquipmentSlot.Slots[0].Local, it.MinLevel
			break
		}
	}
	for _, aug := range a.augmentsCache {
		if len(aug.Types) > 0 && aug.Name != "" {
			s.augName, s.augType, s.augLevel = aug.Name, aug.Types[0], aug.MinLevel
			break
		}
	}
	if len(a.filigreesCache) > 0 {
		s.filName = a.filigreesCache[0].Name
	}
	if len(a.setBonusCache) > 0 {
		s.setName = a.setBonusCache[0].Type
	}

	if s.itemName == "" || s.augName == "" || s.filName == "" || s.setName == "" {
		t.Fatalf("catalog did not yield a sample of every kind: %+v", s)
	}
	return s
}

// The real startup shape: the caches are still loading when the UI asks.
// Every one of these must WAIT and then answer correctly, not race through
// and answer "there is nothing".
func TestCatalogReaders_WaitForCacheLoad(t *testing.T) {
	s := sampleCatalog(t)

	a := NewApp()
	go func() {
		time.Sleep(150 * time.Millisecond) // stand-in for ensureCatalogSeeded
		a.loadCaches("Cached")
	}()

	// Called before the caches exist — exactly the window the user clicks in.
	if got := a.GetAvailableItems(s.itemSlot, s.itemLevel, ""); len(got) == 0 {
		t.Errorf("GetAvailableItems(%q, %d) returned nothing — the gate did not wait", s.itemSlot, s.itemLevel)
	}
	if got := a.GetItemDetails(s.itemName); got.Name != s.itemName {
		t.Errorf("GetItemDetails(%q).Name = %q, want %q", s.itemName, got.Name, s.itemName)
	}
	if got := a.GetAvailableAugments(s.augType, s.augLevel, ""); len(got) == 0 {
		t.Errorf("GetAvailableAugments(%q, %d) returned nothing", s.augType, s.augLevel)
	}
	if got := a.GetAugmentByName(s.augName); got.Name != s.augName {
		t.Errorf("GetAugmentByName(%q).Name = %q, want %q", s.augName, got.Name, s.augName)
	}
	if got := a.GetAvailableFiligrees(""); len(got) == 0 {
		t.Error("GetAvailableFiligrees(\"\") returned nothing")
	}
	if got := a.GetFiligreeByName(s.filName); got.Name != s.filName {
		t.Errorf("GetFiligreeByName(%q).Name = %q, want %q", s.filName, got.Name, s.filName)
	}
	if got := a.GetSetBonus(s.setName); got.Type != s.setName {
		t.Errorf("GetSetBonus(%q).Type = %q, want %q", s.setName, got.Type, s.setName)
	}
}

// The gate must only ever delay the FIRST calls of a run. Once loadCaches has
// finished, the wait is a closed-channel receive; if it were not, every
// keystroke in a search box would pay for it.
func TestCatalogReaders_DoNotWaitOnceReady(t *testing.T) {
	a := NewApp()
	a.markCachesReady() // loadCaches finished — here, with nothing in it

	done := make(chan struct{})
	go func() {
		defer close(done)
		a.GetAvailableItems("Helmet", 34, "")
		a.GetItemDetails("Docent of Defiance")
		a.GetAvailableAugments("Green", 34, "")
		a.GetAugmentByName("+7 Combustion")
		a.GetAvailableFiligrees("")
		a.GetFiligreeByName("Anything")
		a.GetSetBonus("Anything")
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("a reader blocked after markCachesReady — the gate is waiting when it should not")
	}
}

// Run with -race: every read of the four caches and their name indexes must be
// ordered against loadCaches' writes of them.
func TestCatalogReaders_NoRaceWithCacheLoad(t *testing.T) {
	t.Setenv(catalogEnvVar, testCatalogOrSkip(t))

	a := NewApp()
	done := make(chan struct{})
	go func() {
		a.loadCaches("Cached")
		close(done)
	}()

	// One goroutine per reader, so a gate removed from any single one of them
	// still trips the detector.
	readers := []func(){
		func() { a.GetAvailableItems("Helmet", 34, "") },
		func() { a.GetItemDetails("Docent of Defiance") },
		func() { a.GetAvailableAugments("Green", 34, "") },
		func() { a.GetAugmentByName("+7 Combustion") },
		func() { a.GetAvailableFiligrees("spell") },
		func() { a.GetFiligreeByName("Anything") },
		func() { a.GetSetBonus("Anything") },
		func() { a.GetSystemLogs() },
	}

	var wg sync.WaitGroup
	for _, read := range readers {
		wg.Add(1)
		go func(read func()) {
			defer wg.Done()
			for {
				select {
				case <-done:
					return
				default:
					read()
				}
			}
		}(read)
	}
	wg.Wait()
}
