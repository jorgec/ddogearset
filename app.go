package main

import (
	"bufio"
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"goGearset/internal/models"
	"goGearset/internal/services"
)

//go:embed python/dist/solver
var solverBinary []byte

// App struct
type App struct {
	ctx        context.Context
	logs       []string
	solverPath    string
	itemsCache     []models.XMLItem
	augmentsCache  []models.XMLAugment
	filigreesCache []models.XMLFiligree
	initOnce       sync.Once
}

// NewApp creates a new App application struct
func NewApp() *App {
	return &App{
		logs: []string{},
	}
}

// startup is called when the app starts. The context is saved
// so we can call the runtime methods
func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	a.logs = make([]string, 0)
	
	// Load item cache for UI dropdowns
	go func() {
		items, err := services.ParseItems("/Users/jorgecosgayon/dev/ddo/DDOBuilderV2/Output/DataFiles/Items")
		if err == nil {
			a.itemsCache = items
			a.addLog(fmt.Sprintf("Cached %d items for Gearset Editor", len(items)))
		} else {
			a.addLog("Failed to cache items: " + err.Error())
		}
		
		augments, errAugs := services.ParseAugments("/Users/jorgecosgayon/dev/ddo/DDOBuilderV2/Output/DataFiles/Augments")
		if errAugs == nil {
			a.augmentsCache = augments
			a.addLog(fmt.Sprintf("Cached %d augments for Gearset Editor", len(augments)))
		} else {
			a.addLog("Failed to cache augments: " + errAugs.Error())
		}
		
		filigrees, errFils := services.ParseFiligrees("/Users/jorgecosgayon/dev/ddo/DDOBuilderV2/Output/DataFiles/FiligreeSets")
		if errFils == nil {
			a.filigreesCache = filigrees
			a.addLog(fmt.Sprintf("Cached %d filigrees for Gearset Editor", len(filigrees)))
		} else {
			a.addLog("Failed to cache filigrees: " + errFils.Error())
		}
	}()

	a.initOnce.Do(func() {
		if err := a.extractSolver(); err != nil {
			a.addLog("Warning: failed to extract bundled solver: " + err.Error())
		}
	})
}

// extractSolver writes the embedded solver binary to a temp path and makes it executable.
func (a *App) extractSolver() error {
	tmpDir, err := os.MkdirTemp("", "ddo-solver-*")
	if err != nil {
		return err
	}
	solverPath := filepath.Join(tmpDir, "solver")
	if err := os.WriteFile(solverPath, solverBinary, 0755); err != nil {
		return err
	}
	a.solverPath = solverPath
	a.addLog(fmt.Sprintf("Solver extracted to %s", solverPath))
	return nil
}

type OptimizationPayload struct {
	GearsetName                string              `json:"gearset_name"`
	MaxLevel                   int                 `json:"max_level"`
	BuildType                  string              `json:"build_type"`
	WeaponStyle                string              `json:"weapon_style"`
	Swashbuckling              bool                `json:"swashbuckling"`
	OffhandStyle               string              `json:"offhand_style"`
	CasterSpellpowers          []string            `json:"caster_spellpowers"`
	CasterSchools              []string            `json:"caster_schools"`
	StatPriorities             map[string]int      `json:"stat_priorities"`
	ArmorRestriction           string              `json:"armor_restriction"`
	ReservedMinorArtifactSlot  string              `json:"reserved_minor_artifact_slot"`
	MinorArtifactFiligreeSlots int                 `json:"minor_artifact_filigree_slots"`
	ExcludeGemOfManyFacets     bool                `json:"exclude_gem_of_many_facets"`
	RunearmUse                 bool                `json:"runearm_use"`
	ExcludedPacks              []string            `json:"excluded_packs"`
	RaidItemLimit              int                 `json:"raid_item_limit"`
	IsDinoArtifact             bool                `json:"is_dino_artifact"`
	OutputFilename             string              `json:"output_filename"`
	PreEquipped                map[string]string   `json:"pre_equipped"`
	PreFilledAugments          map[string][]string `json:"pre_filled_augments"`
	PreFilledFiligrees         map[string][]string `json:"pre_filled_filigrees"`
	CalculateOnly              bool                `json:"calculate_only"`
}

type ResultPayload struct {
	Success       bool                   `json:"success"`
	TimeTaken     float64                `json:"timeTaken"`
	GearSet       map[string]interface{} `json:"gearSet"`
	RealizedStats map[string]interface{} `json:"realizedStats,omitempty"`
	ActiveSets    []string               `json:"activeSets,omitempty"`
	Filigrees     map[string][]string    `json:"filigrees,omitempty"`
	AllEffects    map[string]interface{} `json:"allEffects,omitempty"`
	ErrorMessage  string                 `json:"errorMessage,omitempty"`
}

