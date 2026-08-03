import sys
import os
import optimizer

def prompt_weapon_style(b_type):
    w1 = []
    w2 = []
    
    twf_weapons = ['dagger', 'kukri', 'rapier', 'scimitar', 'longsword', 'khopesh', 'handwraps', 'shortsword', 'kama', 'sickle', 'battle axe', 'hand axe', 'dwarven waraxe', 'bastard sword', 'heavy mace', 'light mace', 'morningstar', 'club', 'light pick', 'heavy pick', 'warhammer']
    thf_weapons = ['great sword', 'falchion', 'great axe', 'maul', 'quarterstaff', 'great club']
    swash_weapons = ['dagger', 'kukri', 'rapier', 'shortsword', 'hand axe', 'kama', 'sickle', 'light mace', 'light pick', 'heavy pick', 'throwing dagger', 'throwing axe', 'dart']
    shields = ['buckler', 'small shield', 'large shield', 'tower shield']
    caster_1h = ['club', 'dagger', 'sickle', 'heavy mace', 'light mace', 'morningstar', 'scepter', 'shortsword']
    
    if b_type == '1': # Melee
        print("\n--- Melee Weapon Style ---")
        print("1: Two Handed Weapon Fighting (Great Swords, Falchions, Great Axe, Maul, Quarterstaffs, etc.)")
        print("2: Two Weapon Fighting (Daggers, Kukris, Rapiers, Scimitars, Long Swords, Khopeshes, Handwraps, etc.)")
        print("3: Single Weapon Fighting")
        print("4: Sword and Board (Weapon + Shield)")
        choice = input("Select style (1-4): ").strip()
        if choice == '1':
            w1 = thf_weapons
            w2 = ['none']
        elif choice == '2':
            w1 = twf_weapons
            w2 = twf_weapons
        elif choice == '3':
            swash = input("Swashbuckling? (y/n): ").strip().lower()
            w1 = swash_weapons if swash == 'y' else twf_weapons
            print("Offhand options: 1: Empty, 2: Buckler, 3: Shield, 4: Orb, 5: Runearm")
            off = input("Select offhand (1-5): ").strip()
            if off == '1': w2 = ['none']
            elif off == '2': w2 = ['buckler']
            elif off == '3': w2 = shields
            elif off == '4': w2 = ['orb']
            elif off == '5': w2 = ['rune arm', 'runearm']
            else: w2 = ['none']
        elif choice == '4':
            w1 = twf_weapons
            w2 = shields
            
    elif b_type == '2': # Ranged
        print("\n--- Ranged Weapon Style ---")
        print("1: Bow")
        print("2: Repeating Crossbow")
        print("3: Great Crossbow")
        print("4: Simple Light/Heavy Crossbow")
        print("5: Thrower (Throwing Dagger, Dart, Shuriken, Throwing Axe)")
        choice = input("Select style (1-5): ").strip()
        if choice == '1':
            w1 = ['longbow', 'shortbow']
            w2 = ['none']
        elif choice == '2':
            w1 = ['repeating light crossbow', 'repeating heavy crossbow']
            ra = input("Runearm? (y/n): ").strip().lower()
            w2 = ['rune arm', 'runearm'] if ra == 'y' else ['none']
        elif choice == '3':
            w1 = ['great crossbow']
            w2 = ['none']
        elif choice == '4':
            w1 = ['light crossbow', 'heavy crossbow']
            ra = input("Runearm? (y/n): ").strip().lower()
            w2 = ['rune arm', 'runearm'] if ra == 'y' else ['none']
        elif choice == '5':
            w1 = ['throwing dagger', 'dart', 'shuriken', 'throwing axe']
            ra = input("Runearm? (y/n): ").strip().lower()
            w2 = ['rune arm', 'runearm'] if ra == 'y' else ['none']
            
    elif b_type == '3': # Caster
        print("\n--- Caster Weapon Style ---")
        print("1: Dual Caster Sticks (Scepters/Clubs/Daggers)")
        print("2: Stick and Orb")
        print("3: Quarterstaff")
        choice = input("Select style (1-3): ").strip()
        if choice == '1':
            w1 = caster_1h
            w2 = caster_1h
        elif choice == '2':
            w1 = caster_1h
            w2 = ['orb']
        elif choice == '3':
            w1 = ['quarterstaff']
            w2 = ['none']
            
    else:
        w1 = []
        w2 = []
        
    return w1, w2

