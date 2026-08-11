package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"goGearset/internal/appdb"
	"goGearset/internal/catalog"
)

// appDBFileName sits beside catalog.db in the user data directory. Two files,
// one directory, opposite lifecycles: catalog.db is replaced wholesale by an
// app update, app.db is never replaced by anything (schema doc §4).
const appDBFileName = "app.db"

// legacyGearsetDirName is where SaveGearset has always written .ddogearset
// files: a RELATIVE path, resolved against the process working directory.
//
// That was only ever correct when the app was launched from the repo during
// development. A double-clicked macOS .app has no meaningful working directory,
// and on a read-only volume the write fails outright. 0.5.1 is the release that
// decides where user data lives, so the export directory moves under
// userDataDir() with the databases — see gearsetExportDir.
const legacyGearsetDirName = "gearsets"

// appDBPathFor returns where app.db lives, honouring an override.
//
// DDO_APP_DB mirrors DDO_CATALOG_DB's convention so a test or a dev run can
// point at a scratch file without touching the real one. That matters more here
// than it does for the catalog: pointing a test at the real app.db would write
// into data the user cannot regenerate.
func appDBPathFor() (string, error) {
	if p := os.Getenv("DDO_APP_DB"); p != "" {
		return p, nil
	}
	dir, err := userDataDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, appDBFileName), nil
}

// gearsetExportDir is where .ddogearset files are written from 0.5.1 on.
//
// They are an EXPORT format now, not storage (schema §8 Q3) — a file can be
// sent to someone, a database cannot, so the feature stays while the source of
// truth moves to app.db.
//
// DDO_GEARSET_DIR overrides it, completing the set alongside DDO_CATALOG_DB and
// DDO_APP_DB. Needed by this project's own tests, which must not write into the
// real user data directory to check that exporting works.
func gearsetExportDir() (string, error) {
	if p := os.Getenv("DDO_GEARSET_DIR"); p != "" {
		return p, nil
	}
	dir, err := userDataDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "gearsets"), nil
}

// ensureAppDB opens (creating on first run) the user's app.db and stores the
// handle on the App.
//
// Unlike ensureCatalogSeeded there is nothing to seed: app.db starts empty and
// is filled by the user. A failure here is NOT fatal to startup — the app still
// solves, it just cannot persist — because refusing to launch over a storage
// problem would leave someone with no way to reach their own exported files.
func (a *App) ensureAppDB() error {
	path, err := appDBPathFor()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return fmt.Errorf("creating data directory for app.db: %w", err)
	}
	db, err := appdb.Open(path, AppVersion)
	if err != nil {
		return err
	}
	a.appDB = db
	a.appDBPath = path
	a.addLog(fmt.Sprintf("User data ready at %s (schema %d).", path, appdb.SchemaVersion))
	return nil
}

// legacyGearsetFiles finds .ddogearset files left by pre-0.5.1 builds, so the
// import can offer them.
//
// Looks in the new export directory AND the old working-directory-relative one,
// because whether the latter has anything in it depends entirely on where the
// app happened to be launched from before now.
func legacyGearsetFiles() []string {
	var dirs []string
	if exportDir, err := gearsetExportDir(); err == nil {
		dirs = append(dirs, exportDir)
	}
	if cwd, err := os.Getwd(); err == nil {
		dirs = append(dirs, filepath.Join(cwd, legacyGearsetDirName))
	}

	seen := map[string]bool{}
	var found []string
	for _, dir := range dirs {
		matches, err := filepath.Glob(filepath.Join(dir, "*.ddogearset"))
		if err != nil {
			continue
		}
		for _, m := range matches {
			resolved, err := filepath.Abs(m)
			if err != nil {
				resolved = m
			}
			if !seen[resolved] {
				seen[resolved] = true
				found = append(found, resolved)
			}
		}
	}
	return found
}

