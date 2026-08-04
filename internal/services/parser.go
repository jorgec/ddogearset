package services

import (
	"encoding/xml"
	"os"
	"path/filepath"
	"strings"

	"goGearset/internal/models"
)

// Every parser below is per-file fault tolerant (docs/ITEM_DETAIL_SPEC.md §3.1,
// INV-3). Returning a non-nil error from a filepath.WalkFunc aborts the ENTIRE
// walk, so the previous "return err on xml.Unmarshal failure" behavior meant a
// single malformed file among thousands produced an empty cache and a silently
// empty UI. Content-level failures now land in the returned `skipped` slice and
// the walk continues; the returned error is reserved for genuine filesystem
// problems (directory missing, permission denied).

// walkXMLFiles applies parse to every non-directory file under root whose name
// ends in suffix, collecting the paths of files parse rejected. root may be a
// single file rather than a directory, in which case only that file is
// considered (SetBonuses.xml is a lone file, not a directory).
func walkXMLFiles(root string, suffix string, parse func(path string, data []byte) error) ([]string, error) {
	var skipped []string

	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			// A filesystem-level walk error (permissions, vanished dir) still
			// aborts — that is not an XML-content error.
			return err
		}
		if info.IsDir() || !strings.HasSuffix(info.Name(), suffix) {
			return nil
		}
		bytes, readErr := os.ReadFile(path)
		if readErr != nil {
			skipped = append(skipped, path)
			return nil
		}
		if parseErr := parse(path, bytes); parseErr != nil {
			skipped = append(skipped, path)
			return nil
		}
		return nil
	})

	return skipped, err
}

// ParseItems scans the given directory for .item files, unmarshals them, and
// returns the successfully-parsed items plus the paths of files that failed to
// parse. A failed file never aborts the walk.
func ParseItems(directory string) ([]models.XMLItem, []string, error) {
	var allItems []models.XMLItem

	skipped, err := walkXMLFiles(directory, ".item", func(_ string, bytes []byte) error {
		var data models.XMLItemData
		if err := xml.Unmarshal(bytes, &data); err != nil {
			return err
		}
		allItems = append(allItems, data.Items...)
		return nil
	})

	return allItems, skipped, err
}

// ParseAugments scans the given directory for .xml files and unmarshals them
// into XMLAugment structs.
func ParseAugments(directory string) ([]models.XMLAugment, []string, error) {
	var allAugments []models.XMLAugment

	skipped, err := walkXMLFiles(directory, ".xml", func(_ string, bytes []byte) error {
		var data models.XMLAugmentsData
		if err := xml.Unmarshal(bytes, &data); err != nil {
			return err
		}
		allAugments = append(allAugments, data.Augments...)
		return nil
	})

	return allAugments, skipped, err
}

// ParseFiligrees scans the given directory for .xml files and unmarshals them
// into XMLFiligree structs, injecting each file's set name onto its filigrees.
func ParseFiligrees(directory string) ([]models.XMLFiligree, []string, error) {
	var allFiligrees []models.XMLFiligree

	skipped, err := walkXMLFiles(directory, ".xml", func(_ string, bytes []byte) error {
		var data models.XMLFiligreeData
		if err := xml.Unmarshal(bytes, &data); err != nil {
			return err
		}
		setName := data.SetBonus.Type
		for i := range data.Filigrees {
			data.Filigrees[i].SetName = setName
		}
		allFiligrees = append(allFiligrees, data.Filigrees...)
		return nil
	})

	return allFiligrees, skipped, err
}

// ParseFiligreeSetBonuses returns the inline <SetBonus> block from every
// *.Filigree.xml file under directory, so filigree set tiers render through the
// same panel as item set tiers.
func ParseFiligreeSetBonuses(directory string) ([]models.XMLSetBonus, []string, error) {
	var allSets []models.XMLSetBonus

	skipped, err := walkXMLFiles(directory, ".xml", func(_ string, bytes []byte) error {
		var data models.XMLFiligreeData
		if err := xml.Unmarshal(bytes, &data); err != nil {
			return err
		}
		if data.SetBonus.Type == "" {
			return nil
		}
		allSets = append(allSets, models.XMLSetBonus{
			Type:  data.SetBonus.Type,
			Icon:  data.SetBonus.Icon,
			Tiers: data.SetBonus.Tiers,
		})
		return nil
	})

	return allSets, skipped, err
}

// ParseSetBonuses reads standalone set-bonus definitions. `path` may point
// directly at SetBonuses.xml or at a directory containing it.
func ParseSetBonuses(path string) ([]models.XMLSetBonus, []string, error) {
	var allSets []models.XMLSetBonus

	skipped, err := walkXMLFiles(path, ".xml", func(_ string, bytes []byte) error {
		var data models.XMLSetBonusData
		if err := xml.Unmarshal(bytes, &data); err != nil {
			return err
		}
		allSets = append(allSets, data.SetBonuses...)
		return nil
	})

	return allSets, skipped, err
}
