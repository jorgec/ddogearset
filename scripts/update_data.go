package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"goGearset/internal/models"
	"goGearset/internal/services"
)

func main() {
	raidsLoaded, err := services.InitEnrichment("data/PackMappings.json", "data/Raids.json")
	if err != nil {
		fmt.Printf("Warning: enrichment init error: %v\n", err)
	}
	if !raidsLoaded {
		fmt.Println("Note: no raids data source loaded — raid detection is disabled.")
	}

	xmlItems, skippedItems, err := services.ParseItems("data/ddobuilder/Items")
	if err != nil {
		fmt.Printf("Error parsing items: %v\n", err)
		os.Exit(1)
	}
	if len(skippedItems) > 0 {
		fmt.Printf("Skipped %d unparseable item files.\n", len(skippedItems))
	}

	xmlSets, skippedSets, err := services.ParseSetBonuses("data/ddobuilder/SetBonuses.xml")
	if err != nil {
		fmt.Printf("Error parsing set bonuses: %v\n", err)
		os.Exit(1)
	}
	if len(skippedSets) > 0 {
		fmt.Printf("Skipped %d unparseable set-bonus files.\n", len(skippedSets))
	}

	appData := models.AppData{
		Items: make([]models.Item, 0, len(xmlItems)),
		Sets:  make([]models.Set, 0, len(xmlSets)),
	}

	for _, xmlItem := range xmlItems {
		item := services.EnrichItem(xmlItem)
		appData.Items = append(appData.Items, item)
	}

	for _, xmlSet := range xmlSets {
		descriptions := make([]string, 0, len(xmlSet.Tiers))
		for _, tier := range xmlSet.Tiers {
			descriptions = append(descriptions, fmt.Sprintf("%s pieces: %s", tier.EquippedCount, tier.Description))
		}
		appData.Sets = append(appData.Sets, models.Set{
			Name:        xmlSet.Type,
			Description: strings.Join(descriptions, "\n"),
		})
	}

	outputBytes, err := json.MarshalIndent(appData, "", "  ")
	if err != nil {
		fmt.Printf("Error marshaling output: %v\n", err)
		os.Exit(1)
	}

	err = os.MkdirAll("data", 0755)
	if err != nil {
		fmt.Printf("Error creating data directory: %v\n", err)
		os.Exit(1)
	}

	err = os.WriteFile("data/app_data.json", outputBytes, 0644)
	if err != nil {
		fmt.Printf("Error writing output file: %v\n", err)
		os.Exit(1)
	}

	fmt.Println("Successfully generated data/app_data.json")
}
