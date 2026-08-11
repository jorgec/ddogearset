package appdb

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"

	"github.com/google/uuid"
)

// buildNamespace seeds the deterministic build UUIDs minted below. Fixed
// forever: changing it would give every already-imported file a new identity
// and re-import all of them as duplicates.
var buildNamespace = uuid.NewSHA1(uuid.NameSpaceURL, []byte("ddogearset:build"))

// Status values for ImportOutcome.
const (
	StatusImported        = "imported"
	StatusAlreadyImported = "already-imported"
	StatusFailed          = "failed"
)

// Orphan is a name the file referenced that no catalog row answers to.
//
// Reported, never fatal. A gearset saved two game updates ago can legitimately
// name an item that has since been removed, and refusing the whole import over
// one missing trinket would strand the other thirteen slots. This is what
// gearset_slot's denormalized item_name is for (schema §5.3).
type Orphan struct {
	Kind   string `json:"kind"` // item | augment | filigree
	Slot   string `json:"slot,omitempty"`
	Name   string `json:"name"`
	Detail string `json:"detail,omitempty"`
}

// ImportOutcome is the per-file result. Deliberately a value, not an error:
// importing ten files where one fails should report nine successes and one
// diagnosis, not abort at the first problem.
type ImportOutcome struct {
	SourceFile string   `json:"sourceFile"`
	BuildUUID  string   `json:"buildUuid"`
	BuildName  string   `json:"buildName"`
	Status     string   `json:"status"`
	Orphans    []Orphan `json:"orphans,omitempty"`
	Error      string   `json:"error,omitempty"`
}

// savedGearset is the on-disk .ddogearset shape, read loosely on purpose:
// files exist from several app versions and this reads the parts that have
// been stable, not the whole struct.
type savedGearset struct {
	Version     string                 `json:"version"`
	AppVersion  string                 `json:"app_version"`
	GearsetName string                 `json:"gearset_name"`
	SavedAt     string                 `json:"saved_at"`
	Config      map[string]interface{} `json:"config"`
	Result      map[string]interface{} `json:"result"`
}

// Catalog is the lookup surface an import needs. An interface so tests can
// drive imports against a handful of rows instead of a 58 MB file.
type Catalog interface {
	ItemUUID(name string) (string, bool)
	AugmentUUID(name, colour string) (string, bool)
	FiligreeUUID(name string) (string, bool)
}

// SQLCatalog resolves names against a real catalog.db.
//
// Everything is loaded up front rather than queried per name: an import
// resolves on the order of 60 names per file, and one pass over three small
// tables beats 60 round trips through the driver.
type SQLCatalog struct {
	items     map[string]string
	augments  map[string]string // name \x1f colour
	filigrees map[string]string
}

// NewSQLCatalog reads the name→uuid maps out of an open catalog.db.
func NewSQLCatalog(catalog *sql.DB) (*SQLCatalog, error) {
	c := &SQLCatalog{
		items:     map[string]string{},
		augments:  map[string]string{},
		filigrees: map[string]string{},
	}
	load := func(query string, into func(cols []string)) error {
		rows, err := catalog.Query(query)
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			var a, b, c string
			var dest []interface{}
			cols, _ := rows.Columns()
			switch len(cols) {
			case 2:
				dest = []interface{}{&a, &b}
			default:
				dest = []interface{}{&a, &b, &c}
			}
			if err := rows.Scan(dest...); err != nil {
				return err
			}
			into([]string{a, b, c})
		}
		return rows.Err()
	}

	if err := load("SELECT name, uuid FROM item", func(c2 []string) {
		c.items[normalizeName(c2[0])] = c2[1]
	}); err != nil {
		return nil, fmt.Errorf("loading item names: %w", err)
	}
	// name+colour, because name alone is not a key: the real corpus has two
	// different "Deathblock" augments in different colour slots (see
	// etl/transform.py's augment section).
	if err := load("SELECT name, colour, uuid FROM augment", func(c2 []string) {
		c.augments[augmentKey(c2[0], c2[1])] = c2[2]
	}); err != nil {
		return nil, fmt.Errorf("loading augment names: %w", err)
	}
	if err := load("SELECT name, uuid FROM filigree", func(c2 []string) {
		c.filigrees[normalizeName(c2[0])] = c2[1]
	}); err != nil {
		return nil, fmt.Errorf("loading filigree names: %w", err)
	}
	return c, nil
}

