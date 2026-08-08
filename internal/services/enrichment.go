package services

import (
	"encoding/json"
	"fmt"
	"io"
	"net/url"
	"os"
	"regexp"
	"strings"

	"goGearset/internal/models"
)

var config models.PackMappingsConfig
var raidNames []string

// InitEnrichmentForTest initializes the enrichment service with mock data for testing
func InitEnrichmentForTest(mockConfig models.PackMappingsConfig, mockRaids []string) {
	config = mockConfig
	raidNames = mockRaids
}

// InitEnrichment initializes the enrichment service from configuration files.
//
// Pack-mapping load failure is fatal (returned as an error) — without it no
// item can be attributed to an adventure pack. `quests` is the parsed
// Quests.xml data (docs/RAID_DETECTION_SPEC.md) — raid names are extracted
// from whichever quests carry a bare <IsRaid/> marker. There is no longer a
// separately-maintained raids data file to fail to load: DDOBuilderV2's own
// Quests.xml (already fetched/kept current by this app) is the raid list,
// verified to match DDO wiki's "Raids" page exactly (41/41). A malformed or
// missing Quests.xml is handled by the caller the same way as any other
// per-file parse failure (ParseQuests' fault-tolerant walk) — this function
// simply gets an empty `quests` slice in that case and reports zero raids.
//
// Returns (raidCount, error) — raidCount lets the caller log how many raids
// were actually recognized, in place of the old "raids loaded at all" bool.
func InitEnrichment(packMappingsPath string, quests []models.XMLQuest) (int, error) {
	// Load pack mappings — fatal on failure.
	packFile, err := os.Open(packMappingsPath)
	if err != nil {
		return 0, err
	}
	defer packFile.Close()
	packBytes, err := io.ReadAll(packFile)
	if err != nil {
		return 0, err
	}
	if err := json.Unmarshal(packBytes, &config); err != nil {
		return 0, err
	}

	raidNames = nil
	for _, q := range quests {
		if q.IsRaid != nil && q.Name != "" {
			raidNames = append(raidNames, q.Name)
		}
	}
	return len(raidNames), nil
}

// --- Raid detection (docs/RAID_DETECTION_SPEC.md) --------------------------
//
// Mirrors python/optimizer.py's _raid_ingredient_names/_resolve_is_raid —
// same two-signal design, same confirmed prefix/keyword lists. See that
// file's comments for the full rationale; kept in sync deliberately (not
// factored into one shared implementation — Go and Python already parse the
// same DDOBuilderV2 corpus independently throughout this codebase).

// Confirmed real tier-quality prefixes that share a base item's exact name
// once stripped (verified against the corpus — see optimizer.py's
// RAID_UPGRADE_TIER_PREFIXES comment for the exact hit-rate numbers).
var raidUpgradeTierPrefixes = []string{"Epic ", "Legendary ", "Mythic ", "Perfected ", "Elite "}

// Scoping keywords for the looser ingredient-name cross-reference (needed
// for catalyst-crafted items whose ingredient name doesn't follow "version
// of" phrasing or a tier-prefix relationship at all).
var raidCraftingKeywords = []string{"turn in", "catalyst", "crafting"}

// A candidate ingredient name shorter than this is more likely to
// false-positive-match as a substring of unrelated text than to be a
// genuine ingredient reference.
const raidMinIngredientNameLen = 8

var raidVersionOfRe = regexp.MustCompile(`(?i)(?:upgraded )?version of\s+(.+)`)
var raidParenSuffixRe = regexp.MustCompile(`\s*\([^)]*\)\s*$`)
var raidAndPlusSplitRe = regexp.MustCompile(`\s+and\s+|\s*\+\s*`)

// raidIngredientNames returns the set of other item names this item's raid
// status should be inherited from. `allDropLocations` is the full corpus
// name->DropLocation index, for cross-referencing.
func raidIngredientNames(name, dropLocation string, allDropLocations map[string]string) map[string]bool {
	found := make(map[string]bool)

	// Signal A — "<Tier> version of <Name>[ and <Name2>]" phrasing.
	if m := raidVersionOfRe.FindStringSubmatch(dropLocation); m != nil {
		tail := strings.TrimSpace(raidParenSuffixRe.ReplaceAllString(strings.TrimSpace(m[1]), ""))
		for _, part := range raidAndPlusSplitRe.Split(tail, -1) {
			part = strings.TrimSuffix(strings.TrimSpace(part), ".")
			if _, ok := allDropLocations[part]; ok {
				found[part] = true
			}
		}
	}

	// Signal A (cont.) — looser ingredient cross-reference for catalyst-
	// crafted items, scoped to crafting-flavored DropLocation text only.
	dlLower := strings.ToLower(dropLocation)
	hasCraftingKeyword := false
	for _, kw := range raidCraftingKeywords {
		if strings.Contains(dlLower, kw) {
			hasCraftingKeyword = true
			break
		}
	}
	if hasCraftingKeyword {
		for candidate := range allDropLocations {
			if candidate != name && len(candidate) >= raidMinIngredientNameLen && strings.Contains(dropLocation, candidate) {
				found[candidate] = true
			}
		}
	}

	// Signal B — tier-prefix name stripping.
	for _, prefix := range raidUpgradeTierPrefixes {
		if strings.HasPrefix(name, prefix) {
			remainder := name[len(prefix):]
			if _, ok := allDropLocations[remainder]; ok {
				found[remainder] = true
			}
		}
	}

	delete(found, name)
	return found
}

