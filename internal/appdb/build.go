package appdb

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"
)

// namedBuildNamespace mints identities for builds SAVED IN THE APP, as opposed
// to imported from a file (buildNamespace, over file bytes).
//
// A named build's identity is its name, so saving twice updates one row instead
// of accumulating a new one per keystroke of the Save button. Renaming
// therefore creates a NEW build and leaves the old one — "Save As", which is
// the non-destructive reading and the one that cannot lose work. Explicit build
// management is 0.5.2's problem.
var namedBuildNamespace = uuid.NewSHA1(uuid.NameSpaceURL, []byte("ddogearset:named-build"))

// BuildUUIDForName is the identity of an app-saved build with a given name.
// Case- and whitespace-insensitive, so "My Caster" and "my caster " are the
// same build rather than two that look identical in a list.
func BuildUUIDForName(name string) string {
	return uuid.NewSHA1(namedBuildNamespace, []byte(normalizeName(name))).String()
}

// BuildSummary is one row of a build list: enough to show and choose, without
// loading a whole configuration.
type BuildSummary struct {
	UUID         string `json:"uuid"`
	Name         string `json:"name"`
	BuildType    string `json:"buildType"`
	WeaponStyle  string `json:"weaponStyle"`
	MaxLevel     int    `json:"maxLevel"`
	UpdatedAt    string `json:"updatedAt"`
	ImportedFrom string `json:"importedFrom,omitempty"`
	SlotCount    int    `json:"slotCount"`
	OrphanCount  int    `json:"orphanCount"`
}

// SaveResult reports what a save did.
type SaveResult struct {
	UUID    string   `json:"uuid"`
	Name    string   `json:"name"`
	Created bool     `json:"created"`
	Orphans []Orphan `json:"orphans,omitempty"`
}

// SaveBuild writes a build and its equipped gearset, replacing any previous
// version of that build.
//
// `config` is an OptimizationPayload marshaled to a generic map. Passing it that
// way rather than as a typed struct keeps this package independent of the app's
// wire types, and — more usefully — means a save and an import travel through
// exactly the same writer (writeBuild), so an exported file re-imports to the
// same rows it came from.
//
// Replace-then-write inside ONE transaction: a save that failed halfway through
// after deleting the old rows would destroy a gearset to store nothing, which is
// the one thing app.db must never do.
func SaveBuild(db *sql.DB, catalog Catalog, config map[string]interface{}, appVersion string) (SaveResult, error) {
	name := strings.TrimSpace(stringOr(config, "gearset_name", ""))
	if name == "" {
		// An unnamed save gets a fresh identity every time, matching what the
		// app has always done with unnamed gearsets: write a new timestamped
		// file. Collapsing them all into one row would silently overwrite the
		// previous unnamed save, which nobody asked for.
		name = "Untitled"
		return saveBuildAs(db, catalog, config, uuid.NewString(), name, appVersion)
	}
	return saveBuildAs(db, catalog, config, BuildUUIDForName(name), name, appVersion)
}

// SaveBuildAs writes a build under a caller-supplied identity, for the case
// where the caller already knows which build it is holding.
func SaveBuildAs(db *sql.DB, catalog Catalog, config map[string]interface{},
	buildUUID, appVersion string) (SaveResult, error) {
	name := strings.TrimSpace(stringOr(config, "gearset_name", ""))
	if name == "" {
		name = "Untitled"
	}
	return saveBuildAs(db, catalog, config, buildUUID, name, appVersion)
}