// normalizeName trims and case-folds. Saved files carry names typed or copied
// by hand across several app versions; a trailing space should not orphan an
// item that is plainly present.
func normalizeName(name string) string {
	return strings.ToLower(strings.TrimSpace(name))
}

func augmentKey(name, colour string) string {
	return normalizeName(name) + "\x1f" + normalizeName(colour)
}

func (c *SQLCatalog) ItemUUID(name string) (string, bool) {
	v, ok := c.items[normalizeName(name)]
	return v, ok
}

func (c *SQLCatalog) AugmentUUID(name, colour string) (string, bool) {
	if v, ok := c.augments[augmentKey(name, colour)]; ok {
		return v, true
	}
	// Colour is not always recorded faithfully in older saves. Fall back to a
	// unique name match, and only a unique one — resolving an ambiguous name to
	// whichever row happened to load first is exactly the silent mis-identity
	// the UUID registry exists to prevent.
	var found string
	matches := 0
	prefix := normalizeName(name) + "\x1f"
	for k, v := range c.augments {
		if strings.HasPrefix(k, prefix) {
			matches++
			found = v
		}
	}
	if matches == 1 {
		return found, true
	}
	return "", false
}

func (c *SQLCatalog) FiligreeUUID(name string) (string, bool) {
	v, ok := c.filigrees[normalizeName(name)]
	return v, ok
}

// BuildUUIDForFile is the deterministic identity of an imported file: a v5 UUID
// over the file's exact bytes.
//
// Content-addressed, so re-importing the same file resolves to the same build
// and the second import is a no-op rather than a duplicate. An EDITED file
// hashes differently and imports as a new build, which is the honest answer —
// it is different content, and the app cannot know whether the edit was a fix
// or a fork.
func BuildUUIDForFile(content []byte) string {
	sum := sha256.Sum256(content)
	return uuid.NewSHA1(buildNamespace, []byte(hex.EncodeToString(sum[:]))).String()
}

// ImportFile imports one .ddogearset into app.db.
//
// Additive and idempotent: a build that is already present is left completely
// alone and reported as StatusAlreadyImported. It is never updated in place,
// because the row may have been edited in the app since it was imported and the
// file cannot know that. Re-import is not a sync.
func ImportFile(app *sql.DB, catalog Catalog, path, appVersion string) ImportOutcome {
	content, err := os.ReadFile(path)
	if err != nil {
		return ImportOutcome{SourceFile: path, Status: StatusFailed,
			Error: fmt.Sprintf("reading %s: %v", path, err)}
	}
	return ImportContent(app, catalog, content, path, appVersion)
}

// ImportContent is ImportFile for callers that already hold the bytes.
//
// The frontend is one: its file picker is a browser <input type="file">, which
// yields content and never a filesystem path. `sourceLabel` is recorded as the
// provenance and is a filename in that case rather than a path — it is for
// telling a human where a build came from, not for reading anything back.
func ImportContent(app *sql.DB, catalog Catalog, content []byte,
	sourceLabel, appVersion string) ImportOutcome {
	out := ImportOutcome{SourceFile: sourceLabel, Status: StatusFailed}

	var saved savedGearset
	if err := json.Unmarshal(content, &saved); err != nil {
		out.Error = fmt.Sprintf("%s is not a readable .ddogearset: %v", sourceLabel, err)
		return out
	}
	path := sourceLabel

	out.BuildUUID = BuildUUIDForFile(content)
	out.BuildName = buildName(saved, path)

	var exists int
	if err := app.QueryRow("SELECT count(*) FROM build WHERE uuid = ?", out.BuildUUID).Scan(&exists); err != nil {
		out.Error = fmt.Sprintf("checking for an existing build: %v", err)
		return out
	}
	if exists > 0 {
		out.Status = StatusAlreadyImported
		return out
	}

	tx, err := app.Begin()
	if err != nil {
		out.Error = fmt.Sprintf("starting transaction: %v", err)
		return out
	}
	defer tx.Rollback() //nolint:errcheck // no-op after a successful Commit

	orphans, err := writeBuild(tx, catalog, saved, out.BuildUUID, out.BuildName, path, appVersion, "")
	if err != nil {
		out.Error = err.Error()
		return out
	}
	if err := tx.Commit(); err != nil {
		out.Error = fmt.Sprintf("committing import: %v", err)
		return out
	}

	out.Orphans = orphans
	out.Status = StatusImported
	return out
}

