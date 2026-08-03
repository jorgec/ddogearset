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
    
    cap = parsed_data.get('max_level', 34)
    b_type = parsed_data.get('build_type', 'Melee')
    raw_priorities = parsed_data.get('stat_priorities', [])
    # `stat_priorities` is an ordered list of {"stat": str, "value": int} entries
    # (order preserved end-to-end for filigree-selection bias, see
    # docs/PHASE9_PLAN.md). Older saved .ddogearset files may still store this
    # as a plain {stat: value} dict; support both for backward compatibility.
    if isinstance(raw_priorities, dict):
        priority_pairs = list(raw_priorities.items())
    else:
        priority_pairs = [(e.get('stat'), e.get('value')) for e in raw_priorities if e.get('stat')]
    priority_names = [name for name, _ in priority_pairs]
    armor_input = parsed_data.get('armor_restriction', '')
    
    weapon_style = parsed_data.get('weapon_style', 'Two Weapon Fighting')
    runearm_use = parsed_data.get('runearm_use', False)

    twf_weapons = ['dagger', 'kukri', 'rapier', 'scimitar', 'longsword', 'khopesh', 'handwraps', 'shortsword', 'kama', 'sickle', 'battle axe', 'hand axe', 'dwarven waraxe', 'bastard sword', 'heavy mace', 'light mace', 'morningstar', 'club', 'light pick', 'heavy pick', 'warhammer']
    thf_weapons = ['great sword', 'falchion', 'great axe', 'maul', 'quarterstaff', 'great club']
    swash_weapons = ['dagger', 'kukri', 'rapier', 'shortsword', 'hand axe', 'kama', 'sickle', 'light mace', 'light pick', 'heavy pick', 'throwing dagger', 'throwing axe', 'dart']
    shields = ['buckler', 'small shield', 'large shield', 'tower shield']
    caster_1h = ['club', 'dagger', 'sickle', 'heavy mace', 'light mace', 'morningstar', 'scepter', 'shortsword']
    runearm_offhand = ['rune arm', 'runearm']

    if weapon_style == 'Two Handed Fighting':
        w1_list = thf_weapons
        w2_list = ['none']
    elif weapon_style == 'Two Weapon Fighting':
        w1_list = twf_weapons
        w2_list = twf_weapons
    elif weapon_style == 'Single Weapon Fighting':
        swashbuckling = parsed_data.get('swashbuckling', False)
        w1_list = swash_weapons if swashbuckling else twf_weapons
        offhand_style = parsed_data.get('offhand_style', 'Empty')
        if offhand_style == 'Buckler':
            w2_list = ['buckler']
        elif offhand_style == 'Shield':
            w2_list = shields
        elif offhand_style == 'Orb':
            w2_list = ['orb']
        elif offhand_style == 'Runearm':
            w2_list = runearm_offhand
        else:
            w2_list = ['none']
    elif weapon_style == 'Sword and Board':
        w1_list = twf_weapons
        w2_list = shields
    elif weapon_style == 'Bow':
        w1_list = ['longbow', 'shortbow']
        w2_list = ['none']
    elif weapon_style == 'Repeating Crossbow':
        w1_list = ['repeating light crossbow', 'repeating heavy crossbow']
        w2_list = runearm_offhand if runearm_use else ['none']
    elif weapon_style == 'Great Crossbow':
        w1_list = ['great crossbow']
        w2_list = ['none']
    elif weapon_style == 'Dual Crossbow':
        w1_list = ['light crossbow', 'heavy crossbow']
        w2_list = runearm_offhand if runearm_use else ['none']
    elif weapon_style == 'Thrown':
        w1_list = ['throwing dagger', 'throwing axe', 'dart']
        w2_list = runearm_offhand if runearm_use else ['none']
    elif weapon_style == 'Shuriken':
        w1_list = ['shuriken']
        w2_list = runearm_offhand if runearm_use else ['none']
    elif weapon_style == 'Dual Caster':
        w1_list = caster_1h
        w2_list = caster_1h
    elif weapon_style == 'Stick and Orb':
        w1_list = caster_1h
        w2_list = ['orb']
    elif weapon_style == 'Quarterstaff':
        w1_list = ['quarterstaff']
        w2_list = ['none']
    else:  # None / fallback
        w1_list = None
        w2_list = None

    allow_gomf = not parsed_data.get('exclude_gem_of_many_facets', False)
    art_slot_input = parsed_data.get('reserved_minor_artifact_slot', '')
    if parsed_data.get('is_dino_artifact', False):
        art_slot_input += ' (dino)'
    art_slots = parsed_data.get('minor_artifact_filigree_slots', 4)
    excluded_packs = parsed_data.get('excluded_packs', [])
    raid_item_limit = parsed_data.get('raid_item_limit', None)
    pre_equipped = parsed_data.get('pre_equipped', {})
    pre_filled_augments = parsed_data.get('pre_filled_augments', {})
    pre_filled_filigrees = parsed_data.get('pre_filled_filigrees', {})
    calculate_only = parsed_data.get('calculate_only', False)
    
    base_dir = "/Users/jorgecosgayon/dev/ddo/DDOBuilderV2/Output/DataFiles"
    if not os.path.exists(base_dir):
        print(f"Error: Base directory {base_dir} not found.")
        sys.exit(1)
        
    print(f"\nParsing Quests from {base_dir}...")
    quests_lookup = parser.parse_quests(base_dir)
    
    print(f"\nParsing Sets from {base_dir}...")
    sets = optimizer.parse_sets(base_dir, priority_names)
    print(f"Loaded {len(sets)} sets.")
    
    filename = parsed_data.get('output_filename', 'gearset_output.json')
    if not filename.endswith('.json'):
        filename += '.json'
    
    log_filename = "gearset_output.txt"
    final_gearset = {}
    with open(log_filename, 'w') as out_file:
        out_file.write("======================================\n")
        out_file.write("           USER INPUTS\n")
        out_file.write("======================================\n")
        out_file.write(f"Build Type: {b_type}\n")
        out_file.write(f"Final Priorities: {', '.join(priority_names)}\n")
        out_file.write(f"Armor Restriction: {armor_input or 'None'}\n")
        out_file.write(f"Reserved Minor Artifact Slot: {art_slot_input or 'Any'}\n")
        out_file.write(f"Minor Artifact Filigree Slots: {art_slots}\n")
        out_file.write(f"Allow Gem of Many Facets: {allow_gomf}\n")
        out_file.write(f"Excluded Packs: {', '.join(excluded_packs) if excluded_packs else 'None'}\n")
        out_file.write(f"Raid Item Limit: {raid_item_limit}\n\n")
        
        print(f"\nParsing Items (ML 29-{cap})...")
        pre_equipped_names = list(pre_equipped.values()) if pre_equipped else []
        items = optimizer.parse_items(base_dir, cap, priority_names, armor_input, w1_list, w2_list, allow_gomf, art_slot_input, excluded_packs, quests_lookup, pre_equipped_names)
        print(f"Loaded {len(items)} items")
        
        print(f"Parsing Augments (ML 29-{cap})...")
        augments = optimizer.parse_augments(base_dir, cap, priority_names)
        print(f"Loaded {len(augments)} augments")
        
        filigrees = []
        if cap >= 34:
            print(f"Parsing Filigrees...")
            filigrees, filigree_sets = optimizer.parse_filigrees(base_dir, priority_names)
            print(f"Loaded {len(filigrees)} filigrees")
            for k, v in filigree_sets.items():
                if k not in sets:
                    sets[k] = v
                else:
                    for count, buffs in v.items():
                        sets[k][count] = buffs
                        
        print(f"Solving ILP for max level {cap} (this may take a minute)...")
        equipped_simple = optimizer.run_optimization(items, sets, augments, filigrees, priority_pairs, out_file, cap, art_slots, raid_item_limit, pre_equipped, pre_filled_augments, pre_filled_filigrees, calculate_only)
        if equipped_simple:
            final_gearset = equipped_simple
            
    # Print the json to stdout so the Go app can easily parse it
    print(f"JSON_RESULT:{json.dumps(final_gearset)}")
    print(f"\nSuccess! Results written to {filename}")

if __name__ == "__main__":
    main()
