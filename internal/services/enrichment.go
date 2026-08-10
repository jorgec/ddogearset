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

// InitEnrichmentForTest initializes the enrichment service with mock data for testing
func InitEnrichmentForTest(mockConfig models.PackMappingsConfig) {
	config = mockConfig
}

// InitEnrichment loads pack-mapping configuration — fatal on failure, since
// without it no item can be attributed to an adventure pack.
//
// Raid detection is no longer computed here. It used to be a Go-side
// upgrade/crafting-chain walk (docs/RAID_DETECTION_SPEC.md) mirroring
// python/rules/provenance.py's _resolve_is_raid; that walk is now done once,
// correctly, by the ETL (docs/0.5.0/00_ETL_START_HERE.md Phase 4 verified the
// two agree), and catalog.LoadItems sets XMLItem.IsRaid directly from the
// catalog's precomputed column. See internal/catalog/catalog.go.
func InitEnrichment(packMappingsPath string) error {
	packFile, err := os.Open(packMappingsPath)
	if err != nil {
		return err
	}
	defer packFile.Close()
	packBytes, err := io.ReadAll(packFile)
	if err != nil {
		return err
	}
	return json.Unmarshal(packBytes, &config)
}

// packIDFor maps an item's drop locations to a UI-facing pack ID via
// data/PackMappings.json's keyword table. Pure and cheap — needs no
// corpus-wide index, so it runs per item with no batch pass required.
func packIDFor(dropLocations []string) string {
	for _, dropLoc := range dropLocations {
		for _, packMap := range config.PackMappings {
			for _, keyword := range packMap.Keywords {
				if strings.Contains(dropLoc, keyword) {
					return packMap.PackID
				}
			}
		}
	}
	return "base"
}

func wikiURLFor(name string) string {
	// Go's url.QueryEscape doesn't escape apostrophes, which wiki links need escaped.
	escapedName := url.QueryEscape(name)
	escapedName = strings.ReplaceAll(escapedName, "'", "%27")
	return fmt.Sprintf("https://ddowiki.com/page/Special:Search?search=%s", escapedName)
}

// EnrichItem transforms an XMLItem into an enriched Item. IsRaid/RaidName are
// NOT set here — see InitEnrichment's doc comment; callers reading from the
// catalog already have IsRaid populated on the source XMLItem.
func EnrichItem(xmlItem models.XMLItem) models.Item {
	item := models.Item{
		Name:          xmlItem.Name,
		Description:   xmlItem.Description,
		MinLevel:      xmlItem.MinLevel,
		DropLocations: xmlItem.DropLocations,
		IsRaid:        xmlItem.IsRaid,
	}

	for _, slot := range xmlItem.EquipmentSlot.Slots {
		item.Slots = append(item.Slots, slot.Local)
	}

	item.PackID = packIDFor(item.DropLocations)
	item.WikiURL = wikiURLFor(item.Name)

	return item
}

// EnrichItemsInPlace batch-enriches every item's PackID/WikiURL. IsRaid comes
// from the catalog already (see InitEnrichment) and is left untouched here.
func EnrichItemsInPlace(items []models.XMLItem) {
	for i := range items {
		item := &items[i]
		item.PackID = packIDFor(item.DropLocations)
		item.WikiURL = wikiURLFor(item.Name)
	}
}
