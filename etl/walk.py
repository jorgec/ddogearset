"""Restriction-free corpus walkers — the ETL's Extract stage.

Deliberately does NOT call `optimizer.parse_items` / `parse_augments` /
`parse_filigrees`. Those functions have search restrictions (ML window, armor
filter, pack exclusion, owned-items) baked into their signatures, and calling
them with "neutral" arguments (max_ml=999, allowed_armor=None, ...) is exactly
the "passed but ignored" failure mode
docs/0.5.0/00_ETL_START_HERE.md warns about: a restriction silently starts
being honoured again the moment someone edits a default.

Instead this module calls `rules.extract`'s per-node functions directly, with
`keep_unmatched=True` and no candidacy filter at all. There is no restriction
parameter anywhere in this file for the same reason there is none in the
`recalculate` payload (docs/0.5.0/00_ETL_START_HERE.md §7): if it cannot be
expressed, it cannot be silently reinstated.
"""

from __future__ import annotations

import glob
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "python"))

import parser as ddo_parser  # noqa: E402
from rules.extract import (  # noqa: E402
    _augment_from_node,
    _effect_buffs_from_node,
    _filigree_from_node,
    _item_from_node,
    _item_provenance,
    _item_slots_from_node,
    wanted_weapon_stats_for,
)
from rules.provenance import _all_item_name_drop_locations, _resolve_is_raid  # noqa: E402
from rules.constants import WEAPON_BASE_STATS  # noqa: E402

# Every priority ever needed by the catalog is "everything" — keep_unmatched
# handles the actual unmatched case, but normalize_stat_name still needs SOME
# vocabulary to test against for the stats that DO have a canonical spelling,
# so it produces sensible fallback `otherStats`-style names at query time too.
# Passing the full weapon-stat vocabulary here means _weapon_base_buffs is
# never starved by a caller-specific projection (see wanted_weapon_stats_for).
_ALL_WEAPON_STATS = {s: s for s in WEAPON_BASE_STATS}


@dataclass
class RawItem:
    node_name: str
    file: str
    slots: List[str]
    buffs: list
    sets: List[str]
    augment_slots: List[str]           # ItemAugment <Type> values, in XML order
    minor: bool
    is_raid: bool
    pack: Optional[str]
    ml: int
    weapon_type: Optional[str]
    damage_type: Optional[str]
    craftable_family: bool


@dataclass
class RawAugment:
    name: str
    type: str
    buffs: list


@dataclass
class RawFiligree:
    name: str
    base_name: str
    sets: List[str]        # ALL <SetBonus> values — see note below
    buffs: list


@dataclass
class RawSetTier:
    set_name: str
    piece_count: int
    buffs: list


@dataclass
class Corpus:
    items: List[RawItem] = field(default_factory=list)
    augments: List[RawAugment] = field(default_factory=list)
    filigrees: List[RawFiligree] = field(default_factory=list)
    set_tiers: List[RawSetTier] = field(default_factory=list)
    quests: Dict[str, dict] = field(default_factory=dict)


def walk_items(base_dir: str, quests_lookup: dict) -> List[RawItem]:
    raid_names = frozenset(
        qname for qname, qinfo in quests_lookup.items() if qinfo.get('is_raid'))
    raid_all_drop_locations = _all_item_name_drop_locations(base_dir)
    raid_memo: dict = {}
    out = []

    for item_file in glob.glob(os.path.join(base_dir, 'Items', '*.item')):
        try:
            tree = ET.parse(item_file)
        except Exception:
            continue
        for item_node in tree.getroot().findall('.//Item'):
            try:
                slots = _item_slots_from_node(item_node)
                if not slots:
                    continue
                name = item_node.findtext('Name') or 'Unknown'
                provenance = _item_provenance(
                    item_node, name, quests_lookup, raid_names,
                    raid_all_drop_locations, raid_memo)
                granted = _item_from_node(
                    item_node, item_file, slots, [], _ALL_WEAPON_STATS,
                    provenance, keep_unmatched=True, with_raw=True)
                out.append(RawItem(
                    node_name=granted['name'],
                    file=granted['file'],
                    slots=granted['slots'],
                    buffs=granted['buffs'],
                    sets=granted['sets'],
                    augment_slots=granted['augments'],
                    minor=granted['minor'],
                    is_raid=granted['is_raid'],
                    pack=granted['pack'],
                    ml=granted['ml'],
                    weapon_type=granted['weapon_type'],
                    damage_type=granted['damage_type'],
                    craftable_family=granted['craftable_family'],
                ))
            except Exception:
                # A single malformed node must not abort the whole build; it
                # will simply be absent from the catalog. Consistent with
                # parse_items' own per-file exception handling.
                continue
    return out


