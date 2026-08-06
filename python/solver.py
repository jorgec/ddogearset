import json
import sys
import os
import re
import parser
import optimizer
from optimizer import PriorityEntry

VALID_MODES = ("optimize", "calculate", "alternatives", "stat_search")

# §2.6 — every validation message starts with this literal prefix.
VALIDATION_PREFIX = "Stat priority validation failed: "

MIN_TIER = 1
MAX_TIER = 5


def parse_payload(payload):
    # Just returns the payload for now, any required normalization can happen here
    return payload


def fail(message):
    """Prints the failure payload on the existing JSON_RESULT channel, then
    exits 1. app.go returns the captured payload even on a non-zero exit."""
    print(f"JSON_RESULT:{json.dumps({'success': False, 'errorMessage': message})}")
    sys.exit(1)


def _legacy_tier(value):
    """§2.4 — legacy 1-100 `value` -> tier."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    if v >= 100:
        return 1
    if v >= 75:
        return 2
    if v >= 50:
        return 3
    if v >= 25:
        return 4
    return 5


def _cap_from_suffix(raw_name):
    m = re.search(r'\[(\d+)\]', str(raw_name))
    return float(m.group(1)) if m else None


def parse_stat_priorities(raw, warnings=None):
    """Accepts Shape A / B / C (§2.4). Returns (entries, None) on success or
    ([], error_message) on validation failure. Runs BEFORE any XML parsing.

    `warnings` is an optional list that collects non-fatal notes (currently only
    the cap/`[N]`-suffix disagreement of EC-22), which main() writes to
    out_file once it is open.
    """
    if warnings is None:
        warnings = []

    if not raw:
        return [], VALIDATION_PREFIX + "no stat priorities were provided."

    # --- shape detection (§2.4) -------------------------------------------
    raw_entries = []
    if isinstance(raw, dict):
        # Shape A — legacy dict. Intra-tier order is JSON object insertion
        # order, guaranteed since Python 3.7.
        for name, value in raw.items():
            raw_entries.append({"stat": name, "tier": _legacy_tier(value), "cap": None})
    elif isinstance(raw, (list, tuple)):
        has_tier = any(isinstance(e, dict) and 'tier' in e for e in raw)
        for e in raw:
            if not isinstance(e, dict):
                continue
            name = e.get('stat')
            if not name:
                continue
            if has_tier:
                # Shape C — elements *without* tier are a validation error.
                if 'tier' not in e:
                    return [], (VALIDATION_PREFIX +
                                f"entry '{name}' is missing a tier.")
                tier = e.get('tier')
            else:
                # Shape B — Phase 9 ordered list with `value`.
                tier = _legacy_tier(e.get('value'))
            raw_entries.append({"stat": name, "tier": tier, "cap": e.get('cap')})
    else:
        return [], VALIDATION_PREFIX + "no stat priorities were provided."

    if not raw_entries:
        return [], VALIDATION_PREFIX + "no stat priorities were provided."

    # --- validation (§2.6) -------------------------------------------------
    seen = {}          # normalized key -> (display name, tier)
    tier_counts = {}
    entries = []

    for e in raw_entries:
        raw_name = e['stat']
        base = optimizer.strip_cap_suffix(raw_name)
        key = optimizer.normalize_stat_key(raw_name)

        tier = e['tier']
        if not isinstance(tier, int) or isinstance(tier, bool):
            try:
                tier = int(tier)
            except (TypeError, ValueError):
                return [], (VALIDATION_PREFIX +
                            f"'{base}' has invalid tier {e['tier']!r} (must be 1-5).")
        if tier < MIN_TIER or tier > MAX_TIER:
            return [], (VALIDATION_PREFIX +
                        f"'{base}' has invalid tier {tier} (must be 1-5).")

        if key in seen:
            prev_name, prev_tier = seen[key]
            if prev_tier == tier:
                return [], (VALIDATION_PREFIX +
                            f"'{prev_name}' is listed more than once in tier {tier}.")
            return [], (VALIDATION_PREFIX +
                        f"'{prev_name}' appears in more than one tier "
                        f"(tiers {prev_tier} and {tier}). Each stat may be listed only once.")
        seen[key] = (base, tier)

        suffix_cap = _cap_from_suffix(raw_name)
        cap = e.get('cap')
        if cap is not None:
            if isinstance(cap, bool) or not isinstance(cap, (int, float)) or \
                    float(cap) != int(cap) or int(cap) <= 0:
                return [], (VALIDATION_PREFIX +
                            f"'{base}' has invalid cap {cap!r} (must be a positive integer).")
            cap = float(int(cap))
            # EC-22 — the `cap` field wins over a "[N]" suffix; warn on disagreement.
            if suffix_cap is not None and suffix_cap != cap:
                warnings.append(
                    f"Priority '{raw_name}' declares cap {int(cap)} and suffix cap "
                    f"{int(suffix_cap)}; using the cap field ({int(cap)}).")
        else:
            cap = suffix_cap

        order = tier_counts.get(tier, 0)
        tier_counts[tier] = order + 1
        entries.append(PriorityEntry(stat=base, tier=tier, cap=cap, order=order))

    return entries, None


def normalize_mode(parsed_data):
    """(mode, error_message). §2.5. `calculate_only` remains accepted as a
    legacy field and is never read again after normalization."""
    mode = parsed_data.get('mode')
    if mode:
        mode = str(mode).strip().lower()
        if mode not in VALID_MODES:
            return None, VALIDATION_PREFIX + f"unknown mode '{parsed_data.get('mode')}'."
        return mode, None
    if parsed_data.get('calculate_only'):
        return "calculate", None
    return "optimize", None


def resolve_weapon_lists(parsed_data):
    """Weapon-style filtering. Extracted so the alternatives path uses exactly
    the same pool the main solve would.

    Returns (w1_list, w2_list, require_weapon2, weapon1_eligible_types,
    weapon2_eligible_types). `require_weapon2` is True for the cases scoped in
    docs/HARD_REQUIRED_SLOTS_SPEC.md: Single Weapon Fighting with
    offhand_style == 'Runearm', the caster 'Stick and Runearm'/'Dual
    Caster'/'Stick and Orb' styles, any crossbow style with runearm_use
    checked, Thrown/Shuriken (off-hand Kama), and Tank (shield). Everywhere
    else, runearm_use is ignored outright — it no longer blends a runearm
    into TWF/Sword and Board's Weapon2 pool as an optional extra, per
    explicit instruction: those styles keep their normal offhand/second-
    weapon and never touch a runearm.

    `weapon1_eligible_types`/`weapon2_eligible_types` (each a set of
    lowercase weapon_type strings, or None) feed create_model's craftable-
    family + highest-ML restriction — see docs/HARD_REQUIRED_SLOTS_SPEC.md's
    Ranged/Tank addendum. They narrow WITHIN whatever w1_list/w2_list already
    allows; they don't by themselves grant a slot that w1_list/w2_list denies."""
    build_type = parsed_data.get('build_type', 'Melee')
    weapon_style = parsed_data.get('weapon_style', 'Two Weapon Fighting')
    runearm_use = parsed_data.get('runearm_use', False)

    weapon1_eligible_types = None
    weapon2_eligible_types = None

    # Tank: fixed Longsword + Large Shield, both from the craftable families,
    # REGARDLESS of whatever weapon_style is selected — this is a blanket
    # override, not one more weapon_style branch, per explicit instruction.
    if build_type == 'Tank':
        return (['longsword'], ['large shield'], True, {'longsword'}, {'large shield'})

    twf_weapons = ['dagger', 'kukri', 'rapier', 'scimitar', 'longsword', 'khopesh', 'handwraps', 'shortsword', 'kama', 'sickle', 'battle axe', 'hand axe', 'dwarven waraxe', 'bastard sword', 'heavy mace', 'light mace', 'morningstar', 'club', 'light pick', 'heavy pick', 'warhammer']
    thf_weapons = ['great sword', 'falchion', 'great axe', 'maul', 'quarterstaff', 'great club']
    swash_weapons = ['dagger', 'kukri', 'rapier', 'shortsword', 'hand axe', 'kama', 'sickle', 'light mace', 'light pick', 'heavy pick', 'throwing dagger', 'throwing axe', 'dart']
    shields = ['buckler', 'small shield', 'large shield', 'tower shield']
    # "Caster stick" = any one-handed weapon (docs/HARD_REQUIRED_SLOTS_SPEC.md
    # §4) — the authoritative "One Handed" WeaponGroupings.xml group, same
    # source as optimizer.WEAPON_DAMAGE_TYPES. The old hardcoded caster_1h
    # list (club/dagger/sickle/heavy mace/light mace/morningstar/scepter/
    # shortsword) was both too narrow (missing e.g. longsword, rapier, kukri,
    # scimitar) and included "scepter", which isn't a real DDO weapon type at
    # all and never matched anything.
    caster_1h = sorted(optimizer.ONE_HANDED_WEAPON_TYPES)
    runearm_offhand = ['rune arm', 'runearm']

    require_weapon2 = False

    if weapon_style == 'Two Handed Fighting':
        w1_list = thf_weapons
        w2_list = ['none']
    elif weapon_style == 'Two Weapon Fighting':
        w1_list = twf_weapons
        w2_list = twf_weapons
    elif weapon_style == 'Single Weapon Fighting':
        swashbuckling = parsed_data.get('swashbuckling', False)
        w1_list = swash_weapons if swashbuckling else twf_weapons
        if swashbuckling:
            w2_list = ['none', 'buckler', 'orb'] + runearm_offhand
        else:
            offhand_style = parsed_data.get('offhand_style', 'Empty')
            if offhand_style == 'Buckler':
                w2_list = ['buckler']
            elif offhand_style == 'Shield':
                w2_list = shields
            elif offhand_style == 'Orb':
                w2_list = ['orb']
            elif offhand_style == 'Runearm':
                w2_list = runearm_offhand
                require_weapon2 = True
            else:
                w2_list = ['none']
    elif weapon_style == 'Sword and Board':
        w1_list = twf_weapons
        w2_list = shields
    elif weapon_style == 'Bow':
        # Bows always lock out Weapon2 entirely (explicit instruction) — and
        # always specifically a Longbow, never a Shortbow.
        w1_list = ['longbow', 'shortbow']
        w2_list = ['none']
        weapon1_eligible_types = {'longbow'}
    elif weapon_style == 'Repeating Crossbow':
        w1_list = ['repeating light crossbow', 'repeating heavy crossbow']
        w2_list = runearm_offhand if runearm_use else ['none']
        require_weapon2 = runearm_use
        weapon1_eligible_types = {'repeating heavy crossbow'}
    elif weapon_style == 'Great Crossbow':
        w1_list = ['great crossbow']
        w2_list = runearm_offhand if runearm_use else ['none']
        require_weapon2 = runearm_use
        weapon1_eligible_types = {'great crossbow'}
    elif weapon_style == 'Dual Crossbow':
        # "Other crossbows" — always Heavy Crossbow, never Light Crossbow.
        w1_list = ['light crossbow', 'heavy crossbow']
        w2_list = runearm_offhand if runearm_use else ['none']
        require_weapon2 = runearm_use
        weapon1_eligible_types = {'heavy crossbow'}
    elif weapon_style == 'Thrown':
        # Throwers: Weapon1 stays whichever of the style's own ranged types
        # scores best (no further narrowing beyond craftable-family/ML, since
        # none of throwing dagger/axe/dart carry a DDOBuilderV2 damage-type
        # classification anyway); Weapon2 is always specifically a Kama.
        w1_list = ['throwing dagger', 'throwing axe', 'dart']
        w2_list = ['kama']
        require_weapon2 = True
        weapon1_eligible_types = set(w1_list)
        weapon2_eligible_types = {'kama'}
    elif weapon_style == 'Shuriken':
        w1_list = ['shuriken']
        w2_list = ['kama']
        require_weapon2 = True
        weapon1_eligible_types = {'shuriken'}
        weapon2_eligible_types = {'kama'}
    elif weapon_style == 'Dual Caster':
        # "Dual caster sticks" — both Weapon1 and Weapon2 required, both any
        # one-handed weapon (docs/HARD_REQUIRED_SLOTS_SPEC.md §4).
        w1_list = caster_1h
        w2_list = caster_1h
        require_weapon2 = True
    elif weapon_style == 'Stick and Orb':
        w1_list = caster_1h
        w2_list = ['orb']
        require_weapon2 = True
    elif weapon_style == 'Stick and Runearm':
        w1_list = caster_1h
        w2_list = runearm_offhand
        require_weapon2 = True
    elif weapon_style == 'Quarterstaff':
        w1_list = ['quarterstaff']
        w2_list = ['none']
    else:
        w1_list = twf_weapons
        w2_list = twf_weapons

    # Melee damage-type restriction (docs/HARD_REQUIRED_SLOTS_SPEC.md §1) —
    # applies on top of whatever weapon_style already narrowed w1_list to
    # (e.g. Two Handed Fighting's list spans both Slashing and Bludgeoning
    # types; picking a damage type here correctly narrows within it).
    if build_type == 'Melee':
        weapon_damage_type = parsed_data.get('weapon_damage_type')
        if weapon_damage_type:
            weapon1_eligible_types = optimizer.weapon_types_for_damage_type(weapon_damage_type)

    return w1_list, w2_list, require_weapon2, weapon1_eligible_types, weapon2_eligible_types


