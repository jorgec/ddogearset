"""Catalog-backed replacements for optimizer.py's XML parsers.

Phase 4 of docs/0.5.0/00_ETL_START_HERE.md. Same signatures, same return
shapes, same candidacy semantics as `optimizer.parse_items` /
`parse_augments` / `parse_filigrees` / `parse_sets` — but reading
`catalog.db` instead of walking 8779 XML files.

WHY THIS IS NOT IN `python/rules/`
----------------------------------
Every function here applies SEARCH RESTRICTIONS: the ML window, the armor and
weapon-style filters, excluded packs, owned-items. `python/rules/` is defined
by not knowing those exist (§7 of START_HERE). Candidacy lives with the
search, which is `optimizer.py`'s side of the line — so this module sits
beside it, and imports `rules` for naming exactly as `optimizer` does.

WHAT IS DELIBERATELY PRESERVED
------------------------------
These are bug-for-bug reproductions of the XML versions, because the Phase 1
differential snapshot proves them equal and that proof is the whole point:

* `parse_sets` / `parse_filigrees` build the full dict SKELETON (every set,
  every piece_count bucket) BEFORE filtering effects by priority, so a set
  whose effects all filter out still appears with empty buckets. Emitting only
  surviving rows drops 190 of 263 sets — measured, not theorised.
* A filigree's `set` is its FIRST `<SetBonus>` only, matching
  `findtext('SetBonus')`. The catalog stores every membership in
  `filigree_set`; this reader takes `position = 0` to stay identical. The
  richer data is there for whoever wants it (0.5.1), it just is not exposed
  through this compatibility surface.
* `effect_target.position = 0` throughout, matching the extractors'
  first-`<Item>`-only behaviour (decision 8, still open).
"""

from __future__ import annotations

import os
import sqlite3
from typing import Dict, List, Optional

from rules.constants import (
    PROC_AUGMENT_ALIASES, PROC_BONUS_TYPE, PROC_ZERO_EFFECT_AUGMENT_NAMES,
    WEAPON_BASE_STATS,
)
from rules.extract import wanted_weapon_stats_for
from rules.naming import _is_proc_presence_flag_type, _proc_priority_match, normalize_stat_name

# Set by app.go (replacing DDO_DATA_PATH). Falls back to a dev-local build so
# `python solver.py` keeps working from a checkout, mirroring how base_dir
# resolution worked before.
CATALOG_ENV_VAR = "DDO_CATALOG_DB"
_DEFAULT_CATALOG = "catalog.db"


def catalog_path() -> str:
    return os.environ.get(CATALOG_ENV_VAR) or _DEFAULT_CATALOG


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    """Read-only, immutable. `immutable=1` is honest — nothing writes the
    catalog while the app runs — and lets SQLite skip locking entirely
    (START_HERE §5.2.3)."""
    p = path or catalog_path()
    if not os.path.exists(p):
        raise FileNotFoundError(
            f"catalog not found at {p!r}. Set {CATALOG_ENV_VAR}, or build one "
            f"with `python -m etl` (see docs/0.5.0/00_ETL_START_HERE.md)."
        )
    return sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)


def _buff(raw_type, raw_target, bonus_type, value, priorities, wanted_weapon_stats=None):
    """One (stat, bonus_type, value) triple, or None if no priority claims it.

    Weapon base stats are a SPECIAL CASE, not a substring match: §15.2 says
    they "are matched by exact element name in parse_items and must never go
    through the substring heuristic" — `normalize_stat_name` has an explicit
    guard skipping them (`if p_clean in WEAPON_BASE_STATS: continue`) for
    exactly this reason. `_weapon_base_buffs` looks them up in
    `wanted_weapon_stats` (built once per call by `wanted_weapon_stats_for`) by
    exact canonical name, never by substring. The catalog stores the raw
    canonical name as `raw_type` (walk.py tags weapon buffs `(s, None)` where
    `s` IS the canonical name), so the same exact-lookup is reproduced here —
    routing this through normalize_stat_name instead was the one real bug
    Phase 4's snapshot comparison caught.
    """
    if raw_type in WEAPON_BASE_STATS:
        if not wanted_weapon_stats:
            return None
        user_name = wanted_weapon_stats.get(raw_type)
        if not user_name:
            return None
        return (user_name, bonus_type.strip() if bonus_type else bonus_type, value)

    if bonus_type == PROC_BONUS_TYPE and _is_proc_presence_flag_type(raw_type):
        proc_stat = _proc_priority_match(raw_type, priorities)
        if not proc_stat:
            return None
        return (proc_stat, PROC_BONUS_TYPE, 1.0)

    stat = normalize_stat_name(raw_type, raw_target, "", priorities,
                               bonus_type=bonus_type)
    if not stat:
        return None
    return (stat, bonus_type.strip() if bonus_type else bonus_type, value)


