package main

// Content-integrity checksum for saved .ddogearset files — detects a file
// edited outside the app (by hand, by another tool, disk corruption) between
// save and load. Not a security mechanism (no secret key — anyone with the
// source can recompute a valid checksum for tampered content); it's a
// tripwire for accidental external changes, matching the "warn, never
// refuse" policy already established for the app_version check (see
// Summary.svelte's loadGearset()).

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
)

// gearsetChecksum computes the deterministic SHA-256 checksum of a
// .ddogearset save's content, excluding the "checksum" field itself. Both
// SaveGearset and VerifyGearsetChecksum call this exact function so the two
// can never drift out of sync with each other.
//
// `data` may be any JSON-marshalable value — a struct-typed map built fresh
// at save time, or a map[string]interface{} parsed from a file at verify
// time. It is always normalized by round-tripping through encoding/json
// before hashing: Go's json.Marshal sorts map[string]interface{} keys but
// does NOT reorder struct fields (it uses declaration order), so hashing a
// typed struct (as SaveGearset's payload/result fields are) directly would
// never byte-match hashing that same content after it comes back from
// json.Unmarshal into a generic map (as VerifyGearsetChecksum's input
// always is, reading a file from disk). Normalizing both sides through the
// same marshal→unmarshal→marshal pipeline guarantees save and verify always
// hash the exact same canonical byte sequence regardless of which Go type
// the caller started with.
func gearsetChecksum(data interface{}) (string, error) {
	raw, err := json.Marshal(data)
	if err != nil {
		return "", err
	}
	var normalized map[string]interface{}
	if err := json.Unmarshal(raw, &normalized); err != nil {
		return "", err
	}
	delete(normalized, "checksum")
	canonical, err := json.Marshal(normalized)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(canonical)
	return hex.EncodeToString(sum[:]), nil
}

// GearsetChecksumResult reports whether a loaded .ddogearset file's content
// still matches the checksum stamped into it at save time.
type GearsetChecksumResult struct {
	// HasChecksum is false for files saved before this feature existed —
	// there is nothing to check, which is NOT the same as an invalid
	// checksum. The frontend must treat these differently (no warning, vs. a
	// loud one for a genuine mismatch).
	HasChecksum bool `json:"hasChecksum"`
	Valid       bool `json:"valid"`
}

// VerifyGearsetChecksum re-derives a saved gearset's content checksum from
// its raw file text (as read client-side via FileReader — see
// Summary.svelte's loadGearset(), matching how the file is already read for
// parsing) and compares it to the "checksum" field stored inside. Uses the
// exact same gearsetChecksum() function SaveGearset writes with, so this can
// never disagree with what was actually saved. A malformed/non-JSON
// fileContent is returned as an error — the caller (loadGearset) already has
// its own JSON.parse error handling for that case.
func (a *App) VerifyGearsetChecksum(fileContent string) (GearsetChecksumResult, error) {
	var parsed map[string]interface{}
	if err := json.Unmarshal([]byte(fileContent), &parsed); err != nil {
		return GearsetChecksumResult{}, err
	}

	stored, ok := parsed["checksum"].(string)
	if !ok || stored == "" {
		return GearsetChecksumResult{HasChecksum: false, Valid: false}, nil
	}

	recomputed, err := gearsetChecksum(parsed)
	if err != nil {
		return GearsetChecksumResult{}, err
	}
	return GearsetChecksumResult{HasChecksum: true, Valid: recomputed == stored}, nil
}
