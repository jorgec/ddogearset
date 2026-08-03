import pytest
import re
from unittest.mock import patch, MagicMock
import pulp

# =====================================================================
# This is a test blueprint to validate Phase 3 Integration changes.
# The actual imports and functions below may need to be adjusted 
# depending on the final implementations in the codebase (e.g., `solver.py`, 
# `parser.py`, `optimizer.py`).
# =====================================================================

def test_parse_json_payload():
    """
    1. Validates parsing the new JSON payload format correctly.
    """
    payload_json = {
        "max_levels": [32],
        "build_type": "Melee", 
        "weapon_style": "Two Weapon Fighting", 
        "swashbuckling": False, 
        "offhand_style": "None", 
        "caster_spellpowers": ["Fire", "Force"],
        "caster_schools": ["Evocation"],
        "stat_priorities": {
            "Constitution": 100,
            "Charisma": 90,
            "Melee Power[50]": 85,
            "Doublestrike": 70
        },
        "armor_restriction": "Light",
        "reserved_minor_artifact_slot": "Ring",
        "minor_artifact_filigree_slots": 4,
        "allow_gomf": True,
        "excluded_packs": ["Isle of Dread", "Fables of the Feywild"],
        "raid_item_limit": 2
    }
    
    # Builder should ensure these assertions hold true based on how the payload is parsed
    # e.g.:
    # from solver import parse_payload
    # parsed_data = parse_payload(payload_json)
    #
    # assert parsed_data['stat_priorities']['Constitution'] == 100
    # assert "Isle of Dread" in parsed_data['excluded_packs']
    # assert parsed_data['raid_item_limit'] == 2

def test_calculate_weights_objective_function():
    """
    4. Validates the calculation of the new 1-100 WEIGHTS dictionary 
    in the objective function.
    """
    stat_priorities = {
        "Constitution": 100,
        "Charisma": 90,
        "Melee Power[50]": 85,
        "Doublestrike": 70
    }
    
    # Expected logic to be implemented by Builder in optimizer.py
    WEIGHTS = {}
    CAPS = {}
    for stat_name, weight_val in stat_priorities.items():
        p_base = re.sub(r'\[\d+\]', '', stat_name).strip()
        cap_match = re.search(r'\[(\d+)\]', stat_name)
        if cap_match:
            CAPS[p_base] = float(cap_match.group(1))
        WEIGHTS[p_base] = float(weight_val)
        
    assert WEIGHTS["Constitution"] == 100.0
    assert WEIGHTS["Charisma"] == 90.0
    assert WEIGHTS["Melee Power"] == 85.0
    assert WEIGHTS["Doublestrike"] == 70.0
    
    assert "Constitution" not in CAPS
    assert CAPS["Melee Power"] == 50.0

@patch('parser.parse_quests')
def test_parse_items_is_raid_and_pack_assignment(mock_parse_quests):
    """
    2. Validates the `parse_items` logic for checking `Quests.xml` and correctly 
       flagging items with `is_raid` and assigning them to an expansion pack.
    3. Validates the logic that filters out items if their pack matches the 
       `excluded_packs` payload array.
    """
    # Simulate a lookup dictionary generated from parsing Quests.xml
    mock_parse_quests_lookup = {
        "Defiler of the Just": {"AdventurePack": "The Devil's Gambit", "is_raid": True},
        "Fall of Truth": {"AdventurePack": "The Fall of Truth", "is_raid": True},
        "Isle of Dread Quest 1": {"AdventurePack": "Isle of Dread", "is_raid": False}
    }
    
    mock_items_xml = [
        {"name": "Item A", "DropLocation": "Defiler of the Just"},
        {"name": "Item B", "DropLocation": "Isle of Dread Quest 1"},
        {"name": "Item C", "DropLocation": "Random Chest, Raid"},
        {"name": "Item D", "DropLocation": "Unknown Location"}
    ]
    
    excluded_packs = ["Isle of Dread"]
    
    # Builder will implement the item parsing and filtering logic, simulating it here:
    parsed_items = []
    for item in mock_items_xml:
        drop_location = item.get("DropLocation", "")
        item['is_raid'] = False
        item['pack'] = None
        
        # Check against quests
        for quest_name, quest_info in mock_parse_quests_lookup.items():
            if quest_name in drop_location:
                item['pack'] = quest_info['AdventurePack']
                item['is_raid'] = quest_info['is_raid']
                break
                
        # Fallback for Raid
        if not item['is_raid'] and "raid" in drop_location.lower():
            item['is_raid'] = True
            
        # Filter excluded packs
        if item['pack'] in excluded_packs:
            continue
            
        parsed_items.append(item)

    # Validate the resulting logic
    
    # Item A: Should be a raid item from "The Devil's Gambit" and not excluded
    item_a = next(i for i in parsed_items if i['name'] == 'Item A')
    assert item_a['is_raid'] is True
    assert item_a['pack'] == "The Devil's Gambit"
    
    # Item B: Should be excluded because its pack 'Isle of Dread' is in excluded_packs
    item_b_matches = [i for i in parsed_items if i['name'] == 'Item B']
    assert len(item_b_matches) == 0
    
    # Item C: Should be a raid item because 'Raid' is in DropLocation (fallback)
    item_c = next(i for i in parsed_items if i['name'] == 'Item C')
    assert item_c['is_raid'] is True
    
    # Item D: Should not be a raid item
    item_d = next(i for i in parsed_items if i['name'] == 'Item D')
    assert item_d['is_raid'] is False

def test_raid_item_limit_pulp_constraint():
    """
    Additional Validation: Verify that the raid item limit constraint is 
    correctly added to the Pulp model in `create_model`.
    """
    items = [
        {"name": "Raid Item 1", "is_raid": True, "slots": ["Ring"]},
        {"name": "Raid Item 2", "is_raid": True, "slots": ["Ring"]},
        {"name": "Normal Item 1", "is_raid": False, "slots": ["Head"]}
    ]
    
    raid_item_limit = 1
    
    # Mock decision variables for items x[(item_index, slot)]
    x = {
        (0, "Ring"): pulp.LpVariable("x_0_Ring", cat="Binary"),
        (1, "Ring"): pulp.LpVariable("x_1_Ring", cat="Binary"),
        (2, "Head"): pulp.LpVariable("x_2_Head", cat="Binary")
    }
    
    prob = pulp.LpProblem("Test_Problem", pulp.LpMaximize)
    
    # Code that the Builder is instructed to place in create_model:
    raid_vars = []
    for i, item in enumerate(items):
        if item.get('is_raid'):
            raid_vars.extend([x[(i, s)] for s in item['slots'] if (i, s) in x])
            
    if raid_vars:
        prob += pulp.lpSum(raid_vars) <= raid_item_limit, "Max_Raid_Items"
        
    # Validation constraints
    assert "Max_Raid_Items" in prob.constraints
    constraint = prob.constraints["Max_Raid_Items"]
    
    # The constraint should bound the sum to <= raid_item_limit
    assert str(constraint) in ("x_0_Ring + x_1_Ring <= 1", "x_0_Ring + x_1_Ring <= 1.0")
