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
)
from rules.provenance import _all_item_name_drop_locations  # noqa: E402
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
    raw_xml: str
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
    armor_type: Optional[str]
    drop_location: Optional[str]


@dataclass
class RawAugment:
    name: str
    type: str
    raw_xml: str
    buffs: list
    min_level: int


@dataclass
class RawFiligree:
    name: str
    base_name: str
    raw_xml: str
    sets: List[str]        # ALL <SetBonus> values — see note below
    buffs: list


@dataclass
class RawSetTier:
    set_name: str
    piece_count: int
    buffs: list
    # Which DDOBuilderV2 file this came from: 'top_level' (SetBonuses.xml) or
    # 'filigree_file' (a FiligreeSets/*.xml). NOT meaningful game data — it is
    # the SAME kind of tier row either way, and the app-facing schema never
    # needs it — but two historical code paths (parse_sets vs parse_filigrees'
    # second return value) read them from different files, and the Phase 1
    # differential snapshot still tests them as separate keys. Measured on the
    # real corpus: zero overlap in (set_name, piece_count) between the two
    # files, so tagging costs nothing and keeps that proof exact.
    origin_hint: str = "top_level"


@dataclass
class Corpus:
    items: List[RawItem] = field(default_factory=list)
    augments: List[RawAugment] = field(default_factory=list)
    filigrees: List[RawFiligree] = field(default_factory=list)
    set_tiers: List[RawSetTier] = field(default_factory=list)
    quests: Dict[str, dict] = field(default_factory=dict)
    # One <SetBonus> element's raw XML per set NAME (not per tier — the XML
    # element wraps every tier of a set together, which is what GetSetBonus
    # needs to display). Measured zero name overlap between SetBonuses.xml
    # and FiligreeSets/*.xml (same corpus check as origin_hint's), so one
    # entry per name is never ambiguous about which file it came from.
    set_bonus_raw_xml: Dict[str, str] = field(default_factory=dict)


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
                    raw_xml=ET.tostring(item_node, encoding='unicode'),
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
                    # Not part of _item_from_node's return shape (that
                    # extractor is shared with the search, which never needed
                    # these) — read directly off the node and the provenance
                    # tuple this loop already computed.
                    armor_type=item_node.findtext('Armor'),
                    drop_location=provenance[0] or None,
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
                ml_node = aug_node.find('MinLevel')
                ml = int(ml_node.text) if ml_node is not None and ml_node.text else 0
                out.append(RawAugment(
                    name=granted['name'], type=granted['type'],
                    raw_xml=ET.tostring(aug_node, encoding='unicode'),
                    buffs=granted['buffs'], min_level=ml))
            except Exception:
                continue
    return out


def walk_filigrees(base_dir: str):
    """Returns (filigrees, set_tiers_from_filigree_files, set_bonus_raw_xml).

    Filigree files (`FiligreeSets/*.xml`) carry BOTH `<Filigree>` nodes and
    their own `<SetBonus>` tier definitions — parse_filigrees folds the latter
    into the same `sets` dict the top-level SetBonuses.xml populates, so this
    mirrors that. `set_bonus_raw_xml` is one raw-XML capture per set NAME
    (the whole `<SetBonus>` element, every tier) — see Corpus.set_bonus_raw_xml.
    """
    filigrees: List[RawFiligree] = []
    set_tiers: List[RawSetTier] = []
    set_bonus_raw_xml: Dict[str, str] = {}

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
                set_bonus_raw_xml[set_name] = ET.tostring(set_node, encoding='unicode')
                for buff_node in set_node.findall('Buff'):
                    count = buff_node.findtext('EquippedCount')
                    if not count:
                        continue
                    buffs = []
                    for effect_node in buff_node.findall('Effect'):
                        buffs.extend(_effect_buffs_from_node(
                            effect_node, [], keep_unmatched=True, with_raw=True))
                    set_tiers.append(RawSetTier(
                        set_name=set_name, piece_count=int(count), buffs=buffs,
                        origin_hint="filigree_file"))
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
                    raw_xml=ET.tostring(f_node, encoding='unicode'),
                    sets=all_sets, buffs=granted['buffs']))
            except Exception:
                continue

    return filigrees, set_tiers, set_bonus_raw_xml


def walk_set_bonuses(base_dir: str):
    """The top-level SetBonuses.xml — same shape as the filigree-file set tiers
    above, kept as a separate function because it is a separate file with a
    flat (non-repeating) structure. Returns (set_tiers, set_bonus_raw_xml)."""
    out = []
    raw_xml: Dict[str, str] = {}
    try:
        tree = ET.parse(os.path.join(base_dir, 'SetBonuses.xml'))
    except Exception:
        return out, raw_xml

    for set_node in tree.findall('.//SetBonus'):
        try:
            name_node = set_node.find('Type')
            if name_node is None or not name_node.text:
                continue
            set_name = name_node.text
            raw_xml[set_name] = ET.tostring(set_node, encoding='unicode')
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
    return out, raw_xml


def walk_corpus(base_dir: str) -> Corpus:
    quests = ddo_parser.parse_quests(base_dir)
    filigrees, filigree_set_tiers, filigree_set_raw_xml = walk_filigrees(base_dir)
    top_set_tiers, top_set_raw_xml = walk_set_bonuses(base_dir)
    # Zero name overlap measured between the two files (see
    # Corpus.set_bonus_raw_xml's docstring) — union is never ambiguous.
    return Corpus(
        items=walk_items(base_dir, quests),
        augments=walk_augments(base_dir),
        filigrees=filigrees,
        set_tiers=top_set_tiers + filigree_set_tiers,
        quests=quests,
        set_bonus_raw_xml={**top_set_raw_xml, **filigree_set_raw_xml},
    )
