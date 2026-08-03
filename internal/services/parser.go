package services

import (
	"encoding/xml"
	"io"
	"os"
	"path/filepath"
	"strings"

	"goGearset/internal/models"
)

// ParseItems scans the given directory for .xml files, unmarshals them, and returns a slice of XMLItem
func ParseItems(directory string) ([]models.XMLItem, error) {
	var allItems []models.XMLItem

	err := filepath.Walk(directory, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && strings.HasSuffix(info.Name(), ".item") {
			file, err := os.Open(path)
			if err != nil {
				return err
			}
			defer file.Close()

			bytes, err := io.ReadAll(file)
			if err != nil {
				return err
			}

			var data models.XMLItemData
			if err := xml.Unmarshal(bytes, &data); err != nil {
				return err
			}
			allItems = append(allItems, data.Items...)
		}
		return nil
	})

	return allItems, err
}

// ParseSets scans the given directory for .xml files, unmarshals them, and returns a slice of XMLSet
func ParseSets(directory string) ([]models.XMLSet, error) {
	var allSets []models.XMLSet

	err := filepath.Walk(directory, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && strings.HasSuffix(info.Name(), ".xml") {
			file, err := os.Open(path)
			if err != nil {
				return err
			}
			defer file.Close()

			bytes, err := io.ReadAll(file)
			if err != nil {
				return err
			}

			var data models.XMLSetData
			if err := xml.Unmarshal(bytes, &data); err != nil {
				return err
			}
			allSets = append(allSets, data.Sets...)
		}
		return nil
	})

	return allSets, err
}

// ParseAugments scans the given directory for .xml files and unmarshals them into XMLAugment structs
func ParseAugments(directory string) ([]models.XMLAugment, error) {
	var allAugments []models.XMLAugment

	err := filepath.Walk(directory, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && strings.HasSuffix(info.Name(), ".xml") {
			file, err := os.Open(path)
			if err != nil {
				return err
			}
			defer file.Close()

			bytes, err := io.ReadAll(file)
			if err != nil {
				return err
			}

			var data models.XMLAugmentsData
			if err := xml.Unmarshal(bytes, &data); err != nil {
				return err
			}
			allAugments = append(allAugments, data.Augments...)
		}
		return nil
	})
	if err != nil {
		return nil, err
	}

	return allAugments, nil
}

// ParseFiligrees scans the given directory for .xml files and unmarshals them into XMLFiligree structs
func ParseFiligrees(directory string) ([]models.XMLFiligree, error) {
	var allFiligrees []models.XMLFiligree

	err := filepath.Walk(directory, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && strings.HasSuffix(info.Name(), ".xml") {
			file, err := os.Open(path)
			if err != nil {
				return err
			}
			defer file.Close()

			bytes, err := io.ReadAll(file)
			if err != nil {
				return err
			}

			var data models.XMLFiligreeData
			if err := xml.Unmarshal(bytes, &data); err != nil {
				return err
			}
			
			// Inject SetName into each filigree
			setName := data.SetBonus.Type
			for i := range data.Filigrees {
				data.Filigrees[i].SetName = setName
			}
			
			allFiligrees = append(allFiligrees, data.Filigrees...)
		}
		return nil
	})
	if err != nil {
		return nil, err
	}

	return allFiligrees, nil
}