def derive_required_slots(items):
    available_slots = set()
    for item in items:
        for slot in item['slots']:
            if slot == 'Ring':
                available_slots.add('Ring_1')
                available_slots.add('Ring_2')
            else:
                available_slots.add(slot)
    base_required = ['Helmet', 'Necklace', 'Trinket', 'Cloak', 'Belt', 'Ring_1', 'Ring_2',
                     'Gloves', 'Boots', 'Bracers', 'Armor', 'Goggles', 'Weapon1', 'Weapon2']
    return [s for s in base_required if s in available_slots]


def run_alternatives(parsed_data, entries, items, sets, augments, filigrees,
                     required_slots, out_file):
    """mode == 'alternatives' branch (§7). Cold-callable: no prior optimization
    run is required."""
    target_slot = parsed_data.get('target_slot') or ''
    current_item = parsed_data.get('current_item') or ''
    equipped_items = parsed_data.get('equipped_items') or {}
    count = parsed_data.get('count', 5)
    pre_filled_augments = parsed_data.get('pre_filled_augments', {})
    pre_filled_filigrees = parsed_data.get('pre_filled_filigrees', {})

    if not target_slot:
        return {"success": False, "slot": "", "baselineTierScores": {},
                "alternatives": [], "errorMessage": "No target slot was supplied."}

    caps = {e.stat: float(e.cap) for e in entries if e.cap is not None}

    # §7.3 — UB_s comes from the FULL parsed pool (the same
    # compute_stat_upper_bounds call the main solve would make), not from the
    # candidate set, so TierScores stay comparable to a main-solve G_t and
    # comparable across candidates.
    ub_sources = optimizer.build_ub_sources(items, sets, augments, filigrees, required_slots)
    ub_all = optimizer.compute_stat_upper_bounds(ub_sources, items, required_slots, caps, True)
    ub_nofil = optimizer.compute_stat_upper_bounds(ub_sources, items, required_slots, caps, False)

    usable = [e for e in entries if e.stat in ub_all]
    weights = optimizer.compute_tier_weights(usable)

    out_file.write(f"\n=== SLOT ALTERNATIVES: {target_slot} ===\n")
    out_file.write(f"Current item: {current_item or '(empty)'}\n")

    result = optimizer.find_slot_alternatives(
        items, sets, augments, filigrees, entries, required_slots,
        equipped_items, pre_filled_augments, pre_filled_filigrees,
        target_slot, current_item, count, ub_all, ub_nofil, weights)

    for alt in result.get('alternatives', []):
        out_file.write(f"  {alt['rank']}. {alt['itemName']} "
                       f"(objective {alt['objectiveScore']})\n")
    for w in result.get('warnings', []):
        out_file.write(f"  ! {w}\n")

    return result


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

    mode, err = normalize_mode(parsed_data)
    if err:
        fail(err)

    # Fail loud and early: _glpk_cmd() also raises if glpsol can't be
    # resolved, but that's called from inside _solve()'s broad except, which
    # would otherwise turn a missing/misconfigured GLPK into a generic "no
    # feasible solution" instead of this specific, actionable message.
    if optimizer.resolve_glpsol_path() is None:
        fail("GLPK (glpsol) could not be found. This build's bundled glpsol may be "
             "missing or failed to extract; set GLPSOL_PATH, or install GLPK so "
             "'glpsol' is on PATH, to run the solver directly.")

    priority_warnings = []
    if mode == "stat_search":
        search_stat = parsed_data.get('stat', '')
        if not search_stat:
            fail("No stat provided for stat_search mode.")
        priority_names = [search_stat]
        entries = []
    else:
        # --- validation runs BEFORE any XML parsing (§2.6) ---------------------
        entries, err = parse_stat_priorities(parsed_data.get('stat_priorities'), priority_warnings)
        if err:
            fail(err)

        # INV-2: priority_names must contain stats from ALL FIVE tiers. Dropping
        # tier-5 stats would make matching XML data invisible to normalize_stat_name
        # and therefore to the entire model.
        priority_names = [e.stat for e in entries]

    armor_input = parsed_data.get('armor_restriction', '')
    # docs/HARD_REQUIRED_SLOTS_SPEC.md — weapon1_eligible_types/
    # weapon2_eligible_types are computed inside resolve_weapon_lists per
    # build_type/weapon_style (melee damage-type selection, fixed per-style
    # types for Ranged, a fixed Longsword/Large-Shield override for Tank).
    w1_list, w2_list, require_weapon2, weapon1_eligible_types, weapon2_eligible_types = \
        resolve_weapon_lists(parsed_data)

    allow_gomf = not parsed_data.get('exclude_gem_of_many_facets', False)
    art_slot_input = parsed_data.get('reserved_minor_artifact_slot', '')
    if parsed_data.get('is_dino_artifact', False):
        art_slot_input += ' (dino)'
    art_slots = parsed_data.get('minor_artifact_filigree_slots', 4)
    excluded_packs = parsed_data.get('excluded_packs', [])
    # docs/TROVE_INVENTORY_IMPORT_SPEC.md — None (not []) means "no
    # restriction": an ABSENT/empty owned_item_names must behave exactly
    # like today's unrestricted catalog (AC-3), not "the player owns
    # nothing". parse_items/parse_augments treat owned_names=None as
    # unrestricted and an empty set as "match nothing", so this can't
    # collapse the two cases.
    owned_item_names_raw = parsed_data.get('owned_item_names')
    owned_item_names = set(owned_item_names_raw) if owned_item_names_raw else None
    raid_item_limit = parsed_data.get('raid_item_limit', None)
    pre_equipped = parsed_data.get('pre_equipped', {})
    pre_filled_augments = parsed_data.get('pre_filled_augments', {})
    pre_filled_filigrees = parsed_data.get('pre_filled_filigrees', {})
    max_search_time = parsed_data.get('max_search_time', optimizer.DEFAULT_SEARCH_TIME)

    # DDO_DATA_PATH is set by app.go's runSolver() to the absolute path of the
    # DDOBuilderV2 checkout it maintains (see ensureDDOBuilderData in app.go —
    # clones it into ./DDOBuilderV2 on first run, gitignored). Falling back to
    # the project-relative default keeps `python solver.py` usable directly
    # from a dev checkout, as long as it's run from the project root (the same
    # assumption app.go's own packMappingsPath already makes).
    base_dir = os.environ.get("DDO_DATA_PATH") or "DDOBuilderV2/Output/DataFiles"
    if not os.path.exists(base_dir):
        fail(f"DDOBuilderV2 data directory not found at '{base_dir}'. Set DDO_DATA_PATH, "
             f"or run from the project root after DDOBuilderV2 has been cloned "
             f"(see ensureDDOBuilderData in app.go / install.sh).")

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
        out_file.write(f"Mode: {mode}\n")
        out_file.write(f"Max Search Time: {max_search_time}\n")
        out_file.write(f"Final Priorities: {', '.join(priority_names)}\n")
        out_file.write("Priority Tiers: " + ', '.join(
            f"{e.stat} (T{e.tier}" + (f", cap {int(e.cap)}" if e.cap else "") + ")"
            for e in entries) + "\n")
        out_file.write(f"Armor Restriction: {armor_input or 'None'}\n")
        out_file.write(f"Reserved Minor Artifact Slot: {art_slot_input or 'Any'}\n")
        out_file.write(f"Minor Artifact Filigree Slots: {art_slots}\n")
        out_file.write(f"Allow Gem of Many Facets: {allow_gomf}\n")
        out_file.write(f"Excluded Packs: {', '.join(excluded_packs) if excluded_packs else 'None'}\n")
        out_file.write(f"Raid Item Limit: {raid_item_limit}\n")
        for w in priority_warnings:
            out_file.write(f"WARNING: {w}\n")
        # excluded_packs matching is exact-string against AdventurePack values
        # derived from Quests.xml (see optimizer.parse_items) — a name that
        # doesn't exactly match a real pack silently excludes nothing at all,
        # which is exactly how GitHub issue jorgec/ddogearset#1 happened
        # ("The Chill of Ravenloft" vs the real "Chill of Ravenloft", no
        # "The" prefix). Surfaced via BOTH out_file (the saved-file/debug log)
        # and print() — out_file alone is not enough: Go's RunOptimization
        # only streams the subprocess's stdout (print()) into the Status
        # Console in real time, it never reads gearset_output.txt, so a
        # print()-less warning here would be invisible in the running app.
        if excluded_packs:
            real_packs = {info.get('AdventurePack') for info in quests_lookup.values() if info.get('AdventurePack')}
            for p in excluded_packs:
                if p not in real_packs:
                    msg = (f"WARNING: excluded pack '{p}' does not exactly match any known "
                           f"AdventurePack name — it will exclude nothing. Check for typos "
                           f"or a missing/extra 'The' prefix.")
                    out_file.write(msg + "\n")
                    print(msg)
        out_file.write("\n")

        min_ml = cap - 6 if mode == "stat_search" else 29
        # owned_item_names constrains what the solver may SELECT for a
        # gearset — stat_search is a browse-the-whole-catalog feature (what's
        # possible in the game, not what you own), so it's deliberately
        # exempt regardless of what was loaded via LoadTroveInventory.
        pool_owned_names = owned_item_names if mode != "stat_search" else None
        if pool_owned_names is not None:
            out_file.write(f"Owned-items restriction: {len(pool_owned_names)} names loaded from Trove export\n")
        print(f"\nParsing Items (ML {min_ml}-{cap})...")
        pre_equipped_names = list(pre_equipped.values()) if pre_equipped else []
        if mode == "alternatives":
            pre_equipped_names = list((parsed_data.get('equipped_items') or {}).values())
        items = optimizer.parse_items(base_dir, cap, priority_names, armor_input, w1_list, w2_list, allow_gomf, art_slot_input, excluded_packs, quests_lookup, pre_equipped_names, min_ml=min_ml, owned_names=pool_owned_names)
        print(f"Loaded {len(items)} items")

        print(f"Parsing Augments (ML {min_ml}-{cap})...")
        pre_filled_augment_names = optimizer.flatten_pre_filled_augment_names(pre_filled_augments)
        augments = optimizer.parse_augments(base_dir, cap, priority_names, pre_filled_augment_names, min_ml=min_ml, owned_names=pool_owned_names)
        print(f"Loaded {len(augments)} augments")

        filigrees = []
        if cap >= 34 or mode == "stat_search":
            print(f"Parsing Filigrees...")
            filigrees, filigree_sets = optimizer.parse_filigrees(base_dir, priority_names)
            print(f"Loaded {len(filigrees)} filigrees")
            for k, v in filigree_sets.items():
                if k not in sets:
                    sets[k] = v
                else:
                    for count, buffs in v.items():
                        sets[k][count] = buffs

        if mode == "stat_search":
            results = []
            target_stat = optimizer.normalize_stat_key(priority_names[0])
            
            def add_matches(collection, source_type):
                for item in collection:
                    for buff in item.get('buffs', []):
                        if optimizer.normalize_stat_key(buff[0]) == target_stat:
                            results.append({
                                "sourceType": source_type,
                                "sourceName": item.get('name'),
                                "bonusType": buff[1],
                                "value": buff[2],
                                "ml": item.get('ml', 0),
                                "slots": item.get('slots', []),
                                "pack": item.get('pack')
                            })

            add_matches(items, "item")
            add_matches(augments, "augment")
            add_matches(filigrees, "filigree")

            results.sort(key=lambda x: x['value'], reverse=True)
            print(f"JSON_RESULT:{json.dumps({'stat': priority_names[0], 'results': results})}")
            return

        if mode == "alternatives":
            print("Enumerating slot alternatives...")
            result = run_alternatives(parsed_data, entries, items, sets, augments, filigrees,
                                      derive_required_slots(items), out_file)
            print(f"JSON_RESULT:{json.dumps(result)}")
            if not result.get('success'):
                sys.exit(1)
            return

        print(f"Solving ILP for max level {cap} (this may take a minute)...")
        result = optimizer.run_optimization(
            items, sets, augments, filigrees, entries, out_file, cap, art_slots,
            raid_item_limit, pre_equipped, pre_filled_augments, pre_filled_filigrees,
            mode, max_search_time,
            weapon1_eligible_types=weapon1_eligible_types,
            weapon2_eligible_types=weapon2_eligible_types,
            require_weapon2=require_weapon2)

        if result and result.get('success') is not False:
            final_gearset = result
            print(f"JSON_RESULT:{json.dumps(final_gearset)}")
            print(f"\nSuccess! Results written to {filename}")
        else:
            # Output an explicit failure JSON payload so the Go app knows to abort
            message = (result or {}).get('errorMessage') or (
                'Solver could not find a valid combination of gear that satisfies all of your '
                'constraints. Try clearing some locked items or reducing requirements.')
            print(f"JSON_RESULT:{json.dumps({'success': False, 'errorMessage': message})}")
            print("\nSolver failed to find a feasible solution.")
            sys.exit(1)


if __name__ == "__main__":
    main()
