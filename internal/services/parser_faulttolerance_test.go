package services_test

import (
	"encoding/xml"
	"os"
	"path/filepath"
	"testing"

	"goGearset/internal/models"
	"goGearset/internal/services"
)

// AC-1/AC-2/EC-10: one malformed file must never empty the cache. Returning a
// non-nil error from a filepath.WalkFunc aborts the whole walk, which is exactly
// what the old parsers did — a single bad file among thousands produced zero
// cached entries and a silently empty UI.

func writeFile(t *testing.T, dir, name, contents string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), []byte(contents), 0644); err != nil {
		t.Fatalf("write %s: %v", name, err)
	}
}

const validItem = `<Items><Item><Name>%s</Name><MinLevel>10</MinLevel></Item></Items>`

func TestParseItems_SkipsMalformedFileWithoutEmptyingCache(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"a", "b", "c", "d", "e"} {
		writeFile(t, dir, name+".item", "<Items><Item><Name>"+name+"</Name></Item></Items>")
	}
	// Truncated mid-element: xml.Unmarshal fails outright for this file.
	writeFile(t, dir, "broken.item", "<Items><Item><Name>Broken</Na")

	items, skipped, err := services.ParseItems(dir)
	if err != nil {
		t.Fatalf("walk-level error should be nil for an XML content failure, got %v", err)
	}
	if len(items) != 5 {
		t.Fatalf("want 5 parsed items, got %d", len(items))
	}
	if len(skipped) != 1 || filepath.Base(skipped[0]) != "broken.item" {
		t.Errorf("want broken.item reported as skipped, got %v", skipped)
	}
}

func TestParseAugments_SkipsMalformedFile(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "ok.xml", `<Augments><Augment><Name>Ruby of Power</Name><Type>Red</Type><MinLevel>4</MinLevel></Augment></Augments>`)
	writeFile(t, dir, "bad.xml", `<Augments><Augment><Name>Nope`)

	augs, skipped, err := services.ParseAugments(dir)
	if err != nil {
		t.Fatalf("unexpected walk error: %v", err)
	}
	if len(augs) != 1 || augs[0].Name != "Ruby of Power" {
		t.Fatalf("want the one valid augment, got %+v", augs)
	}
	if len(skipped) != 1 {
		t.Errorf("want 1 skipped file, got %v", skipped)
	}
}

func TestParseFiligrees_SkipsMalformedFile(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "ok.xml", `<Filigrees><SetBonus><Type>Angelic Wings</Type></SetBonus>`+
		`<Filigree><Name>Angelic Wings: +1 Charisma</Name></Filigree></Filigrees>`)
	writeFile(t, dir, "bad.xml", `<Filigrees><Filigree><Name>`)

	fils, skipped, err := services.ParseFiligrees(dir)
	if err != nil {
		t.Fatalf("unexpected walk error: %v", err)
	}
	if len(fils) != 1 || fils[0].SetName != "Angelic Wings" {
		t.Fatalf("want one filigree carrying its set name, got %+v", fils)
	}
	if len(skipped) != 1 {
		t.Errorf("want 1 skipped file, got %v", skipped)
	}
}

// AC-2/AC-6: ParseSetBonuses is fault tolerant from the start and reads the real
// <SetBonuses><SetBonus><Type> shape (the deleted ParseSets targeted
// <Sets><Set><Name>, which does not exist in the data files).
func TestParseSetBonuses_ParsesTiersAndSkipsMalformedFile(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "SetBonuses.xml", `<SetBonuses>
	  <SetBonus>
	    <Type>Inevitable Balance</Type>
	    <Icon>InevitableBalance</Icon>
	    <Buff>
	      <EquippedCount>2</EquippedCount>
	      <Description>+5 Melee Power</Description>
	      <Effect><Type>MeleePower</Type><Type>Doublestrike</Type><Bonus>Stacking</Bonus><Amount size="1">5</Amount></Effect>
	    </Buff>
	    <Buff>
	      <EquippedCount>4</EquippedCount>
	      <Description>Description-only tier</Description>
	    </Buff>
	  </SetBonus>
	</SetBonuses>`)
	writeFile(t, dir, "bad.xml", `<SetBonuses><SetBonus><Type>`)

	sets, skipped, err := services.ParseSetBonuses(dir)
	if err != nil {
		t.Fatalf("unexpected walk error: %v", err)
	}
	if len(skipped) != 1 {
		t.Errorf("want 1 skipped file, got %v", skipped)
	}
	if len(sets) != 1 {
		t.Fatalf("want 1 set, got %d", len(sets))
	}
	set := sets[0]
	if set.Type != "Inevitable Balance" || set.Icon != "InevitableBalance" {
		t.Errorf("set header: %+v", set)
	}
	if len(set.Tiers) != 2 {
		t.Fatalf("want 2 tiers, got %d", len(set.Tiers))
	}
	if set.Tiers[0].EquippedCount != "2" || len(set.Tiers[0].Effects) != 1 {
		t.Errorf("tier 0: %+v", set.Tiers[0])
	}
	// A single <Effect> may repeat <Type>, hence Types is a slice.
	if len(set.Tiers[0].Effects[0].Types) != 2 || set.Tiers[0].Effects[0].Amount != "5" {
		t.Errorf("tier 0 effect: %+v", set.Tiers[0].Effects[0])
	}
	// EC-6: a description-only tier is legal and carries no effects.
	if len(set.Tiers[1].Effects) != 0 || set.Tiers[1].Description != "Description-only tier" {
		t.Errorf("tier 1: %+v", set.Tiers[1])
	}
}

