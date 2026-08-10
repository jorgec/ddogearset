//go:build ignore

// Standalone smoke test, run manually against the fixture catalog built
// during Phase 4/5 development:
//
//	go run internal/catalog/catalog_smoketest.go /tmp/etl_phase4/catalog.db
//
// Not a _test.go on purpose: it depends on a fixture path outside the repo
// and is meant to be run by hand while developing this package, not by `go
// test ./...`. Delete once Phase 5 has real coverage in app_test.go / an
// internal/catalog/*_test.go against a committed fixture.
package main

import (
	"fmt"
	"os"

	"goGearset/internal/catalog"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Println("usage: go run catalog_smoketest.go <path-to-catalog.db>")
		os.Exit(1)
	}
	db, err := catalog.Open(os.Args[1])
	if err != nil {
		panic(err)
	}
	defer db.Close()

	meta, err := catalog.ReadMeta(db)
	if err != nil {
		panic(err)
	}
	fmt.Printf("catalog_meta: %+v\n\n", meta)

	items, skipped, err := catalog.LoadItems(db)
	if err != nil {
		panic(err)
	}
	fmt.Printf("items: %d loaded, %d skipped\n", len(items), len(skipped))
	if len(skipped) > 0 {
		fmt.Println("  skipped:", skipped[:min(5, len(skipped))])
	}

	for _, it := range items {
		if it.Name == "Docent of Defiance" {
			fmt.Printf("  sample item: %s\n", it.Name)
			fmt.Printf("    Description: %.80s...\n", it.Description)
			fmt.Printf("    Slots: %v\n", it.EquipmentSlot.Slots)
			fmt.Printf("    Buffs: %d, Effects: %d\n", len(it.Buffs), len(it.Effects))
			fmt.Printf("    IsRaid: %v  Armor: %q  ArmorBonus: %q\n", it.IsRaid, it.Armor, it.ArmorBonus)
			break
		}
	}

	// Look for a multi-<Item> effect to confirm the []string fix works.
	multiFound := false
	for _, it := range items {
		for _, eff := range it.Effects {
			if len(eff.Item) > 1 {
				fmt.Printf("\n  multi-target effect on %q: Item=%v (display shows Item[0]=%q)\n",
					it.Name, eff.Item, eff.Item[0])
				multiFound = true
				break
			}
		}
		if multiFound {
			break
		}
	}
	if !multiFound {
		fmt.Println("\n  (no multi-target item Effect found in items — checking augments)")
	}

	augs, augSkipped, err := catalog.LoadAugments(db)
	if err != nil {
		panic(err)
	}
	fmt.Printf("\naugments: %d loaded, %d skipped\n", len(augs), len(augSkipped))

	fils, filSkipped, err := catalog.LoadFiligrees(db)
	if err != nil {
		panic(err)
	}
	fmt.Printf("filigrees: %d loaded, %d skipped\n", len(fils), len(filSkipped))
	for _, f := range fils {
		if f.Name == "Zarigan's Arcane Enlightenment/Voltaic Experiment +2 Intelligence" {
			fmt.Printf("  dual-set filigree SetName (first membership): %q\n", f.SetName)
		}
	}

	sets, setSkipped, err := catalog.LoadSetBonuses(db)
	if err != nil {
		panic(err)
	}
	fmt.Printf("set bonuses: %d loaded, %d skipped\n", len(sets), len(setSkipped))
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
