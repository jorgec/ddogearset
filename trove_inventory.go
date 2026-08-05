package main

// Parses a Trove inventory export (CSV) into the set of item/augment names the
// user actually owns, so the solver can be constrained to only select gear
// they have — see docs/TROVE_INVENTORY_IMPORT_SPEC.md for the full spec and
// the real-data validation behind the filter choices below.
//
// Deliberately NOT filigree-aware and NOT random-loot-aware (see the spec's
// "Scope" section) — DDOBuilderV2 is treated as the definitive source, and a
// CSV row whose Name doesn't match it is silently dropped. No fuzzy matching.

import (
	"bytes"
	"encoding/csv"
	"fmt"
	"io"
	"sort"
	"strings"
)

// TroveInventoryResult is what LoadTroveInventory returns to the frontend.
// OwnedNames is the deduplicated set of names that survived the CSV-level
// filter (Location/Binding) — whether each name actually matches a real
// DDOBuilderV2 item/augment is only resolved later, at solve time, by
// optimizer.py's name-set membership check.
type TroveInventoryResult struct {
	Success      bool     `json:"success"`
	ErrorMessage string   `json:"errorMessage,omitempty"`
	TotalRows    int      `json:"totalRows"`
	OwnedNames   []string `json:"ownedNames"`
}

// parseTroveInventoryCSV applies the Location/Binding filter (see spec) and
// returns the deduplicated set of surviving item/augment names. Reads by
// column NAME (not fixed index) so a reordered Trove export column layout
// doesn't silently misparse.
func parseTroveInventoryCSV(csvContent string) (names map[string]bool, totalRows int, err error) {
	// Trove's export has shown up with a UTF-8 BOM in testing (EC-2 in the
	// spec) — strip it before handing off to encoding/csv, which doesn't
	// otherwise know to skip it.
	trimmed := strings.TrimPrefix(csvContent, "\uFEFF")

	r := csv.NewReader(bytes.NewReader([]byte(trimmed)))
	r.FieldsPerRecord = -1 // tolerate ragged rows rather than aborting the whole file

	header, err := r.Read()
	if err == io.EOF {
		return map[string]bool{}, 0, nil
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
	bindingCol, ok := colIndex["Binding"]
	if !ok {
		return nil, 0, fmt.Errorf("CSV is missing a 'Binding' column")
	}
	nameCol, ok := colIndex["Name"]
	if !ok {
		return nil, 0, fmt.Errorf("CSV is missing a 'Name' column")
	}

	names = make(map[string]bool)
	for {
		row, err := r.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, 0, fmt.Errorf("reading CSV row %d: %w", totalRows+1, err)
		}
		totalRows++

		if locationCol >= len(row) || bindingCol >= len(row) || nameCol >= len(row) {
			continue // ragged row missing one of the columns we need — skip, don't abort
		}
		if row[locationCol] == "SharedCrafting" {
			continue
		}
		binding := row[bindingCol]
		if binding != "BtA" && binding != "BtC" {
			continue
		}
		name := strings.TrimSpace(row[nameCol])
		if name == "" {
			continue
		}
		names[name] = true
	}

	return names, totalRows, nil
}

// LoadTroveInventory is the RPC the frontend calls with the raw text content
// of a user-selected Trove export (read client-side via FileReader, matching
// how gearset files are already loaded — see Summary.svelte's loadGearset()
// — rather than Go opening a file by path).
func (a *App) LoadTroveInventory(csvContent string) TroveInventoryResult {
	names, totalRows, err := parseTroveInventoryCSV(csvContent)
	if err != nil {
		a.addLog("Failed to parse Trove inventory CSV: " + err.Error())
		return TroveInventoryResult{Success: false, ErrorMessage: err.Error()}
	}

	ownedNames := make([]string, 0, len(names))
	for n := range names {
		ownedNames = append(ownedNames, n)
	}

	a.addLog(fmt.Sprintf("Trove inventory loaded: %d rows, %d owned item/augment names after filtering.", totalRows, len(ownedNames)))
	return TroveInventoryResult{
		Success:    true,
		TotalRows:  totalRows,
		OwnedNames: ownedNames,
	}
}

// TroveOwnedItem is one row in the Owned Items screen's list — just enough to
// render a list entry; the full detail is fetched separately (ItemDetail.svelte
// self-fetches by name, same as everywhere else it's used).
type TroveOwnedItem struct {
	Name     string `json:"name"`
	MinLevel int    `json:"minLevel"`
	PackID   string `json:"packId,omitempty"`
}

type TroveOwnedItemsResult struct {
	Success      bool             `json:"success"`
	ErrorMessage string           `json:"errorMessage,omitempty"`
	TotalRows    int              `json:"totalRows"`
	Items        []TroveOwnedItem `json:"items"`
}

// GetTroveOwnedItems is the RPC behind the standalone "Owned Items" screen.
// Unlike LoadTroveInventory (which feeds the solver and must include both
// items AND augments, unfiltered against the catalog — matching happens
// later in Python), this is items-only and pre-filtered against the
// already-loaded itemsCache/itemsByName index, so the screen only ever shows
// names that are actually usable — no augments, no unmatched CSV noise.
func (a *App) GetTroveOwnedItems(csvContent string) TroveOwnedItemsResult {
	names, totalRows, err := parseTroveInventoryCSV(csvContent)
	if err != nil {
		a.addLog("Failed to parse Trove inventory CSV: " + err.Error())
		return TroveOwnedItemsResult{Success: false, ErrorMessage: err.Error()}
	}

	items := make([]TroveOwnedItem, 0, len(names))
	for name := range names {
		idx, ok := a.itemsByName[name]
		if !ok || idx >= len(a.itemsCache) {
			continue
		}
		it := a.itemsCache[idx]
		items = append(items, TroveOwnedItem{
			Name:     it.Name,
			MinLevel: it.MinLevel,
			PackID:   it.PackID,
		})
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Name < items[j].Name })

	a.addLog(fmt.Sprintf("Trove owned items: %d rows, %d matched to real items.", totalRows, len(items)))
	return TroveOwnedItemsResult{
		Success:   true,
		TotalRows: totalRows,
		Items:     items,
	}
}
