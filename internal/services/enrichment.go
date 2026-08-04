package services

import (
	"encoding/json"
	"fmt"
	"io"
	"net/url"
	"os"
	"strings"

	"goGearset/internal/models"
)

var config models.PackMappingsConfig
var raids []string

// InitEnrichmentForTest initializes the enrichment service with mock data for testing
func InitEnrichmentForTest(mockConfig models.PackMappingsConfig, mockRaids []string) {
	config = mockConfig
	raids = mockRaids
}

// InitEnrichment initializes the enrichment service from configuration files.
//
// Pack-mapping load failure is fatal (returned as an error) — without it no
// item can be attributed to an adventure pack. A raids-file load failure is
// deliberately NOT fatal: no raids data source exists in this repo, so raid
// detection is expected to be unavailable. In that case `raids` is left nil,
// EnrichItem's raid loop never matches, IsRaid stays false for every item, and
// the caller is told via the returned bool so it can log the degradation.
// See docs/ITEM_DETAIL_SPEC.md §4.3 / AC-12.
//
// Returns (raidsLoaded, error).
func InitEnrichment(packMappingsPath string, raidsPath string) (bool, error) {
	// Load pack mappings — fatal on failure.
	packFile, err := os.Open(packMappingsPath)
	if err != nil {
		return false, err
	}
	defer packFile.Close()
	packBytes, err := io.ReadAll(packFile)
	if err != nil {
		return false, err
	}
	if err := json.Unmarshal(packBytes, &config); err != nil {
		return false, err
	}

	// Load raids — non-fatal on failure.
	raids = nil
	if raidsPath == "" {
		return false, nil
	}
	raidBytes, raidErr := os.ReadFile(raidsPath)
	if raidErr != nil {
		return false, nil
	}
	if err := json.Unmarshal(raidBytes, &raids); err != nil {
		raids = nil
		return false, nil
	}
	return true, nil
}

// acquisitionFor computes the pack/wiki/raid attribution for an item name and
// its drop locations. Single source of truth shared by EnrichItem (which builds
// a separate models.Item) and EnrichItemInPlace (which annotates an XMLItem),
// so the two can never drift apart.
func acquisitionFor(name string, dropLocations []string) (packID, wikiURL string, isRaid bool, raidName string) {
	packID = "base"

	// Go's url.QueryEscape doesn't escape apostrophes, which wiki links need escaped.
	escapedName := url.QueryEscape(name)
	escapedName = strings.ReplaceAll(escapedName, "'", "%27")
	wikiURL = fmt.Sprintf("https://ddowiki.com/page/Special:Search?search=%s", escapedName)

	packIDAssigned := false
	for _, dropLoc := range dropLocations {
		for _, packMap := range config.PackMappings {
			for _, keyword := range packMap.Keywords {
				if strings.Contains(dropLoc, keyword) {
					packID = packMap.PackID
					packIDAssigned = true
					break
				}
			}
			if packIDAssigned {
				break
			}
		}
		if packIDAssigned {
			break
		}
	}

	// raids is nil whenever no raids data source was loaded, which is the
	// current expected state — see InitEnrichment.
	for _, dropLoc := range dropLocations {
		for _, rn := range raids {
			if strings.Contains(dropLoc, rn) {
				isRaid = true
				raidName = rn
				break
			}
		}
		if isRaid {
			break
		}
	}

	return packID, wikiURL, isRaid, raidName
}

// EnrichItem transforms an XMLItem into an enriched Item
func EnrichItem(xmlItem models.XMLItem) models.Item {
	item := models.Item{
		Name:          xmlItem.Name,
		Description:   xmlItem.Description,
		MinLevel:      xmlItem.MinLevel,
		DropLocations: xmlItem.DropLocations,
	}

	for _, slot := range xmlItem.EquipmentSlot.Slots {
		item.Slots = append(item.Slots, slot.Local)
	}

	item.PackID, item.WikiURL, item.IsRaid, item.RaidName = acquisitionFor(item.Name, item.DropLocations)

	return item
}

// EnrichItemInPlace annotates an XMLItem with its acquisition metadata. Called
// once per item at cache-load time (not per request), so GetItemDetails can
// return a fully-populated item with no extra RPC and no extra frontend type.
func EnrichItemInPlace(item *models.XMLItem) {
	if item == nil {
		return
	}
	item.PackID, item.WikiURL, item.IsRaid, item.RaidName = acquisitionFor(item.Name, item.DropLocations)
}