def _load_items(conn) -> Dict[str, dict]:
    items: Dict[str, dict] = {}
    for (uuid_, name, source_file, ml, weapon_type, damage_type, armor_type,
         is_minor, is_raid, craftable_family, pack) in conn.execute("""
        SELECT uuid, name, source_file, min_level, weapon_type, damage_type,
               armor_type, is_minor_artifact, is_raid, craftable_family,
               adventure_pack
        FROM item
    """):
        items[uuid_] = {
            'name': name, 'file': source_file, 'ml': ml,
            'weapon_type': weapon_type, 'damage_type': damage_type,
            'armor_type': armor_type, 'minor': bool(is_minor),
            'is_raid': bool(is_raid), 'craftable_family': bool(craftable_family),
            'pack': pack, 'slots': [], 'augments': [], 'sets': [], 'raw_buffs': [],
        }

    for item_uuid, slot in conn.execute("SELECT item_uuid, slot FROM item_slot"):
        items[item_uuid]['slots'].append(slot)
    for item_uuid, colour in conn.execute(
            "SELECT item_uuid, colour FROM item_augment_slot ORDER BY item_uuid, position"):
        items[item_uuid]['augments'].append(colour)
    for item_uuid, set_name in conn.execute("""
        SELECT its.item_uuid, gs.name FROM item_set its
        JOIN gear_set gs ON gs.uuid = its.set_uuid
    """):
        items[item_uuid]['sets'].append(set_name)
    for item_uuid, bonus_type, value, raw_type, raw_target in conn.execute("""
        SELECT ef.source_uuid, ef.bonus_type, ef.value, s.raw_type, s.raw_target
        FROM effect ef
        JOIN effect_target et ON et.effect_uuid = ef.uuid AND et.position = 0
        JOIN stat s ON s.uuid = et.stat_uuid
        JOIN source src ON src.uuid = ef.source_uuid AND src.kind = 'item'
        ORDER BY ef.source_uuid, ef.ordinal
    """):
        items[item_uuid]['raw_buffs'].append((raw_type, raw_target, bonus_type, value))
    return items


def parse_items(catalog, max_ml, priorities, allowed_armor, allowed_w1_list,
                allowed_w2_list, allow_gomf, art_slot_input, excluded_packs=None,
                pre_equipped_names=None, min_ml=29, owned_names=None) -> List[dict]:
    """Candidacy is byte-for-byte optimizer.parse_items'. `quests_lookup` is
    gone from the signature: adventure pack and raid status are columns now,
    resolved once at ETL time rather than per-run."""
    conn = catalog if isinstance(catalog, sqlite3.Connection) else connect(catalog)
    try:
        raw_items = _load_items(conn)
    finally:
        if not isinstance(catalog, sqlite3.Connection):
            conn.close()

    allowed_armor = allowed_armor.strip().lower() if allowed_armor else None
    wanted_weapon_stats = wanted_weapon_stats_for(priorities)

    force_dino = False
    if art_slot_input:
        art_slot_input = art_slot_input.lower().strip()
        if '(dino)' in art_slot_input:
            force_dino = True
            art_slot_input = art_slot_input.replace('(dino)', '').strip()

    out = []
    for it in raw_items.values():
        name = it['name']
        is_pre_equipped = pre_equipped_names and name in pre_equipped_names

        if not is_pre_equipped:
            if it['ml'] < min_ml or it['ml'] > max_ml:
                continue
            if not allow_gomf and "Gem of Many Facets" in name:
                continue

        weapon_type = it['weapon_type']
        is_minor = it['minor']
        slots = list(it['slots'])
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

            armor_type = it['armor_type']
            if 'Armor' in slots and allowed_armor:
                if not armor_type or allowed_armor not in armor_type.strip().lower():
                    slots.remove('Armor')

        if not slots:
            slots = original_slots if is_pre_equipped else []
            if not slots:
                continue

        if not is_pre_equipped and excluded_packs and it['pack'] in excluded_packs:
            continue
        if not is_pre_equipped and owned_names is not None and name not in owned_names:
            continue

        buffs = []
        for raw_type, raw_target, bonus_type, value in it['raw_buffs']:
            b = _buff(raw_type, raw_target, bonus_type, value, priorities,
                     wanted_weapon_stats=wanted_weapon_stats)
            if b:
                buffs.append(b)

        out.append({
            'name': name, 'file': it['file'], 'slots': slots, 'buffs': buffs,
            'sets': it['sets'], 'augments': it['augments'], 'minor': is_minor,
            'is_raid': it['is_raid'], 'pack': it['pack'], 'ml': it['ml'],
            'weapon_type': weapon_type, 'damage_type': it['damage_type'],
            'craftable_family': it['craftable_family'],
        })
    return out