func (a *App) addLog(msg string) {
	a.logs = append(a.logs, msg)
}

// ParseMetadata triggers the Phase 2 XML parsing logic.
func (a *App) ParseMetadata(filePath string) error {
	a.addLog(fmt.Sprintf("Parsing metadata from %s...", filePath))
	// Mock implementation
	a.addLog("Successfully parsed metadata.")
	return nil
}

// RunOptimization triggers the bundled solver binary with the given payload.
func (a *App) RunOptimization(config OptimizationPayload) (ResultPayload, error) {
	if a.solverPath == "" {
		err := a.extractSolver()
		if err != nil {
			return ResultPayload{Success: false, ErrorMessage: "Solver not available: " + err.Error()}, err
		}
	}

	a.addLog("Serializing payload...")
	payloadBytes, err := json.Marshal(config)
	if err != nil {
		return ResultPayload{Success: false, ErrorMessage: err.Error()}, err
	}
	tmpFile := filepath.Join(os.TempDir(), "ddo_payload.json")
	if err := os.WriteFile(tmpFile, payloadBytes, 0644); err != nil {
		return ResultPayload{Success: false, ErrorMessage: err.Error()}, err
	}

	a.addLog("Invoking solver...")
	cmd := exec.Command(a.solverPath, tmpFile)
	stdout, _ := cmd.StdoutPipe()
	cmd.Stderr = cmd.Stdout

	if err := cmd.Start(); err != nil {
		return ResultPayload{Success: false, ErrorMessage: err.Error()}, err
	}
	var richResult ResultPayload
	scanner := bufio.NewScanner(stdout)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "JSON_RESULT:") {
			jsonStr := strings.TrimPrefix(line, "JSON_RESULT:")
			json.Unmarshal([]byte(jsonStr), &richResult)
		} else {
			a.addLog(line)
		}
	}
	if err := cmd.Wait(); err != nil {
		a.addLog("Solver exited with error: " + err.Error())
		return ResultPayload{Success: false, ErrorMessage: err.Error()}, err
	}
	a.addLog("Solver completed successfully.")
	
	richResult.Success = true
	richResult.TimeTaken = 0
	return richResult, nil
}

// GetSystemLogs retrieves real-time execution logs.
func (a *App) GetSystemLogs() []string {
	return a.logs
}

// GetAvailableItems returns items for a given slot, maxLevel, and artifact filter
func (a *App) GetAvailableItems(slot string, maxLevel int, searchTerm string) []models.XMLItem {
	results := make([]models.XMLItem, 0)
	minLvl := maxLevel - 6
	searchTermLower := strings.ToLower(searchTerm)
	for _, item := range a.itemsCache {
		if item.MinLevel >= minLvl && item.MinLevel <= maxLevel {
			for _, s := range item.EquipmentSlot.Slots {
				slotName := s.Local
				if slotName == slot || (slot == "Ring_1" && slotName == "Ring") || (slot == "Ring_2" && slotName == "Ring") {
					if searchTermLower == "" || strings.Contains(strings.ToLower(item.Name), searchTermLower) || strings.Contains(strings.ToLower(item.RawXML), searchTermLower) {
						results = append(results, item)
					}
					break
				}
			}
		}
	}
	
	sort.Slice(results, func(i, j int) bool {
		return results[i].MinLevel > results[j].MinLevel
	})
	
	return results
}

// GetItemDetails returns the full XMLItem for a given item name
func (a *App) GetItemDetails(itemName string) models.XMLItem {
	for _, item := range a.itemsCache {
		if item.Name == itemName {
			return item
		}
	}
	return models.XMLItem{}
}

// GetAvailableAugments returns augments matching a given slot type (e.g. Green), maxLevel, and search term
func (a *App) GetAvailableAugments(slotType string, maxLevel int, searchTerm string) []models.XMLAugment {
	results := make([]models.XMLAugment, 0)
	searchTermLower := strings.ToLower(searchTerm)
	
	// DDO Rules mapping - green takes yellow or blue, purple takes clear or blue, etc.
	// But in DDOBuilder, augments specify which types they can fit into via multiple <Type> elements!
	// E.g. <Type>Blue</Type>, <Type>Green</Type>
	
	for _, aug := range a.augmentsCache {
		if aug.MinLevel <= maxLevel {
			matchType := false
			for _, t := range aug.Types {
				if t == slotType {
					matchType = true
					break
				}
			}
			
			if matchType {
				if searchTermLower == "" || strings.Contains(strings.ToLower(aug.Name), searchTermLower) || strings.Contains(strings.ToLower(aug.RawXML), searchTermLower) {
					results = append(results, aug)
				}
			}
		}
	}
	
	sort.Slice(results, func(i, j int) bool {
		return results[i].MinLevel > results[j].MinLevel
	})
	
	return results
}