// ListBuilds returns every stored build, most recently updated first.
func (a *App) ListBuilds() ([]appdb.BuildSummary, error) {
	if a.appDB == nil {
		return nil, fmt.Errorf("user data is unavailable")
	}
	return appdb.ListBuilds(a.appDB)
}

// LoadBuild reads one stored build back into a solve configuration.
//
// Returns the configuration and any unresolved references, and NO stats. That
// is the shape of the release: app.db records what you configured and what you
// have equipped, and the numbers come from recalculating it. A stored total
// would be a second answer that goes stale the moment the catalog updates.
func (a *App) LoadBuild(buildUUID string) (LoadedBuildPayload, error) {
	var out LoadedBuildPayload
	if a.appDB == nil {
		return out, fmt.Errorf("user data is unavailable")
	}
	loaded, err := appdb.LoadBuild(a.appDB, buildUUID)
	if err != nil {
		return out, err
	}
	raw, err := loaded.ConfigJSON()
	if err != nil {
		return out, fmt.Errorf("reading build %s: %w", buildUUID, err)
	}
	var config OptimizationPayload
	if err := json.Unmarshal(raw, &config); err != nil {
		return out, fmt.Errorf("reading build %s: %w", buildUUID, err)
	}
	return LoadedBuildPayload{
		UUID:    loaded.UUID,
		Name:    loaded.Name,
		Config:  config,
		Orphans: loaded.Orphans,
	}, nil
}

// LoadedBuildPayload is LoadBuild's wire shape — the generic config map from
// appdb, unmarshaled into the same OptimizationPayload the frontend already
// binds to, so nothing downstream learns a second config type.
type LoadedBuildPayload struct {
	UUID    string              `json:"uuid"`
	Name    string              `json:"name"`
	Config  OptimizationPayload `json:"config"`
	Orphans []appdb.Orphan      `json:"orphans,omitempty"`
}

// AcceptAll promotes the solver's suggestion to the user's equipped gearset and
// returns the refreshed configuration.
//
// Schema §5.4's one statement. The caller gets the build back so the UI shows
// the accepted gear without re-deriving it from a result payload — which is how
// the two used to drift apart in the first place.
func (a *App) AcceptAll(buildUUID string) (LoadedBuildPayload, error) {
	var out LoadedBuildPayload
	if a.appDB == nil {
		return out, fmt.Errorf("user data is unavailable")
	}
	moved, err := appdb.AcceptSuggestion(a.appDB, buildUUID)
	if err != nil {
		return out, err
	}
	a.addLog(fmt.Sprintf("Accepted the suggestion: %d slot(s) are now equipped.", moved))
	return a.LoadBuild(buildUUID)
}

// GetSuggestion returns what the solver most recently proposed for a build, in
// the same pre_equipped / pre_filled_* shape a configuration uses.
//
// Read-only. Nothing here can turn a suggestion into equipped gear — that is
// AcceptAll's job, and keeping it to one entry point is what makes the two-node
// split enforceable rather than merely intended.
func (a *App) GetSuggestion(buildUUID string) (map[string]interface{}, error) {
	if a.appDB == nil {
		return nil, fmt.Errorf("user data is unavailable")
	}
	return appdb.LoadGearset(a.appDB, buildUUID, appdb.OriginSuggested)
}

// BuildIDForCurrentConfig tells the frontend which build a configuration maps
// to, so it can ask about a suggestion without having saved first.
func (a *App) BuildIDForCurrentConfig(gearsetName string) string {
	name := strings.TrimSpace(gearsetName)
	if name == "" {
		name = "Untitled"
	}
	return appdb.BuildUUIDForName(name)
}

// DeleteBuild removes a stored build and everything belonging to it.
func (a *App) DeleteBuild(buildUUID string) error {
	if a.appDB == nil {
		return fmt.Errorf("user data is unavailable")
	}
	if err := appdb.DeleteBuild(a.appDB, buildUUID); err != nil {
		return err
	}
	a.addLog("Deleted build " + buildUUID)
	return nil
}

