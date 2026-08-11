package services

import (
	"encoding/json"
	"fmt"
	"net/url"
	"strings"

	"goGearset/internal/models"
)

var config models.PackMappingsConfig

// InitEnrichmentForTest initializes the enrichment service with mock data for testing
func InitEnrichmentForTest(mockConfig models.PackMappingsConfig) {
	config = mockConfig
}

// InitEnrichment loads pack-mapping configuration from its embedded bytes —
// fatal on failure, since without it no item can be attributed to an
// adventure pack.
//
// Bytes, not a path. It used to be `os.Open(packMappingsPath)` against
// `"data/PackMappings.json"`, resolved against the process's WORKING
// DIRECTORY — which is the repo root under `go run`/`wails dev`, and
// something else entirely once packaged. Confirmed from a real Windows
// install: "Failed to load pack mappings ... The system cannot find the path
// specified." Every item still loaded — the failure is caught and only
// degrades pack attribution — which is exactly why it shipped unnoticed. The
// comment this replaced claimed the path "match[ed] every other bundled
// data-file path in this app"; that was the misconception. The sibling file
// two lines above it in app.go, `data/stat_sets.default.json`, has been
// `go:embed`-ed the whole time — this one just wasn't. Embedding removes the
// failure mode instead of relocating it: there is no path left to resolve
// wrong.
func InitEnrichment(packMappingsJSON []byte) error {
	return json.Unmarshal(packMappingsJSON, &config)
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