// GetAvailableFiligrees returns filigrees matching a search term (by Name, Menu, or SetName)
func (a *App) GetAvailableFiligrees(searchTerm string) []models.XMLFiligree {
	results := make([]models.XMLFiligree, 0)
	searchTermLower := strings.ToLower(searchTerm)
	
	for _, fil := range a.filigreesCache {
		if searchTermLower == "" || 
			strings.Contains(strings.ToLower(fil.Name), searchTermLower) || 
			strings.Contains(strings.ToLower(fil.SetName), searchTermLower) ||
			strings.Contains(strings.ToLower(fil.Menu), searchTermLower) ||
			strings.Contains(strings.ToLower(fil.RawXML), searchTermLower) {
			results = append(results, fil)
		}
	}
	
	sort.Slice(results, func(i, j int) bool {
		return results[i].Name < results[j].Name
	})
	
	return results
}

// UpdateExternalSources runs a git pull on the DDOBuilderV2 repo and reloads the cache
func (a *App) UpdateExternalSources() (string, error) {
	a.addLog("Updating external sources from DDOBuilderV2...")
	
	cmd := exec.Command("git", "pull")
	cmd.Dir = "/Users/jorgecosgayon/dev/ddo/DDOBuilderV2"
	out, err := cmd.CombinedOutput()
	if err != nil {
		a.addLog(fmt.Sprintf("Failed to update DDOBuilderV2: %s", string(out)))
		return string(out), err
	}
	
	a.addLog(fmt.Sprintf("Git Pull Result: %s", string(out)))
	
	// Reload caches
	a.addLog("Reloading item and augment caches...")
	items, errItems := services.ParseItems("/Users/jorgecosgayon/dev/ddo/DDOBuilderV2/Output/DataFiles/Items")
	if errItems == nil {
		a.itemsCache = items
		a.addLog(fmt.Sprintf("Successfully reloaded %d items.", len(items)))
	} else {
		a.addLog("Failed to reload items: " + errItems.Error())
	}
	
	augments, errAugs := services.ParseAugments("/Users/jorgecosgayon/dev/ddo/DDOBuilderV2/Output/DataFiles/Augments")
	if errAugs == nil {
		a.augmentsCache = augments
		a.addLog(fmt.Sprintf("Successfully reloaded %d augments.", len(augments)))
	} else {
		a.addLog("Failed to reload augments: " + errAugs.Error())
	}
	
	filigrees, errFils := services.ParseFiligrees("/Users/jorgecosgayon/dev/ddo/DDOBuilderV2/Output/DataFiles/FiligreeSets")
	if errFils == nil {
		a.filigreesCache = filigrees
		a.addLog(fmt.Sprintf("Successfully reloaded %d filigrees.", len(filigrees)))
	} else {
		a.addLog("Failed to reload filigrees: " + errFils.Error())
	}
	
	return string(out), nil
}

// OpenFile opens a file using the default OS application.
func (a *App) OpenFile(filePath string) error {
	absPath, err := filepath.Abs(filePath)
	if err != nil {
		return err
	}
	return exec.Command("open", absPath).Start()
}

// SaveGearset writes the payload and result to a .ddogearset file in the gearsets/ directory
func (a *App) SaveGearset(payload OptimizationPayload, result ResultPayload) (string, error) {
	timestamp := time.Now().Format("20060102150405")
	bt := strings.ReplaceAll(payload.BuildType, " ", "")
	ws := strings.ReplaceAll(payload.WeaponStyle, " ", "")
	name := strings.ReplaceAll(payload.GearsetName, " ", "_")
	
	var filename string
	if name != "" {
		filename = fmt.Sprintf("%s_%s%s_%s.ddogearset", name, bt, ws, timestamp)
	} else {
		filename = fmt.Sprintf("%s%s_%s.ddogearset", bt, ws, timestamp)
	}
	
	dir := "gearsets"
	os.MkdirAll(dir, 0755)
	
	path := filepath.Join(dir, filename)
	
	saveData := map[string]interface{}{
		"version": "1.2",
		"gearset_name": payload.GearsetName,
		"saved_at": time.Now().Format(time.RFC3339),
		"config": payload,
		"result": result,
	}
	
	bytes, err := json.MarshalIndent(saveData, "", "  ")
	if err != nil {
		return "", err
	}
	
	err = os.WriteFile(path, bytes, 0644)
	return path, err
}
