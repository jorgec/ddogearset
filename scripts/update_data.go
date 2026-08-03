package main

import (
	"encoding/json"
	"fmt"
	"os"

	"goGearset/internal/models"
	"goGearset/internal/services"
)

func main() {
	err := services.InitEnrichment("data/PackMappings.json", "data/Raids.json")
	if err != nil {
		fmt.Printf("Warning: enrichment init error: %v\n", err)
	}

	xmlItems, err := services.ParseItems("data/ddobuilder/Items")
	if err != nil {
		fmt.Printf("Error parsing items: %v\n", err)
		os.Exit(1)
	}

	xmlSets, err := services.ParseSets("data/ddobuilder/Sets")
	if err != nil {
		fmt.Printf("Error parsing sets: %v\n", err)
		os.Exit(1)
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
		set := models.Set{
			Name:        xmlSet.Name,
			Description: xmlSet.Description,
		}
		appData.Sets = append(appData.Sets, set)
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
