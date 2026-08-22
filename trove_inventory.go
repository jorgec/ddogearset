package main

// Parses a Trove inventory export (CSV) into the set of item/augment names the
// user actually owns, so the solver can be constrained to only select gear
// they have — see docs/TROVE_INVENTORY_IMPORT_SPEC.md for the full spec and
// the real-data validation behind the filter choices below.
//
// Deliberately NOT filigree-aware and NOT random-loot-aware (see the spec's
// "Scope" section) — DDOBuilderV2 is treated as the definitive source, and a
// CSV row whose Name doesn't match it is silently dropped. No fuzzy matching.
//
// Import is drag-and-drop only, so this file takes a PATH and reads the file
// itself. The two content-taking RPCs it used to expose (LoadTroveInventory,
// GetTroveOwnedItems) were removed with the file-picker buttons that fed
// them — see docs/FILE_DIALOG_SILENT_DROP.md.

import (
	"bytes"
	"encoding/csv"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// parseTroveInventoryCSV applies the Location/Binding filter (see spec) and
// returns the deduplicated set of surviving item/augment names. Reads by
// column NAME (not fixed index) so a reordered Trove export column layout
// doesn't silently misparse.
//
// Only SubscriptionHash, Character, Location, Tab, and Name are guaranteed
// to be present in a Trove export — everything else, including Binding, is
// not. Location and Name are required (an export without them can't be
// meaningfully parsed); Binding is genuinely optional (see below).
// troveNameInfo accumulates the distinct Character/Location values seen for
// one owned name across the CSV — a name can appear more than once (the same
// character banking and re-inventorying it, or two characters both owning
// one), and the Owned Items screen wants to show all of them, not just
// whichever row happened to survive a plain dedup.
type troveNameInfo struct {
	characters map[string]bool
	locations  map[string]bool
}

func newTroveNameInfo() *troveNameInfo {
	return &troveNameInfo{characters: map[string]bool{}, locations: map[string]bool{}}
}

// sortedJoin renders a string set as a stable, human-readable list for
// display (e.g. in the Owned Items table's Character/Location columns).
func sortedJoin(set map[string]bool) string {
	vals := make([]string, 0, len(set))
	for v := range set {
		vals = append(vals, v)
	}
	sort.Strings(vals)
	return strings.Join(vals, ", ")
}

func parseTroveInventoryCSV(csvContent string) (names map[string]*troveNameInfo, totalRows int, err error) {
	// Trove's export has shown up with a UTF-8 BOM in testing (EC-2 in the
	// spec) — strip it before handing off to encoding/csv, which doesn't
	// otherwise know to skip it.
	trimmed := strings.TrimPrefix(csvContent, "\uFEFF")

	r := csv.NewReader(bytes.NewReader([]byte(trimmed)))
	r.FieldsPerRecord = -1 // tolerate ragged rows rather than aborting the whole file

	header, err := r.Read()
	if err == io.EOF {
		return map[string]*troveNameInfo{}, 0, nil
	}
	if err != nil {
		return nil, 0, fmt.Errorf("reading CSV header: %w", err)
	}

	colIndex := make(map[string]int, len(header))
	for i, col := range header {
		colIndex[strings.TrimSpace(col)] = i
	}
	locationCol, ok := colIndex["Location"]
	if !ok {
		return nil, 0, fmt.Errorf("CSV is missing a 'Location' column")
	}
	characterCol, ok := colIndex["Character"]
	if !ok {
		return nil, 0, fmt.Errorf("CSV is missing a 'Character' column")
	}
	nameCol, ok := colIndex["Name"]
	if !ok {
		return nil, 0, fmt.Errorf("CSV is missing a 'Name' column")
	}
	// Only SubscriptionHash, Character, Location, Tab, and Name are
	// guaranteed to be present in a Trove export — Binding is not, so it's
	// optional here. When present, rows are still filtered to BtA/BtC as
	// before; when absent, that filter is skipped rather than rejecting the
	// whole file or silently keeping zero rows.
	bindingCol, hasBinding := colIndex["Binding"]

	names = make(map[string]*troveNameInfo)
	for {
		row, err := r.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, 0, fmt.Errorf("reading CSV row %d: %w", totalRows+1, err)
		}
		totalRows++

		if locationCol >= len(row) || characterCol >= len(row) || nameCol >= len(row) {
			continue // ragged row missing one of the columns we need — skip, don't abort
		}
		location := row[locationCol]
		if location == "SharedCrafting" {
			continue
		}
		if hasBinding && bindingCol < len(row) {
			binding := row[bindingCol]
			if binding != "BtA" && binding != "BtC" {
				continue
			}
		}
		name := strings.TrimSpace(row[nameCol])
		if name == "" {
			continue
		}
		character := strings.TrimSpace(row[characterCol])

		info, exists := names[name]
		if !exists {
			info = newTroveNameInfo()
			names[name] = info
		}
		if character != "" {
			info.characters[character] = true
		}
		if location != "" {
			info.locations[location] = true
		}
	}

	return names, totalRows, nil
}