func saveBuildAs(db *sql.DB, catalog Catalog, config map[string]interface{},
	buildUUID, name, appVersion string) (SaveResult, error) {
	out := SaveResult{UUID: buildUUID, Name: name}

	var createdAt string
	err := db.QueryRow("SELECT created_at FROM build WHERE uuid = ?", buildUUID).Scan(&createdAt)
	switch {
	case err == sql.ErrNoRows:
		out.Created = true
		createdAt = nowRFC3339()
	case err != nil:
		return out, fmt.Errorf("looking up build: %w", err)
	}

	tx, err := db.Begin()
	if err != nil {
		return out, fmt.Errorf("starting transaction: %w", err)
	}
	defer tx.Rollback() //nolint:errcheck // no-op after a successful Commit

	// ON DELETE CASCADE takes every child row with it, so this one statement
	// clears priorities, packs, caster options, all three gearset tables and
	// the orphan report in one go. Inside the transaction, so nothing is gone
	// unless the replacement lands.
	if _, err := tx.Exec("DELETE FROM build WHERE uuid = ?", buildUUID); err != nil {
		return out, fmt.Errorf("clearing the previous version of this build: %w", err)
	}

	saved := savedGearset{
		GearsetName: name,
		AppVersion:  appVersion,
		Config:      config,
	}
	orphans, err := writeBuild(tx, catalog, saved, buildUUID, name, nil, appVersion, createdAt)
	if err != nil {
		return out, err
	}
	// created_at is preserved across saves; updated_at moves. writeBuild sets
	// both from createdAt because an import has only one timestamp to work
	// with, so a save corrects updated_at afterwards, in the same transaction.
	if _, err := tx.Exec("UPDATE build SET updated_at = ? WHERE uuid = ?",
		nowRFC3339(), buildUUID); err != nil {
		return out, fmt.Errorf("stamping updated_at: %w", err)
	}

	if err := tx.Commit(); err != nil {
		return out, fmt.Errorf("committing save: %w", err)
	}
	out.Orphans = orphans
	return out, nil
}

// ListBuilds returns every stored build, most recently updated first.
func ListBuilds(db *sql.DB) ([]BuildSummary, error) {
	rows, err := db.Query(`
		SELECT b.uuid, b.name, b.build_type, COALESCE(b.weapon_style, ''),
		       b.max_level, b.updated_at, COALESCE(b.imported_from, ''),
		       (SELECT count(*) FROM gearset_slot s
		         WHERE s.build_uuid = b.uuid AND s.origin = 'equipped'),
		       (SELECT count(*) FROM orphan_reference o WHERE o.build_uuid = b.uuid)
		  FROM build b
		 ORDER BY b.updated_at DESC, b.name ASC`)
	if err != nil {
		return nil, fmt.Errorf("listing builds: %w", err)
	}
	defer rows.Close()

	// Non-nil so an empty database marshals to [] rather than null — the
	// frontend iterates this directly.
	out := []BuildSummary{}
	for rows.Next() {
		var b BuildSummary
		if err := rows.Scan(&b.UUID, &b.Name, &b.BuildType, &b.WeaponStyle,
			&b.MaxLevel, &b.UpdatedAt, &b.ImportedFrom, &b.SlotCount, &b.OrphanCount); err != nil {
			return nil, fmt.Errorf("reading build row: %w", err)
		}
		out = append(out, b)
	}
	return out, rows.Err()
}

// LoadedBuild is a stored build read back into the shape the app configures
// solves with.
type LoadedBuild struct {
	UUID string `json:"uuid"`
	Name string `json:"name"`
	// Config is an OptimizationPayload-shaped map: the caller unmarshals it
	// into its own type. Deliberately NOT the typed struct — see SaveBuild.
	Config  map[string]interface{} `json:"config"`
	Orphans []Orphan               `json:"orphans,omitempty"`
	// Stats are deliberately absent. app.db stores what you configured and what
	// you have equipped; the NUMBERS come from recalculating it (Phase 4).
	// Storing them would mean carrying a second answer that silently goes stale
	// the moment the catalog updates — which is exactly what run.catalog_commit
	// exists to make visible when run history lands in Phase 6.
}

