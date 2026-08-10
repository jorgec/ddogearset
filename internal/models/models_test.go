package models_test

import (
	"encoding/xml"
	"testing"

	"goGearset/internal/models"
)

// These test xml.Unmarshal directly against the model structs — not file
// walking (that lived in internal/services/parser.go, deleted in Phase 5;
// see docs/0.5.0/00_ETL_START_HERE.md). They matter MORE now than before:
// internal/catalog reads raw_xml out of catalog.db and unmarshals it through
// these exact same structs, so their correctness is load-bearing for the
// whole catalog-backed read path, not just the old file walk.

func TestXMLItemData_Unmarshal(t *testing.T) {
	mockXML := []byte(`
		<Items>
			<Item>
				<Name>Crown of Snow</Name>
				<Description>A crown of ice...</Description>
				<MinLevel>5</MinLevel>
				<EquipmentSlot>
					<Helmet/>
				</EquipmentSlot>
				<DropLocation>Fables of the Feywild</DropLocation>
				<DropLocation>Some other location</DropLocation>
			</Item>
		</Items>
	`)

	var data models.XMLItemData
	if err := xml.Unmarshal(mockXML, &data); err != nil {
		t.Fatalf("Failed to unmarshal XML: %v", err)
	}

	if len(data.Items) != 1 {
		t.Fatalf("Expected 1 item, got %d", len(data.Items))
	}
	item := data.Items[0]
	if item.Name != "Crown of Snow" {
		t.Errorf("Expected Name 'Crown of Snow', got '%s'", item.Name)
	}
	if item.Description != "A crown of ice..." {
		t.Errorf("Expected Description 'A crown of ice...', got '%s'", item.Description)
	}
	if item.MinLevel != 5 {
		t.Errorf("Expected MinLevel 5, got %d", item.MinLevel)
	}
	if len(item.EquipmentSlot.Slots) != 1 || item.EquipmentSlot.Slots[0].Local != "Helmet" {
		t.Fatalf("Expected 1 slot 'Helmet', got %v", item.EquipmentSlot.Slots)
	}
	if len(item.DropLocations) != 2 || item.DropLocations[0] != "Fables of the Feywild" {
		t.Fatalf("Expected 2 drop locations, got %v", item.DropLocations)
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
	// Item repeats on <Effect> now: [0]'s single <Item>Charisma</Item> still
	// round-trips as a one-element slice.
	if len(data.Filigrees[0].Effects[0].Item) != 1 || data.Filigrees[0].Effects[0].Item[0] != "Charisma" {
		t.Errorf("effect 0 Item: %+v", data.Filigrees[0].Effects[0].Item)
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
	if len(item.Effects[0].Item) != 1 || item.Effects[0].Item[0] != "Fireball" {
		t.Errorf("effect Item: %+v", item.Effects[0].Item)
	}
	if len(item.Effects[0].Requirements) != 1 || item.Effects[0].Requirements[0].Item != "Wizard" {
		t.Errorf("requirements: %+v", item.Effects[0].Requirements)
	}
}

// The bug this phase fixes, proven directly: a repeating <Item> on one
// <Effect> now round-trips as ALL targets, in XML order, instead of Go's old
// last-wins single-string behaviour.
func TestXMLEffect_ItemRepeatsInOrder(t *testing.T) {
	var data models.XMLAugmentsData
	if err := xml.Unmarshal([]byte(`<Augments><Augment><Name>Miserable Arcana: Force</Name>
	  <Effect><Type>SpellPower</Type><Bonus>Equipment</Bonus>
	    <Item>Force</Item><Item>Physical</Item><Item>Untyped</Item>
	    <Amount size="1">159</Amount></Effect>
	</Augment></Augments>`), &data); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	eff := data.Augments[0].Effects[0]
	want := []string{"Force", "Physical", "Untyped"}
	if len(eff.Item) != len(want) {
		t.Fatalf("want %d targets, got %d: %v", len(want), len(eff.Item), eff.Item)
	}
	for i, w := range want {
		if eff.Item[i] != w {
			t.Errorf("Item[%d]: want %q, got %q", i, w, eff.Item[i])
		}
	}
	// Display convention (this phase, §8): bind to Item[0] only, matching
	// Python's findtext (first-wins) — never join or show additional targets.
	if eff.Item[0] != "Force" {
		t.Errorf("display target Item[0]: want %q, got %q", "Force", eff.Item[0])
	}
}
