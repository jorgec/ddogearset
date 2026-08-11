package appdb

import (
	"database/sql"
	"fmt"

	"github.com/google/uuid"
)

// RunRecord is one invocation of the solver or the recalculator, as it happened.
//
// History, not state. Nothing reads a run to decide what a build IS — that is
// what `gearset_slot` is for. A run answers "what did this produce, when, and
// against which catalog", which is the question that becomes unanswerable the
// moment a catalog update moves a number and nobody can say whether the gear
// changed or the data did.
type RunRecord struct {
	UUID          string  `json:"uuid"`
	BuildUUID     string  `json:"buildUuid"`
	Mode          string  `json:"mode"`
	RanAt         string  `json:"ranAt"`
	AppVersion    string  `json:"appVersion"`
	CatalogCommit string  `json:"catalogCommit,omitempty"`
	Seconds       float64 `json:"seconds"`
	Succeeded     bool    `json:"succeeded"`
	ErrorMessage  string  `json:"errorMessage,omitempty"`
}

// RunOutcome is what a run produced, in the shape the result payload uses.
// Passed as generic maps for the same reason SaveBuild takes one: appdb stays
// independent of the app's wire types.
type RunOutcome struct {
	RealizedStats map[string]float64
	OtherStats    map[string]float64
	ActiveSets    []string
	// EffectDetail is allEffectsDetail: stat -> [{value, bonusType, sourceName, sourceKind}].
	EffectDetail map[string][]map[string]interface{}
	Warnings     []map[string]interface{}
}

// RecordRun writes a run and everything it produced, in ONE transaction.
//
// All or nothing is the invariant this exists to hold (plan §2.1: "an empty or
// failed result must never overwrite saved stats"). A half-written run — the
// header committed, the stats lost to an error partway through — is a run that
// claims to have succeeded while reporting nothing, which is worse than no
// record at all.
//
// A FAILED run is still recorded, with `succeeded = 0`, its error message, and
// no stat rows. That is the point of keeping history: "it failed at 14:03
// against catalog c8f21a" is exactly what you want six weeks later, and it is
// the part people omit because a failure feels like nothing to store.
func RecordRun(db *sql.DB, run RunRecord, outcome *RunOutcome) (string, error) {
	if run.UUID == "" {
		run.UUID = uuid.NewString()
	}
	if run.RanAt == "" {
		run.RanAt = nowRFC3339()
	}

	tx, err := db.Begin()
	if err != nil {
		return "", fmt.Errorf("starting transaction: %w", err)
	}
	defer tx.Rollback() //nolint:errcheck // no-op after a successful Commit

	var catalogCommit interface{}
	if run.CatalogCommit != "" {
		catalogCommit = run.CatalogCommit
	}
	var errorMessage interface{}
	if run.ErrorMessage != "" {
		errorMessage = run.ErrorMessage
	}
	succeeded := 0
	if run.Succeeded {
		succeeded = 1
	}

	if _, err := tx.Exec(`INSERT INTO run
		(uuid, build_uuid, mode, ran_at, app_version, catalog_commit, seconds,
		 succeeded, error_message)
		VALUES (?,?,?,?,?,?,?,?,?)`,
		run.UUID, run.BuildUUID, run.Mode, run.RanAt, run.AppVersion,
		catalogCommit, run.Seconds, succeeded, errorMessage); err != nil {
		return "", fmt.Errorf("recording run: %w", err)
	}

	if outcome != nil {
		if err := writeOutcome(tx, run.UUID, outcome); err != nil {
			return "", err
		}
	}

	if err := tx.Commit(); err != nil {
		return "", fmt.Errorf("committing run: %w", err)
	}
	return run.UUID, nil
}

