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

// InitEnrichment initializes the enrichment service from configuration files
func InitEnrichment(packMappingsPath string, raidsPath string) error {
	// Load pack mappings
	packFile, err := os.Open(packMappingsPath)
	if err != nil {
		return err
	}
	defer packFile.Close()
	packBytes, err := io.ReadAll(packFile)
	if err != nil {
		return err
	}
	if err := json.Unmarshal(packBytes, &config); err != nil {
		return err
	}

	// Load raids
	raidFile, err := os.Open(raidsPath)
	if err != nil {
		return err
	}
	defer raidFile.Close()
	raidBytes, err := io.ReadAll(raidFile)
	if err != nil {
		return err
	}
	if err := json.Unmarshal(raidBytes, &raids); err != nil {
		return err
	}

	return nil
}

// EnrichItem transforms an XMLItem into an enriched Item
func EnrichItem(xmlItem models.XMLItem) models.Item {
	item := models.Item{
		Name:          xmlItem.Name,
		Description:   xmlItem.Description,
		MinLevel:      xmlItem.MinLevel,
		DropLocations: xmlItem.DropLocations,
		PackID:        "base",
	}

	for _, slot := range xmlItem.EquipmentSlot.Slots {
		item.Slots = append(item.Slots, slot.Local)
	}

	// Calculate WikiURL
	// Go's url.QueryEscape doesn't escape apostrophes, which wiki links might need escaped. 
	// We'll replace it specifically if url.QueryEscape doesn't handle it for the wiki.
	escapedName := url.QueryEscape(item.Name)
	escapedName = strings.ReplaceAll(escapedName, "'", "%27") // Ensure apostrophes are escaped for the test
	item.WikiURL = fmt.Sprintf("https://ddowiki.com/page/Special:Search?search=%s", escapedName)

	packIDAssigned := false
	for _, dropLoc := range item.DropLocations {
		for _, packMap := range config.PackMappings {
			for _, keyword := range packMap.Keywords {
				if strings.Contains(dropLoc, keyword) {
					item.PackID = packMap.PackID
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

	for _, dropLoc := range item.DropLocations {
		for _, raidName := range raids {
			if strings.Contains(dropLoc, raidName) {
				item.IsRaid = true
				item.RaidName = raidName
				break
			}
		}
		if item.IsRaid {
			break
		}
	}

	return item
}