func buildName(saved savedGearset, path string) string {
	if n := strings.TrimSpace(saved.GearsetName); n != "" {
		return n
	}
	if cfg := saved.Config; cfg != nil {
		if n, _ := cfg["gearset_name"].(string); strings.TrimSpace(n) != "" {
			return strings.TrimSpace(n)
		}
	}
	base := path
	if i := strings.LastIndexAny(base, "/\\"); i >= 0 {
		base = base[i+1:]
	}
	return strings.TrimSuffix(base, ".ddogearset")
}

// writeBuild inserts a build and everything hanging off it.
//
// The single writer for BOTH entry points — ImportFile and SaveBuild. They
// differ only in where the content came from and what identity it gets; the
// mapping from a config map to rows is one implementation on purpose, because
// two would drift and the drift would show up as an export that no longer
// round-trips.
//
// `importedFrom` is the source path for an import and nil for a save.
func writeBuild(tx *sql.Tx, catalog Catalog, saved savedGearset,
	buildUUID, name string, importedFrom interface{}, appVersion, createdAt string) ([]Orphan, error) {

	cfg := saved.Config
	if cfg == nil {
		cfg = map[string]interface{}{}
	}
	savedAt := createdAt
	if savedAt == "" {
		savedAt = saved.SavedAt
	}
	if savedAt == "" {
		savedAt = nowRFC3339()
	}
	fileAppVersion := saved.AppVersion
	if fileAppVersion == "" {
		fileAppVersion = appVersion
	}
	if fileAppVersion == "" {
		fileAppVersion = "unknown"
	}

	_, err := tx.Exec(`
		INSERT INTO build (uuid, name, created_at, updated_at, app_version,
			imported_from, max_level, build_type, weapon_style, offhand_style,
			weapon_damage_type, swashbuckling, runearm_use, armor_restriction,
			reserved_minor_artifact_slot, minor_artifact_filigree_slots,
			is_dino_artifact, exclude_gem_of_many_facets, raid_item_limit,
			caster_restrict_weapon_families, max_search_time)
		VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?, ?,?,?, ?,?)`,
		buildUUID, name, savedAt, savedAt, fileAppVersion,
		importedFrom,
		intOr(cfg, "max_level", 34), stringOr(cfg, "build_type", ""),
		nullString(stringOr(cfg, "weapon_style", "")),
		nullString(stringOr(cfg, "offhand_style", "")),
		nullString(stringOr(cfg, "weapon_damage_type", "")),
		boolOr(cfg, "swashbuckling", false), boolOr(cfg, "runearm_use", false),
		nullString(stringOr(cfg, "armor_restriction", "")),
		nullString(stringOr(cfg, "reserved_minor_artifact_slot", "")),
		intOr(cfg, "minor_artifact_filigree_slots", 4),
		boolOr(cfg, "is_dino_artifact", false),
		boolOr(cfg, "exclude_gem_of_many_facets", false),
		intOr(cfg, "raid_item_limit", -1),
		// Absent means TRUE, matching solver.py's own default for an old saved
		// file — the Go zero value would silently opt every legacy build out.
		boolOr(cfg, "caster_restrict_weapon_families", true),
		intOr(cfg, "max_search_time", 0),
	)
	if err != nil {
		return nil, fmt.Errorf("inserting build: %w", err)
	}

	if err := insertPriorities(tx, buildUUID, cfg); err != nil {
		return nil, err
	}
	if err := insertStringList(tx, buildUUID, cfg, "excluded_packs",
		"INSERT OR IGNORE INTO build_excluded_pack (build_uuid, pack) VALUES (?,?)"); err != nil {
		return nil, err
	}
	for key, kind := range map[string]string{
		"caster_spellpowers": "spellpower", "caster_schools": "school"} {
		for _, v := range stringList(cfg, key) {
			if _, err := tx.Exec(
				"INSERT OR IGNORE INTO build_caster_option (build_uuid, kind, value) VALUES (?,?,?)",
				buildUUID, kind, v); err != nil {
				return nil, fmt.Errorf("inserting caster option: %w", err)
			}
		}
	}

	return insertGearset(tx, catalog, buildUUID, saved)
}