func writeOutcome(tx *sql.Tx, runUUID string, outcome *RunOutcome) error {
	for _, group := range []struct {
		stats      map[string]float64
		isPriority int
	}{
		{outcome.RealizedStats, 1},
		{outcome.OtherStats, 0},
	} {
		for name, value := range group.stats {
			// INSERT OR IGNORE: a name appearing in both realized and other
			// would otherwise abort the run over a reporting quirk. Realized
			// wins because it is written first — the user's own spelling.
			if _, err := tx.Exec(`INSERT OR IGNORE INTO run_stat
				(run_uuid, display_name, value, is_priority) VALUES (?,?,?,?)`,
				runUUID, name, value, group.isPriority); err != nil {
				return fmt.Errorf("recording stat %q: %w", name, err)
			}
		}
	}

	position := 0
	for stat, effects := range outcome.EffectDetail {
		for _, e := range effects {
			value, _ := e["value"].(float64)
			bonusType, _ := e["bonusType"].(string)
			sourceName, _ := e["sourceName"].(string)
			sourceKind, _ := e["sourceKind"].(string)
			if _, err := tx.Exec(`INSERT INTO run_effect
				(run_uuid, position, stat_name, bonus_type, value, source_name, source_kind)
				VALUES (?,?,?,?,?,?,?)`,
				runUUID, position, stat, bonusType, value, sourceName,
				nullString(sourceKind)); err != nil {
				return fmt.Errorf("recording effect for %q: %w", stat, err)
			}
			position++
		}
	}

	for _, active := range outcome.ActiveSets {
		name, pieces := parseActiveSet(active)
		if name == "" {
			continue
		}
		// INSERT OR IGNORE, and the primary key does the deduplication: the
		// catalog genuinely holds several separate rows for one (set, piece
		// count) — 212 of 965 measured in 0.5.0 — and they describe ONE active
		// tier. No application-side dedup, per schema §5.4.
		if _, err := tx.Exec(`INSERT OR IGNORE INTO run_active_set
			(run_uuid, set_name, piece_count) VALUES (?,?,?)`,
			runUUID, name, pieces); err != nil {
			return fmt.Errorf("recording active set %q: %w", active, err)
		}
	}

	for i, w := range outcome.Warnings {
		message, _ := w["message"].(string)
		kind, _ := w["kind"].(string)
		slot, _ := w["slot"].(string)
		if message == "" {
			continue
		}
		if _, err := tx.Exec(`INSERT INTO run_warning
			(run_uuid, position, kind, slot, message) VALUES (?,?,?,?,?)`,
			runUUID, i, nullString(kind), nullString(slot), message); err != nil {
			return fmt.Errorf("recording warning: %w", err)
		}
	}
	return nil
}

// parseActiveSet splits "Zarigan's Arcane Enlightenment (3-piece)".
//
// Right-most " (" so a set whose NAME contains parentheses still splits
// correctly — "Legendary Soul of the Red Dragon (2 Piece)" is exactly the shape
// that breaks a naive left-to-right split.
func parseActiveSet(label string) (string, int) {
	end := len(label)
	if end == 0 || label[end-1] != ')' {
		return label, 0
	}
	open := -1
	for i := end - 2; i >= 0; i-- {
		if label[i] == '(' {
			open = i
			break
		}
	}
	if open <= 0 {
		return label, 0
	}
	inner := label[open+1 : end-1]
	pieces := 0
	for _, r := range inner {
		if r >= '0' && r <= '9' {
			pieces = pieces*10 + int(r-'0')
			continue
		}
		break
	}
	name := label[:open]
	for len(name) > 0 && name[len(name)-1] == ' ' {
		name = name[:len(name)-1]
	}
	return name, pieces
}

// ListRuns returns a build's history, newest first.
func ListRuns(db *sql.DB, buildUUID string, limit int) ([]RunRecord, error) {
	if limit <= 0 {
		limit = 50
	}
	rows, err := db.Query(`
		SELECT uuid, build_uuid, mode, ran_at, app_version,
		       COALESCE(catalog_commit,''), COALESCE(seconds,0), succeeded,
		       COALESCE(error_message,'')
		  FROM run WHERE build_uuid = ? ORDER BY ran_at DESC LIMIT ?`,
		buildUUID, limit)
	if err != nil {
		return nil, fmt.Errorf("listing runs: %w", err)
	}
	defer rows.Close()

	out := []RunRecord{}
	for rows.Next() {
		var r RunRecord
		var succeeded int
		if err := rows.Scan(&r.UUID, &r.BuildUUID, &r.Mode, &r.RanAt, &r.AppVersion,
			&r.CatalogCommit, &r.Seconds, &succeeded, &r.ErrorMessage); err != nil {
			return nil, fmt.Errorf("reading run: %w", err)
		}
		r.Succeeded = succeeded != 0
		out = append(out, r)
	}
	return out, rows.Err()
}

// RunStats returns the stats a run produced, keyed by display name.
func RunStats(db *sql.DB, runUUID string) (map[string]float64, map[string]float64, error) {
	rows, err := db.Query(
		"SELECT display_name, value, is_priority FROM run_stat WHERE run_uuid = ?",
		runUUID)
	if err != nil {
		return nil, nil, fmt.Errorf("reading run stats: %w", err)
	}
	defer rows.Close()

	realized, other := map[string]float64{}, map[string]float64{}
	for rows.Next() {
		var name string
		var value float64
		var isPriority int
		if err := rows.Scan(&name, &value, &isPriority); err != nil {
			return nil, nil, err
		}
		if isPriority != 0 {
			realized[name] = value
		} else {
			other[name] = value
		}
	}
	return realized, other, rows.Err()
}
