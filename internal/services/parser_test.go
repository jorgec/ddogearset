package services_test

import (
	"encoding/xml"
	"testing"

	"goGearset/internal/models"
)

func TestXMLItemData_Unmarshal(t *testing.T) {
	// Use mock XML data mimicking DDOBuilder's format
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
	err := xml.Unmarshal(mockXML, &data)
	if err != nil {
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
	if len(item.EquipmentSlot.Slots) != 1 {
		t.Fatalf("Expected 1 EquipmentSlot slot, got %d", len(item.EquipmentSlot.Slots))
	}
	if item.EquipmentSlot.Slots[0].Local != "Helmet" {
		t.Errorf("Expected EquipmentSlot 'Helmet', got '%s'", item.EquipmentSlot.Slots[0].Local)
	}
	if len(item.DropLocations) != 2 {
		t.Fatalf("Expected 2 drop locations, got %d", len(item.DropLocations))
	}
	if item.DropLocations[0] != "Fables of the Feywild" {
		t.Errorf("Expected DropLocation[0] 'Fables of the Feywild', got '%s'", item.DropLocations[0])
	}
}