// ImportGearsetFile imports one .ddogearset chosen by the user.
//
// This is what the Load button became. The file is read, not moved or deleted —
// import copies it in, and the file stays wherever the user keeps it.
func (a *App) ImportGearsetFile(path string) (appdb.ImportOutcome, error) {
	if a.appDB == nil {
		return appdb.ImportOutcome{}, fmt.Errorf("user data is unavailable")
	}
	resolver, closeCatalog, err := a.nameResolver()
	if err != nil {
		return appdb.ImportOutcome{}, err
	}
	defer closeCatalog()

	outcome := appdb.ImportFile(a.appDB, resolver, path, AppVersion)
	if outcome.Status == appdb.StatusFailed {
		return outcome, fmt.Errorf("%s", outcome.Error)
	}
	a.addLog(fmt.Sprintf("Imported %s: %s (%d unresolved reference(s)).",
		filepath.Base(path), outcome.Status, len(outcome.Orphans)))
	return outcome, nil
}

// ImportGearsetContent imports a .ddogearset the frontend already read.
//
// The UI's file picker is a browser <input type="file">, which hands back
// content and never a path, so this is the entry point the Load button uses.
// `filename` is recorded as provenance only.
func (a *App) ImportGearsetContent(filename, content string) (appdb.ImportOutcome, error) {
	if a.appDB == nil {
		return appdb.ImportOutcome{}, fmt.Errorf("user data is unavailable")
	}
	resolver, closeCatalog, err := a.nameResolver()
	if err != nil {
		return appdb.ImportOutcome{}, err
	}
	defer closeCatalog()

	outcome := appdb.ImportContent(a.appDB, resolver, []byte(content), filename, AppVersion)
	if outcome.Status == appdb.StatusFailed {
		return outcome, fmt.Errorf("%s", outcome.Error)
	}
	a.addLog(fmt.Sprintf("Imported %s: %s (%d unresolved reference(s)).",
		filename, outcome.Status, len(outcome.Orphans)))
	return outcome, nil
}

// ImportLegacyGearsets imports every .ddogearset this machine can find into
// app.db and reports what happened to each.
//
// Explicit — nothing calls this on startup. Importing is a decision, and one
// made silently during launch is one nobody can connect to its effects.
//
// Safe to run repeatedly: a file already imported is reported as such and
// nothing about its build is touched (see appdb.ImportFile). Re-import is not a
// sync, because the build may have been edited in the app since.
func (a *App) ImportLegacyGearsets() ([]appdb.ImportOutcome, error) {
	if a.appDB == nil {
		return nil, fmt.Errorf("user data is not available; nothing was imported")
	}
	// Opened for the duration of the import rather than held: resolving names
	// is the only thing an import needs the catalog for, and it is read-only
	// and immutable, so there is nothing to keep warm.
	path := a.catalogDBPath
	if path == "" {
		path = catalogPath()
	}
	catalogDB, err := catalog.Open(path)
	if err != nil {
		return nil, fmt.Errorf("cannot resolve item names without the catalog: %w", err)
	}
	defer catalogDB.Close()

	resolver, err := appdb.NewSQLCatalog(catalogDB)
	if err != nil {
		return nil, err
	}

	files := legacyGearsetFiles()
	outcomes := make([]appdb.ImportOutcome, 0, len(files))
	for _, path := range files {
		outcome := appdb.ImportFile(a.appDB, resolver, path, AppVersion)
		outcomes = append(outcomes, outcome)
		switch outcome.Status {
		case appdb.StatusImported:
			a.addLog(fmt.Sprintf("Imported %s (%d unresolved reference(s)).",
				filepath.Base(path), len(outcome.Orphans)))
		case appdb.StatusAlreadyImported:
			a.addLog(fmt.Sprintf("Already imported, left alone: %s", filepath.Base(path)))
		default:
			a.addLog(fmt.Sprintf("Could not import %s: %s", filepath.Base(path), outcome.Error))
		}
	}
	return outcomes, nil
}