def walk_augments(base_dir: str) -> List[RawAugment]:
    out = []
    for aug_file in glob.glob(os.path.join(base_dir, 'Augments', '*.xml')):
        try:
            tree = ET.parse(aug_file)
        except Exception:
            continue
        for aug_node in tree.findall('.//Augment'):
            try:
                granted = _augment_from_node(aug_node, [], keep_unmatched=True,
                                             with_raw=True)
                if granted is None:
                    continue
                out.append(RawAugment(
                    name=granted['name'], type=granted['type'],
                    buffs=granted['buffs']))
            except Exception:
                continue
    return out


def walk_filigrees(base_dir: str):
    """Returns (filigrees, set_tiers_from_filigree_files).

    Filigree files (`FiligreeSets/*.xml`) carry BOTH `<Filigree>` nodes and
    their own `<SetBonus>` tier definitions — parse_filigrees folds the latter
    into the same `sets` dict the top-level SetBonuses.xml populates, so this
    mirrors that.
    """
    filigrees: List[RawFiligree] = []
    set_tiers: List[RawSetTier] = []

    for xml_file in glob.glob(os.path.join(base_dir, 'FiligreeSets', '*.xml')):
        try:
            tree = ET.parse(xml_file)
        except Exception:
            continue

        for set_node in tree.findall('.//SetBonus'):
            try:
                name_node = set_node.find('Type')
                if name_node is None or not name_node.text:
                    continue
                set_name = name_node.text
                for buff_node in set_node.findall('Buff'):
                    count = buff_node.findtext('EquippedCount')
                    if not count:
                        continue
                    buffs = []
                    for effect_node in buff_node.findall('Effect'):
                        buffs.extend(_effect_buffs_from_node(
                            effect_node, [], keep_unmatched=True, with_raw=True))
                    set_tiers.append(RawSetTier(
                        set_name=set_name, piece_count=int(count), buffs=buffs))
            except Exception:
                continue

        for f_node in tree.findall('.//Filigree'):
            try:
                granted = _filigree_from_node(f_node, [], keep_unmatched=True,
                                              with_raw=True)
                # THE dual-set fix (schema doc §2.3): findtext('SetBonus') in
                # _filigree_from_node keeps only the first membership.
                # Re-derive ALL of them here — this is exactly the case the
                # ETL exists to fix structurally, so it must not inherit the
                # first-wins loss from the shared extractor.
                all_sets = [s.text.strip() for s in f_node.findall('SetBonus')
                           if s.text and s.text.strip()]
                filigrees.append(RawFiligree(
                    name=granted['name'], base_name=granted['base_name'],
                    sets=all_sets, buffs=granted['buffs']))
            except Exception:
                continue

    return filigrees, set_tiers


def walk_set_bonuses(base_dir: str) -> List[RawSetTier]:
    """The top-level SetBonuses.xml — same shape as the filigree-file set tiers
    above, kept as a separate function because it is a separate file with a
    flat (non-repeating) structure."""
    out = []
    try:
        tree = ET.parse(os.path.join(base_dir, 'SetBonuses.xml'))
    except Exception:
        return out

    for set_node in tree.findall('.//SetBonus'):
        try:
            name_node = set_node.find('Type')
            if name_node is None or not name_node.text:
                continue
            set_name = name_node.text
            for buff_node in set_node.findall('Buff'):
                count = buff_node.findtext('EquippedCount')
                if not count:
                    continue
                buffs = []
                for effect_node in buff_node.findall('Effect'):
                    buffs.extend(_effect_buffs_from_node(
                        effect_node, [], keep_unmatched=True, with_raw=True))
                out.append(RawSetTier(
                    set_name=set_name, piece_count=int(count), buffs=buffs))
        except Exception:
            continue
    return out


def walk_corpus(base_dir: str) -> Corpus:
    quests = ddo_parser.parse_quests(base_dir)
    filigrees, filigree_set_tiers = walk_filigrees(base_dir)
    return Corpus(
        items=walk_items(base_dir, quests),
        augments=walk_augments(base_dir),
        filigrees=filigrees,
        set_tiers=walk_set_bonuses(base_dir) + filigree_set_tiers,
        quests=quests,
    )