// LoadBuild reads one build back out.
func LoadBuild(db *sql.DB, buildUUID string) (LoadedBuild, error) {
	out := LoadedBuild{UUID: buildUUID, Config: map[string]interface{}{}}

	var name, buildType string
	var weaponStyle, offhandStyle, weaponDamageType, armorRestriction, reservedSlot sql.NullString
	var maxLevel, minorSlots, raidLimit, maxSearchTime int
	var swashbuckling, runearm, isDino, excludeGomf, casterRestrict int
	err := db.QueryRow(`
		SELECT name, build_type, weapon_style, offhand_style, weapon_damage_type,
		       armor_restriction, reserved_minor_artifact_slot, max_level,
		       minor_artifact_filigree_slots, raid_item_limit,
		       COALESCE(max_search_time, 0), swashbuckling, runearm_use,
		       is_dino_artifact, exclude_gem_of_many_facets,
		       caster_restrict_weapon_families
		  FROM build WHERE uuid = ?`, buildUUID).Scan(
		&name, &buildType, &weaponStyle, &offhandStyle, &weaponDamageType,
		&armorRestriction, &reservedSlot, &maxLevel, &minorSlots, &raidLimit,
		&maxSearchTime, &swashbuckling, &runearm, &isDino, &excludeGomf, &casterRestrict)
	if err == sql.ErrNoRows {
		return out, fmt.Errorf("no build with id %s", buildUUID)
	}
	if err != nil {
		return out, fmt.Errorf("reading build: %w", err)
	}
	out.Name = name

	cfg := out.Config
	cfg["gearset_name"] = name
	cfg["build_type"] = buildType
	cfg["max_level"] = maxLevel
	cfg["weapon_style"] = weaponStyle.String
	cfg["offhand_style"] = offhandStyle.String
	cfg["armor_restriction"] = armorRestriction.String
	cfg["reserved_minor_artifact_slot"] = reservedSlot.String
	cfg["minor_artifact_filigree_slots"] = minorSlots
	cfg["raid_item_limit"] = raidLimit
	cfg["swashbuckling"] = swashbuckling != 0
	cfg["runearm_use"] = runearm != 0
	cfg["is_dino_artifact"] = isDino != 0
	cfg["exclude_gem_of_many_facets"] = excludeGomf != 0
	cfg["caster_restrict_weapon_families"] = casterRestrict != 0
	if weaponDamageType.Valid && weaponDamageType.String != "" {
		cfg["weapon_damage_type"] = weaponDamageType.String
	}
	if maxSearchTime > 0 {
		cfg["max_search_time"] = maxSearchTime
	}

	priorities, err := loadPriorities(db, buildUUID)
	if err != nil {
		return out, err
	}
	cfg["stat_priorities"] = priorities

	packs, err := loadStrings(db,
		"SELECT pack FROM build_excluded_pack WHERE build_uuid = ? ORDER BY pack", buildUUID)
	if err != nil {
		return out, err
	}
	cfg["excluded_packs"] = packs

	for _, pair := range []struct{ kind, key string }{
		{"spellpower", "caster_spellpowers"}, {"school", "caster_schools"}} {
		values, err := loadStrings(db,
			"SELECT value FROM build_caster_option WHERE build_uuid = ? AND kind = '"+
				pair.kind+"' ORDER BY value", buildUUID)
		if err != nil {
			return out, err
		}
		cfg[pair.key] = values
	}

	if err := loadGearsetInto(db, buildUUID, cfg); err != nil {
		return out, err
	}
	orphans, err := loadOrphans(db, buildUUID)
	if err != nil {
		return out, err
	}
	out.Orphans = orphans
	return out, nil
}

func loadPriorities(db *sql.DB, buildUUID string) ([]map[string]interface{}, error) {
	rows, err := db.Query(
		"SELECT raw_text, tier, cap FROM build_priority WHERE build_uuid = ? ORDER BY position",
		buildUUID)
	if err != nil {
		return nil, fmt.Errorf("reading priorities: %w", err)
	}
	defer rows.Close()

	out := []map[string]interface{}{}
	for rows.Next() {
		var text string
		var tier int
		var cap sql.NullFloat64
		if err := rows.Scan(&text, &tier, &cap); err != nil {
			return nil, fmt.Errorf("reading priority: %w", err)
		}
		entry := map[string]interface{}{"stat": text, "tier": tier}
		if cap.Valid {
			entry["cap"] = cap.Float64
		}
		out = append(out, entry)
	}
	return out, rows.Err()
}

