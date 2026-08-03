import os
import glob
import xml.etree.ElementTree as ET
import pulp
import re
import collections

def safe_name(s):
    return re.sub(r'[^a-zA-Z0-9_]', '_', str(s))

def normalize_stat_name(typ, item, desc, priorities):
    typ = (typ or '').lower()
    item = (item or '').lower()
    desc = (desc or '').lower()

    if 'skill' in typ or 'skill' in item or 'skill' in desc:
        return None

    combined = f"{item} {typ} {desc}".lower()
    
    for p in priorities:
        p_base = re.sub(r'\[\d+\]', '', p).strip()
        p_clean = p_base.lower()
        p_no_space = p_clean.replace(' ', '')
        
        matches = [p_clean, p_no_space]
        if p_clean == 'prr':
            matches.extend(['physical resistance', 'physicalresistancerating'])
        elif p_clean == 'mrr':
            matches.extend(['magical resistance', 'magicalresistancerating'])
        elif p_clean == 'hamp' or p_clean == 'healing amp':
            matches.extend(['healing amplification'])
            
        if 'spell power' in p_clean:
            matches.append(p_clean.replace('spell power', 'spellpower'))
        if 'spell crit chance' in p_clean or 'spell lore' in p_clean:
            ele = p_clean.replace('spell crit chance', '').replace('spell lore', '').strip()
            matches.append(f"{ele} spelllore")
            matches.append(f"{ele} spell lore")
        if 'spell crit damage' in p_clean or 'spell critical damage' in p_clean:
            ele = p_clean.replace('spell crit damage', '').replace('spell critical damage', '').strip()
            matches.append(f"{ele} spellcriticaldamage")
            matches.append(f"{ele} spell critical damage")
        if 'dc' in p_clean or 'focus' in p_clean:
            school = p_clean.replace('dc', '').replace('focus', '').replace('spell', '').strip()
            matches.append(f"{school} spellfocus")
            matches.append(f"{school} spell focus")
            matches.append(f"spell focus mastery")
            matches.append(f"spellfocusmastery")
            
        for m in matches:
            if m in combined:
                return p_base
    return None