// TroveOwnedItem is one row in the Owned Items screen's list — just enough to
// render a list entry; the full detail is fetched separately (ItemDetail.svelte
// self-fetches by name, same as everywhere else it's used). Character/Location
// are comma-joined since one name can appear under more than one of each
// (e.g. two characters owning the same named item, or one character banking
// and re-inventorying it) — see troveNameInfo.
type TroveOwnedItem struct {
	Name      string `json:"name"`
	MinLevel  int    `json:"minLevel"`
	PackID    string `json:"packId,omitempty"`
	Character string `json:"character,omitempty"`
	Location  string `json:"location,omitempty"`
}

// TroveLoadResult is everything one import produces, in one reply.
//
// Both consumers are served by a single call on purpose. The solver
// constraint needs OwnedNames — items AND augments, unfiltered against the
// catalog, because the matching happens later in optimizer.py — while the
// Owned Items screen needs Items, catalog-matched and items-only. Those used
// to be two RPCs (LoadTroveInventory and GetTroveOwnedItems), which meant the
// frontend sent the whole CSV twice, concurrently, and Go parsed it twice.
// Now the file is read and parsed once, here.
type TroveLoadResult struct {
	Success      bool             `json:"success"`
	ErrorMessage string           `json:"errorMessage,omitempty"`
	FileName     string           `json:"fileName"`
	TotalRows    int              `json:"totalRows"`
	OwnedNames   []string         `json:"ownedNames"`
	Items        []TroveOwnedItem `json:"items"`
}

// LoadTroveFromPath imports a Trove export the user dragged onto the window.
//
// Takes a PATH, not the file's content: the import is drag-and-drop only
// (Wails' OnFileDrop hands the frontend absolute paths), so the CSV never
// crosses the IPC bridge at all. That removes the two failure modes the old
// content-based RPCs carried — a multi-megabyte payload sent twice over a
// bridge whose send errors are swallowed by Wails with no timeout, and the
// HTML file input whose element could be garbage-collected mid-dialog
// (docs/FILE_DIALOG_SILENT_DROP.md).
func (a *App) LoadTroveFromPath(path string) TroveLoadResult {
	fileName := filepath.Base(path)

	content, err := os.ReadFile(path)
	if err != nil {
		a.addLog("Failed to read Trove inventory CSV: " + err.Error())
		return TroveLoadResult{Success: false, FileName: fileName, ErrorMessage: "could not read " + fileName + ": " + err.Error()}
	}

	names, totalRows, err := parseTroveInventoryCSV(string(content))
	if err != nil {
		a.addLog("Failed to parse Trove inventory CSV: " + err.Error())
		return TroveLoadResult{Success: false, FileName: fileName, ErrorMessage: err.Error()}
	}

	ownedNames := make([]string, 0, len(names))
	for n := range names {
		ownedNames = append(ownedNames, n)
	}
	sort.Strings(ownedNames)

	// Wait for the item cache before matching against it. loadCaches runs in
	// a goroutine while the UI is already usable (see App.cacheReadyCh), so
	// without this an import in the first ~0.5s of a launch matched nothing
	// and the Owned Items screen rendered its empty state — a successful
	// import that looked exactly like a broken one. Waiting also gives the
	// reads below a happens-before edge against loadCaches' writes, which
	// `go test -race` flagged.
	select {
	case <-a.cachesReady():
	case <-time.After(catalogWaitTimeout):
		msg := catalogLoadingMsg
		a.addLog("Trove import: " + msg)
		return TroveLoadResult{Success: false, FileName: fileName, ErrorMessage: msg, TotalRows: totalRows}
	}
	if len(a.itemsCache) == 0 {
		// The gate opened but nothing is behind it: loadCaches failed (an
		// unreadable or missing catalog, already logged by it). Saying so is
		// the point — silently returning an empty list here is
		// indistinguishable from "you own nothing".
		msg := "the item catalog is unavailable — see the System Console for why"
		a.addLog("Trove import: " + msg)
		return TroveLoadResult{Success: false, FileName: fileName, ErrorMessage: msg, TotalRows: totalRows}
	}

	items := make([]TroveOwnedItem, 0, len(names))
	for name, info := range names {
		idx, ok := a.itemsByName[name]
		if !ok || idx >= len(a.itemsCache) {
			continue
		}
		it := a.itemsCache[idx]
		items = append(items, TroveOwnedItem{
			Name:      it.Name,
			MinLevel:  it.MinLevel,
			PackID:    it.PackID,
			Character: sortedJoin(info.characters),
			Location:  sortedJoin(info.locations),
		})
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Name < items[j].Name })

	a.addLog(fmt.Sprintf("Trove import from %s: %d rows, %d owned names, %d matched to real items.",
		fileName, totalRows, len(ownedNames), len(items)))
	return TroveLoadResult{
		Success:    true,
		FileName:   fileName,
		TotalRows:  totalRows,
		OwnedNames: ownedNames,
		Items:      items,
	}
}