func insertPriorities(tx *sql.Tx, buildUUID string, cfg map[string]interface{}) error {
	raw, _ := cfg["stat_priorities"].([]interface{})
	position := 0
	for _, entry := range raw {
		e, ok := entry.(map[string]interface{})
		if !ok {
			continue
		}
		text, _ := e["stat"].(string)
		if strings.TrimSpace(text) == "" {
			continue
		}
		tier := intOr(e, "tier", 0)
		if tier < 1 || tier > 5 {
			// Legacy "Shape B" files carry `value` instead of `tier`. The
			// migration from value to tier lives in solver.py's
			// parse_stat_priorities and is NOT duplicated here — a second
			// implementation of a rule is how the two drift. Park it in the
			// lowest tier so the priority survives the import; Phase 2 routes
			// these through the real migration when it wires the app up.
			tier = 5
		}
		var cap interface{}
		if c, present := e["cap"]; present && c != nil {
			cap = c
		}
		if _, err := tx.Exec(
			"INSERT INTO build_priority (build_uuid, position, raw_text, tier, cap) VALUES (?,?,?,?,?)",
			buildUUID, position, text, tier, cap); err != nil {
			return fmt.Errorf("inserting priority %q: %w", text, err)
		}
		position++
	}
	return nil
}

func insertStringList(tx *sql.Tx, buildUUID string, cfg map[string]interface{},
	key, query string) error {
	for _, v := range stringList(cfg, key) {
		if _, err := tx.Exec(query, buildUUID, v); err != nil {
			return fmt.Errorf("inserting %s %q: %w", key, v, err)
		}
	}
	return nil
}

// insertGearset writes the file's gearset as origin='equipped'.
//
// A .ddogearset records ONE gearset, and after a save that gearset is what the
// user has — so it is `equipped`, not `suggested`. Nothing imports as a
// suggestion: a suggestion is the live output of a solve (Phase 3), and
// resurrecting a years-old one as if it were pending would be inventing state
// the file never claimed.
//
// Where the gearset lives in the file varies by how it was saved: pinned into
// `config.pre_equipped`, or only in `result.gearSet` when a solve was saved
// without writing the picks back. Real files exist in both shapes — the same
// survey scripts/capture_oracle.py's reconstruct_gearset was written from, and
// the same precedence.
func insertGearset(tx *sql.Tx, catalog Catalog, buildUUID string, saved savedGearset) ([]Orphan, error) {
	var orphans []Orphan
	cfg := saved.Config
	if cfg == nil {
		cfg = map[string]interface{}{}
	}
	result := saved.Result
	if result == nil {
		result = map[string]interface{}{}
	}

	items := stringMap(cfg, "pre_equipped")
	if len(items) == 0 {
		items = stringMap(result, "gearSet")
	}
	for _, slot := range sortedKeys(items) {
		itemName := items[slot]
		if strings.TrimSpace(itemName) == "" {
			continue
		}
		itemUUID, ok := catalog.ItemUUID(itemName)
		if !ok {
			orphans = append(orphans, Orphan{Kind: "item", Slot: slot, Name: itemName,
				Detail: "no item of this name in the catalog"})
			// Recorded, then SKIPPED: gearset_slot.item_uuid is NOT NULL, and
			// inventing a placeholder UUID would put a value in the join key
			// that resolves to nothing. orphan_reference is where it lives.
			if err := recordOrphan(tx, buildUUID, "item", slot, itemName,
				"no item of this name in the catalog"); err != nil {
				return nil, err
			}
			continue
		}
		if _, err := tx.Exec(`INSERT INTO gearset_slot
			(build_uuid, origin, slot, item_uuid, item_name) VALUES (?,'equipped',?,?,?)`,
			buildUUID, slot, itemUUID, itemName); err != nil {
			return nil, fmt.Errorf("inserting slot %s: %w", slot, err)
		}
	}

	augOrphans, err := insertAugments(tx, catalog, buildUUID, cfg, result)
	if err != nil {
		return nil, err
	}
	orphans = append(orphans, augOrphans...)

	filOrphans, err := insertFiligrees(tx, catalog, buildUUID, cfg, result)
	if err != nil {
		return nil, err
	}
	orphans = append(orphans, filOrphans...)

	return orphans, nil
}

