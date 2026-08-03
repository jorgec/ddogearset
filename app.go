package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
)

// App struct
type App struct {
	ctx  context.Context
	logs []string
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
	a.addLog("System started.")
}

type OptimizationPayload struct {
	MaxLevels                  []int          `json:"max_levels"`
	BuildType                  string         `json:"build_type"`
	WeaponStyle                string         `json:"weapon_style"`
	Swashbuckling              bool           `json:"swashbuckling"`
	OffhandStyle               string         `json:"offhand_style"`
	CasterSpellpowers          []string       `json:"caster_spellpowers"`
	CasterSchools              []string       `json:"caster_schools"`
	StatPriorities             map[string]int `json:"stat_priorities"`
	ArmorRestriction           string         `json:"armor_restriction"`
	ReservedMinorArtifactSlot  string         `json:"reserved_minor_artifact_slot"`
	MinorArtifactFiligreeSlots int            `json:"minor_artifact_filigree_slots"`
	ExcludeGemOfManyFacets     bool           `json:"exclude_gem_of_many_facets"`
	RunearmUse                 bool           `json:"runearm_use"`
	ExcludedPacks              []string       `json:"excluded_packs"`
	RaidItemLimit              int            `json:"raid_item_limit"`
}

type ResultPayload struct {
	Success      bool                   `json:"success"`
	TimeTaken    float64                `json:"timeTaken"`
	GearSet      map[string]interface{} `json:"gearSet"`
	ErrorMessage string                 `json:"errorMessage,omitempty"`
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

// RunOptimization triggers the Phase 3 Python script using the Pulp library.
func (a *App) RunOptimization(config OptimizationPayload) (ResultPayload, error) {
	a.addLog("Serializing payload...")
	payloadBytes, err := json.Marshal(config)
	if err != nil {
		return ResultPayload{Success: false, ErrorMessage: err.Error()}, err
	}
	tmpFile := "/tmp/ddo_payload.json"
	if err := os.WriteFile(tmpFile, payloadBytes, 0644); err != nil {
		return ResultPayload{Success: false, ErrorMessage: err.Error()}, err
	}
	a.addLog("Invoking Python solver...")
	cmd := exec.Command("python3",
		"/Users/jorgecosgayon/dev/ddo/goGearset/python/solver.py",
		tmpFile)
	cmd.Dir = "/Users/jorgecosgayon/dev/ddo/goGearset/python"
	stdout, _ := cmd.StdoutPipe()
	cmd.Stderr = cmd.Stdout
	if err := cmd.Start(); err != nil {
		return ResultPayload{Success: false, ErrorMessage: err.Error()}, err
	}
	scanner := bufio.NewScanner(stdout)
	for scanner.Scan() {
		a.addLog(scanner.Text())
	}
	if err := cmd.Wait(); err != nil {
		a.addLog("Solver exited with error: " + err.Error())
		return ResultPayload{Success: false, ErrorMessage: err.Error()}, err
	}
	a.addLog("Solver completed successfully.")
	return ResultPayload{Success: true, TimeTaken: 0}, nil
}

// GetSystemLogs retrieves real-time execution logs.
func (a *App) GetSystemLogs() []string {
	return a.logs
}