def parse_items(base_dir, max_ml, priorities, allowed_armor, allowed_w1_list, allowed_w2_list, allow_gomf, art_slot_input, excluded_packs=None, quests_lookup=None, pre_equipped_names=None):
    items = []
    allowed_armor = allowed_armor.strip().lower() if allowed_armor else None
    
    force_dino = False
    if art_slot_input:
        art_slot_input = art_slot_input.lower().strip()
        if '(dino)' in art_slot_input:
            force_dino = True
            art_slot_input = art_slot_input.replace('(dino)', '').strip()
    
    for item_file in glob.glob(os.path.join(base_dir, 'Items', '*.item')):
        try:
            tree = ET.parse(item_file)
            root = tree.getroot()
            
            for item_node in root.findall('.//Item'):
                name = item_node.findtext('Name') or 'Unknown'
                is_pre_equipped = pre_equipped_names and name in pre_equipped_names
                
                ml_node = item_node.find('MinLevel')
                ml = int(ml_node.text) if ml_node is not None and ml_node.text else 0
                
                if not is_pre_equipped:
                    if ml < 29 or ml > max_ml:
                        continue
                    if not allow_gomf and "Gem of Many Facets" in name:
                        continue
                    
                weapon_type = item_node.findtext('Weapon')
                is_minor = item_node.find('MinorArtifact') is not None
                
                slots = []
                slots_node = item_node.find('EquipmentSlot') or item_node.find('Slots')
                if slots_node is not None:
                    for child in slots_node:
                        tag = child.tag
                        if tag in ['Helmet', 'Necklace', 'Trinket', 'Cloak', 'Belt', 'Ring', 'Gloves', 'Boots', 'Bracers', 'Armor', 'Goggles', 'Weapon1', 'Weapon2']:
                            slots.append(tag)
                            
                if not slots:
                    continue
                
                original_slots = slots.copy()
                
                if not is_pre_equipped:
                    if is_minor and art_slot_input:
                        matched_slots = [s for s in slots if art_slot_input in s.lower()]
                        if not matched_slots:
                            continue
                        if force_dino and 'dinosaur bone' not in name.lower():
                            continue
                        slots = matched_slots
                    elif is_minor and force_dino and not art_slot_input:
                        if 'dinosaur bone' not in name.lower():
                            continue

                    w_type_lower = (weapon_type or '').lower()
                    
                    if 'Weapon1' in slots:
                        if allowed_w1_list and w_type_lower not in allowed_w1_list:
                            slots.remove('Weapon1')
                            
                    if 'Weapon2' in slots:
                        if allowed_w2_list:
                            if 'none' in allowed_w2_list:
                                slots.remove('Weapon2')
                            elif w_type_lower not in allowed_w2_list:
                                slots.remove('Weapon2')
                    
                    armor_type = item_node.findtext('Armor')
                    if 'Armor' in slots and allowed_armor:
                        if not armor_type or allowed_armor not in armor_type.strip().lower():
                            slots.remove('Armor')
                        
                if not slots:
                    slots = original_slots if is_pre_equipped else []
                    if not slots:
                        continue

                drop_location = item_node.findtext('DropLocation') or ""
                item_is_raid = False
                item_pack = None
                
                if quests_lookup:
                    for quest_name, quest_info in quests_lookup.items():
                        if quest_name in drop_location:
                            item_pack = quest_info.get('AdventurePack')
                            item_is_raid = quest_info.get('is_raid', False)
                            break
                            
                if not item_is_raid and "raid" in drop_location.lower():
                    item_is_raid = True
                    
                if not is_pre_equipped and excluded_packs and item_pack in excluded_packs:
                    continue

                buffs = []
                for buff_node in item_node.findall('Buff'):
                    b_type = buff_node.findtext('Type')
                    b_item = buff_node.findtext('Item')
                    b_desc = buff_node.findtext('Description1')
                    b_val = buff_node.findtext('Value1')
                    b_bonus = buff_node.findtext('BonusType')
                    
                    stat = normalize_stat_name(b_type, b_item, b_desc, priorities)
                    if stat and b_val and b_bonus:
                        try:
                            val = float(b_val)
                            buffs.append((stat, b_bonus.strip(), val))
                        except ValueError:
                            pass
                
                sets = []
                for set_node in item_node.findall('.//SetBonus'):
                    if set_node.text:
                        sets.append(set_node.text.strip())
                
                augments = []
                for aug_node in item_node.findall('.//ItemAugment'):
                    a_type = aug_node.findtext('Type')
                    if a_type:
                        augments.append(a_type.strip())
                        
                items.append({
                    'name': name,
                    'file': os.path.basename(item_file),
                    'slots': slots,
                    'buffs': buffs,
                    'sets': sets,
                    'augments': augments,
                    'minor': is_minor,
                    'is_raid': item_is_raid,
                    'pack': item_pack,
                    'ml': ml
                })
        except Exception:
            pass
    return items

def parse_sets(base_dir, priorities):
    set_bonuses = {}
    try:
        tree = ET.parse(os.path.join(base_dir, 'SetBonuses.xml'))
        for set_node in tree.findall('.//SetBonus'):
            name = set_node.findtext('Type')
            if not name: continue
            
            if name not in set_bonuses:
                set_bonuses[name] = {}
                
            for buff_node in set_node.findall('Buff'):
                count = buff_node.findtext('EquippedCount')
                if not count: continue
                count = int(count)
                
                if count not in set_bonuses[name]:
                    set_bonuses[name][count] = []
                    
                for effect_node in buff_node.findall('Effect'):
                    b_types = [t.text for t in effect_node.findall('Type') if t.text]
                    b_bonus = effect_node.findtext('Bonus')
                    b_item = effect_node.findtext('Item')
                    amt_node = effect_node.find('Amount')
                    b_val = amt_node.text if amt_node is not None else None
                    
                    if b_val and b_bonus:
                        try:
                            val = float(b_val)
                            for t in b_types:
                                stat = normalize_stat_name(t, b_item, "", priorities)
                                if stat:
                                    set_bonuses[name][count].append((stat, b_bonus.strip(), val))
                        except ValueError:
                            pass
    except Exception:
        pass
    return set_bonuses