def parse_augments(catalog, max_ml, priorities, pre_filled_augment_names=None,
                   min_ml=29, owned_names=None) -> List[dict]:
    conn = catalog if isinstance(catalog, sqlite3.Connection) else connect(catalog)
    try:
        augs: Dict[str, dict] = {}
        for uuid_, name, colour, ml in conn.execute(
                "SELECT uuid, name, colour, min_level FROM augment"):
            augs[uuid_] = {'name': name, 'type': colour, 'ml': ml, 'raw_buffs': []}
        for aug_uuid, bonus_type, value, raw_type, raw_target in conn.execute("""
            SELECT ef.source_uuid, ef.bonus_type, ef.value, s.raw_type, s.raw_target
            FROM effect ef
            JOIN effect_target et ON et.effect_uuid = ef.uuid AND et.position = 0
            JOIN stat s ON s.uuid = et.stat_uuid
            JOIN source src ON src.uuid = ef.source_uuid AND src.kind = 'augment'
            ORDER BY ef.source_uuid, ef.ordinal
        """):
            augs[aug_uuid]['raw_buffs'].append((raw_type, raw_target, bonus_type, value))
    finally:
        if not isinstance(catalog, sqlite3.Connection):
            conn.close()

    pre_filled_augment_names = set(pre_filled_augment_names or [])
    out = []
    for a in augs.values():
        name = a['name']
        is_pre_filled = name in pre_filled_augment_names
        if not is_pre_filled and (a['ml'] < min_ml or a['ml'] > max_ml):
            continue
        if not is_pre_filled and owned_names is not None and name not in owned_names:
            continue

        buffs = []
        for raw_type, raw_target, bonus_type, value in a['raw_buffs']:
            b = _buff(raw_type, raw_target, bonus_type, value, priorities)
            if b:
                buffs.append(b)

        # Shape B — see _augment_from_node's comment in rules/extract.py.
        name_lower = name.strip().lower()
        has_proc = any(b[1] == PROC_BONUS_TYPE for b in buffs)
        if not has_proc and name_lower in PROC_ZERO_EFFECT_AUGMENT_NAMES:
            proc_stat = _proc_priority_match(name, priorities)
            if proc_stat:
                buffs.append((proc_stat, PROC_BONUS_TYPE, 1.0))
                has_proc = True

        # Aliased augments — see PROC_AUGMENT_ALIASES in constants.py.
        if not has_proc:
            alias_proc = PROC_AUGMENT_ALIASES.get(name_lower)
            if alias_proc:
                proc_stat = _proc_priority_match(alias_proc, priorities)
                if proc_stat:
                    buffs.append((proc_stat, PROC_BONUS_TYPE, 1.0))

        if buffs or is_pre_filled:
            out.append({'name': name, 'type': a['type'], 'buffs': buffs})
    return out


def _load_tiers(conn, origin_hint: str, priorities) -> Dict[str, Dict[int, list]]:
    """{set_name: {piece_count: [(stat, bonus, value), ...]}}.

    The skeleton is materialised BEFORE effects are filtered — see this
    module's docstring. `origin_hint` distinguishes SetBonuses.xml tiers from
    per-filigree-file tiers, which the two XML parsers read separately.
    """
    sets: Dict[str, Dict[int, list]] = {}
    for set_name, piece_count in conn.execute("""
        SELECT gs.name, st.piece_count FROM set_tier st
        JOIN gear_set gs ON gs.uuid = st.set_uuid
        WHERE st.origin_hint = ?
        ORDER BY gs.name, st.piece_count
    """, (origin_hint,)):
        sets.setdefault(set_name, {}).setdefault(piece_count, [])

    for set_name, piece_count, bonus_type, value, raw_type, raw_target in conn.execute("""
        SELECT gs.name, st.piece_count, ef.bonus_type, ef.value, s.raw_type, s.raw_target
        FROM set_tier st
        JOIN gear_set gs ON gs.uuid = st.set_uuid
        JOIN effect ef ON ef.source_uuid = st.uuid
        JOIN effect_target et ON et.effect_uuid = ef.uuid AND et.position = 0
        JOIN stat s ON s.uuid = et.stat_uuid
        WHERE st.origin_hint = ?
        ORDER BY gs.name, st.piece_count, ef.ordinal
    """, (origin_hint,)):
        b = _buff(raw_type, raw_target, bonus_type, value, priorities)
        if b:
            sets[set_name][piece_count].append(b)
    return sets


