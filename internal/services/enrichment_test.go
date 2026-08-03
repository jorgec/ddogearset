package services_test

import (
	"encoding/xml"
	"testing"

	"goGearset/internal/models"
	"goGearset/internal/services"
)

func TestEnrichItem_WikiURLAndPackMappingAndRaid(t *testing.T) {
	// Mock config
	mockConfig := models.PackMappingsConfig{
		PackMappings: []struct {
			PackID   string   `json:"pack_id"`
			Keywords []string `json:"keywords"`
		}{
			{PackID: "feywild", Keywords: []string{"Fables of the Feywild"}},
			{PackID: "isle_of_dread", Keywords: []string{"Isle of Dread", "Hunt or Be Hunted"}},
		},
	}
	mockRaids := []string{"Hunt or Be Hunted", "Project Nemesis"}

	// Note to Builder: Provide a way to inject mock config/raids into the Enrichment service for testing.
	// For instance, implement InitEnrichmentForTest in enrichment.go.
	services.InitEnrichmentForTest(mockConfig, mockRaids)

	tests := []struct {
		name             string
		xmlItem          models.XMLItem
		expectedWiki     string
		expectedPack     string
		expectedIsRaid   bool
		expectedRaidName string
	}{
		{
			name: "Raid item with apostrophe in name",
			xmlItem: models.XMLItem{
				Name:          "Attunement's Gaze",
				DropLocations: []string{"Hunt or Be Hunted"},
			},
			expectedWiki:     "https://ddowiki.com/page/Special:Search?search=Attunement%27s+Gaze",
			expectedPack:     "isle_of_dread",
			expectedIsRaid:   true,
			expectedRaidName: "Hunt or Be Hunted",
		},
		{
			name: "Normal pack item",
			xmlItem: models.XMLItem{
				Name:          "Crown of Snow",
				DropLocations: []string{"Fables of the Feywild", "Somewhere else"},
			},
			expectedWiki:     "https://ddowiki.com/page/Special:Search?search=Crown+of+Snow",
			expectedPack:     "feywild",
			expectedIsRaid:   false,
			expectedRaidName: "",
		},
		{
			name: "Fallback to base pack when no match",
			xmlItem: models.XMLItem{
				Name:          "Generic Item",
				DropLocations: []string{"Unknown Location"},
			},
			expectedWiki:     "https://ddowiki.com/page/Special:Search?search=Generic+Item",
			expectedPack:     "base",
			expectedIsRaid:   false,
			expectedRaidName: "",
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
			if enriched.IsRaid != tc.expectedIsRaid {
				t.Errorf("IsRaid: expected %v, got %v", tc.expectedIsRaid, enriched.IsRaid)
			}
			if enriched.RaidName != tc.expectedRaidName {
				t.Errorf("RaidName: expected %s, got %s", tc.expectedRaidName, enriched.RaidName)
			}
		})
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