def parse_augments(base_dir, max_ml, priorities):
    augments = []
    for aug_file in glob.glob(os.path.join(base_dir, 'Augments', '*.xml')):
        try:
            tree = ET.parse(aug_file)
            for aug_node in tree.findall('.//Augment'):
                name = aug_node.findtext('Name') or 'Unknown'
                a_type = aug_node.findtext('Type')
                if not a_type: continue
                
                ml_node = aug_node.find('MinLevel')
                ml = int(ml_node.text) if ml_node is not None and ml_node.text else 0
                if ml < 29 or ml > max_ml:
                    continue
                
                buffs = []
                for effect_node in aug_node.findall('Effect'):
                    b_types = [t.text for t in effect_node.findall('Type') if t.text]
                    b_bonus = effect_node.findtext('Bonus')
                    b_item = effect_node.findtext('Item')
                    amt_node = effect_node.find('Amount')
                    b_val = amt_node.text if amt_node is not None else None
                    
                    if b_val and b_bonus:
                        try:
                            val = float(b_val)
                            for t in b_types:
                                stat = normalize_stat_name(t, b_item, "", priorities)
                                if stat:
                                    buffs.append((stat, b_bonus.strip(), val))
                        except ValueError:
                            pass
                
                if buffs:
                    augments.append({
                        'name': name,
                        'type': a_type.strip(),
                        'buffs': buffs
                    })
        except Exception:
            pass
    return augments

def parse_filigrees(base_dir, priorities):
    filigrees = []
    sets = {}
    
    for xml_file in glob.glob(os.path.join(base_dir, 'FiligreeSets', '*.xml')):
        try:
            tree = ET.parse(xml_file)
            
            for set_node in tree.findall('.//SetBonus'):
                name_node = set_node.find('Type')
                if name_node is None:
                    continue
                name = name_node.text
                if not name:
                    continue
                    
                if name not in sets:
                    sets[name] = {}
                    
                for buff_node in set_node.findall('Buff'):
                    count = buff_node.findtext('EquippedCount')
                    if not count: continue
                    count = int(count)
                    
                    if count not in sets[name]:
                        sets[name][count] = []
                        
                    for effect_node in buff_node.findall('Effect'):
                        b_types = [t.text for t in effect_node.findall('Type') if t.text]
                        b_bonus = effect_node.findtext('Bonus')
                        b_item = effect_node.findtext('Item')
                        amt_node = effect_node.find('Amount')
                        b_val = amt_node.text if amt_node is not None else None
                        
                        if b_val and b_bonus:
                            try:
                                val = float(b_val)
                                for t in b_types:
                                    stat = normalize_stat_name(t, b_item, "", priorities)
                                    if stat:
                                        sets[name][count].append((stat, b_bonus.strip(), val))
                            except ValueError:
                                pass
            
            for f_node in tree.findall('.//Filigree'):
                name = f_node.findtext('Name') or 'Unknown'
                set_bonus = f_node.findtext('SetBonus')
                
                buffs = []
                for effect_node in f_node.findall('Effect'):
                    b_types = [t.text for t in effect_node.findall('Type') if t.text]
                    b_bonus = effect_node.findtext('Bonus')
                    b_item = effect_node.findtext('Item')
                    amt_node = effect_node.find('Amount')
                    b_val = amt_node.text if amt_node is not None else None
                    
                    if b_val and b_bonus:
                        try:
                            val = float(b_val)
                            for t in b_types:
                                stat = normalize_stat_name(t, b_item, "", priorities)
                                if stat:
                                    buffs.append((stat, b_bonus.strip(), val))
                        except ValueError:
                            pass
                            
                base_name = name.split(':')[0].strip() if ':' in name else name
                
                if buffs:
                    filigrees.append({
                        'name': name,
                        'base_name': base_name,
                        'set': set_bonus,
                        'buffs': buffs
                    })
        except Exception:
            pass
            
    return filigrees, sets

