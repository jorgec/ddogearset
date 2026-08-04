package main

import (
	"encoding/json"
	"testing"
)

// Phase 10 wire-contract tests. These pin the JSON shapes that python/solver.py
// (parse_stat_priorities, normalize_mode) and python/optimizer.py
// (solve_tiered / find_slot_alternatives output assembly) actually read and
// emit. If a field name or tag changes here it must change in all three legs —
// Go struct, Python payload parsing, TS types (docs/PHASE9_PLAN.md Phase 9.2).

func TestStatPriorityEntry_TieredShapeMarshalsAsShapeC(t *testing.T) {
	cap50 := 50
	entries := []StatPriorityEntry{
		{Stat: "Ranged Power", Tier: 1},
		{Stat: "Doubleshot", Tier: 1},
		{Stat: "Melee Power", Tier: 3, Cap: &cap50},
	}

	got, err := json.Marshal(entries)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	want := `[{"stat":"Ranged Power","tier":1},{"stat":"Doubleshot","tier":1},{"stat":"Melee Power","tier":3,"cap":50}]`
	if string(got) != want {
		t.Errorf("stat_priorities wire shape\n got: %s\nwant: %s", got, want)
	}
}

// A legacy .ddogearset carries only `value`. It must round-trip WITHOUT a
// `tier` key, because solver.py detects the new format by the presence of a
// `tier` key on any element and rejects a Shape-C list containing an element
// that lacks one. Emitting "tier":0 here would turn every legacy load into a
// validation failure.
func TestStatPriorityEntry_LegacyValueRoundTripsWithoutTier(t *testing.T) {
	const legacy = `[{"stat":"Constitution","value":100},{"stat":"Melee Power[50]","value":60}]`

	var entries []StatPriorityEntry
	if err := json.Unmarshal([]byte(legacy), &entries); err != nil {
		t.Fatalf("unmarshal legacy: %v", err)
	}
	if len(entries) != 2 || entries[0].Value != 100 || entries[0].Tier != 0 {
		t.Fatalf("unexpected legacy parse: %+v", entries)
	}

	got, err := json.Marshal(entries)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if string(got) != legacy {
		t.Errorf("legacy round trip\n got: %s\nwant: %s", got, legacy)
	}

	var reparsed []map[string]any
	if err := json.Unmarshal(got, &reparsed); err != nil {
		t.Fatalf("reparse: %v", err)
	}
	for i, e := range reparsed {
		if _, ok := e["tier"]; ok {
			t.Errorf("entry %d leaked a tier key into a legacy payload: %v", i, e)
		}
	}
}

// Cap is a pointer so "no cap" and "cap 0" are distinguishable; cap 0 is a
// validation error on the Python side and must therefore reach it intact.
func TestStatPriorityEntry_ZeroCapIsDistinctFromNoCap(t *testing.T) {
	zero := 0
	withZero, _ := json.Marshal(StatPriorityEntry{Stat: "X", Tier: 1, Cap: &zero})
	withNone, _ := json.Marshal(StatPriorityEntry{Stat: "X", Tier: 1})

	if string(withZero) != `{"stat":"X","tier":1,"cap":0}` {
		t.Errorf("cap 0 not preserved: %s", withZero)
	}
	if string(withNone) != `{"stat":"X","tier":1}` {
		t.Errorf("absent cap should be omitted: %s", withNone)
	}
}

func TestOptimizationPayload_MaxSearchTimeAndModeReachTheWire(t *testing.T) {
	raw, err := json.Marshal(OptimizationPayload{MaxSearchTime: 120, Mode: "optimize"})
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var got map[string]any
	if err := json.Unmarshal(raw, &got); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if v, ok := got["max_search_time"]; !ok || v.(float64) != 120 {
		t.Errorf("max_search_time missing or wrong: %v", got["max_search_time"])
	}
	if got["mode"] != "optimize" {
		t.Errorf("mode missing or wrong: %v", got["mode"])
	}
}