def parse_sets(catalog, priorities) -> Dict[str, Dict[int, list]]:
    conn = catalog if isinstance(catalog, sqlite3.Connection) else connect(catalog)
    try:
        return _load_tiers(conn, "top_level", priorities)
    finally:
        if not isinstance(catalog, sqlite3.Connection):
            conn.close()


def parse_filigrees(catalog, priorities):
    conn = catalog if isinstance(catalog, sqlite3.Connection) else connect(catalog)
    try:
        sets = _load_tiers(conn, "filigree_file", priorities)

        fils: Dict[str, dict] = {}
        for uuid_, name, base_name in conn.execute("""
            SELECT f.uuid, f.name, fb.name FROM filigree f
            JOIN filigree_base fb ON fb.uuid = f.base_uuid
        """):
            fils[uuid_] = {'name': name, 'base_name': base_name,
                          'set': None, 'buffs': []}
        # position = 0 only: findtext('SetBonus') parity. See module docstring.
        for fil_uuid, set_name in conn.execute("""
            SELECT fs.filigree_uuid, gs.name FROM filigree_set fs
            JOIN gear_set gs ON gs.uuid = fs.set_uuid
            WHERE fs.position = 0
        """):
            fils[fil_uuid]['set'] = set_name
        for fil_uuid, bonus_type, value, raw_type, raw_target in conn.execute("""
            SELECT ef.source_uuid, ef.bonus_type, ef.value, s.raw_type, s.raw_target
            FROM effect ef
            JOIN effect_target et ON et.effect_uuid = ef.uuid AND et.position = 0
            JOIN stat s ON s.uuid = et.stat_uuid
            JOIN source src ON src.uuid = ef.source_uuid AND src.kind = 'filigree'
            ORDER BY ef.source_uuid, ef.ordinal
        """):
            b = _buff(raw_type, raw_target, bonus_type, value, priorities)
            if b:
                fils[fil_uuid]['buffs'].append(b)

        return [f for f in fils.values() if f['buffs']], sets
    finally:
        if not isinstance(catalog, sqlite3.Connection):
            conn.close()


def known_adventure_pack_names(catalog) -> set:
    """Every AdventurePack name any item in the catalog actually carries.

    Replaces the old quests_lookup-derived `real_packs` set (solver.py used to
    build this by walking Quests.xml at request time); the catalog's
    `item.adventure_pack` column already holds the SAME resolved value — it
    was computed from Quests.xml once, at ETL time (walk.py's
    `_item_provenance`), not rederived per request. Used only to validate an
    `excluded_packs` entry actually matches something real (proposal:
    docs/0.5.0/00_ETL_START_HERE.md — the "Chill of Ravenloft" typo warning).
    """
    conn = catalog if isinstance(catalog, sqlite3.Connection) else connect(catalog)
    try:
        rows = conn.execute(
            "SELECT DISTINCT adventure_pack FROM item WHERE adventure_pack IS NOT NULL")
        return {r[0] for r in rows}
    finally:
        if not isinstance(catalog, sqlite3.Connection):
            conn.close()


# --- Recalculation: resolve a gearset the user already has -------------------
#
# 0.5.1 Phase 4. Everything above answers "what COULD go in this slot" and is
# shaped by the search restrictions that question needs. These answer "what IS
# in this slot", which needs none of them — no ML window, no armor filter, no
# excluded packs, no owned-items list, no candidate pool at all.
#
# That is the whole reason recalculation moved: a restriction is a statement
# about what the solver may PROPOSE, and applying one while evaluating gear the
# user already owns is how `mode: "calculate"` ended up refusing to answer for a
# real gearset (see python/tests/fixtures/known_deltas.yaml). Here there is
# nowhere to put one.

