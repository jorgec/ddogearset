package models

import "encoding/xml"

// ---------------------------------------------------------
// 1. Raw XML Parsing Models
// ---------------------------------------------------------

// XMLItemData represents the root element of an items XML file
type XMLItemData struct {
	XMLName xml.Name  `xml:"Items"`
	Items   []XMLItem `xml:"Item"`
}

// XMLItem represents a single item directly mapped from DDOBuilder XML
type XMLItem struct {
	Name          string           `xml:"Name"`
	Description   string           `xml:"Description"`
	MinLevel      int              `xml:"MinLevel"`
	EquipmentSlot XMLEquipmentSlot `xml:"EquipmentSlot"`
	DropLocations []string         `xml:"DropLocation"`
	ItemAugments  []XMLItemAugment `xml:"ItemAugment"`
	MinorArtifact *string          `xml:"MinorArtifact"`
	RawXML        string           `xml:",innerxml" json:"-"`
}

type XMLItemAugment struct {
	Type string `xml:"Type"`
}

// XMLAugmentsData represents the root element of an augments XML file
type XMLAugmentsData struct {
	XMLName  xml.Name     `xml:"Augments"`
	Augments []XMLAugment `xml:"Augment"`
}

// XMLAugment represents a single augment from DDOBuilder XML
type XMLAugment struct {
	Name        string   `xml:"Name"`
	Description string   `xml:"Description"`
	Types       []string `xml:"Type"`
	MinLevel    int      `xml:"MinLevel"`
	RawXML      string   `xml:",innerxml" json:"-"`
}

type XMLFiligreeData struct {
	XMLName  xml.Name      `xml:"Filigrees"`
	SetBonus XMLSetBonus   `xml:"SetBonus"`
	Filigrees []XMLFiligree `xml:"Filigree"`
}

type XMLSetBonus struct {
	Type string `xml:"Type"`
}

type XMLFiligree struct {
	Name        string `xml:"Name"`
	Description string `xml:"Description"`
	Menu        string `xml:"Menu"`
	SetName     string `json:"SetName"` // Derived from SetBonus
	RawXML      string `xml:",innerxml" json:"-"`
}

// XMLEquipmentSlot dynamically captures child tags (e.g., <Helmet/>, <Ring/>)
type XMLEquipmentSlot struct {
	Slots []xml.Name `xml:",any"`
}

// XMLSetData represents the root element of a sets XML file
type XMLSetData struct {
	XMLName xml.Name `xml:"Sets"`
	Sets    []XMLSet `xml:"Set"`
}

// XMLSet represents a single gear set from DDOBuilder XML
type XMLSet struct {
	Name        string `xml:"Name"`
	Description string `xml:"Description"`
}

// ---------------------------------------------------------
// 2. Enriched Output Models (JSON)
// ---------------------------------------------------------

// Item represents the final, enriched structure served to the application
type Item struct {
	Name          string   `json:"name"`
	Description   string   `json:"description"`
	MinLevel      int      `json:"min_level"`
	Slots         []string `json:"slots"`
	DropLocations []string `json:"drop_locations"`

	// Phase 2 Enriched Data
	PackID   string `json:"pack_id"`
	WikiURL  string `json:"wiki_url"`
	IsRaid   bool   `json:"is_raid"`
	RaidName string `json:"raid_name,omitempty"`
}

// Set represents the finalized Set structure
type Set struct {
	Name        string `json:"name"`
	Description string `json:"description"`
}

// AppData represents the consolidated JSON payload structure
type AppData struct {
	Items []Item `json:"items"`
	Sets  []Set  `json:"sets"`
}

// ---------------------------------------------------------
// 3. Configuration Models
// ---------------------------------------------------------

// PackMappingsConfig maps to data/PackMappings.json
type PackMappingsConfig struct {
	PackMappings []struct {
		PackID   string   `json:"pack_id"`
		Keywords []string `json:"keywords"`
	} `json:"pack_mappings"`
}
