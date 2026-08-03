import json
import sys
import os
import parser
import optimizer

def parse_payload(payload):
    # Just returns the payload for now, any required normalization can happen here
    return payload

def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r') as f:
            payload = json.load(f)
    elif not sys.stdin.isatty():
        payload = json.load(sys.stdin)
    else:
        print("Error: No JSON payload provided via file or stdin.")
        sys.exit(1)
        
    parsed_data = parse_payload(payload)
    
    levels = parsed_data.get('max_levels', [32])
    b_type = parsed_data.get('build_type', 'Melee')
    stat_priorities = parsed_data.get('stat_priorities', {})
    armor_input = parsed_data.get('armor_restriction', '')
    
    weapon_style = parsed_data.get('weapon_style', 'Two Weapon Fighting')
    # Basic mapping for w1_list, w2_list based on payload (simplified for solver)
    w1_list = None
    w2_list = None
    
    allow_gomf = parsed_data.get('allow_gomf', True)
    art_slot_input = parsed_data.get('reserved_minor_artifact_slot', '')
    art_slots = parsed_data.get('minor_artifact_filigree_slots', 4)
    excluded_packs = parsed_data.get('excluded_packs', [])
    raid_item_limit = parsed_data.get('raid_item_limit', None)
    
    base_dir = "/Users/jorgecosgayon/dev/ddo/DDOBuilderV2/Output/DataFiles"
    if not os.path.exists(base_dir):
        print(f"Error: Base directory {base_dir} not found.")
        sys.exit(1)
        
    print(f"\nParsing Quests from {base_dir}...")
    quests_lookup = parser.parse_quests(base_dir)
    
    print(f"\nParsing Sets from {base_dir}...")
    sets = optimizer.parse_sets(base_dir, stat_priorities)
    print(f"Loaded {len(sets)} sets.")
    
    filename = "gearset_output.txt"
    with open(filename, 'w') as out_file:
        out_file.write("======================================\n")
        out_file.write("           USER INPUTS\n")
        out_file.write("======================================\n")
        out_file.write(f"Build Type: {b_type}\n")
        out_file.write(f"Final Priorities: {', '.join(stat_priorities.keys())}\n")
        out_file.write(f"Armor Restriction: {armor_input or 'None'}\n")
        out_file.write(f"Reserved Minor Artifact Slot: {art_slot_input or 'Any'}\n")
        out_file.write(f"Minor Artifact Filigree Slots: {art_slots}\n")
        out_file.write(f"Allow Gem of Many Facets: {allow_gomf}\n")
        out_file.write(f"Excluded Packs: {', '.join(excluded_packs) if excluded_packs else 'None'}\n")
        out_file.write(f"Raid Item Limit: {raid_item_limit}\n\n")
        
        for cap in levels:
            print(f"\nParsing Items (ML 29-{cap})...")
            items = optimizer.parse_items(base_dir, cap, stat_priorities, armor_input, w1_list, w2_list, allow_gomf, art_slot_input, excluded_packs, quests_lookup)
            print(f"Loaded {len(items)} items")
            
            print(f"Parsing Augments (ML 29-{cap})...")
            augments = optimizer.parse_augments(base_dir, cap, stat_priorities)
            print(f"Loaded {len(augments)} augments")
            
            filigrees = []
            if cap >= 34:
                print(f"Parsing Filigrees...")
                filigrees, filigree_sets = optimizer.parse_filigrees(base_dir, stat_priorities)
                print(f"Loaded {len(filigrees)} filigrees")
                for k, v in filigree_sets.items():
                    if k not in sets:
                        sets[k] = v
                    else:
                        for count, buffs in v.items():
                            sets[k][count] = buffs
                            
            print(f"Solving ILP for max level {cap} (this may take a minute)...")
            optimizer.run_optimization(items, sets, augments, filigrees, stat_priorities, out_file, cap, art_slots, raid_item_limit)
            
    print(f"\nSuccess! Results written to {filename}")

if __name__ == "__main__":
    main()