// AlternativesPayload embeds OptimizationPayload, so the solver must receive
// the data-filtering fields inline alongside the alternatives-specific ones.
func TestAlternativesPayload_EmbedsOptimizationPayloadInline(t *testing.T) {
	p := AlternativesPayload{
		OptimizationPayload: OptimizationPayload{MaxLevel: 34, Mode: "alternatives"},
		TargetSlot:          "Ring_1",
		CurrentItem:         "Some Ring",
		EquippedItems:       map[string]string{"Helmet": "Some Helm"},
		Count:               5,
	}
	raw, err := json.Marshal(p)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var got map[string]any
	if err := json.Unmarshal(raw, &got); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	for _, key := range []string{"max_level", "mode", "target_slot", "current_item", "equipped_items", "count"} {
		if _, ok := got[key]; !ok {
			t.Errorf("alternatives payload is missing %q: %v", key, got)
		}
	}
}

// Mirrors the §9 output assembly in optimizer.py's rich_output.
func TestResultPayload_UnmarshalsPhase10Fields(t *testing.T) {
	const solverOutput = `{
      "gearSet": {"Helmet": "Some Helm"},
      "realizedStats": {"Melee Power": 42},
      "slots": {},
      "tierReport": {
        "stages": [
          {"tier":1,"goalValue":0.8734,"status":"optimal","proven":true,
           "budgetSeconds":21.0,"elapsedSeconds":8.2,"folded":[]},
          {"tier":3,"goalValue":null,"status":"no_incumbent","proven":false,
           "budgetSeconds":27.8,"elapsedSeconds":27.8,"folded":[3]}
        ],
        "consolidation": {"status":"restored","elapsedSeconds":3.1,
                          "itemsEquipped":12,"duplicateSources":4},
        "reconciliation": {"status":"optimal","elapsedSeconds":0.3},
        "totalElapsedSeconds": 39.4,
        "degraded": true,
        "notes": ["a note"]
      },
      "tierScores": {"1": 0.8734, "3": 0.4102},
      "priorityTiers": {"Ranged Power": 1, "Melee Power": 3},
      "unmetTier4": ["Constitution"],
      "unmatchedPriorities": ["Typoed Stat"]
    }`

	var r ResultPayload
	if err := json.Unmarshal([]byte(solverOutput), &r); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	if r.TierReport == nil {
		t.Fatal("tierReport did not unmarshal")
	}
	if len(r.TierReport.Stages) != 2 {
		t.Fatalf("want 2 stages, got %d", len(r.TierReport.Stages))
	}
	if r.TierReport.Stages[0].GoalValue == nil || *r.TierReport.Stages[0].GoalValue != 0.8734 {
		t.Errorf("stage 0 goalValue: %v", r.TierReport.Stages[0].GoalValue)
	}
	// A stage with no incumbent reports a null goalValue; the pointer keeps
	// that distinguishable from a genuine 0.0.
	if r.TierReport.Stages[1].GoalValue != nil {
		t.Errorf("stage 1 goalValue should be nil, got %v", *r.TierReport.Stages[1].GoalValue)
	}
	if len(r.TierReport.Stages[1].Folded) != 1 || r.TierReport.Stages[1].Folded[0] != 3 {
		t.Errorf("folded: %v", r.TierReport.Stages[1].Folded)
	}
	if r.TierReport.Consolidation == nil || r.TierReport.Consolidation.DuplicateSources != 4 {
		t.Errorf("consolidation: %+v", r.TierReport.Consolidation)
	}
	if r.TierReport.Reconciliation == nil || r.TierReport.Reconciliation.Status != "optimal" {
		t.Errorf("reconciliation: %+v", r.TierReport.Reconciliation)
	}
	if !r.TierReport.Degraded || r.TierReport.TotalElapsedSeconds != 39.4 {
		t.Errorf("report scalars: %+v", r.TierReport)
	}
	if r.TierScores["1"] != 0.8734 || r.TierScores["3"] != 0.4102 {
		t.Errorf("tierScores: %v", r.TierScores)
	}
	if r.PriorityTiers["Melee Power"] != 3 {
		t.Errorf("priorityTiers: %v", r.PriorityTiers)
	}
	if len(r.UnmetTier4) != 1 || r.UnmetTier4[0] != "Constitution" {
		t.Errorf("unmetTier4: %v", r.UnmetTier4)
	}
	if len(r.UnmatchedPriorities) != 1 || r.UnmatchedPriorities[0] != "Typoed Stat" {
		t.Errorf("unmatchedPriorities: %v", r.UnmatchedPriorities)
	}
}