// ParseSetBonuses accepts a single file as well as a directory, because
// SetBonuses.xml is a lone file sitting among many unrelated .xml files.
func TestParseSetBonuses_AcceptsASingleFilePath(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "SetBonuses.xml", `<SetBonuses><SetBonus><Type>Arcane Mind</Type></SetBonus></SetBonuses>`)

	sets, _, err := services.ParseSetBonuses(filepath.Join(dir, "SetBonuses.xml"))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(sets) != 1 || sets[0].Type != "Arcane Mind" {
		t.Fatalf("got %+v", sets)
	}
}

// AC-13: all three buff shapes survive verbatim. ~25% of item buffs carry no
// value and/or no bonus type; Python's parse_items skips those by design, but
// the display layer must still show them (INV-1).
func TestXMLItem_BuffsParseVerbatimIncludingValuelessOnes(t *testing.T) {
	var data models.XMLItemData
	err := xml.Unmarshal([]byte(`<Items><Item><Name>Mixed</Name>
	  <Buff><Type>WeaponEnchantment</Type><Value1>15</Value1><BonusType>Weapon Enchantment</BonusType></Buff>
	  <Buff><Type>Dripping with Magma</Type></Buff>
	  <Buff><Type>Sovereign Vorpal</Type><Item>All</Item><Description1>All</Description1><BonusType>Enhancement</BonusType></Buff>
	</Item></Items>`), &data)
	if err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	buffs := data.Items[0].Buffs
	if len(buffs) != 3 {
		t.Fatalf("want 3 buffs, got %d", len(buffs))
	}
	if buffs[0].Value1 != "15" || buffs[0].BonusType != "Weapon Enchantment" {
		t.Errorf("buff 0: %+v", buffs[0])
	}
	if buffs[1].Type != "Dripping with Magma" || buffs[1].Value1 != "" || buffs[1].BonusType != "" {
		t.Errorf("buff 1 should survive with empty value/bonus: %+v", buffs[1])
	}
	if buffs[2].Item != "All" || buffs[2].Description1 != "All" || buffs[2].Value1 != "" {
		t.Errorf("buff 2: %+v", buffs[2])
	}
}

// AC-14: BaseDice is a pointer so "absent" and "present but empty" differ, and
// its scalars are strings (INV-2).
func TestXMLItem_BaseDicePointerDistinguishesAbsence(t *testing.T) {
	var withDice models.XMLItemData
	if err := xml.Unmarshal([]byte(`<Items><Item><Name>W</Name><Weapon>Rapier</Weapon>
	  <BaseDice><Number>2</Number><Sides>6</Sides></BaseDice>
	  <CriticalMultiplier>2</CriticalMultiplier><CriticalThreatRange>3</CriticalThreatRange>
	  <DRBypass>Magic</DRBypass><DRBypass>Pierce</DRBypass></Item></Items>`), &withDice); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	item := withDice.Items[0]
	if item.BaseDice == nil {
		t.Fatal("BaseDice should be non-nil when the element is present")
	}
	if item.BaseDice.Number != "2" || item.BaseDice.Sides != "6" {
		t.Errorf("base dice: %+v", item.BaseDice)
	}
	if len(item.DRBypass) != 2 || item.Weapon != "Rapier" {
		t.Errorf("weapon profile: %+v", item)
	}

	var noDice models.XMLItemData
	if err := xml.Unmarshal([]byte(`<Items><Item><Name>H</Name></Item></Items>`), &noDice); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if noDice.Items[0].BaseDice != nil {
		t.Error("BaseDice should be nil when the element is absent")
	}
}

