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
// filter (Location, and Binding when the column is present) — whether each
// name actually matches a real DDOBuilderV2 item/augment is only resolved
// later, at solve time, by optimizer.py's name-set membership check.
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

	a.addLog(fmt.Sprintf("Trove owned items: %d rows, %d matched to real items.", totalRows, len(items)))
	return TroveOwnedItemsResult{
		Success:   true,
		TotalRows: totalRows,
		Items:     items,
	}
}
