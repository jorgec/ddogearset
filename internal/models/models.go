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

// XMLQuestData represents the root element of Quests.xml.
type XMLQuestData struct {
	XMLName xml.Name   `xml:"Quests"`
	Quests  []XMLQuest `xml:"Quest"`
}

// XMLQuest mirrors a <Quest> element, scoped to only what raid detection
// needs (docs/RAID_DETECTION_SPEC.md) — Quests.xml also carries Patron/
// Favor/Levels/DoNotShow/etc. fields this app has no use for. IsRaid mirrors
// MinorArtifact's presence-only-marker convention below: a non-nil pointer
// means the bare <IsRaid/> element was present, same as Python's
// `quest_node.find('IsRaid') is not None`.
type XMLQuest struct {
	Name          string  `xml:"Name"`
	AdventurePack string  `xml:"AdventurePack"`
	IsRaid        *string `xml:"IsRaid"`
}

// XMLBuff mirrors a <Buff> element verbatim.
//
// Every scalar is a string on purpose (INV-2, docs/ITEM_DETAIL_SPEC.md §2.2):
// a typed int/float field turns a single malformed value in any one of ~8,800
// item files into an xml.Unmarshal failure for that whole file. Display code
// converts at render time; the solver's own (deliberately different) parsing
// lives in python/optimizer.py and is not duplicated here (INV-1).
type XMLBuff struct {
	Type         string `xml:"Type"`
	Item         string `xml:"Item"`
	Description1 string `xml:"Description1"`
	Value1       string `xml:"Value1"`
	Value2       string `xml:"Value2"`
	BonusType    string `xml:"BonusType"`
}

// XMLRequirement mirrors <Requirement> (nested under <Effect><Requirements>).
type XMLRequirement struct {
	Type string `xml:"Type"`
	Item string `xml:"Item"`
}

// XMLEffect mirrors <Effect>. Types is a slice because a single <Effect> may
// repeat <Type> (e.g. MeleePower + Doublestrike sharing one Amount).
type XMLEffect struct {
	Types        []string         `xml:"Type"`
	Bonus        string           `xml:"Bonus"`
	Item         string           `xml:"Item"`
	AType        string           `xml:"AType"`
	Amount       string           `xml:"Amount"`
	Requirements []XMLRequirement `xml:"Requirements>Requirement"`
}

// XMLEmbeddedAugment mirrors <Augment> nested inside <ItemAugment> — an
// item-specific upgrade/crafting choice, distinct from the generic color-slot
// augment system (XMLAugment). SetBonus is populated only when choosing this
// specific augment grants set membership (the "conditional set bonus" case —
// see docs/ITEM_DETAIL_SPEC.md §2.7).
type XMLEmbeddedAugment struct {
	Name         string      `xml:"Name"`
	Description  string      `xml:"Description"`
	MinLevel     string      `xml:"MinLevel"`
	Icon         string      `xml:"Icon"`
	GrantAugment string      `xml:"GrantAugment"`
	SetBonus     string      `xml:"SetBonus"`
	Effects      []XMLEffect `xml:"Effect"`
}

// XMLBaseDice mirrors <BaseDice>. Held by pointer on XMLItem so "no <BaseDice>
// element" is distinguishable from "present but empty".
type XMLBaseDice struct {
	Number string `xml:"Number"`
	Sides  string `xml:"Sides"`
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

	// --- structural projection (docs/ITEM_DETAIL_SPEC.md §2.3) ---
	Icon       string      `xml:"Icon"`
	Material   string      `xml:"Material"`
	SetBonuses []string    `xml:"SetBonus"` // top-level, unconditional set membership
	Buffs      []XMLBuff   `xml:"Buff"`
	Effects    []XMLEffect `xml:"Effect"` // item-level clickies/SLAs

	// --- weapon profile (meaningful only when Weapon != "") ---
	Weapon              string       `xml:"Weapon"`
	AttackModifier      string       `xml:"AttackModifier"`
	DamageModifier      string       `xml:"DamageModifier"`
	DRBypass            []string     `xml:"DRBypass"`
	WeaponDamage        string       `xml:"WeaponDamage"`
	BaseDice            *XMLBaseDice `xml:"BaseDice"`
	CriticalMultiplier  string       `xml:"CriticalMultiplier"`
	CriticalThreatRange string       `xml:"CriticalThreatRange"`

	// --- armor profile (meaningful only when Armor != "") ---
	Armor                 string `xml:"Armor"`
	ArmorBonus            string `xml:"ArmorBonus"`
	ShieldBonus           string `xml:"ShieldBonus"`
	MaximumDexterityBonus string `xml:"MaximumDexterityBonus"`
	ArcaneSpellFailure    string `xml:"ArcaneSpellFailure"`
	ArmorCheckPenalty     string `xml:"ArmorCheckPenalty"`

	// --- acquisition enrichment: computed once at cache-load time by
	// services.EnrichItemInPlace, never parsed from this item's own XML ---
	PackID   string `xml:"-" json:"pack_id,omitempty"`
	WikiURL  string `xml:"-" json:"wiki_url,omitempty"`
	IsRaid   bool   `xml:"-" json:"is_raid,omitempty"`
	RaidName string `xml:"-" json:"raid_name,omitempty"`
}