func loadStrings(db *sql.DB, query string, args ...interface{}) ([]string, error) {
	rows, err := db.Query(query, args...)
	if err != nil {
		return nil, fmt.Errorf("query %q: %w", query, err)
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var v string
		if err := rows.Scan(&v); err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

// loadGearsetInto reconstructs pre_equipped / pre_filled_augments /
// pre_filled_filigrees from the `equipped` rows.
//
// Reads origin='equipped' and nothing else. What the solver most recently
// SUGGESTED is a different set of rows and never leaks into a configuration —
// the failure this two-node split exists to make impossible (schema §5.4).
func loadGearsetInto(db *sql.DB, buildUUID string, cfg map[string]interface{}) error {
	equipped := map[string]string{}
	rows, err := db.Query(
		"SELECT slot, item_name FROM gearset_slot WHERE build_uuid = ? AND origin = 'equipped'",
		buildUUID)
	if err != nil {
		return fmt.Errorf("reading gearset slots: %w", err)
	}
	for rows.Next() {
		var slot, name string
		if err := rows.Scan(&slot, &name); err != nil {
			rows.Close()
			return err
		}
		equipped[slot] = name
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	cfg["pre_equipped"] = equipped

	augments := map[string]map[string]string{}
	rows, err = db.Query(`SELECT slot, colour, augment_name FROM gearset_augment
		WHERE build_uuid = ? AND origin = 'equipped'`, buildUUID)
	if err != nil {
		return fmt.Errorf("reading gearset augments: %w", err)
	}
	for rows.Next() {
		var slot, colour, name string
		if err := rows.Scan(&slot, &colour, &name); err != nil {
			rows.Close()
			return err
		}
		setNested(augments, slot, colour, name)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	cfg["pre_filled_augments"] = augments

	filigrees := map[string][]string{"weapon": {}, "artifact": {}}
	rows, err = db.Query(`SELECT bucket, filigree_name FROM gearset_filigree
		WHERE build_uuid = ? AND origin = 'equipped' ORDER BY bucket, position`, buildUUID)
	if err != nil {
		return fmt.Errorf("reading gearset filigrees: %w", err)
	}
	for rows.Next() {
		var bucket, name string
		if err := rows.Scan(&bucket, &name); err != nil {
			rows.Close()
			return err
		}
		filigrees[bucket] = append(filigrees[bucket], name)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	cfg["pre_filled_filigrees"] = filigrees
	return nil
}

func loadOrphans(db *sql.DB, buildUUID string) ([]Orphan, error) {
	rows, err := db.Query(`SELECT kind, COALESCE(slot,''), name, COALESCE(detail,'')
		FROM orphan_reference WHERE build_uuid = ? ORDER BY kind, name`, buildUUID)
	if err != nil {
		return nil, fmt.Errorf("reading orphan references: %w", err)
	}
	defer rows.Close()
	var out []Orphan
	for rows.Next() {
		var o Orphan
		if err := rows.Scan(&o.Kind, &o.Slot, &o.Name, &o.Detail); err != nil {
			return nil, err
		}
		out = append(out, o)
	}
	return out, rows.Err()
}

// DeleteBuild removes a build and, by cascade, everything belonging to it.
func DeleteBuild(db *sql.DB, buildUUID string) error {
	res, err := db.Exec("DELETE FROM build WHERE uuid = ?", buildUUID)
	if err != nil {
		return fmt.Errorf("deleting build: %w", err)
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return fmt.Errorf("no build with id %s", buildUUID)
	}
	return nil
}

// ConfigJSON is a convenience for callers that want the loaded config as JSON
// to unmarshal into their own payload type.
func (b LoadedBuild) ConfigJSON() ([]byte, error) {
	return json.Marshal(b.Config)
}