// AC-15/§2.7: an <ItemAugment> can carry a default choice plus embedded upgrade
// choices, one of which may grant CONDITIONAL set membership.
func TestXMLItemAugment_ParsesSelectedAndEmbeddedAugments(t *testing.T) {
	var data models.XMLItemData
	if err := xml.Unmarshal([]byte(`<Items><Item><Name>Dagger</Name>
	  <ItemAugment>
	    <Type>Sealed in Fire</Type>
	    <SelectedAugment>Sealed in Fire</SelectedAugment>
	    <SelectedLevelIndex>1</SelectedLevelIndex>
	    <Augment><Name>+7 Combustion</Name><Description>d</Description><MinLevel>20</MinLevel></Augment>
	    <Augment><Name>Epic Upgrade</Name><SetBonus>Epic Elemental Evil Set</SetBonus></Augment>
	  </ItemAugment>
	</Item></Items>`), &data); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	augs := data.Items[0].ItemAugments
	if len(augs) != 1 {
		t.Fatalf("want 1 item augment, got %d", len(augs))
	}
	if augs[0].SelectedAugment != "Sealed in Fire" || augs[0].SelectedLevelIndex != "1" {
		t.Errorf("selected: %+v", augs[0])
	}
	if len(augs[0].Augments) != 2 {
		t.Fatalf("want 2 embedded augments, got %d", len(augs[0].Augments))
	}
	if augs[0].Augments[0].MinLevel != "20" {
		t.Errorf("MinLevel must stay a string (INV-2), got %q", augs[0].Augments[0].MinLevel)
	}
	if augs[0].Augments[1].SetBonus != "Epic Elemental Evil Set" {
		t.Errorf("conditional set bonus not captured: %+v", augs[0].Augments[1])
	}
	// A conditional set bonus lives ONLY on the embedded augment — it must not
	// leak into the item's top-level, unconditional SetBonuses list.
	if len(data.Items[0].SetBonuses) != 0 {
		t.Errorf("augment-nested SetBonus leaked into top-level SetBonuses: %v", data.Items[0].SetBonuses)
	}
}

// AC-16: Go's display parsing deliberately KEEPS <Rare>-tagged effects, unlike
// Python's parse_filigrees which skips them for solver matching.
func TestXMLFiligree_KeepsRareTaggedEffects(t *testing.T) {
	var data models.XMLFiligreeData
	if err := xml.Unmarshal([]byte(`<Filigrees><SetBonus><Type>Angelic Wings</Type></SetBonus>
	  <Filigree><Name>Angelic Wings: +1 Charisma</Name>
	    <Effect><Type>AbilityBonus</Type><Item>Charisma</Item><Amount>1</Amount></Effect>
	    <Effect><Type>MRR</Type><Amount>2</Amount><Rare/></Effect>
	  </Filigree></Filigrees>`), &data); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(data.Filigrees) != 1 {
		t.Fatalf("want 1 filigree, got %d", len(data.Filigrees))
	}
	if len(data.Filigrees[0].Effects) != 2 {
		t.Errorf("want both the base and the Rare effect retained, got %d", len(data.Filigrees[0].Effects))
	}
}

// §2.6: the inline filigree <SetBonus> is its own type and carries tiers, so
// filigree sets render through the same panel as item sets.
func TestXMLFiligreeSetRef_CarriesTiers(t *testing.T) {
	var data models.XMLFiligreeData
	if err := xml.Unmarshal([]byte(`<Filigrees><SetBonus><Type>Angelic Wings</Type><Icon>AngelicWings</Icon>
	  <Buff><EquippedCount>2</EquippedCount><Description>+3 Turn Undead Charges</Description>
	    <Effect><Type>ExtraTurns</Type><Amount>3</Amount></Effect></Buff>
	</SetBonus></Filigrees>`), &data); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if data.SetBonus.Type != "Angelic Wings" || len(data.SetBonus.Tiers) != 1 {
		t.Fatalf("got %+v", data.SetBonus)
	}
	if data.SetBonus.Tiers[0].EquippedCount != "2" || len(data.SetBonus.Tiers[0].Effects) != 1 {
		t.Errorf("tier: %+v", data.SetBonus.Tiers[0])
	}
}

// §2.3: item-level <Effect> (clickies/SLAs) and their requirements parse, and
// top-level <SetBonus> membership is a plain list of names.
func TestXMLItem_EffectsAndTopLevelSetBonuses(t *testing.T) {
	var data models.XMLItemData
	if err := xml.Unmarshal([]byte(`<Items><Item><Name>Clicky</Name>
	  <SetBonus>Legendary Inevitable Balance</SetBonus>
	  <Effect><Type>GrantSpell</Type><Bonus>Stacking</Bonus><Item>Fireball</Item><AType>Simple</AType><Amount>3</Amount>
	    <Requirements><Requirement><Type>Class</Type><Item>Wizard</Item></Requirement></Requirements>
	  </Effect></Item></Items>`), &data); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	item := data.Items[0]
	if len(item.SetBonuses) != 1 || item.SetBonuses[0] != "Legendary Inevitable Balance" {
		t.Errorf("set bonuses: %v", item.SetBonuses)
	}
	if len(item.Effects) != 1 {
		t.Fatalf("want 1 effect, got %d", len(item.Effects))
	}
	if len(item.Effects[0].Requirements) != 1 || item.Effects[0].Requirements[0].Item != "Wizard" {
		t.Errorf("requirements: %+v", item.Effects[0].Requirements)
	}
}
