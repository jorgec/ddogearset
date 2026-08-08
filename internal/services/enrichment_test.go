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

// TestEnrichItemsInPlace_UpgradeChain reproduces the real-data chain from
// docs/RAID_DETECTION_SPEC.md: a direct raid item, an "Epic version of X"
// upgrade, a "Legendary version of Epic X" upgrade chaining one more hop,
// and a "Perfected" tier whose DropLocation has zero textual link to any of
// the above (only the shared name suffix links it — Signal B).
func TestEnrichItemsInPlace_UpgradeChain(t *testing.T) {
	services.InitEnrichmentForTest(models.PackMappingsConfig{}, []string{"Zawabi's Revenge"})

	items := []models.XMLItem{
		{Name: "Torc of Prince Raiyum-de II", DropLocations: []string{"Zawabi's Revenge, warded chest"}},
		{Name: "Epic Torc of Prince Raiyum-de II", DropLocations: []string{"Epic version of Torc of Prince Raiyum-de II"}},
		{Name: "Legendary Torc of Prince Raiyum-de II", DropLocations: []string{"Legendary version of Epic Torc of Prince Raiyum-de II"}},
		{Name: "Perfected Torc of Prince Raiyum-de II", DropLocations: []string{"Lahar, Turn in Nebula Fragment"}},
	}

	services.EnrichItemsInPlace(items)

	for _, it := range items {
		if !it.IsRaid {
			t.Errorf("%s: expected IsRaid true, got false", it.Name)
		}
		if it.RaidName != "Zawabi's Revenge" {
			t.Errorf("%s: expected RaidName %q, got %q", it.Name, "Zawabi's Revenge", it.RaidName)
		}
	}
}

// TestEnrichItemsInPlace_CraftedFromNonRaidIngredientStaysFalse guards
// against a false positive: a catalyst-crafted item whose real ingredient is
// a non-raid quest reward must resolve false, not get swept in just for
// sharing crafting-keyword DropLocation text with unrelated raid items.
func TestEnrichItemsInPlace_CraftedFromNonRaidIngredientStaysFalse(t *testing.T) {
	services.InitEnrichmentForTest(models.PackMappingsConfig{}, []string{"Zawabi's Revenge"})

	items := []models.XMLItem{
		{Name: "Drow Longsword of the Weapon Master", DropLocations: []string{"The House of Rusted Blades, End Chest"}},
		{
			Name: "Perfected Longsword of the Weapon Master",
			DropLocations: []string{"Catalyst Crafting, Turn in Drow Longsword of the Weapon Master, " +
				"the Weapon Master Abyssal Catalyst and 50 Abyssal Gems at the Strange Catalyst Forge"},
		},
	}

	services.EnrichItemsInPlace(items)

	if items[1].IsRaid {
		t.Errorf("expected Perfected Longsword of the Weapon Master IsRaid false, got true (raidName=%q)", items[1].RaidName)
	}
}

// TestEnrichItemsInPlace_MultiIngredientCombine covers the "Cauldron of Sora
// Katra, Upgraded version of X and Y" phrasing — two ingredients joined by
// "and", either of which being a raid item should propagate.
func TestEnrichItemsInPlace_MultiIngredientCombine(t *testing.T) {
	services.InitEnrichmentForTest(models.PackMappingsConfig{}, []string{"Defiler of the Just"})

	items := []models.XMLItem{
		{Name: "Blade of Fury", DropLocations: []string{"Some ordinary quest, end chest"}},
		{Name: "Hooked Blade", DropLocations: []string{"Defiler of the Just, Warded chest"}},
		{
			Name:          "Fused Blade",
			DropLocations: []string{"Cauldron of Sora Katra, Upgraded version of Blade of Fury and Hooked Blade"},
		},
	}

	services.EnrichItemsInPlace(items)

	if !items[2].IsRaid {
		t.Errorf("expected Fused Blade IsRaid true (via Hooked Blade), got false")
	}
	if items[2].RaidName != "Defiler of the Just" {
		t.Errorf("expected RaidName %q, got %q", "Defiler of the Just", items[2].RaidName)
	}
}