def resolve_equipped_items(catalog, names, priorities):
    """Items by exact name. `WHERE name IN (...)` — no glob, no XML, no pool.

    Returns (by_name, missing). A name with no row is REPORTED, not fatal: a
    gearset saved two game updates ago can legitimately reference an item that
    has since been removed, and the other thirteen slots still have answers.
    """
    conn = catalog if isinstance(catalog, sqlite3.Connection) else connect(catalog)
    try:
        wanted = [n for n in dict.fromkeys(names) if (n or '').strip()]
        if not wanted:
            return {}, []
        wanted_weapon_stats = wanted_weapon_stats_for(priorities)

        raw_items = _load_items(conn)
        by_name = {}
        for it in raw_items.values():
            if it['name'] not in wanted:
                continue
            buffs = []
            for raw_type, raw_target, bonus_type, value in it['raw_buffs']:
                b = _buff(raw_type, raw_target, bonus_type, value, priorities,
                          wanted_weapon_stats=wanted_weapon_stats)
                if b:
                    buffs.append(b)
            by_name[it['name']] = {
                'name': it['name'], 'file': it['file'], 'slots': list(it['slots']),
                'buffs': buffs, 'sets': it['sets'], 'augments': it['augments'],
                'minor': it['minor'], 'is_raid': it['is_raid'], 'pack': it['pack'],
                'ml': it['ml'], 'weapon_type': it['weapon_type'],
                'damage_type': it['damage_type'],
                'craftable_family': it['craftable_family'],
            }
        missing = [n for n in wanted if n not in by_name]
        return by_name, missing
    finally:
        if not isinstance(catalog, sqlite3.Connection):
            conn.close()


def resolve_equipped_augments(catalog, names, priorities):
    """Augments by exact name, with no ML window.

    Name alone is ambiguous for a handful of augments (the catalog has two
    called "Deathblock", in different colour slots — see etl/transform.py). A
    saved gearset records the colour it was slotted in, so a caller that has one
    should prefer it; this returns every match keyed by name and lets the caller
    disambiguate, rather than silently picking one.
    """
    conn = catalog if isinstance(catalog, sqlite3.Connection) else connect(catalog)
    try:
        wanted = {n for n in names if (n or '').strip()}
        if not wanted:
            return {}, []
        out = {}
        for aug in parse_augments(conn, 999, priorities, pre_filled_augment_names=list(wanted),
                                  min_ml=0):
            if aug['name'] in wanted:
                out.setdefault(aug['name'], []).append(aug)
        missing = sorted(n for n in wanted if n not in out)
        return out, missing
    finally:
        if not isinstance(catalog, sqlite3.Connection):
            conn.close()


def resolve_equipped_filigrees(catalog, names, priorities):
    """Filigrees by exact name, plus the set tiers they can activate."""
    conn = catalog if isinstance(catalog, sqlite3.Connection) else connect(catalog)
    try:
        fils, filigree_sets = parse_filigrees(conn, priorities)
        by_name = {f['name']: f for f in fils}
        wanted = [n for n in names if (n or '').strip()]
        missing = sorted({n for n in wanted if n not in by_name})
        return by_name, filigree_sets, missing
    finally:
        if not isinstance(catalog, sqlite3.Connection):
            conn.close()


def priorities_with_no_source(catalog, priorities):
    """Priority names that nothing in the CATALOG grants.

    The solve path answered this from its candidate pool, so a stat that existed
    but had been filtered out looked identical to a typo. Asking the catalog
    instead makes it the question it was always meant to be: does anything in
    the game grant this at all?

    Bonus type is part of the question, not decoration. A priority like
    "insightful spell focus mastery" names a stat AND the bonus type that has to
    carry it, so testing every stat against one hardcoded bonus type reports
    every bonus-type-prefixed priority as unmatched — which is exactly what a
    first version of this did, and what the oracle differential caught.
    """
    conn = catalog if isinstance(catalog, sqlite3.Connection) else connect(catalog)
    try:
        wanted_weapon_stats = wanted_weapon_stats_for(priorities)
        remaining = list(priorities)
        matched = set()
        for raw_type, raw_target, bonus_type in conn.execute("""
            SELECT DISTINCT s.raw_type, s.raw_target, e.bonus_type
              FROM effect_target t
              JOIN stat s   ON s.uuid = t.stat_uuid
              JOIN effect e ON e.uuid = t.effect_uuid
        """):
            if not remaining:
                break
            still = []
            for p in remaining:
                if _buff(raw_type, raw_target, bonus_type, 1.0, [p],
                         wanted_weapon_stats=wanted_weapon_stats):
                    matched.add(p)
                else:
                    still.append(p)
            remaining = still
        return [p for p in priorities if p not in matched]
    finally:
        if not isinstance(catalog, sqlite3.Connection):
            conn.close()