type raidMemoEntry struct {
	isRaid   bool
	raidName string
}

// directRaidMatch is the plain, corpus-independent check: does any of this
// item's own DropLocations name a real raid quest.
func directRaidMatch(dropLocations []string) (bool, string) {
	for _, dropLoc := range dropLocations {
		for _, rn := range raidNames {
			if strings.Contains(dropLoc, rn) {
				return true, rn
			}
		}
	}
	return false, ""
}

// resolveIsRaidChain is the memoized graph walk: true if `name` is sourced
// from a real raid directly, OR any of its upgrade/crafting ingredients
// (transitively) are. `memo` also doubles as a cycle guard — seeded false
// before recursing, so a (theoretical, never observed) cycle resolves to
// false rather than infinite-looping.
func resolveIsRaidChain(name string, dropLocations []string, allDropLocations map[string]string, memo map[string]raidMemoEntry) (bool, string) {
	if e, ok := memo[name]; ok {
		return e.isRaid, e.raidName
	}
	memo[name] = raidMemoEntry{}

	if isRaid, rn := directRaidMatch(dropLocations); isRaid {
		memo[name] = raidMemoEntry{true, rn}
		return true, rn
	}

	dl := strings.Join(dropLocations, "; ")
	for ingredient := range raidIngredientNames(name, dl, allDropLocations) {
		ingredientDL := allDropLocations[ingredient]
		if isRaid, rn := resolveIsRaidChain(ingredient, []string{ingredientDL}, allDropLocations, memo); isRaid {
			memo[name] = raidMemoEntry{true, rn}
			return true, rn
		}
	}
	return false, ""
}

// packIDFor and wikiURLFor are the two acquisitionFor sub-computations that
// don't need the raid corpus index — shared by both the simple
// (EnrichItem/EnrichItemInPlace) and chain-aware (EnrichItemsInPlace) paths.
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

// acquisitionFor computes the pack/wiki/raid attribution for an item name and
// its drop locations. Single source of truth shared by EnrichItem (which builds
// a separate models.Item) and EnrichItemInPlace (which annotates an XMLItem),
// so the two can never drift apart. This is the corpus-independent, direct-
// match-only path — see EnrichItemsInPlace for upgrade-chain resolution.
func acquisitionFor(name string, dropLocations []string) (packID, wikiURL string, isRaid bool, raidName string) {
	packID = packIDFor(dropLocations)
	wikiURL = wikiURLFor(name)
	isRaid, raidName = directRaidMatch(dropLocations)
	return
}

// EnrichItem transforms an XMLItem into an enriched Item
func EnrichItem(xmlItem models.XMLItem) models.Item {
	item := models.Item{
		Name:          xmlItem.Name,
		Description:   xmlItem.Description,
		MinLevel:      xmlItem.MinLevel,
		DropLocations: xmlItem.DropLocations,
	}

	for _, slot := range xmlItem.EquipmentSlot.Slots {
		item.Slots = append(item.Slots, slot.Local)
	}

	item.PackID, item.WikiURL, item.IsRaid, item.RaidName = acquisitionFor(item.Name, item.DropLocations)

	return item
}

// EnrichItemInPlace annotates an XMLItem with its acquisition metadata. Called
// once per item at cache-load time (not per request), so GetItemDetails can
// return a fully-populated item with no extra RPC and no extra frontend type.
//
// Direct-match raid detection only (no upgrade-chain resolution) — this
// function has no view of the rest of the corpus needed to walk a chain.
// The live app uses EnrichItemsInPlace instead; this stays available for
// isolated single-item enrichment (tests, tooling) where the full corpus
// index isn't worth building.
func EnrichItemInPlace(item *models.XMLItem) {
	if item == nil {
		return
	}
	item.PackID, item.WikiURL, item.IsRaid, item.RaidName = acquisitionFor(item.Name, item.DropLocations)
}

// EnrichItemsInPlace batch-enriches every item, resolving raid status
// through upgrade/crafting chains (docs/RAID_DETECTION_SPEC.md) — e.g.
// Legendary Torc of Prince Raiyum-de II ← Epic Torc of Prince Raiyum-de II ←
// Torc of Prince Raiyum-de II, a real Zawabi's Revenge raid item. Unlike
// EnrichItemInPlace, this builds a name->DropLocation index across the WHOLE
// slice first, since an upgrade chain's base item is often below any single
// request's ML floor and wouldn't otherwise be visible. Call once per
// cache-load pass (startup / UpdateExternalSources), not per item/request.
func EnrichItemsInPlace(items []models.XMLItem) {
	allDropLocations := make(map[string]string, len(items))
	for i := range items {
		allDropLocations[items[i].Name] = strings.Join(items[i].DropLocations, "; ")
	}

	memo := make(map[string]raidMemoEntry, len(items))
	for i := range items {
		item := &items[i]
		item.PackID = packIDFor(item.DropLocations)
		item.WikiURL = wikiURLFor(item.Name)
		item.IsRaid, item.RaidName = resolveIsRaidChain(item.Name, item.DropLocations, allDropLocations, memo)
	}
}
