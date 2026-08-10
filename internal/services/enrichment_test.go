package services_test

import (
	"encoding/xml"
	"testing"

	"goGearset/internal/models"
	"goGearset/internal/services"
)

// Raid-detection tests (upgrade-chain walk, ingredient cross-reference) were
// removed along with the Go-side chain walker they covered — raid detection
// now comes from the catalog's precomputed is_raid column (Phase 5,
// docs/0.5.0/00_ETL_START_HERE.md), verified against Python's identical walk
// in Phase 4. What remains here is PackID/WikiURL attribution, which is still
// Go-side, UI-only logic.
func TestEnrichItem_WikiURLAndPackMapping(t *testing.T) {
	mockConfig := models.PackMappingsConfig{
		PackMappings: []struct {
			PackID   string   `json:"pack_id"`
			Keywords []string `json:"keywords"`
		}{
			{PackID: "feywild", Keywords: []string{"Fables of the Feywild"}},
			{PackID: "isle_of_dread", Keywords: []string{"Isle of Dread", "Hunt or Be Hunted"}},
		},
	}
	services.InitEnrichmentForTest(mockConfig)

	tests := []struct {
		name         string
		xmlItem      models.XMLItem
		expectedWiki string
		expectedPack string
	}{
		{
			name: "Item with apostrophe in name",
			xmlItem: models.XMLItem{
				Name:          "Attunement's Gaze",
				DropLocations: []string{"Hunt or Be Hunted"},
			},
			expectedWiki: "https://ddowiki.com/page/Special:Search?search=Attunement%27s+Gaze",
			expectedPack: "isle_of_dread",
		},
		{
			name: "Normal pack item",
			xmlItem: models.XMLItem{
				Name:          "Crown of Snow",
				DropLocations: []string{"Fables of the Feywild", "Somewhere else"},
			},
			expectedWiki: "https://ddowiki.com/page/Special:Search?search=Crown+of+Snow",
			expectedPack: "feywild",
		},
		{
			name: "Fallback to base pack when no match",
			xmlItem: models.XMLItem{
				Name:          "Generic Item",
				DropLocations: []string{"Unknown Location"},
			},
			expectedWiki: "https://ddowiki.com/page/Special:Search?search=Generic+Item",
			expectedPack: "base",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			enriched := services.EnrichItem(tc.xmlItem)
			if enriched.WikiURL != tc.expectedWiki {
				t.Errorf("WikiURL: expected %s, got %s", tc.expectedWiki, enriched.WikiURL)
			}
			if enriched.PackID != tc.expectedPack {
				t.Errorf("PackID: expected %s, got %s", tc.expectedPack, enriched.PackID)
			}
		})
	}
}

// EnrichItem no longer computes IsRaid itself; it passes through whatever the
// caller already set on the source XMLItem (the catalog, in the live app).
func TestEnrichItem_PassesThroughIsRaid(t *testing.T) {
	services.InitEnrichmentForTest(models.PackMappingsConfig{})

	raid := services.EnrichItem(models.XMLItem{Name: "A Raid Item", IsRaid: true})
	if !raid.IsRaid {
		t.Errorf("expected IsRaid true to pass through, got false")
	}

	nonRaid := services.EnrichItem(models.XMLItem{Name: "A Normal Item", IsRaid: false})
	if nonRaid.IsRaid {
		t.Errorf("expected IsRaid false to pass through, got true")
	}
}

func TestEnrichItem_SlotConversion(t *testing.T) {
	xmlItem := models.XMLItem{
		Name: "Test Helmet",
		EquipmentSlot: models.XMLEquipmentSlot{
			Slots: []xml.Name{
				{Local: "Helmet"},
				{Local: "CosmeticHelm"},
			},
		},
	}

	enriched := services.EnrichItem(xmlItem)

	if len(enriched.Slots) != 2 {
		t.Fatalf("Expected 2 slots, got %d", len(enriched.Slots))
	}
	if enriched.Slots[0] != "Helmet" || enriched.Slots[1] != "CosmeticHelm" {
		t.Errorf("Expected slots [Helmet, CosmeticHelm], got %v", enriched.Slots)
	}
}