def create_model(items, sets, augments, filigrees, priorities, art_slots, required_slots, raid_item_limit=None, pre_equipped=None, pre_filled_augments=None, pre_filled_filigrees=None, calculate_only=False):
    if pre_equipped is None:
        pre_equipped = {}
    if pre_filled_augments is None:
        pre_filled_augments = {}
    if pre_filled_filigrees is None:
        pre_filled_filigrees = {}
    WEIGHTS = {}
    CAPS = {}
    
    for stat_name, weight_val in priorities.items():
        p_base = re.sub(r'\[\d+\]', '', stat_name).strip()
        cap_match = re.search(r'\[(\d+)\]', stat_name)
        if cap_match:
            CAPS[p_base] = float(cap_match.group(1))
            
        WEIGHTS[p_base] = float(weight_val)

    prob = pulp.LpProblem("DDO_Gear_Optimization", pulp.LpMaximize)
    
    x = {}
    for i, item in enumerate(items):
        for slot in item['slots']:
            if slot == 'Ring':
                x[(i, 'Ring_1')] = pulp.LpVariable(f"x_{i}_Ring_1", cat="Binary")
                x[(i, 'Ring_2')] = pulp.LpVariable(f"x_{i}_Ring_2", cat="Binary")
            else:
                x[(i, slot)] = pulp.LpVariable(f"x_{i}_{slot}", cat="Binary")
                
    if pre_equipped:
        for slot, eq_name in pre_equipped.items():
            if slot in required_slots:
                for i, item in enumerate(items):
                    if item['name'] == eq_name:
                        if (i, slot) in x:
                            prob += x[(i, slot)] == 1
                        break
                
    y = {}
    for i, item in enumerate(items):
        color_counts = collections.Counter(item['augments'])
        for color, limit in color_counts.items():
            for aug_idx, aug in enumerate(augments):
                if aug['type'].lower() == color.lower() or color.lower() in aug['type'].lower():
                    y[(aug_idx, i, color)] = pulp.LpVariable(f"y_{aug_idx}_{i}_{safe_name(color)}", cat="Binary")
                    
    fw = {}
    fm = {}
    for idx, f in enumerate(filigrees):
        fw[idx] = pulp.LpVariable(f"fw_{idx}", cat="Binary")
        fm[idx] = pulp.LpVariable(f"fm_{idx}", cat="Binary")
        
    if pre_filled_augments and pre_equipped:
        for slot, aug_list in pre_filled_augments.items():
            if slot in required_slots and slot in pre_equipped:
                eq_name = pre_equipped[slot]
                for i, item in enumerate(items):
                    if item['name'] == eq_name:
                        for aug_name in aug_list:
                            if not aug_name: continue
                            matched_aug_idx = None
                            for idx, a in enumerate(augments):
                                if a['name'] == aug_name:
                                    matched_aug_idx = idx
                                    break
                            if matched_aug_idx is not None:
                                matched_aug = augments[matched_aug_idx]
                                matched_color = None
                                color_counts = collections.Counter(item['augments'])
                                for c in color_counts.keys():
                                    if matched_aug['type'].lower() == c.lower() or c.lower() in matched_aug['type'].lower():
                                        if (matched_aug_idx, i, c) in y:
                                            matched_color = c
                                            break
                                if matched_color:
                                    prob += y[(matched_aug_idx, i, matched_color)] == 1
                        break

    if pre_filled_filigrees and filigrees:
        w_fils = pre_filled_filigrees.get('weapon', [])
        a_fils = pre_filled_filigrees.get('artifact', [])
        
        for fname in w_fils:
            if not fname: continue
            for idx, f in enumerate(filigrees):
                if f['name'] == fname:
                    prob += fw[idx] == 1
                    break
                    
        for fname in a_fils:
            if not fname: continue
            for idx, f in enumerate(filigrees):
                if f['name'] == fname:
                    prob += fm[idx] == 1
                    break
        
    w_vars = {}
    for k, tiers in sets.items():
        for m in tiers.keys():
            w_vars[(k, m)] = pulp.LpVariable(f"w_{safe_name(k)}_{m}", cat="Binary")
            
    z = {}
    delta = {}
    
    for slot in required_slots:
        prob += pulp.lpSum([x[(i, s)] for (i, s) in x.keys() if s == slot]) == 1
        
    if calculate_only:
        # Force all unequipped slots to be empty
        all_possible_slots = set(s for (_, s) in x.keys())
        for slot in all_possible_slots:
            if slot not in required_slots:
                prob += pulp.lpSum([x[(i, s)] for (i, s) in x.keys() if s == slot]) == 0
                
    for i in range(len(items)):
        prob += pulp.lpSum([x[(i, s)] for (item_idx, s) in x.keys() if item_idx == i]) <= 1
        
    minor_vars = []
    for i, item in enumerate(items):
        if item['minor']:
            minor_vars.extend([x[(item_idx, s)] for (item_idx, s) in x.keys() if item_idx == i])
    if minor_vars:
        prob += pulp.lpSum(minor_vars) == 1
        
    if raid_item_limit is not None and raid_item_limit >= 0:
        raid_vars = []
        for i, item in enumerate(items):
            if item.get('is_raid'):
                raid_vars.extend([x[(item_idx, s)] for (item_idx, s) in x.keys() if item_idx == i])
        if raid_vars:
            prob += pulp.lpSum(raid_vars) <= raid_item_limit, "Max_Raid_Items"
        
    for i, item in enumerate(items):
        color_counts = collections.Counter(item['augments'])
        for color, limit in color_counts.items():
            valid_y = [y[(a, item_idx, c)] for (a, item_idx, c) in y.keys() if item_idx == i and c == color]
            item_is_equipped = pulp.lpSum([x[(item_idx, s)] for (item_idx, s) in x.keys() if item_idx == i])
            if valid_y:
                prob += pulp.lpSum(valid_y) <= limit * item_is_equipped
                
    for a in range(len(augments)):
        prob += pulp.lpSum([y[(aug_idx, i, c)] for (aug_idx, i, c) in y.keys() if aug_idx == a]) <= 1
        
    if calculate_only:
        # To strictly compute what was passed, force sum of y to equal the number of pre-filled augments
        total_pre_filled_augments = sum(len([a for a in aug_list if a]) for aug_list in pre_filled_augments.values()) if pre_filled_augments else 0
        prob += pulp.lpSum(y.values()) == total_pre_filled_augments
        
    if filigrees:
        base_name_groups = collections.defaultdict(list)
        for idx, f in enumerate(filigrees):
            base_name_groups[f['base_name']].append(idx)
            
        for base_name, idx_list in base_name_groups.items():
            if len(idx_list) > 1:
                prob += pulp.lpSum([fw[idx] for idx in idx_list]) <= 1
                prob += pulp.lpSum([fm[idx] for idx in idx_list]) <= 1
                
        prob += pulp.lpSum(fw.values()) <= 10
        
        if calculate_only:
            total_w_fils = len([f for f in pre_filled_filigrees.get('weapon', []) if f]) if pre_filled_filigrees else 0
            total_m_fils = len([f for f in pre_filled_filigrees.get('artifact', []) if f]) if pre_filled_filigrees else 0
            prob += pulp.lpSum(fw.values()) == total_w_fils
            prob += pulp.lpSum(fm.values()) == total_m_fils
        
        max_fm_slots_expr = []
        for i, item in enumerate(items):
            if item['minor']:
                slots_for_item = 3
                if item['name'] == "Epic Voice of the Master":
                    slots_for_item = 1
                elif item.get('ml', 0) >= 33:
                    slots_for_item = 5
                elif item.get('ml', 0) >= 31:
                    slots_for_item = 4
                elif item.get('ml', 0) >= 30:
                    slots_for_item = 3
                
                item_equipped_var = pulp.lpSum([x[(item_idx, s)] for (item_idx, s) in x.keys() if item_idx == i])
                max_fm_slots_expr.append(slots_for_item * item_equipped_var)
                
        if max_fm_slots_expr:
            prob += pulp.lpSum(fm.values()) <= pulp.lpSum(max_fm_slots_expr)
        else:
            prob += pulp.lpSum(fm.values()) <= 0
        
    for k, tiers in sets.items():
        pieces = pulp.lpSum([x[(i, s)] for (i, s) in x.keys() if k in items[i]['sets']])
        if filigrees:
            pieces += pulp.lpSum([fw[idx] + fm[idx] for idx, f in enumerate(filigrees) if f['set'] == k])
            
        for m in tiers.keys():
            prob += m * w_vars[(k, m)] <= pieces
            
    sources = collections.defaultdict(list)
    
    for (i, s), var in x.items():
        for stat, b_type, val in items[i]['buffs']:
            sources[(stat, b_type)].append((val, var))
            
    for (a, i, c), var in y.items():
        for stat, b_type, val in augments[a]['buffs']:
            sources[(stat, b_type)].append((val, var))
            
    for idx, f in enumerate(filigrees):
        for stat, b_type, val in f['buffs']:
            sources[(stat, b_type)].append((val, fw[idx]))
            sources[(stat, b_type)].append((val, fm[idx]))
            
    for (k, m), var in w_vars.items():
        for stat, b_type, val in sets[k][m]:
            sources[(stat, b_type)].append((val, var))
            
    source_counter = 0
    objective_terms = []
    
    for (stat, b_type), srclist in sources.items():
        z_var = pulp.LpVariable(f"z_{stat}_{safe_name(b_type)}", lowBound=0)
        z[(stat, b_type)] = z_var
        
        if b_type.lower().strip() in ['stacking', 'mythic', 'reaper']:
            expr = []
            for val, var in srclist:
                expr.append(val * var)
            prob += z_var == pulp.lpSum(expr)
        else:
            deltas = []
            d_vars_for_this_stat = []
            for val, var in srclist:
                d_var = pulp.LpVariable(f"d_{source_counter}", cat="Binary")
                delta[source_counter] = d_var
                d_vars_for_this_stat.append(d_var)
                
                prob += d_var <= var
                deltas.append(val * d_var)
                source_counter += 1
                
            prob += pulp.lpSum(d_vars_for_this_stat) <= 1
            prob += z_var == pulp.lpSum(deltas)
        
    stat_totals = collections.defaultdict(list)
    for (stat, b_type), z_var in z.items():
        stat_totals[stat].append(z_var)
        
    for stat, z_list in stat_totals.items():
        if stat in WEIGHTS:
            if stat in CAPS:
                capped_var = pulp.LpVariable(f"capped_total_{safe_name(stat)}", lowBound=0, upBound=CAPS[stat])
                prob += capped_var <= pulp.lpSum(z_list)
                objective_terms.append(WEIGHTS[stat] * capped_var)
            else:
                objective_terms.append(WEIGHTS[stat] * pulp.lpSum(z_list))
            
    prob += pulp.lpSum(objective_terms)
    
    return prob, x, y, fw, fm, w_vars, z