func insertAugments(tx *sql.Tx, catalog Catalog, buildUUID string,
	cfg, result map[string]interface{}) ([]Orphan, error) {
	var orphans []Orphan

	// slot -> colour -> name. Older files stored a plain list of names per
	// slot instead; solver.py normalizes both shapes and so does this — a
	// listed augment has no recorded colour, which AugmentUUID's unique-name
	// fallback handles.
	perSlot := map[string]map[string]string{}
	for slot, raw := range mapOf(cfg, "pre_filled_augments") {
		switch v := raw.(type) {
		case map[string]interface{}:
			for colour, name := range v {
				if s, _ := name.(string); s != "" {
					setNested(perSlot, slot, colour, s)
				}
			}
		case []interface{}:
			for _, name := range v {
				if s, _ := name.(string); s != "" {
					setNested(perSlot, slot, "", s)
				}
			}
		}
	}
	if len(perSlot) == 0 {
		for slot, raw := range mapOf(result, "slots") {
			sd, _ := raw.(map[string]interface{})
			list, _ := sd["augments"].([]interface{})
			for _, a := range list {
				am, _ := a.(map[string]interface{})
				name, _ := am["name"].(string)
				colour, _ := am["color"].(string)
				if name != "" {
					setNested(perSlot, slot, colour, name)
				}
			}
		}
	}

	for _, slot := range sortedKeys2(perSlot) {
		for _, colour := range sortedKeys(perSlot[slot]) {
			name := perSlot[slot][colour]
			augUUID, ok := catalog.AugmentUUID(name, colour)
			if !ok {
				detail := "no augment of this name in the catalog"
				if colour != "" {
					detail = fmt.Sprintf("no augment %q in a %q slot", name, colour)
				}
				orphans = append(orphans, Orphan{Kind: "augment", Slot: slot, Name: name, Detail: detail})
				if err := recordOrphan(tx, buildUUID, "augment", slot, name, detail); err != nil {
					return nil, err
				}
				continue
			}
			if _, err := tx.Exec(`INSERT OR IGNORE INTO gearset_augment
				(build_uuid, origin, slot, colour, augment_uuid, augment_name)
				VALUES (?,'equipped',?,?,?,?)`,
				buildUUID, slot, colour, augUUID, name); err != nil {
				return nil, fmt.Errorf("inserting augment %s/%s: %w", slot, name, err)
			}
		}
	}
	return orphans, nil
}