// RecalculationRequest is everything a recalculation takes — and nothing else.
//
// Deliberately NOT OptimizationPayload. That type carries armor_restriction,
// excluded_packs, weapon_style, raid_item_limit and the rest, and passing it
// here would mean stripping fields on the way through: a field that is removed
// in transit is a field somebody re-adds later. This type simply has nowhere to
// put one, which is the same guarantee solver.py's restriction check makes,
// stated in the type system instead of at runtime.
type RecalculationRequest struct {
	GearsetName        string                 `json:"gearset_name"`
	MaxLevel           int                    `json:"max_level"`
	BuildType          string                 `json:"build_type"`
	StatPriorities     []StatPriorityEntry    `json:"stat_priorities"`
	PreEquipped        map[string]string      `json:"pre_equipped"`
	PreFilledAugments  map[string]interface{} `json:"pre_filled_augments"`
	PreFilledFiligrees map[string][]string    `json:"pre_filled_filigrees"`
}

// RecalculateGearset evaluates the gear the user has equipped.
//
// This is what the Calculate button became. No solver runs: solver.py's
// recalculate branch returns before any candidate pool exists (0.5.1 Phase 4).
func (a *App) RecalculateGearset(request RecalculationRequest) (ResultPayload, error) {
	payload := map[string]interface{}{
		"mode":                 "recalculate",
		"gearset_name":         request.GearsetName,
		"max_level":            request.MaxLevel,
		"build_type":           request.BuildType,
		"stat_priorities":      request.StatPriorities,
		"pre_equipped":         request.PreEquipped,
		"pre_filled_augments":  request.PreFilledAugments,
		"pre_filled_filigrees": request.PreFilledFiligrees,
	}

	started := time.Now()
	raw, err := a.runSolver(payload)
	if err != nil {
		a.recordRun(configFor(request), "recalculate", ResultPayload{},
			time.Since(started).Seconds(), err)
		return ResultPayload{Success: false, ErrorMessage: err.Error()}, err
	}
	var result ResultPayload
	if err := json.Unmarshal(raw, &result); err != nil {
		return ResultPayload{Success: false,
			ErrorMessage: "Could not read the recalculation: " + err.Error()}, err
	}
	if !result.Success && result.ErrorMessage != "" {
		return result, nil
	}
	result.Success = true
	// A recalculation proposes nothing, so it never records a SUGGESTION (see
	// shouldRecordSuggestion) — but it absolutely records a RUN. "What did my
	// gear total to on the 11th, against catalog f91af4e6" is the question run
	// history exists for.
	a.recordRun(configFor(request), "recalculate", result, time.Since(started).Seconds(), nil)
	return result, nil
}

// configFor widens a recalculation request back to the config shape recordRun
// needs to find the build. Only the identifying fields — nothing here can put a
// restriction back.
func configFor(request RecalculationRequest) OptimizationPayload {
	return OptimizationPayload{
		GearsetName:    request.GearsetName,
		BuildType:      request.BuildType,
		MaxLevel:       request.MaxLevel,
		StatPriorities: request.StatPriorities,
		PreEquipped:    request.PreEquipped,
	}
}

// RecalculationRequestFrom narrows a full configuration down to what a
// recalculation may see. The one place the narrowing happens, so it is
// reviewable rather than scattered across call sites.
func RecalculationRequestFrom(config OptimizationPayload) RecalculationRequest {
	return RecalculationRequest{
		GearsetName:        config.GearsetName,
		MaxLevel:           config.MaxLevel,
		BuildType:          config.BuildType,
		StatPriorities:     config.StatPriorities,
		PreEquipped:        config.PreEquipped,
		PreFilledAugments:  config.PreFilledAugments,
		PreFilledFiligrees: config.PreFilledFiligrees,
	}
}