// Calculate mode skips every tier stage and the consolidation stage by design.
func TestResultPayload_CalculateModeTierReport(t *testing.T) {
	const out = `{"gearSet":{},"tierReport":{"stages":[],"consolidation":null,
      "reconciliation":{"status":"optimal","elapsedSeconds":0.2},
      "totalElapsedSeconds":0.2,"degraded":false,"notes":[]},"tierScores":{}}`

	var r ResultPayload
	if err := json.Unmarshal([]byte(out), &r); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if r.TierReport == nil || len(r.TierReport.Stages) != 0 || r.TierReport.Consolidation != nil {
		t.Errorf("calculate-mode report: %+v", r.TierReport)
	}
}

// Mirrors find_slot_alternatives' output assembly in optimizer.py.
func TestAlternativesResult_UnmarshalsSolverOutput(t *testing.T) {
	const out = `{
      "success": true,
      "slot": "Ring_1",
      "baselineTierScores": {"1": 0.5, "3": 0.25},
      "alternatives": [
        {"rank":1,"itemName":"Better Ring","slot":"Ring_1","ml":34,"isRaid":true,
         "tierScores":{"1":0.7,"3":0.25},"objectiveScore":7025.0,
         "statDeltas":{"Melee Power":12.0,"Doubleshot":-3.0},
         "augments":[{"color":"Green","name":"Some Augment"}],
         "filigrees":{"weapon":[],"artifact":[]}}
      ],
      "warnings": ["Equipped item 'X' for slot 'Y' was not found in the data files and was ignored."]
    }`

	var r AlternativesResult
	if err := json.Unmarshal([]byte(out), &r); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if !r.Success || r.Slot != "Ring_1" {
		t.Fatalf("header: %+v", r)
	}
	if r.BaselineTierScores["1"] != 0.5 {
		t.Errorf("baselineTierScores: %v", r.BaselineTierScores)
	}
	if len(r.Alternatives) != 1 {
		t.Fatalf("want 1 alternative, got %d", len(r.Alternatives))
	}
	alt := r.Alternatives[0]
	if alt.Rank != 1 || alt.ItemName != "Better Ring" || alt.ML != 34 || !alt.IsRaid {
		t.Errorf("alternative scalars: %+v", alt)
	}
	if alt.TierScores["1"] != 0.7 || alt.ObjectiveScore != 7025.0 {
		t.Errorf("scores: %+v", alt)
	}
	if alt.StatDeltas["Doubleshot"] != -3.0 {
		t.Errorf("statDeltas: %v", alt.StatDeltas)
	}
	if len(alt.Augments) != 1 || alt.Augments[0].Color != "Green" {
		t.Errorf("augments: %v", alt.Augments)
	}
	if _, ok := alt.Filigrees["weapon"]; !ok {
		t.Errorf("filigrees: %v", alt.Filigrees)
	}
	if len(r.Warnings) != 1 {
		t.Errorf("warnings: %v", r.Warnings)
	}
}

// A target slot with zero legal candidates is a success, not an error (EC-37).
func TestAlternativesResult_EmptyCandidateSetIsNotAnError(t *testing.T) {
	const out = `{"success":true,"slot":"Goggles","baselineTierScores":{"1":0.5},"alternatives":[]}`
	var r AlternativesResult
	if err := json.Unmarshal([]byte(out), &r); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if !r.Success || r.ErrorMessage != "" || len(r.Alternatives) != 0 {
		t.Errorf("unexpected: %+v", r)
	}
	if len(r.BaselineTierScores) == 0 {
		t.Error("baselineTierScores should still be populated")
	}
}