def solve_for_alternatives(items, sets, augments, filigrees, priorities, art_slots, required_slots, equipped_items, target_slot, num_alts, raid_item_limit=None):
    alternatives = []
    forbidden_items = [equipped_items[target_slot]]
    
    for _ in range(num_alts):
        prob, x, y, fw, fm, w_vars, z = create_model(items, sets, augments, filigrees, priorities, art_slots, required_slots, raid_item_limit, None, None, None)
        
        # Lock all slots except target_slot
        for slot, eq_item in equipped_items.items():
            if slot != target_slot:
                item_idx = items.index(eq_item)
                if (item_idx, slot) in x:
                    prob += x[(item_idx, slot)] == 1
                    
        # Ban previously found items for the target_slot
        for f_item in forbidden_items:
            f_idx = items.index(f_item)
            if (f_idx, target_slot) in x:
                prob += x[(f_idx, target_slot)] == 0
                
        prob.solve(pulp.GLPK_CMD(msg=1, path="/opt/homebrew/bin/glpsol", options=["--log", "solver_progress.log"]))
        
        if prob.status == 1:
            for (i, s), var in x.items():
                if s == target_slot and var.varValue and var.varValue > 0.5:
                    alt_item = items[i]
                    alternatives.append(alt_item)
                    forbidden_items.append(alt_item)
                    break
        else:
            break
            
    return alternatives