// recordRun writes a run to history. Best-effort and never fatal: a result the
// user is looking at must not be withheld because the historian failed.
//
// The catalog revision goes on the row deliberately. Six weeks after a catalog
// update, "did my gear change or did the data?" is otherwise unanswerable — and
// it is the question that makes someone distrust every number the app shows.
func (a *App) recordRun(config OptimizationPayload, mode string, result ResultPayload,
	seconds float64, runErr error) {
	if a.appDB == nil {
		return
	}
	resolver, closeCatalog, err := a.nameResolver()
	if err != nil {
		return
	}
	buildUUID, err := a.ensureBuildFor(config, resolver)
	closeCatalog()
	if err != nil {
		a.addLog("Could not record this run: " + err.Error())
		return
	}

	record := appdb.RunRecord{
		BuildUUID:     buildUUID,
		Mode:          mode,
		AppVersion:    AppVersion,
		CatalogCommit: a.catalogCommit(),
		Seconds:       seconds,
		Succeeded:     runErr == nil && result.Success,
	}
	if runErr != nil {
		record.ErrorMessage = runErr.Error()
	} else if !result.Success {
		record.ErrorMessage = result.ErrorMessage
	}

	var outcome *appdb.RunOutcome
	if record.Succeeded {
		outcome = runOutcomeFrom(result)
	}
	if _, err := appdb.RecordRun(a.appDB, record, outcome); err != nil {
		a.addLog("Could not record this run: " + err.Error())
	}
}

// catalogCommit reads catalog_meta.ddobuilder_commit — which game data produced
// these numbers.
func (a *App) catalogCommit() string {
	path := a.catalogDBPath
	if path == "" {
		path = catalogPath()
	}
	db, err := catalog.Open(path)
	if err != nil {
		return ""
	}
	defer db.Close()
	meta, err := catalog.ReadMeta(db)
	if err != nil {
		return ""
	}
	return meta.DDOBuilderCommit
}

// runOutcomeFrom pulls the recordable parts out of a result payload.
//
// Reads the typed fields directly. It used to re-marshal the struct to JSON and
// fish for `otherStats` / `allEffectsDetail` / `warnings` by name — which found
// nothing, because those fields were not declared on ResultPayload and had been
// discarded when the solver's output was unmarshaled. Re-serialising a value
// cannot recover what was dropped on the way in.
func runOutcomeFrom(result ResultPayload) *appdb.RunOutcome {
	outcome := &appdb.RunOutcome{
		RealizedStats: numericMap(result.RealizedStats),
		OtherStats:    result.OtherStats,
		ActiveSets:    result.ActiveSets,
		EffectDetail:  map[string][]map[string]interface{}{},
	}
	for _, e := range result.AllEffectsDetail {
		outcome.EffectDetail[e.Stat] = append(outcome.EffectDetail[e.Stat],
			map[string]interface{}{
				"value":      e.Value,
				"bonusType":  e.BonusType,
				"sourceName": e.SourceName,
				"sourceKind": e.SourceKind,
			})
	}
	for _, w := range result.Warnings {
		outcome.Warnings = append(outcome.Warnings, map[string]interface{}{
			"kind": w.Kind, "slot": w.Slot, "message": w.Message,
		})
	}
	return outcome
}

func numericMap(in map[string]interface{}) map[string]float64 {
	out := map[string]float64{}
	for k, v := range in {
		if f, ok := v.(float64); ok {
			out[k] = f
		}
	}
	return out
}

// ListRuns returns a build's run history, newest first.
func (a *App) ListRuns(buildUUID string) ([]appdb.RunRecord, error) {
	if a.appDB == nil {
		return nil, fmt.Errorf("user data is unavailable")
	}
	return appdb.ListRuns(a.appDB, buildUUID, 50)
}