func insertFiligrees(tx *sql.Tx, catalog Catalog, buildUUID string,
	cfg, result map[string]interface{}) ([]Orphan, error) {
	var orphans []Orphan

	buckets := map[string][]string{}
	for _, bucket := range []string{"weapon", "artifact"} {
		buckets[bucket] = stringSlice(mapOf(cfg, "pre_filled_filigrees")[bucket])
	}
	if len(buckets["weapon"])+len(buckets["artifact"]) == 0 {
		for _, bucket := range []string{"weapon", "artifact"} {
			buckets[bucket] = stringSlice(mapOf(result, "filigrees")[bucket])
		}
	}

	for _, bucket := range []string{"artifact", "weapon"} {
		// `position` is the array index, and it is STORAGE, not semantics —
		// nothing may read meaning into a filigree's index. 0.5.1 Phase 0
		// measured this list reordering wholesale between the XML and catalog
		// eras without a single number changing
		// (python/tests/fixtures/known_deltas.yaml).
		position := 0
		for _, name := range buckets[bucket] {
			if strings.TrimSpace(name) == "" {
				// Empty entries are real in saved files — a known corruption
				// class (capture_oracle.py's `empty-filigree-entry`). Dropped
				// rather than stored: an empty string is not a filigree.
				continue
			}
			filUUID, ok := catalog.FiligreeUUID(name)
			if !ok {
				orphans = append(orphans, Orphan{Kind: "filigree", Name: name,
					Detail: "no filigree of this name in the catalog"})
				if err := recordOrphan(tx, buildUUID, "filigree", bucket, name,
					"no filigree of this name in the catalog"); err != nil {
					return nil, err
				}
				continue
			}
			if _, err := tx.Exec(`INSERT INTO gearset_filigree
				(build_uuid, origin, bucket, position, filigree_uuid, filigree_name)
				VALUES (?,'equipped',?,?,?,?)`,
				buildUUID, bucket, position, filUUID, name); err != nil {
				return nil, fmt.Errorf("inserting filigree %s[%d]: %w", bucket, position, err)
			}
			position++
		}
	}
	return orphans, nil
}

func recordOrphan(tx *sql.Tx, buildUUID, kind, slot, name, detail string) error {
	_, err := tx.Exec(`INSERT OR IGNORE INTO orphan_reference
		(build_uuid, kind, slot, name, detail) VALUES (?,?,?,?,?)`,
		buildUUID, kind, slot, name, detail)
	if err != nil {
		return fmt.Errorf("recording orphan %s %q: %w", kind, name, err)
	}
	return nil
}

// --- small JSON accessors --------------------------------------------------
// The saved files are read as generic maps (see savedGearset), so these carry
// the "absent, wrong type, or null" handling in one place instead of at every
// call site.

func stringOr(m map[string]interface{}, key, fallback string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return fallback
}

func intOr(m map[string]interface{}, key string, fallback int) int {
	switch v := m[key].(type) {
	case float64: // every JSON number arrives as float64
		return int(v)
	case int:
		return v
	}
	return fallback
}

func boolOr(m map[string]interface{}, key string, fallback bool) bool {
	if v, ok := m[key].(bool); ok {
		return v
	}
	return fallback
}

func nullString(s string) interface{} {
	if s == "" {
		return nil
	}
	return s
}

func stringList(m map[string]interface{}, key string) []string {
	return stringSlice(m[key])
}

func stringSlice(raw interface{}) []string {
	list, _ := raw.([]interface{})
	out := make([]string, 0, len(list))
	for _, v := range list {
		if s, ok := v.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func mapOf(m map[string]interface{}, key string) map[string]interface{} {
	v, _ := m[key].(map[string]interface{})
	if v == nil {
		return map[string]interface{}{}
	}
	return v
}

func stringMap(m map[string]interface{}, key string) map[string]string {
	out := map[string]string{}
	for k, v := range mapOf(m, key) {
		if s, ok := v.(string); ok {
			out[k] = s
		}
	}
	return out
}

func setNested(m map[string]map[string]string, outer, inner, value string) {
	if m[outer] == nil {
		m[outer] = map[string]string{}
	}
	m[outer][inner] = value
}

// Map iteration order is random in Go, and these drive INSERT order. Sorting
// keeps an import of the same file byte-identical across runs, which is what
// makes "importing twice changes nothing" checkable rather than merely likely.
func sortedKeys(m map[string]string) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func sortedKeys2(m map[string]map[string]string) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