def run_optimization(items, sets, augments, filigrees, priorities, out_file, cap, art_slots, raid_item_limit=None, pre_equipped=None, pre_filled_augments=None, pre_filled_filigrees=None, calculate_only=False):
    # Required slots based on available items
    available_slots = set()
    for item in items:
        for slot in item['slots']:
            if slot == 'Ring':
                available_slots.add('Ring_1')
                available_slots.add('Ring_2')
            else:
                available_slots.add(slot)
            
    base_required = ['Helmet', 'Necklace', 'Trinket', 'Cloak', 'Belt', 'Ring_1', 'Ring_2', 'Gloves', 'Boots', 'Bracers', 'Armor', 'Goggles', 'Weapon1', 'Weapon2']
    if calculate_only and pre_equipped:
        required_slots = [s for s in base_required if s in available_slots and s in pre_equipped]
    else:
        required_slots = [s for s in base_required if s in available_slots]
    
    prob, x, y, fw, fm, w_vars, z = create_model(items, sets, augments, filigrees, priorities, art_slots, required_slots, raid_item_limit, pre_equipped, pre_filled_augments, pre_filled_filigrees, calculate_only)
    
    out_file.write(f"\n======================================\n")
    out_file.write(f"       RUNNING FOR MAX LEVEL {cap}\n")
    out_file.write(f"======================================\n\n")
    
    prob.solve(pulp.GLPK_CMD(msg=1, path="/opt/homebrew/bin/glpsol", options=["--log", "solver_progress.log"]))
    
    out_file.write(f"Status: {pulp.LpStatus[prob.status]}\n")
    if prob.status != 1:
        out_file.write("Could not find a feasible set of gear for this cap/priorities.\n")
        return
    
    out_file.write("\n=== EQUIPPED ITEMS ===\n")
    equipped = {}
    equipped_simple = {}
    for (i, s), var in x.items():
        if var.varValue and var.varValue > 0.5:
            equipped[s] = items[i]
            equipped_simple[s] = items[i]['name']
            
    for slot in required_slots:
        if slot in equipped:
            item = equipped[slot]
            if item['minor']:
                out_file.write(f"{slot}: {item['name']} (Minor Artifact) (ML: {item['file']})\n")
            else:
                out_file.write(f"{slot}: {item['name']} (ML: {item['file']})\n")
            for (a, i, c), y_var in y.items():
                if i == items.index(item) and y_var.varValue and y_var.varValue > 0.5:
                    out_file.write(f"  + Augment [{c}]: {augments[a]['name']}\n")
                    
    # Find Alternatives for Weapon1 and Weapon2
    for w_slot in ['Weapon1', 'Weapon2']:
        if w_slot in equipped:
            alts = solve_for_alternatives(items, sets, augments, filigrees, priorities, art_slots, required_slots, equipped, w_slot, 2, raid_item_limit)
            if alts:
                out_file.write(f"\n  [{w_slot} Alternatives]:\n")
                for alt_idx, alt_item in enumerate(alts):
                    out_file.write(f"    Alt {alt_idx + 1}: {alt_item['name']} (ML: {alt_item['file']})\n")

    if filigrees:
        w_fil = [f for idx, f in enumerate(filigrees) if fw[idx].varValue and fw[idx].varValue > 0.5]
        m_fil = [f for idx, f in enumerate(filigrees) if fm[idx].varValue and fm[idx].varValue > 0.5]
        
        if w_fil:
            out_file.write(f"\n=== WEAPON FILIGREES ===\n")
            for f in w_fil:
                out_file.write(f"  + {f['name']}\n")
                
        if m_fil:
            out_file.write(f"\n=== MINOR ARTIFACT FILIGREES ===\n")
            for f in m_fil:
                out_file.write(f"  + {f['name']}\n")
                    
    active_sets_out = []
    out_file.write("\n=== ACTIVE SET BONUSES ===\n")
    for (k, m), w_var in w_vars.items():
        if w_var.varValue and w_var.varValue > 0.5:
            out_file.write(f"{k} ({m}-piece)\n")
            active_sets_out.append(f"{k} ({m}-piece)")
            if k in sets and m in sets[k]:
                for stat, bonus, val in sets[k][m]:
                    out_file.write(f"  + {val} {bonus} bonus to {stat}\n")
            
    realized_stats_out = {}
    out_file.write("\n=== REALIZED STATS ===\n")
    for p in priorities:
        p_base = re.sub(r'\[\d+\]', '', p).strip()
        total = 0
        details = []
        for (st, b_type), z_var in z.items():
            if st.lower() == p_base.lower() and z_var.varValue and z_var.varValue > 0:
                total += z_var.varValue
                details.append(f"{z_var.varValue} {b_type}")
        if total > 0:
            out_file.write(f"{p}: {total} ({', '.join(details)})\n")
            realized_stats_out[p] = total

    filigrees_out = {"weapon": [], "artifact": []}
    if filigrees:
        w_fil = [f for idx, f in enumerate(filigrees) if fw[idx].varValue and fw[idx].varValue > 0.5]
        m_fil = [f for idx, f in enumerate(filigrees) if fm[idx].varValue and fm[idx].varValue > 0.5]
        for f in w_fil:
            filigrees_out["weapon"].append(f['name'])
        for f in m_fil:
            filigrees_out["artifact"].append(f['name'])
            
    all_effects_out = {}
    for (st, b_type), z_var in z.items():
        if z_var.varValue and z_var.varValue > 0:
            if st not in all_effects_out:
                all_effects_out[st] = []
            all_effects_out[st].append(f"{z_var.varValue} {b_type}")

    rich_output = {
        "gearSet": equipped_simple,
        "realizedStats": realized_stats_out,
        "activeSets": active_sets_out,
        "filigrees": filigrees_out,
        "allEffects": all_effects_out
    }
    return rich_output