type XMLItemAugment struct {
	Type string `xml:"Type"` // color/slot type

	SelectedAugment    string               `xml:"SelectedAugment"` // default choice, when present
	SelectedLevelIndex string               `xml:"SelectedLevelIndex"`
	Augments           []XMLEmbeddedAugment `xml:"Augment"` // embedded upgrade/crafting choices
}

// XMLAugmentsData represents the root element of an augments XML file
type XMLAugmentsData struct {
	XMLName  xml.Name     `xml:"Augments"`
	Augments []XMLAugment `xml:"Augment"`
}

// XMLAugment represents a single augment from DDOBuilder XML
type XMLAugment struct {
	Name        string      `xml:"Name"`
	Description string      `xml:"Description"`
	Types       []string    `xml:"Type"`
	MinLevel    int         `xml:"MinLevel"`
	Effects     []XMLEffect `xml:"Effect"`
	RawXML      string      `xml:",innerxml" json:"-"`
}

type XMLFiligreeData struct {
	XMLName   xml.Name          `xml:"Filigrees"`
	SetBonus  XMLFiligreeSetRef `xml:"SetBonus"`
	Filigrees []XMLFiligree     `xml:"Filigree"`
}

// XMLFiligreeSetRef is the inline <SetBonus> block inside a *.Filigree.xml
// file's root — distinct from the standalone SetBonuses.xml entries
// (XMLSetBonus), which is why it is a separate type rather than a shared one.
type XMLFiligreeSetRef struct {
	Type  string       `xml:"Type"`
	Icon  string       `xml:"Icon"`
	Tiers []XMLSetTier `xml:"Buff"`
}

type XMLFiligree struct {
	Name        string      `xml:"Name"`
	Description string      `xml:"Description"`
	Menu        string      `xml:"Menu"`
	SetName     string      `json:"SetName"` // Derived from SetBonus
	Effects     []XMLEffect `xml:"Effect"`   // retains <Rare>-tagged effects for display
	RawXML      string      `xml:",innerxml" json:"-"`
}

// XMLEquipmentSlot dynamically captures child tags (e.g., <Helmet/>, <Ring/>)
type XMLEquipmentSlot struct {
	Slots []xml.Name `xml:",any"`
}

// XMLSetBonusData represents the root element of SetBonuses.xml.
//
// This replaces the former XMLSetData/XMLSet pair, which targeted a <Sets><Set>
// shape that does not exist in the DDOBuilder data files and had no callers.
type XMLSetBonusData struct {
	XMLName    xml.Name      `xml:"SetBonuses"`
	SetBonuses []XMLSetBonus `xml:"SetBonus"`
}

// XMLSetBonus is one named gear set and its per-piece-count tiers.
type XMLSetBonus struct {
	Type  string       `xml:"Type"`
	Icon  string       `xml:"Icon"`
	Tiers []XMLSetTier `xml:"Buff"`
}

// XMLSetTier is one <Buff> under a set bonus: what you get at EquippedCount
// pieces. Description is DDOBuilder's own ready-made human text.
type XMLSetTier struct {
	EquippedCount string      `xml:"EquippedCount"`
	Description   string      `xml:"Description"`
	Effects       []XMLEffect `xml:"Effect"`
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