def main():
    print("=== DDO ILP Gearset Optimizer ===")
    
    levels_input = input("Enter max levels to run for (comma-separated, e.g. 36, 34, 32): ")
    levels = []
    for l in levels_input.split(','):
        l = l.strip()
        if l.isdigit():
            levels.append(int(l))
    
    if not levels:
        print("No valid levels provided. Exiting.")
        return
        
    print("\n--- Build Type ---")
    print("1: Melee")
    print("2: Ranged")
    print("3: Caster")
    b_type = input("Select Build Type (1-3): ").strip()
    
    priorities = []
    if b_type == '3':
        print("\n--- Caster Details ---")
        sp_input = input("Enter preferred Spellpowers (e.g. Fire, Force, Light): ").strip()
        sch_input = input("Enter preferred Spell Schools (e.g. Evocation, Necromancy): ").strip()
        
        sp_list = [s.strip() for s in sp_input.split(',') if s.strip()]
        sch_list = [s.strip() for s in sch_input.split(',') if s.strip()]
        
        for sp in sp_list:
            priorities.append(f"{sp} Spell Power")
            priorities.append(f"{sp} Spell Lore")
            priorities.append(f"{sp} Spell Critical Damage")
        for sch in sch_list:
            priorities.append(f"{sch} DC")
            
    print("\n--- Stat Priorities ---")
    if b_type == '3':
        print("Note: Your Spellpowers and Spell Schools have automatically been placed as your top priorities.")
        print("Enter any ADDITIONAL stat priorities (comma-separated, up to 10 total).")
        print("Example: Constitution, Charisma, PRR, Dodge")
    else:
        print("Enter up to 10 stat priorities (comma-separated).")
        print("Example: Ranged Power, Doubleshot, Charisma, Constitution, PRR, Dodge, Seeker, Sneak Attack")
        
    priorities_input = input("Priorities: ")
    user_priorities = [p.strip() for p in priorities_input.split(',') if p.strip()]
    priorities.extend(user_priorities)
    
    if not priorities:
        print("No priorities provided. Exiting.")
        return
        
    if len(priorities) > 10:
        print("Truncating to the top 10 priorities.")
        priorities = priorities[:10]
        
    print("\n--- Armor Restrictions ---")
    armor_input = input("Allowed Armor (e.g. Light, Medium, Heavy, Cloth, empty for any): ").strip()
    
    w1_list, w2_list = prompt_weapon_style(b_type)
    
    print("\n--- Minor Artifact & Trinkets ---")
    art_slot_input = input("Reserved Minor Artifact Slot (e.g. Ring, Trinket. Add ' (Dino)' to force Dinosaur Bone, e.g. 'Bracers (Dino)'. Empty for Any): ").strip().lower()
    
    art_slots_in = input("Minor Artifact Filigree Slots (e.g. 3, 4, 5, empty to default 4): ").strip()
    art_slots = int(art_slots_in) if art_slots_in.isdigit() else 4
    
    gomf_input = input("Allow 'Gem of Many Facets'? (y/n, default y): ").strip().lower()
    allow_gomf = False if gomf_input == 'n' else True
        
    filename = input("\nEnter output filename (e.g. output.txt): ").strip()
    if not filename:
        filename = "gearset_output.txt"
        
    base_dir = "/Users/jorgecosgayon/dev/ddo/DDOBuilderV2/Output/DataFiles"
    
    if not os.path.exists(base_dir):
        print(f"Error: Base directory {base_dir} not found.")
        return
        
    print(f"\nParsing Sets from {base_dir}...")
    sets = optimizer.parse_sets(base_dir, priorities)
    print(f"Loaded {len(sets)} sets.")
    
    with open(filename, 'w') as out_file:
        out_file.write("======================================\n")
        out_file.write("           USER INPUTS\n")
        out_file.write("======================================\n")
        build_str = "Melee" if b_type == '1' else "Ranged" if b_type == '2' else "Caster" if b_type == '3' else "Unknown"
        out_file.write(f"Build Type: {build_str}\n")
        if b_type == '3':
            out_file.write(f"Caster Spellpowers: {sp_input}\n")
            out_file.write(f"Caster Schools: {sch_input}\n")
        out_file.write(f"Final Priorities: {', '.join(priorities)}\n")
        out_file.write(f"Armor Restriction: {armor_input or 'None'}\n")
        out_file.write(f"Reserved Minor Artifact Slot: {art_slot_input or 'Any'}\n")
        out_file.write(f"Minor Artifact Filigree Slots: {art_slots}\n")
        out_file.write(f"Allow Gem of Many Facets: {allow_gomf}\n\n")
        
        for cap in levels:
            print(f"\nParsing Items (ML 29-{cap})...")
            items = optimizer.parse_items(base_dir, cap, priorities, armor_input, w1_list, w2_list, allow_gomf, art_slot_input)
            print(f"Loaded {len(items)} items")
            
            print(f"Parsing Augments (ML 29-{cap})...")
            augments = optimizer.parse_augments(base_dir, cap, priorities)
            print(f"Loaded {len(augments)} augments")
            
            filigrees = []
            if cap >= 34:
                print(f"Parsing Filigrees...")
                filigrees, filigree_sets = optimizer.parse_filigrees(base_dir, priorities)
                print(f"Loaded {len(filigrees)} filigrees")
                for k, v in filigree_sets.items():
                    if k not in sets:
                        sets[k] = v
                    else:
                        for count, buffs in v.items():
                            sets[k][count] = buffs
                            
            print(f"Solving ILP for max level {cap} (this may take a minute)...")
            optimizer.run_optimization(items, sets, augments, filigrees, priorities, out_file, cap, art_slots)
            
    print(f"\nSuccess! Results written to {filename}")

if __name__ == "__main__":
    main()
